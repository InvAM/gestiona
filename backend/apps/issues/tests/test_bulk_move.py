import pytest
from django.core import mail

pytestmark = pytest.mark.django_db


@pytest.fixture
def other(admin, member):
    from apps.projects.models import Role
    from apps.projects.services import create_project, set_member

    p = create_project(admin, name="Otro equipo", key="OTR", template="kanban")
    set_member(admin, p, member.id, Role.objects.get(name="Miembro").id)
    return p


def test_bulk_edit_labels_assignee_and_transition(api, admin, member, make_issue, project):
    a = make_issue("A", labels=["x", "viejo"])
    b = make_issue("B", labels=["viejo"])
    done = project.workflow.statuses.get(category="done")
    api.login(admin)
    r = api.post("/issues/bulk", {
        "issue_ids": [a.id, b.id], "changes": {"assignee": member.id},
        "add_labels": ["nuevo"], "remove_labels": ["viejo"],
        "transition_to_status_id": done.id, "watch": True,
    })
    assert r.status_code == 200, r.content
    assert sorted(r.json()["updated"]) == ["GES-1", "GES-2"] and r.json()["failed"] == []
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.labels == ["x", "nuevo"] and b.labels == ["nuevo"]
    assert a.assignee == member and a.status == done and a.resolution is not None
    assert a.watchers.filter(pk=admin.pk).exists()


def test_bulk_reports_per_issue_failures(api, member, make_issue, admin):
    from apps.projects.services import create_project

    mine = make_issue("Mía")
    private = create_project(admin, name="Privado", key="PRV", access="private")
    hidden = make_issue("Oculta", project=private)
    api.login(member)
    r = api.post("/issues/bulk", {"issue_ids": [mine.id, hidden.id], "delete": True})
    body = r.json()
    # member can't delete in GES and can't even see PRV
    assert body["updated"] == []
    assert {f["key"] for f in body["failed"]} == {"GES-1", "PRV-1"}


def test_bulk_can_mute_notifications(api, admin, member, make_issue,
                                     django_capture_on_commit_callbacks):
    from apps.notifications.models import Notification

    issue = make_issue("Silenciosa")
    api.login(admin)
    with django_capture_on_commit_callbacks(execute=True):
        api.post("/issues/bulk", {"issue_ids": [issue.id], "changes": {"assignee": member.id},
                                  "notify": False})
    assert not Notification.objects.filter(recipient=member).exists()
    assert len(mail.outbox) == 0
    with django_capture_on_commit_callbacks(execute=True):
        api.post("/issues/bulk", {"issue_ids": [issue.id], "changes": {"priority": 1}})
    assert Notification.objects.filter(recipient=member).exists()


def test_move_issue_with_subtasks_keeps_old_key(api, admin, make_issue, project, other, types):
    from apps.projects.services import save_component

    save_component(admin, project, None, name="API")
    save_component(admin, other, None, name="API")
    epic = make_issue("Épica", type_name="Épica")
    story = make_issue("Historia", type_name="Historia", parent_id=epic.id, labels=["l"],
                       component_ids=list(project.components.values_list("id", flat=True)))
    sub = make_issue("Sub", type_name="Subtarea", parent_id=story.id)
    api.login(admin)
    r = api.post(f"/issues/{story.key}/move", {"project": "OTR"})
    assert r.status_code == 200, r.content
    moved = r.json()
    assert moved["key"] == "OTR-1"
    story.refresh_from_db()
    sub.refresh_from_db()
    assert story.project == other and story.parent is None  # epic stays in GES
    assert sub.project == other and sub.key == "OTR-2" and sub.parent == story
    assert [c.name for c in story.components.all()] == ["API"]
    assert story.components.get().project == other
    assert story.status in other.workflow.statuses.all()

    # old keys still resolve
    assert api.get("/issues/GES-2").json()["key"] == "OTR-1"
    assert api.get("/issues/GES-3").json()["key"] == "OTR-2"
    fields = [i["field"] for i in api.get("/issues/OTR-1/history").json()[0]["items"]]
    assert fields[:2] == ["project", "key"]


def test_move_rejections(api, admin, member, make_issue, project, other):
    story = make_issue("Historia", type_name="Historia")
    sub = make_issue("Sub", type_name="Subtarea", parent_id=story.id)
    api.login(admin)
    assert api.post(f"/issues/{sub.key}/move", {"project": "OTR"}).status_code == 422
    assert api.post(f"/issues/{story.key}/move", {"project": "GES"}).status_code == 422
    assert api.post(f"/issues/{story.key}/move", {"project": "NOPE"}).status_code == 404
    api.login(member)  # members lack delete_issues in the source project
    assert api.post(f"/issues/{story.key}/move", {"project": "OTR"}).status_code == 403


def test_bulk_move_with_status_map(api, admin, make_issue, project, other):
    a = make_issue("A", type_name="Historia")
    b = make_issue("B", type_name="Historia")
    sub = make_issue("S", type_name="Subtarea", parent_id=a.id)
    target_status = other.workflow.statuses.filter(category="in_progress").last()
    api.login(admin)
    r = api.post("/issues/bulk", {"issue_ids": [sub.id, a.id, b.id], "move": {
        "project": "OTR", "status_map": {str(a.status_id): target_status.id}}})
    body = r.json()
    assert body["failed"] == [], body
    assert sorted(body["updated"]) == ["OTR-1", "OTR-3"]
    a.refresh_from_db()
    assert a.status == target_status
    sub.refresh_from_db()
    assert sub.project == other
