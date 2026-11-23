"""Cronograma paginado: cursor estable, carga por niveles, filtros y grupos en el servidor,
dependencias y conflictos con incidencias sin cargar, permisos y consultas acotadas."""

from datetime import date

import pytest

pytestmark = pytest.mark.django_db

# Requests are made by the logged-in test client: session + user lookups are included.
MAX_QUERIES = 14


@pytest.fixture
def secret(admin):
    from apps.projects.services import create_project

    return create_project(admin, name="Secreto", key="SEC", template="scrum", access="private")


@pytest.fixture
def other(admin, member):
    from apps.projects.models import Role
    from apps.projects.services import create_project, set_member

    p = create_project(admin, name="Plataforma", key="PLA", template="scrum")
    set_member(admin, p, member.id, Role.objects.get(name="Miembro").id)
    return p


def _plan(api, user, **body):
    api.login(user)
    r = api.post("/plans", {"name": "Hoja de ruta", "access": "public", **body})
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def _rows(api, pid, **body):
    r = api.post(f"/plans/{pid}/timeline/rows", body)
    assert r.status_code == 200, r.json()
    return r.json()


def _all(api, pid, **body):
    """Follow the cursor to the end; returns (keys in order, pages)."""
    keys, cursor, pages = [], body.pop("cursor", None), []
    while True:
        page = _rows(api, pid, cursor=cursor, **body)
        pages.append(page)
        keys += [r["key"] for r in page["rows"]]
        cursor = page["next_cursor"]
        if not cursor:
            return keys, pages


def _groups(api, pid, group_by, **filters):
    r = api.post(f"/plans/{pid}/timeline/groups", {"group_by": group_by, "filters": filters})
    assert r.status_code == 200, r.json()
    return r.json()


def _blocks(blocker, blocked):
    from apps.issues.models import IssueLink, IssueLinkType

    IssueLink.objects.create(link_type=IssueLinkType.objects.get(is_dependency=True),
                             source=blocker, target=blocked)


# ------------------------------------------------------------------ cursor

def test_rows_page_by_a_stable_cursor(api, admin, project, other, make_issue):
    epics = [make_issue(f"Épica {n}", type_name="Épica", project=p)
             for n, p in enumerate([other, project, project])]
    tasks = [make_issue(f"Tarea {n}", project=project if n % 2 else other) for n in range(13)]
    pid = _plan(api, admin, project_ids=[project.id, other.id])

    keys, pages = _all(api, pid, limit=4)
    # epics first, then project key (GES < PLA), then rank (creation order here)
    expected = [e.key for e in sorted(epics, key=lambda e: (e.project.key, e.rank))] + \
        [t.key for t in sorted(tasks, key=lambda t: (t.project.key, t.rank))]
    assert keys == expected
    assert [len(p["rows"]) for p in pages] == [4, 4, 4, 4]
    assert pages[0]["total"] == 16 and all(p["total"] is None for p in pages[1:])

    # inserting while paging neither repeats nor skips what was already returned
    first = _rows(api, pid, limit=5)
    make_issue("Nueva", project=project)
    rest, _ = _all(api, pid, limit=5, cursor=first["next_cursor"])
    seen = [r["key"] for r in first["rows"]] + rest
    assert len(seen) == len(set(seen)) == 17

    r = api.post(f"/plans/{pid}/timeline/rows", {"cursor": "no-es-un-cursor"})
    assert r.status_code == 422 and r.json()["code"] == "cursor"
    r = api.post(f"/plans/{pid}/timeline/rows", {"limit": 501})
    assert r.status_code == 422 and r.json()["code"] == "limit"


# ------------------------------------------------------------------ hierarchy + filters

def test_children_load_on_expand_and_filters_run_on_the_server(api, admin, member, project,
                                                               make_issue):
    epic = make_issue("Épica", type_name="Épica")
    mine = make_issue("Mía", type_name="Historia", parent_id=epic.id, assignee_id=member.id,
                      start_date=date(2026, 12, 1), due_date=date(2026, 12, 9))
    make_issue("Libre", type_name="Historia", parent_id=epic.id,
               due_date=date(2027, 1, 20))
    sub = make_issue("Sub", type_name="Subtarea", parent_id=mine.id,
                     start_date=date(2026, 11, 25), due_date=date(2026, 11, 26))
    pid = _plan(api, admin, project_ids=[project.id])

    roots = _rows(api, pid)["rows"]
    assert [r["key"] for r in roots] == [epic.key]
    # an epic without dates rolls up its whole subtree (children and grandchildren)
    assert roots[0]["children_count"] == 2
    assert (roots[0]["rollup_start"], roots[0]["rollup_end"]) == ("2026-11-25", "2027-01-20")
    kids = _rows(api, pid, parent_id=epic.id)
    assert [r["key"] for r in kids["rows"]] == [mine.key, "GES-3"] and kids["total"] == 2
    assert kids["rows"][0]["children_count"] == 1

    # the parent is filtered out → its matching children become roots of the view
    only_mine = _rows(api, pid, filters={"assignee_ids": [member.id]})
    assert [r["key"] for r in only_mine["rows"]] == [mine.key]
    assert only_mine["rows"][0]["children_count"] == 0  # the sub-task is unassigned
    unassigned = _rows(api, pid, filters={"assignee_ids": [0]})
    assert [r["key"] for r in unassigned["rows"]] == [epic.key, sub.key]
    assert unassigned["rows"][0]["children_count"] == 1
    assert _groups(api, pid, "none", assignee_ids=[0])["total"] == 3


