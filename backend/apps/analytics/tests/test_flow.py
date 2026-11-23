from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

pytestmark = pytest.mark.django_db

DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def st(project):
    """{category: first status of that category} + 'review' (second in-progress status)."""
    ordered = project.workflow.ordered_statuses()
    out = {}
    for s in ordered:
        out.setdefault(s.category, s)
    out["review"] = [s for s in ordered if s.category == "in_progress"][-1]
    return out


def _status_item(a, b, *, jira=False):
    if jira:  # imported from Jira: foreign ids as strings, names in *_display
        return {"field": "status", "from": "10001", "from_display": a.name.upper(),
                "to": "10002", "to_display": b.name}
    return {"field": "status", "from": a.id, "from_display": a.name, "to": b.id,
            "to_display": b.name}


def fabricate(issue, created, steps, *, jira=False):
    """Rewrite an issue's timeline: created at `created`, then `steps` = [(when, to_status)].
    The issue ends in the last status; resolved_at follows the category like the services
    do (cleared on reopen, set on the final resolution)."""
    from apps.issues.models import Issue, IssueHistory

    current = issue.status
    resolved = None
    for at, to in steps:
        h = IssueHistory.objects.create(issue=issue, items=[_status_item(current, to, jira=jira)])
        IssueHistory.objects.filter(pk=h.pk).update(created_at=at)
        resolved = at if to.category == "done" else None
        current = to
    Issue.objects.filter(pk=issue.pk).update(
        created_at=created, status=current, resolved_at=resolved,
        status_changed_at=steps[-1][0] if steps else created)
    issue.refresh_from_db()
    return issue


def flow(api, **q):
    r = api.get(f"/analytics/flow?{urlencode(q)}")
    assert r.status_code == 200, r.content
    return r.json()


@pytest.fixture
def scenario(make_issue, st):
    now = timezone.now()
    t0 = now - 20 * DAY
    todo, prog, done = st["todo"], st["in_progress"], st["done"]
    # A: started, resolved, REOPENED, started again, resolved again.
    a = fabricate(make_issue("A"), t0, [(t0 + DAY, prog), (t0 + 3 * DAY, done),
                                        (t0 + 4 * DAY, todo), (t0 + 5 * DAY, prog),
                                        (t0 + 6 * DAY, done)])
    # B: straightforward.
    b = fabricate(make_issue("B"), t0, [(t0 + 2 * DAY, prog), (t0 + 4 * DAY, done)])
    # C: never went through «En curso» → no cycle time, but lead time.
    c = fabricate(make_issue("C"), t0, [(t0 + DAY, done)])
    # D: work in progress for 10 days.
    d = fabricate(make_issue("D"), t0, [(t0 + 10 * DAY, prog)])
    return {"a": a, "b": b, "c": c, "d": d, "now": now, "t0": t0}


def test_cycle_lead_wip_with_reopen(api, admin, scenario):
    data = flow(api.login(admin), projects="GES")
    k = data["kpis"]
    assert k["resolved"] == 3 and k["cycle_count"] == 2 and k["reopened"] == 1
    # cycle: A = 6d - 1d (first start → final resolution) = 120 h; B = 48 h
    assert k["cycle"]["p50"] == pytest.approx(84)
    assert k["cycle"]["avg"] == pytest.approx(84)
    # lead: A 144 h, B 96 h, C 24 h
    assert k["lead"]["p50"] == pytest.approx(96)
    assert k["wip"] == 1
    assert k["wip_age"]["p50"] == pytest.approx(240, abs=0.1)
    assert data["wip_oldest"][0]["key"] == scenario["d"].key
    assert sum(b["count"] for b in data["cycle_histogram"]) == 2
    hist = {b["label"]: b["count"] for b in data["cycle_histogram"]}
    assert hist["2–3 d"] == 1 and hist["5–8 d"] == 1
    assert sum(p["resolved"] for p in data["created_vs_resolved"]) == 3
    assert sum(p["total"] for p in data["throughput"]) == 3


def test_time_in_status_adds_up_visits(api, admin, scenario, st):
    r = api.login(admin).get("/analytics/time-in-status?projects=GES")
    assert r.status_code == 200, r.content
    data = r.json()
    assert data["issues"] == 3
    rows = {s["status_id"]: s for s in data["statuses"]}
    todo, prog, done = rows[st["todo"].id], rows[st["in_progress"].id], rows[st["done"].id]
    # todo: A 1d + 1d (two visits), B 2d, C 1d
    assert todo["issues"] == 3 and todo["visits"] == 4
    assert todo["avg_hours"] == pytest.approx((48 + 48 + 24) / 3)
    assert todo["total_hours"] == pytest.approx(120)
    # in progress: A 2d + 1d, B 2d
    assert prog["issues"] == 2 and prog["avg_hours"] == pytest.approx(60)
    # done: only A's closed segment before the reopen (the final one is open)
    assert done["issues"] == 1 and done["total_hours"] == pytest.approx(24)
    assert [s["category"] for s in data["statuses"]][0] == "todo"


