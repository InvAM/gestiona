"""Data for dashboard gadgets. Always computed as the *viewer*, so a shared dashboard never
shows issues the viewer can't see."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from apps.core.errors import ValidationFailed
from apps.core.schemas import user_ref

from .models import Gadget

GROUP_FIELDS = {
    # name: (values() path for the key, path for the label)
    "status": ("status_id", "status__name"),
    "assignee": ("assignee_id", "assignee__full_name"),
    "reporter": ("reporter_id", "reporter__full_name"),
    "priority": ("priority_id", "priority__name"),
    "type": ("issue_type_id", "issue_type__name"),
    "project": ("project_id", "project__name"),
    "resolution": ("resolution_id", "resolution__name"),
    "component": ("components__id", "components__name"),
    "fix_version": ("fix_versions__id", "fix_versions__name"),
    "sprint": ("sprint_id", "sprint__name"),
    "labels": (None, None),
}
# UI labels for GROUP_FIELDS (exposed by GET /meta → group_by_fields), in display order.
GROUP_FIELD_LABELS = {
    "status": "Estado", "assignee": "Responsable", "priority": "Prioridad", "type": "Tipo",
    "project": "Proyecto", "resolution": "Resolución", "reporter": "Informador",
    "labels": "Etiquetas", "component": "Componente", "fix_version": "Versión",
    "sprint": "Sprint",
}
# Fields that can't be an axis of the two-dimensional table.
NOT_TWO_D = {"labels"}
# Gadget descriptions (GET /meta → gadget_kinds), in display order.
GADGET_DESCRIPTIONS = {
    Gadget.Kind.FILTER_RESULTS: "Lista de incidencias de un JQL o filtro guardado",
    Gadget.Kind.ASSIGNED_TO_ME: "Tus incidencias sin resolver",
    Gadget.Kind.PIE: "Incidencias agrupadas por un campo",
    Gadget.Kind.STATS: "Barras con conteo y porcentaje por campo",
    Gadget.Kind.TWO_D: "Tabla cruzada entre dos campos",
    Gadget.Kind.CREATED_VS_RESOLVED: "Tendencia diaria o semanal",
    Gadget.Kind.SPRINT_BURNDOWN: "Trabajo restante del sprint activo de un tablero",
    Gadget.Kind.ACTIVITY: "Últimos cambios en tus proyectos",
    Gadget.Kind.TEXT: "Notas, enlaces o instrucciones para el equipo",
    Gadget.Kind.CONTROL_CHART: "Tiempo de ciclo o de entrega de cada incidencia resuelta, "
                               "con media móvil",
    Gadget.Kind.CYCLE_TIME: "Percentiles y distribución del tiempo de ciclo",
}
EMPTY_LABEL = {
    "assignee": "Sin asignar", "reporter": "Sin informador", "resolution": "Sin resolver",
    "component": "Sin componente", "fix_version": "Sin versión", "sprint": "Sin sprint",
    "labels": "Sin etiquetas",
}
MAX_GROUPS = 50


def _jql(user, config: dict) -> str:
    fid = config.get("filter_id")
    if fid:
        from apps.search.api import _visible_filters

        f = _visible_filters(user).filter(pk=fid).first()
        if f is None:
            raise ValidationFailed("El filtro no existe o no está compartido contigo")
        return f.jql
    jql = (config.get("jql") or "").strip()
    return jql


def _issues(user, config: dict):
    from apps.issues.models import Issue
    from apps.search.jql import search_issues

    qs = search_issues(user, _jql(user, config))
    return qs, Issue.objects.filter(id__in=qs.values("id"))


def group_counts(base, field: str) -> list[dict]:
    if field not in GROUP_FIELDS:
        raise ValidationFailed("Campo de agrupación inválido")
    if field == "labels":
        counter: Counter = Counter()
        for labels in base.values_list("labels", flat=True)[:20000]:
            counter.update(labels or ["__none__"])
        rows = [{"key": k, "label": EMPTY_LABEL["labels"] if k == "__none__" else k,
                 "count": n} for k, n in counter.most_common(MAX_GROUPS)]
        return rows
    key, label = GROUP_FIELDS[field]
    rows = base.order_by().values(key, label).annotate(n=Count("id", distinct=True)) \
        .order_by("-n")[:MAX_GROUPS]
    out = []
    for r in rows:
        k = r[key]
        name = r[label]
        if field in ("assignee", "reporter") and k:
            from django.contrib.auth import get_user_model

            u = get_user_model().objects.filter(pk=k).first()
            name = u.display_name if u else name
        out.append({"key": k, "label": name if k is not None else EMPTY_LABEL.get(field, "Ninguno"),
                    "count": r["n"]})
    if field == "status":
        from apps.workflows.models import Status

        cats = dict(Status.objects.filter(id__in=[o["key"] for o in out])
                    .values_list("id", "category"))
        for o in out:
            o["category"] = cats.get(o["key"])
    return out


def _row(i) -> dict:
    return {
        "key": i.key, "summary": i.summary,
        "status": {"name": i.status.name, "category": i.status.category},
        "type": {"name": i.issue_type.name, "icon": i.issue_type.icon,
                 "color": i.issue_type.color},
        "priority": {"name": i.priority.name, "icon": i.priority.icon,
                     "color": i.priority.color},
        "assignee": user_ref(i.assignee),
        "due_date": i.due_date.isoformat() if i.due_date else None,
        "updated_at": i.updated_at.isoformat(),
    }


def _list(qs, limit: int) -> dict:
    qs = qs.select_related("status", "issue_type", "priority", "assignee")
    return {"total": qs.count(), "issues": [_row(i) for i in qs[:limit]]}


def gadget_data(user, kind: str, config: dict) -> dict:
    config = config or {}
    limit = max(1, min(int(config.get("limit") or 10), 50))

    if kind == Gadget.Kind.TEXT:
        return {"text": str(config.get("text") or "")[:10000]}

    if kind == Gadget.Kind.ASSIGNED_TO_ME:
        from apps.search.jql import search_issues

        qs = search_issues(user, "assignee = currentUser() AND resolution = Unresolved "
                                 "ORDER BY priority ASC, updated DESC")
        return _list(qs, limit)

    if kind == Gadget.Kind.FILTER_RESULTS:
        qs, _ = _issues(user, config)
        return _list(qs, limit)

    if kind in (Gadget.Kind.PIE, Gadget.Kind.STATS):
        _, base = _issues(user, config)
        field = config.get("group_by") or "status"
        return {"total": base.count(), "group_by": field, "groups": group_counts(base, field)}

    if kind == Gadget.Kind.TWO_D:
        _, base = _issues(user, config)
        x, y = config.get("x") or "status", config.get("y") or "assignee"
        if x == "labels" or y == "labels" or x not in GROUP_FIELDS or y not in GROUP_FIELDS:
            raise ValidationFailed("Campos inválidos para la tabla bidimensional")
        xs = group_counts(base, x)[:12]
        ys = group_counts(base, y)[:15]
        (xk, _), (yk, _) = GROUP_FIELDS[x], GROUP_FIELDS[y]
        cells = {(r[xk], r[yk]): r["n"] for r in base.order_by().values(xk, yk)
                 .annotate(n=Count("id", distinct=True))}
        return {"total": base.count(), "x": x, "y": y, "xs": xs, "ys": ys,
                "cells": [[cells.get((cx["key"], cy["key"]), 0) for cx in xs] for cy in ys]}

    if kind == Gadget.Kind.CREATED_VS_RESOLVED:
        _, base = _issues(user, config)
        days = max(7, min(int(config.get("days") or 30), 365))
        period = "week" if config.get("period") == "week" else "day"
        since = timezone.now() - timedelta(days=days)
        trunc = TruncWeek if period == "week" else TruncDate
        created = dict(base.filter(created_at__gte=since).order_by()
                       .annotate(d=trunc("created_at")).values("d")
                       .annotate(n=Count("id")).values_list("d", "n"))
        resolved = dict(base.filter(resolved_at__gte=since).order_by()
                        .annotate(d=trunc("resolved_at")).values("d")
                        .annotate(n=Count("id")).values_list("d", "n"))

        def norm(d):
            return d.date() if hasattr(d, "date") and callable(d.date) else d

        created = {norm(k): v for k, v in created.items()}
        resolved = {norm(k): v for k, v in resolved.items()}
        start = timezone.localdate() - timedelta(days=days)
        if period == "week":
            start -= timedelta(days=start.weekday())
        step = timedelta(days=7 if period == "week" else 1)
        series, cur = [], start
        while cur <= timezone.localdate():
            series.append({"date": cur.isoformat(), "created": created.get(cur, 0),
                           "resolved": resolved.get(cur, 0)})
            cur += step
        return {"period": period, "series": series,
                "created": sum(s["created"] for s in series),
                "resolved": sum(s["resolved"] for s in series)}

    if kind == Gadget.Kind.ACTIVITY:
        from apps.issues.models import IssueHistory
        from apps.projects.permissions import visible_projects

        qs = IssueHistory.objects.filter(issue__project__in=visible_projects(user)) \
            .select_related("actor", "issue", "issue__issue_type")
        if config.get("project"):
            qs = qs.filter(issue__project__key=str(config["project"]).upper())
        items = []
        for h in qs[:limit]:
            items.append({
                "at": h.created_at.isoformat(), "actor": user_ref(h.actor),
                "issue": {"key": h.issue.key, "summary": h.issue.summary},
                "fields": [i.get("field_name") or i.get("field") for i in h.items][:5],
                "created": any(i.get("field") == "created" for i in h.items),
            })
        return {"items": items}

    if kind == Gadget.Kind.SPRINT_BURNDOWN:
        from apps.boards.models import Board
        from apps.boards.services import burndown
        from apps.projects.models import Perm
        from apps.projects.permissions import has_perm

        board = Board.objects.select_related("project").filter(pk=config.get("board_id")).first()
        if board is None or not has_perm(user, board.project, Perm.BROWSE):
            raise ValidationFailed("Elige un tablero")
        sprint = board.sprints.filter(state="active").first()
        if sprint is None:
            return {"board": board.name, "sprint": None}
        return {"board": board.name, **burndown(sprint)}

    if kind in (Gadget.Kind.CONTROL_CHART, Gadget.Kind.CYCLE_TIME):
        from apps.analytics.gadgets import flow_gadget_data

        return flow_gadget_data(user, kind, config, _jql(user, config))

    raise ValidationFailed("Tipo de gadget desconocido")


DEFAULT_GADGETS = [
    {"kind": Gadget.Kind.ASSIGNED_TO_ME, "title": "Asignadas a mí", "column": 0},
    {"kind": Gadget.Kind.ACTIVITY, "title": "Actividad reciente", "column": 0,
     "config": {"limit": 15}},
    {"kind": Gadget.Kind.PIE, "title": "Mis incidencias por estado", "column": 1,
     "config": {"jql": "assignee = currentUser() AND resolution = Unresolved",
                "group_by": "status"}},
    {"kind": Gadget.Kind.CREATED_VS_RESOLVED, "title": "Creadas vs. resueltas (30 días)",
     "column": 1, "config": {"jql": "", "days": 30, "period": "day"}},
]
