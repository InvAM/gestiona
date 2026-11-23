from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import NotFound, ValidationFailed
from apps.core.schemas import (
    IssueTypeOut,
    PriorityOut,
    StatusOut,
    UserRef,
    priority_ref,
    status_ref,
    type_ref,
    user_ref,
)
from apps.issues.models import Issue, IssueType
from apps.projects.api import get_project
from apps.projects.models import Perm
from apps.projects.permissions import require
from apps.workflows.models import Status

from . import services
from .models import Board, BoardColumn, QuickFilter, Sprint

router = Router(tags=["boards"])


# ------------------------------------------------------------------ schemas

class NamedCol(Schema):
    id: int
    name: str


class EpicRef(Schema):
    id: int
    key: str
    summary: str
    color: str


class CardOut(Schema):
    id: int
    key: str
    summary: str
    type: IssueTypeOut
    status: StatusOut
    priority: PriorityOut
    assignee: UserRef | None
    story_points: Decimal | None
    original_estimate: int | None
    epic: EpicRef | None
    parent_id: int | None
    labels: list[str]
    flagged: bool
    rank: str
    sprint_id: int | None
    due_date: str | None
    start_date: str | None = None
    subtasks_total: int
    subtasks_done: int
    fix_versions: list[str]
    components: list[str]
    days_in_column: int | None


class ColumnOut(Schema):
    id: int
    name: str
    position: int
    status_ids: list[int]
    min_issues: int | None
    max_issues: int | None


class QuickFilterOut(Schema):
    id: int
    name: str
    jql: str
    description: str


class BoardOut(Schema):
    id: int
    name: str
    kind: str
    project_key: str
    filter_jql: str
    swimlanes: str
    estimation: str
    kanban_backlog: bool
    hide_done_after_days: int
    card_fields: list[str]
    columns: list[ColumnOut]
    quick_filters: list[QuickFilterOut]
    can_manage: bool
    can_manage_sprints: bool
    deleted_at: str | None = None


class BoardIn(Schema):
    name: str | None = None
    kind: str | None = None
    filter_jql: str | None = None
    swimlanes: str | None = None
    estimation: str | None = None
    kanban_backlog: bool | None = None
    hide_done_after_days: int | None = None
    card_fields: list[str] | None = None


class ColumnIn(Schema):
    id: int | None = None
    name: str
    status_ids: list[int]
    min_issues: int | None = None
    max_issues: int | None = None


class SprintOut(Schema):
    id: int
    name: str
    goal: str
    state: str
    start_date: str | None
    end_date: str | None
    completed_at: str | None
    position: int


class SprintWithIssues(SprintOut):
    issues: list[CardOut]


class BoardDataOut(Schema):
    board: BoardOut
    sprint: SprintOut | None
    future_sprints: list[SprintOut]
    issues: list[CardOut]
    unmapped_status_ids: list[int]


class BacklogOut(Schema):
    board: BoardOut
    sprints: list[SprintWithIssues]
    backlog: list[CardOut]
    epics: list[EpicRef]


class SprintIn(Schema):
    name: str | None = None
    goal: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class CompleteIn(Schema):
    move_to_sprint_id: int | None = None


class MoveIn(Schema):
    issue_ids: list[int]
    sprint_id: int | None = None
    before_id: int | None = None
    after_id: int | None = None


class QuickFilterIn(Schema):
    name: str
    jql: str
    description: str = ""


class BurndownPoint(Schema):
    at: str
    issue: str
    kind: str
    delta: float
    remaining: float


class SprintDates(Schema):
    id: int
    name: str
    start: str | None
    end: str | None
    completed_at: str | None


class SprintReportOut(Schema):
    sprint: SprintDates
    estimation: str
    initial: float
    timeline: list[BurndownPoint]
    completed: list[CardOut]
    incomplete: list[CardOut]
    goal: str
    state: str


class VelocityRow(Schema):
    id: int
    name: str
    committed: float
    completed: float


class VelocityOut(Schema):
    sprints: list[VelocityRow]


class CfdSeries(Schema):
    date: str
    counts: dict[str, int]