def test_groups_have_server_counts_and_their_own_roots(api, admin, project, other,
                                                       make_issue):
    from apps.projects.models import Version

    team = api.login(admin).post("/teams", {"name": "Alfa"}).json()
    v1 = Version.objects.create(project=project, name="1.0", release_date=date(2026, 12, 1))
    v2 = Version.objects.create(project=other, name="2.0")
    a = make_issue("A", team_id=team["id"])
    a.fix_versions.set([v1])
    b = make_issue("B", project=other)
    b.fix_versions.set([v1, v2])
    make_issue("C", project=other, team_id=team["id"])
    pid = _plan(api, admin, project_ids=[project.id, other.id],
                teams=[{"team_id": team["id"]}])

    g = _groups(api, pid, "project")
    assert [(x["key"], x["count"]) for x in g["groups"]] == \
        [(f"p{project.id}", 1), (f"p{other.id}", 2)]
    g = _groups(api, pid, "team")
    assert [(x["label"], x["count"]) for x in g["groups"]] == [("Alfa", 2), ("Sin equipo", 1)]
    g = _groups(api, pid, "version")
    assert [(x["key"], x["label"], x["count"]) for x in g["groups"]] == [
        (f"v{v1.id}", "1.0 · GES", 2), (f"v{v2.id}", "2.0 · PLA", 1), ("v0", "Sin versión", 1)]
    assert _groups(api, pid, "version", project_ids=[other.id])["total"] == 2

    def keys(**body):
        return [r["key"] for r in _rows(api, pid, **body)["rows"]]

    assert keys(group_by="version", group=f"v{v1.id}") == [a.key, b.key]  # in both groups
    assert keys(group_by="version", group=f"v{v2.id}") == [b.key]
    assert keys(group_by="version", group="v0") == ["PLA-2"]
    assert keys(group_by="team", group="t0") == [b.key]
    assert keys(group_by="team", group=f"t{team['id']}", filters={"version_ids": [0]}) == \
        ["PLA-2"]

    assert api.post(f"/plans/{pid}/timeline/groups", {"group_by": "x"}).json()["code"] == \
        "group_by"
    r = api.post(f"/plans/{pid}/timeline/rows", {"group_by": "team", "group": "p1"})
    assert r.status_code == 422 and r.json()["code"] == "group"


# ------------------------------------------------------------------ dependencies

def test_dependencies_and_conflicts_work_with_unloaded_issues(api, admin, member, project,
                                                              secret, make_issue):
    from apps.issues.services import archive_issue

    a = make_issue("A", start_date=date(2026, 12, 1), due_date=date(2026, 12, 10))
    b = make_issue("B", start_date=date(2026, 12, 5), due_date=date(2026, 12, 20))
    c = make_issue("C", due_date=date(2026, 12, 30))
    gone = make_issue("Archivada", start_date=date(2026, 12, 2))
    hidden = make_issue("Oculta", project=secret, start_date=date(2027, 1, 5))
    _blocks(a, b)  # conflict: A ends on the 10th, B starts on the 5th
    _blocks(b, c)  # c starts (due) on the 30th: fine
    _blocks(a, gone)
    _blocks(hidden, c)  # conflict, but only for whoever can see SEC
    archive_issue(admin, gone)
    pid = _plan(api, admin, project_ids=[project.id, secret.id])

    # page 1 holds only A: its arrow to B comes with B's dates although B is not loaded
    first = _rows(api, pid, limit=1)
    assert [r["key"] for r in first["rows"]] == [a.key]
    [dep] = first["dependencies"]
    assert dep["blocked"] == {"id": b.id, "key": b.key, "summary": "B",
                              "project_id": project.id, "start_date": "2026-12-05",
                              "due_date": "2026-12-20", "can_link": True}
    assert dep["conflict"] is True and dep["blocker"]["key"] == a.key

    conflicts = api.get(f"/plans/{pid}/conflicts").json()
    assert conflicts["count"] == 2 and not conflicts["truncated"]
    assert {(x["blocker"]["key"], x["blocked"]["key"]) for x in conflicts["conflicts"]} == \
        {(a.key, b.key), (hidden.key, c.key)}
    assert api.get(f"/plans/{pid}/conflicts?limit=1").json()["truncated"] is True

    api.login(member)  # cannot browse SEC: neither its issues nor its links leak
    assert api.get(f"/plans/{pid}/conflicts").json()["count"] == 1
    _, pages = _all(api, pid, limit=2)
    deps = {d["id"]: (d["blocker"]["key"], d["blocked"]["key"])
            for p in pages for d in p["dependencies"]}
    assert set(deps.values()) == {(a.key, b.key), (b.key, c.key)}


