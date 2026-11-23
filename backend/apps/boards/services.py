from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.core import events, softdelete
from apps.core.errors import Conflict, ValidationFailed
from apps.issues.models import Issue, IssueType
from apps.projects.models import Perm, Project
from apps.projects.permissions import require
from apps.workflows.models import StatusCategory

from .models import Board, BoardColumn, Sprint, SprintScopeChange

# --------------------------------------------------------------------------- boards

def create_default_board(project: Project, owner) -> Board:
    kind = Board.Kind.KANBAN if project.template == Project.Template.KANBAN else Board.Kind.SCRUM
    board = Board.objects.create(
        name=f"Tablero {project.key}", kind=kind, project=project, owner=owner,
        card_fields=["issue_type", "key", "priority", "assignee", "story_points", "epic"],
    )
    reset_columns_from_workflow(board)
    return board


def reset_columns_from_workflow(board: Board) -> None:
    board.columns.all().delete()
    statuses = board.project.workflow.ordered_statuses()
    for pos, status in enumerate(statuses):
        col = BoardColumn.objects.create(board=board, name=status.name, position=pos)
        col.statuses.add(status)


def sync_columns_with_workflow(board: Board) -> None:
    """Give every status of the project's workflow a column (appended at the end) without
    touching the existing ones. Used on restore: workflow edits made while the board was in
    the papelera only reached the active boards."""
    statuses = board.project.workflow.ordered_statuses()
    mapped = set(BoardColumn.statuses.through.objects.filter(boardcolumn__board=board)
                 .values_list("status_id", flat=True))
    pos = (board.columns.aggregate(m=Max("position"))["m"] or 0) + 1
    for status in statuses:
        if status.id not in mapped:
            col = BoardColumn.objects.create(board=board, name=status.name[:60], position=pos)
            col.statuses.add(status)
            pos += 1


# --------------------------------------------------------------------------- papelera
#
# Decisions (documented in FASE3.md):
# * Soft delete keeps columns, quick filters and sprints untouched → restore brings them back.
# * A board with an ACTIVE sprint cannot be deleted (409 ``active_sprint``): complete it first.
#   Its future sprints stay frozen with it; their open issues show up in the backlog of the
#   project's other boards (see ``backlog_issues``) and go back to their sprint on restore.
# * Like Jira (company-managed projects), deleting the last board is allowed: a project can
#   live without boards (Lista / Incidencias / Informes de flujo; «Crear tablero» in the UI).
# * Permanent delete (system admin) → 409 ``protected`` while any sprint holds issues (current
#   or closed-sprint history). Empty sprints are purged with the board.

def _ensure_deletable(board: Board) -> None:
    active = board.sprints.filter(state=Sprint.State.ACTIVE).first()
    if active is not None:
        raise Conflict(f"Completa el sprint activo «{active.name}» antes de eliminar el tablero",
                       code="active_sprint", details={"sprint_id": active.id})


def board_changed(actor, board: Board) -> None:
    events.publish_project(board.project_id, "project.updated", {"board_id": board.id},
                           actor_id=actor.id)
    events.publish_project(board.project_id, "sprint.changed", {"board_id": board.id},
                           actor_id=actor.id)


@transaction.atomic
def soft_delete_board(actor, board: Board) -> None:
    require(actor, board.project, Perm.ADMINISTER)
    _ensure_deletable(board)
    board.soft_delete()
    board_changed(actor, board)


def sprints_with_issues(board: Board) -> int:
    closed = Issue.closed_sprints.through.objects.filter(sprint__board=board).values(
        "sprint_id")
    return (Sprint.objects.filter(board=board)
            .filter(Q(issues__isnull=False) | Q(id__in=closed)).distinct().count())


@transaction.atomic
def purge_board(actor, board: Board) -> None:
    """Hard delete (system admin). Works on active boards and on the papelera."""
    softdelete.require_system_admin(actor, "Solo los administradores pueden borrar "
                                           "definitivamente")
    if not board.is_deleted:
        require(actor, board.project, Perm.ADMINISTER)
        _ensure_deletable(board)
    n = sprints_with_issues(board)
    if n:
        usages = [(n, "sprint con incidencias", "sprints con incidencias")]
        raise Conflict(softdelete.usage_message(usages), code="protected",
                       details=softdelete.usage_details(usages))
    project_id, board_id = board.project_id, board.id
    board.delete()
    events.publish_project(project_id, "project.updated", {"board_id": board_id},
                           actor_id=actor.id)