class CfdOut(Schema):
    columns: list[NamedCol]
    series: list[CfdSeries]


# ------------------------------------------------------------------ serialization

EPIC_COLORS = ["#6554C0", "#00875A", "#FF991F", "#0065FF", "#DE350B", "#00A3BF", "#5243AA",
               "#36B37E", "#FF5630", "#8777D9"]


def epic_ref(e: Issue | None) -> dict | None:
    if e is None:
        return None
    color = (e.custom_fields or {}).get("epic_color") or EPIC_COLORS[e.id % len(EPIC_COLORS)]
    return {"id": e.id, "key": e.key, "summary": e.summary, "color": color}


def card_queryset(qs):
    return qs.select_related(
        "issue_type", "status", "priority", "assignee", "parent", "parent__issue_type",
    ).prefetch_related("fix_versions", "components").annotate(
        n_sub=Count("children", distinct=True),
        n_sub_done=Count("children", filter=Q(children__status__category="done"),
                         distinct=True),
    )


def card(i: Issue) -> dict:
    from django.utils import timezone

    epic = None
    if i.parent and i.parent.issue_type.level == IssueType.Level.EPIC:
        epic = i.parent
    days = None
    if i.status_changed_at:
        days = (timezone.now() - i.status_changed_at).days
    return {
        "id": i.id, "key": i.key, "summary": i.summary, "type": type_ref(i.issue_type),
        "status": status_ref(i.status), "priority": priority_ref(i.priority),
        "assignee": user_ref(i.assignee), "story_points": i.story_points,
        "original_estimate": i.original_estimate, "epic": epic_ref(epic),
        "parent_id": i.parent_id, "labels": i.labels, "flagged": i.flagged, "rank": i.rank,
        "sprint_id": i.sprint_id, "due_date": i.due_date.isoformat() if i.due_date else None,
        "start_date": i.start_date.isoformat() if i.start_date else None,
        "subtasks_total": getattr(i, "n_sub", 0), "subtasks_done": getattr(i, "n_sub_done", 0),
        "fix_versions": [v.name for v in i.fix_versions.all()],
        "components": [c.name for c in i.components.all()],
        "days_in_column": days,
    }


def sprint_out(s: Sprint) -> dict:
    return {
        "id": s.id, "name": s.name, "goal": s.goal, "state": s.state,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "position": s.position,
    }


def board_out(b: Board, user) -> dict:
    from apps.projects.permissions import has_perm

    cols = b.columns.prefetch_related("statuses")
    return {
        "id": b.id, "name": b.name, "kind": b.kind, "project_key": b.project.key,
        "filter_jql": b.filter_jql, "swimlanes": b.swimlanes, "estimation": b.estimation,
        "kanban_backlog": b.kanban_backlog, "hide_done_after_days": b.hide_done_after_days,
        "card_fields": b.card_fields,
        "columns": [{"id": c.id, "name": c.name, "position": c.position,
                     "status_ids": [s.id for s in c.statuses.all()],
                     "min_issues": c.min_issues, "max_issues": c.max_issues} for c in cols],
        # all_objects: the papelera listing shows what a restore will bring back
        "quick_filters": [{"id": q.id, "name": q.name, "jql": q.jql,
                           "description": q.description}
                          for q in QuickFilter.all_objects.filter(board=b)],
        "can_manage": has_perm(user, b.project, Perm.ADMINISTER),
        "can_manage_sprints": has_perm(user, b.project, Perm.MANAGE_SPRINTS),
        "deleted_at": softdelete.iso(b.deleted_at),
    }


def get_board(user, board_id: int, perm: str = Perm.BROWSE, *,
              include_deleted: bool = False) -> Board:
    """Active board (a board in the papelera is 404 for every view and mutation)."""
    qs = Board.all_objects if include_deleted else Board.objects
    b = qs.select_related("project").filter(pk=board_id).first()
    if b is None:
        raise NotFound("Tablero no encontrado")
    require(user, b.project, perm)
    return b


