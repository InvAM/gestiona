import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def form(api, admin, project, types):
    api.login(admin)
    r = api.post("/projects/GES/forms", {
        "name": "Solicitud de soporte", "issue_type_id": types["Tarea"].id,
        "fields": [{"field": "summary", "label": "¿Qué necesitas?"},
                   {"field": "description"}, {"field": "priority", "required": True},
                   {"field": "due_date"}],
        "default_labels": ["formulario"], "success_message": "Te responderemos pronto",
    })
    assert r.status_code == 201, r.content
    return r.json()


def test_member_submits_form(api, member, form):
    from apps.issues.models import Issue

    api.login(member)
    public = api.get(f"/f/{form['slug']}").json()
    assert [f["field"] for f in public["fields"]] == ["summary", "description", "priority",
                                                      "due_date"]
    assert public["fields"][2]["options"]
    r = api.post(f"/f/{form['slug']}", {"values": {"summary": "Necesito acceso a la VPN"}})
    assert r.status_code == 422  # priority required
    prio = public["fields"][2]["options"][0]["id"]
    r = api.post(f"/f/{form['slug']}", {"values": {
        "summary": "Necesito acceso a la VPN", "description": "Desde casa", "priority": prio,
        "due_date": "2026-12-01"}})
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["message"] == "Te responderemos pronto" and body["key"].startswith("GES-")
    issue = Issue.objects.get(key=body["key"])
    assert issue.reporter == member and issue.labels == ["formulario"]
    assert issue.description_text == "Desde casa" and str(issue.due_date) == "2026-12-01"


def test_outsider_can_submit_org_form_to_private_project(api, admin, outsider, project, form):
    from apps.issues.models import Issue

    api.login(admin)
    api.patch("/projects/GES", {"access": "private"})
    api.login(outsider)
    prio = api.get(f"/f/{form['slug']}").json()["fields"][2]["options"][0]["id"]
    r = api.post(f"/f/{form['slug']}", {"values": {"summary": "Pedido externo",
                                                   "priority": prio}})
    assert r.status_code == 201, r.content
    assert r.json()["key"] is None and not r.json()["can_view"]  # no leak of private keys
    issue = Issue.objects.get(summary="Pedido externo")
    assert issue.reporter == outsider and issue.watchers.filter(pk=outsider.pk).exists()


def test_members_only_form_and_unknown_fields(api, admin, outsider, form):
    api.login(admin)
    upd = {**{k: form[k] for k in ("name", "description", "default_labels",
                                   "success_message")},
           "issue_type_id": form["issue_type"]["id"], "fields": form["fields"],
           "access": "members"}
    assert api.put(f"/forms/{form['id']}", upd).status_code == 200
    r = api.post(f"/f/{form['slug']}", {"values": {"summary": "x", "priority": 1,
                                                   "assignee": 1}})
    assert r.status_code == 422
    api.login(outsider)
    assert api.get(f"/f/{form['slug']}").status_code == 403


def test_inactive_form_404_and_admin_only_management(api, admin, member, form):
    api.login(member)
    assert api.get("/projects/GES/forms").status_code == 403
    api.login(admin)
    upd = {"name": form["name"], "issue_type_id": form["issue_type"]["id"],
           "fields": form["fields"], "is_active": False}
    api.put(f"/forms/{form['id']}", upd)
    api.login(member)
    assert api.get(f"/f/{form['slug']}").status_code == 404
