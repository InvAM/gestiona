"""Cronograma de un plan sin tope de incidencias.

Diseño: **carga por niveles + paginación por cursor**. El cliente nunca recibe el plan entero:

* ``timeline_meta``: totales, rango de fechas y catálogos de filtros (equipos, versiones,
  estados, responsables) calculados en el servidor sobre el plan completo.
* ``timeline_groups``: grupos (proyecto, equipo, versión o ninguno) con su conteo total,
  ya con los filtros aplicados en el servidor.
* ``timeline_rows``: un *nodo* de la jerarquía, es decir, las raíces de un grupo (incidencias
  cuyo padre no está en el grupo filtrado: épicas primero) o las hijas de una incidencia al
  expandirla. Se pagina por cursor estable sobre ``(-nivel, proyecto, rank, id)``: una
  inserción o un cambio en otra página no duplica ni salta filas, y no hay OFFSET que
  recorrer a medida que el usuario avanza.
* Cada página trae las dependencias que tocan sus filas, con los datos del otro extremo
  aunque no esté cargado, y el conflicto ya calculado. ``plan_conflicts`` resume en el
  servidor todos los conflictos de fechas del plan.

El número de consultas por petición no depende del tamaño del plan (solo del número de
proyectos, por los permisos que ya se cachean por usuario y proyecto).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Q, QuerySet
from django.db.models.functions import Coalesce

from apps.core.errors import ValidationFailed
from apps.core.schemas import priority_ref, status_ref, type_ref, user_ref
from apps.issues.models import Issue, IssueLink, IssueLinkType
from apps.projects.models import Perm, Version
from apps.projects.permissions import project_perms
from apps.workflows.models import Status

from . import services
from .models import Plan, Team

User = get_user_model()

PAGE_SIZE = 100
PAGE_MAX = 500
CONFLICTS_MAX = 200
NONE = 0  # filter / group value meaning "empty" (sin equipo, sin asignar, sin versión)
GROUP_BY = ("none", "project", "team", "version")

FixVersion = Issue.fix_versions.through


# --------------------------------------------------------------------------- filters

@dataclass
class TimelineFilters:
    project_ids: list[int] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    status_ids: list[int] = field(default_factory=list)
    assignee_ids: list[int] = field(default_factory=list)
    version_ids: list[int] = field(default_factory=list)


def _with_none(column: str, values: list[int]) -> Q:
    ids = [v for v in values if v != NONE]
    q = Q(**{f"{column}__in": ids}) if ids else Q(pk__in=[])
    if NONE in values:
        q |= Q(**{f"{column}__isnull": True})
    return q


def _has_versions() -> Exists:
    return Exists(FixVersion.objects.filter(issue_id=OuterRef("pk")))


def apply_filters(qs: QuerySet[Issue], f: TimelineFilters) -> QuerySet[Issue]:
    if f.project_ids:
        qs = qs.filter(project_id__in=f.project_ids)
    if f.team_ids:
        qs = qs.filter(_with_none("team_id", f.team_ids))
    if f.status_ids:
        qs = qs.filter(status_id__in=f.status_ids)
    if f.assignee_ids:
        qs = qs.filter(_with_none("assignee_id", f.assignee_ids))
    if f.version_ids:
        ids = [v for v in f.version_ids if v != NONE]
        q = Q(pk__in=FixVersion.objects.filter(version_id__in=ids).values("issue_id")) \
            if ids else Q(pk__in=[])
        if NONE in f.version_ids:
            q |= Q(~_has_versions())
        qs = qs.filter(q)
    return qs


def check_group_by(group_by: str) -> str:
    if group_by not in GROUP_BY:
        raise ValidationFailed("Agrupación desconocida", code="group_by")
    return group_by


def group_q(group_by: str, key: str | None) -> Q:
    """`key` as returned by `timeline_groups` ("all", "p12", "t0", "v7"…)."""
    check_group_by(group_by)
    if group_by == "none":
        if key not in (None, "", "all"):
            raise ValidationFailed("Grupo inválido", code="group")
        return Q()
    prefix = {"project": "p", "team": "t", "version": "v"}[group_by]
    try:
        if not key or key[0] != prefix:
            raise ValueError
        gid = int(key[1:])
    except ValueError as e:
        raise ValidationFailed("Grupo inválido", code="group") from e
    if group_by == "project":
        return Q(project_id=gid)
    if group_by == "team":
        return Q(team__isnull=True) if gid == NONE else Q(team_id=gid)
    if gid == NONE:
        return Q(~_has_versions())
    return Q(pk__in=FixVersion.objects.filter(version_id=gid).values("issue_id"))


# --------------------------------------------------------------------------- cursor

def encode_cursor(issue: Issue) -> str:
    raw = json.dumps([issue.plan_lvl, issue.plan_pkey, issue.rank, issue.id],
                     separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str, str, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        lvl, pkey, rank, pk = json.loads(raw)
        if not (isinstance(lvl, int) and isinstance(pk, int) and isinstance(pkey, str)
                and isinstance(rank, str)):
            raise ValueError
    except (ValueError, TypeError, binascii.Error) as e:
        raise ValidationFailed("Cursor inválido", code="cursor") from e
    return lvl, pkey, rank, pk


def _ordered(qs: QuerySet[Issue]) -> QuerySet[Issue]:
    # epics first (their children come on expand), then project, rank and id
    return qs.annotate(plan_lvl=F("issue_type__level"), plan_pkey=F("project__key")) \
        .order_by("-plan_lvl", "plan_pkey", "rank", "id")


def _after(cursor: str) -> Q:
    lvl, pkey, rank, pk = decode_cursor(cursor)
    return (Q(plan_lvl__lt=lvl) | Q(plan_lvl=lvl, plan_pkey__gt=pkey)
            | Q(plan_lvl=lvl, plan_pkey=pkey, rank__gt=rank)
            | Q(plan_lvl=lvl, plan_pkey=pkey, rank=rank, id__gt=pk))


# --------------------------------------------------------------------------- meta

def _date_range(scope: QuerySet[Issue]) -> dict:
    agg = scope.aggregate(a=Min("start_date"), b=Min("due_date"),
                          c=Max("start_date"), d=Max("due_date"))
    lows = [d for d in (agg["a"], agg["b"]) if d]
    highs = [d for d in (agg["c"], agg["d"]) if d]
    return {"start": min(lows) if lows else None, "end": max(highs) if highs else None}


def timeline_meta(user, plan: Plan) -> dict:
    """Totals, date range and filter catalogs over the whole plan the viewer may see."""
    scope, error = services.plan_scope(user, plan)
    project_ids = list(services.viewer_projects(user, plan).values_list("id", flat=True))
    plan_team_ids = {pt.team_id for pt in services.plan_teams(plan)}
    teams = Team._base_manager.filter(
        Q(id__in=scope.filter(team__isnull=False).values("team_id"))
        | Q(id__in=plan_team_ids, deleted_at__isnull=True)
    ).order_by("name", "id")
    versions = Version._base_manager.filter(
        Q(project_id__in=project_ids, deleted_at__isnull=True)
        | Q(id__in=FixVersion.objects.filter(issue__in=scope).values("version_id"),
            project_id__in=project_ids)
    ).order_by("release_date", "position", "id")
    statuses = Status.objects.filter(id__in=scope.values("status_id")).order_by("id")
    assignees = User.objects.filter(id__in=scope.filter(assignee__isnull=False)
                                    .values("assignee_id")).order_by("full_name", "id")
    return {
        "total": scope.count(),
        "date_range": _date_range(scope),
        "teams": [{"id": t.id, "name": t.name, "in_plan": t.id in plan_team_ids,
                   "deleted": t.deleted_at is not None} for t in teams],
        "versions": [{"id": v.id, "name": v.name, "project_id": v.project_id,
                      "status": v.status, "release_date": v.release_date,
                      "deleted": v.deleted_at is not None} for v in versions],
        "statuses": [status_ref(s) for s in statuses],
        "assignees": [user_ref(u) for u in assignees],
        "dependency_link_types": list(IssueLinkType.objects.filter(is_dependency=True)),
        "page_size": PAGE_SIZE,
        "page_max": PAGE_MAX,
        "filter_error": error,
    }


# --------------------------------------------------------------------------- groups

def timeline_groups(user, plan: Plan, filters: TimelineFilters, group_by: str) -> dict:
    check_group_by(group_by)
    scope, _ = services.plan_scope(user, plan)
    qs = apply_filters(scope, filters)
    total = qs.count()
    groups: list[dict] = []
    if group_by == "none":
        groups = [{"key": "all", "label": "Todas", "count": total}] if total else []
    elif group_by == "project":
        counts = dict(qs.order_by().values_list("project_id").annotate(n=Count("id")))
        groups = [{"key": f"p{p.id}", "label": f"{p.name} ({p.key})", "count": counts[p.id]}
                  for p in services.viewer_projects(user, plan) if counts.get(p.id)]
    elif group_by == "team":
        counts = dict(qs.order_by().values_list("team_id").annotate(n=Count("id")))
        plan_team_ids = {pt.team_id for pt in services.plan_teams(plan)}
        named = {t.id: t for t in Team._base_manager.filter(id__in=[k for k in counts if k])}
        rows = []
        for tid, n in counts.items():
            team = named.get(tid)
            order = 2 if team is None else 0 if tid in plan_team_ids else 1
            rows.append((order, team.name if team else "Sin equipo", tid or NONE, n))
        groups = [{"key": f"t{tid}", "label": label, "count": n}
                  for _, label, tid, n in sorted(rows, key=lambda r: (r[0], r[1].lower()))]
    else:
        counts = dict(FixVersion.objects.filter(issue__in=qs).order_by()
                      .values_list("version_id").annotate(n=Count("issue_id")))
        none = qs.filter(Q(~_has_versions())).count()
        versions = Version._base_manager.filter(id__in=list(counts)).select_related("project")
        rows = sorted(versions, key=lambda v: (v.release_date is None,
                                               v.release_date or 0, v.name.lower(), v.id))
        groups = [{"key": f"v{v.id}", "label": f"{v.name} · {v.project.key}",
                   "count": counts[v.id]} for v in rows]
        if none:
            groups.append({"key": f"v{NONE}", "label": "Sin versión", "count": none})
    return {"group_by": group_by, "total": total, "groups": groups}


# --------------------------------------------------------------------------- rows

def _end(i: Issue):
    return i.due_date or i.start_date


def _start(i: Issue):
    return i.start_date or i.due_date


def _rollups(scope: QuerySet[Issue], ids: list[int]) -> dict[int, list]:
    """[min, max] of the dates of each issue's descendants (children and grandchildren),
    over the whole plan: a parent without dates still gets a bar while collapsed."""
    out: dict[int, list] = {}

    def merge(rows):
        for pid, a, b, c, d in rows:
            lows = [x for x in (a, b) if x]
            highs = [x for x in (c, d) if x]
            if not lows:
                continue
            cur = out.setdefault(pid, [min(lows), max(highs)])
            cur[0], cur[1] = min(cur[0], min(lows)), max(cur[1], max(highs))

    aggs = (Min("start_date"), Min("due_date"), Max("start_date"), Max("due_date"))
    merge(scope.filter(parent_id__in=ids).order_by().values_list("parent_id")
          .annotate(*aggs))
    # a plain join on the parent (not a semi-join on the scope again): the planner keeps
    # it on the parent_id index whatever its estimates
    merge(scope.filter(parent__parent_id__in=ids, parent__is_archived=False).order_by()
          .values_list("parent__parent_id").annotate(*aggs))
    return out


def _end_ref(i: Issue, perms) -> dict:
    p = perms(i.project)
    return {"id": i.id, "key": i.key, "summary": i.summary, "project_id": i.project_id,
            "start_date": i.start_date, "due_date": i.due_date,
            "can_link": Perm.LINK_ISSUES.value in p}


def dependencies_for(user, scope: QuerySet[Issue], ids: list[int], perms=None) -> list[dict]:
    """Dependency links touching `ids` whose both ends the viewer may see in the plan. Each
    end comes with its dates, so arrows and conflicts work when the other end is not
    loaded on the client."""
    perms = perms or _perm_cache(user)
    if not ids:
        return []
    links = IssueLink.objects.filter(
        Q(source_id__in=ids) | Q(target_id__in=ids), link_type__is_dependency=True,
        source__in=scope, target__in=scope,
    ).select_related("link_type", "source__project", "target__project").order_by("id")
    out = []
    for link in links:
        blocker, blocked = link.source, link.target
        end, start = _end(blocker), _start(blocked)
        out.append({
            "id": link.id, "link_type_id": link.link_type_id, "label": link.link_type.outward,
            "blocker_id": blocker.id, "blocked_id": blocked.id,
            "blocker": _end_ref(blocker, perms), "blocked": _end_ref(blocked, perms),
            "conflict": bool(end and start and end > start),
        })
    return out


def _perm_cache(user):
    cache: dict[int, set[str]] = {}

    def get(project):
        if project.id not in cache:
            cache[project.id] = project_perms(user, project)
        return cache[project.id]

    return get


def timeline_rows(user, plan: Plan, filters: TimelineFilters, *, group_by: str = "none",
                  group: str | None = None, parent_id: int | None = None,
                  cursor: str | None = None, limit: int = PAGE_SIZE) -> dict:
    """One page of a node: the roots of `group` or, with `parent_id`, that issue's children
    inside the same (filtered) group."""
    if not 1 <= limit <= PAGE_MAX:
        raise ValidationFailed(f"El tamaño de página va de 1 a {PAGE_MAX}", code="limit")
    scope, _ = services.plan_scope(user, plan)
    node_set = apply_filters(scope, filters).filter(group_q(group_by, group))
    if parent_id is not None:
        node = node_set.filter(parent_id=parent_id)
    else:
        node = node_set.filter(~Exists(node_set.filter(pk=OuterRef("parent_id"))))
    total = node.count() if not cursor else None
    page = _ordered(node)
    if cursor:
        page = page.filter(_after(cursor))
    rows = list(page.select_related("issue_type", "status", "priority", "assignee", "project")
                .prefetch_related("fix_versions")[: limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    ids = [i.id for i in rows]
    children = dict(node_set.filter(parent_id__in=ids).order_by().values_list("parent_id")
                    .annotate(n=Count("id"))) if ids else {}
    rollups = _rollups(scope, ids) if ids else {}
    perms = _perm_cache(user)
    out = []
    for i in rows:
        p = perms(i.project)
        roll = rollups.get(i.id)
        out.append({
            "id": i.id, "key": i.key, "summary": i.summary, "project_id": i.project_id,
            "type": type_ref(i.issue_type), "status": status_ref(i.status),
            "priority": priority_ref(i.priority), "assignee": user_ref(i.assignee),
            "parent_id": i.parent_id, "team_id": i.team_id,
            "sprint_id": i.sprint_id, "fix_version_ids": [v.id for v in i.fix_versions.all()],
            "start_date": i.start_date, "due_date": i.due_date,
            "story_points": i.story_points, "original_estimate": i.original_estimate,
            "can_edit": Perm.EDIT_ISSUES.value in p, "can_link": Perm.LINK_ISSUES.value in p,
            "children_count": children.get(i.id, 0),
            "rollup_start": roll[0] if roll else None, "rollup_end": roll[1] if roll else None,
        })
    return {
        "rows": out, "total": total,
        "next_cursor": encode_cursor(rows[-1]) if more else None,
        "dependencies": dependencies_for(user, scope, ids, perms),
    }


# --------------------------------------------------------------------------- conflicts

def plan_conflicts(user, plan: Plan, *, limit: int = 100) -> dict:
    """Every date conflict of the plan (blocker ends after the blocked issue starts),
    computed in SQL over the whole plan the viewer may see, not over what is loaded."""
    limit = max(1, min(limit, CONFLICTS_MAX))
    scope, _ = services.plan_scope(user, plan)
    qs = IssueLink.objects.filter(
        link_type__is_dependency=True, source__in=scope, target__in=scope,
    ).annotate(
        b_end=Coalesce("source__due_date", "source__start_date"),
        t_start=Coalesce("target__start_date", "target__due_date"),
    ).filter(b_end__gt=F("t_start"))
    count = qs.count()
    perms = _perm_cache(user)
    items = []
    if count:
        for link in qs.select_related("link_type", "source__project", "target__project") \
                .order_by("t_start", "id")[:limit]:
            items.append({
                "id": link.id, "link_type_id": link.link_type_id,
                "label": link.link_type.outward,
                "blocker_id": link.source_id, "blocked_id": link.target_id,
                "blocker": _end_ref(link.source, perms), "blocked": _end_ref(link.target, perms),
                "conflict": True,
            })
    return {"count": count, "conflicts": items, "truncated": count > len(items)}