def _filters_q(user, board: Board, quick_filter_ids: list[int], assignee_ids: list[int],
               q: str, epic_ids: list[int], type_ids: list[int], label: str | None) -> Q:
    from apps.search.jql import compile_jql

    out = Q()
    for qf in board.quick_filters.filter(id__in=quick_filter_ids):
        out &= compile_jql(qf.jql, user=user, project=board.project).q
    if assignee_ids:
        aq = Q(assignee_id__in=[a for a in assignee_ids if a > 0])
        if 0 in assignee_ids:
            aq |= Q(assignee__isnull=True)
        out &= aq
    if epic_ids:
        eq = Q(parent_id__in=[e for e in epic_ids if e > 0]) | \
            Q(parent__parent_id__in=[e for e in epic_ids if e > 0])
        if 0 in epic_ids:
            eq |= Q(parent__isnull=True)
        out &= eq
    if type_ids:
        out &= Q(issue_type_id__in=type_ids)
    if label:
        out &= Q(labels__contains=[label])
    if q:
        out &= Q(summary__icontains=q) | Q(key__iexact=q)
    return out


# ------------------------------------------------------------------ boards

@router.get("/projects/{key}/boards", response=list[BoardOut])
def list_boards(request, key: str, deleted: bool = False):
    """Active boards; ``?deleted=true`` → the papelera (project administrators)."""
    if deleted:
        p = get_project(request.user, key, Perm.ADMINISTER)
        qs = Board.all_objects.deleted().filter(project=p).order_by("-deleted_at", "id")
    else:
        p = get_project(request.user, key)
        qs = p.boards.all()
    return [board_out(b, request.user) for b in qs.select_related("project")]


@router.post("/projects/{key}/boards", response={201: BoardOut})
@transaction.atomic
def create_board(request, key: str, data: BoardIn):
    p = get_project(request.user, key, Perm.ADMINISTER)
    if data.kind and data.kind not in Board.Kind.values:
        raise ValidationFailed("Tipo de tablero inválido", code="kind")
    name = (data.name or "").strip() or f"Tablero {p.key}"
    b = Board.objects.create(project=p, name=name[:80],
                             kind=data.kind or Board.Kind.SCRUM, owner=request.user,
                             card_fields=["issue_type", "key", "priority", "assignee",
                                          "story_points", "epic"])
    services.reset_columns_from_workflow(b)
    services.board_changed(request.user, b)
    return 201, board_out(b, request.user)


@router.get("/boards/{board_id}", response=BoardOut)
def get_board_config(request, board_id: int):
    return board_out(get_board(request.user, board_id), request.user)


@router.patch("/boards/{board_id}", response=BoardOut)
def update_board(request, board_id: int, data: BoardIn):
    b = get_board(request.user, board_id, Perm.ADMINISTER)
    d = data.dict(exclude_unset=True)
    if "filter_jql" in d and d["filter_jql"]:
        from apps.search.jql import compile_jql

        compile_jql(d["filter_jql"], user=request.user, project=b.project)
    if "kind" in d and d["kind"] not in Board.Kind.values:
        raise ValidationFailed("Tipo de tablero inválido")
    if "name" in d and d["name"] is not None:
        d["name"] = d["name"].strip()[:80]
        if not d["name"]:
            raise ValidationFailed("El nombre es obligatorio", code="name")
    for k, v in d.items():
        if v is not None:
            setattr(b, k, v)
    b.save()
    return board_out(b, request.user)


@router.delete("/boards/{board_id}", response={204: None})
def delete_board(request, board_id: int, permanent: bool = False):
    """Papelera (project admin). ``?permanent=true`` → hard delete (system admin, also for
    boards already in the papelera); 409 ``protected`` while its sprints hold issues."""
    if permanent:
        softdelete.require_system_admin(request.user, "Solo los administradores pueden "
                                                      "borrar definitivamente")
        b = get_board(request.user, board_id, Perm.BROWSE, include_deleted=True)
        services.purge_board(request.user, b)
        return 204, None
    b = get_board(request.user, board_id, Perm.ADMINISTER)
    services.soft_delete_board(request.user, b)
    return 204, None