# ------------------------------------------------------------------ meta + permissions

def test_meta_catalogs_cover_the_whole_visible_plan(api, admin, member, project, secret,
                                                    make_issue):
    from apps.issues.services import archive_issue

    make_issue("A", assignee_id=member.id, start_date=date(2026, 10, 1))
    make_issue("B", due_date=date(2027, 3, 1))
    old = make_issue("Vieja", due_date=date(2020, 1, 1))
    archive_issue(admin, old)
    make_issue("Oculta", project=secret, assignee_id=admin.id, due_date=date(2030, 1, 1))
    pid = _plan(api, admin, project_ids=[project.id, secret.id])

    api.login(member)
    meta = api.get(f"/plans/{pid}/timeline").json()
    assert meta["total"] == 2  # no archived, nothing from SEC
    assert meta["date_range"] == {"start": "2026-10-01", "end": "2027-03-01"}
    assert [u["id"] for u in meta["assignees"]] == [member.id]
    assert len(meta["statuses"]) == 1 and meta["page_max"] == 500
    assert _groups(api, pid, "project")["groups"] == [
        {"key": f"p{project.id}", "label": "Gestiona Core (GES)", "count": 2}]
    # asking for a group of a project you cannot see returns nothing
    assert _rows(api, pid, group_by="project", group=f"p{secret.id}")["rows"] == []
    api.login(admin)
    assert api.get(f"/plans/{pid}/timeline").json()["total"] == 3


def test_capacity_counts_the_whole_plan_not_what_is_loaded(api, admin, project, make_issue):
    team = api.login(admin).post("/teams", {"name": "Alfa", "capacity_points": "5"}).json()
    for n in range(12):
        make_issue(f"T{n}", type_name="Historia", team_id=team["id"], story_points=2)
    pid = _plan(api, admin, project_ids=[project.id], teams=[{"team_id": team["id"]}])
    assert len(_rows(api, pid, limit=3)["rows"]) == 3
    cap = api.get(f"/plans/{pid}/capacity").json()["teams"][0]
    assert cap["unscheduled"] == {"assigned": 24.0, "issue_count": 12}


# ------------------------------------------------------------------ query count

@pytest.mark.parametrize("group_by", ["none", "project", "team", "version"])
def test_query_count_does_not_grow_with_the_plan(api, admin, project, other, make_issue,
                                                 django_assert_max_num_queries, group_by):
    from apps.projects.models import Version

    team = api.login(admin).post("/teams", {"name": "Alfa"}).json()
    version = Version.objects.create(project=project, name="1.0")

    def seed(n):
        for k in range(n):
            epic = make_issue(f"E{k}", type_name="Épica", project=other if k % 2 else project,
                              team_id=team["id"])
            story = make_issue(f"H{k}", type_name="Historia", parent_id=epic.id,
                               project=epic.project, start_date=date(2026, 12, 1 + k % 20))
            story.fix_versions.set([version])
            _blocks(story, make_issue(f"T{k}", project=epic.project, due_date=date(2026, 12, 3)))

    def measure(pid):
        group = {"none": "all", "project": f"p{project.id}", "team": f"t{team['id']}",
                 "version": f"v{version.id}"}[group_by]
        with django_assert_max_num_queries(MAX_QUERIES):
            assert api.get(f"/plans/{pid}/timeline").status_code == 200
        with django_assert_max_num_queries(MAX_QUERIES):
            _groups(api, pid, group_by)
        with django_assert_max_num_queries(MAX_QUERIES):
            page = _rows(api, pid, group_by=group_by, group=group, limit=50)
        with django_assert_max_num_queries(MAX_QUERIES):
            _rows(api, pid, group_by=group_by, group=group, cursor=page["next_cursor"])
        with django_assert_max_num_queries(MAX_QUERIES):
            _rows(api, pid, group_by=group_by, group=group, parent_id=page["rows"][0]["id"])
        with django_assert_max_num_queries(MAX_QUERIES):
            assert api.get(f"/plans/{pid}/conflicts").status_code == 200

    seed(2)
    pid = _plan(api, admin, project_ids=[project.id, other.id], teams=[{"team_id": team["id"]}])
    measure(pid)
    seed(40)  # 20x the issues, links and versions: same bound
    measure(pid)
