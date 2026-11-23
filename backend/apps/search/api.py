import csv
import io

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import HttpResponse
from ninja import Router, Schema

from apps.boards.api import CardOut, card, card_queryset
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import UserRef, user_ref
from apps.projects.permissions import visible_projects

from .jql import (
    FIELD_DOCS,
    FUNCTION_DOCS,
    SORT_ONLY_DOCS,
    compile_jql,
    doc_is_orderable,
    search_issues,
)
from .models import RecentItem, SavedFilter

router = Router(tags=["search"])
User = get_user_model()


class SearchIn(Schema):
    jql: str = ""
    start: int = 0
    limit: int = 50


class SearchRow(CardOut):
    project_key: str
    reporter: UserRef | None
    resolution: str | None
    created_at: str
    updated_at: str
    resolved_at: str | None


class SearchOut(Schema):
    total: int
    start: int
    limit: int
    issues: list[SearchRow]


class FilterOut(Schema):
    id: int
    name: str
    description: str
    jql: str
    owner: UserRef
    visibility: str
    starred: bool
    is_owner: bool
    columns: list[str]


class FilterIn(Schema):
    name: str | None = None
    description: str | None = None
    jql: str | None = None
    visibility: str | None = None
    columns: list[str] | None = None


class Suggestion(Schema):
    value: str
    label: str


class RecentOut(Schema):
    kind: str
    id: int
    title: str
    subtitle: str
    url: str
    icon: str | None = None
    viewed_at: str


def _row(i) -> dict:
    return {
        **card(i), "project_key": i.project.key, "reporter": user_ref(i.reporter),
        "resolution": i.resolution.name if i.resolution else None,
        "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat(),
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }


@router.post("/search", response=SearchOut)
def search(request, data: SearchIn):
    limit = max(1, min(data.limit, 200))
    start = max(0, data.start)
    qs = search_issues(request.user, data.jql)
    total = qs.count()
    rows = card_queryset(qs.select_related("project", "reporter", "resolution"))[
        start:start + limit
    ]
    return {"total": total, "start": start, "limit": limit, "issues": [_row(i) for i in rows]}


class FieldDoc(Schema):
    name: str
    label: str
    sortable: bool = False  # valid after ORDER BY
    searchable: bool = True  # valid in a clause (`rank` only sorts)


class FieldsOut(Schema):
    fields: list[FieldDoc]
    functions: list[str]
    operators: list[str]


class WorkCard(CardOut):
    project_key: str
    project_name: str


class YourWorkOut(Schema):
    assigned: list[WorkCard]
    worked_on: list[WorkCard]


class ValidOut(Schema):
    ok: bool


@router.get("/search/validate", response=ValidOut)
def validate(request, jql: str):
    compile_jql(jql, user=request.user)
    return {"ok": True}


