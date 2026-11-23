import pytest

from apps.boards import services
from apps.boards.models import Sprint
from apps.core.errors import ValidationFailed
from apps.issues import services as issue_services
from apps.workflows.models import Status

pytestmark = pytest.mark.django_db


@pytest.fixture
def board(project):
    return project.boards.get()


def test_default_board_columns_follow_workflow(board):
    assert [c.name for c in board.columns.all()] == ["Por hacer", "En curso", "En revisión",
                                                    "Listo"]


def test_sprint_lifecycle(board, make_issue, admin):
    s1 = services.create_sprint(admin, board)
    s2 = services.create_sprint(admin, board)
    a, b = make_issue("a", story_points=3), make_issue("b", story_points=5)
    sub = make_issue("sub", "Subtarea", parent_id=a.id)
    with pytest.raises(ValidationFailed):
        services.start_sprint(admin, s1)  # empty
    services.move_issues_to_sprint(admin, board, [a.id, b.id], s1)
    sub.refresh_from_db()
    assert sub.sprint == s1  # subtasks follow parent
    assert list(services.backlog_issues(board)) == []
    services.start_sprint(admin, s1)
    with pytest.raises(ValidationFailed):
        services.start_sprint(admin, s2)  # one active at a time
    ids = {i.id for i in services.board_issues(board, sprint=s1)}
    assert {a.id, b.id, sub.id} <= ids

    done = Status.objects.get(name="Listo")
    issue_services.transition_issue(admin, a, to_status_id=done.id)
    services.complete_sprint(admin, s1, move_to_sprint_id=s2.id)
    s1.refresh_from_db()
    b.refresh_from_db()
    a.refresh_from_db()
    assert s1.state == Sprint.State.CLOSED
    assert b.sprint == s2 and a.sprint == s1
    assert s1 in b.closed_sprints.all()
    report = services.burndown(s1)
    assert report["initial"] == 8.0
    assert report["timeline"][-1]["remaining"] == 5.0
    assert services.velocity(board)[0] == {"id": s1.id, "name": s1.name, "committed": 8.0,
                                           "completed": 3.0}


def test_scope_change_tracked(board, make_issue, admin):
    s = services.create_sprint(admin, board)
    a = make_issue("a", story_points=2, sprint_id=s.id)
    services.start_sprint(admin, s)
    issue_services.update_issue(admin, a, {"story_points": 4})
    c = make_issue("c", story_points=1, sprint_id=s.id)
    kinds = list(s.scope_changes.values_list("kind", flat=True))
    assert kinds == ["estimate", "added"]
    assert services.burndown(s)["timeline"][-1]["remaining"] == 5.0
    del c


def test_cannot_add_to_closed_sprint(board, make_issue, admin):
    s = services.create_sprint(admin, board)
    a = make_issue("a", sprint_id=s.id)
    services.start_sprint(admin, s)
    services.complete_sprint(admin, s)
    with pytest.raises(ValidationFailed):
        issue_services.update_issue(admin, a, {"sprint": s.id})


def test_archived_issues_cannot_be_moved_into_a_sprint(board, make_issue, admin):
    s1 = services.create_sprint(admin, board)
    live, archived = make_issue("viva"), make_issue("archivada")
    issue_services.archive_issue(admin, archived)
    services.move_issues_to_sprint(admin, board, [live.id, archived.id], s1)
    live.refresh_from_db()
    archived.refresh_from_db()
    assert live.sprint == s1
    assert archived.sprint is None
