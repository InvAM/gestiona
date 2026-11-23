"""Soft delete of catalogs/configuration, restore, PROTECT → 409 and flag-based roles."""

import pytest

pytestmark = pytest.mark.django_db


def _by_name(rows):
    return {r["name"]: r for r in rows}


# ------------------------------------------------------------------ priorities (FK catalog)

def test_priority_soft_delete_hides_it_but_issues_keep_it(api, admin, member, project,
                                                          make_issue):
    from apps.issues.models import Issue, Priority

    api.login(admin)
    high = Priority.objects.get(name="Alta")
    issue = make_issue("Con prioridad alta", priority_id=high.id)

    assert api.delete(f"/priorities/{high.id}").status_code == 204
    assert "Alta" not in _by_name(api.get("/priorities").json())
    meta = api.get("/projects/GES/meta").json()
    assert "Alta" not in [p["name"] for p in meta["priorities"]]
    # JQL value autocomplete no longer offers it
    assert "Alta" not in [s["label"] for s in api.get("/search/suggest?field=priority").json()]

    # the issue still shows it: FK access goes through _base_manager
    assert Issue.objects.get(pk=issue.pk).priority.name == "Alta"
    assert api.get(f"/issues/{issue.key}").json()["priority"]["name"] == "Alta"
    assert Priority.all_objects.get(pk=high.pk).is_deleted

    # papelera + restore are admin only
    api.login(member)
    assert api.get("/priorities?deleted=true").status_code == 403
    assert api.post(f"/priorities/{high.id}/restore").status_code == 403
    api.login(admin)
    trash = api.get("/priorities?deleted=true").json()
    assert [p["name"] for p in trash] == ["Alta"] and trash[0]["deleted_at"]
    r = api.post(f"/priorities/{high.id}/restore")
    assert r.status_code == 200 and r.json()["deleted_at"] is None
    assert "Alta" in _by_name(api.get("/priorities").json())


def test_deleted_name_can_be_reused_and_restore_detects_clash(api, admin):
    api.login(admin)
    created = api.post("/link-types", {"name": "Depende", "outward": "depende de",
                                       "inward": "es dependencia de"})
    assert created.status_code == 201
    old = created.json()["id"]
    assert api.post("/link-types", {"name": "Depende", "outward": "a",
                                    "inward": "b"}).status_code == 409
    assert api.delete(f"/link-types/{old}").status_code == 204
    again = api.post("/link-types", {"name": "Depende", "outward": "a", "inward": "b"})
    assert again.status_code == 201
    clash = api.post(f"/link-types/{old}/restore")
    assert clash.status_code == 409 and clash.json()["code"] == "name_taken"


def test_default_priority_cannot_be_deleted(api, admin):
    from apps.issues.models import Priority

    api.login(admin)
    default = Priority.objects.get(is_default=True)
    r = api.delete(f"/priorities/{default.id}")
    assert r.status_code == 409 and r.json()["code"] == "is_default"


# ------------------------------------------------------------------ PROTECT → 409

def test_permanent_delete_of_used_priority_is_409_with_count(api, admin, project, make_issue):
    from apps.issues.models import Priority

    api.login(admin)
    low = Priority.objects.get(name="Baja")
    make_issue("Uno", priority_id=low.id)
    make_issue("Dos", priority_id=low.id)
    r = api.delete(f"/priorities/{low.id}?permanent=true")
    assert r.status_code == 409, r.content
    body = r.json()
    assert body["code"] == "protected"
    assert body["message"] == "No se puede borrar: lo usan 2 incidencias"
    assert body["details"]["usages"] == [{"count": 2, "label": "incidencias"}]
    assert Priority.objects.filter(pk=low.pk).exists()  # rolled back, still alive

    unused = Priority.objects.get(name="Más baja")
    assert api.delete(f"/priorities/{unused.id}?permanent=true").status_code == 204
    assert not Priority.all_objects.filter(pk=unused.pk).exists()


def test_permanent_delete_requires_admin(api, member):
    from apps.issues.models import Priority

    api.login(member)
    p = Priority.objects.get(name="Baja")
    assert api.delete(f"/priorities/{p.id}?permanent=true").status_code == 403


