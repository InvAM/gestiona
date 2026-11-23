"""Screens and field configurations (Jira company-managed): defaults, resolution, validation
on every entry point, administration (soft delete, 409, permissions) and query budget."""

from datetime import date

import pytest

from apps.issues import fieldrules
from apps.issues.models import (
    CustomField,
    FieldConfiguration,
    FieldConfigurationItem,
    FieldConfigurationScheme,
    IssueTypeScreenScheme,
    Screen,
    ScreenScheme,
)
from apps.issues.services import IssueInput, create_issue

pytestmark = pytest.mark.django_db

ALL = list(fieldrules.SYSTEM_KEYS)


# ------------------------------------------------------------------ helpers

def _without(*keys):
    return [k for k in ALL if k not in keys]


def _setup(api, admin, project, *, config=None, create=None, edit=None, view=None,
           by_type=None, screens_by_type=None):
    """Give `project` its own schemes through the admin API.

    config: [{key, required, hidden, description}] for the default configuration.
    create / edit / view: field keys of those screens (None = the default screen).
    by_type: {type_id: config fields} (one configuration per type).
    screens_by_type: {type_id: {"create": keys, ...}} (one screen scheme per type)."""
    api.login(admin)
    n = FieldConfiguration.all_objects.count()

    def mk_config(fields, name):
        r = api.post("/field-configurations", {"name": name, "fields": fields})
        assert r.status_code == 201, r.json()
        return r.json()["id"]

    def mk_screen(keys, name):
        r = api.post("/screens", {"name": name, "tabs": [{"name": "General", "fields": keys}]})
        assert r.status_code == 201, r.json()
        return r.json()["id"]

    def mk_ss(ops, name):
        default = Screen.objects.get(is_default=True).id
        body = {"name": name, "default_screen_id": default}
        for op, keys in ops.items():
            if keys is not None:
                body[f"{op}_screen_id"] = mk_screen(keys, f"{name} {op}")
        r = api.post("/screen-schemes", body)
        assert r.status_code == 201, r.json()
        return r.json()["id"]

    cfg = mk_config(config or [], f"Config {n}")
    entries = [{"issue_type_id": tid, "configuration_id": mk_config(f, f"Config {n} {tid}")}
               for tid, f in (by_type or {}).items()]
    r = api.post("/field-configuration-schemes", {
        "name": f"FCS {n}", "default_configuration_id": cfg, "entries": entries})
    assert r.status_code == 201, r.json()
    fcs = r.json()["id"]
    ss = mk_ss({"create": create, "edit": edit, "view": view}, f"SS {n}")
    ss_entries = [{"issue_type_id": tid, "screen_scheme_id": mk_ss(ops, f"SS {n} {tid}")}
                  for tid, ops in (screens_by_type or {}).items()]
    r = api.post("/issue-type-screen-schemes", {
        "name": f"ITSS {n}", "default_screen_scheme_id": ss, "entries": ss_entries})
    assert r.status_code == 201, r.json()
    itss = r.json()["id"]
    r = api.put(f"/projects/{project.key}/field-schemes", {
        "field_configuration_scheme_id": fcs, "issue_type_screen_scheme_id": itss})
    assert r.status_code == 200, r.json()
    return {"fcs": fcs, "itss": itss, "config": cfg, "ss": ss}


def _create(api, project, types, **kw):
    body = {"project": project.key, "issue_type_id": types[kw.pop("type", "Tarea")].id,
            "summary": kw.pop("summary", "Algo")}
    body.update(kw)
    return api.post("/issues", body)


# ------------------------------------------------------------------ defaults / migration

def test_defaults_after_migration_keep_behaviour(api, admin, project, types):
    fc = FieldConfiguration.objects.get(is_default=True)
    screen = Screen.objects.get(is_default=True)
    assert fc.name == "Configuración de campos predeterminada" and not fc.items.exists()
    assert project.field_configuration_scheme.is_default
    assert project.issue_type_screen_scheme.is_default
    assert project.issue_type_screen_scheme.default_screen_scheme.default_screen == screen
    keys = list(screen.screen_fields.values_list("field", flat=True))
    assert keys[:len(ALL)] == ALL

    api.login(admin)
    rules = api.get(f"/projects/{project.key}/field-rules").json()
    task = rules["by_type"][str(types["Tarea"].id)]
    assert task["create_required"] == ["summary", "issue_type"] and task["hidden"] == []
    assert task["screens"]["create"]["fields"] == ALL
    assert task["screens"]["view"]["tabs"][0]["name"] == "General"
    epic = rules["by_type"][str(types["Épica"].id)]
    assert "parent" not in epic["screens"]["edit"]["fields"]  # structural, not config
    assert {f["key"] for f in rules["fields"]} >= set(ALL)
    assert all(not t["screen"] and not t["required_fields"] for t in task["transitions"])

    # everything optional: a bare create, a full edit and a transition work as before
    r = _create(api, project, types)
    assert r.status_code == 201, r.json()
    key = r.json()["key"]
    r = api.patch(f"/issues/{key}", {"story_points": 3, "labels": ["a"], "due_date": None})
    assert r.status_code == 200, r.json()
    t = api.get(f"/issues/{key}/transitions").json()[0]
    assert t["screen"] is None and t["required_fields"] == []
    assert api.post(f"/issues/{key}/transitions", {"transition_id": t["id"]}).status_code == 200


