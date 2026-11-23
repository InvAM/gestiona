"""Regressions: bulk move of epic + children (bug 1), archive/restore of an epic (bug 2),
ranks on restore (bug 3) and archived issues being read-only everywhere (bug 4)."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.errors import ValidationFailed
from apps.core.ranking import key_between
from apps.issues import services
from apps.issues.models import Issue, IssueLinkType

pytestmark = pytest.mark.django_db


@pytest.fixture
def other(admin, member):
    from apps.projects.models import Role
    from apps.projects.services import create_project, set_member

    p = create_project(admin, name="Otro equipo", key="OTR", template="scrum")
    set_member(admin, p, member.id, Role.objects.get(name="Miembro").id)
    return p


def _reload(*issues):
    return [Issue.objects.select_related("parent", "project").get(pk=i.pk) for i in issues]


# --------------------------------------------------------------------------- bug 1

def test_bulk_move_epic_with_selected_children_keeps_hierarchy(api, admin, make_issue, other):
    epic = make_issue("Épica", type_name="Épica")
    s1 = make_issue("H1", type_name="Historia", parent_id=epic.id)
    s2 = make_issue("H2", type_name="Historia", parent_id=epic.id)
    left = make_issue("Se queda", type_name="Historia", parent_id=epic.id)
    sub = make_issue("Sub", type_name="Subtarea", parent_id=s1.id)
    api.login(admin)
    # children listed before the epic: the order of the selection must not matter
    r = api.post("/issues/bulk", {"issue_ids": [s2.id, s1.id, epic.id],
                                  "move": {"project": "OTR"}})
    body = r.json()
    assert r.status_code == 200 and body["failed"] == [], body
    epic, s1, s2, left, sub = _reload(epic, s1, s2, left, sub)
    assert epic.project == other and epic.key == body["updated"][0]
    assert s1.project == other and s1.parent == epic
    assert s2.project == other and s2.parent == epic
    assert sub.project == other and sub.parent == s1
    assert left.project.key == "GES" and left.parent is None  # not selected: unlinked
    assert "parent" not in [i["field"] for i in s1.history.first().items]


def test_bulk_move_child_that_fails_is_detached_from_moved_epic(admin, make_issue, other,
                                                                types):
    epic = make_issue("Épica", type_name="Épica")
    story = make_issue("H", type_name="Historia", parent_id=epic.id)
    errors = []
    # mapping the story type to an epic type is invalid -> only the story fails
    moved = services.move_issues(
        admin, [story, epic], other, type_map={str(types["Historia"].id): types["Épica"].id},
        on_error=lambda issue, exc: errors.append((issue.key, exc.message)))
    epic, story = _reload(epic, story)
    assert [m.id for m in moved] == [epic.id] and epic.project == other
    assert errors and errors[0][0] == "GES-2"
    assert story.project.key == "GES" and story.parent is None  # no cross-project parent
    assert story.history.first().items[0]["field"] == "parent"


def test_single_move_of_epic_still_unlinks_children(admin, make_issue, other):
    epic = make_issue("Épica", type_name="Épica")
    story = make_issue("H", type_name="Historia", parent_id=epic.id)
    services.move_issue(admin, epic, other)
    (story,) = _reload(story)
    assert story.parent is None and story.project.key == "GES"


# --------------------------------------------------------------------------- bug 2

def test_archiving_an_epic_keeps_children_linked(api, admin, make_issue):
    epic = make_issue("Épica", type_name="Épica")
    story = make_issue("H", type_name="Historia", parent_id=epic.id)
    sibling = make_issue("Otra", type_name="Historia")
    services.archive_issue(admin, epic)
    epic, story = _reload(epic, story)
    assert epic.is_archived and not story.is_archived and story.parent == epic

    # the visible child still works and shows its (archived) epic
    api.login(admin)
    r = api.get(f"/issues/{story.key}")
    assert r.status_code == 200 and r.json()["parent"]["key"] == epic.key
    assert api.patch(f"/issues/{story.key}", {"summary": "Editable"}).status_code == 200
    # ...but nothing new can be attached to an archived epic
    with pytest.raises(ValidationFailed, match="archivada"):
        services.update_issue(admin, sibling, {"parent": epic.id})
    with pytest.raises(ValidationFailed, match="archivada"):
        services.create_issue(admin, epic.project, services.IssueInput(
            issue_type_id=story.issue_type_id, summary="Nueva", parent_id=epic.id))
    # unrelated edits of the child do not trip over its archived parent
    services.update_issue(admin, story, {"issue_type": story.issue_type_id, "labels": ["x"]})

    services.restore_issue(admin, epic)
    epic, story = _reload(epic, story)
    assert not epic.is_archived and story.parent == epic
    assert [c["key"] for c in api.get(f"/issues/{epic.key}").json()["children"]] == [story.key]


def test_story_archived_on_its_own_can_be_restored_under_archived_epic(admin, make_issue):
    epic = make_issue("Épica", type_name="Épica")
    story = make_issue("H", type_name="Historia", parent_id=epic.id)
    services.archive_issue(admin, story)
    services.archive_issue(admin, epic)
    services.restore_issue(admin, story)
    (story,) = _reload(story)
    assert not story.is_archived and story.parent_id == epic.id


# --------------------------------------------------------------------------- bug 3

def test_restore_gives_each_issue_its_own_increasing_rank(admin, make_issue, project):
    story = make_issue("H", type_name="Historia")
    subs = [make_issue(f"S{n}", type_name="Subtarea", parent_id=story.id) for n in range(3)]
    tail = make_issue("Última")
    services.archive_issue(admin, story)
    services.restore_issue(admin, story)
    restored = _reload(story, *subs)
    ranks = [i.rank for i in restored]
    assert len(set(ranks)) == len(ranks) == 4
    assert ranks == sorted(ranks) and ranks[0] > tail.rank  # parent first, then subtasks
    # ranking between two restored issues works (key_between(a, b) needs a < b)
    assert ranks[0] < key_between(ranks[0], ranks[1]) < ranks[1]
    services.rank_issues(admin, [tail], after=restored[0])
    tail.refresh_from_db()
    assert ranks[0] < tail.rank < ranks[1]


# --------------------------------------------------------------------------- bug 4

def test_archived_issue_is_read_only_in_every_service(admin, make_issue, other):
    issue = make_issue("Archivada", type_name="Historia")
    partner = make_issue("Activa")
    comment = services.add_comment(admin, issue, "hola")
    att = services.add_attachment(admin, issue, SimpleUploadedFile("a.txt", b"x", "text/plain"))
    link_type = IssueLinkType.objects.first()
    link = services.link_issues(admin, partner, issue, link_type)
    web = services.add_web_link(admin, issue, "https://example.com")
    worklog = services.log_work(admin, issue, time_spent=60, started_at=timezone.now())
    services.archive_issue(admin, issue)
    (issue,) = _reload(issue)
    comment.refresh_from_db()
    att.refresh_from_db()
    link.refresh_from_db()
    web.refresh_from_db()
    worklog.refresh_from_db()

    blocked = {
        "edit_comment": lambda: services.edit_comment(admin, comment, "cambio"),
        "delete_comment": lambda: services.delete_comment(admin, comment),
        "delete_attachment": lambda: services.delete_attachment(admin, att),
        "link as source": lambda: services.link_issues(admin, issue, partner, link_type),
        "link as target": lambda: services.link_issues(admin, partner, issue, link_type),
        "unlink": lambda: services.unlink(admin, link),
        "add_web_link": lambda: services.add_web_link(admin, issue, "https://x.example"),
        "delete_web_link": lambda: services.delete_web_link(admin, web),
        "log_work": lambda: services.log_work(admin, issue, time_spent=5,
                                              started_at=timezone.now()),
        "delete_worklog": lambda: services.delete_worklog(admin, worklog),
        "vote": lambda: services.set_vote(admin, issue, True),
        "watch": lambda: services.set_watching(admin, issue, True),
        "rank": lambda: services.rank_issues(admin, [issue], after=partner),
        "move": lambda: services.move_issue(admin, issue, other),
        "clone": lambda: services.clone_issue(admin, issue),
        "update": lambda: services.update_issue(admin, issue, {"summary": "x"}),
        "comment": lambda: services.add_comment(admin, issue, "nuevo"),
    }
    for name, call in blocked.items():
        with pytest.raises(ValidationFailed) as e:
            call()
        assert e.value.code == "archived", name

    # nothing changed
    assert issue.comments.count() == 1 and issue.attachments.count() == 1
    assert issue.web_links.count() == 1 and issue.worklogs.count() == 1
    assert issue.project.key == "GES" and Issue.objects.filter(project=other).count() == 0
    # leaving the watch list, restoring and permanent deletion remain possible
    services.set_watching(admin, issue, False)
    assert not issue.watchers.filter(pk=admin.pk).exists()
    services.restore_issue(admin, issue)
    services.delete_issue(admin, Issue.objects.get(pk=issue.pk))
    assert not Issue.objects.filter(pk=issue.pk).exists()


def test_archived_read_only_through_the_api(api, admin, make_issue):
    issue = make_issue("Archivada", type_name="Historia")
    partner = make_issue("Activa")
    api.login(admin)
    web = api.post(f"/issues/{issue.key}/weblinks", {"url": "https://example.com"}).json()
    api.post(f"/issues/{issue.key}/archive")
    assert api.delete(f"/weblinks/{web['id']}").status_code == 422
    assert api.post(f"/issues/{partner.key}/links",
                    {"target": issue.key, "link_type_id": IssueLinkType.objects.first().id}
                    ).status_code == 422
    assert api.post(f"/issues/{issue.key}/votes").status_code == 422
    assert api.post("/issues/rank", {"issue_ids": [issue.id], "after_id": partner.id}
                    ).status_code == 422
    assert api.delete(f"/issues/{issue.key}").status_code == 204
