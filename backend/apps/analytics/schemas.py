from __future__ import annotations

from datetime import date, datetime

from ninja import Schema


class AnalyticsChoice(Schema):
    value: str
    label: str
    description: str = ""


class AnalyticsIntChoice(Schema):
    value: int
    label: str


class AnalyticsMetaOut(Schema):
    group_by: list[AnalyticsChoice]
    intervals: list[AnalyticsChoice]
    metrics: list[AnalyticsChoice]
    range_presets: list[AnalyticsIntChoice]
    max_range_days: int
    default_range_days: int


class AnalyticsProjectRef(Schema):
    id: int
    key: str
    name: str


class AnalyticsScopeOut(Schema):
    projects: list[AnalyticsProjectRef]
    jql: str
    start: date
    end: date
    interval: str
    group_by: str | None = None
    group_label: str | None = None


class AnalyticsGroupRef(Schema):
    key: str
    label: str


class AnalyticsPercentiles(Schema):
    p50: float | None = None
    p85: float | None = None
    p95: float | None = None
    avg: float | None = None


class AnalyticsKpisOut(Schema):
    created: int
    resolved: int
    reopened: int
    cycle_count: int
    throughput_per_week: float
    cycle: AnalyticsPercentiles
    lead: AnalyticsPercentiles
    wip: int
    wip_age: AnalyticsPercentiles


class AnalyticsGroupRow(Schema):
    key: str
    label: str
    created: int
    resolved: int
    wip: int
    cycle_p50: float | None = None
    cycle_p85: float | None = None
    lead_p50: float | None = None
    lead_p85: float | None = None


class AnalyticsCreatedResolved(Schema):
    period: date
    created: int
    resolved: int


class AnalyticsThroughputRow(Schema):
    period: date
    total: int
    counts: dict[str, int]


class AnalyticsHistogramBin(Schema):
    label: str
    min_days: float
    max_days: float | None = None
    count: int


class AnalyticsWipItem(Schema):
    key: str
    summary: str
    status: str
    status_category: str
    age_hours: float | None = None
    group: str | None = None


class AnalyticsFlowOut(Schema):
    scope: AnalyticsScopeOut
    groups: list[AnalyticsGroupRef]
    kpis: AnalyticsKpisOut
    by_group: list[AnalyticsGroupRow]
    created_vs_resolved: list[AnalyticsCreatedResolved]
    throughput: list[AnalyticsThroughputRow]
    cycle_histogram: list[AnalyticsHistogramBin]
    wip_oldest: list[AnalyticsWipItem]


class AnalyticsTypeRef(Schema):
    name: str
    icon: str
    color: str


class AnalyticsControlPoint(Schema):
    key: str
    summary: str
    resolved_at: datetime
    group: str | None = None
    type: AnalyticsTypeRef | None = None
    reopened: bool
    value_hours: float | None = None
    avg_hours: float | None = None
    std_hours: float | None = None


class AnalyticsControlStats(Schema):
    count: int
    mean_hours: float | None = None
    std_hours: float | None = None
    p50_hours: float | None = None
    p85_hours: float | None = None
    p95_hours: float | None = None


class AnalyticsControlOut(Schema):
    scope: AnalyticsScopeOut
    metric: str
    metric_label: str
    window: int
    total: int
    truncated: bool
    stats: AnalyticsControlStats
    groups: list[AnalyticsGroupRef]
    points: list[AnalyticsControlPoint]


class AnalyticsStatusTime(Schema):
    status_id: int
    name: str
    category: str
    issues: int
    visits: int
    avg_hours: float | None = None
    p50_hours: float | None = None
    p85_hours: float | None = None
    total_hours: float | None = None


class AnalyticsTimeInStatusOut(Schema):
    scope: AnalyticsScopeOut
    issues: int
    statuses: list[AnalyticsStatusTime]
