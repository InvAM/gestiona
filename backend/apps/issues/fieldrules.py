"""Field rules, the Jira (company-managed) way. The single place that knows which fields an
issue type shows on each screen, which ones are required or hidden and their help text, and
the validation every entry point applies (create, quick create, clone, edit, transitions,
bulk, move, forms, automation). The Jira importer is deliberately exempt: it writes through
the ORM and keeps whatever Jira had.

Resolution for (project, issue type):

* project → FieldConfigurationScheme (entry of the type, else its default configuration)
  → FieldConfiguration: required / hidden / description per field.
* project → IssueTypeScreenScheme (entry of the type, else default) → ScreenScheme
  → create / edit / view screen (empty operations use the scheme's default screen).
* Transitions carry their own optional screen and a «campos obligatorios» validator.

Decisions (documented in FASE4.md and the module docstrings that apply them):

* Create: the required fields are the ones required by the configuration that are ON the
  create screen (Jira only enforces what the screen shows); required fields missing from the
  create screen show up as `warnings` for the admin. Values sent for hidden fields or fields
  not on the create screen are rejected (422), like Jira's REST API, except the context of
  where the issue is created (`parent`, `sprint`). Defaults count (default priority, reporter
  = creator, project default assignee).
* Edit: a field that CHANGES must be on the edit screen; a required field cannot be emptied.
* `summary` and `issue_type` are locked: always required, never hidden, always on the
  create / edit screens.

Everything for one project is loaded in a bounded number of queries into a plain "bundle"
that is cached; signals (apps.issues.signals) bump a global version on any change.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q

from apps.core.errors import ValidationFailed

# --------------------------------------------------------------------------- catalog

# (key, label, kind) in the order the issue view shows them today.
SYSTEM_FIELDS: list[tuple[str, str, str]] = [
    ("summary", "Resumen", "text"),
    ("issue_type", "Tipo de incidencia", "issue_type"),
    ("description", "Descripción", "rich_text"),
    ("priority", "Prioridad", "priority"),
    ("assignee", "Responsable", "user"),
    ("reporter", "Informador", "user"),
    ("labels", "Etiquetas", "labels"),
    ("components", "Componentes", "components"),
    ("fix_versions", "Versión de corrección", "versions"),
    ("affects_versions", "Versión afectada", "versions"),
    ("start_date", "Fecha de inicio", "date"),
    ("due_date", "Fecha de vencimiento", "date"),
    ("original_estimate", "Estimación original", "duration"),
    ("remaining_estimate", "Estimación restante", "duration"),
    ("story_points", "Puntos de historia", "number"),
    ("sprint", "Sprint", "sprint"),
    ("parent", "Principal", "issue"),
    ("team", "Equipo", "team"),
    ("flagged", "Marcada", "flag"),
]
SYSTEM_KEYS = [k for k, _, _ in SYSTEM_FIELDS]
SYSTEM_LABELS = {k: label for k, label, _ in SYSTEM_FIELDS}
SYSTEM_KINDS = {k: kind for k, _, kind in SYSTEM_FIELDS}
# Always required, never hidden, always on the create / edit screens (like Jira).
LOCKED = ("summary", "issue_type")
# Set by where the issue is created (sub-task of…, inside a sprint): accepted on create even
# when the field is not on the create screen.
CONTEXT_FIELDS = frozenset({"parent", "sprint"})
OPERATIONS = ("create", "edit", "view")
OPERATION_LABELS = {"create": "Crear incidencia", "edit": "Editar incidencia",
                    "view": "Ver incidencia"}
OPTION_KINDS = ("select", "multiselect", "checkbox")
ALL_SCREEN_NAME = "Todos los campos"


def is_custom(key: str) -> bool:
    return key.startswith("cf:") and key[3:].isdigit()


def is_known_key(key: str) -> bool:
    """System key or an existing (alive) custom field."""
    from .models import CustomField

    if key in SYSTEM_LABELS:
        return True
    return is_custom(key) and CustomField.objects.filter(pk=int(key[3:])).exists()


def system_field_out(key: str) -> dict:
    return {"key": key, "label": SYSTEM_LABELS[key], "kind": SYSTEM_KINDS[key], "system": True,
            "custom_field_id": None, "locked": key in LOCKED, "has_options": False,
            "options": [], "description": ""}


def custom_field_out(cf: dict) -> dict:
    return {"key": f"cf:{cf['id']}", "label": cf["name"], "kind": cf["kind"], "system": False,
            "custom_field_id": cf["id"], "locked": False,
            "has_options": cf["kind"] in OPTION_KINDS, "options": cf["options"] or [],
            "description": cf["description"] or ""}


def catalog(custom_fields: Iterable | None = None) -> list[dict]:
    """Every field: system ones first (fixed order), then the alive custom fields."""
    from .models import CustomField

    if custom_fields is None:
        custom_fields = CustomField.objects.all()
    out = [system_field_out(k) for k in SYSTEM_KEYS]
    for c in custom_fields:
        out.append(custom_field_out({"id": c.id, "name": c.name, "kind": c.kind,
                                     "options": c.options, "description": c.description}))
    return out


def labels_for(keys: Iterable[str]) -> dict[str, str]:
    """Labels of any keys (custom fields looked up in one query, deleted ones included)."""
    from .models import CustomField

    keys = list(keys)
    ids = [int(k[3:]) for k in keys if is_custom(k)]
    names = dict(CustomField.all_objects.filter(id__in=ids).values_list("id", "name")) \
        if ids else {}
    return {k: SYSTEM_LABELS.get(k) or names.get(int(k[3:]) if is_custom(k) else -1) or k
            for k in keys}


# --------------------------------------------------------------------------- cache

VERSION_KEY = "fieldrules:version"
BUNDLE_TTL = 3600
_local: dict[tuple[int, int], dict] = {}


def _version() -> int:
    v = cache.get(VERSION_KEY)
    if v is None:
        # a fresh, ever-increasing base so an evicted version key never revives old bundles
        cache.add(VERSION_KEY, int(time.time() * 1000), None)
        v = cache.get(VERSION_KEY) or 0
    return int(v)


def _bump() -> None:
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        cache.set(VERSION_KEY, int(time.time() * 1000), None)
    _local.clear()


def invalidate() -> None:
    """Called on every change that affects the rules: now (the same transaction sees the
    change) and after commit (nobody keeps a bundle built from uncommitted data)."""
    _bump()
    transaction.on_commit(_bump)


def bundle(project) -> dict:
    v = _version()
    key = (v, project.id)
    b = _local.get(key)
    if b is not None:
        return b
    ck = f"fieldrules:{v}:{project.id}"
    b = cache.get(ck)
    if b is None:
        b = _load_bundle(project)
        cache.set(ck, b, BUNDLE_TTL)
    if len(_local) > 256:
        _local.clear()
    b["_rules"] = {}
    _local[key] = b
    return b


def _load_bundle(project) -> dict:
    """Everything the rules of `project` need, as plain data, in a bounded number of
    queries (independent of the number of fields, types, screens or transitions)."""
    from apps.workflows.models import Transition, WorkflowMapping

    from .models import (
        CustomField,
        FieldConfiguration,
        FieldConfigurationItem,
        FieldConfigurationScheme,
        FieldConfigurationSchemeEntry,
        IssueTypeScreenScheme,
        IssueTypeScreenSchemeEntry,
        Screen,
        ScreenField,
        ScreenScheme,
        ScreenTab,
    )

    # ---- field configuration
    fcs = None
    if project.field_configuration_scheme_id:
        fcs = FieldConfigurationScheme.all_objects.filter(
            pk=project.field_configuration_scheme_id).values(
            "id", "name", "default_configuration_id").first()
    if fcs is None:
        fcs = FieldConfigurationScheme.objects.filter(is_default=True).values(
            "id", "name", "default_configuration_id").first()
    fc_by_type: dict[int, int] = {}
    config_ids: set[int] = set()
    if fcs:
        fc_by_type = dict(FieldConfigurationSchemeEntry.objects.filter(scheme_id=fcs["id"])
                          .values_list("issue_type_id", "configuration_id"))
        config_ids = {fcs["default_configuration_id"], *fc_by_type.values()}
    configs = {c["id"]: {**c, "items": {}} for c in FieldConfiguration.all_objects.filter(
        id__in=config_ids).values("id", "name")}
    for it in FieldConfigurationItem.objects.filter(configuration_id__in=config_ids).values(
            "configuration_id", "field", "required", "hidden", "description"):
        configs[it["configuration_id"]]["items"][it["field"]] = {
            "required": it["required"], "hidden": it["hidden"],
            "description": it["description"]}

    # ---- screens
    itss = None
    if project.issue_type_screen_scheme_id:
        itss = IssueTypeScreenScheme.all_objects.filter(
            pk=project.issue_type_screen_scheme_id).values(
            "id", "name", "default_screen_scheme_id").first()
    if itss is None:
        itss = IssueTypeScreenScheme.objects.filter(is_default=True).values(
            "id", "name", "default_screen_scheme_id").first()
    ss_by_type: dict[int, int] = {}
    ss_ids: set[int] = set()
    if itss:
        ss_by_type = dict(IssueTypeScreenSchemeEntry.objects.filter(scheme_id=itss["id"])
                          .values_list("issue_type_id", "screen_scheme_id"))
        ss_ids = {itss["default_screen_scheme_id"], *ss_by_type.values()}
    screen_schemes = {s["id"]: s for s in ScreenScheme.all_objects.filter(id__in=ss_ids).values(
        "id", "name", "default_screen_id", "create_screen_id", "edit_screen_id",
        "view_screen_id")}
    screen_ids = {sid for s in screen_schemes.values()
                  for sid in (s["default_screen_id"], s["create_screen_id"], s["edit_screen_id"],
                              s["view_screen_id"]) if sid}

    # ---- workflows / transitions (screens and validators)
    wf_by_type = dict(WorkflowMapping.objects.filter(project_id=project.id)
                      .values_list("issue_type_id", "workflow_id"))
    wf_ids = {project.workflow_id, *wf_by_type.values()}
    transitions: dict[int, list[dict]] = {}
    for t in Transition.objects.filter(workflow_id__in=wf_ids).order_by("position", "id").values(
            "id", "name", "workflow_id", "to_status_id", "screen_id", "required_fields"):
        transitions.setdefault(t["workflow_id"], []).append(t)
        if t["screen_id"]:
            screen_ids.add(t["screen_id"])

    screens = {s["id"]: {**s, "tabs": []} for s in Screen.all_objects.filter(
        id__in=screen_ids).values("id", "name")}
    tabs: dict[int, dict] = {}
    for t in ScreenTab.objects.filter(screen_id__in=screen_ids).order_by("position", "id") \
            .values("id", "name", "screen_id"):
        tab = {"id": t["id"], "name": t["name"], "fields": []}
        tabs[t["id"]] = tab
        screens[t["screen_id"]]["tabs"].append(tab)
    for f in ScreenField.objects.filter(screen_id__in=screen_ids).order_by("position", "id") \
            .values("tab_id", "field"):
        if f["tab_id"] in tabs:
            tabs[f["tab_id"]]["fields"].append(f["field"])

    # ---- custom fields that apply to the project (contexts)
    custom: dict[str, dict] = {}
    for c in CustomField.objects.filter(Q(projects__isnull=True) | Q(projects=project.id)) \
            .distinct().order_by("position", "id").values(
            "id", "name", "kind", "description", "options"):
        custom[f"cf:{c['id']}"] = {**c, "type_ids": None}
    if custom:
        through = CustomField.issue_types.through
        for cid, tid in through.objects.filter(
                customfield_id__in=[c["id"] for c in custom.values()]).values_list(
                "customfield_id", "issuetype_id"):
            c = custom[f"cf:{cid}"]
            c["type_ids"] = [*(c["type_ids"] or []), tid]

    return {
        "fcs": {"id": fcs["id"], "name": fcs["name"]} if fcs else None,
        "fc_default": fcs["default_configuration_id"] if fcs else None,
        "fc_by_type": fc_by_type, "configs": configs,
        "itss": {"id": itss["id"], "name": itss["name"]} if itss else None,
        "ss_default": itss["default_screen_scheme_id"] if itss else None,
        "ss_by_type": ss_by_type, "screen_schemes": screen_schemes, "screens": screens,
        "wf_default": project.workflow_id, "wf_by_type": wf_by_type,
        "transitions": transitions, "custom": custom,
    }


# --------------------------------------------------------------------------- rules

@dataclass
class Rules:
    issue_type_id: int
    fields: dict[str, dict]  # applicable catalog entries, in catalog order
    config: dict[str, dict]  # key → {required, hidden, description} (every applicable key)
    required: list[str]
    hidden: list[str]
    descriptions: dict[str, str]
    screens: dict[str, dict]  # operation → resolved screen
    field_configuration: dict | None
    screen_scheme: dict | None
    transitions: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    _bundle: dict | None = None

    def on(self, operation: str) -> set[str]:
        return set(self.screens[operation]["fields"])

    @property
    def create_required(self) -> list[str]:
        on = self.on("create")
        return [k for k in self.required if k in on]

    def label(self, key: str) -> str:
        f = self.fields.get(key)
        if f:
            return f["label"]
        return labels_for([key])[key]

    def applies(self, key: str) -> bool:
        return key in self.fields

    def transition(self, transition) -> dict:
        """{screen: Screen|None, required_fields: [keys]} for a Transition (model or dict)."""
        get = transition.get if isinstance(transition, dict) else \
            (lambda k: getattr(transition, k))
        screen_id, validator = get("screen_id"), list(get("required_fields") or [])
        validator = [k for k in validator if k in self.fields]  # hidden ones still count
        screen = None
        if screen_id:
            screen = _screen_out(self._bundle, screen_id, self, force_locked=False,
                                 extra_required=set(validator))
        return {"screen": screen, "required_fields": validator}

    def as_dict(self) -> dict:
        return {
            "field_configuration": self.field_configuration,
            "screen_scheme": self.screen_scheme,
            "screens": self.screens,
            "required": list(self.required),
            "create_required": self.create_required,
            "hidden": list(self.hidden),
            "descriptions": dict(self.descriptions),
            "config": self.config,
            "transitions": self.transitions,
            "warnings": self.warnings,
        }


def _applicable(b: dict, issue_type) -> dict[str, dict]:
    from .models import IssueType

    out: dict[str, dict] = {}
    for key in SYSTEM_KEYS:
        if key == "parent" and issue_type.level == IssueType.Level.EPIC:
            continue  # an epic never has a parent
        if key == "sprint" and issue_type.level == IssueType.Level.SUBTASK:
            continue  # sub-tasks follow their parent's sprint
        out[key] = system_field_out(key)
    for key, c in b["custom"].items():
        if c["type_ids"] is None or issue_type.id in c["type_ids"]:
            out[key] = custom_field_out(c)
    return out


def _screen_out(b: dict, screen_id: int | None, rules: Rules, *, force_locked: bool,
                extra_required: set[str] = frozenset()) -> dict:
    hidden = set(rules.hidden)
    required = set(rules.required) | set(extra_required)

    def ref(k):
        return {"key": k, "required": k in required,
                "description": rules.descriptions.get(k, "")}

    s = b["screens"].get(screen_id) if screen_id else None
    if s is None:  # no screen configuration at all: every field (legacy behaviour)
        keys = [k for k in rules.fields if k not in hidden]
        tabs = [{"id": None, "name": "General", "fields": [ref(k) for k in keys]}]
        return {"id": None, "name": ALL_SCREEN_NAME, "tabs": tabs, "fields": keys}
    tabs, seen = [], set()
    for t in s["tabs"]:
        keys = [k for k in t["fields"] if k in rules.fields and k not in hidden and k not in seen]
        seen.update(keys)
        tabs.append({"id": t["id"], "name": t["name"], "fields": [ref(k) for k in keys]})
    if force_locked:
        for key in (k for k in LOCKED if k not in seen):
            if not tabs:
                tabs.append({"id": None, "name": "General", "fields": []})
            if key == "summary":
                tabs[0]["fields"].insert(0, ref(key))
                continue
            first = tabs[0]["fields"]  # issue type: right after the summary
            at = next((i + 1 for i, f in enumerate(first) if f["key"] == "summary"), 0)
            first.insert(at, ref(key))
    if len(tabs) > 1:
        tabs = [t for t in tabs if t["fields"]] or tabs[:1]
    return {"id": s["id"], "name": s["name"], "tabs": tabs,
            "fields": [f["key"] for t in tabs for f in t["fields"]]}


def _compute(b: dict, issue_type) -> Rules:
    fields = _applicable(b, issue_type)
    cfg_id = b["fc_by_type"].get(issue_type.id) or b["fc_default"]
    cfg = b["configs"].get(cfg_id)
    items = cfg["items"] if cfg else {}
    config, required, hidden, descriptions = {}, [], [], {}
    for key in fields:
        it = items.get(key) or {}
        req = key in LOCKED or bool(it.get("required"))
        hid = key not in LOCKED and bool(it.get("hidden")) and not req
        desc = it.get("description") or ""
        config[key] = {"required": req, "hidden": hid, "description": desc}
        if req:
            required.append(key)
        if hid:
            hidden.append(key)
        if desc:
            descriptions[key] = desc
    ss_id = b["ss_by_type"].get(issue_type.id) or b["ss_default"]
    ss = b["screen_schemes"].get(ss_id)
    rules = Rules(
        issue_type_id=issue_type.id, fields=fields, config=config, required=required,
        hidden=hidden, descriptions=descriptions, screens={},
        field_configuration={"id": cfg["id"], "name": cfg["name"]} if cfg else None,
        screen_scheme={"id": ss["id"], "name": ss["name"]} if ss else None, _bundle=b,
    )
    for op in OPERATIONS:
        sid = (ss.get(f"{op}_screen_id") or ss["default_screen_id"]) if ss else None
        rules.screens[op] = _screen_out(b, sid, rules, force_locked=op != "view")

    wf_id = b["wf_by_type"].get(issue_type.id) or b["wf_default"]
    for t in b["transitions"].get(wf_id, []):
        tr = rules.transition(t)
        rules.transitions.append({"id": t["id"], "name": t["name"],
                                  "to_status_id": t["to_status_id"], **tr})

    # admin hints
    on_create = rules.on("create")
    for key in required:
        if key not in on_create:
            rules.warnings.append({"field": key, "message": (
                f"«{fields[key]['label']}» es obligatorio pero no está en la pantalla de "
                "creación: no se exigirá al crear")})
    for t in rules.transitions:
        for key in t["required_fields"]:
            if key in hidden:
                rules.warnings.append({"field": key, "message": (
                    f"La transición «{t['name']}» exige «{rules.label(key)}», que está oculto: "
                    "no se podrá completar")})
    return rules


def resolve(project, issue_type) -> Rules:
    """Rules of `issue_type` in `project` (cached; see module docstring)."""
    b = bundle(project)
    memo = b["_rules"]
    r = memo.get(issue_type.id)
    if r is None:
        r = memo[issue_type.id] = _compute(b, issue_type)
    return r


def project_rules(project, issue_types) -> dict:
    """GET /projects/{key}/field-rules."""
    b = bundle(project)
    fields: dict[str, dict] = {}
    by_type = {}
    for t in issue_types:
        r = resolve(project, t)
        for k, f in r.fields.items():
            fields.setdefault(k, f)
        by_type[str(t.id)] = r.as_dict()
    ordered = [fields[k] for k in SYSTEM_KEYS if k in fields] + \
        [f for k, f in fields.items() if k not in SYSTEM_LABELS]
    return {"field_configuration_scheme": b["fcs"], "issue_type_screen_scheme": b["itss"],
            "fields": ordered, "by_type": by_type}


# --------------------------------------------------------------------------- values

def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value is False
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, dict) and value.get("type") == "doc":
        from apps.core.richtext import to_text

        return not to_text(value).strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


M2M_KEYS = ("components", "fix_versions", "affects_versions")
FK_KEYS = ("issue_type", "priority", "assignee", "reporter", "parent", "sprint", "team")


def issue_value(issue, key: str, m2m: dict | None = None) -> Any:
    """Current value of a field key on an issue (ids for relations)."""
    if is_custom(key):
        return (issue.custom_fields or {}).get(key[3:])
    if key in FK_KEYS:
        return getattr(issue, f"{key}_id")
    if key in M2M_KEYS:
        if m2m and key in m2m:
            return [o.pk for o in m2m[key]]
        if issue.pk is None:
            return []
        return list(getattr(issue, key).values_list("id", flat=True))
    return getattr(issue, key, None)


def normalize(values: dict | None) -> dict[str, Any]:
    """PATCH-format values ({"assignee": 3, "custom_fields": {"12": "x"}}, or "cf:12": "x")
    → {field key: value}."""
    out: dict[str, Any] = {}
    for k, v in (values or {}).items():
        if k == "custom_fields":
            for cid, cv in (v or {}).items():
                out[f"cf:{cid}"] = cv
        else:
            out[k] = v
    return out


def to_patch(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in values.items():
        if is_custom(k):
            out.setdefault("custom_fields", {})[k[3:]] = v
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- validation

class FieldErrors:
    """Collects per-field errors → one 422 {code: "fields", details: {fields: {key: msg}}}."""

    def __init__(self, rules: Rules | None = None):
        self.rules = rules
        self.errors: dict[str, str] = {}
        self.missing: list[str] = []

    def label(self, key: str) -> str:
        return self.rules.label(key) if self.rules else labels_for([key])[key]

    def add(self, key: str, message: str) -> None:
        self.errors.setdefault(key, message)

    def required(self, key: str) -> None:
        if key not in self.errors:
            self.missing.append(key)
            self.errors[key] = f"«{self.label(key)}» es obligatorio"

    def message(self, prefix: str = "") -> str:
        msgs = list(self.errors.values())
        if self.missing and len(self.missing) == len(msgs) and len(msgs) > 1:
            text = "Faltan campos obligatorios: " + ", ".join(
                f"«{self.label(k)}»" for k in self.missing)
        else:
            text = "; ".join(msgs)
        return f"{prefix}{text}"

    def raise_if_any(self, prefix: str = "") -> None:
        if self.errors:
            raise ValidationFailed(self.message(prefix), code="fields",
                                   details={"fields": dict(self.errors)})


def _not_settable(rules: Rules, key: str, where: str) -> str:
    label = rules.label(key)
    if key in rules.hidden:
        return f"El campo «{label}» está oculto para este tipo de incidencia"
    if not rules.applies(key):
        return f"El campo «{label}» no se usa en este tipo de incidencia"
    return f"El campo «{label}» no está en la pantalla de {where}"


def check_create(project, issue_type, *, provided: dict[str, Any], effective: dict[str, Any],
                 mode: str = "create") -> None:
    """`provided`: what the caller sent (field key → raw value); `effective`: the values
    the issue will get, defaults applied. `mode`: create | form | clone."""
    rules = resolve(project, issue_type)
    errs = FieldErrors(rules)
    if mode != "clone":  # a clone copies every value, on screen or not (like Jira)
        exempt = set(CONTEXT_FIELDS) | set(LOCKED)
        if mode == "form":
            exempt.add("reporter")  # forms file on behalf of the submitter
        on = rules.on("create")
        for key, value in provided.items():
            if key in exempt or is_empty(value) or key in on:
                continue
            errs.add(key, _not_settable(rules, key, "creación"))
    for key in rules.create_required:
        if is_empty(effective.get(key)):
            errs.required(key)
    errs.raise_if_any()


def check_edit(issue, rules: Rules, *, changed: Iterable[str], value, assign_only: bool,
               type_changed: bool) -> None:
    """`changed`: keys whose value changes; `value(key)`: the value after the change."""
    errs = FieldErrors(rules)
    on = rules.on("edit")
    required = set(rules.required)
    for key in changed:
        if assign_only and key == "assignee":
            # the Assign operation does not need the edit screen (Jira), but not if hidden
            if key in rules.hidden:
                errs.add(key, _not_settable(rules, key, "edición"))
        elif key not in on:
            errs.add(key, _not_settable(rules, key, "edición"))
            continue
        if key in required and is_empty(value(key)):
            errs.required(key)
    if type_changed:
        for key in rules.required:
            if key in on and is_empty(value(key)):
                errs.required(key)
    errs.raise_if_any()


def check_transition(issue, rules: Rules, transition, values: dict[str, Any]) -> None:
    """Values sent with the transition must be on its screen; required = configuration
    required fields on that screen + the transition's validator fields."""
    tr = rules.transition(transition)
    screen = tr["screen"]
    on = set(screen["fields"]) if screen else set()
    errs = FieldErrors(rules)
    for key in values:
        if key not in on:
            label = rules.label(key)
            errs.add(key, f"El campo «{label}» no está en la pantalla de la transición "
                          f"«{transition.name}»" if screen else
                     f"La transición «{transition.name}» no tiene pantalla: no admite «{label}»")
    errs.raise_if_any()
    needed = [k for k in rules.required if k in on]
    needed += [k for k in tr["required_fields"] if k not in needed]
    for key in needed:
        v = values[key] if key in values else issue_value(issue, key)
        if is_empty(v):
            errs.required(key)
    errs.raise_if_any()