def test_new_projects_get_the_default_schemes(admin):
    from apps.projects.services import create_project

    fcs = FieldConfigurationScheme.objects.create(
        name="Otro", default_configuration=FieldConfiguration.objects.get(is_default=True))
    FieldConfigurationScheme.objects.filter(is_default=True).update(is_default=False)
    FieldConfigurationScheme.objects.filter(pk=fcs.pk).update(is_default=True)
    p = create_project(admin, name="Nuevo", key="NUE")
    assert p.field_configuration_scheme_id == fcs.id  # by flag, not by name
    assert p.issue_type_screen_scheme == IssueTypeScreenScheme.objects.get(is_default=True)


def test_new_custom_field_goes_to_default_screen_and_required_compat(api, admin, project, types):
    api.login(admin)
    r = api.post("/custom-fields", {"name": "Cliente", "kind": "text", "required": True})
    assert r.status_code == 201 and r.json()["required"] is True
    cid = r.json()["id"]
    screen = Screen.objects.get(is_default=True)
    assert list(screen.screen_fields.values_list("field", flat=True))[-1] == f"cf:{cid}"
    assert FieldConfigurationItem.objects.get(
        configuration__is_default=True, field=f"cf:{cid}").required
    # still required on create, like before the field configurations existed
    r = _create(api, project, types)
    assert r.status_code == 422 and r.json()["code"] == "fields"
    assert r.json()["details"]["fields"] == {f"cf:{cid}": "«Cliente» es obligatorio"}
    assert _create(api, project, types, custom_fields={str(cid): "ACME"}).status_code == 201
    meta = api.get(f"/projects/{project.key}/meta").json()
    assert next(c for c in meta["custom_fields"] if c["id"] == cid)["required"] is True
    # omitted `required` keeps it; false clears it
    body = {"name": "Cliente", "kind": "text"}
    assert api.put(f"/custom-fields/{cid}", body).json()["required"] is True
    assert api.put(f"/custom-fields/{cid}", {**body, "required": False}).json()["required"] \
        is False
    assert _create(api, project, types).status_code == 201


def test_catalog_and_meta(api, member):
    api.login(member)
    cf = CustomField.objects.create(name="Área", kind="select",
                                    options=[{"id": "a", "value": "A"}])
    fields = api.get("/fields").json()
    assert [f["key"] for f in fields[:len(ALL)]] == ALL
    summary = fields[0]
    assert summary == {"key": "summary", "label": "Resumen", "kind": "text", "system": True,
                       "custom_field_id": None, "locked": True, "has_options": False,
                       "options": [], "description": ""}
    custom = next(f for f in fields if f["key"] == f"cf:{cf.id}")
    assert custom["has_options"] and custom["kind"] == "select" and not custom["system"]
    meta = api.get("/meta").json()
    assert [o["value"] for o in meta["screen_operations"]] == ["create", "edit", "view"]
    assert meta["system_fields"][1] == {"value": "issue_type", "label": "Tipo de incidencia",
                                        "description": "", "kind": "issue_type", "locked": True}


# ------------------------------------------------------------------ create

def test_required_on_create_only_when_on_the_create_screen(api, admin, project, types, member):
    cfg = [{"key": "assignee", "required": True},
           {"key": "due_date", "required": True, "description": "Fecha comprometida"}]
    _setup(api, admin, project, config=cfg)
    r = _create(api, project, types)
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "fields"
    assert body["message"] == "Faltan campos obligatorios: «Responsable», «Fecha de vencimiento»"
    assert set(body["details"]["fields"]) == {"assignee", "due_date"}
    r = _create(api, project, types, assignee_id=member.id, due_date="2026-12-24")
    assert r.status_code == 201, r.json()

    # without those fields on the create screen they are not asked (Jira) + admin warning
    _setup(api, admin, project, config=cfg, create=_without("assignee", "due_date"))
    assert _create(api, project, types).status_code == 201
    rules = api.get(f"/projects/{project.key}/field-rules").json()["by_type"][
        str(types["Tarea"].id)]
    assert rules["create_required"] == ["summary", "issue_type"]
    assert rules["required"] == ["summary", "issue_type", "assignee", "due_date"]
    assert rules["descriptions"] == {"due_date": "Fecha comprometida"}
    assert {w["field"] for w in rules["warnings"]} == {"assignee", "due_date"}
    # a value for a field that is not on the create screen is refused, like Jira's REST API
    r = _create(api, project, types, due_date="2026-12-24")
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["due_date"] == \
        "El campo «Fecha de vencimiento» no está en la pantalla de creación"


