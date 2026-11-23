"""End-to-end API smoke tests through the real URL/auth stack."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


def test_requires_auth(api):
    assert api.get("/me").status_code == 401
    assert api.get("/health").status_code == 200


def test_full_flow(api, admin, member, types):
    api.login(admin)
    r = api.post("/projects", {"name": "Plataforma", "key": "PLAT", "template": "scrum"})
    assert r.status_code == 201, r.content
    meta = api.get("/projects/PLAT/meta").json()
    assert "administer" in meta["permissions"]
    board_id = meta["boards"][0]["id"]
    story = next(t for t in meta["issue_types"] if t["name"] == "Historia")

    r = api.post("/issues", {"project": "PLAT", "issue_type_id": story["id"],
                             "summary": "Primera historia", "story_points": 3})
    assert r.status_code == 201, r.content
    issue = r.json()
    assert issue["key"] == "PLAT-1"

    r = api.patch("/issues/PLAT-1", {"summary": "Editada", "labels": ["ux"]})
    assert r.status_code == 200 and r.json()["summary"] == "Editada"

    trans = api.get("/issues/PLAT-1/transitions").json()
    to_done = next(t for t in trans if t["to"]["category"] == "done")
    r = api.post("/issues/PLAT-1/transitions", {"transition_id": to_done["id"]})
    assert r.json()["status"]["category"] == "done"

    r = api.post("/issues/PLAT-1/comments", {"body": "Listo!"})
    assert r.status_code == 201
    assert len(api.get("/issues/PLAT-1/comments").json()) == 1

    r = api.post("/search", {"jql": "project = PLAT AND labels = ux"})
    assert r.json()["total"] == 1

    r = api.post(f"/boards/{board_id}/sprints", {})
    assert r.status_code == 201
    backlog = api.get(f"/boards/{board_id}/backlog").json()
    assert len(backlog["sprints"]) == 1
    assert len(api.get("/issues/PLAT-1/history").json()) >= 3

    # attachments: upload, download (permission-checked), delete
    f = SimpleUploadedFile("nota.txt", b"hola", content_type="text/plain")
    r = api.c.post("/api/v1/issues/PLAT-1/attachments", {"files": [f]})
    assert r.status_code == 201, r.content
    att = r.json()[0]
    r = api.c.get(att["url"])
    assert r.status_code == 200 and b"".join(r.streaming_content) == b"hola"
    api.c.force_login(member)
    # member is not in PLAT but project is 'limited' → can browse
    assert api.c.get(att["url"]).status_code == 200
    assert api.delete(f"/attachments/{att['id']}").status_code == 403


def test_jql_error_is_400(api, admin, project):
    api.login(admin)
    r = api.post("/search", {"jql": "status = "})
    assert r.status_code == 400 and r.json()["code"] == "jql_error"


def test_non_admin_cannot_create_project(api, member):
    api.login(member)
    r = api.post("/projects", {"name": "X", "key": "XX"})
    assert r.status_code == 403


def test_private_project_is_404(api, project, outsider):
    project.access = "private"
    project.save()
    api.login(outsider)
    assert api.get("/projects/GES").status_code == 404
    assert all(p["key"] != "GES" for p in api.get("/projects").json())


def test_staff_cannot_modify_superuser(api, admin, make_user):
    root = make_user(email="root@test.local", is_superuser=True, is_staff=True)
    api.login(admin)
    assert api.patch(f"/admin/users/{root.id}", {"is_active": False}).status_code == 403
    regular = make_user()
    r = api.patch(f"/admin/users/{regular.id}", {"full_name": "Nuevo"})
    assert r.status_code == 200 and r.json()["name"] == "Nuevo"


def test_jql_does_not_leak_private_project_names(api, project, outsider):
    project.access = "private"
    project.save()
    api.login(outsider)
    r = api.post("/search", {"jql": "project = GES"})
    assert r.status_code == 400
    assert "no tienes acceso" in r.json()["message"]


def test_switch_project_workflow_requires_status_map(api, admin, make_issue, project):
    from apps.workflows.models import Status, Workflow

    issue = make_issue()
    review = Status.objects.get(name="En revisión")
    from apps.issues import services

    services.transition_issue(admin, issue, to_status_id=review.id)
    api.login(admin)
    target = Workflow.objects.get(name="Flujo de tareas")
    r = api.put("/projects/GES/workflow", {"workflow_id": target.id})
    assert r.status_code == 422 and r.json()["code"] == "status_map_required"
    todo = Status.objects.get(name="Por hacer")
    r = api.put("/projects/GES/workflow", {"workflow_id": target.id,
                                           "status_map": {str(review.id): todo.id}})
    assert r.status_code == 204
    issue.refresh_from_db()
    assert issue.status == todo
    assert [c.name for c in project.boards.get().columns.all()] == ["Por hacer", "En curso",
                                                                   "Listo"]
