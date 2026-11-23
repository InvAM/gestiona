"""Plan domain logic: scope (always limited to what the viewer may see), dependencies,
capacity per iteration and cross-project releases."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.core import softdelete
from apps.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from apps.issues.models import Issue, IssueType
from apps.projects.models import Perm, Project, Version
from apps.projects.permissions import has_perm, visible_projects
from apps.workflows.models import StatusCategory

from .models import IterationCapacity, Plan, PlanRelease, PlanTeam, Team

User = get_user_model()

MAX_ITERATIONS = 26
RECENT_CLOSED_SPRINT_DAYS = 60


# --------------------------------------------------------------------------- access

def visible_plans(user) -> QuerySet[Plan]:
    """Plans the user may open: own, public, or shared with them."""
    return Plan.objects.filter(
        Q(owner=user) | Q(access=Plan.Access.PUBLIC)
        | Q(access=Plan.Access.SHARED, shared_with=user)
    ).distinct()


def can_edit_plan(user, plan: Plan) -> bool:
    return plan.owner_id == user.id or bool(user.is_superuser)


def get_plan(user, pid: int, *, edit: bool = False) -> Plan:
    plan = visible_plans(user).select_related("owner").filter(pk=pid).first()
    if plan is None:
        raise NotFound("Plan no encontrado")
    if edit and not can_edit_plan(user, plan):
        raise Forbidden("Solo el propietario puede modificar este plan")
    return plan


def deleted_plans(user) -> QuerySet[Plan]:
    """Papelera: your own deleted plans (system admins see every deleted plan)."""
    qs = Plan.all_objects.deleted()
    return qs if softdelete.is_system_admin(user) else qs.filter(owner=user)


def viewer_projects(user, plan: Plan) -> QuerySet[Project]:
    """Plan sources the viewer is allowed to browse."""
    return plan.projects.filter(id__in=visible_projects(user).values("id")).order_by("key")


def plan_scope(user, plan: Plan) -> tuple[QuerySet[Issue], str | None]:
    """Issues the plan shows to `user`: browsable source projects, not archived, matching
    the plan JQL compiled *as the viewer* (so it can never reveal anything else). A JQL the
    viewer cannot run (e.g. it names a project they cannot see) yields no issues."""
    from apps.search.jql import JQLError, compile_jql

    qs = Issue.objects.filter(project__in=viewer_projects(user, plan), is_archived=False)
    jql = (plan.filter_jql or "").strip()
    if jql:
        try:
            compiled = compile_jql(jql, user=user)
        except JQLError as e:
            return qs.none(), e.message
        qs = qs.filter(id__in=Issue.objects.filter(compiled.q).values("id"))
    return qs, None


# --------------------------------------------------------------------------- validation

def _clean_name(value: str | None, limit: int = 120) -> str:
    name = (value or "").strip()[:limit]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    return name


def _active_users(ids) -> list:
    ids = list(dict.fromkeys(ids or []))
    users = list(User.objects.filter(id__in=ids, is_active=True))
    if len(users) != len(ids):
        raise ValidationFailed("Algún usuario no existe o está inactivo", code="users")
    return users


def _check_jql(user, jql: str) -> str:
    from apps.search.jql import JQLError, compile_jql

    jql = (jql or "").strip()
    if jql:
        try:
            compile_jql(jql, user=user)
        except JQLError as e:
            raise ValidationFailed(f"JQL inválido: {e.message}", code="filter_jql") from e
    return jql


def _resolve_projects(user, plan: Plan | None, ids: list[int]) -> list[Project]:
    ids = list(dict.fromkeys(ids))
    visible = list(visible_projects(user).filter(id__in=ids))
    if len(visible) != len(ids):
        raise ValidationFailed("Algún proyecto no existe o no tienes acceso", code="project_ids")
    if plan is not None and plan.pk:
        # sources the editor cannot see are kept: you cannot remove what you cannot see
        hidden = plan.projects.exclude(id__in=visible_projects(user).values("id"))
        visible += list(hidden)
    return visible


@dataclass
class TeamSlot:
    team: Team
    board_id: int | None


def _resolve_plan_teams(user, plan: Plan, projects: list[Project],
                        rows: list[dict]) -> list[TeamSlot]:
    from apps.boards.models import Board

    slots, seen = [], set()
    project_ids = {p.id for p in projects}
    # links the editor cannot choose (board in the trash or in a project they cannot
    # browse) are accepted when sent back as they are
    kept = {(pt.team_id, pt.board_id) for pt in _kept_boards(user, plan)}
    for row in rows:
        tid = row.get("team_id")
        if tid in seen:
            continue
        seen.add(tid)
        team = Team.objects.filter(pk=tid).first()
        if team is None:
            raise ValidationFailed("Equipo no encontrado", code="teams")
        board_id = row.get("board_id")
        if board_id and (tid, board_id) not in kept:
            board = Board.objects.select_related("project").filter(pk=board_id).first()
            if board is None or board.project_id not in project_ids or \
                    not has_perm(user, board.project, Perm.BROWSE):
                raise ValidationFailed("El tablero debe ser de un proyecto del plan",
                                       code="teams")
            if board.kind != Board.Kind.SCRUM:
                raise ValidationFailed(f"El tablero «{board.name}» no usa sprints; deja el "
                                       "equipo con iteraciones fijas", code="teams")
        slots.append(TeamSlot(team, board_id or None))
    return slots


def _kept_boards(user, plan: Plan) -> list[PlanTeam]:
    if not plan.pk:
        return []
    return [pt for pt in plan.plan_teams.filter(board__isnull=False)
            .select_related("board__project")
            if pt.board.deleted_at is not None or not board_visible(user, pt)]


def _check_iteration_days(days: int) -> int:
    if not 1 <= days <= 90:
        raise ValidationFailed("La iteración debe durar entre 1 y 90 días",
                               code="iteration_days")
    return days


# --------------------------------------------------------------------------- plans CRUD

@transaction.atomic
def save_plan(user, plan: Plan, data: dict) -> Plan:
    """Create (plan.pk is None) or partially update a plan. `data` holds only sent keys."""
    creating = plan.pk is None
    if creating:
        plan.owner = user
    if creating or "name" in data:
        plan.name = _clean_name(data.get("name"))
    if "description" in data:
        plan.description = (data["description"] or "").strip()
    if "access" in data:
        if data["access"] not in Plan.Access.values:
            raise ValidationFailed("Acceso inválido", code="access")
        plan.access = data["access"]
    if "estimation" in data:
        if data["estimation"] not in Plan.Estimation.values:
            raise ValidationFailed("Unidad de estimación inválida", code="estimation")
        plan.estimation = data["estimation"]
    if "iteration_days" in data and data["iteration_days"] is not None:
        plan.iteration_days = _check_iteration_days(int(data["iteration_days"]))
    if "iteration_start" in data:
        plan.iteration_start = data["iteration_start"]
    if "filter_jql" in data:
        plan.filter_jql = _check_jql(user, data["filter_jql"])

    projects = None
    if creating or "project_ids" in data:
        projects = _resolve_projects(user, plan, data.get("project_ids") or [])
    slots = None
    if "teams" in data and data["teams"] is not None:
        scope = projects if projects is not None else list(plan.projects.all())
        slots = _resolve_plan_teams(user, plan, scope, data["teams"])
    shared = _active_users(data.get("shared_with_ids")) if "shared_with_ids" in data else None

    plan.save()
    if projects is not None:
        plan.projects.set(projects)
    if shared is not None:
        plan.shared_with.set(shared)
    if slots is not None:
        keep = []
        kept = {pt.team_id: pt.board_id for pt in _kept_boards(user, plan)}
        for slot in slots:
            # a board in the trash (restoring it brings its sprints back) or one the
            # editor cannot see stays linked: you cannot remove what you cannot see
            board_id = slot.board_id or kept.get(slot.team.id)
            pt, _ = PlanTeam.objects.update_or_create(
                plan=plan, team=slot.team, defaults={"board_id": board_id})
            keep.append(pt.id)
        PlanTeam.objects.filter(plan=plan).exclude(id__in=keep).delete()
    elif projects is not None:
        # a board whose project left the plan no longer drives that team's iterations
        PlanTeam.objects.filter(plan=plan, board__isnull=False).exclude(
            board__project__in=projects).update(board=None)
    return plan


def board_visible(user, pt: PlanTeam) -> bool:
    return bool(pt.board_id) and has_perm(user, pt.board.project, Perm.BROWSE)


def active_board(user, pt: PlanTeam):
    """The board driving the team's sprints, as `user` sees it: None without one, while it
    is in the trash, or when `user` cannot browse its project (then the team plans with
    fixed iterations and neither the board nor its sprints are shown)."""
    if not pt.board_id or pt.board.deleted_at is not None or not board_visible(user, pt):
        return None
    return pt.board


def plan_teams(plan: Plan) -> list[PlanTeam]:
    return list(plan.plan_teams.filter(team__deleted_at__isnull=True)
                .select_related("team", "board__project").prefetch_related("team__members"))


def iteration_anchor(plan: Plan) -> date:
    if plan.iteration_start:
        return plan.iteration_start
    created = timezone.localtime(plan.created_at).date() if plan.created_at else \
        timezone.localdate()
    return created - timedelta(days=created.weekday())


# --------------------------------------------------------------------------- teams CRUD

def can_edit_team(user, team: Team) -> bool:
    if softdelete.is_system_admin(user) or team.created_by_id == user.id:
        return True
    return team.members.filter(pk=user.pk).exists()


def deleted_teams(user) -> QuerySet[Team]:
    qs = Team.all_objects.deleted()
    return qs if softdelete.is_system_admin(user) else qs.filter(created_by=user)


def _capacity(value) -> Decimal | None:
    if value is None:
        return None
    value = Decimal(str(value))
    if value < 0:
        raise ValidationFailed("La capacidad no puede ser negativa", code="capacity")
    return value


@transaction.atomic
def save_team(user, team: Team, data: dict) -> Team:
    creating = team.pk is None
    if creating:
        team.created_by = user
    if creating or "name" in data:
        team.name = _clean_name(data.get("name"), 80)
    if "description" in data:
        team.description = (data["description"] or "").strip()[:255]
    for field in ("capacity_points", "capacity_hours"):
        if field in data:
            setattr(team, field, _capacity(data[field]))
    members = _active_users(data.get("member_ids")) if "member_ids" in data else None
    try:
        with transaction.atomic():
            team.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un equipo con ese nombre", code="name_taken") from e
    if members is not None:
        team.members.set(members)
    return team


# --------------------------------------------------------------------------- capacity

def _unit_value(plan: Plan, issue: Issue) -> Decimal:
    if plan.estimation == Plan.Estimation.HOURS:
        return Decimal(issue.original_estimate or 0) / Decimal(3600)
    return issue.story_points or Decimal(0)


def _counted_issues(plan: Plan, scope: QuerySet[Issue], team: Team) -> list[Issue]:
    """Work that consumes capacity: epics never (their children do); with story points,
    sub-tasks neither (points live on the parent)."""
    qs = scope.filter(team=team).exclude(issue_type__level=IssueType.Level.EPIC)
    if plan.estimation == Plan.Estimation.STORY_POINTS:
        qs = qs.exclude(issue_type__level=IssueType.Level.SUBTASK)
    return list(qs.only("id", "sprint_id", "start_date", "due_date", "story_points",
                        "original_estimate"))


def _num(d: Decimal | None) -> float | None:
    return None if d is None else float(round(d, 1))


def _sprints_for(pt: PlanTeam):
    from apps.boards.models import Sprint

    recent = timezone.now() - timedelta(days=RECENT_CLOSED_SPRINT_DAYS)
    qs = Sprint.objects.filter(board_id=pt.board_id).exclude(
        Q(state=Sprint.State.CLOSED) & (Q(end_date__lt=recent) | Q(end_date__isnull=True)))
    order = {Sprint.State.CLOSED: 0, Sprint.State.ACTIVE: 1, Sprint.State.FUTURE: 2}
    return sorted(qs[:MAX_ITERATIONS], key=lambda s: (order.get(s.state, 3),
                                                      s.start_date or timezone.now(),
                                                      s.position, s.id))


def fixed_iterations(plan: Plan, count: int, today: date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    anchor, days = iteration_anchor(plan), plan.iteration_days
    current = (today - anchor).days // days
    first = max(0, current - 1)
    out = []
    for k in range(first, first + count):
        start = anchor + timedelta(days=k * days)
        out.append({"index": k, "start": start, "end": start + timedelta(days=days - 1)})
    return out


def team_capacity(user, plan: Plan, pt: PlanTeam, scope: QuerySet[Issue], *,
                  count: int = 8, today: date | None = None) -> dict:
    team = pt.team
    hours = plan.estimation == Plan.Estimation.HOURS
    default = team.capacity_hours if hours else team.capacity_points
    overrides = {(c.sprint_id, c.iteration_start): c.capacity for c in pt.capacities.all()}
    issues = _counted_issues(plan, scope, team)
    iterations = []
    unscheduled = [Decimal(0), 0]

    def row(key, name, start, end, state, sprint_id, iteration_start, total, n):
        cap = overrides.get((sprint_id, iteration_start))
        effective = cap if cap is not None else default
        return {
            "key": key, "name": name, "sprint_id": sprint_id,
            "iteration_start": iteration_start, "start": start, "end": end, "state": state,
            "capacity": _num(effective), "overridden": cap is not None,
            "assigned": _num(total), "issue_count": n,
            "over": effective is not None and total > effective,
        }

    board = active_board(user, pt)
    if board:
        sprints = _sprints_for(pt)
        by_sprint: dict[int, list] = defaultdict(lambda: [Decimal(0), 0])
        sprint_ids = {s.id for s in sprints}
        for i in issues:
            if i.sprint_id in sprint_ids:
                acc = by_sprint[i.sprint_id]
            else:
                acc = unscheduled if i.sprint_id is None else None
            if acc is not None:
                acc[0] += _unit_value(plan, i)
                acc[1] += 1
        for s in sprints:
            total, n = by_sprint.get(s.id, [Decimal(0), 0])
            iterations.append(row(
                f"s{s.id}", s.name,
                timezone.localtime(s.start_date).date() if s.start_date else None,
                timezone.localtime(s.end_date).date() if s.end_date else None,
                s.state, s.id, None, total, n))
        mode = "sprints"
    else:
        window = fixed_iterations(plan, count, today)
        sums = [[Decimal(0), 0] for _ in window]
        for i in issues:
            when = i.due_date or i.start_date
            if when is None:
                unscheduled[0] += _unit_value(plan, i)
                unscheduled[1] += 1
                continue
            for idx, it in enumerate(window):
                if it["start"] <= when <= it["end"]:
                    sums[idx][0] += _unit_value(plan, i)
                    sums[idx][1] += 1
                    break
        today = today or timezone.localdate()
        for it, (total, n) in zip(window, sums, strict=True):
            state = "closed" if it["end"] < today else "active" if it["start"] <= today \
                else "future"
            iterations.append(row(f"i{it['start'].isoformat()}", f"Iteración {it['index'] + 1}",
                                  it["start"], it["end"], state, None, it["start"], total, n))
        mode = "fixed"
    return {
        "team": {"id": team.id, "name": team.name},
        "mode": mode,
        "board": {"id": board.id, "name": board.name, "project_key": board.project.key}
        if board else None,
        # only told to whoever may see the board
        "board_deleted": board_visible(user, pt) and pt.board.deleted_at is not None,
        "default_capacity": _num(default),
        "iterations": iterations,
        "unscheduled": {"assigned": _num(unscheduled[0]), "issue_count": unscheduled[1]},
    }


def plan_capacity(user, plan: Plan, *, count: int = 8, today: date | None = None) -> dict:
    count = max(1, min(count, MAX_ITERATIONS))
    scope, error = plan_scope(user, plan)
    teams = [team_capacity(user, plan, pt, scope, count=count, today=today)
             for pt in plan_teams(plan)]
    return {"unit": plan.estimation, "teams": teams, "filter_error": error}


@transaction.atomic
def set_capacity(user, plan: Plan, team_id: int, *, sprint_id: int | None,
                 iteration_start: date | None, capacity) -> None:
    pt = PlanTeam.objects.select_related("team", "board__project").filter(
        plan=plan, team_id=team_id, team__deleted_at__isnull=True).first()
    if pt is None:
        raise ValidationFailed("El equipo no forma parte del plan", code="team_id")
    if sprint_id:
        from apps.boards.models import Sprint

        if not active_board(user, pt) or not Sprint.objects.filter(
                pk=sprint_id, board_id=pt.board_id).exists():
            raise ValidationFailed("El sprint no pertenece al tablero del equipo",
                                   code="sprint_id")
        lookup = {"plan_team": pt, "sprint_id": sprint_id}
    else:
        if iteration_start is None:
            raise ValidationFailed("Indica el sprint o la iteración", code="iteration_start")
        if active_board(user, pt):
            raise ValidationFailed("Este equipo planifica con los sprints de su tablero",
                                   code="iteration_start")
        if (iteration_start - iteration_anchor(plan)).days % plan.iteration_days:
            raise ValidationFailed("La fecha no coincide con el inicio de una iteración",
                                   code="iteration_start")
        lookup = {"plan_team": pt, "sprint__isnull": True, "iteration_start": iteration_start}
    if capacity is None:
        IterationCapacity.objects.filter(**lookup).delete()
        return
    value = _capacity(capacity)
    obj = IterationCapacity.objects.filter(**lookup).first()
    if obj is None:
        obj = IterationCapacity(plan_team=pt, sprint_id=sprint_id or None,
                                iteration_start=None if sprint_id else iteration_start)
    obj.capacity = value
    obj.save()


# --------------------------------------------------------------------------- releases

def _release_versions(user, release: PlanRelease) -> list[Version]:
    return list(Version._base_manager.filter(
        id__in=release.versions.values("id"),
        project__in=visible_projects(user),
    ).select_related("project").order_by("project__key", "position", "id"))


def release_out(user, release: PlanRelease) -> dict:
    versions = _release_versions(user, release)
    # aggregated in SQL: a release can span thousands of issues across projects
    issues = Issue.objects.filter(
        id__in=Issue.fix_versions.through.objects.filter(version__in=versions)
        .values("issue_id"),
        is_archived=False, project__in=visible_projects(user),
    )
    progress = {c.value: {"count": 0, "points": 0.0} for c in StatusCategory}
    for row in issues.order_by().values("status__category").annotate(
            n=Count("id"), points=Sum("story_points")):
        progress[row["status__category"]] = {"count": row["n"],
                                             "points": float(row["points"] or 0)}
    target = release.target_date
    late, late_count = [], 0
    if target:
        late_qs = issues.filter(due_date__gt=target).exclude(
            status__category=StatusCategory.DONE)
        late_count = late_qs.count()
        if late_count:
            late = list(late_qs.select_related("status", "project")
                        .order_by("due_date", "key")[:100])
    return {
        "id": release.id, "name": release.name, "description": release.description,
        "target_date": release.target_date,
        "versions": [{
            "id": v.id, "name": v.name, "status": v.status, "release_date": v.release_date,
            "project": {"id": v.project.id, "key": v.project.key, "name": v.project.name,
                        "avatar": v.project.avatar, "color": v.project.color},
            "late": bool(target and v.release_date and v.release_date > target),
            "deleted": v.deleted_at is not None,
        } for v in versions],
        "progress": [{"category": k, **v} for k, v in progress.items()],
        "total": sum(v["count"] for v in progress.values()),
        "done": progress[StatusCategory.DONE.value]["count"],
        "late_issues": [{
            "id": i.id, "key": i.key, "summary": i.summary, "due_date": i.due_date,
            "status": {"id": i.status.id, "name": i.status.name, "category": i.status.category},
            "project_key": i.project.key,
        } for i in late],
        "late_count": late_count,
    }


@transaction.atomic
def save_release(user, plan: Plan, release: PlanRelease, data: dict) -> PlanRelease:
    creating = release.pk is None
    if creating:
        release.plan = plan
    if creating or "name" in data:
        release.name = _clean_name(data.get("name"))
    if "description" in data:
        release.description = (data["description"] or "").strip()
    if "target_date" in data:
        release.target_date = data["target_date"]
    versions = None
    if "version_ids" in data and data["version_ids"] is not None:
        ids = list(dict.fromkeys(data["version_ids"]))
        versions = list(Version.objects.filter(
            id__in=ids, project__in=viewer_projects(user, plan)))
        if len(versions) != len(ids):
            raise ValidationFailed("Las versiones deben ser de proyectos del plan",
                                   code="version_ids")
    release.save()
    if versions is not None:
        if not creating:
            # versions the editor cannot see stay in the release
            hidden = release.versions.exclude(project__in=visible_projects(user))
            versions += list(hidden)
        release.versions.set(versions)
    return release


def get_release(plan: Plan, rid: int) -> PlanRelease:
    release = plan.releases.filter(pk=rid).first()
    if release is None:
        raise NotFound("Versión del plan no encontrada")
    return release