def test_defaults_count_for_required_fields(api, admin, project, types):
    """Priority has a default and the reporter is the creator: required but satisfied."""
    _setup(api, admin, project, config=[{"key": "priority", "required": True},
                                        {"key": "reporter", "required": True}])
    assert _create(api, project, types).status_code == 201


def test_hidden_fields(api, admin, project, types):
    _setup(api, admin, project, config=[{"key": "labels", "hidden": True}])
    r = _create(api, project, types, labels=["x"])
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["labels"] == \
        "El campo «Etiquetas» está oculto para este tipo de incidencia"
    assert _create(api, project, types, labels=[]).status_code == 201  # empty = not set
    rules = api.get(f"/projects/{project.key}/field-rules").json()["by_type"][
        str(types["Tarea"].id)]
    assert rules["hidden"] == ["labels"] and rules["config"]["labels"]["hidden"]
    assert all("labels" not in s["fields"] for s in rules["screens"].values())
    # hidden + required, or hiding a locked field, is refused
    r = api.post("/field-configurations", {"name": "Mal", "fields": [
        {"key": "labels", "required": True, "hidden": True}]})
    assert r.status_code == 422
    r = api.post("/field-configurations", {"name": "Mal", "fields": [
        {"key": "summary", "required": True, "hidden": True}]})
    assert r.status_code == 422


def test_context_fields_and_quick_create(api, admin, project, types, make_issue):
    """Creating a sub-task (parent) or inside a sprint works without those fields on screen."""
    _setup(api, admin, project, create=["summary", "issue_type"])
    story = make_issue("Historia", type_name="Historia")
    r = _create(api, project, types, type="Subtarea", parent_id=story.id)
    assert r.status_code == 201, r.json()


def test_clone_checks_required_but_copies_everything(api, admin, project, types, make_issue):
    issue = make_issue("Original", story_points=5)
    _setup(api, admin, project, config=[{"key": "due_date", "required": True}],
           create=["summary", "issue_type", "due_date"])
    r = api.post(f"/issues/{issue.key}/clone", {})
    assert r.status_code == 422 and "due_date" in r.json()["details"]["fields"]
    issue.due_date = date(2026, 12, 1)
    issue.save()
    r = api.post(f"/issues/{issue.key}/clone", {})
    assert r.status_code == 201, r.json()
    assert r.json()["story_points"] == "5.0" or float(r.json()["story_points"]) == 5


# ------------------------------------------------------------------ edit

def test_edit_cannot_empty_a_required_field(api, admin, project, types, make_issue):
    issue = make_issue("Sin fecha")
    _setup(api, admin, project, config=[{"key": "due_date", "required": True}])
    # other fields can still be edited on an issue created before the rule
    assert api.patch(f"/issues/{issue.key}", {"story_points": 2}).status_code == 200
    assert api.patch(f"/issues/{issue.key}", {"due_date": "2026-12-01"}).status_code == 200
    r = api.patch(f"/issues/{issue.key}", {"due_date": None})
    assert r.status_code == 422
    assert r.json() == {"code": "fields", "message": "«Fecha de vencimiento» es obligatorio",
                        "details": {"fields": {"due_date": "«Fecha de vencimiento» es "
                                                           "obligatorio"}}}


def test_field_not_on_the_edit_screen(api, admin, project, types, make_issue, member):
    issue = make_issue("Algo", story_points=3)
    _setup(api, admin, project, edit=_without("story_points", "assignee"))
    r = api.patch(f"/issues/{issue.key}", {"story_points": 8})
    assert r.status_code == 422
    assert r.json()["message"] == \
        "El campo «Puntos de historia» no está en la pantalla de edición"
    # sending the current value changes nothing and is accepted
    assert api.patch(f"/issues/{issue.key}", {"story_points": 3, "summary": "Otro"}) \
        .status_code == 200
    # the Assign operation does not need the edit screen (like Jira)
    assert api.patch(f"/issues/{issue.key}", {"assignee": member.id}).status_code == 200


def test_changing_type_uses_the_new_type_rules(api, admin, project, types, make_issue):
    issue = make_issue("Algo")
    _setup(api, admin, project, by_type={types["Error"].id: [
        {"key": "due_date", "required": True}]})
    r = api.patch(f"/issues/{issue.key}", {"issue_type": types["Error"].id})
    assert r.status_code == 422 and "due_date" in r.json()["details"]["fields"]
    r = api.patch(f"/issues/{issue.key}", {"issue_type": types["Error"].id,
                                           "due_date": "2026-12-01"})
    assert r.status_code == 200, r.json()