def check_move(issue_key: str, rules: Rules, target, issue_type, *, value) -> None:
    """The issue entering `target` must satisfy its create rules (`value(key)` = value it
    will have there, payload values included)."""
    errs = FieldErrors(rules)
    for key in rules.create_required:
        if is_empty(value(key)):
            errs.required(key)
    if errs.errors:
        names = ", ".join(f"«{errs.label(k)}»" for k in errs.errors)
        raise ValidationFailed(
            f"{issue_key}: faltan campos obligatorios en {target.key} ({issue_type.name}): "
            f"{names}. Indícalos en «fields» al mover", code="fields",
            details={"fields": dict(errs.errors)})


def movable_values(rules: Rules, values: dict[str, Any], *, current, mode: str = "strict"
                   ) -> dict[str, Any]:
    """Payload values of a move. Only fields the target REQUIRES on create and that are
    EMPTY on the moved issue (`current(key)`) are applied: a move never edits other fields
    nor overwrites a value. `mode`:
    * "strict" (one issue): any other key → 422 per field;
    * "fill" (bulk move, like Jira's wizard): keys the target does not require → 422; a
      required key the issue already has is left as is (only empty ones are filled);
    * "lenient" (sub-tasks travelling with their parent): everything else is dropped."""
    needed = {k for k in rules.create_required if k not in LOCKED and is_empty(current(k))}
    errs = FieldErrors(rules)
    out = {}
    for k, v in values.items():
        if k in needed:
            out[k] = v
        elif mode == "lenient" or (mode == "fill" and k in rules.create_required):
            continue
        else:
            label = rules.label(k)
            errs.add(k, f"«{label}» ya tiene valor; al mover solo se completan los "
                        "obligatorios que faltan en el destino"
                     if k in rules.create_required else
                     f"«{label}» no es un obligatorio del destino; al mover solo se completan "
                     "los obligatorios que faltan")
    errs.raise_if_any()
    return out