def test_workflow_mapping_protects_issue_type(api, admin, project, types):
    from apps.workflows.models import Workflow

    api.login(admin)
    wf = Workflow.objects.get(name="Flujo de tareas")
    assert api.put("/projects/GES/workflow-mappings",
                   [{"issue_type_id": types["Error"].id, "workflow_id": wf.id}]).status_code == 204
    r = api.delete(f"/issue-types/{types['Error'].id}?permanent=true")
    assert r.status_code == 409
    assert r.json()["message"] == "No se puede borrar: lo usa 1 flujo por tipo"


def test_in_use_configuration_cannot_be_soft_deleted(api, admin, project):
    from apps.workflows.models import Status, Workflow

    api.login(admin)
    wf = Workflow.objects.get(name="Flujo de software")
    r = api.delete(f"/workflows/{wf.id}")
    assert r.status_code == 409 and r.json()["code"] == "in_use"
    assert r.json()["message"] == "No se puede borrar: lo usa 1 proyecto"

    in_progress = Status.objects.get(name="En curso")  # in both seeded workflows
    r = api.delete(f"/statuses/{in_progress.id}")
    assert r.status_code == 409
    assert r.json()["message"] == "No se puede borrar: lo usan 2 flujos de trabajo"

    backlog = Status.objects.get(name="Backlog")  # in no workflow
    assert api.delete(f"/statuses/{backlog.id}").status_code == 204
    assert "Backlog" not in _by_name(api.get("/statuses").json())


# ------------------------------------------------------------------ issue types

def test_issue_type_soft_delete(api, admin, project, make_issue, types):
    api.login(admin)
    bug = types["Error"]
    issue = make_issue("Fallo", type_name="Error")
    assert api.delete(f"/issue-types/{bug.id}").status_code == 204
    meta = api.get("/projects/GES/meta").json()
    assert "Error" not in [t["name"] for t in meta["issue_types"]]
    assert str(bug.id) not in meta["statuses_by_type"]
    assert "Error" not in [t["name"] for t in api.get("/issue-types").json()]
    assert "Error" not in [s["label"] for s in api.get("/search/suggest?field=type").json()]
    assert api.get(f"/issues/{issue.key}").json()["type"]["name"] == "Error"
    # can't create new issues with it
    r = api.post("/issues", {"project": "GES", "issue_type_id": bug.id, "summary": "x"})
    assert r.status_code in (403, 404, 422)
    assert api.post(f"/issue-types/{bug.id}/restore").status_code == 200
    meta = api.get("/projects/GES/meta").json()
    assert "Error" in [t["name"] for t in meta["issue_types"]]


# ------------------------------------------------------------------ project catalogs

def test_component_and_version_soft_delete(api, admin, member, project, make_issue):
    api.login(admin)
    comp = api.post("/projects/GES/components", {"name": "API"}).json()
    ver = api.post("/projects/GES/versions", {"name": "1.0"}).json()
    issue = make_issue("Con componente", component_ids=[comp["id"]], fix_version_ids=[ver["id"]])

    assert api.delete(f"/projects/GES/components/{comp['id']}").status_code == 204
    assert api.delete(f"/projects/GES/versions/{ver['id']}").status_code == 204
    meta = api.get("/projects/GES/meta").json()
    assert meta["components"] == [] and meta["versions"] == []
    assert api.get("/projects/GES/components").json() == []
    # the issue keeps showing them
    out = api.get(f"/issues/{issue.key}").json()
    assert [c["name"] for c in out["components"]] == ["API"]
    assert [v["name"] for v in out["fix_versions"]] == ["1.0"]
    # name can be reused while deleted
    assert api.post("/projects/GES/components", {"name": "API"}).status_code == 201

    api.login(member)
    assert api.get("/projects/GES/versions?deleted=true").status_code == 403
    api.login(admin)
    trash = api.get("/projects/GES/versions?deleted=true").json()
    assert [v["name"] for v in trash] == ["1.0"]
    r = api.post(f"/projects/GES/versions/{ver['id']}/restore")
    assert r.status_code == 200 and r.json()["issue_count"] == 1
    clash = api.post(f"/projects/GES/components/{comp['id']}/restore")
    assert clash.status_code == 409