# ------------------------------------------------------------------ per type

def test_schemes_per_issue_type(api, admin, project, types):
    bug, task = types["Error"], types["Tarea"]
    _setup(api, admin, project,
           by_type={bug.id: [{"key": "affects_versions", "required": True}]},
           screens_by_type={bug.id: {"create": ["summary", "issue_type", "affects_versions",
                                                "priority"]}})
    rules = api.get(f"/projects/{project.key}/field-rules").json()["by_type"]
    assert rules[str(bug.id)]["screens"]["create"]["fields"] == \
        ["summary", "issue_type", "affects_versions", "priority"]
    assert rules[str(bug.id)]["create_required"] == ["summary", "issue_type",
                                                     "affects_versions"]
    assert rules[str(task.id)]["create_required"] == ["summary", "issue_type"]
    assert rules[str(bug.id)]["field_configuration"]["name"] != \
        rules[str(task.id)]["field_configuration"]["name"]
    assert _create(api, project, types).status_code == 201
    r = _create(api, project, types, type="Error")
    assert r.status_code == 422 and list(r.json()["details"]["fields"]) == ["affects_versions"]
    r = _create(api, project, types, type="Error", labels=["x"])
    assert r.json()["details"]["fields"]["labels"].endswith("pantalla de creación")


def test_custom_field_contexts(api, admin, project, types):
    cf = CustomField.objects.create(name="Gravedad", kind="text")
    cf.issue_types.set([types["Error"]])
    rules = fieldrules.resolve(project, types["Tarea"])
    assert f"cf:{cf.id}" not in rules.fields
    assert f"cf:{cf.id}" in fieldrules.resolve(project, types["Error"]).on("create")
    api.login(admin)
    r = _create(api, project, types, custom_fields={str(cf.id): "alta"})
    assert r.status_code == 422
    assert "no se usa en este tipo" in r.json()["message"]


# ------------------------------------------------------------------ transitions

def _transition_with(project, *, screen_keys=None, required=(), issue=None):
    """A transition of the project's workflow (one available for `issue` if given)."""
    from apps.issues.services import available_transitions

    if issue is not None:
        t = available_transitions(project.lead, issue)[0]
    else:
        t = project.workflow.transitions.order_by("position", "id").first()
    if screen_keys is not None:
        s = Screen.objects.create(name=f"Transición {t.id}")
        tab = s.tabs.create(name="General")
        for i, k in enumerate(screen_keys):
            s.screen_fields.create(tab=tab, field=k, position=i)
        t.screen = s
    t.required_fields = list(required)
    t.save()
    return t


def test_transition_screen_and_validator(api, admin, member, project, make_issue):
    issue = make_issue("Algo")
    t = _transition_with(project, screen_keys=["assignee", "labels"], required=["assignee"],
                         issue=issue)
    api.login(admin)
    row = next(x for x in api.get(f"/issues/{issue.key}/transitions").json()
               if x["id"] == t.id)
    assert row["required_fields"] == ["assignee"]
    assert row["screen"]["fields"] == ["assignee", "labels"]
    assert row["screen"]["tabs"][0]["fields"][0] == {"key": "assignee", "required": True,
                                                     "description": ""}
    rules = api.get(f"/projects/{project.key}/field-rules").json()["by_type"]
    tr = next(x for x in rules[str(issue.issue_type_id)]["transitions"] if x["id"] == t.id)
    assert tr["required_fields"] == ["assignee"] and tr["screen"]["id"] == t.screen_id

    r = api.post(f"/issues/{issue.key}/transitions", {"transition_id": t.id})
    assert r.status_code == 422
    assert r.json()["details"]["fields"] == {"assignee": "«Responsable» es obligatorio"}
    r = api.post(f"/issues/{issue.key}/transitions",
                 {"transition_id": t.id, "fields": {"due_date": "2026-12-01"}})
    assert r.status_code == 422 and "pantalla de la transición" in r.json()["message"]
    issue.refresh_from_db()
    assert issue.status_id != t.to_status_id and issue.due_date is None  # atomic

    r = api.post(f"/issues/{issue.key}/transitions", {
        "transition_id": t.id, "fields": {"assignee": member.id, "labels": ["revisado"]}})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["assignee"]["id"] == member.id and body["labels"] == ["revisado"]
    assert body["status"]["id"] == t.to_status_id


def test_transition_required_by_screen_configuration(api, admin, project, make_issue):
    issue = make_issue("Algo")
    _setup(api, admin, project, config=[{"key": "story_points", "required": True}],
           create=_without("story_points"))
    t = _transition_with(project, screen_keys=["story_points"], issue=issue)
    r = api.post(f"/issues/{issue.key}/transitions", {"transition_id": t.id})
    assert r.status_code == 422 and "story_points" in r.json()["details"]["fields"]
    r = api.post(f"/issues/{issue.key}/transitions",
                 {"transition_id": t.id, "fields": {"story_points": 5}})
    assert r.status_code == 200, r.json()


