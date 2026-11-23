"""Boards go to the papelera: soft delete, restore, purge (409), visibility and permissions."""

import pytest

from apps.boards import services
from apps.boards.models import Board, BoardColumn, QuickFilter, Sprint

pytestmark = pytest.mark.django_db


@pytest.fixture
def project_admin(make_user, project):
    """Administers the project but is not a system administrator."""
    from apps.projects.models import Role
    from apps.projects.services import set_member

    u = make_user(email="padmin@test.local", full_name="Admin Proyecto")
    set_member(project.lead, project, u.id, Role.objects.admin_role().id)
    return u


@pytest.fixture
def boards(api, admin, project):
    """The default scrum board plus a second one, both with config."""
    api.login(admin)
    main = project.boards.get()
    r = api.post("/projects/GES/boards", {"name": "Equipo B", "kind": "scrum"})
    assert r.status_code == 201, r.content
    second = Board.objects.get(pk=r.json()["id"])
    QuickFilter.objects.create(board=second, name="Mías", jql="assignee = currentUser()")
    return main, second


def _ids(rows):
    return [r["id"] for r in rows]


# ------------------------------------------------------------------ soft delete + restore

def test_soft_delete_keeps_columns_filters_and_sprints_and_restore_brings_them_back(
        api, admin, project, boards, make_issue):
    main, b = boards
    sprint = services.create_sprint(admin, b, name="Sprint B1")
    issue = make_issue("Planificada en B")
    services.move_issues_to_sprint(admin, b, [issue.id], sprint)
    cols = list(b.columns.values_list("id", "name"))
    assert cols

    assert api.delete(f"/boards/{b.id}").status_code == 204
    b_db = Board.all_objects.get(pk=b.id)
    assert b_db.is_deleted
    # nothing is orphaned or lost
    assert list(BoardColumn.objects.filter(board=b).values_list("id", "name")) == cols
    assert QuickFilter.all_objects.filter(board=b).count() == 1
    assert Sprint.objects.filter(board=b).count() == 1
    issue.refresh_from_db()
    assert issue.sprint_id == sprint.id  # issues of its sprints are untouched

    # gone from every view
    assert api.get(f"/boards/{b.id}").status_code == 404
    assert api.get(f"/boards/{b.id}/data").status_code == 404
    assert api.get(f"/boards/{b.id}/backlog").status_code == 404
    assert api.get(f"/sprints/{sprint.id}/report").status_code == 404
    assert api.delete(f"/boards/{b.id}").status_code == 404  # already in the papelera

    r = api.post(f"/boards/{b.id}/restore")
    assert r.status_code == 200, r.content
    out = r.json()
    assert out["deleted_at"] is None
    assert [c["name"] for c in out["columns"]] == [n for _, n in cols]
    assert [q["name"] for q in out["quick_filters"]] == ["Mías"]
    assert b.id in _ids(api.get("/projects/GES/boards").json())
    assert api.get(f"/boards/{b.id}/backlog").json()["sprints"][0]["issues"][0]["id"] == issue.id
    # restoring something that is not in the papelera → 404
    assert api.post(f"/boards/{b.id}/restore").status_code == 404


def test_restore_maps_statuses_added_while_deleted(api, admin, boards):
    _main, b = boards
    first = b.columns.first()
    status_id = first.statuses.first().id
    first.statuses.clear()  # e.g. the workflow changed while the board was deleted
    assert api.delete(f"/boards/{b.id}").status_code == 204
    out = api.post(f"/boards/{b.id}/restore").json()
    assert any(status_id in c["status_ids"] for c in out["columns"])


# ------------------------------------------------------------------ papelera listing

def test_papelera_lists_only_deleted_boards(api, admin, member, project_admin, boards):
    main, b = boards
    api.delete(f"/boards/{b.id}")
    assert _ids(api.get("/projects/GES/boards").json()) == [main.id]
    trash = api.get("/projects/GES/boards?deleted=true").json()
    assert _ids(trash) == [b.id] and trash[0]["deleted_at"]
    assert [q["name"] for q in trash[0]["quick_filters"]] == ["Mías"]

    api.login(project_admin)
    assert _ids(api.get("/projects/GES/boards?deleted=true").json()) == [b.id]
    api.login(member)
    assert api.get("/projects/GES/boards?deleted=true").status_code == 403


# ------------------------------------------------------------------ hidden everywhere