@router.get("/search/export")
def export_csv(request, jql: str = "", columns: str = ""):
    if columns:  # column ids of the «Lista» view (GET /projects/{key}/list/meta)
        from apps.listview.api import export_columns_csv

        return export_columns_csv(request.user, jql, columns)
    qs = search_issues(request.user, jql).select_related(
        "project", "issue_type", "status", "priority", "assignee", "reporter", "resolution",
        "sprint", "parent",
    )[:10000]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Clave", "Resumen", "Tipo", "Estado", "Prioridad", "Responsable", "Informador",
                "Resolución", "Sprint", "Principal", "Puntos", "Etiquetas", "Creado",
                "Actualizado", "Resuelto", "Vencimiento"])
    for i in qs:
        w.writerow([
            i.key, i.summary, i.issue_type.name, i.status.name, i.priority.name,
            i.assignee.display_name if i.assignee else "",
            i.reporter.display_name if i.reporter else "",
            i.resolution.name if i.resolution else "", i.sprint.name if i.sprint else "",
            i.parent.key if i.parent else "", i.story_points or "", " ".join(i.labels),
            i.created_at.isoformat(), i.updated_at.isoformat(),
            i.resolved_at.isoformat() if i.resolved_at else "",
            i.due_date.isoformat() if i.due_date else "",
        ])
    resp = HttpResponse("﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="gestiona-export.csv"'
    return resp


@router.get("/search/fields", response=FieldsOut)
def fields(request):
    from apps.issues.models import CustomField

    docs = [{"name": n, "label": label, "sortable": doc_is_orderable(n), "searchable": True}
            for n, label in FIELD_DOCS]
    docs += [{"name": n, "label": label, "sortable": True, "searchable": False}
             for n, label in SORT_ONLY_DOCS]
    cfs = [{"name": f"cf[{c.id}]", "label": c.name, "sortable": True, "searchable": True}
           for c in CustomField.objects.all()]  # every kind sorts (see search/jql.py)
    return {
        "fields": docs + cfs,
        "functions": FUNCTION_DOCS,
        "operators": ["=", "!=", "~", "!~", ">", ">=", "<", "<=", "in", "not in", "is empty",
                      "is not empty"],
    }


@router.get("/search/suggest", response=list[Suggestion])
def suggest(request, field: str, value: str = ""):
    """Value autocomplete for the JQL editor."""
    from apps.boards.models import Sprint
    from apps.issues.models import IssueType, Priority, Resolution
    from apps.projects.models import Component, Version
    from apps.workflows.models import Status

    f = field.strip().lower().strip('"')
    v = value.strip().strip('"')
    projects = visible_projects(request.user)

    def quote(s: str) -> str:
        return f'"{s}"' if any(ch in s for ch in " ,()=!~<>") else s

    out: list[dict] = []
    if f in ("project", "proyecto"):
        for p in projects.filter(Q(key__istartswith=v) | Q(name__icontains=v))[:15]:
            out.append({"value": p.key, "label": f"{p.name} ({p.key})"})
    elif f in ("status", "estado"):
        for s in Status.objects.filter(name__icontains=v)[:15]:
            out.append({"value": quote(s.name), "label": s.name})
    elif f in ("type", "issuetype", "tipo"):
        for t in IssueType.objects.filter(name__icontains=v)[:15]:
            out.append({"value": quote(t.name), "label": t.name})
    elif f in ("priority", "prioridad"):
        for p in Priority.objects.filter(name__icontains=v):
            out.append({"value": quote(p.name), "label": p.name})
    elif f in ("resolution", "resolución", "resolucion"):
        out.append({"value": "Unresolved", "label": "Sin resolver"})
        for r in Resolution.objects.filter(name__icontains=v):
            out.append({"value": quote(r.name), "label": r.name})
    elif f in ("assignee", "reporter", "watcher", "responsable", "informador"):
        out.append({"value": "currentUser()", "label": "Usuario actual"})
        for u in User.objects.filter(is_active=True).filter(
            Q(full_name__icontains=v) | Q(email__icontains=v)
        )[:15]:
            out.append({"value": quote(u.email), "label": f"{u.display_name} ({u.email})"})
    elif f in ("sprint",):
        out += [{"value": "openSprints()", "label": "Sprints abiertos"},
                {"value": "futureSprints()", "label": "Sprints futuros"},
                {"value": "closedSprints()", "label": "Sprints cerrados"}]
        for s in Sprint.objects.filter(board__project__in=projects, name__icontains=v)[:15]:
            out.append({"value": quote(s.name), "label": s.name})
    elif f in ("component", "componente"):
        for c in Component.objects.filter(project__in=projects, name__icontains=v)[:15]:
            out.append({"value": quote(c.name), "label": f"{c.name} ({c.project.key})"})
    elif f in ("fixversion", "affectedversion", "version"):
        out.append({"value": "unreleasedVersions()", "label": "Versiones no publicadas"})
        for x in Version.objects.filter(project__in=projects, name__icontains=v)[:15]:
            out.append({"value": quote(x.name), "label": f"{x.name} ({x.project.key})"})
    elif f in ("labels", "label", "etiquetas"):
        from apps.issues.api import labels as label_view

        out += [{"value": quote(lab), "label": lab} for lab in label_view(request, q=v)]
    elif f in ("team", "equipo"):
        from apps.plans.models import Team

        for t in Team.objects.filter(name__icontains=v)[:15]:
            out.append({"value": quote(t.name), "label": t.name})
    elif f in ("statuscategory",):
        out += [{"value": '"To Do"', "label": "Por hacer"},
                {"value": '"In Progress"', "label": "En curso"},
                {"value": "Done", "label": "Listo"}]
    elif f in ("created", "updated", "resolved", "due", "duedate"):
        out += [{"value": "-1d", "label": "Último día"}, {"value": "-1w", "label": "Última semana"},
                {"value": "startOfWeek()", "label": "Inicio de semana"},
                {"value": "startOfMonth()", "label": "Inicio de mes"},
                {"value": "now()", "label": "Ahora"}]
    return out


# ------------------------------------------------------------------ saved filters

def _filter_out(f: SavedFilter, user, starred_ids: set[int] | None = None) -> dict:
    starred = f.id in starred_ids if starred_ids is not None else \
        f.starred_by.filter(pk=user.pk).exists()
    return {"id": f.id, "name": f.name, "description": f.description, "jql": f.jql,
            "owner": user_ref(f.owner), "visibility": f.visibility, "starred": starred,
            "is_owner": f.owner_id == user.id, "columns": f.columns}


def _visible_filters(user):
    return SavedFilter.objects.select_related("owner").filter(
        Q(owner=user) | Q(visibility=SavedFilter.Visibility.PUBLIC)
        | Q(visibility=SavedFilter.Visibility.PROJECT, project__in=visible_projects(user))
    ).distinct()


def _get_filter(user, fid: int) -> SavedFilter:
    f = _visible_filters(user).filter(pk=fid).first()
    if f is None:
        raise NotFound("Filtro no encontrado")
    return f


@router.get("/filters", response=list[FilterOut])
def list_filters(request, q: str = "", mine: bool = False, starred: bool = False,
                 deleted: bool = False):
    qs = _deleted_filters(request.user) if deleted else _visible_filters(request.user)
    if q:
        qs = qs.filter(name__icontains=q)
    if mine:
        qs = qs.filter(owner=request.user)
    if starred:
        qs = qs.filter(starred_by=request.user)
    ids = set(request.user.starred_filters.values_list("id", flat=True))
    return [_filter_out(f, request.user, ids) for f in qs]


@router.post("/filters", response={201: FilterOut})
def create_filter(request, data: FilterIn):
    if not (data.name or "").strip():
        raise ValidationFailed("El nombre es obligatorio")
    compile_jql(data.jql or "", user=request.user)
    vis = data.visibility or SavedFilter.Visibility.PRIVATE
    if vis not in SavedFilter.Visibility.values:
        raise ValidationFailed("Visibilidad inválida")
    f = SavedFilter.objects.create(name=data.name.strip()[:120], description=data.description
                                   or "", jql=data.jql or "", owner=request.user,
                                   visibility=vis, columns=data.columns or [])
    f.starred_by.add(request.user)
    return 201, _filter_out(f, request.user)


@router.get("/filters/{fid}", response=FilterOut)
def get_filter(request, fid: int):
    f = _get_filter(request.user, fid)
    RecentItem.objects.update_or_create(user=request.user, kind="filter", object_id=f.id)
    return _filter_out(f, request.user)


@router.patch("/filters/{fid}", response=FilterOut)
def update_filter(request, fid: int, data: FilterIn):
    f = _get_filter(request.user, fid)
    if f.owner_id != request.user.id:
        raise Forbidden("Solo el propietario puede editar el filtro")
    d = data.dict(exclude_unset=True)
    if "jql" in d and d["jql"] is not None:
        compile_jql(d["jql"], user=request.user)
    if "visibility" in d and d["visibility"] not in SavedFilter.Visibility.values:
        raise ValidationFailed("Visibilidad inválida")
    for k, v in d.items():
        if v is not None:
            setattr(f, k, v)
    f.save()
    return _filter_out(f, request.user)


@router.delete("/filters/{fid}", response={204: None})
def delete_filter(request, fid: int):
    """Soft delete; the owner (or a superuser) can restore it."""
    f = _get_filter(request.user, fid)
    if f.owner_id != request.user.id and not request.user.is_superuser:
        raise Forbidden("Solo el propietario puede eliminar el filtro")
    f.soft_delete()
    return 204, None


def _deleted_filters(user):
    qs = SavedFilter.all_objects.deleted().select_related("owner")
    return qs if user.is_superuser else qs.filter(owner=user)


@router.post("/filters/{fid}/restore", response=FilterOut)
def restore_filter(request, fid: int):
    f = _deleted_filters(request.user).filter(pk=fid).first()
    if f is None:
        raise NotFound("Filtro no encontrado")
    f.restore()
    return _filter_out(f, request.user)


@router.post("/filters/{fid}/star", response={204: None})
def star_filter(request, fid: int):
    _get_filter(request.user, fid).starred_by.add(request.user)
    return 204, None


@router.delete("/filters/{fid}/star", response={204: None})
def unstar_filter(request, fid: int):
    _get_filter(request.user, fid).starred_by.remove(request.user)
    return 204, None


# ------------------------------------------------------------------ recent

@router.get("/recent", response=list[RecentOut])
def recent(request, kind: str | None = None, limit: int = 10):
    from apps.boards.models import Board
    from apps.issues.models import Issue

    qs = RecentItem.objects.filter(user=request.user)
    if kind:
        qs = qs.filter(kind=kind)
    items = list(qs[: min(limit, 50) * 2])
    projects = visible_projects(request.user)
    ids = {k: [i.object_id for i in items if i.kind == k] for k in
           ("issue", "project", "board", "filter")}
    issues = {i.id: i for i in Issue.objects.filter(id__in=ids["issue"], project__in=projects)
              .select_related("issue_type", "project")}
    projs = {p.id: p for p in projects.filter(id__in=ids["project"])}
    boards = {b.id: b for b in Board.objects.filter(id__in=ids["board"], project__in=projects)
              .select_related("project")}
    filters = {f.id: f for f in _visible_filters(request.user).filter(id__in=ids["filter"])}
    out = []
    for it in items:
        t = it.viewed_at.isoformat()
        if it.kind == "issue" and it.object_id in issues:
            i = issues[it.object_id]
            out.append({"kind": "issue", "id": i.id, "title": i.summary,
                        "subtitle": f"{i.key} · {i.project.name}", "url": f"/browse/{i.key}",
                        "icon": i.issue_type.icon, "viewed_at": t})
        elif it.kind == "project" and it.object_id in projs:
            p = projs[it.object_id]
            out.append({"kind": "project", "id": p.id, "title": p.name,
                        "subtitle": "Proyecto de software" if p.template != "business"
                        else "Proyecto de negocio",
                        "url": f"/projects/{p.key}", "icon": p.avatar, "viewed_at": t})
        elif it.kind == "board" and it.object_id in boards:
            b = boards[it.object_id]
            out.append({"kind": "board", "id": b.id, "title": b.name,
                        "subtitle": b.project.name,
                        "url": f"/projects/{b.project.key}/boards/{b.id}", "viewed_at": t})
        elif it.kind == "filter" and it.object_id in filters:
            f = filters[it.object_id]
            out.append({"kind": "filter", "id": f.id, "title": f.name, "subtitle": "Filtro",
                        "url": f"/issues?filter={f.id}", "viewed_at": t})
        if len(out) >= limit:
            break
    return out


@router.get("/dashboard/summary", response=YourWorkOut)
def dashboard_summary(request):
    """'Your work' page data: assigned to me, recently worked on, viewed."""
    from apps.issues.models import Issue

    projects = visible_projects(request.user)
    assigned = card_queryset(
        Issue.objects.filter(project__in=projects, assignee=request.user, is_archived=False)
        .exclude(status__category="done").select_related("project")
    ).order_by("-updated_at")[:50]
    worked = card_queryset(
        Issue.objects.filter(project__in=projects, history__actor=request.user)
        .select_related("project").distinct()
    ).order_by("-updated_at")[:30]
    return {
        "assigned": [{**card(i), "project_key": i.project.key,
                      "project_name": i.project.name} for i in assigned],
        "worked_on": [{**card(i), "project_key": i.project.key,
                       "project_name": i.project.name} for i in worked],
    }