@transaction.atomic
def restore_board(actor, board: Board) -> Board:
    require(actor, board.project, Perm.ADMINISTER)
    softdelete.restore(board)
    sync_columns_with_workflow(board)
    board_changed(actor, board)
    return board


def board_issue_queryset(board: Board):
    qs = Issue.objects.filter(project=board.project, is_archived=False)
    if board.filter_jql.strip():
        from apps.search.jql import compile_jql

        qs = qs.filter(compile_jql(board.filter_jql, project=board.project).q)
    return qs


def board_issues(board: Board, *, sprint: Sprint | None = None, extra_q: Q | None = None):
    """Issues shown on the board view (active sprint for scrum, all/not-old-done for kanban)."""
    status_ids = list(
        BoardColumn.statuses.through.objects.filter(boardcolumn__board=board)
        .values_list("status_id", flat=True)
    )
    qs = board_issue_queryset(board).filter(status_id__in=status_ids)
    if board.kind == Board.Kind.SCRUM:
        if sprint is None:
            return qs.none()
        qs = qs.filter(sprint=sprint)
    else:
        if board.hide_done_after_days:
            cutoff = timezone.now() - timedelta(days=board.hide_done_after_days)
            qs = qs.exclude(status__category=StatusCategory.DONE, resolved_at__lt=cutoff)
    qs = qs.exclude(issue_type__level=IssueType.Level.EPIC)
    if extra_q is not None:
        qs = qs.filter(extra_q)
    return qs


def backlog_issues(board: Board):
    """Not-done, non-epic issues without an open sprint. Issues planned in a (future) sprint
    of a board in the papelera count as backlog too, so they never become unreachable."""
    return (
        board_issue_queryset(board)
        .exclude(issue_type__level=IssueType.Level.EPIC)
        .exclude(issue_type__level=IssueType.Level.SUBTASK)
        .filter(Q(sprint__isnull=True) | Q(sprint__state=Sprint.State.CLOSED)
                | Q(sprint__board__deleted_at__isnull=False))
        .exclude(status__category=StatusCategory.DONE)
    )


# --------------------------------------------------------------------------- sprints

def _estimate(issue: Issue, board: Board) -> Decimal:
    if board.estimation == Board.Estimation.ISSUE_COUNT:
        return Decimal(1)
    if board.estimation == Board.Estimation.ORIGINAL_ESTIMATE:
        return Decimal(issue.original_estimate or 0) / Decimal(3600)
    return issue.story_points or Decimal(0)


@transaction.atomic
def create_sprint(actor, board: Board, name: str | None = None, goal: str = "",
                  start_date=None, end_date=None) -> Sprint:
    require(actor, board.project, Perm.MANAGE_SPRINTS)
    if board.kind != Board.Kind.SCRUM:
        raise ValidationFailed("Los sprints solo existen en tableros Scrum")
    pos = (board.sprints.aggregate(m=Max("position"))["m"] or 0) + 1
    count = board.sprints.count() + 1
    sprint = Sprint.objects.create(
        board=board, name=(name or f"{board.project.key} Sprint {count}")[:80], goal=goal,
        start_date=start_date, end_date=end_date, position=pos,
    )
    events.publish_project(board.project_id, "sprint.changed", {"id": sprint.id},
                           actor_id=actor.id)
    return sprint


@transaction.atomic
def update_sprint(actor, sprint: Sprint, **fields) -> Sprint:
    require(actor, sprint.board.project, Perm.MANAGE_SPRINTS)
    if sprint.state == Sprint.State.CLOSED:
        raise ValidationFailed("No se puede editar un sprint cerrado")
    for k in ("name", "goal", "start_date", "end_date"):
        if k in fields:
            setattr(sprint, k, fields[k])
    if not sprint.name.strip():
        raise ValidationFailed("El nombre es obligatorio")
    if sprint.start_date and sprint.end_date and sprint.end_date <= sprint.start_date:
        raise ValidationFailed("La fecha de fin debe ser posterior al inicio")
    sprint.save()
    events.publish_project(sprint.board.project_id, "sprint.changed", {"id": sprint.id},
                           actor_id=actor.id)
    return sprint