def test_workflow_api_round_trips_transition_screen(api, admin, project):
    api.login(admin)
    screen = Screen.objects.create(name="Resolver")
    wf = api.get(f"/workflows/{project.workflow_id}").json()
    body = {"name": wf["name"], "description": wf["description"],
            "initial_status_id": wf["initial_status_id"],
            "statuses": [{"status_id": s["status"]["id"], "x": s["x"], "y": s["y"]}
                         for s in wf["statuses"]],
            "transitions": [{k: v for k, v in t.items() if k != "id"}
                            for t in wf["transitions"]]}
    body["transitions"][0].update(screen_id=screen.id, required_fields=["assignee"])
    r = api.put(f"/workflows/{wf['id']}", body)
    assert r.status_code == 200, r.json()
    assert r.json()["transitions"][0]["screen_id"] == screen.id
    assert r.json()["transitions"][0]["required_fields"] == ["assignee"]
    body["transitions"][0]["required_fields"] = ["nada"]
    assert api.put(f"/workflows/{wf['id']}", body).status_code == 422
    # a screen used by a transition cannot go to the papelera
    r = api.delete(f"/screens/{screen.id}")
    assert r.status_code == 409 and r.json()["code"] == "in_use"


# ------------------------------------------------------------------ bulk / move

def test_bulk_validates_each_issue(api, admin, project, types, make_issue):
    task, bug = make_issue("Tarea"), make_issue("Bug", type_name="Error")
    _setup(api, admin, project, screens_by_type={
        types["Error"].id: {"edit": _without("story_points")}})
    r = api.post("/issues/bulk", {"issue_ids": [task.id, bug.id],
                                  "changes": {"story_points": 3}})
    assert r.status_code == 200
    assert r.json()["updated"] == [task.key]
    fail = r.json()["failed"][0]
    assert fail["key"] == bug.key and list(fail["fields"]) == ["story_points"]

    t = _transition_with(project, required=["due_date"], issue=task)
    r = api.post("/issues/bulk", {"issue_ids": [task.id], "transition_to_status_id":
                                  t.to_status_id})
    assert r.json()["failed"][0]["fields"] == {"due_date": "«Fecha de vencimiento» es "
                                                           "obligatorio"}


def test_move_requires_target_fields(api, admin, project, types, make_issue):
    from apps.projects.services import create_project

    target = create_project(admin, name="Destino", key="DES")
    issue = make_issue("Mover")
    _setup(api, admin, target, config=[{"key": "due_date", "required": True}])
    r = api.post(f"/issues/{issue.key}/move", {"project": "DES"})
    assert r.status_code == 422
    assert r.json()["message"].startswith(f"{issue.key}: faltan campos obligatorios en DES")
    assert list(r.json()["details"]["fields"]) == ["due_date"]
    issue.refresh_from_db()
    assert issue.project_id == project.id

    r = api.post("/issues/bulk", {"issue_ids": [issue.id], "move": {"project": "DES"}})
    assert r.json()["updated"] == [] and "due_date" in r.json()["failed"][0]["fields"]

    r = api.post(f"/issues/{issue.key}/move", {"project": "DES",
                                               "fields": {"due_date": "2026-12-01"}})
    assert r.status_code == 200, r.json()
    assert r.json()["key"].startswith("DES-") and r.json()["due_date"] == "2026-12-01"


def test_move_fields_only_fill_missing_required(api, admin, member, project, types,
                                                make_issue):
    """`move.fields` is not a way to edit other fields (security review)."""
    from apps.projects.services import create_project

    target = create_project(admin, name="Destino", key="DES")
    _setup(api, admin, target, config=[{"key": "due_date", "required": True}])
    issue = make_issue("Mover", due_date=date(2026, 1, 1))
    # not required in the target → 422 per field, nothing moves
    r = api.post(f"/issues/{issue.key}/move", {"project": "DES",
                                               "fields": {"assignee": member.id}})
    assert r.status_code == 422 and r.json()["code"] == "fields"
    assert "no es un obligatorio del destino" in r.json()["details"]["fields"]["assignee"]
    # required but already filled → 422 too
    r = api.post(f"/issues/{issue.key}/move", {"project": "DES",
                                               "fields": {"due_date": "2030-01-01"}})
    assert r.status_code == 422 and "ya tiene valor" in r.json()["details"]["fields"][
        "due_date"]
    issue.refresh_from_db()
    assert issue.project_id == project.id and issue.due_date == date(2026, 1, 1)
    # the bulk move reports it per issue
    r = api.post("/issues/bulk", {"issue_ids": [issue.id], "move": {
        "project": "DES", "fields": {"labels": ["x"]}}})
    assert r.json()["updated"] == [] and list(r.json()["failed"][0]["fields"]) == ["labels"]
    # bulk: required values only fill the issues that lack them, never overwrite
    empty = make_issue("Sin fecha")
    r = api.post("/issues/bulk", {"issue_ids": [issue.id, empty.id], "move": {
        "project": "DES", "fields": {"due_date": "2030-01-01"}}})
    assert len(r.json()["updated"]) == 2, r.json()
    issue.refresh_from_db()
    empty.refresh_from_db()
    assert issue.due_date == date(2026, 1, 1) and empty.due_date == date(2030, 1, 1)