# --------------------------------------------------------------------------- forms

FORM_FIELDS = ("summary", "description", "priority", "due_date", "labels", "components")


def form_problems(project, issue_type, fields: list[dict], default_labels=()) -> FieldErrors:
    """A form must ask every field required on create, and only fields on the create
    screen (Jira: request type fields come from the create screen)."""
    rules = resolve(project, issue_type)
    errs = FieldErrors(rules)
    on = rules.on("create")
    keys = [f["field"] for f in fields]
    for key in keys:
        if key not in on and key not in LOCKED:
            errs.add(key, _not_settable(rules, key, "creación"))
    if default_labels and "labels" not in on:
        errs.add("labels", "Las etiquetas por defecto necesitan el campo «Etiquetas» en la "
                           "pantalla de creación")
    for key in rules.create_required:
        if key == "issue_type" or key in keys:
            continue
        if key not in FORM_FIELDS and not is_custom(key):
            errs.add(key, f"«{rules.label(key)}» es obligatorio y no se puede pedir en un "
                          "formulario")
        else:
            errs.add(key, f"Falta el campo obligatorio «{rules.label(key)}»")
    return errs


# --------------------------------------------------------------------------- custom fields

def default_configuration():
    from .models import FieldConfiguration

    return FieldConfiguration.objects.filter(is_default=True).first()


