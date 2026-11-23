"""Vista del plan por usuario (agrupación, filtros, escala y contraídos): permisos,
validación y ciclo de vida con el borrado del plan."""

import pytest

pytestmark = pytest.mark.django_db

VIEW = {
    "group_by": "team", "scale": "weeks",
    "filters": {"project_ids": [3, 3, 4], "team_ids": [0], "status_ids": [],
                "assignee_ids": [], "version_ids": []},
    "collapse": {"team": {"mode": "expanded", "exceptions": ["g:t0", "t3:120", "t3:120"]},
                 "none": {"mode": "collapsed", "exceptions": ["all:7"]}},
}


def _plan(api, user, **body):
    api.login(user)
    r = api.post("/plans", {"name": "Hoja de ruta", **body})
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def test_each_viewer_keeps_their_own_view(api, admin, member, outsider, project):
    pid = _plan(api, admin, project_ids=[project.id], access="shared",
                shared_with_ids=[member.id])
    assert api.get(f"/plans/{pid}/view").json() == {"view": None, "updated_at": None}

    r = api.put(f"/plans/{pid}/view", VIEW)
    assert r.status_code == 200, r.json()
    view = r.json()["view"]
    assert view["filters"]["project_ids"] == [3, 4]  # deduplicated
    assert view["collapse"]["team"]["exceptions"] == ["g:t0", "t3:120"]
    assert api.get(f"/plans/{pid}/view").json()["view"] == view

    api.login(member)  # can see the plan (shared): own, separate view
    assert api.get(f"/plans/{pid}/view").json()["view"] is None
    assert api.put(f"/plans/{pid}/view", {"scale": "quarters"}).status_code == 200
    assert api.get(f"/plans/{pid}/view").json()["view"]["scale"] == "quarters"
    assert api.delete(f"/plans/{pid}/view").status_code == 204
    assert api.get(f"/plans/{pid}/view").json()["view"] is None

    api.login(outsider)  # cannot see the plan
    assert api.get(f"/plans/{pid}/view").status_code == 404
    assert api.put(f"/plans/{pid}/view", VIEW).status_code == 404
    assert api.delete(f"/plans/{pid}/view").status_code == 404

    api.login(admin)
    assert api.get(f"/plans/{pid}/view").json()["view"]["group_by"] == "team"


@pytest.mark.parametrize("patch, code", [
    ({"group_by": "epic"}, "group_by"),
    ({"scale": "days"}, "scale"),
    ({"filters": {"team_ids": [-1]}}, "filters"),
    ({"filters": {"status_ids": list(range(201))}}, "filters"),
    ({"collapse": {"sprint": {"mode": "expanded"}}}, "collapse"),
    ({"collapse": {"none": {"mode": "folded"}}}, "collapse"),
    ({"collapse": {"none": {"exceptions": [f"all:{n}" for n in range(2001)]}}}, "collapse"),
])
def test_view_input_is_validated(api, admin, project, patch, code):
    pid = _plan(api, admin, project_ids=[project.id])
    r = api.put(f"/plans/{pid}/view", {**VIEW, **patch})
    assert r.status_code == 422 and r.json()["code"] == code


def test_unknown_node_keys_are_dropped(api, admin, project):
    pid = _plan(api, admin, project_ids=[project.id])
    keys = ["g:all", "all:12", "x:1", "g:p", "<script>", "p3:9" * 3, "v0:44"]
    r = api.put(f"/plans/{pid}/view", {"collapse": {"version": {"exceptions": keys}}})
    assert r.json()["view"]["collapse"]["version"]["exceptions"] == ["g:all", "all:12", "v0:44"]
    exactly = [f"all:{n}" for n in range(2000)]
    r = api.put(f"/plans/{pid}/view", {"collapse": {"none": {"exceptions": exactly}}})
    assert r.status_code == 200 and len(r.json()["view"]["collapse"]["none"]["exceptions"]) == 2000


def test_soft_delete_keeps_the_view_and_permanent_delete_removes_it(api, admin, project):
    from apps.plans.models import PlanView

    pid = _plan(api, admin, project_ids=[project.id])
    api.put(f"/plans/{pid}/view", VIEW)
    assert api.delete(f"/plans/{pid}").status_code == 204  # to the trash
    assert api.get(f"/plans/{pid}/view").status_code == 404
    assert PlanView.objects.filter(plan_id=pid).count() == 1
    assert api.post(f"/plans/{pid}/restore").status_code == 200
    assert api.get(f"/plans/{pid}/view").json()["view"]["scale"] == "weeks"

    assert api.delete(f"/plans/{pid}?permanent=true").status_code == 204
    assert not PlanView.objects.filter(plan_id=pid).exists()