def test_move_fields_need_edit_permissions_in_target(api, admin, member, project, types,
                                                     make_issue):
    from apps.projects.models import Perm, Role
    from apps.projects.services import create_project, set_member

    target = create_project(admin, name="Destino", key="DES")
    _setup(api, admin, target, config=[{"key": "assignee", "required": True}])
    no_assign = Role.objects.create(name="Sin asignar", permissions=[
        p.value for p in Perm if p not in (Perm.ASSIGN_ISSUES, Perm.ADMINISTER)])
    for p in (project, target):
        set_member(admin, p, member.id, no_assign.id)
    issue = make_issue("Mover", actor=member)
    api.login(member)
    r = api.post(f"/issues/{issue.key}/move", {"project": "DES",
                                               "fields": {"assignee": admin.id}})
    assert r.status_code == 403
    issue.refresh_from_db()
    assert issue.project_id == project.id and issue.assignee_id is None
    r = api.post("/issues/bulk", {"issue_ids": [issue.id], "move": {
        "project": "DES", "fields": {"assignee": admin.id}}})
    assert r.json()["updated"] == [] and r.json()["failed"][0]["key"] == issue.key


def test_transition_screen_assignee_needs_assign_permission(api, admin, member, project,
                                                            make_issue):
    from apps.projects.models import Perm, Role
    from apps.projects.services import set_member

    no_assign = Role.objects.create(name="Sin asignar", permissions=[
        p.value for p in Perm if p not in (Perm.ASSIGN_ISSUES, Perm.ADMINISTER)])
    set_member(admin, project, member.id, no_assign.id)
    issue = make_issue("Algo")
    t = _transition_with(project, screen_keys=["assignee", "labels"], issue=issue)
    api.login(member)
    r = api.post(f"/issues/{issue.key}/transitions",
                 {"transition_id": t.id, "fields": {"assignee": admin.id}})
    assert r.status_code == 403
    issue.refresh_from_db()
    assert issue.assignee_id is None and issue.status_id != t.to_status_id
    r = api.post(f"/issues/{issue.key}/transitions",
                 {"transition_id": t.id, "fields": {"labels": ["ok"]}})
    assert r.status_code == 200 and r.json()["labels"] == ["ok"]


# ------------------------------------------------------------------ forms

def test_form_must_include_required_fields(api, admin, member, project, types):
    _setup(api, admin, project, config=[{"key": "due_date", "required": True}])
    base = {"name": "Solicitudes", "issue_type_id": types["Tarea"].id}
    r = api.post(f"/projects/{project.key}/forms", {**base, "fields": [{"field": "summary"}]})
    assert r.status_code == 422 and r.json()["code"] == "fields"
    assert "due_date" in r.json()["details"]["fields"]
    r = api.post(f"/projects/{project.key}/forms", {**base, "fields": [
        {"field": "summary"}, {"field": "due_date"}]})
    assert r.status_code == 201, r.json()
    form = r.json()
    assert next(f for f in form["fields"] if f["field"] == "due_date")["required"] is True

    # the configuration changes afterwards: submitting says the form is outdated
    _setup(api, admin, project, config=[{"key": "due_date", "required": True},
                                        {"key": "assignee", "required": True}])
    api.login(member)
    r = api.post(f"/f/{form['slug']}", {"values": {"summary": "x", "due_date": "2026-12-01"}})
    assert r.status_code == 422 and r.json()["code"] == "form_outdated"
    assert "Responsable" in r.json()["message"]


def test_form_fields_must_be_on_the_create_screen(api, admin, project, types):
    _setup(api, admin, project, create=_without("priority"))
    r = api.post(f"/projects/{project.key}/forms", {
        "name": "F", "issue_type_id": types["Tarea"].id,
        "fields": [{"field": "summary"}, {"field": "priority"}]})
    assert r.status_code == 422
    assert r.json()["details"]["fields"]["priority"].endswith("pantalla de creación")


# ------------------------------------------------------------------ automation

