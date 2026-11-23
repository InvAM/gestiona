"""Planes: planificación entre proyectos (cronograma, dependencias, equipos, capacidad y
versiones entre proyectos). Everything a plan shows is limited to what the viewer may see;
issue edits go through the regular issue endpoints (and their permissions)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from django.db.models import Count
from ninja import Field, Router, Schema

from apps.core import softdelete
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import (
    IssueTypeOut,
    PriorityOut,
    StatusOut,
    UserRef,
    user_ref,
)
from apps.projects.models import Version

from . import services, timeline
from .models import Plan, PlanRelease, PlanView, Team

router = Router(tags=["plans"])


# ------------------------------------------------------------------ schemas

class PlanProjectRef(Schema):
    id: int
    key: str
    name: str
    avatar: str
    color: str


class PlanTeamIn(Schema):
    team_id: int
    board_id: int | None = None


class PlanTeamOut(Schema):
    team_id: int
    name: str
    board_id: int | None
    board_name: str | None
    board_project_key: str | None
    capacity_points: float | None
    capacity_hours: float | None
    members: list[UserRef]


class PlanOut(Schema):
    id: int
    name: str
    description: str
    owner: UserRef
    access: str
    shared_with: list[UserRef]
    estimation: str
    iteration_days: int
    iteration_start: date | None
    iteration_anchor: date
    filter_jql: str
    projects: list[PlanProjectRef]
    hidden_project_count: int
    teams: list[PlanTeamOut]
    can_edit: bool
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class PlanIn(Schema):
    name: str
    description: str = ""
    project_ids: list[int] = []
    filter_jql: str = ""
    access: str = "private"
    shared_with_ids: list[int] = []
    estimation: str = "story_points"
    iteration_days: int = 14
    iteration_start: date | None = None
    teams: list[PlanTeamIn] = []


class PlanPatch(Schema):
    name: str | None = None
    description: str | None = None
    project_ids: list[int] | None = None
    filter_jql: str | None = None
    access: str | None = None
    shared_with_ids: list[int] | None = None
    estimation: str | None = None
    iteration_days: int | None = None
    iteration_start: date | None = None
    teams: list[PlanTeamIn] | None = None


class PlanIssueOut(Schema):
    id: int
    key: str
    summary: str
    project_id: int
    type: IssueTypeOut
    status: StatusOut
    priority: PriorityOut | None
    assignee: UserRef | None
    parent_id: int | None
    team_id: int | None
    sprint_id: int | None
    fix_version_ids: list[int]
    start_date: date | None
    due_date: date | None
    story_points: Decimal | None
    original_estimate: int | None
    can_edit: bool
    can_link: bool
    children_count: int  # children inside the same filtered group (expand to load them)
    rollup_start: date | None  # dates of its descendants over the whole plan
    rollup_end: date | None


class PlanDependencyEnd(Schema):
    id: int
    key: str
    summary: str
    project_id: int
    start_date: date | None
    due_date: date | None
    can_link: bool


class PlanDependencyOut(Schema):
    id: int
    link_type_id: int
    label: str
    blocker_id: int
    blocked_id: int
    blocker: PlanDependencyEnd
    blocked: PlanDependencyEnd
    conflict: bool


class PlanTeamRef(Schema):
    id: int
    name: str
    in_plan: bool
    deleted: bool


class PlanVersionRef(Schema):
    id: int
    name: str
    project_id: int
    status: str
    release_date: date | None
    deleted: bool


class PlanLinkTypeRef(Schema):
    id: int
    name: str
    outward: str
    inward: str


class PlanDateRange(Schema):
    start: date | None
    end: date | None


class PlanTimelineOut(Schema):
    total: int
    date_range: PlanDateRange
    teams: list[PlanTeamRef]
    versions: list[PlanVersionRef]
    statuses: list[StatusOut]
    assignees: list[UserRef]
    dependency_link_types: list[PlanLinkTypeRef]
    page_size: int
    page_max: int
    filter_error: str | None


class PlanTimelineFilters(Schema):
    """0 in team/assignee/version ids = «Sin equipo» / «Sin asignar» / «Sin versión»."""
    project_ids: list[int] = []
    team_ids: list[int] = []
    status_ids: list[int] = []
    assignee_ids: list[int] = []
    version_ids: list[int] = []


class PlanGroupsIn(Schema):
    filters: PlanTimelineFilters = Field(default_factory=PlanTimelineFilters)
    group_by: str = "none"  # none | project | team | version


class PlanGroupOut(Schema):
    key: str
    label: str
    count: int


class PlanGroupsOut(Schema):
    group_by: str
    total: int
    groups: list[PlanGroupOut]


class PlanRowsIn(Schema):
    filters: PlanTimelineFilters = Field(default_factory=PlanTimelineFilters)
    group_by: str = "none"
    group: str | None = None  # key from /timeline/groups ("all", "p3", "t0", "v12"…)
    parent_id: int | None = None  # children of this issue instead of the group roots
    cursor: str | None = None
    limit: int = timeline.PAGE_SIZE


class PlanRowsOut(Schema):
    rows: list[PlanIssueOut]
    total: int | None  # rows in this node; only on the first page (no cursor)
    next_cursor: str | None
    dependencies: list[PlanDependencyOut]


class PlanConflictsOut(Schema):
    count: int
    conflicts: list[PlanDependencyOut]
    truncated: bool


class PlanViewCollapse(Schema):
    mode: str = "expanded"  # expanded | collapsed: what every node does by default
    exceptions: list[str] = []  # node keys toggled against the mode ("g:t3", "p2:120"…)


class PlanViewIn(Schema):
    group_by: str = "none"
    scale: str = "months"  # weeks | months | quarters
    filters: PlanTimelineFilters = Field(default_factory=PlanTimelineFilters)
    collapse: dict[str, PlanViewCollapse] = {}  # per grouping (none, project, team, version)


class PlanViewOut(Schema):
    view: PlanViewIn | None
    updated_at: str | None


class PlanIterationOut(Schema):
    key: str
    name: str
    sprint_id: int | None
    iteration_start: date | None
    start: date | None
    end: date | None
    state: str
    capacity: float | None
    overridden: bool
    assigned: float
    issue_count: int
    over: bool


class PlanBoardRef(Schema):
    id: int
    name: str
    project_key: str


class PlanUnscheduledOut(Schema):
    assigned: float
    issue_count: int


class PlanTeamNameRef(Schema):
    id: int
    name: str


class PlanTeamCapacityOut(Schema):
    team: PlanTeamNameRef
    mode: str  # sprints | fixed
    board: PlanBoardRef | None
    board_deleted: bool  # its board is in the trash: fixed iterations until restored
    default_capacity: float | None
    iterations: list[PlanIterationOut]
    unscheduled: PlanUnscheduledOut


class PlanCapacityOut(Schema):
    unit: str
    teams: list[PlanTeamCapacityOut]
    filter_error: str | None


class PlanCapacityIn(Schema):
    team_id: int
    sprint_id: int | None = None
    iteration_start: date | None = None
    capacity: Decimal | None = None  # null = back to the team default


class PlanReleaseVersionOut(Schema):
    id: int
    name: str
    status: str
    release_date: date | None
    project: PlanProjectRef
    late: bool
    deleted: bool


class PlanReleaseProgress(Schema):
    category: str
    count: int
    points: float


class PlanLateIssueOut(Schema):
    id: int
    key: str
    summary: str
    due_date: date | None
    status: StatusOut
    project_key: str


class PlanReleaseOut(Schema):
    id: int
    name: str
    description: str
    target_date: date | None
    versions: list[PlanReleaseVersionOut]
    progress: list[PlanReleaseProgress]
    total: int
    done: int
    late_issues: list[PlanLateIssueOut]
    late_count: int


class PlanReleaseIn(Schema):
    name: str
    description: str = ""
    target_date: date | None = None
    version_ids: list[int] = []


class PlanReleasePatch(Schema):
    name: str | None = None
    description: str | None = None
    target_date: date | None = None
    version_ids: list[int] | None = None


class PlanVersionOption(Schema):
    id: int
    name: str
    status: str
    release_date: date | None
    project: PlanProjectRef


class TeamOut(Schema):
    id: int
    name: str
    description: str
    members: list[UserRef]
    capacity_points: float | None
    capacity_hours: float | None
    created_by: UserRef | None
    can_edit: bool
    issue_count: int
    plan_count: int
    deleted_at: str | None = None


class TeamIn(Schema):
    name: str
    description: str = ""
    member_ids: list[int] = []
    capacity_points: Decimal | None = None
    capacity_hours: Decimal | None = None


class TeamPatch(Schema):
    name: str | None = None
    description: str | None = None
    member_ids: list[int] | None = None
    capacity_points: Decimal | None = None
    capacity_hours: Decimal | None = None


# ------------------------------------------------------------------ serialization

def _project_ref(p) -> dict:
    return {"id": p.id, "key": p.key, "name": p.name, "avatar": p.avatar, "color": p.color}


def _f(d) -> float | None:
    return None if d is None else float(d)


def plan_out(plan: Plan, user) -> dict:
    visible = list(services.viewer_projects(user, plan))
    teams = []
    for pt in services.plan_teams(plan):
        board_visible = services.active_board(user, pt) is not None
        teams.append({
            "team_id": pt.team_id, "name": pt.team.name,
            "board_id": pt.board_id if board_visible else None,
            "board_name": pt.board.name if board_visible else None,
            "board_project_key": pt.board.project.key if board_visible else None,
            "capacity_points": _f(pt.team.capacity_points),
            "capacity_hours": _f(pt.team.capacity_hours),
            "members": [user_ref(u) for u in pt.team.members.all()],
        })
    return {
        "id": plan.id, "name": plan.name, "description": plan.description,
        "owner": user_ref(plan.owner), "access": plan.access,
        "shared_with": [user_ref(u) for u in plan.shared_with.all()],
        "estimation": plan.estimation, "iteration_days": plan.iteration_days,
        "iteration_start": plan.iteration_start,
        "iteration_anchor": services.iteration_anchor(plan),
        "filter_jql": plan.filter_jql,
        "projects": [_project_ref(p) for p in visible],
        "hidden_project_count": plan.projects.count() - len(visible),
        "teams": teams, "can_edit": services.can_edit_plan(user, plan),
        "created_at": plan.created_at.isoformat(), "updated_at": plan.updated_at.isoformat(),
        "deleted_at": softdelete.iso(plan.deleted_at),
    }


def team_out(team: Team, user) -> dict:
    return {
        "id": team.id, "name": team.name, "description": team.description,
        "members": [user_ref(u) for u in team.members.all()],
        "capacity_points": _f(team.capacity_points), "capacity_hours": _f(team.capacity_hours),
        "created_by": user_ref(team.created_by), "can_edit": services.can_edit_team(user, team),
        "issue_count": team.n_issues, "plan_count": team.n_plans,
        "deleted_at": softdelete.iso(team.deleted_at),
    }


# ------------------------------------------------------------------ plans

@router.get("/plans", response=list[PlanOut])
def list_plans(request, q: str = "", deleted: bool = False):
    qs = services.deleted_plans(request.user) if deleted else services.visible_plans(request.user)
    if q:
        qs = qs.filter(name__icontains=q.strip())
    return [plan_out(p, request.user) for p in qs.select_related("owner")]


@router.post("/plans", response={201: PlanOut})
def create_plan(request, data: PlanIn):
    plan = services.save_plan(request.user, Plan(), data.dict())
    return 201, plan_out(plan, request.user)


@router.get("/plans/{pid}", response=PlanOut)
def get_plan(request, pid: int):
    return plan_out(services.get_plan(request.user, pid), request.user)


@router.patch("/plans/{pid}", response=PlanOut)
def update_plan(request, pid: int, data: PlanPatch):
    plan = services.get_plan(request.user, pid, edit=True)
    changes = data.dict(exclude_unset=True)
    plan = services.save_plan(request.user, plan, changes)
    return plan_out(plan, request.user)


@router.delete("/plans/{pid}", response={204: None})
def delete_plan(request, pid: int, permanent: bool = False):
    """Soft delete (papelera). `permanent` is admin only and also works on deleted plans."""
    if permanent:
        plan = Plan.all_objects.filter(pk=pid).first()
        if plan is None:
            raise NotFound("Plan no encontrado")
        softdelete.delete(plan, request.user, permanent=True)
        return 204, None
    services.get_plan(request.user, pid, edit=True).soft_delete()
    return 204, None


@router.post("/plans/{pid}/restore", response=PlanOut)
def restore_plan(request, pid: int):
    plan = services.deleted_plans(request.user).filter(pk=pid).first()
    if plan is None:
        raise NotFound("Plan no encontrado")
    softdelete.restore(plan)
    return plan_out(plan, request.user)


@router.get("/plans/{pid}/timeline", response=PlanTimelineOut)
def plan_timeline(request, pid: int):
    """Totals, date range and filter catalogs of the whole plan (no issues: those come
    paged from /timeline/rows). Always limited to what the viewer can browse."""
    plan = services.get_plan(request.user, pid)
    return timeline.timeline_meta(request.user, plan)


def _filters(data: PlanTimelineFilters) -> timeline.TimelineFilters:
    return timeline.TimelineFilters(**data.dict())


@router.post("/plans/{pid}/timeline/groups", response=PlanGroupsOut)
def plan_timeline_groups(request, pid: int, data: PlanGroupsIn):
    plan = services.get_plan(request.user, pid)
    return timeline.timeline_groups(request.user, plan, _filters(data.filters), data.group_by)


@router.post("/plans/{pid}/timeline/rows", response=PlanRowsOut)
def plan_timeline_rows(request, pid: int, data: PlanRowsIn):
    """One page of one hierarchy node: the roots of a group (epics first) or the children
    of `parent_id`, by a stable cursor over (level, project, rank, id)."""
    plan = services.get_plan(request.user, pid)
    return timeline.timeline_rows(
        request.user, plan, _filters(data.filters), group_by=data.group_by, group=data.group,
        parent_id=data.parent_id, cursor=data.cursor, limit=data.limit)


@router.get("/plans/{pid}/conflicts", response=PlanConflictsOut)
def plan_conflicts(request, pid: int, limit: int = 100):
    """Date conflicts of every dependency in the plan, computed on the server."""
    plan = services.get_plan(request.user, pid)
    return timeline.plan_conflicts(request.user, plan, limit=limit)


VIEW_SCALES = ("weeks", "months", "quarters")
VIEW_MODES = ("expanded", "collapsed")
VIEW_MAX_EXCEPTIONS = 2000
VIEW_MAX_FILTER_IDS = 200
_NODE_KEY = re.compile(r"^(g:(all|[ptv]\d{1,18})|(all|[ptv]\d{1,18}):\d{1,18})$")


def _clean_view(data: PlanViewIn) -> dict:
    """Validated, normalized copy (unknown node keys dropped, ids deduplicated)."""
    timeline.check_group_by(data.group_by)
    if data.scale not in VIEW_SCALES:
        raise ValidationFailed("Escala desconocida", code="scale")
    filters = {}
    for name, ids in data.filters.dict().items():
        ids = list(dict.fromkeys(ids))
        if len(ids) > VIEW_MAX_FILTER_IDS or any(i < 0 for i in ids):
            raise ValidationFailed("Filtro no válido", code="filters")
        filters[name] = ids
    collapse = {}
    for group_by, c in data.collapse.items():
        if group_by not in timeline.GROUP_BY:
            raise ValidationFailed("Agrupación desconocida", code="collapse")
        if c.mode not in VIEW_MODES:
            raise ValidationFailed("Modo desconocido", code="collapse")
        keys = [k for k in dict.fromkeys(c.exceptions) if _NODE_KEY.match(k)]
        if len(keys) > VIEW_MAX_EXCEPTIONS:
            raise ValidationFailed(f"Como mucho {VIEW_MAX_EXCEPTIONS} excepciones por "
                                   "agrupación", code="collapse")
        collapse[group_by] = {"mode": c.mode, "exceptions": keys}
    return {"group_by": data.group_by, "scale": data.scale, "filters": filters,
            "collapse": collapse}


def _view_out(view: PlanView | None) -> dict:
    if view is None:
        return {"view": None, "updated_at": None}
    return {"view": view.config, "updated_at": view.updated_at.isoformat()}


@router.get("/plans/{pid}/view", response=PlanViewOut)
def get_plan_view(request, pid: int):
    """The viewer's own layout of the plan timeline (`view: null` = never saved)."""
    plan = services.get_plan(request.user, pid)
    return _view_out(PlanView.objects.filter(user=request.user, plan=plan).first())