@transaction.atomic
def start_sprint(actor, sprint: Sprint, *, name=None, goal=None, start_date=None,
                 end_date=None) -> Sprint:
    board = sprint.board
    require(actor, board.project, Perm.MANAGE_SPRINTS)
    if sprint.state != Sprint.State.FUTURE:
        raise ValidationFailed("El sprint ya fue iniciado")
    if board.sprints.filter(state=Sprint.State.ACTIVE).exists():
        raise ValidationFailed("Ya hay un sprint activo en este tablero")
    issues = list(sprint.issues.all())
    if not issues:
        raise ValidationFailed("Agrega incidencias al sprint antes de iniciarlo")
    sprint.name = name or sprint.name
    if goal is not None:
        sprint.goal = goal
    sprint.start_date = start_date or timezone.now()
    sprint.end_date = end_date or (sprint.start_date + timedelta(days=14))
    if sprint.end_date <= sprint.start_date:
        raise ValidationFailed("La fecha de fin debe ser posterior al inicio")
    sprint.state = Sprint.State.ACTIVE
    sprint.start_snapshot = {
        "issues": [
            {"id": i.id, "estimate": str(_estimate(i, board)),
             "done": i.status.category == StatusCategory.DONE}
            for i in issues
        ],
        "estimation": board.estimation,
    }
    sprint.save()
    events.publish_project(board.project_id, "sprint.changed", {"id": sprint.id},
                           actor_id=actor.id)
    return sprint


@transaction.atomic
def complete_sprint(actor, sprint: Sprint, *, move_to_sprint_id: int | None = None) -> Sprint:
    board = sprint.board
    require(actor, board.project, Perm.MANAGE_SPRINTS)
    if sprint.state != Sprint.State.ACTIVE:
        raise ValidationFailed("Solo se puede completar un sprint activo")
    target = None
    if move_to_sprint_id:
        target = board.sprints.filter(pk=move_to_sprint_id, state=Sprint.State.FUTURE).first()
        if target is None:
            raise ValidationFailed("Sprint destino inválido")
    issues = list(sprint.issues.select_related("status"))
    done = [i for i in issues if i.status.category == StatusCategory.DONE]
    open_ = [i for i in issues if i.status.category != StatusCategory.DONE]
    sprint.close_snapshot = {
        "completed": [{"id": i.id, "estimate": str(_estimate(i, board))} for i in done],
        "incomplete": [{"id": i.id, "estimate": str(_estimate(i, board))} for i in open_],
        "estimation": board.estimation,
    }
    sprint.state = Sprint.State.CLOSED
    sprint.completed_at = timezone.now()
    sprint.save()
    for issue in issues:
        issue.closed_sprints.add(sprint)
    Issue.objects.filter(id__in=[i.id for i in open_]).update(sprint=target)
    # done issues keep the sprint reference (closed) for reports
    events.publish_project(board.project_id, "sprint.changed", {"id": sprint.id},
                           actor_id=actor.id)
    return sprint


@transaction.atomic
def delete_sprint(actor, sprint: Sprint) -> None:
    require(actor, sprint.board.project, Perm.MANAGE_SPRINTS)
    if sprint.state == Sprint.State.ACTIVE:
        raise ValidationFailed("No se puede eliminar un sprint activo")
    if sprint.state == Sprint.State.CLOSED:
        raise ValidationFailed("No se puede eliminar un sprint cerrado")
    pid = sprint.board.project_id
    sprint.issues.update(sprint=None)
    sprint.delete()
    events.publish_project(pid, "sprint.changed", {}, actor_id=actor.id)


@transaction.atomic
def move_issues_to_sprint(actor, board: Board, issue_ids: list[int], sprint: Sprint | None):
    require(actor, board.project, Perm.MANAGE_SPRINTS)
    if sprint is not None:
        if sprint.board_id != board.id or sprint.state == Sprint.State.CLOSED:
            raise ValidationFailed("Sprint inválido")
    issues = list(
        Issue.objects.filter(project=board.project, id__in=issue_ids, is_archived=False)
        .exclude(issue_type__level__in=[IssueType.Level.SUBTASK, IssueType.Level.EPIC])
    )
    for issue in issues:
        old = issue.sprint
        if (old.id if old else None) == (sprint.id if sprint else None):
            continue
        issue.sprint = sprint
        issue.save(update_fields=["sprint", "updated_at"])
        Issue.objects.filter(parent=issue, issue_type__level=IssueType.Level.SUBTASK).update(
            sprint=sprint
        )
        from apps.issues.models import IssueHistory
        from apps.issues.services import _item

        IssueHistory.objects.create(issue=issue, actor=actor,
                                    items=[_item("sprint", old, sprint)])
        track_issue_sprint_change(issue, old, issue.story_points)
    events.publish_project(board.project_id, "issue.updated",
                           {"ids": [i.id for i in issues], "fields": ["sprint"]},
                           actor_id=actor.id)
    return issues