def test_automation_cannot_skip_field_rules(api, admin, project, types, make_issue,
                                            django_capture_on_commit_callbacks):
    from apps.automation.models import AutomationLog, AutomationRule

    _setup(api, admin, project, edit=_without("priority"))
    AutomationRule.objects.create(project=project, name="Subir prioridad",
                                  trigger="issue_created",
                                  actions=[{"type": "edit", "fields": {"priority": 1}}])
    with django_capture_on_commit_callbacks(execute=True):
        make_issue("Algo")
    log = AutomationLog.objects.get()
    assert log.status == "failure"
    assert log.message == "El campo «Prioridad» no está en la pantalla de edición"


def test_automation_create_subtasks_respects_required(api, admin, project, types, make_issue,
                                                      django_capture_on_commit_callbacks):
    from apps.automation.models import AutomationLog, AutomationRule

    _setup(api, admin, project, by_type={types["Subtarea"].id: [
        {"key": "due_date", "required": True}]})
    AutomationRule.objects.create(project=project, name="Subtareas", trigger="issue_created",
                                  actions=[{"type": "create_subtasks",
                                            "summaries": ["Probar"]}])
    with django_capture_on_commit_callbacks(execute=True):
        make_issue("Historia", type_name="Historia")
    log = AutomationLog.objects.get()
    assert log.status == "failure" and "Fecha de vencimiento" in log.message


# ------------------------------------------------------------------ administration

def test_admin_crud_soft_delete_and_in_use(api, admin, project):
    api.login(admin)
    ids = _setup(api, admin, project)
    # in use by the project → 409; the defaults → 409 is_default
    r = api.delete(f"/field-configuration-schemes/{ids['fcs']}")
    assert r.status_code == 409 and r.json()["code"] == "in_use"
    assert r.json()["details"]["usages"] == [{"count": 1, "label": "proyecto"}]
    assert api.delete(f"/issue-type-screen-schemes/{ids['itss']}").json()["code"] == "in_use"
    assert api.delete(f"/field-configurations/{ids['config']}").json()["code"] == "in_use"
    assert api.delete(f"/screen-schemes/{ids['ss']}").json()["code"] == "in_use"
    default_screen = Screen.objects.get(is_default=True)
    r = api.delete(f"/screens/{default_screen.id}")
    assert r.status_code == 409 and r.json()["code"] == "is_default"
    # hard delete of something still referenced → 409 protected
    r = api.delete(f"/field-configuration-schemes/{ids['fcs']}?permanent=true")
    assert r.status_code == 409 and r.json()["code"] == "protected"

    # back to the defaults: the project's own schemes can go to the papelera and come back
    fcs_default = FieldConfigurationScheme.objects.get(is_default=True)
    itss_default = IssueTypeScreenScheme.objects.get(is_default=True)
    api.put(f"/projects/{project.key}/field-schemes", {
        "field_configuration_scheme_id": fcs_default.id,
        "issue_type_screen_scheme_id": itss_default.id})
    assert api.delete(f"/field-configuration-schemes/{ids['fcs']}").status_code == 204
    assert api.delete(f"/field-configurations/{ids['config']}").status_code == 204
    trash = api.get("/field-configuration-schemes?deleted=true").json()
    assert [s["id"] for s in trash] == [ids["fcs"]] and trash[0]["deleted_at"]
    r = api.post(f"/field-configuration-schemes/{ids['fcs']}/restore")
    assert r.status_code == 409 and r.json()["code"] == "deleted_dependency"
    assert api.post(f"/field-configurations/{ids['config']}/restore").status_code == 200
    assert api.post(f"/field-configuration-schemes/{ids['fcs']}/restore").status_code == 200
    # a deleted scheme cannot be assigned
    api.delete(f"/issue-type-screen-schemes/{ids['itss']}")
    r = api.put(f"/projects/{project.key}/field-schemes",
                {"issue_type_screen_scheme_id": ids["itss"]})
    assert r.status_code == 422
    # names are unique among the alive rows
    r = api.post("/screens", {"name": "Pantalla predeterminada", "tabs": [{"fields": []}]})
    assert r.status_code == 409


def test_default_flag_moves_and_cannot_be_unset(api, admin):
    api.login(admin)
    old = Screen.objects.get(is_default=True)
    r = api.put(f"/screens/{old.id}", {"name": old.name, "is_default": False,
                                       "tabs": [{"name": "General", "fields": ALL}]})
    assert r.status_code == 422 and r.json()["code"] == "is_default"
    r = api.post("/screens", {"name": "Nueva", "is_default": True,
                              "tabs": [{"name": "Uno", "fields": ["summary"]},
                                       {"name": "Dos", "fields": ["description"]}]})
    assert r.status_code == 201, r.json()
    assert [t["name"] for t in r.json()["tabs"]] == ["Uno", "Dos"]
    assert Screen.objects.get(is_default=True).id == r.json()["id"]
    cf = CustomField.objects.create(name="Nuevo", kind="text")
    assert Screen.objects.get(is_default=True).screen_fields.filter(field=f"cf:{cf.id}") \
        .exists()
    r = api.post("/screens", {"name": "Rep", "tabs": [{"fields": ["summary", "summary"]}]})
    assert r.status_code == 422