@router.post("/boards/{board_id}/restore", response=BoardOut)
def restore_board(request, board_id: int):
    b = Board.all_objects.deleted().select_related("project").filter(pk=board_id).first()
    if b is None:
        raise NotFound("El tablero no está en la papelera")
    require(request.user, b.project, Perm.ADMINISTER)
    services.restore_board(request.user, b)
    return board_out(b, request.user)


@router.put("/boards/{board_id}/columns", response=BoardOut)
@transaction.atomic
def set_columns(request, board_id: int, columns: list[ColumnIn]):
    b = get_board(request.user, board_id, Perm.ADMINISTER)
    if not columns:
        raise ValidationFailed("El tablero necesita al menos una columna")
    seen: set[int] = set()
    for c in columns:
        dup = seen & set(c.status_ids)
        if dup:
            raise ValidationFailed("Un estado solo puede estar en una columna")
        seen |= set(c.status_ids)
        if c.min_issues is not None and c.max_issues is not None and c.min_issues > c.max_issues:
            raise ValidationFailed(f"Columna {c.name}: mínimo mayor que máximo")
    valid = set(Status.objects.filter(id__in=seen).values_list("id", flat=True))
    if valid != seen:
        raise ValidationFailed("Estado inválido")
    keep = {c.id for c in columns if c.id}
    b.columns.exclude(id__in=keep).delete()
    for pos, c in enumerate(columns):
        col = b.columns.filter(pk=c.id).first() if c.id else None
        col = col or BoardColumn(board=b)
        col.name = c.name.strip()[:60] or "Columna"
        col.position = pos
        col.min_issues, col.max_issues = c.min_issues, c.max_issues
        col.save()
        col.statuses.set(c.status_ids)
    return board_out(b, request.user)


@router.get("/boards/{board_id}/data", response=BoardDataOut)
def board_data(request, board_id: int, sprint_id: int | None = None, q: str = "",
               quick_filters: str = "", assignees: str = "", epics: str = "",
               types: str = "", label: str | None = None):
    b = get_board(request.user, board_id)

    def ints(s):
        return [int(x) for x in s.split(",") if x.strip().lstrip("-").isdigit()]

    sprint = None
    if b.kind == Board.Kind.SCRUM:
        sprints = b.sprints.filter(state=Sprint.State.ACTIVE)
        sprint = sprints.filter(pk=sprint_id).first() if sprint_id else sprints.first()
    extra = _filters_q(request.user, b, ints(quick_filters), ints(assignees), q.strip(),
                       ints(epics), ints(types), label)
    issues = card_queryset(services.board_issues(b, sprint=sprint, extra_q=extra)).order_by(
        "rank"
    )
    mapped = set(
        BoardColumn.statuses.through.objects.filter(boardcolumn__board=b)
        .values_list("status_id", flat=True)
    )
    wf_status_ids = {s.id for s in b.project.workflow.statuses.all()}
    return {
        "board": board_out(b, request.user),
        "sprint": sprint_out(sprint) if sprint else None,
        "future_sprints": [sprint_out(s) for s in b.sprints.filter(state=Sprint.State.FUTURE)],
        "issues": [card(i) for i in issues],
        "unmapped_status_ids": sorted(wf_status_ids - mapped),
    }


