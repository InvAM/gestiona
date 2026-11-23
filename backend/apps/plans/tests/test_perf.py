"""Medición del cronograma con un plan de ~20.000 incidencias (no corre por defecto).

    GESTIONA_PERF=1 uv run pytest apps/plans/tests/test_perf.py -s

Imprime la mediana de 3 llamadas (ms) y el número de consultas de cada endpoint."""

import os
import random
import statistics
import time
from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not os.environ.get("GESTIONA_PERF"), reason="medición: GESTIONA_PERF=1"),
]

EPICS, STORIES, SUBTASKS = 200, 6000, 3800  # per project, two projects → 20.000


def _seed_project(rnd, project, types, admin, users, teams, priority):
    from apps.issues.models import Issue
    from apps.issues.services import workflow_for
    from apps.projects.models import Version

    statuses = {lvl: list(workflow_for(project, types[name]).statuses.all())
                for lvl, name in ((1, "Épica"), (0, "Historia"), (-1, "Subtarea"))}
    versions = [Version.objects.create(project=project, name=f"{project.key} v{n}",
                                       release_date=date(2027, 1 + n, 1)) for n in range(5)]
    counter = iter(range(1, 10**6))

    def build(type_name, lvl, parent=None, **kw):
        n = next(counter)
        return Issue(project=project, number=n, key=f"{project.key}-{n}",
                     issue_type=types[type_name], summary=f"{type_name} {n}",
                     status=rnd.choice(statuses[lvl]), priority=priority, reporter=admin,
                     parent=parent, rank=f"r{n:07d}", **kw)

    epics = Issue.objects.bulk_create([build("Épica", 1) for _ in range(EPICS)])
    stories = []
    for _ in range(STORIES):
        start = date(2026, 6, 1) + timedelta(days=rnd.randrange(540))
        stories.append(build(
            "Historia", 0, rnd.choice(epics), team=rnd.choice(teams),
            assignee=rnd.choice(users + [None]), story_points=rnd.choice([1, 2, 3, 5, 8]),
            start_date=start, due_date=start + timedelta(days=rnd.randrange(3, 30))))
    stories = Issue.objects.bulk_create(stories, batch_size=2000)
    Issue.objects.bulk_create([build("Subtarea", -1, rnd.choice(stories))
                               for _ in range(SUBTASKS)], batch_size=2000)
    project.issue_counter = next(counter) - 1
    project.save(update_fields=["issue_counter"])
    through = Issue.fix_versions.through
    through.objects.bulk_create([through(issue_id=x.id, version_id=rnd.choice(versions).id)
                                 for x in stories], batch_size=5000)
    return stories, versions


def _seed(admin, member, projects, types):
    from apps.issues.models import IssueLink, IssueLinkType, Priority
    from apps.plans.models import Team

    rnd = random.Random(7)
    priority = Priority.objects.first()
    teams = [Team.objects.create(name=f"Equipo {n}", capacity_points=40) for n in range(4)]
    stories_all, versions = [], []
    for project in projects:
        stories, vs = _seed_project(rnd, project, types, admin, [admin, member], teams,
                                    priority)
        stories_all += stories
        versions += vs
    lt = IssueLinkType.objects.get(is_dependency=True)
    pairs = set()
    while len(pairs) < 3000:
        a, b = rnd.sample(stories_all, 2)
        pairs.add((a.id, b.id))
    IssueLink.objects.bulk_create([IssueLink(link_type=lt, source_id=a, target_id=b)
                                   for a, b in pairs], batch_size=3000)
    with connection.cursor() as c:
        for table in ("issues_issue", "issues_issue_fix_versions", "issues_issuelink",
                      "projects_project", "projects_projectmember", "plans_plan_projects"):
            c.execute(f"ANALYZE {table}")
    return teams, versions


def _measure(label, fn, out):
    times, queries = [], 0
    for _ in range(3):
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = fn()
            times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, r.content[:300]
        queries = len(ctx.captured_queries)
    out.append((label, statistics.median(times), queries, len(r.content)))
    return r.json()


def test_timeline_with_20k_issues(api, admin, member, project, types):
    from apps.issues.models import Issue
    from apps.projects.services import create_project

    other = create_project(admin, name="Plataforma", key="PLA", template="scrum")
    t0 = time.perf_counter()
    teams, versions = _seed(admin, member, [project, other], types)
    seed_s = time.perf_counter() - t0
    api.login(admin)
    r = api.post("/plans", {"name": "Grande", "project_ids": [project.id, other.id],
                            "teams": [{"team_id": t.id} for t in teams]})
    pid = r.json()["id"]
    rel = api.post(f"/plans/{pid}/releases", {"name": "R1", "target_date": "2027-03-01",
                                              "version_ids": [v.id for v in versions[:3]]})
    assert rel.status_code == 201
    out = []

    def rows(**body):
        return api.post(f"/plans/{pid}/timeline/rows", body)

    meta = _measure("GET timeline (meta)", lambda: api.get(f"/plans/{pid}/timeline"), out)
    assert meta["total"] == Issue.objects.count() == 20000
    for gb in ("none", "project", "team", "version"):
        _measure(f"POST timeline/groups {gb}", lambda gb=gb: api.post(
            f"/plans/{pid}/timeline/groups", {"group_by": gb}), out)
    first = _measure("POST rows: 1ª página (100 épicas)", lambda: rows(), out)
    # by team the stories are roots (their epics have no team): ~1500 per team
    team_group = {"group_by": "team", "group": f"t{teams[0].id}"}
    page = rows(**team_group).json()
    assert page["total"] > 1000
    for _ in range(10):  # 1000 rows deep
        cursor = page["next_cursor"]
        page = rows(cursor=cursor, **team_group).json()
    _measure("POST rows: grupo equipo, página 11 (cursor)",
             lambda: rows(cursor=cursor, **team_group), out)
    epic = first["rows"][0]
    _measure(f"POST rows: hijas de una épica ({epic['children_count']})",
             lambda: rows(parent_id=epic["id"]), out)
    _measure("POST rows: 500 raíces del grupo versión", lambda: rows(
        group_by="version", group=f"v{versions[0].id}", limit=500), out)
    _measure("POST rows: filtro equipo+responsable", lambda: rows(
        filters={"team_ids": [teams[0].id], "assignee_ids": [member.id]}), out)
    _measure("GET conflicts", lambda: api.get(f"/plans/{pid}/conflicts"), out)
    _measure("GET capacity (4 equipos)", lambda: api.get(f"/plans/{pid}/capacity"), out)
    _measure("GET releases", lambda: api.get(f"/plans/{pid}/releases"), out)

    print(f"\nSiembra: 20.000 incidencias en {seed_s:.1f} s")
    print(f"{'endpoint':48} {'ms':>8} {'consultas':>10} {'KB':>8}")
    for label, ms, q, size in out:
        print(f"{label:48} {ms:8.1f} {q:10d} {size / 1024:8.1f}")
