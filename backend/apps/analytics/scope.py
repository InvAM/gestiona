"""What an analytics query looks at: the viewer's visible, non-archived issues narrowed by
projects and/or JQL, a date range (bounded) and an optional group-by dimension.

Labels for every option here are exposed by GET /meta → `analytics`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.core.exceptions import FieldDoesNotExist
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.errors import NotFound, ValidationFailed

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 90
CACHE_SECONDS = 60
NONE_KEY = "__none__"

# name: (Issue field, label, label of the empty group, description)
_DIMENSIONS = {
    "project": ("project", "Proyecto", "Sin proyecto", ""),
    "type": ("issue_type", "Tipo", "Sin tipo", ""),
    "priority": ("priority", "Prioridad", "Sin prioridad", ""),
    "assignee": ("assignee", "Responsable", "Sin asignar", "Responsable actual de la incidencia"),
    "team": ("team", "Equipo", "Sin equipo", ""),
}
INTERVALS = {"day": "Día", "week": "Semana", "month": "Mes"}
METRICS = {
    "cycle": ("Tiempo de ciclo",
              "Desde que la incidencia entra por primera vez en un estado «En curso» hasta que "
              "se resuelve"),
    "lead": ("Tiempo de entrega", "Desde que se crea la incidencia hasta que se resuelve"),
}
RANGE_PRESETS = [(14, "Últimos 14 días"), (30, "Últimos 30 días"), (90, "Últimos 90 días"),
                 (180, "Últimos 6 meses"), (365, "Último año")]


def _issue_field(name: str):
    from apps.issues.models import Issue

    try:
        return Issue._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def dimensions() -> dict[str, tuple]:
    """Group-by dimensions available in this install (e.g. `team` only once the field
    exists on Issue)."""
    return {k: v for k, v in _DIMENSIONS.items() if _issue_field(v[0]) is not None}


def analytics_meta() -> dict:
    return {
        "group_by": [{"value": k, "label": v[1], "description": v[3]}
                     for k, v in dimensions().items()],
        "intervals": [{"value": k, "label": v, "description": ""} for k, v in INTERVALS.items()],
        "metrics": [{"value": k, "label": v[0], "description": v[1]} for k, v in METRICS.items()],
        "range_presets": [{"value": d, "label": label} for d, label in RANGE_PRESETS],
        "max_range_days": MAX_RANGE_DAYS,
        "default_range_days": DEFAULT_RANGE_DAYS,
    }


@dataclass
class Scope:
    user_id: int
    issues: QuerySet  # Issue queryset: visible, not archived, project/JQL filters applied
    projects: list[dict]
    jql: str
    start: date
    end: date
    interval: str = "week"
    group_by: str | None = None
    signature: dict = field(default_factory=dict)

    @property
    def start_dt(self) -> datetime:
        return timezone.make_aware(datetime.combine(self.start, time.min))

    @property
    def end_dt(self) -> datetime:
        """Exclusive upper bound (start of the day after `end`)."""
        return timezone.make_aware(datetime.combine(self.end + timedelta(days=1), time.min))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def group_column(self) -> str | None:
        if not self.group_by:
            return None
        return _issue_field(dimensions()[self.group_by][0]).column

    def cache_key(self, name: str, **extra) -> str:
        raw = json.dumps([self.user_id, name, self.signature, extra], sort_keys=True,
                         default=str)
        return f"analytics:v1:{hashlib.sha256(raw.encode()).hexdigest()}"

    def out(self) -> dict:
        dim = dimensions().get(self.group_by or "")
        return {"projects": self.projects, "jql": self.jql, "start": self.start,
                "end": self.end, "interval": self.interval, "group_by": self.group_by,
                "group_label": dim[1] if dim else None}


def _keys(raw: str | None) -> list[str]:
    return sorted({k.strip().upper() for k in (raw or "").split(",") if k.strip()})


def build_scope(user, *, projects: str | None = None, jql: str | None = None,
                start: date | None = None, end: date | None = None,
                interval: str | None = None, group_by: str | None = None) -> Scope:
    from apps.issues.models import Issue
    from apps.projects.permissions import visible_projects
    from apps.search.jql import compile_jql

    today = timezone.localdate()
    end = end or today
    start = start or (end - timedelta(days=DEFAULT_RANGE_DAYS - 1))
    if start > end:
        raise ValidationFailed("La fecha de inicio debe ser anterior a la de fin", code="range")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValidationFailed(f"El rango máximo es de {MAX_RANGE_DAYS} días", code="range",
                               details={"max_range_days": MAX_RANGE_DAYS})
    interval = interval or "week"
    if interval not in INTERVALS:
        raise ValidationFailed("Intervalo inválido", code="interval")
    group_by = group_by or None
    if group_by and group_by not in dimensions():
        raise ValidationFailed("Agrupación inválida", code="group_by")

    visible = visible_projects(user)
    keys = _keys(projects)
    project_rows: list[dict] = []
    qs = Issue.objects.filter(project__in=visible, is_archived=False)
    if keys:
        project_rows = list(visible.filter(key__in=keys).order_by("name")
                            .values("id", "key", "name"))
        if len(project_rows) != len(keys):
            raise NotFound("Proyecto no encontrado")
        qs = qs.filter(project_id__in=[p["id"] for p in project_rows])
    jql = (jql or "").strip()
    if jql:
        compiled = compile_jql(jql, user=user)
        # JQL joins (labels, components…) can duplicate rows: keep it as an id subquery.
        qs = Issue.objects.filter(id__in=qs.filter(compiled.q).values("id"))
    return Scope(
        user_id=user.id, issues=qs.order_by(), projects=project_rows, jql=jql, start=start,
        end=end, interval=interval, group_by=group_by,
        signature={"projects": keys, "jql": jql, "start": start.isoformat(),
                   "end": end.isoformat(), "interval": interval, "group_by": group_by},
    )


def group_labels(scope: Scope, keys) -> dict[str, str]:
    """{group key: label} for raw group ids (one query)."""
    if not scope.group_by:
        return {}
    name, _label, empty, _d = dimensions()[scope.group_by]
    model = _issue_field(name).related_model
    ids = {int(k) for k in keys if k not in (None, NONE_KEY)}
    out = {NONE_KEY: empty}
    for obj in model._base_manager.filter(pk__in=ids):
        out[str(obj.pk)] = getattr(obj, "display_name", None) or getattr(obj, "name", None) \
            or str(obj)
    return out


def gkey(value) -> str:
    return NONE_KEY if value is None else str(value)