def test_project_categories(api, admin, member, project):
    api.login(member)
    assert api.post("/project-categories", {"name": "Producto"}).status_code == 403
    api.login(admin)
    cat = api.post("/project-categories", {"name": "Producto"}).json()
    assert api.patch("/projects/GES", {"category_id": cat["id"]}).status_code == 200
    assert api.delete(f"/project-categories/{cat['id']}").status_code == 204
    assert api.get("/project-categories").json() == []
    # the project keeps showing its category
    assert api.get("/projects/GES").json()["category"]["name"] == "Producto"
    assert api.patch("/projects/GES", {"category_id": cat["id"] + 999}).status_code == 422
    assert api.post(f"/project-categories/{cat['id']}/restore").json()["project_count"] == 1


# ------------------------------------------------------------------ custom fields

def test_custom_field_soft_delete_keeps_values_and_options(api, admin, project, make_issue):
    from apps.issues.models import Issue

    api.login(admin)
    cf = api.post("/custom-fields", {"name": "Entorno", "kind": "select", "options": [
        {"id": "a", "value": "Producción"}, {"id": "b", "value": "Pruebas"}]}).json()
    issue = make_issue("Con campo", custom_fields={str(cf["id"]): "b"})
    # removing option "b" keeps it as deleted so the issue still renders
    upd = api.put(f"/custom-fields/{cf['id']}", {"name": "Entorno", "kind": "select",
                                                 "options": [{"id": "a", "value": "Producción"}]})
    assert upd.json()["options"] == [{"id": "a", "value": "Producción"},
                                     {"id": "b", "value": "Pruebas", "deleted": True}]
    meta_cf = next(c for c in api.get("/projects/GES/meta").json()["custom_fields"]
                   if c["id"] == cf["id"])
    assert {"id": "b", "value": "Pruebas", "deleted": True} in meta_cf["options"]

    assert api.delete(f"/custom-fields/{cf['id']}").status_code == 204
    assert cf["id"] not in [c["id"] for c in api.get("/projects/GES/meta").json()
                            ["custom_fields"]]
    assert Issue.objects.get(pk=issue.pk).custom_fields == {str(cf["id"]): "b"}
    assert api.post(f"/custom-fields/{cf['id']}/restore").status_code == 200
    assert api.delete(f"/custom-fields/{cf['id']}?permanent=true").status_code == 204
    assert Issue.objects.get(pk=issue.pk).custom_fields == {}


# ------------------------------------------------------------------ roles by flag

def test_renamed_admin_role_keeps_its_protection(api, admin, member, project):
    from apps.projects.models import Role

    api.login(admin)
    adm = _by_name(api.get("/roles").json())["Administrador"]
    r = api.put(f"/roles/{adm['id']}", {"name": "Jefatura", "permissions": adm["permissions"]})
    assert r.status_code == 200 and r.json()["name"] == "Jefatura"
    assert r.json()["is_system"] and r.json()["locked_permissions"] == ["administer"]
    bad = api.put(f"/roles/{adm['id']}", {"name": "Jefatura", "permissions": ["browse"]})
    assert bad.status_code == 422 and "Administrar proyecto" in bad.json()["message"]
    assert api.delete(f"/roles/{adm['id']}").status_code == 422
    # project creation still finds the admin role by flag, not by name
    assert Role.objects.admin_role().name == "Jefatura"
    p = api.post("/projects", {"name": "Otro", "key": "OTR"})
    assert p.status_code == 201, p.content
    members = api.get("/projects/OTR/members").json()
    assert [m["role"]["name"] for m in members] == ["Jefatura"]


def test_project_creation_uses_template_flags(api, admin):
    from apps.issues.models import IssueType
    from apps.workflows.models import Workflow

    api.login(admin)
    Workflow.objects.filter(name="Flujo de tareas").update(name="Operaciones")
    IssueType.objects.filter(name="Tarea").update(name="Trabajo")
    r = api.post("/projects", {"name": "Negocio", "key": "NEG", "template": "business"})
    assert r.status_code == 201, r.content
    meta = api.get("/projects/NEG/meta").json()
    assert sorted(t["name"] for t in meta["issue_types"]) == ["Subtarea", "Trabajo"]
    assert {w["workflow_name"] for w in meta["issue_type_workflows"]} == {"Operaciones"}