@router.put("/plans/{pid}/view", response=PlanViewOut)
def put_plan_view(request, pid: int, data: PlanViewIn):
    plan = services.get_plan(request.user, pid)
    view, _ = PlanView.objects.update_or_create(
        user=request.user, plan=plan, defaults={"config": _clean_view(data)})
    return _view_out(view)


@router.delete("/plans/{pid}/view", response={204: None})
def delete_plan_view(request, pid: int):
    plan = services.get_plan(request.user, pid)
    PlanView.objects.filter(user=request.user, plan=plan).delete()
    return 204, None


# ------------------------------------------------------------------ capacity

@router.get("/plans/{pid}/capacity", response=PlanCapacityOut)
def plan_capacity(request, pid: int, iterations: int = 8):
    plan = services.get_plan(request.user, pid)
    return services.plan_capacity(request.user, plan, count=iterations)


@router.put("/plans/{pid}/capacity", response=PlanCapacityOut)
def set_plan_capacity(request, pid: int, data: PlanCapacityIn, iterations: int = 8):
    """Override a team's capacity for one sprint / fixed iteration (`capacity: null`
    removes the override)."""
    plan = services.get_plan(request.user, pid, edit=True)
    services.set_capacity(request.user, plan, data.team_id, sprint_id=data.sprint_id,
                          iteration_start=data.iteration_start, capacity=data.capacity)
    return services.plan_capacity(request.user, plan, count=iterations)