def test_deleted_board_is_hidden_from_meta_lists_and_quick_filters(api, admin, boards):
    main, b = boards
    api.delete(f"/boards/{b.id}")
    meta = api.get("/projects/GES/meta").json()
    assert _ids(meta["boards"]) == [main.id]
    # its quick filters no longer reach the list view
    quick = api.get("/projects/GES/list/meta").json()["quick_filters"]
    assert not any(q["label"] == "Mías" for q in quick)
    # recent items skip it
    from apps.search.models import RecentItem

    RecentItem.objects.create(user=admin, kind="board", object_id=b.id)
    assert not any(r["kind"] == "board" and r["id"] == b.id
                   for r in api.get("/recent").json())


def test_sprints_of_a_deleted_board_are_frozen(api, admin, project, boards, make_issue):
    main, b = boards
    frozen = services.create_sprint(admin, b, name="Congelado")
    target = services.create_sprint(admin, main, name="Principal 1")
    planned = make_issue("En sprint futuro de B")
    services.move_issues_to_sprint(admin, b, [planned.id], frozen)
    api.delete(f"/boards/{b.id}")

    # no edits/starts on the frozen sprint
    assert api.patch(f"/sprints/{frozen.id}", {"name": "x"}).status_code == 404
    assert api.post(f"/sprints/{frozen.id}/start", {}).status_code == 404
    # its issues are not lost: they show up in the backlog of the other board…
    backlog = api.get(f"/boards/{main.id}/backlog").json()
    assert planned.id in _ids(backlog["backlog"])
    # …and new issues cannot be put into it
    r = api.patch(f"/issues/{planned.key}", {"sprint": frozen.id})
    assert r.status_code == 422 and r.json()["code"] == "sprint"
    # dragging it into a sprint of an active board works
    r = api.post(f"/boards/{main.id}/move", {"issue_ids": [planned.id], "sprint_id": target.id})
    assert r.status_code == 204
    planned.refresh_from_db()
    assert planned.sprint_id == target.id


# ------------------------------------------------------------------ guards

def test_board_with_active_sprint_cannot_be_deleted(api, admin, boards, make_issue):
    _main, b = boards
    sprint = services.create_sprint(admin, b, name="En curso")
    issue = make_issue("Activa")
    services.move_issues_to_sprint(admin, b, [issue.id], sprint)
    services.start_sprint(admin, sprint)

    r = api.delete(f"/boards/{b.id}")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "active_sprint" and "Completa el sprint activo" in body["message"]
    assert api.delete(f"/boards/{b.id}?permanent=true").json()["code"] == "active_sprint"
    assert not Board.all_objects.get(pk=b.id).is_deleted

    services.complete_sprint(admin, Sprint.objects.get(pk=sprint.id))
    assert api.delete(f"/boards/{b.id}").status_code == 204


def test_last_board_of_a_scrum_project_can_be_deleted(api, admin, project, boards):
    """Like Jira: no «last board» rule, the project simply ends up without boards."""
    main, b = boards
    assert api.delete(f"/boards/{b.id}").status_code == 204
    assert api.delete(f"/boards/{main.id}").status_code == 204
    assert api.get("/projects/GES/boards").json() == []
    assert api.post(f"/boards/{main.id}/restore").status_code == 200
    assert [x["id"] for x in api.get("/projects/GES/meta").json()["boards"]] == [main.id]


def test_last_board_can_be_purged(api, admin, project):
    api.login(admin)
    board = project.boards.get()
    assert api.delete(f"/boards/{board.id}?permanent=true").status_code == 204
    assert not Board.all_objects.filter(project=project).exists()


def test_business_project_may_delete_its_only_board(api, admin):
    from apps.projects.services import create_project

    p = create_project(admin, name="Operaciones", key="OPS", template="business")
    api.login(admin)
    board = p.boards.get()
    assert api.delete(f"/boards/{board.id}").status_code == 204
    assert api.get("/projects/OPS/meta").json()["boards"] == []


def test_scrum_project_without_boards_keeps_working(api, admin, member, project, types,
                                                    make_issue):
    """Meta, search, list view, create/edit issues and flow reports with no board at all."""
    api.login(admin)
    existing = make_issue("Antes de borrar")
    board = project.boards.get()
    assert api.delete(f"/boards/{board.id}").status_code == 204

    for user in (admin, member):
        api.login(user)
        meta = api.get("/projects/GES/meta").json()
        assert meta["boards"] == [] and meta["issue_types"] and meta["statuses"]
        r = api.post("/issues", {"project": "GES", "issue_type_id": types["Tarea"].id,
                                 "summary": f"Creada por {user.full_name}"})
        assert r.status_code == 201, r.content
        assert r.json()["sprint"] is None

    api.login(admin)
    r = api.post("/search", {"jql": "project = GES ORDER BY created ASC"})
    assert r.status_code == 200, r.content
    keys = [row["key"] for row in r.json()["issues"]]
    assert keys[0] == existing.key and len(keys) == 3
    assert api.get("/projects/GES/list/meta").status_code == 200
    r = api.patch(f"/issues/{existing.key}", {"summary": "Editada sin tablero"})
    assert r.status_code == 200, r.content
    assert api.get(f"/issues/{existing.key}").json()["summary"] == "Editada sin tablero"
    # a new board can be created again from scratch
    r = api.post("/projects/GES/boards", {"name": "Nuevo", "kind": "scrum"})
    assert r.status_code == 201 and r.json()["columns"]


