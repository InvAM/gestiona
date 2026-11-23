import csv
import io

import pytest

from apps.issues import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def select_field(project):
    from apps.issues.models import CustomField

    cf = CustomField.objects.create(name="Entorno", kind="select", options=[
        {"id": "p", "value": "Producción"}, {"id": "s", "value": "Staging"},
    ])
    cf.projects.add(project)
    return cf


def _csv(resp):
    text = b"".join(resp.streaming_content).decode() if resp.streaming else resp.content.decode()
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def test_meta_lists_columns_groupings_and_quick_filters(api, member, project, select_field):
    from apps.boards.models import Board, QuickFilter

    board = Board.objects.filter(project=project).first()
    QuickFilter.objects.create(board=board, name="Errores", jql="type = Error")
    r = api.login(member).get(f"/projects/{project.key}/list/meta")
    assert r.status_code == 200, r.content
    meta = r.json()
    by_id = {c["id"]: c for c in meta["columns"]}
    assert by_id["summary"]["label"] == "Resumen" and by_id["summary"]["field"] == "summary"
    assert by_id["summary"]["sort"] == "summary" and by_id["summary"]["default"]
    assert by_id["status"]["field"] is None  # changed through workflow transitions
    assert by_id["created"]["field"] is None and by_id["created"]["sort"] == "created"
    cf = by_id[f"cf:{select_field.id}"]
    assert cf["label"] == "Entorno" and cf["custom_kind"] == "select"
    assert cf["sort"] == f"cf[{select_field.id}]"
    assert [g["value"] for g in meta["group_by"]] == [
        "status", "assignee", "epic", "priority", "sprint", "type"]
    quick = {q["id"]: q for q in meta["quick_filters"]}
    assert quick["mine"]["jql"] == "assignee = currentUser()"
    assert any(q["label"] == "Errores" and q["id"].startswith("board:") for q in quick.values())
    assert meta["page_max"] == 500 and meta["bulk_max"] >= 100


def test_quick_filter_jql_is_valid(api, member, project):
    from apps.listview.api import QUICK_FILTERS

    api.login(member)
    for _, _, jql in QUICK_FILTERS:
        r = api.post(f"/projects/{project.key}/list", {"jql": f"project = GES AND {jql}"})
        assert r.status_code == 200, (jql, r.content)


def test_page_rows_order_permissions_and_scope(api, admin, member, outsider, project,
                                               make_issue):
    from apps.projects.services import create_project

    a = make_issue("Alfa", assignee_id=member.id, labels=["web"])
    b = make_issue("Beta")
    other = create_project(admin, name="Otro", key="OTR", template="kanban")
    make_issue("Ajena", project=other)

    api.login(member)
    r = api.post(f"/projects/{project.key}/list",
                 {"jql": "ORDER BY summary DESC", "start": 0, "limit": 1})
    assert r.status_code == 200, r.content
    page = r.json()
    assert page["total"] == 2 and page["limit"] == 1
    assert [x["key"] for x in page["rows"]] == [b.key]
    page = api.post(f"/projects/{project.key}/list",
                    {"jql": "ORDER BY summary DESC", "start": 1, "limit": 1}).json()
    row = page["rows"][0]
    assert row["key"] == a.key and row["assignee"]["id"] == member.id
    assert row["labels"] == ["web"] and row["children_count"] == 0
    assert "edit_issues" in row["permissions"] and not row["is_archived"]
    assert row["group"] is None

    # an invalid JQL is a 400 with the parser message
    bad = api.post(f"/projects/{project.key}/list", {"jql": "estado ="})
    assert bad.status_code == 400 and bad.json()["code"] == "jql_error"
    # limit is capped
    assert api.post(f"/projects/{project.key}/list", {"limit": 10_000}).json()["limit"] == 500

    project.access = "private"
    project.save(update_fields=["access"])
    api.login(outsider)
    assert api.post(f"/projects/{project.key}/list", {}).status_code == 404