def test_percentiles_and_control_chart(api, admin, make_issue, st):
    now = timezone.now()
    for n in range(1, 11):
        start = now - 30 * DAY
        fabricate(make_issue(f"P{n}"), start - DAY,
                  [(start, st["in_progress"]), (start + n * DAY, st["done"])])
    api.login(admin)
    k = flow(api, projects="GES")["kpis"]
    assert k["cycle"]["p50"] == pytest.approx(5.5 * 24)
    assert k["cycle"]["p85"] == pytest.approx(8.65 * 24)
    assert k["cycle"]["p95"] == pytest.approx(9.55 * 24)
    r = api.get("/analytics/control-chart?projects=GES")
    assert r.status_code == 200, r.content
    cc = r.json()
    assert cc["total"] == 10 and len(cc["points"]) == 10 and not cc["truncated"]
    assert cc["stats"]["p50_hours"] == pytest.approx(132)
    assert cc["stats"]["mean_hours"] == pytest.approx(132)
    assert cc["window"] == 5
    first = cc["points"][0]
    assert first["value_hours"] == pytest.approx(24) and first["type"]["name"]
    # rolling window of 5 (2 before, 2 after): the first point averages days 1..3
    assert first["avg_hours"] == pytest.approx(48)
    assert [p["value_hours"] for p in cc["points"]] == sorted(p["value_hours"]
                                                              for p in cc["points"])
    lead = api.get("/analytics/control-chart?projects=GES&metric=lead").json()
    assert lead["stats"]["p50_hours"] == pytest.approx(156)
    assert api.get("/analytics/control-chart?metric=nope").status_code == 422


def test_jql_filter_and_group_by(api, admin, member, scenario, types):
    api.login(admin)
    data = flow(api, jql=f"key = {scenario['a'].key}")
    assert data["kpis"]["resolved"] == 1 and data["kpis"]["wip"] == 0
    from apps.issues.models import Issue

    Issue.objects.filter(pk=scenario["b"].pk).update(assignee=member)
    data = flow(api, projects="GES", group_by="assignee")
    rows = {g["key"]: g for g in data["by_group"]}
    assert rows[str(member.id)]["label"] == member.display_name
    assert rows[str(member.id)]["resolved"] == 1
    assert rows["__none__"]["label"] == "Sin asignar" and rows["__none__"]["resolved"] == 2
    assert rows["__none__"]["wip"] == 1
    week = [p for p in data["throughput"] if p["total"]]
    assert sum(sum(p["counts"].values()) for p in week) == 3
    assert api.get("/analytics/flow?jql=foo%20%3D%3D").status_code == 400


def test_permissions_private_project(api, admin, member, outsider, scenario, project):
    from apps.projects.models import Project

    Project.objects.filter(pk=project.pk).update(access=Project.Access.PRIVATE)
    api.login(outsider)
    assert api.get("/analytics/flow?projects=GES").status_code == 404
    assert api.get("/analytics/control-chart?projects=GES").status_code == 404
    data = flow(api)
    assert data["kpis"]["resolved"] == 0 and data["kpis"]["wip"] == 0
    assert api.get("/analytics/control-chart").json()["total"] == 0
    assert api.get("/analytics/time-in-status").json()["statuses"] == []
    # JQL can't reach it either
    assert flow(api, jql=f"key = {scenario['a'].key}")["kpis"]["resolved"] == 0
    api.login(member)
    assert flow(api, projects="GES")["kpis"]["resolved"] == 3
    api.c.logout()
    assert api.get("/analytics/flow").status_code == 401


def test_archived_issues_are_excluded(api, admin, scenario):
    from apps.issues.models import Issue

    Issue.objects.filter(pk__in=[scenario["a"].pk, scenario["d"].pk]).update(is_archived=True)
    api.login(admin)
    k = flow(api, projects="GES")["kpis"]
    assert k["resolved"] == 2 and k["wip"] == 0 and k["reopened"] == 0
    cc = api.get("/analytics/control-chart?projects=GES").json()
    assert {p["key"] for p in cc["points"]} == {scenario["b"].key}


def test_range_limits(api, admin, scenario):
    api.login(admin)
    r = api.get("/analytics/flow?start=2025-01-01&end=2026-06-01")
    assert r.status_code == 422 and r.json()["code"] == "range"
    r = api.get("/analytics/flow?start=2026-02-01&end=2026-01-01")
    assert r.status_code == 422 and r.json()["code"] == "range"
    assert api.get("/analytics/flow?group_by=labels").status_code == 422
    assert api.get("/analytics/flow?interval=year").status_code == 422
    # a range that excludes the resolutions: nothing resolved, WIP is "now"
    old = (scenario["t0"] - 200 * DAY).date()
    data = flow(api, start=old.isoformat(), end=(old + 30 * DAY).isoformat())
    assert data["kpis"]["resolved"] == 0 and data["kpis"]["wip"] == 1
    days = flow(api, interval="day", start=old.isoformat(),
                end=(old + 9 * DAY).isoformat())["created_vs_resolved"]
    assert len(days) == 10