@router.get("/boards/{board_id}/backlog", response=BacklogOut)
def backlog(request, board_id: int, q: str = "", quick_filters: str = "", assignees: str = "",
            epics: str = "", types: str = "", label: str | None = None):
    b = get_board(request.user, board_id)

    def ints(s):
        return [int(x) for x in s.split(",") if x.strip().lstrip("-").isdigit()]

    extra = _filters_q(request.user, b, ints(quick_filters), ints(assignees), q.strip(),
                       ints(epics), ints(types), label)
    sprints = list(b.sprints.exclude(state=Sprint.State.CLOSED).order_by("-state", "position"))
    # active first, then future by position
    sprints.sort(key=lambda s: (0 if s.state == Sprint.State.ACTIVE else 1, s.position))
    base = services.board_issue_queryset(b).filter(extra).exclude(
        issue_type__level__in=[IssueType.Level.EPIC, IssueType.Level.SUBTASK]
    )
    by_sprint: dict[int, list] = {s.id: [] for s in sprints}
    for i in card_queryset(base.filter(sprint__in=sprints)).order_by("rank"):
        by_sprint[i.sprint_id].append(card(i))
    backlog_cards = [card(i) for i in card_queryset(
        services.backlog_issues(b).filter(extra)).order_by("rank")]
    if b.kind == Board.Kind.KANBAN and b.kanban_backlog:
        first_col = b.columns.first()
        if first_col:
            ids = set(first_col.statuses.values_list("id", flat=True))
            backlog_cards = [c for c in backlog_cards if c["status"]["id"] in ids]
    epics_qs = Issue.objects.filter(project=b.project, issue_type__level=IssueType.Level.EPIC,
                                    is_archived=False)\
        .exclude(status__category="done").order_by("rank")
    return {
        "board": board_out(b, request.user),
        "sprints": [{**sprint_out(s), "issues": by_sprint[s.id]} for s in sprints]
        if b.kind == Board.Kind.SCRUM else [],
        "backlog": backlog_cards,
        "epics": [epic_ref(e) for e in epics_qs],
    }


# ------------------------------------------------------------------ quick filters

@router.post("/boards/{board_id}/quick-filters", response={201: QuickFilterOut})
def add_quick_filter(request, board_id: int, data: QuickFilterIn):
    from apps.search.jql import compile_jql

    b = get_board(request.user, board_id, Perm.ADMINISTER)
    compile_jql(data.jql, user=request.user, project=b.project)
    qf = QuickFilter.objects.create(board=b, name=data.name[:60], jql=data.jql,
                                    description=data.description[:255],
                                    position=b.quick_filters.count())
    return 201, {"id": qf.id, "name": qf.name, "jql": qf.jql, "description": qf.description}


@router.delete("/boards/{board_id}/quick-filters/{qid}", response={204: None})
def delete_quick_filter(request, board_id: int, qid: int):
    b = get_board(request.user, board_id, Perm.ADMINISTER)
    b.quick_filters.filter(pk=qid).delete()
    return 204, None


# ------------------------------------------------------------------ sprints

def _get_sprint(user, sid: int) -> Sprint:
    # sprints of a board in the papelera are frozen with it (404 until it is restored)
    s = Sprint.objects.select_related("board__project").filter(
        pk=sid, board__deleted_at__isnull=True).first()
    if s is None:
        raise NotFound("Sprint no encontrado")
    require(user, s.board.project, Perm.BROWSE)
    return s


@router.get("/boards/{board_id}/sprints", response=list[SprintOut])
def list_sprints(request, board_id: int, state: str | None = None):
    b = get_board(request.user, board_id)
    qs = b.sprints.all()
    if state:
        qs = qs.filter(state__in=state.split(","))
    return [sprint_out(s) for s in qs.order_by("-completed_at", "position")]


@router.post("/boards/{board_id}/sprints", response={201: SprintOut})
def create_sprint(request, board_id: int, data: SprintIn):
    b = get_board(request.user, board_id)
    s = services.create_sprint(request.user, b, data.name, data.goal or "", data.start_date,
                               data.end_date)
    return 201, sprint_out(s)


@router.patch("/sprints/{sid}", response=SprintOut)
def update_sprint(request, sid: int, data: SprintIn):
    s = services.update_sprint(request.user, _get_sprint(request.user, sid),
                               **data.dict(exclude_unset=True))
    return sprint_out(s)


@router.post("/sprints/{sid}/start", response=SprintOut)
def start_sprint(request, sid: int, data: SprintIn):
    s = services.start_sprint(request.user, _get_sprint(request.user, sid), **data.dict())
    return sprint_out(s)


@router.post("/sprints/{sid}/complete", response=SprintOut)
def complete_sprint(request, sid: int, data: CompleteIn):
    s = services.complete_sprint(request.user, _get_sprint(request.user, sid),
                                 move_to_sprint_id=data.move_to_sprint_id)
    return sprint_out(s)


@router.delete("/sprints/{sid}", response={204: None})
def delete_sprint(request, sid: int):
    services.delete_sprint(request.user, _get_sprint(request.user, sid))
    return 204, None