def test_grouping_by_status_and_epic(api, admin, member, project, make_issue):
    epic = make_issue("Épica 1", type_name="Épica")
    s1 = make_issue("Hija", type_name="Historia", parent_id=epic.id)
    sub = make_issue("Sub", type_name="Subtarea", parent_id=s1.id)
    loose = make_issue("Suelta")
    in_progress = project.workflow.statuses.filter(category="in_progress").first()
    services.transition_issue(admin, loose, to_status_id=in_progress.id)

    api.login(member)
    g = api.post(f"/projects/{project.key}/list/groups",
                 {"jql": "", "group_by": "status"}).json()
    assert g["total"] == 4
    labels = [x["label"] for x in g["groups"]]
    ordered = [s.name for s in project.workflow.ordered_statuses()]
    assert labels == [n for n in ordered if n in labels]  # workflow order
    assert {x["label"]: x["count"] for x in g["groups"]}[in_progress.name] == 1

    rows = api.post(f"/projects/{project.key}/list",
                    {"group_by": "status", "limit": 50}).json()["rows"]
    assert rows[-1]["key"] == loose.key and rows[-1]["group"] == in_progress.id

    e = api.post(f"/projects/{project.key}/list/groups", {"group_by": "epic"}).json()
    groups = {x["key"]: x for x in e["groups"]}
    assert groups[epic.id]["count"] == 2  # the story and its subtask
    assert groups[epic.id]["ref"]["key"] == epic.key
    assert groups[None]["label"] == "Sin épica" and groups[None]["count"] == 2
    assert e["groups"][-1]["key"] is None
    page = api.post(f"/projects/{project.key}/list", {"group_by": "epic", "limit": 50}).json()
    by_key = {r["key"]: r for r in page["rows"]}
    assert by_key[sub.key]["group"] == epic.id and by_key[sub.key]["epic"]["key"] == epic.key

    a = api.post(f"/projects/{project.key}/list/groups", {"group_by": "assignee"}).json()
    assert a["groups"][-1]["label"] == "Sin asignar"
    assert api.post(f"/projects/{project.key}/list/groups",
                    {"group_by": "summary"}).status_code == 422


def test_children_rows_include_archived_read_only(api, admin, member, project, make_issue):
    epic = make_issue("Épica", type_name="Épica")
    s1 = make_issue("Uno", type_name="Historia", parent_id=epic.id)
    s2 = make_issue("Dos", type_name="Historia", parent_id=epic.id)
    make_issue("Sub", type_name="Subtarea", parent_id=s1.id)
    services.archive_issue(admin, s2)

    api.login(member)
    top = api.post(f"/projects/{project.key}/list", {"jql": "type = \"Épica\""}).json()
    assert top["rows"][0]["children_count"] == 2
    kids = api.post(f"/projects/{project.key}/list", {"parent_id": epic.id}).json()
    assert kids["total"] == 2
    rows = {r["key"]: r for r in kids["rows"]}
    assert rows[s1.key]["children_count"] == 1
    assert rows[s2.key]["is_archived"] and "edit_issues" not in rows[s2.key]["permissions"]
    assert api.post(f"/projects/{project.key}/list", {"parent_id": 999999}).status_code == 404


def test_rows_refresh_and_custom_field_users(api, admin, member, project, make_issue):
    from apps.issues.models import CustomField

    cf = CustomField.objects.create(name="Revisor", kind="user")
    a = make_issue("A", custom_fields={str(cf.id): member.id})
    b = make_issue("B")
    services.update_issue(admin, b, {"summary": "B editada"})
    api.login(member)
    r = api.post(f"/projects/{project.key}/list/rows",
                 {"ids": [a.id, b.id, 999999], "group_by": "priority"})
    assert r.status_code == 200, r.content
    data = r.json()
    rows = {x["key"]: x for x in data["rows"]}
    assert set(rows) == {a.key, b.key} and rows[b.key]["summary"] == "B editada"
    assert rows[a.key]["custom_fields"] == {str(cf.id): member.id}
    assert rows[a.key]["group"] == a.priority_id
    assert data["users"][str(member.id)]["name"] == member.display_name


