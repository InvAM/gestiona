import pytest

pytestmark = pytest.mark.django_db


def _gid(dash, kind):
    return next(g["id"] for g in dash["gadgets"] if g["kind"] == kind)


def test_create_default_dashboard_and_gadget_data(api, admin, member, make_issue, project):
    from apps.issues.services import transition_issue

    a = make_issue("Mía", assignee_id=member.id, labels=["ux", "web"])
    make_issue("Otra", assignee_id=member.id, labels=["web"])
    make_issue("De nadie")
    done = project.workflow.statuses.filter(category="done").first()
    transition_issue(admin, a, to_status_id=done.id)

    api.login(member)
    r = api.post("/dashboards", {"name": "Mi panel"})
    assert r.status_code == 201, r.content
    dash = r.json()
    assert len(dash["gadgets"]) == 4 and dash["starred"] and dash["can_edit"]

    mine = api.get(f"/dashboards/{dash['id']}/gadgets/{_gid(dash, 'assigned_to_me')}/data")
    assert mine.status_code == 200, mine.content
    assert [i["summary"] for i in mine.json()["issues"]] == ["Otra"]

    pie = api.get(f"/dashboards/{dash['id']}/gadgets/{_gid(dash, 'pie')}/data").json()
    assert pie["total"] == 1 and pie["groups"][0]["category"] == "todo"

    cvr = api.get(f"/dashboards/{dash['id']}/gadgets/"
                  f"{_gid(dash, 'created_vs_resolved')}/data").json()
    assert cvr["created"] == 3 and cvr["resolved"] == 1 and len(cvr["series"]) >= 30

    act = api.get(f"/dashboards/{dash['id']}/gadgets/{_gid(dash, 'activity')}/data").json()
    assert act["items"] and act["items"][0]["issue"]["key"].startswith("GES-")


def test_gadget_kinds_preview(api, admin, member, make_issue, project):
    make_issue("A", assignee_id=member.id, labels=["x"])
    make_issue("B", labels=["x", "y"])
    api.login(admin)
    r = api.post("/dashboard-gadgets/preview", {"kind": "stats",
                                                "config": {"jql": "project = GES",
                                                           "group_by": "labels"}})
    groups = {g["label"]: g["count"] for g in r.json()["groups"]}
    assert groups == {"x": 2, "y": 1}
    r = api.post("/dashboard-gadgets/preview", {"kind": "two_d",
                                                "config": {"jql": "project = GES",
                                                           "x": "status", "y": "assignee"}})
    body = r.json()
    assert body["total"] == 2 and sum(sum(row) for row in body["cells"]) == 2
    r = api.post("/dashboard-gadgets/preview", {"kind": "filter_results",
                                                "config": {"jql": "project = GES ORDER BY key",
                                                           "limit": 1}})
    assert r.json()["total"] == 2 and len(r.json()["issues"]) == 1
    r = api.post("/dashboard-gadgets/preview", {"kind": "pie", "config": {"jql": "bad = = ="}})
    assert r.status_code in (400, 422)


def test_shared_dashboard_is_scoped_to_viewer(api, admin, member, make_issue):
    from apps.projects.services import create_project

    secret = create_project(admin, name="Secreto", key="SEC", access="private")
    make_issue("Confidencial", project=secret)
    make_issue("Pública")
    api.login(admin)
    dash = api.post("/dashboards", {"name": "Equipo", "visibility": "public",
                                    "template": "blank"}).json()
    g = api.post(f"/dashboards/{dash['id']}/gadgets",
                 {"kind": "filter_results", "title": "Todo", "config": {"jql": ""}}).json()
    assert api.get(f"/dashboards/{dash['id']}/gadgets/{g['id']}/data").json()["total"] == 2

    api.login(member)
    assert dash["id"] in [d["id"] for d in api.get("/dashboards").json()]
    data = api.get(f"/dashboards/{dash['id']}/gadgets/{g['id']}/data").json()
    assert data["total"] == 1 and data["issues"][0]["summary"] == "Pública"
    # member can view but not edit; can copy
    assert api.patch(f"/dashboards/{dash['id']}", {"name": "X"}).status_code == 403
    assert api.post(f"/dashboards/{dash['id']}/gadgets", {"kind": "text"}).status_code == 403
    copy = api.post(f"/dashboards/{dash['id']}/copy")
    assert copy.status_code == 201 and copy.json()["can_edit"]


def test_private_dashboard_hidden(api, admin, member):
    api.login(admin)
    d = api.post("/dashboards", {"name": "Privado", "template": "blank"}).json()
    api.login(member)
    assert api.get(f"/dashboards/{d['id']}").status_code == 404
    assert d["id"] not in [x["id"] for x in api.get("/dashboards").json()]


def test_layout_and_columns(api, admin):
    api.login(admin)
    d = api.post("/dashboards", {"name": "Layout", "columns": 3, "template": "blank"}).json()
    g1 = api.post(f"/dashboards/{d['id']}/gadgets", {"kind": "text", "column": 2,
                                                     "config": {"text": "hola"}}).json()
    g2 = api.post(f"/dashboards/{d['id']}/gadgets", {"kind": "text", "column": 2}).json()
    assert (g1["position"], g2["position"]) == (0, 1)
    r = api.put(f"/dashboards/{d['id']}/layout", {"gadgets": [
        {"id": g2["id"], "column": 0, "position": 0}, {"id": g1["id"], "column": 2,
                                                       "position": 0}]})
    cols = {g["id"]: g["column"] for g in r.json()["gadgets"]}
    assert cols == {g1["id"]: 2, g2["id"]: 0}
    r = api.patch(f"/dashboards/{d['id']}", {"columns": 1})
    assert {g["column"] for g in r.json()["gadgets"]} == {0}


def test_saved_filter_gadget_respects_filter_visibility(api, admin, member, make_issue):
    from apps.search.models import SavedFilter

    make_issue("F")
    private = SavedFilter.objects.create(name="Mío", jql="project = GES", owner=admin)
    api.login(member)
    r = api.post("/dashboard-gadgets/preview", {"kind": "filter_results",
                                                "config": {"filter_id": private.id}})
    assert r.status_code == 422
    api.login(admin)
    r = api.post("/dashboard-gadgets/preview", {"kind": "filter_results",
                                                "config": {"filter_id": private.id}})
    assert r.json()["total"] == 1
