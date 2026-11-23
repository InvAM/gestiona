import pytest

from apps.issues import services
from apps.search.jql import JQLError, search_issues
from apps.workflows.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def data(make_issue, admin, member):
    a = make_issue("Login roto", "Error", assignee_id=member.id, labels=["backend"],
                   story_points=3)
    b = make_issue("Pantalla nueva", "Historia", labels=["frontend"], story_points=8)
    c = make_issue("Documentar", "Tarea")
    services.transition_issue(admin, c, to_status_id=Status.objects.get(name="Listo").id)
    return a, b, c


def keys(user, jql):
    return sorted(i.key for i in search_issues(user, jql))


def test_basic_filters(data, admin, member):
    a, b, c = data
    assert keys(admin, "project = GES") == sorted([a.key, b.key, c.key])
    assert keys(admin, "type = Error") == [a.key]
    assert keys(admin, 'status = "Listo"') == [c.key]
    assert keys(admin, "statusCategory != Done") == sorted([a.key, b.key])
    assert keys(admin, "resolution = Unresolved") == sorted([a.key, b.key])
    assert keys(member, "assignee = currentUser()") == [a.key]
    assert keys(admin, "assignee is empty") == sorted([b.key, c.key])
    assert keys(admin, "labels in (frontend, backend)") == sorted([a.key, b.key])
    assert keys(admin, '"story points" >= 5') == [b.key]
    assert keys(admin, "summary ~ login") == [a.key]
    assert keys(admin, "not (type = Error) and statusCategory = 'To Do'") == [b.key]
    assert keys(admin, "created >= -1d") == sorted([a.key, b.key, c.key])
    assert keys(admin, f"key = {a.key}") == [a.key]
    assert keys(admin, "priority >= Media") == sorted([a.key, b.key, c.key])


def test_order_by(data, admin):
    a, b, c = data
    got = [i.key for i in search_issues(admin, 'project = GES ORDER BY "story points" DESC')]
    assert got == [c.key, b.key, a.key]  # EMPTY is the greatest value (Jira): first in DESC
    got = [i.key for i in search_issues(admin, 'project = GES ORDER BY "story points"')]
    assert got == [a.key, b.key, c.key]


def test_unknown_values_raise(data, admin):
    for q in ["status = Inexistente", "foo = 1", "project = NOPE", "assignee = nadie@x",
              "created > ayer"]:
        with pytest.raises(JQLError):
            list(search_issues(admin, q))


def test_private_projects_not_searchable(data, outsider, project):
    project.access = "private"
    project.save()
    assert keys(outsider, "") == []