def test_config_roundtrip_validation_and_isolation(api, admin, member, project):
    url = f"/projects/{project.key}/list/config"
    api.login(member)
    assert api.get(url).json() == {"config": None, "updated_at": None}
    body = {"columns": [{"id": "key", "width": 5}, {"id": "summary", "width": 400},
                        {"id": "cf:12"}, {"id": "key"}],
            "group_by": "status", "jql": "assignee = currentUser()",
            "quick_filters": ["mine", "board:3", "Bad Id"], "collapsed": ["status:4", "x"]}
    r = api.put(url, body)
    assert r.status_code == 200, r.content
    cfg = r.json()["config"]
    assert cfg["columns"] == [{"id": "key", "width": 40}, {"id": "summary", "width": 400},
                              {"id": "cf:12", "width": None}]
    assert cfg["group_by"] == "status" and cfg["quick_filters"] == ["mine", "board:3"]
    assert cfg["collapsed"] == ["status:4"]
    assert api.get(url).json()["config"] == cfg

    assert api.put(url, {"columns": [{"id": "DROP TABLE"}]}).status_code == 422
    assert api.put(url, {"group_by": "summary"}).status_code == 422

    api.login(admin)  # another user: own (empty) layout
    assert api.get(url).json()["config"] is None
    api.login(member)
    assert api.delete(url).status_code == 204
    assert api.get(url).json()["config"] is None


def test_export_visible_columns(api, member, project, make_issue, select_field):
    make_issue("Con entorno", labels=["a", "b"], custom_fields={str(select_field.id): "p"},
               story_points=3)
    api.login(member)
    jql = f"project = {project.key}"
    r = api.get("/search/export", jql=jql,
                columns=f"key,summary,labels,story_points,cf:{select_field.id}")
    assert r.status_code == 200, r.content
    rows = _csv(r)
    assert rows[0] == ["Clave", "Resumen", "Etiquetas", "Puntos de historia", "Entorno"]
    assert rows[1][1:] == ["Con entorno", "a b", "3", "Producción"]

    assert api.get("/search/export", jql=jql, columns="key,nope").status_code == 422
    assert api.get("/search/export", jql=jql, columns="cf:999999").status_code == 422
    # without columns the default export is unchanged
    default = _csv(api.get("/search/export", jql=jql))
    assert default[0][:3] == ["Clave", "Resumen", "Tipo"]


# Every column of the list sorts (Jira's ORDER BY); a new column needs a JQL sort.
UNSORTABLE: set[str] = set()


@pytest.fixture
def every_kind(project, member):
    """One custom field of each kind on the project, plus a value for it."""
    from apps.issues.models import CustomField

    options = [{"id": "a", "value": "A"}, {"id": "b", "value": "B"}]
    values = {"text": "hola", "textarea": "texto", "number": 4.5, "date": "2026-03-01",
              "datetime": "2026-03-01T10:00:00+00:00", "select": "b",
              "multiselect": ["b", "a"], "checkbox": ["a"], "user": member.id,
              "multiuser": [member.id], "url": "https://example.com", "labels": ["x"]}
    assert set(values) == set(CustomField.Kind.values)
    out = {}
    for kind, value in values.items():
        cf = CustomField.objects.create(name=f"Campo {kind}", kind=kind, options=options)
        cf.projects.add(project)
        out[str(cf.id)] = value
    return out