def required_in(configuration_id: int | None, keys: Iterable[str]) -> set[str]:
    from .models import FieldConfigurationItem

    if not configuration_id:
        return set()
    return set(FieldConfigurationItem.objects.filter(
        configuration_id=configuration_id, field__in=list(keys), required=True)
        .values_list("field", flat=True))


def set_required_in_default(cf, required: bool) -> None:
    """Compatibility of /custom-fields `required`: the default field configuration."""
    from .models import FieldConfigurationItem

    config = default_configuration()
    if config is None:
        return
    key = f"cf:{cf.id}"
    item = FieldConfigurationItem.objects.filter(configuration=config, field=key).first()
    if item is None:
        if required:
            FieldConfigurationItem.objects.create(configuration=config, field=key,
                                                  custom_field=cf, required=True)
        return
    if item.required != required:
        item.required = required
        if required:
            item.hidden = False
        item.save(update_fields=["required", "hidden"])


def add_to_default_screen(cf) -> None:
    """New custom fields go to the end of the default screen (like Jira)."""
    from django.db.models import Max

    from .models import Screen, ScreenField, ScreenTab

    screen = Screen.objects.filter(is_default=True).first()
    if screen is None:
        return
    key = f"cf:{cf.id}"
    if ScreenField.objects.filter(screen=screen, field=key).exists():
        return
    tab = screen.tabs.order_by("position", "id").first() or \
        ScreenTab.objects.create(screen=screen, name="General", position=0)
    last = ScreenField.objects.filter(screen=screen).aggregate(m=Max("position"))["m"]
    ScreenField.objects.create(screen=screen, tab=tab, field=key, custom_field=cf,
                               position=(last or 0) + 1)
