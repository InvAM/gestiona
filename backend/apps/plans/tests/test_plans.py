"""Planes: permissions, dependencies, capacity, cross-project releases, `team` in JQL and
soft delete of plans and teams."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def secret(admin):
    """A private project `member` cannot browse."""
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
    r = api.post("/plans", {"name": "Hoja de ruta", **body})
    assert r.status_code == 201, r.json()
    return r.json()


def _team(api, user, **body):
    api.login(user)
    r = api.post("/teams", {"name": "Alfa", **body})
    assert r.status_code == 201, r.json()
    return r.json()


def _rows(api, pid, **body):
    """First page of the plan roots (no grouping, no filters)."""
    r = api.post(f"/plans/{pid}/timeline/rows", body)
    assert r.status_code == 200, r.json()
    return r.json()


def _keys(data):
    return {i["key"] for i in data["rows"]}


# ------------------------------------------------------------------ permissions

def test_plan_only_shows_what_the_viewer_can_browse(api, admin, member, outsider, project,
                                                    secret, make_issue):
    from apps.issues.services import archive_issue

    visible = make_issue("Visible")
    hidden = make_issue("Oculta", project=secret)
    archived = make_issue("Archivada")
    archive_issue(admin, archived)

    plan = _plan(api, admin, project_ids=[project.id, secret.id], access="public")
    assert _keys(_rows(api, plan["id"])) == {visible.key, hidden.key}

    api.login(member)
    data = _rows(api, plan["id"])
    assert _keys(data) == {visible.key}  # never the private project, never archived
    meta = api.get(f"/plans/{plan['id']}").json()
    assert [p["key"] for p in meta["projects"]] == ["GES"]
    assert meta["hidden_project_count"] == 1 and meta["can_edit"] is False

    # a plan JQL naming a project the viewer cannot see fails closed, it does not leak
    api.login(admin)
    api.patch(f"/plans/{plan['id']}", {"filter_jql": "project = SEC"})
    api.login(member)
    assert _rows(api, plan["id"])["rows"] == []
    assert api.get(f"/plans/{plan['id']}/timeline").json()["filter_error"]

    # editing a plan never drops sources the editor cannot see
    api.login(admin)
    from apps.plans.models import Plan

    p = Plan.objects.get(pk=plan["id"])
    p.owner = member
    p.save()
    api.login(member)
    assert api.patch(f"/plans/{plan['id']}", {"project_ids": [project.id], "filter_jql": ""}
                     ).status_code == 200
    assert set(p.projects.values_list("key", flat=True)) == {"GES", "SEC"}
    # and cannot add projects they cannot see
    assert api.patch(f"/plans/{plan['id']}", {"project_ids": [secret.id]}).status_code == 422

    api.login(outsider)
    assert _keys(_rows(api, plan["id"])) == {visible.key}


def test_plan_access_private_shared_public(api, admin, member, outsider, project):
    plan = _plan(api, admin, project_ids=[project.id])
    for user in (member, outsider):
        api.login(user)
        assert api.get(f"/plans/{plan['id']}").status_code == 404
        assert api.get("/plans").json() == []

    api.login(admin)
    api.patch(f"/plans/{plan['id']}", {"access": "shared", "shared_with_ids": [member.id]})
    api.login(member)
    assert api.get(f"/plans/{plan['id']}").status_code == 200
    assert api.patch(f"/plans/{plan['id']}", {"name": "X"}).status_code == 403
    api.login(outsider)
    assert api.get(f"/plans/{plan['id']}").status_code == 404

    api.login(admin)
    api.patch(f"/plans/{plan['id']}", {"access": "public"})
    api.login(outsider)
    assert [p["name"] for p in api.get("/plans").json()] == ["Hoja de ruta"]


def test_any_user_can_create_plans_but_only_with_visible_projects(api, member, project,
                                                                  secret):
    _plan(api, member, project_ids=[project.id])
    api.login(member)
    assert api.post("/plans", {"name": "X", "project_ids": [secret.id]}).status_code == 422
    bad = api.post("/plans", {"name": "X", "filter_jql": "project = NOPE"})
    assert bad.status_code == 422 and bad.json()["code"] == "filter_jql"


def test_issue_edits_respect_project_permissions(api, admin, member, outsider, project,
                                                 make_issue):
    issue = make_issue("Planificable")
    plan = _plan(api, admin, project_ids=[project.id], access="public")
    api.login(outsider)  # limited project: outsiders browse but cannot edit
    row = _rows(api, plan["id"])["rows"][0]
    assert row["can_edit"] is False
    r = api.patch(f"/issues/{issue.key}", {"start_date": "2026-12-01"})
    assert r.status_code == 403
    api.login(member)
    assert _rows(api, plan["id"])["rows"][0]["can_edit"] is True
    r = api.patch(f"/issues/{issue.key}", {"start_date": "2026-12-01", "due_date": "2026-12-09"})
    assert r.status_code == 200 and r.json()["due_date"] == "2026-12-09"


# ------------------------------------------------------------------ dependencies

def test_dependencies_use_the_flag_and_flag_date_conflicts(api, admin, project, make_issue):
    from apps.issues.models import IssueLinkType

    blocking = IssueLinkType.objects.get(is_dependency=True)  # seeded by data migration
    related = IssueLinkType.objects.filter(is_dependency=False).first()
    blocking.name = "Precede"  # renaming does not matter: plans read the flag
    blocking.save()

    a = make_issue("Backend", start_date=date(2026, 12, 1), due_date=date(2026, 12, 10))
    b = make_issue("Frontend", start_date=date(2026, 12, 5), due_date=date(2026, 12, 20))
    c = make_issue("Docs", start_date=date(2026, 12, 11), due_date=date(2026, 12, 12))
    plan = _plan(api, admin, project_ids=[project.id])

    # created from the plan view through the regular link endpoint
    for target in (b, c):
        r = api.post(f"/issues/{a.key}/links", {"link_type_id": blocking.id,
                                                 "target": target.key})
        assert r.status_code == 200
    api.post(f"/issues/{b.key}/links", {"link_type_id": related.id, "target": c.key})

    meta = api.get(f"/plans/{plan['id']}/timeline").json()
    assert [lt["id"] for lt in meta["dependency_link_types"]] == [blocking.id]
    data = _rows(api, plan["id"])
    deps = {(d["blocker_id"], d["blocked_id"]): d for d in data["dependencies"]}
    assert set(deps) == {(a.id, b.id), (a.id, c.id)}  # the «relates» link is not drawn
    assert deps[(a.id, b.id)]["conflict"] is True  # A ends 10th, B starts 5th
    assert deps[(a.id, c.id)]["conflict"] is False
    conflicts = api.get(f"/plans/{plan['id']}/conflicts").json()
    assert conflicts["count"] == 1 and conflicts["conflicts"][0]["blocked"]["key"] == b.key

    # moving the blocked bar after the blocker resolves the conflict
    api.patch(f"/issues/{b.key}", {"start_date": "2026-12-11", "due_date": "2026-12-26"})
    assert api.get(f"/plans/{plan['id']}/conflicts").json()["count"] == 0

    lid = deps[(a.id, c.id)]["id"]
    assert api.delete(f"/links/{lid}").status_code == 204
    assert len(_rows(api, plan["id"])["dependencies"]) == 1


def test_dependency_flag_is_editable_on_link_types(api, admin):
    api.login(admin)
    r = api.post("/link-types", {"name": "Requiere", "outward": "es requisito de",
                                 "inward": "requiere", "is_dependency": True})
    assert r.status_code == 201 and r.json()["is_dependency"] is True
    lid = r.json()["id"]
    r = api.patch(f"/link-types/{lid}", {"name": "Requiere", "outward": "a", "inward": "b"})
    assert r.json()["is_dependency"] is True  # omitted = unchanged


def test_hierarchy_comes_from_levels(api, admin, project, make_issue):
    epic = make_issue("Épica grande", type_name="Épica")
    story = make_issue("Historia", type_name="Historia", parent_id=epic.id)
    sub = make_issue("Sub", type_name="Subtarea", parent_id=story.id)
    plan = _plan(api, admin, project_ids=[project.id])
    roots = _rows(api, plan["id"])["rows"]  # children come on expand
    assert [r["key"] for r in roots] == [epic.key]
    assert roots[0]["type"]["level"] == 1 and roots[0]["children_count"] == 1
    story_row = _rows(api, plan["id"], parent_id=epic.id)["rows"][0]
    assert story_row["key"] == story.key and story_row["type"]["level"] == 0
    assert story_row["parent_id"] == epic.id and story_row["children_count"] == 1
    sub_row = _rows(api, plan["id"], parent_id=story.id)["rows"][0]
    assert sub_row["key"] == sub.key and sub_row["type"]["level"] == -1


# ------------------------------------------------------------------ teams + capacity

def test_capacity_per_sprint_with_override(api, admin, project, make_issue):
    from apps.boards.models import Board
    from apps.boards.services import create_sprint

    board = Board.objects.filter(project=project).first()
    s1 = create_sprint(admin, board, "Sprint 1")
    s2 = create_sprint(admin, board, "Sprint 2")
    team = _team(api, admin, capacity_points="10", capacity_hours="40")
    other_team = _team(api, admin, name="Beta")
    plan = _plan(api, admin, project_ids=[project.id],
                 teams=[{"team_id": team["id"], "board_id": board.id}])

    make_issue("A", story_points=Decimal(8), sprint_id=s1.id, team_id=team["id"])
    make_issue("B", story_points=Decimal(5), sprint_id=s1.id, team_id=team["id"])
    make_issue("C", story_points=Decimal(3), sprint_id=s2.id, team_id=team["id"])
    make_issue("D", story_points=Decimal(4), team_id=team["id"])  # backlog
    make_issue("E", story_points=Decimal(50), sprint_id=s2.id, team_id=other_team["id"])
    epic = make_issue("Épica", type_name="Épica", team_id=team["id"])
    epic.story_points = Decimal(100)
    epic.save()

    cap = api.get(f"/plans/{plan['id']}/capacity").json()
    assert cap["unit"] == "story_points" and len(cap["teams"]) == 1
    t = cap["teams"][0]
    assert t["mode"] == "sprints" and t["default_capacity"] == 10
    its = {i["sprint_id"]: i for i in t["iterations"]}
    assert its[s1.id]["assigned"] == 13 and its[s1.id]["over"] is True
    assert its[s2.id]["assigned"] == 3 and its[s2.id]["over"] is False
    assert t["unscheduled"] == {"assigned": 4, "issue_count": 1}

    # override the capacity of sprint 1 only
    r = api.put(f"/plans/{plan['id']}/capacity",
                {"team_id": team["id"], "sprint_id": s1.id, "capacity": "15"})
    assert r.status_code == 200
    its = {i["sprint_id"]: i for i in r.json()["teams"][0]["iterations"]}
    assert its[s1.id]["capacity"] == 15 and its[s1.id]["overridden"] is True
    assert its[s1.id]["over"] is False and its[s2.id]["capacity"] == 10
    # back to the default
    r = api.put(f"/plans/{plan['id']}/capacity",
                {"team_id": team["id"], "sprint_id": s1.id, "capacity": None})
    its = {i["sprint_id"]: i for i in r.json()["teams"][0]["iterations"]}
    assert its[s1.id]["capacity"] == 10 and its[s1.id]["overridden"] is False

    # hours: original estimates of leaf work against the hours capacity
    api.patch(f"/plans/{plan['id']}", {"estimation": "hours"})
    make_issue("F", original_estimate=45 * 3600, sprint_id=s2.id, team_id=team["id"])
    t = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    its = {i["sprint_id"]: i for i in t["iterations"]}
    assert t["default_capacity"] == 40 and its[s2.id]["assigned"] == 45
    assert its[s2.id]["over"] is True

    # a sprint of another board cannot be overridden through this team
    assert api.put(f"/plans/{plan['id']}/capacity",
                   {"team_id": other_team["id"], "sprint_id": s1.id, "capacity": 1}
                   ).status_code == 422


def test_capacity_fixed_iterations_without_sprints(api, admin, project, make_issue):
    from apps.plans.models import Plan
    from apps.plans.services import plan_capacity

    team = _team(api, admin, capacity_points="5")
    from django.utils import timezone

    today = timezone.localdate()
    anchor = today - timedelta(days=today.weekday())
    plan = _plan(api, admin, project_ids=[project.id], iteration_days=7,
                 iteration_start=anchor.isoformat(), teams=[{"team_id": team["id"]}])
    make_issue("Esta semana", story_points=Decimal(3), due_date=anchor + timedelta(days=2),
               team_id=team["id"])
    make_issue("También", story_points=Decimal(4), start_date=anchor, team_id=team["id"])
    make_issue("Próxima", story_points=Decimal(2), due_date=anchor + timedelta(days=8),
               team_id=team["id"])
    make_issue("Sin fecha", story_points=Decimal(1), team_id=team["id"])

    t = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    assert t["mode"] == "fixed" and t["board"] is None
    its = {i["start"]: i for i in t["iterations"]}
    current = its[anchor.isoformat()]
    assert current["assigned"] == 7 and current["over"] is True and current["state"] == "active"
    assert its[(anchor + timedelta(days=7)).isoformat()]["assigned"] == 2
    assert t["unscheduled"]["assigned"] == 1

    r = api.put(f"/plans/{plan['id']}/capacity",
                {"team_id": team["id"], "iteration_start": anchor.isoformat(), "capacity": 8})
    assert r.status_code == 200
    its = {i["start"]: i for i in r.json()["teams"][0]["iterations"]}
    assert its[anchor.isoformat()]["over"] is False
    # misaligned iteration start
    bad = api.put(f"/plans/{plan['id']}/capacity",
                  {"team_id": team["id"], "iteration_start":
                   (anchor + timedelta(days=1)).isoformat(), "capacity": 8})
    assert bad.status_code == 422
    # a kanban board has no sprints: it cannot drive a team's iterations
    from apps.boards.models import Board

    kanban = Board.objects.create(project=project, name="Kanban", kind=Board.Kind.KANBAN)
    r = api.patch(f"/plans/{plan['id']}", {"teams": [{"team_id": team["id"],
                                                      "board_id": kanban.id}]})
    assert r.status_code == 422 and r.json()["code"] == "teams"
    # the service honours the requested window size
    p = Plan.objects.get(pk=plan["id"])
    assert len(plan_capacity(admin, p, count=3)["teams"][0]["iterations"]) == 3


def test_capacity_only_counts_visible_issues(api, admin, member, project, secret,
                                             make_issue):
    team = _team(api, admin, capacity_points="5")
    plan = _plan(api, admin, project_ids=[project.id, secret.id], access="public",
                 teams=[{"team_id": team["id"]}])
    make_issue("Pública", story_points=Decimal(2), team_id=team["id"])
    make_issue("Secreta", story_points=Decimal(9), team_id=team["id"], project=secret)
    api.login(member)
    t = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    assert t["unscheduled"]["assigned"] == 2


# ------------------------------------------------------------------ team field + JQL

def test_team_field_on_issues_and_jql(api, admin, member, project, make_issue):
    alpha = _team(api, admin, name="Equipo Alfa")
    beta = _team(api, admin, name="Beta")
    a = make_issue("Con alfa")
    b = make_issue("Con beta", team_id=beta["id"])
    make_issue("Sin equipo")

    api.login(member)
    r = api.patch(f"/issues/{a.key}", {"team": alpha["id"]})
    assert r.status_code == 200 and r.json()["team"] == {"id": alpha["id"],
                                                          "name": "Equipo Alfa"}
    hist = api.get(f"/issues/{a.key}/history").json()[0]["items"][0]
    assert hist["field"] == "team" and hist["to_display"] == "Equipo Alfa"

    def keys(jql):
        r = api.post("/search", {"jql": jql})
        assert r.status_code == 200, r.json()
        return {i["key"] for i in r.json()["issues"]}

    assert keys('team = "Equipo Alfa"') == {a.key}
    assert keys(f'equipo in ("Equipo Alfa", {beta["id"]})') == {a.key, b.key}
    assert keys("team is EMPTY") == {i.key for i in project.issues.filter(team__isnull=True)}
    assert keys('team != Beta AND team is not EMPTY') == {a.key}
    assert keys("project = GES ORDER BY team ASC")
    assert api.post("/search", {"jql": 'team = "Nadie"'}).status_code == 400
    sugg = api.get("/search/suggest?field=team&value=alf").json()
    assert sugg == [{"value": '"Equipo Alfa"', "label": "Equipo Alfa"}]
    assert "team" in {f["name"] for f in api.get("/search/fields").json()["fields"]}
    # unknown team id → 422
    assert api.patch(f"/issues/{a.key}", {"team": 999999}).status_code == 422
    # clearing
    assert api.patch(f"/issues/{a.key}", {"team": None}).json()["team"] is None


def test_meta_exposes_plan_choices(api, member):
    api.login(member)
    plans = api.get("/meta").json()["plans"]
    assert {c["value"] for c in plans["access"]} == {"private", "shared", "public"}
    assert {c["value"] for c in plans["estimations"]} == {"story_points", "hours"}
    assert "team" in {f["value"] for f in api.get("/meta").json()["issue_fields"]}


# ------------------------------------------------------------------ releases

def test_cross_project_release_progress_and_late_issues(api, admin, member, project, other,
                                                        secret, make_issue):
    from apps.issues.services import transition_issue
    from apps.projects.services import save_version
    from apps.workflows.models import Status

    v1 = save_version(admin, project, None, name="1.0", release_date=date(2026, 12, 15))
    v2 = save_version(admin, other, None, name="Q4", release_date=date(2026, 12, 31))
    vs = save_version(admin, secret, None, name="S1")
    done = make_issue("Hecha", fix_version_ids=[v1.id])
    transition_issue(admin, done, to_status_id=Status.objects.filter(category="done").first().id)
    doing = make_issue("En curso", fix_version_ids=[v2.id], project=other,
                       due_date=date(2026, 12, 28))
    transition_issue(admin, doing,
                     to_status_id=Status.objects.filter(category="in_progress").first().id)
    late = make_issue("Tarde", fix_version_ids=[v1.id], due_date=date(2027, 1, 10))
    make_issue("Secreta", fix_version_ids=[vs.id], project=secret, due_date=date(2027, 2, 1))

    plan = _plan(api, admin, project_ids=[project.id, other.id, secret.id], access="public")
    r = api.post(f"/plans/{plan['id']}/releases", {
        "name": "Lanzamiento invierno", "target_date": "2026-12-31",
        "version_ids": [v1.id, v2.id, vs.id]})
    assert r.status_code == 201, r.json()
    rel = r.json()
    prog = {p["category"]: p["count"] for p in rel["progress"]}
    assert prog == {"todo": 2, "in_progress": 1, "done": 1} and rel["total"] == 4
    assert {i["key"] for i in rel["late_issues"]} == {late.key, "SEC-1"}

    # the member does not see the private project's version nor its issues
    api.login(member)
    rel = api.get(f"/plans/{plan['id']}/releases").json()[0]
    assert {v["name"] for v in rel["versions"]} == {"1.0", "Q4"}
    assert rel["total"] == 3 and [i["key"] for i in rel["late_issues"]] == [late.key]
    assert api.post(f"/plans/{plan['id']}/releases", {"name": "X"}).status_code == 403

    # versions of projects outside the plan are rejected; patch keeps hidden versions
    api.login(admin)
    outside = save_version(admin, other, None, name="Fuera")
    api.patch(f"/plans/{plan['id']}", {"project_ids": [project.id, secret.id]})
    assert api.patch(f"/plans/{plan['id']}/releases/{rel['id']}",
                     {"version_ids": [outside.id]}).status_code == 422
    r = api.patch(f"/plans/{plan['id']}/releases/{rel['id']}", {"target_date": "2027-03-01"})
    assert r.json()["late_count"] == 0
    assert api.delete(f"/plans/{plan['id']}/releases/{rel['id']}").status_code == 204
    assert api.get(f"/plans/{plan['id']}/releases").json() == []


# ------------------------------------------------------------------ soft delete

def test_plan_soft_delete_restore_and_purge(api, admin, member, project):
    plan = _plan(api, member, project_ids=[project.id], access="public")
    pid = plan["id"]
    api.login(admin)
    assert api.delete(f"/plans/{pid}").status_code == 403  # not the owner (and not superuser)
    api.login(member)
    assert api.delete(f"/plans/{pid}").status_code == 204
    assert api.get("/plans").json() == []
    assert api.get(f"/plans/{pid}").status_code == 404
    trash = api.get("/plans?deleted=true").json()
    assert [p["id"] for p in trash] == [pid] and trash[0]["deleted_at"]
    assert api.delete(f"/plans/{pid}?permanent=true").status_code == 403  # admin only
    r = api.post(f"/plans/{pid}/restore")
    assert r.status_code == 200 and r.json()["deleted_at"] is None
    assert [p["id"] for p in api.get("/plans").json()] == [pid]

    api.delete(f"/plans/{pid}")
    api.login(admin)
    assert [p["id"] for p in api.get("/plans?deleted=true").json()] == [pid]
    assert api.delete(f"/plans/{pid}?permanent=true").status_code == 204
    from apps.plans.models import Plan

    assert not Plan.all_objects.filter(pk=pid).exists()


def test_team_soft_delete_keeps_issues_and_protects_purge(api, admin, member, outsider,
                                                          project, make_issue):
    team = _team(api, member, member_ids=[member.id])
    tid = team["id"]
    issue = make_issue("Del equipo", team_id=tid)
    plan = _plan(api, admin, project_ids=[project.id], teams=[{"team_id": tid}])

    api.login(outsider)
    assert api.patch(f"/teams/{tid}", {"name": "Hack"}).status_code == 403
    assert api.delete(f"/teams/{tid}").status_code == 403

    api.login(member)
    assert api.get(f"/teams/{tid}").json()["issue_count"] == 1
    assert api.delete(f"/teams/{tid}").status_code == 204
    assert api.get("/teams").json() == []
    assert [t["id"] for t in api.get("/teams?deleted=true").json()] == [tid]
    # the issue keeps showing it, JQL no longer resolves it, it cannot be chosen again
    assert api.get(f"/issues/{issue.key}").json()["team"]["name"] == "Alfa"
    assert api.post("/search", {"jql": "team = Alfa"}).status_code == 400
    other = make_issue("Otra")
    assert api.patch(f"/issues/{other.key}", {"team": tid}).status_code == 422
    # the plan hides it from its teams, the data keeps the issue's (deleted) team
    api.login(admin)
    assert api.get(f"/plans/{plan['id']}").json()["teams"] == []
    teams = api.get(f"/plans/{plan['id']}/timeline").json()["teams"]
    assert teams == [{"id": tid, "name": "Alfa", "in_plan": False, "deleted": True}]

    # a new team can reuse the name; restoring the old one then clashes
    clash = _team(api, admin)
    api.login(member)
    r = api.post(f"/teams/{tid}/restore")
    assert r.status_code == 409 and r.json()["code"] == "name_taken"
    api.login(admin)
    api.delete(f"/teams/{clash['id']}")
    api.login(member)
    assert api.post(f"/teams/{tid}/restore").status_code == 200

    # hard delete: admin only, and PROTECT while issues use it
    assert api.delete(f"/teams/{tid}?permanent=true").status_code == 403
    api.login(admin)
    r = api.delete(f"/teams/{tid}?permanent=true")
    assert r.status_code == 409 and r.json()["code"] == "protected"
    assert api.post("/teams", {"name": "Alfa"}).status_code == 409  # alive name taken


def test_team_board_in_the_trash_falls_back_to_fixed_iterations(api, admin, project):
    from apps.boards.models import Board

    board = Board.objects.filter(project=project).first()
    api.login(admin)
    assert api.post(f"/projects/{project.key}/boards",
                    {"name": "Otro", "kind": "scrum"}).status_code == 201
    team = _team(api, admin, capacity_points="10")
    plan = _plan(api, admin, project_ids=[project.id],
                 teams=[{"team_id": team["id"], "board_id": board.id}])
    assert api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]["mode"] == "sprints"

    assert api.delete(f"/boards/{board.id}").status_code == 204
    cap = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    assert cap["mode"] == "fixed" and cap["board"] is None and cap["board_deleted"] is True
    meta = api.get(f"/plans/{plan['id']}").json()
    assert meta["teams"][0]["board_id"] is None  # the form cannot resend a deleted board
    start = cap["iterations"][0]["iteration_start"]
    assert api.put(f"/plans/{plan['id']}/capacity", {"team_id": team["id"],
                                                     "iteration_start": start,
                                                     "capacity": 4}).status_code == 200
    # saving the plan as the form has it (board_id null) or resending the old board id
    # does not fail and keeps the link, so restoring brings the sprints back
    for board_id in (None, board.id):
        r = api.patch(f"/plans/{plan['id']}", {"teams": [{"team_id": team["id"],
                                                          "board_id": board_id}]})
        assert r.status_code == 200, r.json()
        assert api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]["mode"] == "fixed"
    # another deleted board is still rejected
    assert api.post(f"/projects/{project.key}/boards",
                    {"name": "Tercero", "kind": "scrum"}).status_code == 201
    third = Board.objects.get(project=project, name="Tercero")
    assert api.delete(f"/boards/{third.id}").status_code == 204
    r = api.patch(f"/plans/{plan['id']}", {"teams": [{"team_id": team["id"],
                                                      "board_id": third.id}]})
    assert r.status_code == 422 and r.json()["code"] == "teams"
    assert api.post(f"/boards/{board.id}/restore").status_code == 200
    cap = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    assert cap["mode"] == "sprints" and cap["board"]["id"] == board.id
    assert cap["board_deleted"] is False


def test_capacity_hides_boards_the_viewer_cannot_browse(api, admin, member, project, secret):
    from apps.boards.models import Board
    from apps.boards.services import create_sprint
    from apps.plans.models import Plan, PlanTeam

    board = Board.objects.filter(project=secret).first()
    create_sprint(admin, board, "Sprint secreto")
    team = _team(api, admin, capacity_points="10")
    plan = _plan(api, admin, project_ids=[project.id, secret.id], access="public",
                 teams=[{"team_id": team["id"], "board_id": board.id}])
    cap = api.get(f"/plans/{plan['id']}/capacity").json()["teams"][0]
    assert cap["mode"] == "sprints" and cap["board"]["name"] == board.name

    api.login(member)  # can open the plan, cannot browse SEC
    r = api.get(f"/plans/{plan['id']}/capacity")
    cap = r.json()["teams"][0]
    assert cap["mode"] == "fixed" and cap["board"] is None and cap["board_deleted"] is False
    assert "Sprint secreto" not in r.content.decode() and board.name not in r.content.decode()
    assert api.get(f"/plans/{plan['id']}").json()["teams"][0]["board_id"] is None

    # an editor who cannot see the board keeps the link when saving the plan as shown
    Plan.objects.filter(pk=plan["id"]).update(owner=member)
    r = api.patch(f"/plans/{plan['id']}", {"teams": [{"team_id": team["id"], "board_id": None}]})
    assert r.status_code == 200, r.json()
    assert PlanTeam.objects.get(plan_id=plan["id"]).board_id == board.id
    sprint = board.sprints.first()
    r = api.put(f"/plans/{plan['id']}/capacity", {"team_id": team["id"],
                                                  "sprint_id": sprint.id, "capacity": 3})
    assert r.status_code == 422 and r.json()["code"] == "sprint_id"
