"""Dashboard gadgets backed by the flow metrics (apps/dashboards/gadgets.py dispatches here).

Config: `jql` or `filter_id` (resolved by the caller), `days` (7…366, default 90) and, for
the control chart, `metric` (cycle | lead).
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from . import metrics
from .scope import MAX_RANGE_DAYS, METRICS, build_scope

GADGET_POINTS = 1000


def flow_gadget_data(user, kind: str, config: dict, jql: str) -> dict:
    from apps.core.errors import ValidationFailed

    try:
        days = int(config.get("days") or 90)
    except (TypeError, ValueError):
        raise ValidationFailed("Número de días inválido", code="days") from None
    days = max(7, min(days, MAX_RANGE_DAYS))
    end = timezone.localdate()
    scope = build_scope(user, jql=jql, start=end - timedelta(days=days - 1), end=end)
    if kind == "control_chart":
        metric = config.get("metric") or "cycle"
        if metric not in METRICS:
            raise ValidationFailed("Métrica inválida", code="metric")
        return {"days": days, **metrics.control_chart(scope, metric, GADGET_POINTS)}
    res = metrics.cached(scope, "cycle_gadget", lambda: metrics.resolved_stats(scope))
    t = res["total"]
    return {"days": days, "scope": scope.out(), "resolved": t["resolved"],
            "cycle_count": t["cycle_count"], "cycle": t["cycle"], "lead": t["lead"],
            "histogram": res["histogram"]}
