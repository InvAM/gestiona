import pytest

pytestmark = pytest.mark.django_db


def test_archive_hides_and_locks_issue(api, admin, member, make_issue, project):
    story = make_issue("Historia", type_name="Historia")
    sub = make_issue("Sub", type_name="Subtarea", parent_id=story.id)
    other = make_issue("Otra")
    api.login(member)
    assert api.post(f"/issues/{story.key}/archive").status_code == 403  # needs project admin
    api.login(admin)
    assert api.post(f"/issues/{sub.key}/archive").status_code == 422  # archive parent instead
    r = api.post(f"/issues/{story.key}/archive")
    assert r.status_code == 200 and r.json()["is_archived"]
    sub.refresh_from_db()
    assert sub.is_archived

    # hidden from search, pickers and the backlog; still reachable by key
    keys = [i["key"] for i in api.post("/search", {"jql": "project = GES"}).json()["issues"]]
    assert keys == [other.key]
    assert story.key not in [i["key"] for i in api.get("/issues/picker?q=Historia").json()]
    assert api.get(f"/issues/{story.key}").json()["is_archived"]
    archived = [i["key"] for i in api.get("/projects/GES/archived-issues").json()]
    assert set(archived) == {story.key, sub.key}

    # read-only
    assert api.patch(f"/issues/{story.key}", {"summary": "x"}).status_code == 422
    assert api.post(f"/issues/{story.key}/comments", {"body": "hola"}).status_code == 422

    assert api.post(f"/issues/{sub.key}/restore").status_code == 422  # parent first
    r = api.post(f"/issues/{story.key}/restore")
    assert r.status_code == 200 and not r.json()["is_archived"]
    sub.refresh_from_db()
    assert not sub.is_archived
    assert api.patch(f"/issues/{story.key}", {"summary": "Editable"}).status_code == 200


def test_bulk_archive(api, admin, make_issue):
    a = make_issue("A", type_name="Historia")
    s = make_issue("S", type_name="Subtarea", parent_id=a.id)
    b = make_issue("B")
    api.login(admin)
    r = api.post("/issues/bulk", {"issue_ids": [s.id, a.id, b.id], "archive": True})
    assert r.json()["failed"] == [], r.content
    from apps.issues.models import Issue

    assert Issue.objects.filter(is_archived=True).count() == 3


def test_archived_issue_exposes_read_only_permissions(api, admin, make_issue):
    issue = make_issue("RO")
    api.login(admin)
    perms = api.post(f"/issues/{issue.key}/archive").json()["permissions"]
    assert set(perms) == {"browse", "administer", "delete_issues"}