# --------------------------------------------------------------------------- scope tracking

def record_scope_change(sprint: Sprint, issue: Issue, kind: str, before, after) -> None:
    SprintScopeChange.objects.create(
        sprint=sprint, issue=issue, kind=kind, value_before=before, value_after=after
    )


def track_issue_sprint_change(issue: Issue, old_sprint: Sprint | None, old_points) -> None:
    new_sprint = issue.sprint
    old_id = old_sprint.id if old_sprint else None
    new_id = new_sprint.id if new_sprint else None
    if old_id != new_id:
        if old_sprint and old_sprint.state == Sprint.State.ACTIVE:
            record_scope_change(old_sprint, issue, "removed", old_points, None)
        if new_sprint and new_sprint.state == Sprint.State.ACTIVE:
            record_scope_change(new_sprint, issue, "added", None, issue.story_points)
    elif new_sprint and new_sprint.state == Sprint.State.ACTIVE and old_points != \
            issue.story_points:
        record_scope_change(new_sprint, issue, "estimate", old_points, issue.story_points)


# --------------------------------------------------------------------------- reports

def burndown(sprint: Sprint) -> dict:
    """Story-point burndown: initial scope + timeline of changes."""
    board = sprint.board
    start = sprint.start_snapshot or {}
    initial = sum(
        (Decimal(i["estimate"]) for i in start.get("issues", []) if not i.get("done")),
        Decimal(0),
    )
    timeline = []
    remaining = initial
    for ch in sprint.scope_changes.select_related("issue").all():
        before = ch.value_before or Decimal(0)
        after = ch.value_after or Decimal(0)
        if board.estimation == Board.Estimation.ISSUE_COUNT:
            before = after = Decimal(1)
        delta = Decimal(0)
        if ch.kind == "added":
            delta = after
        elif ch.kind == "removed":
            delta = -before
        elif ch.kind == "estimate":
            delta = after - before
        elif ch.kind == "completed":
            delta = -after
        elif ch.kind == "reopened":
            delta = after
        remaining += delta
        timeline.append({
            "at": ch.created_at.isoformat(), "issue": ch.issue.key, "kind": ch.kind,
            "delta": float(delta), "remaining": float(remaining),
        })
    return {
        "sprint": {"id": sprint.id, "name": sprint.name,
                   "start": sprint.start_date.isoformat() if sprint.start_date else None,
                   "end": sprint.end_date.isoformat() if sprint.end_date else None,
                   "completed_at": sprint.completed_at.isoformat() if sprint.completed_at
                   else None},
        "estimation": board.estimation,
        "initial": float(initial),
        "timeline": timeline,
    }


def velocity(board: Board, limit: int = 7) -> list[dict]:
    sprints = board.sprints.filter(state=Sprint.State.CLOSED).order_by("-completed_at")[:limit]
    out = []
    for s in reversed(list(sprints)):
        committed = sum(
            (Decimal(i["estimate"]) for i in (s.start_snapshot or {}).get("issues", [])),
            Decimal(0),
        )
        completed = sum(
            (Decimal(i["estimate"]) for i in (s.close_snapshot or {}).get("completed", [])),
            Decimal(0),
        )
        out.append({"id": s.id, "name": s.name, "committed": float(committed),
                    "completed": float(completed)})
    return out


def sprint_summary(sprint: Sprint) -> dict:
    agg = sprint.issues.values("status__category").annotate(points=Sum("story_points"))
    by_cat = {r["status__category"]: float(r["points"] or 0) for r in agg}
    counts = {}
    for r in sprint.issues.values_list("status__category", flat=True):
        counts[r] = counts.get(r, 0) + 1
    return {"points": by_cat, "counts": counts}
