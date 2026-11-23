"""«Lista» view: spreadsheet-like issue table of a project.

* `GET  /projects/{key}/list/meta`    columns (standard + custom fields), groupings, quick filters
* `POST /projects/{key}/list`         one page of rows for a JQL (optionally grouped), or the
                                      children of an issue (`parent_id`, hierarchy)
* `POST /projects/{key}/list/groups`  group headers with counts for a JQL
* `POST /projects/{key}/list/rows`    fresh rows by id (after an edit or a realtime event)
* `GET|PUT|DELETE /projects/{key}/list/config`  the user's layout for the project

Edits go through the regular issue endpoints (PATCH /issues/{key}, transitions, bulk).
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from django.db.models import BigIntegerField, Case, Count, F, IntegerField, Value, When
from django.http import HttpResponse
from ninja import Router, Schema

from apps.core.errors import NotFound, ValidationFailed
from apps.core.schemas import UserRef, priority_ref, status_ref, type_ref, user_ref
from apps.issues.models import HISTORY_FIELD_LABELS, Issue, IssueType
from apps.projects.api import get_project
from apps.projects.permissions import visible_projects
from apps.search.jql import compile_jql, search_issues

from . import columns as cols
from .models import ListViewConfig

router = Router(tags=["list"])

PAGE_MAX = 500
ROWS_MAX = 500

GROUP_LABELS = {
    "status": HISTORY_FIELD_LABELS["status"],
    "assignee": HISTORY_FIELD_LABELS["assignee"],
    "epic": cols.EXTRA_LABELS["epic"],
    "priority": HISTORY_FIELD_LABELS["priority"],
    "sprint": HISTORY_FIELD_LABELS["sprint"],
    "type": HISTORY_FIELD_LABELS["issue_type"],
}
NONE_LABELS = {"assignee": "Sin asignar", "epic": "Sin épica", "sprint": "Sin sprint"}

# (id, label, JQL). Board quick filters are appended as "board:<id>".
QUICK_FILTERS = [
    ("mine", "Mis incidencias", "assignee = currentUser()"),
    ("unassigned", "Sin asignar", "assignee is EMPTY"),
    ("unresolved", "Sin resolver", "resolution = Unresolved"),
    ("recent", "Actualizadas recientemente", "updated >= -1w"),
    ("flagged", "Marcadas", "flagged = true"),
    ("overdue", "Vencidas", "due < now() AND resolution = Unresolved"),
]


# ------------------------------------------------------------------ schemas

class ListViewColumnOut(Schema):
    id: str
    label: str
    kind: str
    field: str | None
    sort: str | None
    width: int
    default: bool
    custom_field_id: int | None = None
    custom_kind: str | None = None


class ListViewChoice(Schema):
    value: str
    label: str


class ListViewQuickFilter(Schema):
    id: str
    label: str
    jql: str
    description: str = ""


class ListViewMetaOut(Schema):
    columns: list[ListViewColumnOut]
    group_by: list[ListViewChoice]
    quick_filters: list[ListViewQuickFilter]
    page_max: int
    bulk_max: int


class ListViewQueryIn(Schema):
    jql: str = ""
    start: int = 0
    limit: int = 100
    group_by: str | None = None
    parent_id: int | None = None


class ListViewRow(Schema):
    id: int
    key: str
    project_key: str
    summary: str
    type: dict
    status: dict
    priority: dict
    resolution: dict | None
    assignee: UserRef | None
    reporter: UserRef | None
    parent: dict | None
    epic: dict | None
    labels: list[str]
    components: list[dict]
    fix_versions: list[dict]
    affects_versions: list[dict]
    sprint: dict | None
    story_points: float | None
    original_estimate: int | None
    remaining_estimate: int | None
    time_spent: int
    start_date: str | None
    due_date: str | None
    flagged: bool
    custom_fields: dict
    created_at: str
    updated_at: str
    resolved_at: str | None
    is_archived: bool
    children_count: int
    permissions: list[str]
    group: int | None = None
    team: dict | None = None


class ListViewPageOut(Schema):
    total: int
    start: int
    limit: int
    rows: list[ListViewRow]
    users: dict[str, UserRef]


class ListViewGroupsIn(Schema):
    jql: str = ""
    group_by: str


class ListViewGroup(Schema):
    key: int | None
    label: str
    count: int
    ref: Any = None


class ListViewGroupsOut(Schema):
    group_by: str
    total: int
    groups: list[ListViewGroup]


class ListViewRowsIn(Schema):
    ids: list[int]
    group_by: str | None = None


class ListViewRowsOut(Schema):
    rows: list[ListViewRow]
    users: dict[str, UserRef]


class ListViewColumnPref(Schema):
    id: str
    width: int | None = None


class ListViewConfigIn(Schema):
    columns: list[ListViewColumnPref] = []
    group_by: str | None = None
    jql: str | None = None
    quick_filters: list[str] = []
    collapsed: list[str] = []


class ListViewConfigOut(Schema):
    config: dict | None
    updated_at: str | None


# ------------------------------------------------------------------ helpers

def _check_group(group_by: str | None) -> str | None:
    if group_by in (None, "", "none"):
        return None
    if group_by not in GROUP_LABELS:
        raise ValidationFailed("Agrupación no válida", code="group_by")
    return group_by


def _status_order(project) -> list[int]:
    from apps.issues.services import workflow_for

    ordered: list[int] = []
    for t in project.issue_types.all():
        for s in workflow_for(project, t).ordered_statuses():
            if s.id not in ordered:
                ordered.append(s.id)
    return ordered


def _group_expr(group_by: str):
    if group_by == "epic":
        return Case(
            When(parent__issue_type__level=IssueType.Level.EPIC, then=F("parent_id")),
            When(issue_type__level=IssueType.Level.SUBTASK,
                 parent__parent__issue_type__level=IssueType.Level.EPIC,
                 then=F("parent__parent_id")),
            default=Value(None), output_field=BigIntegerField(),
        )
    return F({"status": "status_id", "assignee": "assignee_id", "priority": "priority_id",
              "sprint": "sprint_id", "type": "issue_type_id"}[group_by])


def _group_order(group_by: str, project) -> list:
    if group_by == "status":
        ids = _status_order(project)
        return [Case(*[When(status_id=sid, then=Value(n)) for n, sid in enumerate(ids)],
                     default=Value(len(ids)), output_field=IntegerField()),
                F("status__name").asc()]
    if group_by == "assignee":
        return [F("assignee__full_name").asc(nulls_last=True),
                F("assignee__email").asc(nulls_last=True)]
    if group_by == "priority":
        return [F("priority__position").asc(), F("priority_id").asc()]
    if group_by == "type":
        return [F("issue_type__position").asc(), F("issue_type_id").asc()]
    if group_by == "sprint":
        return [Case(When(sprint__state="active", then=Value(0)),
                     When(sprint__state="future", then=Value(1)),
                     When(sprint__state="closed", then=Value(2)),
                     default=Value(3), output_field=IntegerField()),
                F("sprint__position").asc(nulls_last=True), F("sprint_id").asc(nulls_last=True)]
    return [F("lv_group").asc(nulls_last=True)]  # epic


def _base(user, project, jql: str):
    """Issues of `project` matching `jql` (visibility + archived rules of the search), with
    the JQL ORDER BY. Wrapped in `pk__in` so joins in the JQL never duplicate rows."""
    search = search_issues(user, jql)
    order = list(search.query.order_by)
    base = Issue.objects.filter(project=project, is_archived=False,
                                pk__in=search.order_by().values("pk"))
    return base, order


def _page(rows, ctx, start, limit, total):
    return {"total": total, "start": start, "limit": limit, "rows": rows,
            "users": ctx.users()}


# ------------------------------------------------------------------ endpoints

@router.get("/projects/{key}/list/meta", response=ListViewMetaOut)
def list_meta(request, key: str):
    from apps.boards.models import QuickFilter
    from apps.issues.api import BULK_LIMIT

    p = get_project(request.user, key)
    quick = [{"id": i, "label": label, "jql": jql, "description": ""}
             for i, label, jql in QUICK_FILTERS]
    for qf in QuickFilter.objects.filter(board__project=p).order_by("board_id", "position", "id"):
        quick.append({"id": f"board:{qf.id}", "label": qf.name, "jql": qf.jql,
                      "description": qf.description})
    return {
        "columns": cols.column_catalog(p),
        "group_by": [{"value": k, "label": v} for k, v in GROUP_LABELS.items()],
        "quick_filters": quick,
        "page_max": PAGE_MAX,
        "bulk_max": BULK_LIMIT,
    }


@router.post("/projects/{key}/list", response=ListViewPageOut)
def list_page(request, key: str, data: ListViewQueryIn):
    p = get_project(request.user, key)
    limit = max(1, min(data.limit, PAGE_MAX))
    start = max(0, data.start)
    ctx = cols.RowContext(request.user)
    if data.parent_id is not None:
        parent = Issue.objects.filter(pk=data.parent_id, project=p).first()
        if parent is None:
            raise NotFound("Incidencia no encontrada")
        # archived children are shown read-only under their parent
        qs = Issue.objects.filter(parent=parent, project__in=visible_projects(request.user))
        total = qs.count()
        rows = cols.row_queryset(qs).order_by("rank", "id")[start:start + limit]
        return _page([cols.row_out(i, ctx) for i in rows], ctx, start, limit, total)

    group_by = _check_group(data.group_by)
    base, order = _base(request.user, p, data.jql)
    total = base.count()
    # Two steps: sort and slice narrow rows, then load that page with its relations.
    # Joining a dozen tables for every matching row only to keep `limit` of them is what
    # made large projects slow (the sort keys only need the joins of the ORDER BY).
    if group_by:
        base = base.annotate(lv_group=_group_expr(group_by))
        base = base.order_by(*_group_order(group_by, p), *order)
    else:
        base = base.order_by(*order)
    ids = list(base.values_list("pk", flat=True)[start:start + limit])
    qs = cols.row_queryset(Issue.objects.filter(pk__in=ids))
    if group_by:
        qs = qs.annotate(lv_group=_group_expr(group_by))
    by_id = {i.id: i for i in qs}
    rows = [cols.row_out(by_id[i], ctx, getattr(by_id[i], "lv_group", None))
            for i in ids if i in by_id]
    return _page(rows, ctx, start, limit, total)


@router.post("/projects/{key}/list/groups", response=ListViewGroupsOut)
def list_groups(request, key: str, data: ListViewGroupsIn):
    from apps.boards.api import epic_ref
    from apps.boards.models import Sprint
    from apps.issues.models import Priority
    from apps.workflows.models import Status

    p = get_project(request.user, key)
    group_by = _check_group(data.group_by)
    if group_by is None:
        raise ValidationFailed("Elige una agrupación", code="group_by")
    base, _ = _base(request.user, p, data.jql)
    counts = {r["lv_group"]: r["n"] for r in base.annotate(lv_group=_group_expr(group_by))
              .values("lv_group").annotate(n=Count("id")).order_by()}
    ids = [k for k in counts if k is not None]
    groups: list[dict] = []
    if group_by == "status":
        order = {sid: n for n, sid in enumerate(_status_order(p))}
        objs = sorted(Status.all_objects.filter(id__in=ids),
                      key=lambda s: (order.get(s.id, len(order)), s.name))
        groups = [{"key": s.id, "label": s.name, "ref": status_ref(s)} for s in objs]
    elif group_by == "assignee":
        from django.contrib.auth import get_user_model

        objs = sorted(get_user_model().objects.filter(id__in=ids),
                      key=lambda u: (u.display_name.lower(), u.id))
        groups = [{"key": u.id, "label": u.display_name, "ref": user_ref(u)} for u in objs]
    elif group_by == "priority":
        objs = Priority.all_objects.filter(id__in=ids).order_by("position", "id")
        groups = [{"key": x.id, "label": x.name, "ref": priority_ref(x)} for x in objs]
    elif group_by == "type":
        objs = IssueType.all_objects.filter(id__in=ids).order_by("position", "id")
        groups = [{"key": t.id, "label": t.name, "ref": type_ref(t)} for t in objs]
    elif group_by == "sprint":
        rank = {"active": 0, "future": 1, "closed": 2}
        objs = sorted(Sprint.objects.filter(id__in=ids),
                      key=lambda s: (rank.get(s.state, 3), s.position, s.id))
        groups = [{"key": s.id, "label": s.name,
                   "ref": {"id": s.id, "name": s.name, "state": s.state}} for s in objs]
    elif group_by == "epic":
        objs = Issue.objects.filter(id__in=ids).order_by("number")
        groups = [{"key": e.id, "label": f"{e.key} {e.summary}", "ref": epic_ref(e)}
                  for e in objs]
    for g in groups:
        g["count"] = counts.get(g["key"], 0)
    if None in counts:
        none = {"key": None, "label": NONE_LABELS.get(group_by, "Ninguno"),
                "count": counts[None], "ref": None}
        groups.append(none)
    return {"group_by": group_by, "total": sum(counts.values()), "groups": groups}


@router.post("/projects/{key}/list/rows", response=ListViewRowsOut)
def list_rows(request, key: str, data: ListViewRowsIn):
    """Current state of some rows (ids that are gone or moved away are simply missing)."""
    p = get_project(request.user, key)
    ids = list(dict.fromkeys(data.ids))[:ROWS_MAX]
    group_by = _check_group(data.group_by)
    qs = cols.row_queryset(Issue.objects.filter(project=p, id__in=ids))
    if group_by:
        qs = qs.annotate(lv_group=_group_expr(group_by))
    ctx = cols.RowContext(request.user)
    rows = [cols.row_out(i, ctx, getattr(i, "lv_group", None)) for i in qs]
    return {"rows": rows, "users": ctx.users()}


CONFIG_MAX_BYTES = 32_000
_COL_ID = re.compile(r"^(cf:\d{1,10}|[a-z][a-z_]{0,39})$")
_GROUP_KEY = re.compile(r"^[a-z]{1,20}:(none|\d{1,18})$")


def _clean_config(data: ListViewConfigIn) -> dict:
    seen: set[str] = set()
    columns = []
    if len(data.columns) > 300:
        raise ValidationFailed("Demasiadas columnas", code="columns")
    for c in data.columns:
        if not _COL_ID.match(c.id):
            raise ValidationFailed(f"Columna no válida: {c.id[:50]}", code="columns")
        if c.id in seen:
            continue
        seen.add(c.id)
        width = None if c.width is None else max(40, min(int(c.width), 1200))
        columns.append({"id": c.id, "width": width})
    jql = (data.jql or "").strip()
    if len(jql) > 4000:
        raise ValidationFailed("El JQL es demasiado largo", code="jql")
    quick = [q for q in dict.fromkeys(data.quick_filters) if re.fullmatch(r"[a-z]+(:\d+)?", q)]
    collapsed = [g for g in dict.fromkeys(data.collapsed) if _GROUP_KEY.match(g)][:500]
    out = {"columns": columns, "group_by": _check_group(data.group_by), "jql": jql,
           "quick_filters": quick[:50], "collapsed": collapsed}
    if len(json.dumps(out)) > CONFIG_MAX_BYTES:
        raise ValidationFailed("La configuración es demasiado grande", code="config")
    return out


def _config_out(cfg: ListViewConfig | None) -> dict:
    if cfg is None:
        return {"config": None, "updated_at": None}
    return {"config": cfg.config, "updated_at": cfg.updated_at.isoformat()}


@router.get("/projects/{key}/list/config", response=ListViewConfigOut)
def get_config(request, key: str):
    p = get_project(request.user, key)
    return _config_out(ListViewConfig.objects.filter(user=request.user, project=p).first())


@router.put("/projects/{key}/list/config", response=ListViewConfigOut)
def put_config(request, key: str, data: ListViewConfigIn):
    p = get_project(request.user, key)
    cfg, _ = ListViewConfig.objects.update_or_create(
        user=request.user, project=p, defaults={"config": _clean_config(data)},
    )
    return _config_out(cfg)


@router.delete("/projects/{key}/list/config", response={204: None})
def delete_config(request, key: str):
    p = get_project(request.user, key)
    ListViewConfig.objects.filter(user=request.user, project=p).delete()
    return 204, None


# ------------------------------------------------------------------ CSV (GET /search/export)

EXPORT_MAX = 10000


def export_columns_csv(user, jql: str, columns: str) -> HttpResponse:
    """CSV of `jql` with the given column ids (the list view's visible columns), same
    format as the default export (UTF-8 BOM, same filename)."""
    ids = [c.strip() for c in columns.split(",") if c.strip()]
    if not ids or len(ids) > 300:
        raise ValidationFailed("Indica entre 1 y 300 columnas", code="columns")
    ids, cfs = cols.resolve_export_columns(list(dict.fromkeys(ids)))
    compile_jql(jql, user=user)  # 400 with the JQL error before building anything
    search = search_issues(user, jql)
    qs = cols.row_queryset(Issue.objects.filter(pk__in=search.order_by().values("pk"))) \
        .order_by(*search.query.order_by)[:EXPORT_MAX]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols.column_labels(ids, cfs))
    w.writerows(cols.export_values(list(qs), ids, cfs))
    resp = HttpResponse("﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="gestiona-export.csv"'
    return resp
