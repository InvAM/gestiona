"""GET /meta (single source of truth for UI choices) and project meta workflow info."""

import pytest

pytestmark = pytest.mark.django_db


def _values(rows):
    return [r["value"] for r in rows]


def test_meta_requires_login(client):
    assert client.get("/api/v1/meta").status_code == 401


def test_meta_lists_come_from_backend_enums(api, member):
    from apps.audit.models import AuditEntry
    from apps.automation import engine
    from apps.automation.models import Trigger
    from apps.dashboards.gadgets import GROUP_FIELDS
    from apps.dashboards.models import Gadget
    from apps.forms.api import BUILTIN
    from apps.projects.models import Perm

    api.login(member)
    r = api.get("/meta")
    assert r.status_code == 200, r.content
    m = r.json()
    auto = m["automation"]
    assert _values(auto["triggers"]) == list(Trigger.values)
    assert all(t["label"] and t["description"] for t in auto["triggers"])
    # labels in models must cover exactly what the engine accepts
    assert set(_values(auto["actions"])) == engine.ACTION_TYPES
    assert set(_values(auto["conditions"])) == engine.CONDITION_TYPES
    assert set(_values(auto["assign_to"])) == engine.ASSIGN_TO
    assert set(_values(auto["notify_to"])) == engine.NOTIFY_TO
    assert {a["value"]: a["admin_only"] for a in auto["actions"]}["webhook"] is True
    assert "priority" in _values(auto["editable_fields"])
    assert _values(auto["weekdays"]) == list(range(7))
    assert "{{issue.key}}" in _values(auto["variables"])

    assert set(_values(m["gadget_kinds"])) == set(Gadget.Kind.values)
    assert set(_values(m["group_by_fields"])) == set(GROUP_FIELDS)
    assert {g["value"]: g["two_d"] for g in m["group_by_fields"]}["labels"] is False
    assert _values(m["form_builtin_fields"]) == list(BUILTIN)
    assert [f for f in m["form_builtin_fields"] if f["always_required"]][0]["value"] == "summary"
    assert _values(m["audit_categories"]) == list(AuditEntry.Category.values)
    assert _values(m["permissions"]) == list(Perm.values)
    assert {"label": "Por hacer", "value": "todo", "description": ""} in m["status_categories"]
    assert {"value": -1, "label": "Subtarea"} in m["issue_type_levels"]


def test_automation_templates_use_real_project_data(api, admin, project, types):
    from apps.issues.models import IssueType

    api.login(admin)
    # renaming the bug type must not break the template: it is found by level + icon
    IssueType.objects.filter(pk=types["Error"].pk).update(name="Defecto")
    tpl = {t["key"]: t for t in api.get("/meta?project=GES").json()["automation"]["templates"]}
    bugs = tpl["assign_new_bugs"]
    assert bugs["ready"]
    assert bugs["draft"]["conditions"] == [{"type": "jql", "jql": 'type = "Defecto"'}]
    assert bugs["draft_template"]["conditions"][0]["jql"] == "type = {{param.issue_type}}"
    param = bugs["params"][0]
    assert param["value"] == types["Error"].id and param["token"] == "{{param.issue_type}}"
    assert {o["name"] for o in param["options"]} >= {"Defecto", "Historia", "Tarea"}
    done = tpl["notify_reporter_on_done"]["draft"]["trigger_config"]["to_status_ids"]
    assert done and all(isinstance(i, int) for i in done)
    # every ready draft is accepted by the rule validator as-is
    for t in tpl.values():
        if t["ready"]:
            r = api.post("/automation/rules?project=GES", t["draft"])
            assert r.status_code == 201, (t["key"], r.content)
    assert api.get("/automation/templates?project=GES").status_code == 200


def test_template_without_matching_type_needs_a_choice(api, admin, project, types):
    from apps.issues.models import IssueType

    api.login(admin)
    IssueType.objects.filter(pk=types["Error"].pk).update(icon="task")
    tpl = {t["key"]: t for t in api.get("/meta?project=GES").json()["automation"]["templates"]}
    assert tpl["assign_new_bugs"]["ready"] is False
    assert tpl["assign_new_bugs"]["draft"] is None
    assert tpl["assign_new_bugs"]["params"][0]["value"] is None


def test_meta_project_param_checks_access(api, outsider, project):
    from apps.projects.models import Project

    Project.objects.filter(pk=project.pk).update(access=Project.Access.PRIVATE)
    api.login(outsider)
    assert api.get("/meta?project=GES").status_code == 404
    assert api.get("/meta?project=NOPE").status_code == 404


def test_project_meta_exposes_workflow_per_type(api, admin, project, types):
    from apps.workflows.models import Workflow

    api.login(admin)
    tasks_wf = Workflow.objects.get(name="Flujo de tareas")
    api.put("/projects/GES/workflow-mappings",
            [{"issue_type_id": types["Error"].id, "workflow_id": tasks_wf.id}])
    meta = api.get("/projects/GES/meta").json()
    by_type = {w["issue_type_id"]: w for w in meta["issue_type_workflows"]}
    assert set(by_type) == {t["id"] for t in meta["issue_types"]}
    bug = by_type[types["Error"].id]
    assert bug["workflow_id"] == tasks_wf.id
    assert bug["initial_status_id"] == tasks_wf.initial_status_id
    assert bug["status_ids"] == [s.id for s in tasks_wf.ordered_statuses()]
    assert bug["status_ids"] == meta["statuses_by_type"][str(types["Error"].id)]
    story = by_type[types["Historia"].id]
    assert story["workflow_id"] == project.workflow_id
    assert len(story["status_ids"]) == 4 and len(bug["status_ids"]) == 3


def test_flags_replace_name_checks_in_the_ui(api, admin, project, types):
    api.login(admin)
    meta = api.get("/projects/GES/meta").json()
    # default type = first standard type (Historia in the scrum template) until configured
    assert meta["default_issue_type_id"] == types["Historia"].id
    assert api.patch("/projects/GES", {"default_issue_type_id": types["Tarea"].id}) \
        .status_code == 200
    assert api.get("/projects/GES/meta").json()["default_issue_type_id"] == types["Tarea"].id
    assert api.patch("/projects/GES", {"default_issue_type_id": types["Subtarea"].id}) \
        .status_code == 422
    assert [p["name"] for p in meta["priorities"] if p["is_default"]] == ["Media"]
    flags = {t["name"]: t["has_affects_versions"] for t in meta["issue_types"]}
    assert flags["Error"] is True and flags["Historia"] is False
    perms = {p["key"]: p["always"] for p in api.get("/permissions").json()}
    assert perms["browse"] is True and perms["administer"] is False
    m = api.get("/meta").json()
    kinds = {k["value"]: k["has_options"] for k in m["custom_field_kinds"]}
    assert kinds["select"] and not kinds["text"]
    assert {"value": "fix_versions", "label": "Versión de corrección", "description": ""} \
        in m["issue_fields"]


def test_issue_ref_marks_archived_parent(api, admin, project, make_issue):
    from apps.issues import services

    api.login(admin)
    epic = make_issue("Épica", type_name="Épica")
    child = make_issue("Hija", parent_id=epic.id)
    assert api.get(f"/issues/{child.key}").json()["parent"]["is_archived"] is False
    services.archive_issue(admin, epic)
    assert api.get(f"/issues/{child.key}").json()["parent"]["is_archived"] is True
