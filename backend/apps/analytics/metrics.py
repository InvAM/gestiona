"""Flow metrics, computed in Postgres from the status history.

Source: `IssueHistory.items` entries with `field = "status"` (one per transition). Native
entries store status ids as JSON numbers; entries imported from Jira store Jira ids as
strings, so those are resolved by status name (`to_display`), the same way the importer
created the statuses. Everything is keyed on the status *category*, never on its name:

* Start of work: first time the issue enters an `in_progress` status (or its creation, when
  it was created directly in one). Issues that never went through «En curso» have no cycle
  time (they still count for throughput and lead time).
* Resolution: `Issue.resolved_at`. It is cleared on reopen and set again on the next
  resolution, so a reopened issue is measured up to its *final* resolution, and only counts
  once, in the period of that final resolution.
* Cycle time = resolution − start of work. Lead time = resolution − creation.
* Time in status: every closed segment between two transitions (several visits add up).
* WIP: issues whose current status is `in_progress`; age = now − start of work.

Issues moved between projects keep their row and history, so they are measured from their
original creation and counted under their current project.

All aggregation (percentiles, histograms, rolling windows) happens in SQL: per request there
is a constant number of queries whatever the number of issues.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.cache import cache
from django.db import connection, transaction
from django.db.models import Count
from django.db.models.functions import Trunc
from django.utils import timezone

from apps.issues.models import Issue, IssueHistory, IssueType
from apps.workflows.models import Status, StatusCategory

from .scope import CACHE_SECONDS, METRICS, NONE_KEY, Scope, gkey, group_labels

TODO, IN_PROGRESS, DONE = (StatusCategory.TODO.value, StatusCategory.IN_PROGRESS.value,
                           StatusCategory.DONE.value)
CATEGORY_ORDER = {TODO: 0, IN_PROGRESS: 1, DONE: 2}
STATUS_ITEMS = """'[{"field": "status"}]'::jsonb"""  # matches the partial index predicate
HIST_EDGES = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]  # days; open-ended last bin
MAX_POINTS = 3000
WIP_OLDEST = 20

I_T, H_T, S_T = Issue._meta.db_table, IssueHistory._meta.db_table, Status._meta.db_table


def hours(seconds) -> float | None:
    return None if seconds is None else round(float(seconds) / 3600, 3)


def _pct(arr) -> dict:
    arr = list(arr or []) + [None, None, None]
    return {"p50": hours(arr[0]), "p85": hours(arr[1]), "p95": hours(arr[2])}


def cached(scope: Scope, name: str, fn, **extra):
    key = scope.cache_key(name, **extra)
    hit = cache.get(key)
    if hit is None:
        hit = fn()
        cache.set(key, hit, CACHE_SECONDS)
    return hit


# --------------------------------------------------------------------------- SQL core

def _flow_cte(scope: Scope, where: str, where_params: list) -> tuple[str, list]:
    """WITH … m: one row per issue in scope matching `where` (alias `i`), with its start of
    work. Also exposes `tr` (status transitions) and `first_tr` to later CTEs."""
    scope_sql, scope_params = scope.issues.values("id").query.sql_with_params()
    gcol = f"i.{scope.group_column}" if scope.group_column else "NULL::bigint"
    sql = f"""
    WITH iss AS MATERIALIZED (
        SELECT i.id, i.key, i.summary, i.created_at, i.resolved_at, i.status_id,
               i.status_changed_at, i.issue_type_id, {gcol} AS grp
        FROM {I_T} i
        WHERE i.id IN ({scope_sql}) AND ({where})
    ),
    st_name AS (
        SELECT DISTINCT ON (lower(name)) lower(name) AS lname, id
        FROM {S_T} ORDER BY lower(name), (deleted_at IS NOT NULL), id
    ),
    tr AS MATERIALIZED (
        SELECT h.issue_id, h.created_at AS at, h.id AS hid, x.ord,
               COALESCE(CASE WHEN jsonb_typeof(x.e->'from') = 'number'
                             THEN (x.e->>'from')::bigint END, fn.id) AS from_id,
               COALESCE(CASE WHEN jsonb_typeof(x.e->'to') = 'number'
                             THEN (x.e->>'to')::bigint END, tn.id) AS to_id
        FROM iss
        JOIN {H_T} h ON h.issue_id = iss.id AND h.items @> {STATUS_ITEMS}
        CROSS JOIN LATERAL jsonb_array_elements(h.items) WITH ORDINALITY AS x(e, ord)
        LEFT JOIN st_name fn ON jsonb_typeof(x.e->'from') = 'string'
                            AND fn.lname = lower(x.e->>'from_display')
        LEFT JOIN st_name tn ON jsonb_typeof(x.e->'to') = 'string'
                            AND tn.lname = lower(x.e->>'to_display')
        WHERE x.e->>'field' = 'status'
    ),
    first_tr AS (
        SELECT DISTINCT ON (issue_id) issue_id, from_id, at
        FROM tr ORDER BY issue_id, at, hid, ord
    ),
    started AS (
        SELECT tr.issue_id, min(tr.at) AS at
        FROM tr JOIN {S_T} s ON s.id = tr.to_id
        WHERE s.category = %s GROUP BY tr.issue_id
    ),
    reopened AS (
        SELECT DISTINCT tr.issue_id
        FROM tr JOIN {S_T} f ON f.id = tr.from_id JOIN {S_T} t ON t.id = tr.to_id
        WHERE f.category = %s AND t.category <> %s
    ),
    m AS (
        SELECT iss.*,
               CASE WHEN ic.category = %s THEN iss.created_at ELSE started.at END
                   AS started_at,
               (reopened.issue_id IS NOT NULL) AS was_reopened
        FROM iss
        LEFT JOIN first_tr ft ON ft.issue_id = iss.id
        LEFT JOIN {S_T} ic ON ic.id = COALESCE(ft.from_id, iss.status_id)
        LEFT JOIN started ON started.issue_id = iss.id
        LEFT JOIN reopened ON reopened.issue_id = iss.id
    )"""
    return sql, [*scope_params, *where_params, IN_PROGRESS, DONE, DONE, IN_PROGRESS]


CYCLE = ("CASE WHEN m.started_at IS NOT NULL AND m.started_at <= m.resolved_at "
         "THEN EXTRACT(EPOCH FROM m.resolved_at - m.started_at)::float8 END")
LEAD = "GREATEST(EXTRACT(EPOCH FROM m.resolved_at - m.created_at)::float8, 0)"
RESOLVED_IN_RANGE = "i.resolved_at >= %s AND i.resolved_at < %s"


def _resolved(scope: Scope):
    return _flow_cte(scope, RESOLVED_IN_RANGE, [scope.start_dt, scope.end_dt])


def _fetch(sql: str, params: list):
    # The CTE row estimates are rough, which makes Postgres JIT-compile these queries:
    # that costs ~1 s and buys nothing at this size, so it is disabled for the statement.
    with transaction.atomic(), connection.cursor() as c:
        c.execute("SET LOCAL jit = off")
        c.execute(sql, params)
        return c.fetchall()


# --------------------------------------------------------------------------- queries

def resolved_stats(scope: Scope) -> dict:
    """Cycle/lead percentiles (overall and per group) + cycle-time histogram. One query."""
    cte, params = _resolved(scope)
    edges = ",".join(str(float(e)) for e in HIST_EDGES)
    sql = f"""{cte},
    v AS MATERIALIZED (
        SELECT m.grp, {CYCLE} AS cycle, {LEAD} AS lead, m.was_reopened FROM m
    ),
    stats AS (
        SELECT grp, GROUPING(grp) AS is_total, count(*) AS n, count(cycle) AS n_cycle,
               count(*) FILTER (WHERE was_reopened) AS n_reopened,
               avg(cycle) AS cycle_avg,
               percentile_cont(ARRAY[0.5, 0.85, 0.95]) WITHIN GROUP (ORDER BY cycle) AS cycle_p,
               avg(lead) AS lead_avg,
               percentile_cont(ARRAY[0.5, 0.85, 0.95]) WITHIN GROUP (ORDER BY lead) AS lead_p
        FROM v GROUP BY GROUPING SETS ((grp), ())
    ),
    hist AS (
        SELECT width_bucket(cycle / 86400.0, ARRAY[{edges}]::float8[]) AS b, count(*) AS n
        FROM v WHERE cycle IS NOT NULL GROUP BY 1
    )
    SELECT (SELECT coalesce(json_agg(stats), '[]'::json) FROM stats),
           (SELECT coalesce(json_agg(hist), '[]'::json) FROM hist)"""
    stats_rows, hist_rows = _fetch(sql, params)[0]
    total = next((r for r in stats_rows if r["is_total"]), None) or {}
    groups = {gkey(r["grp"]): r for r in stats_rows if not r["is_total"]}
    by_bin = {r["b"]: r["n"] for r in hist_rows}
    bounds = [0, *HIST_EDGES]
    bins = []
    for b in range(len(bounds)):
        lo = bounds[b]
        hi = bounds[b + 1] if b + 1 < len(bounds) else None
        bins.append({"label": f"{lo}–{hi} d" if hi is not None else f"≥ {lo} d",
                     "min_days": lo, "max_days": hi, "count": by_bin.get(b, 0)})

    def block(r):
        return {
            "resolved": r.get("n", 0), "cycle_count": r.get("n_cycle", 0),
            "reopened": r.get("n_reopened", 0),
            "cycle": {**_pct(r.get("cycle_p")), "avg": hours(r.get("cycle_avg"))},
            "lead": {**_pct(r.get("lead_p")), "avg": hours(r.get("lead_avg"))},
        }

    return {"total": block(total), "groups": {k: block(r) for k, r in groups.items()},
            "histogram": bins}


def wip_stats(scope: Scope, now=None) -> dict:
    """Current work in progress (ignores the date range): count, age percentiles, per group,
    and the oldest items. One query."""
    now = now or timezone.now()
    cte, params = _flow_cte(
        scope, f"i.resolved_at IS NULL AND i.status_id IN "
               f"(SELECT id FROM {S_T} WHERE category = %s)", [IN_PROGRESS])
    sql = f"""{cte},
    w AS MATERIALIZED (
        SELECT m.id, m.key, m.summary, m.grp, m.status_id,
               GREATEST(EXTRACT(EPOCH FROM %s::timestamptz
                        - COALESCE(m.started_at, m.status_changed_at, m.created_at))::float8, 0)
                   AS age
        FROM m
    ),
    s AS (
        SELECT grp, GROUPING(grp) AS is_total, count(*) AS n,
               percentile_cont(ARRAY[0.5, 0.85, 0.95]) WITHIN GROUP (ORDER BY age) AS p
        FROM w GROUP BY GROUPING SETS ((grp), ())
    ),
    o AS (
        SELECT w.key, w.summary, w.age, w.grp, st.name AS status, st.category
        FROM w JOIN {S_T} st ON st.id = w.status_id
        ORDER BY w.age DESC, w.id LIMIT {WIP_OLDEST}
    )
    SELECT (SELECT coalesce(json_agg(s), '[]'::json) FROM s),
           (SELECT coalesce(json_agg(o), '[]'::json) FROM o)"""
    srows, orows = _fetch(sql, [*params, now])[0]
    total = next((r for r in srows if r["is_total"]), None) or {}
    return {
        "count": total.get("n", 0), "age": _pct(total.get("p")),
        "groups": {gkey(r["grp"]): r["n"] for r in srows if not r["is_total"]},
        "oldest": [{"key": r["key"], "summary": r["summary"], "status": r["status"],
                    "status_category": r["category"], "age_hours": hours(r["age"]),
                    "group": gkey(r["grp"]) if scope.group_by else None} for r in orows],
    }


def _periods(scope: Scope) -> list[date]:
    cur = scope.start
    if scope.interval == "week":
        cur -= timedelta(days=cur.weekday())
    elif scope.interval == "month":
        cur = cur.replace(day=1)
    out = []
    while cur <= scope.end:
        out.append(cur)
        if scope.interval == "day":
            cur += timedelta(days=1)
        elif scope.interval == "week":
            cur += timedelta(days=7)
        else:
            cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _local_date(d):
    return timezone.localtime(d).date() if hasattr(d, "tzinfo") and d.tzinfo else d


def series(scope: Scope) -> dict:
    """Created vs resolved and throughput per period (and per group). Two queries."""
    from .scope import _issue_field, dimensions

    created = dict(
        scope.issues.filter(created_at__gte=scope.start_dt, created_at__lt=scope.end_dt)
        .annotate(p=Trunc("created_at", scope.interval)).values("p")
        .annotate(n=Count("id")).values_list("p", "n"))
    created = {_local_date(k): v for k, v in created.items()}
    gfield = _issue_field(dimensions()[scope.group_by][0]).attname if scope.group_by else None
    values = ["p", gfield] if gfield else ["p"]
    resolved: dict[date, dict[str, int]] = {}
    created_by_group: dict[str, int] = {}
    rows = (scope.issues.filter(resolved_at__gte=scope.start_dt, resolved_at__lt=scope.end_dt)
            .annotate(p=Trunc("resolved_at", scope.interval)).values(*values)
            .annotate(n=Count("id")))
    for r in rows:
        k = gkey(r[gfield]) if gfield else "total"
        resolved.setdefault(_local_date(r["p"]), {})[k] = r["n"]
    if gfield:
        for r in (scope.issues.filter(created_at__gte=scope.start_dt,
                                      created_at__lt=scope.end_dt)
                  .values(gfield).annotate(n=Count("id"))):
            created_by_group[gkey(r[gfield])] = r["n"]
    out_cvr, out_tp = [], []
    for p in _periods(scope):
        counts = resolved.get(p, {})
        total = sum(counts.values())
        out_cvr.append({"period": p, "created": created.get(p, 0), "resolved": total})
        out_tp.append({"period": p, "total": total, "counts": counts if gfield else {}})
    return {"created_vs_resolved": out_cvr, "throughput": out_tp,
            "created_total": sum(created.values()), "created_by_group": created_by_group}


def flow(scope: Scope) -> dict:
    def compute():
        res = resolved_stats(scope)
        wip = wip_stats(scope)
        ser = series(scope)
        keys: set[str] = set()
        if scope.group_by:
            keys = set(res["groups"]) | set(wip["groups"]) | set(ser["created_by_group"])
            for row in ser["throughput"]:
                keys |= set(row["counts"])
        labels = group_labels(scope, keys)
        by_group = []
        for k in keys:
            g = res["groups"].get(k) or {}
            by_group.append({
                "key": k, "label": labels.get(k, k),
                "created": ser["created_by_group"].get(k, 0),
                "resolved": g.get("resolved", 0), "wip": wip["groups"].get(k, 0),
                "cycle_p50": (g.get("cycle") or {}).get("p50"),
                "cycle_p85": (g.get("cycle") or {}).get("p85"),
                "lead_p50": (g.get("lead") or {}).get("p50"),
                "lead_p85": (g.get("lead") or {}).get("p85"),
            })
        by_group.sort(key=lambda r: (-r["resolved"], -r["wip"], r["label"]))
        t = res["total"]
        weeks = max(scope.days / 7, 1)
        return {
            "scope": scope.out(),
            "groups": [{"key": r["key"], "label": r["label"]} for r in by_group],
            "kpis": {
                "created": ser["created_total"], "resolved": t["resolved"],
                "reopened": t["reopened"], "cycle_count": t["cycle_count"],
                "throughput_per_week": round(t["resolved"] / weeks, 2),
                "cycle": t["cycle"], "lead": t["lead"],
                "wip": wip["count"], "wip_age": wip["age"],
            },
            "by_group": by_group,
            "created_vs_resolved": ser["created_vs_resolved"],
            "throughput": ser["throughput"],
            "cycle_histogram": res["histogram"],
            "wip_oldest": wip["oldest"],
        }

    return cached(scope, "flow", compute)


def control_chart(scope: Scope, metric: str = "cycle", max_points: int = MAX_POINTS) -> dict:
    """Scatter of resolved issues (resolution date × cycle or lead time), with a rolling
    average/standard deviation over a window of ~20% of the issues (min 5). Two queries."""
    from apps.core.errors import ValidationFailed

    if metric not in METRICS:
        raise ValidationFailed("Métrica inválida", code="metric")
    expr = CYCLE if metric == "cycle" else LEAD

    def compute():
        cte, params = _resolved(scope)
        stats_sql = f"""{cte},
        v AS (SELECT {expr} AS val FROM m)
        SELECT count(val), avg(val), stddev_samp(val),
               percentile_cont(ARRAY[0.5, 0.85, 0.95]) WITHIN GROUP (ORDER BY val)
        FROM v"""
        n, mean, std, pcts = _fetch(stats_sql, params)[0]
        window = max(5, round(n * 0.2)) if n else 0
        half = window // 2
        points = []
        if n:
            pts_sql = f"""{cte},
            v AS (
                SELECT m.id, m.key, m.summary, m.resolved_at, m.grp, m.issue_type_id,
                       m.was_reopened, {expr} AS val
                FROM m
            ),
            c AS MATERIALIZED (
                -- running sums: any centred window is hi − lo, so the band is O(n)
                SELECT v.*, row_number() OVER o AS rn, sum(val::numeric) OVER o AS s1,
                       sum((val * val)::numeric) OVER o AS s2
                FROM v WHERE val IS NOT NULL
                WINDOW o AS (ORDER BY resolved_at, id ROWS UNBOUNDED PRECEDING)
            ),
            r AS (
                SELECT c.*, hi.s1 - COALESCE(lo.s1, 0) AS ws1, hi.s2 - COALESCE(lo.s2, 0) AS ws2,
                       hi.rn - COALESCE(lo.rn, 0) AS wn
                FROM c
                JOIN c hi ON hi.rn = LEAST(c.rn + %s, (SELECT max(rn) FROM c))
                LEFT JOIN c lo ON lo.rn = GREATEST(c.rn - %s - 1, 0)
                WHERE c.rn > %s
            )
            SELECT key, summary, resolved_at, grp, issue_type_id, was_reopened, val,
                   (ws1 / wn)::float8,
                   CASE WHEN wn > 1
                        THEN sqrt(GREATEST((ws2 - ws1 * ws1 / wn) / (wn - 1), 0))::float8 END
            FROM r ORDER BY rn"""
            rows = _fetch(pts_sql, [*params, half, half, max(n - max_points, 0)])
            types = {t.id: t for t in IssueType._base_manager.filter(
                id__in={r[4] for r in rows})}
            for key, summary, at, grp, tid, reop, val, ravg, rstd in rows:
                t = types.get(tid)
                points.append({
                    "key": key, "summary": summary, "resolved_at": at,
                    "group": gkey(grp) if scope.group_by else None,
                    "type": {"name": t.name, "icon": t.icon, "color": t.color} if t else None,
                    "reopened": reop, "value_hours": hours(val), "avg_hours": hours(ravg),
                    "std_hours": hours(rstd),
                })
        labels = group_labels(scope, {p["group"] for p in points})
        return {
            "scope": scope.out(), "metric": metric, "metric_label": METRICS[metric][0],
            "window": window, "total": n, "truncated": n > len(points),
            "stats": {"count": n, "mean_hours": hours(mean), "std_hours": hours(std),
                      **{f"{k}_hours": v for k, v in _pct(pcts).items()}},
            "groups": [{"key": k, "label": v} for k, v in labels.items()
                       if k in {p["group"] for p in points}],
            "points": points,
        }

    return cached(scope, "control", compute, metric=metric, max_points=max_points)


def time_in_status(scope: Scope) -> dict:
    """Time spent in each status by the issues resolved in the range (closed segments
    only, visits added up per issue). One query + status names."""
    def compute():
        cte, params = _resolved(scope)
        sql = f"""{cte},
        seg AS (
            SELECT tr.issue_id, tr.to_id AS status_id, tr.at AS s,
                   lead(tr.at) OVER (PARTITION BY tr.issue_id ORDER BY tr.at, tr.hid, tr.ord)
                       AS e
            FROM tr
            UNION ALL
            SELECT iss.id, COALESCE(ft.from_id, iss.status_id), iss.created_at, ft.at
            FROM iss LEFT JOIN first_tr ft ON ft.issue_id = iss.id
        ),
        per AS (
            SELECT issue_id, status_id, sum(EXTRACT(EPOCH FROM e - s))::float8 AS secs,
                   count(*) AS visits
            FROM seg WHERE e IS NOT NULL AND status_id IS NOT NULL GROUP BY 1, 2
        )
        SELECT status_id, count(*), sum(visits), avg(secs),
               percentile_cont(ARRAY[0.5, 0.85]) WITHIN GROUP (ORDER BY secs), sum(secs),
               (SELECT count(*) FROM iss)
        FROM per GROUP BY status_id"""
        rows = _fetch(sql, params)
        statuses = {s.id: s for s in Status._base_manager.filter(id__in=[r[0] for r in rows])}
        out = []
        for sid, n, visits, avg, pcts, total, _ in rows:
            st = statuses.get(sid)
            if st is None:
                continue
            p = list(pcts or []) + [None, None]
            out.append({"status_id": sid, "name": st.name, "category": st.category,
                        "issues": n, "visits": int(visits), "avg_hours": hours(avg),
                        "p50_hours": hours(p[0]), "p85_hours": hours(p[1]),
                        "total_hours": hours(total)})
        out.sort(key=lambda r: (CATEGORY_ORDER.get(r["category"], 9), -(r["avg_hours"] or 0)))
        issues = rows[0][6] if rows else scope.issues.filter(
            resolved_at__gte=scope.start_dt, resolved_at__lt=scope.end_dt).count()
        return {"scope": scope.out(), "issues": issues, "statuses": out}

    return cached(scope, "tis", compute)


__all__ = ["flow", "control_chart", "time_in_status", "resolved_stats", "NONE_KEY"]