def test_field_configuration_output_and_warnings(api, admin):
    api.login(admin)
    cf = CustomField.objects.create(name="Cliente", kind="text")
    screen = Screen.objects.get(is_default=True)
    screen.screen_fields.filter(field=f"cf:{cf.id}").delete()
    r = api.post("/field-configurations", {"name": "Estricta", "fields": [
        {"key": f"cf:{cf.id}", "required": True}, {"key": "team", "hidden": True}]})
    assert r.status_code == 201
    out = r.json()
    by_key = {f["key"]: f for f in out["fields"]}
    assert by_key["summary"]["locked"] and by_key["summary"]["required"]
    assert by_key[f"cf:{cf.id}"]["required"] and by_key["team"]["hidden"]
    assert out["warnings"] == [{"field": f"cf:{cf.id}", "message": "«Cliente» es obligatorio "
                                "pero no está en ninguna pantalla: nunca se exigirá"}]
    assert api.post("/field-configurations", {"name": "X", "fields": [
        {"key": "cf:999999", "required": True}]}).status_code == 422


def test_permissions(api, admin, member, project):
    from apps.projects.models import ProjectMember, Role

    lead = ProjectMember.objects.get(project=project, user=admin)
    assert Role.objects.admin_role() == lead.role
    ProjectMember.objects.filter(project=project, user=member).update(role=lead.role)
    api.login(member)  # project admin, not system admin
    for url in ("/field-configurations", "/field-configuration-schemes", "/screens",
                "/screen-schemes", "/issue-type-screen-schemes"):
        assert api.get(url).status_code == 403
        assert api.post(url, {"name": "x"}).status_code in (403, 422)
    assert api.post("/screens", {"name": "x", "tabs": [{"fields": []}]}).status_code == 403
    r = api.put(f"/projects/{project.key}/field-schemes", {"field_configuration_scheme_id": 1})
    assert r.status_code == 403
    out = api.get(f"/projects/{project.key}/field-schemes").json()
    assert out["can_change"] is False and out["field_configuration_scheme"]["name"]
    assert api.get(f"/projects/{project.key}/field-rules").status_code == 200


def test_field_rules_hidden_from_outsiders(api, outsider, project):
    from apps.projects.models import Project

    Project.objects.filter(pk=project.pk).update(access=Project.Access.PRIVATE)
    api.login(outsider)
    assert api.get(f"/projects/{project.key}/field-rules").status_code == 404


# ------------------------------------------------------------------ cache / queries

def test_resolution_queries_are_bounded_and_cached(project, types, admin,
                                                   django_assert_max_num_queries):
    from django.core.cache import cache

    for i in range(15):
        CustomField.objects.create(name=f"Campo {i}", kind="text")
    t = _transition_with(project, screen_keys=["assignee"], required=["due_date"])
    assert t.screen_id
    cache.clear()
    fieldrules._local.clear()
    with django_assert_max_num_queries(16):
        for itype in types.values():
            fieldrules.resolve(project, itype)
    with django_assert_max_num_queries(0):
        rules = fieldrules.resolve(project, types["Tarea"])
    assert len(rules.screens["create"]["fields"]) == len(ALL) + 15


def test_cache_invalidated_by_configuration_changes(project, types):
    assert fieldrules.resolve(project, types["Tarea"]).create_required == ["summary",
                                                                           "issue_type"]
    config = FieldConfiguration.objects.get(is_default=True)
    FieldConfigurationItem.objects.create(configuration=config, field="due_date",
                                          required=True)
    assert "due_date" in fieldrules.resolve(project, types["Tarea"]).create_required
    ss = ScreenScheme.objects.get(is_default=True)
    s = Screen.objects.create(name="Mínima")
    tab = s.tabs.create(name="General")
    s.screen_fields.create(tab=tab, field="summary", position=0)
    ss.create_screen = s
    ss.save()
    rules = fieldrules.resolve(project, types["Tarea"])
    assert rules.screens["create"]["fields"] == ["summary", "issue_type"]
    assert rules.create_required == ["summary", "issue_type"]


def test_create_issue_service_errors_carry_field_keys(project, types, admin):
    config = FieldConfiguration.objects.get(is_default=True)
    FieldConfigurationItem.objects.create(configuration=config, field="team", required=True)
    from apps.core.errors import ValidationFailed

    with pytest.raises(ValidationFailed) as exc:
        create_issue(admin, project, IssueInput(issue_type_id=types["Tarea"].id,
                                                summary="x"))
    assert exc.value.code == "fields" and exc.value.details == {
        "fields": {"team": "«Equipo» es obligatorio"}}
