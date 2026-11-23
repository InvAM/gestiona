"""Flow analytics across projects (GET only, always computed as the viewer).

Common query parameters:
  projects   comma-separated project keys (optional; each must be visible, else 404)
  jql        narrows the issues (optional; same permissions as the issue search)
  start/end  date range, inclusive (default: last 90 days; at most 366 days → 422 `range`)
  interval   day | week | month (period of the series)
  group_by   project | type | priority | assignee | team (see GET /meta → analytics)
"""

from __future__ import annotations

from datetime import date

from ninja import Router

from . import metrics
from .schemas import AnalyticsControlOut, AnalyticsFlowOut, AnalyticsTimeInStatusOut
from .scope import build_scope

router = Router(tags=["analytics"])


def _scope(request, projects, jql, start, end, interval=None, group_by=None):
    return build_scope(request.user, projects=projects, jql=jql, start=start, end=end,
                       interval=interval, group_by=group_by)


@router.get("/analytics/flow", response=AnalyticsFlowOut)
def flow(request, projects: str = "", jql: str = "", start: date | None = None,
         end: date | None = None, interval: str = "week", group_by: str = ""):
    """KPIs, per-group table, created vs resolved, throughput, cycle-time histogram, WIP."""
    return metrics.flow(_scope(request, projects, jql, start, end, interval, group_by))


@router.get("/analytics/control-chart", response=AnalyticsControlOut)
def control_chart(request, projects: str = "", jql: str = "", start: date | None = None,
                  end: date | None = None, metric: str = "cycle", group_by: str = ""):
    """One point per resolved issue (resolution date × cycle or lead time) with a rolling
    average and standard deviation band."""
    return metrics.control_chart(_scope(request, projects, jql, start, end, None, group_by),
                                 metric)


@router.get("/analytics/time-in-status", response=AnalyticsTimeInStatusOut)
def time_in_status(request, projects: str = "", jql: str = "", start: date | None = None,
                   end: date | None = None):
    """Average / median / p85 time spent in each status by the issues resolved in range."""
    return metrics.time_in_status(_scope(request, projects, jql, start, end))
