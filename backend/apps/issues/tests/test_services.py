from decimal import Decimal

import pytest

from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.issues import services
from apps.issues.models import Issue, IssueLinkType
from apps.workflows.models import Status

pytestmark = pytest.mark.django_db


def test_create_assigns_keys_and_defaults(make_issue, project, admin):
    a = make_issue("Primera")
    b = make_issue("Segunda")
    assert (a.key, b.key) == ("GES-1", "GES-2")
    assert a.status.name == "Por hacer"
    assert a.priority.name == "Media"
    assert a.reporter == admin
    assert a.rank < b.rank
    assert admin in a.watchers.all()
    assert a.history.first().items == [{"field": "created"}]


def test_summary_required(make_issue):
    with pytest.raises(ValidationFailed):
        make_issue("   ")


def test_outsider_cannot_see_private_project(make_issue, project, outsider):
    project.access = "private"
    project.save()
    issue = make_issue()
    with pytest.raises(NotFound):
        services.get_issue_or_404(outsider, issue.key)


def test_limited_project_outsider_can_browse_not_edit(make_issue, outsider):
    issue = make_issue()
    assert services.get_issue_or_404(outsider, issue.key) == issue
    with pytest.raises(Forbidden):
        services.update_issue(outsider, issue, {"summary": "hack"})


def test_update_records_history(make_issue, admin, member):
    issue = make_issue()
    services.update_issue(admin, issue, {"summary": "Nuevo", "assignee": member.id,
                                         "story_points": 5, "labels": ["a b", "a b", "x"]})
    issue.refresh_from_db()
    assert issue.summary == "Nuevo"
    assert issue.assignee == member
    assert issue.story_points == Decimal("5")
    assert issue.labels == ["a_b", "x"]
    fields = {i["field"] for i in issue.history.first().items}
    assert {"summary", "assignee", "story_points", "labels"} <= fields
    assert member in issue.watchers.all()


def test_assignee_must_be_assignable(make_issue, admin, outsider):
    issue = make_issue()
    with pytest.raises(ValidationFailed):
        services.update_issue(admin, issue, {"assignee": outsider.id})


def test_subtask_requires_standard_parent(make_issue, types):
    with pytest.raises(ValidationFailed):
        make_issue("sub sin padre", "Subtarea")
    epic = make_issue("Épica", "Épica")
    with pytest.raises(ValidationFailed):
        make_issue("sub de épica", "Subtarea", parent_id=epic.id)
    story = make_issue("Historia", "Historia", parent_id=epic.id)
    sub = make_issue("sub", "Subtarea", parent_id=story.id)
    assert sub.parent == story and story.parent == epic


def test_transition_sets_and_clears_resolution(make_issue, admin):
    issue = make_issue()
    done = Status.objects.get(name="Listo")
    todo = Status.objects.get(name="Por hacer")
    names = {t.to_status.name for t in services.available_transitions(admin, issue)}
    assert names == {"En curso", "En revisión", "Listo"}
    services.transition_issue(admin, issue, to_status_id=done.id)
    issue.refresh_from_db()
    assert issue.resolution.name == "Hecho" and issue.resolved_at is not None
    services.transition_issue(admin, issue, to_status_id=todo.id)
    issue.refresh_from_db()
    assert issue.resolution is None and issue.resolved_at is None


def test_invalid_transition(make_issue, admin):
    issue = make_issue()
    with pytest.raises(ValidationFailed):
        services.transition_issue(admin, issue, to_status_id=issue.status_id)


def test_rank_between(make_issue, admin):
    a, b, c = make_issue("a"), make_issue("b"), make_issue("c")
    services.rank_issues(admin, [c], before=a)
    order = list(Issue.objects.order_by("rank").values_list("summary", flat=True))
    assert order == ["c", "a", "b"]
    services.rank_issues(admin, [c], after=b)
    order = list(Issue.objects.order_by("rank").values_list("summary", flat=True))
    assert order == ["a", "b", "c"]
    services.rank_issues(admin, [a, b], after=c)
    order = list(Issue.objects.order_by("rank").values_list("summary", flat=True))
    assert order == ["c", "a", "b"]


def test_comments_and_mentions_notify(make_issue, admin, member):
    from apps.notifications.models import Notification

    issue = make_issue()
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "hola "},
        {"type": "mention", "attrs": {"id": str(member.id), "label": "Miembro"}},
    ]}]}
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        c = services.add_comment(admin, issue, doc)
    assert c.body_text == "hola @Miembro"
    assert Notification.objects.filter(recipient=member, event="mentioned").exists()
    assert not Notification.objects.filter(recipient=admin).exists()


def test_member_cannot_edit_others_comment(make_issue, admin, member):
    issue = make_issue()
    c = services.add_comment(admin, issue, "texto")
    with pytest.raises(Forbidden):
        services.edit_comment(member, c, "otro")


def test_links_and_clone(make_issue, admin):
    a, b = make_issue("a"), make_issue("b")
    blocks = IssueLinkType.objects.get(name="Bloqueo")
    services.link_issues(admin, a, b, blocks)
    assert a.outward_links.count() == 1
    with pytest.raises(ValidationFailed):
        services.link_issues(admin, a, a, blocks)
    clone = services.clone_issue(admin, a)
    assert clone.summary.startswith("CLONAR")
    assert clone.outward_links.filter(target=a, link_type__name="Clonación").exists()


def test_clone_link_found_by_flag_not_name(make_issue, admin):
    a = make_issue("a")
    clone_type = IssueLinkType.objects.get(is_clone=True)
    clone_type.name = "Copia"
    clone_type.save()
    clone = services.clone_issue(admin, a)
    assert clone.outward_links.filter(target=a, link_type=clone_type).exists()


def test_only_one_clone_link_type(api, admin):
    api.login(admin)
    other = IssueLinkType.objects.get(name="Relación")
    r = api.patch(f"/link-types/{other.id}", {"name": other.name, "outward": other.outward,
                                               "inward": other.inward, "is_clone": True})
    assert r.status_code == 200, r.content
    assert list(IssueLinkType.objects.filter(is_clone=True)) == [other]


def test_worklog_reduces_remaining(make_issue, admin):
    from django.utils import timezone

    issue = make_issue(original_estimate=7200)
    services.log_work(admin, issue, time_spent=3600, started_at=timezone.now())
    issue.refresh_from_db()
    assert issue.time_spent == 3600 and issue.remaining_estimate == 3600


def test_search_vector_finds_text(make_issue, admin):
    from apps.search.jql import search_issues

    make_issue("Error en el login del portal")
    make_issue("Otra cosa")
    assert [i.summary for i in search_issues(admin, 'text ~ "logi"')] == [
        "Error en el login del portal"
    ]


def test_delete_requires_permission(make_issue, member, admin):
    issue = make_issue()
    from apps.projects.models import Role

    viewer = Role.objects.get(name="Observador")
    from apps.projects.services import set_member

    set_member(admin, issue.project, member.id, viewer.id)
    member._gestiona_perm_cache = None
    with pytest.raises(Forbidden):
        services.delete_issue(member, issue)
    services.delete_issue(admin, issue)
    assert not Issue.objects.filter(pk=issue.pk).exists()