# ------------------------------------------------------------------ releases

@router.get("/plans/{pid}/versions", response=list[PlanVersionOption])
def plan_version_options(request, pid: int):
    """Versions of the plan's (visible) projects, for building cross-project releases."""
    plan = services.get_plan(request.user, pid)
    qs = Version.objects.filter(project__in=services.viewer_projects(request.user, plan)) \
        .exclude(status=Version.Status.ARCHIVED).select_related("project") \
        .order_by("project__key", "position", "id")
    return [{"id": v.id, "name": v.name, "status": v.status, "release_date": v.release_date,
             "project": _project_ref(v.project)} for v in qs]


@router.get("/plans/{pid}/releases", response=list[PlanReleaseOut])
def list_releases(request, pid: int):
    plan = services.get_plan(request.user, pid)
    return [services.release_out(request.user, r) for r in plan.releases.all()]


@router.post("/plans/{pid}/releases", response={201: PlanReleaseOut})
def create_release(request, pid: int, data: PlanReleaseIn):
    plan = services.get_plan(request.user, pid, edit=True)
    release = services.save_release(request.user, plan, PlanRelease(), data.dict())
    return 201, services.release_out(request.user, release)


@router.patch("/plans/{pid}/releases/{rid}", response=PlanReleaseOut)
def update_release(request, pid: int, rid: int, data: PlanReleasePatch):
    plan = services.get_plan(request.user, pid, edit=True)
    release = services.save_release(request.user, plan, services.get_release(plan, rid),
                                    data.dict(exclude_unset=True))
    return services.release_out(request.user, release)