# ------------------------------------------------------------------ permanent delete

def test_permanent_delete_is_409_while_sprints_hold_issues(api, admin, boards, make_issue):
    _main, b = boards
    sprint = services.create_sprint(admin, b, name="Con trabajo")
    issue = make_issue("Dentro")
    services.move_issues_to_sprint(admin, b, [issue.id], sprint)
    api.delete(f"/boards/{b.id}")

    r = api.delete(f"/boards/{b.id}?permanent=true")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "protected"
    assert body["message"] == "No se puede borrar: lo usa 1 sprint con incidencias"
    assert body["details"]["usages"] == [{"count": 1, "label": "sprint con incidencias"}]
    assert Board.all_objects.filter(pk=b.id).exists()


def test_permanent_delete_counts_closed_sprint_history(api, admin, boards, make_issue):
    from apps.workflows.models import Status

    _main, b = boards
    sprint = services.create_sprint(admin, b)
    issue = make_issue("Hecha")
    services.move_issues_to_sprint(admin, b, [issue.id], sprint)
    services.start_sprint(admin, sprint)
    from apps.issues import services as issue_services

    issue_services.transition_issue(admin, issue, to_status_id=Status.objects.get(name="Listo").id)
    services.complete_sprint(admin, Sprint.objects.get(pk=sprint.id))
    # even if the issue later leaves the sprint, the closed-sprint history protects it
    from apps.issues.models import Issue

    Issue.objects.filter(pk=issue.pk).update(sprint=None)
    api.delete(f"/boards/{b.id}")
    assert api.delete(f"/boards/{b.id}?permanent=true").json()["code"] == "protected"


def test_permanent_delete_purges_board_with_empty_sprints(api, admin, project, boards):
    from apps.plans.models import Plan, PlanTeam, Team

    _main, b = boards
    empty = services.create_sprint(admin, b, name="Vacío")
    team = Team.objects.create(name="Equipo", created_by=admin)
    plan = Plan.objects.create(name="Plan", owner=admin)
    pt = PlanTeam.objects.create(plan=plan, team=team, board=b)
    col_ids = list(b.columns.values_list("id", flat=True))

    assert api.delete(f"/boards/{b.id}?permanent=true").status_code == 204  # active board too
    assert not Board.all_objects.filter(pk=b.id).exists()
    assert not Sprint.objects.filter(pk=empty.id).exists()
    assert not BoardColumn.objects.filter(id__in=col_ids).exists()
    assert not QuickFilter.all_objects.filter(board_id=b.id).exists()
    pt.refresh_from_db()
    assert pt.board_id is None  # the plan falls back to fixed iterations


# ------------------------------------------------------------------ permissions

def test_permissions(api, admin, member, project_admin, boards):
    _main, b = boards
    api.login(member)
    assert api.delete(f"/boards/{b.id}").status_code == 403
    assert api.delete(f"/boards/{b.id}?permanent=true").status_code == 403

    api.login(project_admin)  # same permission as before: administer the project
    assert api.delete(f"/boards/{b.id}").status_code == 204
    api.login(member)
    assert api.post(f"/boards/{b.id}/restore").status_code == 403
    api.login(project_admin)
    assert api.delete(f"/boards/{b.id}?permanent=true").status_code == 403  # system admin only
    assert api.post(f"/boards/{b.id}/restore").status_code == 200


def test_outsider_cannot_see_the_papelera(api, outsider, project, boards):
    from apps.projects.models import Project

    _main, b = boards
    assert api.delete(f"/boards/{b.id}").status_code == 204
    Project.objects.filter(pk=project.pk).update(access=Project.Access.PRIVATE)
    api.login(outsider)
    assert api.get("/projects/GES/boards?deleted=true").status_code == 404
    assert api.post(f"/boards/{b.id}/restore").status_code == 404


def test_create_board_validates_kind(api, admin, project):
    api.login(admin)
    r = api.post("/projects/GES/boards", {"name": "X", "kind": "otro"})
    assert r.status_code == 422