@router.post("/boards/{board_id}/move", response={204: None})
@transaction.atomic
def move_issues(request, board_id: int, data: MoveIn):
    """Backlog drag & drop: move issues into a sprint (or backlog) and optionally rank."""
    from apps.issues.services import rank_issues

    b = get_board(request.user, board_id)
    sprint = None
    if data.sprint_id:
        sprint = b.sprints.filter(pk=data.sprint_id).first()
        if sprint is None:
            raise ValidationFailed("Sprint inválido")
    issues = Issue.objects.filter(project=b.project, id__in=data.issue_ids)
    current = {i.id: i.sprint_id for i in issues}
    if any(v != (sprint.id if sprint else None) for v in current.values()):
        services.move_issues_to_sprint(request.user, b, data.issue_ids, sprint)
    if data.before_id or data.after_id:
        before = Issue.objects.filter(pk=data.before_id).first() if data.before_id else None
        after = Issue.objects.filter(pk=data.after_id).first() if data.after_id else None
        rank_issues(request.user, list(Issue.objects.filter(id__in=data.issue_ids)),
                    before=before, after=after)
    return 204, None


# ------------------------------------------------------------------ reports

@router.get("/sprints/{sid}/report", response=SprintReportOut)
def sprint_report(request, sid: int):
    s = _get_sprint(request.user, sid)
    data = services.burndown(s)
    snap = s.close_snapshot or {}
    ids = [x["id"] for x in snap.get("completed", []) + snap.get("incomplete", [])] or \
        list(s.issues.values_list("id", flat=True))
    issues = {i.id: i for i in card_queryset(Issue.objects.filter(id__in=ids))}
    if snap:
        completed = [card(issues[x["id"]]) for x in snap.get("completed", []) if x["id"] in issues]
        incomplete = [card(issues[x["id"]]) for x in snap.get("incomplete", [])
                      if x["id"] in issues]
    else:
        completed = [card(i) for i in issues.values() if i.status.category == "done"]
        incomplete = [card(i) for i in issues.values() if i.status.category != "done"]
    data["completed"] = completed
    data["incomplete"] = incomplete
    data["goal"] = s.goal
    data["state"] = s.state
    return data


@router.get("/boards/{board_id}/velocity", response=VelocityOut)
def velocity(request, board_id: int):
    return {"sprints": services.velocity(get_board(request.user, board_id))}


@router.get("/boards/{board_id}/cumulative-flow", response=CfdOut)
def cumulative_flow(request, board_id: int, days: int = 30):
    """Daily count of issues per board column, reconstructed from status history."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.issues.models import IssueHistory

    b = get_board(request.user, board_id)
    days = max(7, min(days, 180))
    cols = list(b.columns.prefetch_related("statuses"))
    status_to_col = {s.id: c.id for c in cols for s in c.statuses.all()}
    issues = list(services.board_issue_queryset(b).values("id", "status_id", "created_at"))
    hist: dict[int, list] = {}
    for h in IssueHistory.objects.filter(issue_id__in=[i["id"] for i in issues]).order_by(
        "created_at"
    ):
        for it in h.items:
            if it.get("field") == "status":
                hist.setdefault(h.issue_id, []).append((h.created_at, it.get("from"),
                                                        it.get("to")))
    today = timezone.localdate()
    series = []
    for d in range(days, -1, -1):
        day = today - timedelta(days=d)
        end = timezone.make_aware(datetime.combine(day + timedelta(days=1), datetime.min.time()))
        counts = {c.id: 0 for c in cols}
        for i in issues:
            if i["created_at"] >= end:
                continue
            changes = hist.get(i["id"], [])
            status = changes[0][1] if changes else i["status_id"]
            for at, _frm, to in changes:
                if at < end:
                    status = to
            col = status_to_col.get(status)
            if col:
                counts[col] += 1
        series.append({"date": day.isoformat(), "counts": {str(k): v for k, v in counts.items()}})
    return {"columns": [{"id": c.id, "name": c.name} for c in cols], "series": series}


__all__ = ["router", "card", "card_queryset", "epic_ref", "Prefetch"]