@router.delete("/plans/{pid}/releases/{rid}", response={204: None})
def delete_release(request, pid: int, rid: int):
    """Only the grouping goes away; the project versions and their issues are untouched."""
    plan = services.get_plan(request.user, pid, edit=True)
    services.get_release(plan, rid).delete()
    return 204, None


# ------------------------------------------------------------------ teams

def _team_qs(qs):
    return qs.select_related("created_by").prefetch_related("members").annotate(
        n_issues=Count("issues", distinct=True), n_plans=Count("plan_teams", distinct=True))


def _get_team(user, tid: int, *, edit: bool = False) -> Team:
    team = Team.objects.filter(pk=tid).first()
    if team is None:
        raise NotFound("Equipo no encontrado")
    if edit and not services.can_edit_team(user, team):
        raise Forbidden("Solo sus miembros, quien lo creó o un administrador pueden modificarlo")
    return team


@router.get("/teams", response=list[TeamOut])
def list_teams(request, q: str = "", deleted: bool = False):
    qs = services.deleted_teams(request.user) if deleted else Team.objects.all()
    if q:
        qs = qs.filter(name__icontains=q.strip())
    return [team_out(t, request.user) for t in _team_qs(qs)]


@router.post("/teams", response={201: TeamOut})
def create_team(request, data: TeamIn):
    team = services.save_team(request.user, Team(), data.dict())
    return 201, team_out(_team_qs(Team.objects.filter(pk=team.pk)).get(), request.user)