def test_every_sortable_column_is_valid_jql(api, member, project, make_issue, every_kind):
    from apps.boards.models import Board, Sprint

    sprint = Sprint.objects.create(board=Board.objects.filter(project=project).first(),
                                   name="S1", state="active")
    epic = make_issue("Épica", type_name="Épica")
    from apps.projects.models import Component, Version

    comp = Component.objects.create(project=project, name="Web")
    version = Version.objects.create(project=project, name="1.0")
    make_issue("Uno", type_name="Historia", parent_id=epic.id, labels=["web"],
               sprint_id=sprint.id, custom_fields=every_kind, component_ids=[comp.id],
               fix_version_ids=[version.id], affects_version_ids=[version.id],
               original_estimate=3600)
    make_issue("Dos", type_name="Historia")
    api.login(member)
    meta = api.get(f"/projects/{project.key}/list/meta").json()
    by_id = {c["id"]: c for c in meta["columns"]}
    assert {i for i, c in by_id.items() if not c["sort"]} == UNSORTABLE
    assert by_id["sprint"]["sort"] == "sprint" and by_id["parent"]["sort"] == "parent"
    assert by_id["labels"]["sort"] == "labels"
    assert {by_id[c]["sort"] for c in ("components", "fix_versions", "affects_versions",
                                       "original_estimate", "remaining_estimate",
                                       "time_spent", "flagged", "resolution")} == {
        "component", "fixVersion", "affectedVersion", "originalEstimate",
        "remainingEstimate", "timeSpent", "flagged", "resolution"}
    for cid in every_kind:
        assert by_id[f"cf:{cid}"]["sort"] == f"cf[{cid}]"
    sortable = [c["sort"] for c in meta["columns"] if c["sort"]]
    for field in sortable:
        for direction in ("ASC", "DESC"):
            jql = (f'project = "{project.key}" AND (summary ~ "Uno") AND text ~ "Uno" '
                   f"ORDER BY {field} {direction}, created DESC")
            for group_by in ("assignee", "epic", None):
                r = api.post(f"/projects/{project.key}/list",
                             {"jql": jql, "group_by": group_by})
                assert r.status_code == 200, (field, r.content)
                assert r.json()["total"] == 1
        # the same JQL drives the search and the CSV export of the visible columns
        jql = f"project = {project.key} ORDER BY {field} DESC"
        r = api.post("/search", {"jql": jql})
        assert r.status_code == 200 and r.json()["total"] == 3, (field, r.content)
        r = api.get("/search/export", jql=jql, columns="key,summary")
        assert r.status_code == 200, (field, r.content)
        assert len(_csv(r)) == 4


def test_sorted_list_pages_have_bounded_queries(api, member, project, make_issue,
                                                every_kind):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    sort = ", ".join(["sprint", "parent", "labels DESC"] + [f"cf[{c}]" for c in every_kind])
    api.login(member)

    def page(group_by):
        with CaptureQueriesContext(connection) as ctx:
            r = api.post(f"/projects/{project.key}/list",
                         {"jql": f"ORDER BY {sort}", "group_by": group_by, "limit": 100})
        assert r.status_code == 200, r.content
        return len(ctx), len(r.json()["rows"])

    epic = make_issue("Épica", type_name="Épica")

    def add(n):
        for k in range(n):
            make_issue(f"Fila {k}", type_name="Historia", parent_id=epic.id,
                       labels=["b", "a"], custom_fields=every_kind)

    add(2)
    small = {g: page(g) for g in (None, "status")}
    add(10)
    big = {g: page(g) for g in (None, "status")}
    for g in small:
        assert small[g][1] == 3 and big[g][1] == 13
        assert big[g][0] == small[g][0], (g, small[g], big[g])  # no per-row queries


def test_team_column_follows_the_planning_app(api, member, project, make_issue):
    from apps.listview.columns import has_team_field, team_is_editable

    api.login(member)
    cols = {c["id"]: c for c in api.get(f"/projects/{project.key}/list/meta").json()["columns"]}
    if not has_team_field():
        assert "team" not in cols
        return
    assert cols["team"]["label"] == "Equipo"
    assert cols["team"]["field"] == ("team" if team_is_editable() else None)
    make_issue("Sin equipo")
    row = api.post(f"/projects/{project.key}/list", {}).json()["rows"][0]
    assert row["team"] is None