def test_default_role_flag_is_used_when_adding_members(api, admin, make_user, project):
    from apps.projects.models import Role

    api.login(admin)
    Role.objects.filter(is_default=True).update(name="Colaborador")
    u = make_user()
    r = api.put(f"/projects/GES/members/{u.id}", {})
    assert r.status_code == 200 and r.json()["role"]["name"] == "Colaborador"


def test_role_soft_delete_rules(api, admin, member, project):
    api.login(admin)
    role = api.post("/roles", {"name": "Cliente", "permissions": ["add_comments"]}).json()
    assert role["in_use"] == 0 and not role["is_system"]
    api.put(f"/projects/GES/members/{member.id}", {"role_id": role["id"]})
    r = api.delete(f"/roles/{role['id']}")
    assert r.status_code == 409
    assert r.json()["message"] == "No se puede borrar: lo usa 1 membresía"
    r = api.delete(f"/roles/{role['id']}?permanent=true")
    assert r.status_code == 409 and r.json()["code"] == "protected"

    api.delete(f"/projects/GES/members/{member.id}")
    assert api.delete(f"/roles/{role['id']}").status_code == 204
    assert "Cliente" not in _by_name(api.get("/roles").json())
    assert api.put(f"/projects/GES/members/{member.id}",
                   {"role_id": role["id"]}).status_code == 422
    assert [x["name"] for x in api.get("/roles?deleted=true").json()] == ["Cliente"]
    assert api.post(f"/roles/{role['id']}/restore").json()["name"] == "Cliente"


# ------------------------------------------------------------------ owned configuration

def test_automation_rule_soft_delete(api, admin, project, make_issue,
                                     django_capture_on_commit_callbacks):
    from apps.automation.models import AutomationLog

    api.login(admin)
    rule = api.post("/automation/rules?project=GES", {
        "name": "Comentar", "trigger": "issue_created",
        "actions": [{"type": "comment", "body": "hola"}]}).json()
    assert api.delete(f"/automation/rules/{rule['id']}").status_code == 204
    assert api.get("/automation/rules?project=GES").json() == []
    with django_capture_on_commit_callbacks(execute=True):
        make_issue("No dispara")
    assert not AutomationLog.objects.filter(rule_id=rule["id"]).exists()
    trash = api.get("/automation/rules?project=GES&deleted=true").json()
    assert [r["id"] for r in trash] == [rule["id"]]
    assert api.post(f"/automation/rules/{rule['id']}/restore").status_code == 200
    with django_capture_on_commit_callbacks(execute=True):
        make_issue("Ahora sí")
    assert AutomationLog.objects.filter(rule_id=rule["id"]).exists()


def test_dashboard_filter_and_form_soft_delete(api, admin, member, project, types):
    api.login(member)
    d = api.post("/dashboards", {"name": "Mío"}).json()
    assert api.delete(f"/dashboards/{d['id']}").status_code == 204
    assert api.get(f"/dashboards/{d['id']}").status_code == 404
    assert [x["id"] for x in api.get("/dashboards?deleted=true").json()] == [d["id"]]
    restored = api.post(f"/dashboards/{d['id']}/restore").json()
    assert restored["gadgets"]  # gadgets survive

    f = api.post("/filters", {"name": "Lo mío", "jql": "assignee = currentUser()"}).json()
    assert api.delete(f"/filters/{f['id']}").status_code == 204
    assert api.get(f"/filters/{f['id']}").status_code == 404
    assert api.post(f"/filters/{f['id']}/restore").status_code == 200

    api.login(admin)
    form = api.post("/projects/GES/forms", {"name": "Soporte",
                                            "issue_type_id": types["Tarea"].id,
                                            "fields": []}).json()
    assert api.delete(f"/forms/{form['id']}").status_code == 204
    assert api.get(f"/f/{form['slug']}").status_code == 404
    assert api.post(f"/forms/{form['id']}/restore").status_code == 200
    assert api.get(f"/f/{form['slug']}").status_code == 200