@router.get("/teams/{tid}", response=TeamOut)
def get_team(request, tid: int):
    _get_team(request.user, tid)
    return team_out(_team_qs(Team.objects.filter(pk=tid)).get(), request.user)


@router.patch("/teams/{tid}", response=TeamOut)
def update_team(request, tid: int, data: TeamPatch):
    team = _get_team(request.user, tid, edit=True)
    services.save_team(request.user, team, data.dict(exclude_unset=True))
    return team_out(_team_qs(Team.objects.filter(pk=tid)).get(), request.user)


@router.delete("/teams/{tid}", response={204: None})
def delete_team(request, tid: int, permanent: bool = False):
    """Soft delete: issues keep showing their team, it just cannot be chosen any more.
    `permanent` (admin) fails with 409 while issues still use it."""
    if permanent:
        team = Team.all_objects.filter(pk=tid).first()
        if team is None:
            raise NotFound("Equipo no encontrado")
        softdelete.delete(team, request.user, permanent=True)
        return 204, None
    _get_team(request.user, tid, edit=True).soft_delete()
    return 204, None


@router.post("/teams/{tid}/restore", response=TeamOut)
def restore_team(request, tid: int):
    team = services.deleted_teams(request.user).filter(pk=tid).first()
    if team is None:
        raise NotFound("Equipo no encontrado")
    softdelete.restore(team, "Ya existe un equipo activo con ese nombre")
    return team_out(_team_qs(Team.objects.filter(pk=tid)).get(), request.user)