def test_jira_imported_history_resolved_by_status_name(api, admin, make_issue, st):
    now = timezone.now()
    t0 = now - 10 * DAY
    fabricate(make_issue("J"), t0, [(t0 + DAY, st["in_progress"]), (t0 + 4 * DAY, st["done"])],
              jira=True)
    k = flow(api.login(admin), projects="GES")["kpis"]
    assert k["cycle_count"] == 1 and k["cycle"]["p50"] == pytest.approx(72)


def test_moved_issue_keeps_its_history(api, admin, make_issue, st, project):
    from apps.issues.services import move_issue
    from apps.projects.services import create_project

    other = create_project(admin, name="Otro", key="OTR", template="scrum")
    now = timezone.now()
    t0 = now - 10 * DAY
    issue = fabricate(make_issue("M"), t0, [(t0 + DAY, st["in_progress"]),
                                            (t0 + 3 * DAY, st["done"])])
    from apps.issues.models import Issue, Resolution

    Issue.objects.filter(pk=issue.pk).update(resolution=Resolution.objects.first())
    issue.refresh_from_db()
    moved = move_issue(admin, issue, other)
    api.login(admin)
    k = flow(api, projects="OTR")["kpis"]
    assert k["resolved"] == 1
    assert k["lead"]["p50"] == pytest.approx(72, abs=0.1)
    assert k["cycle"]["p50"] == pytest.approx(48, abs=0.1)
    assert flow(api, projects="GES")["kpis"]["resolved"] == 0
    data = flow(api, projects="GES,OTR", group_by="project")
    assert [(g["label"], g["resolved"]) for g in data["by_group"]] == [("Otro", 1)]
    cc = api.get("/analytics/control-chart?projects=OTR").json()
    assert cc["points"][0]["key"] == moved.key


def test_query_count_is_constant(api, admin, make_issue, st, django_assert_max_num_queries):
    now = timezone.now()

    def make(n):
        for i in range(n):
            t0 = now - (20 + i % 7) * DAY
            fabricate(make_issue(f"Q{i}"), t0, [(t0 + DAY, st["in_progress"]),
                                                (t0 + (2 + i % 5) * DAY, st["review"]),
                                                (t0 + (4 + i % 9) * DAY, st["done"])])

    api.login(admin)
    urls = ["/analytics/flow?group_by=assignee", "/analytics/control-chart?group_by=type",
            "/analytics/time-in-status"]

    def counts():
        out = []
        for url in urls:
            cache.clear()
            with CaptureQueriesContext(connection) as ctx:
                assert api.get(url).status_code == 200
            out.append(len(ctx.captured_queries))
        return out

    make(3)
    small = counts()
    make(40)
    assert counts() == small
    cache.clear()
    with django_assert_max_num_queries(14):
        assert api.get(urls[0]).json()["kpis"]["resolved"] == 43
    # cached for the same user and query
    with django_assert_max_num_queries(4):
        assert api.get(urls[0]).status_code == 200


def test_meta_and_gadgets(api, admin, scenario):
    api.login(admin)
    meta = api.get("/meta").json()
    a = meta["analytics"]
    assert {g["value"] for g in a["group_by"]} >= {"project", "type", "priority", "assignee"}
    assert a["max_range_days"] == 366 and {m["value"] for m in a["metrics"]} == {"cycle", "lead"}
    kinds = {g["value"]: g["label"] for g in meta["gadget_kinds"]}
    assert "control_chart" in kinds and "cycle_time" in kinds
    r = api.post("/dashboard-gadgets/preview",
                 {"kind": "control_chart", "config": {"jql": "project = GES", "days": 30}})
    assert r.status_code == 200, r.content
    assert r.json()["total"] == 2 and r.json()["days"] == 30
    r = api.post("/dashboard-gadgets/preview", {"kind": "cycle_time", "config": {"days": 9999}})
    assert r.status_code == 200, r.content
    assert r.json()["days"] == 366 and r.json()["cycle_count"] == 2
    r = api.post("/dashboard-gadgets/preview",
                 {"kind": "control_chart", "config": {"metric": "x"}})
    assert r.status_code == 422


def test_team_dimension_when_available(api, admin, scenario):
    from apps.analytics.scope import dimensions

    if "team" not in dimensions():
        pytest.skip("Issue.team no existe en esta instalación")
    from apps.plans.models import Team

    team = Team.objects.create(name="Plataforma")
    from apps.issues.models import Issue

    Issue.objects.filter(pk=scenario["a"].pk).update(team=team)
    data = flow(api.login(admin), group_by="team")
    rows = {g["label"]: g["resolved"] for g in data["by_group"]}
    assert rows == {"Plataforma": 1, "Sin equipo": 2}
