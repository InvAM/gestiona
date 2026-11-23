"""Field configurations and screens (Jira company-managed), see apps/issues/fieldrules.py.

* ``GET /fields``                               catalog (system + custom fields)
* ``/field-configurations``                     required / hidden / description per field
* ``/field-configuration-schemes``              configuration per issue type (+ default)
* ``/screens``                                  ordered fields in tabs
* ``/screen-schemes``                           screen for create / edit / view (+ default)
* ``/issue-type-screen-schemes``                screen scheme per issue type (+ default)
* ``GET|PUT /projects/{key}/field-schemes``     the project's schemes (PUT: system admin)
* ``GET /projects/{key}/field-rules``           everything resolved for the UI

Administration is for system admins and follows the soft delete contract of
apps/core/softdelete.py (409 ``in_use`` / ``is_default`` / ``protected``, restore, papelera).
"""

from django.db import IntegrityError, transaction
from django.db.models import Q
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Conflict, NotFound, ValidationFailed
from apps.core.schemas import IssueTypeOut, NamedRef, type_ref
from apps.projects.models import Perm, Project
from apps.projects.permissions import has_perm, require

from . import fieldrules
from .models import (
    CustomField,
    FieldConfiguration,
    FieldConfigurationItem,
    FieldConfigurationScheme,
    FieldConfigurationSchemeEntry,
    IssueType,
    IssueTypeScreenScheme,
    IssueTypeScreenSchemeEntry,
    Screen,
    ScreenField,
    ScreenScheme,
    ScreenTab,
)

router = Router(tags=["fields"])


# ------------------------------------------------------------------ schemas

class FieldCatalogOut(Schema):
    key: str
    label: str
    kind: str
    system: bool
    custom_field_id: int | None = None
    locked: bool = False
    has_options: bool = False
    options: list[dict] = []
    description: str = ""


class FieldSettingIn(Schema):
    key: str
    required: bool = False
    hidden: bool = False
    description: str = ""


class FieldSettingOut(Schema):
    key: str
    label: str
    kind: str
    system: bool
    locked: bool
    required: bool
    hidden: bool
    description: str


class FieldWarningOut(Schema):
    field: str
    message: str


class FieldConfigurationIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False
    fields: list[FieldSettingIn] = []


class FieldConfigurationOut(Schema):
    id: int
    name: str
    description: str
    is_default: bool
    fields: list[FieldSettingOut]
    schemes: list[NamedRef]
    warnings: list[FieldWarningOut]
    deleted_at: str | None = None


class FcsEntryIn(Schema):
    issue_type_id: int
    configuration_id: int


class FcsEntryOut(Schema):
    issue_type: IssueTypeOut
    configuration: NamedRef


class SchemeProjectRef(Schema):
    id: int
    key: str
    name: str


class FieldConfigurationSchemeIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False
    default_configuration_id: int
    entries: list[FcsEntryIn] = []


class FieldConfigurationSchemeOut(Schema):
    id: int
    name: str
    description: str
    is_default: bool
    default_configuration: NamedRef
    entries: list[FcsEntryOut]
    projects: list[SchemeProjectRef]
    deleted_at: str | None = None


class ScreenTabIn(Schema):
    name: str = ""
    fields: list[str] = []


class ScreenIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False
    tabs: list[ScreenTabIn]


class ScreenFieldRef(Schema):
    key: str
    label: str
    kind: str
    system: bool


class ScreenTabOut(Schema):
    id: int
    name: str
    fields: list[ScreenFieldRef]


class ScreenTransitionRef(Schema):
    workflow_id: int
    workflow_name: str
    transition_id: int
    transition_name: str


class ScreenOut(Schema):
    id: int
    name: str
    description: str
    is_default: bool
    tabs: list[ScreenTabOut]
    screen_schemes: list[NamedRef]
    transitions: list[ScreenTransitionRef]
    deleted_at: str | None = None


class ScreenSchemeIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False
    default_screen_id: int
    create_screen_id: int | None = None
    edit_screen_id: int | None = None
    view_screen_id: int | None = None


class ScreenSchemeOut(Schema):
    id: int
    name: str
    description: str
    is_default: bool
    default_screen: NamedRef
    create_screen: NamedRef | None = None
    edit_screen: NamedRef | None = None
    view_screen: NamedRef | None = None
    issue_type_screen_schemes: list[NamedRef]
    deleted_at: str | None = None


class ItssEntryIn(Schema):
    issue_type_id: int
    screen_scheme_id: int


class ItssEntryOut(Schema):
    issue_type: IssueTypeOut
    screen_scheme: NamedRef


class IssueTypeScreenSchemeIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False
    default_screen_scheme_id: int
    entries: list[ItssEntryIn] = []


class IssueTypeScreenSchemeOut(Schema):
    id: int
    name: str
    description: str
    is_default: bool
    default_screen_scheme: NamedRef
    entries: list[ItssEntryOut]
    projects: list[SchemeProjectRef]
    deleted_at: str | None = None


class ProjectFieldSchemesIn(Schema):
    field_configuration_scheme_id: int | None = None
    issue_type_screen_scheme_id: int | None = None


class ProjectFieldSchemesOut(Schema):
    field_configuration_scheme: NamedRef | None
    issue_type_screen_scheme: NamedRef | None
    can_change: bool


class RulesScreenField(Schema):
    key: str
    required: bool
    description: str = ""


class RulesScreenTab(Schema):
    id: int | None
    name: str
    fields: list[RulesScreenField]


class RulesScreen(Schema):
    id: int | None
    name: str
    tabs: list[RulesScreenTab]
    fields: list[str]


class RulesFieldConfig(Schema):
    required: bool
    hidden: bool
    description: str = ""


class RulesTransition(Schema):
    id: int
    name: str
    to_status_id: int
    screen: RulesScreen | None
    required_fields: list[str]


class RulesForType(Schema):
    field_configuration: NamedRef | None
    screen_scheme: NamedRef | None
    screens: dict[str, RulesScreen]
    required: list[str]
    create_required: list[str]
    hidden: list[str]
    descriptions: dict[str, str]
    config: dict[str, RulesFieldConfig]
    transitions: list[RulesTransition]
    warnings: list[FieldWarningOut]


class ProjectFieldRulesOut(Schema):
    field_configuration_scheme: NamedRef | None
    issue_type_screen_scheme: NamedRef | None
    fields: list[FieldCatalogOut]
    by_type: dict[str, RulesForType]


# ------------------------------------------------------------------ helpers

def _admin(user) -> None:
    softdelete.require_system_admin(user, "Solo los administradores pueden configurar campos "
                                          "y pantallas")


def _ref(obj) -> dict | None:
    return {"id": obj.id, "name": obj.name} if obj else None


def _name(value: str) -> str:
    name = (value or "").strip()[:120]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    return name


def _save(obj, message: str) -> None:
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as e:
        raise Conflict(message, code="name") from e


def _apply_default(model, obj, value: bool, label: str) -> None:
    """`is_default: true` takes the flag from the previous default; unmarking the default
    is refused (pick another one instead), like priorities and resolutions."""
    if value:
        model.objects.filter(is_default=True).exclude(pk=obj.pk).update(is_default=False)
        obj.is_default = True
    elif obj.is_default and obj.pk:
        raise ValidationFailed(f"Marca otro elemento como {label} en lugar de desmarcar este",
                               code="is_default")


def _alive(model, pk: int | None, message: str):
    obj = model.objects.filter(pk=pk).first() if pk else None
    if obj is None:
        raise ValidationFailed(message)
    return obj


def _get(model, pk: int, message: str, *, permanent: bool = False):
    obj = (model.all_objects if permanent else model.objects).filter(pk=pk).first()
    if obj is None:
        raise NotFound(message)
    return obj


def _check_key(key: str) -> None:
    if not fieldrules.is_known_key(key):
        raise ValidationFailed(f"Campo desconocido: {key}", code="fields")


def _ensure_not_default(obj, message: str) -> None:
    if obj.is_default and obj.deleted_at is None:
        raise Conflict(message, code="is_default")


def _project_refs(qs) -> list[dict]:
    return [{"id": p.id, "key": p.key, "name": p.name} for p in qs.order_by("key")]


# ------------------------------------------------------------------ catalog

@router.get("/fields", response=list[FieldCatalogOut])
def field_catalog(request):
    """Every field with its key, label and kind (custom fields: the alive ones)."""
    return fieldrules.catalog()


# ------------------------------------------------------------------ field configurations

def _fc_out(c: FieldConfiguration, *, screen_keys: set[str] | None = None) -> dict:
    items = {i.field: i for i in c.items.all()}
    fields = []
    for f in fieldrules.catalog():
        it = items.get(f["key"])
        locked = f["locked"]
        fields.append({
            "key": f["key"], "label": f["label"], "kind": f["kind"], "system": f["system"],
            "locked": locked, "required": locked or bool(it and it.required),
            "hidden": bool(it and it.hidden) and not locked,
            "description": it.description if it else "",
        })
    if screen_keys is None:
        screen_keys = set(ScreenField.objects.filter(screen__deleted_at__isnull=True)
                          .values_list("field", flat=True))
    warnings = [{"field": f["key"], "message": f"«{f['label']}» es obligatorio pero no está "
                                               "en ninguna pantalla: nunca se exigirá"}
                for f in fields if f["required"] and not f["locked"]
                and f["key"] not in screen_keys]
    schemes = FieldConfigurationScheme.objects.filter(
        Q(default_configuration=c) | Q(entries__configuration=c)).distinct()
    return {"id": c.id, "name": c.name, "description": c.description,
            "is_default": c.is_default, "fields": fields,
            "schemes": [_ref(s) for s in schemes], "warnings": warnings,
            "deleted_at": softdelete.iso(c.deleted_at)}


@router.get("/field-configurations", response=list[FieldConfigurationOut])
def list_field_configurations(request, deleted: bool = False):
    _admin(request.user)
    screen_keys = set(ScreenField.objects.filter(screen__deleted_at__isnull=True)
                      .values_list("field", flat=True))
    qs = softdelete.deleted_queryset(FieldConfiguration, request.user, deleted)
    return [_fc_out(c, screen_keys=screen_keys) for c in qs.prefetch_related("items")]


@router.get("/field-configurations/{cid}", response=FieldConfigurationOut)
def get_field_configuration(request, cid: int):
    _admin(request.user)
    return _fc_out(_get(FieldConfiguration, cid, "Configuración de campos no encontrada"))


@transaction.atomic
def _save_fc(c: FieldConfiguration, data: FieldConfigurationIn) -> FieldConfiguration:
    c.name, c.description = _name(data.name), data.description[:255]
    _apply_default(FieldConfiguration, c, data.is_default, "configuración predeterminada")
    rows, seen = [], set()
    for f in data.fields:
        if f.key in seen:
            raise ValidationFailed(f"Campo repetido: {f.key}", code="fields")
        seen.add(f.key)
        _check_key(f.key)
        label = fieldrules.labels_for([f.key])[f.key]
        if f.key in fieldrules.LOCKED:
            if f.hidden or not f.required:
                raise ValidationFailed(f"«{label}» es siempre obligatorio y visible",
                                       code="fields")
            if not f.description.strip():
                continue
        if f.required and f.hidden:
            raise ValidationFailed(f"«{label}» no puede ser obligatorio y estar oculto",
                                   code="fields")
        if f.required or f.hidden or f.description.strip():
            rows.append(f)
    _save(c, "Ya existe una configuración de campos con ese nombre")
    # items of deleted custom fields are kept (they come back with the field)
    c.items.filter(Q(custom_field__isnull=True) | Q(custom_field__deleted_at__isnull=True)) \
        .delete()
    FieldConfigurationItem.objects.bulk_create([
        FieldConfigurationItem(
            configuration=c, field=f.key, required=f.required and f.key not in
            fieldrules.LOCKED, hidden=f.hidden, description=f.description.strip()[:500],
            custom_field_id=int(f.key[3:]) if fieldrules.is_custom(f.key) else None)
        for f in rows
    ])
    fieldrules.invalidate()  # bulk_create sends no signals
    return c


@router.post("/field-configurations", response={201: FieldConfigurationOut})
def create_field_configuration(request, data: FieldConfigurationIn):
    _admin(request.user)
    return 201, _fc_out(_save_fc(FieldConfiguration(), data))


@router.put("/field-configurations/{cid}", response=FieldConfigurationOut)
def update_field_configuration(request, cid: int, data: FieldConfigurationIn):
    _admin(request.user)
    c = _get(FieldConfiguration, cid, "Configuración de campos no encontrada")
    return _fc_out(_save_fc(c, data))


@router.delete("/field-configurations/{cid}", response={204: None})
def delete_field_configuration(request, cid: int, permanent: bool = False):
    _admin(request.user)
    c = _get(FieldConfiguration, cid, "Configuración de campos no encontrada",
             permanent=permanent)
    _ensure_not_default(c, "Es la configuración de campos predeterminada: marca otra antes "
                           "de borrarla")
    if not permanent:
        softdelete.ensure_unused((
            FieldConfigurationScheme.objects.filter(
                Q(default_configuration=c) | Q(entries__configuration=c)).distinct().count(),
            "esquema de configuración de campos", "esquemas de configuración de campos"))
    softdelete.delete(c, request.user, permanent=permanent)
    return 204, None


@router.post("/field-configurations/{cid}/restore", response=FieldConfigurationOut)
def restore_field_configuration(request, cid: int):
    _admin(request.user)
    c = softdelete.get_deleted_or_404(FieldConfiguration, cid,
                                      "Configuración de campos no encontrada")
    return _fc_out(softdelete.restore(c, "Ya existe una configuración de campos activa con ese "
                                         "nombre"))


# ------------------------------------------------------------------ field configuration schemes

def _fcs_out(s: FieldConfigurationScheme) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description, "is_default": s.is_default,
        "default_configuration": _ref(s.default_configuration),
        "entries": [{"issue_type": type_ref(e.issue_type), "configuration": _ref(e.configuration)}
                    for e in s.entries.select_related("issue_type", "configuration")
                    .order_by("issue_type__position", "issue_type_id")],
        "projects": _project_refs(s.projects.all()),
        "deleted_at": softdelete.iso(s.deleted_at),
    }


@router.get("/field-configuration-schemes", response=list[FieldConfigurationSchemeOut])
def list_fcs(request, deleted: bool = False):
    _admin(request.user)
    qs = softdelete.deleted_queryset(FieldConfigurationScheme, request.user, deleted)
    return [_fcs_out(s) for s in qs.select_related("default_configuration")]


@router.get("/field-configuration-schemes/{sid}", response=FieldConfigurationSchemeOut)
def get_fcs(request, sid: int):
    _admin(request.user)
    return _fcs_out(_get(FieldConfigurationScheme, sid, "Esquema no encontrado"))


def _entries(entries, attr: str, model, message: str) -> list[tuple[IssueType, object]]:
    out, seen = [], set()
    for e in entries:
        if e.issue_type_id in seen:
            raise ValidationFailed("Tipo de incidencia repetido", code="entries")
        seen.add(e.issue_type_id)
        itype = _alive(IssueType, e.issue_type_id, "Tipo de incidencia inválido")
        out.append((itype, _alive(model, getattr(e, attr), message)))
    return out


@transaction.atomic
def _save_fcs(s: FieldConfigurationScheme, data: FieldConfigurationSchemeIn):
    s.name, s.description = _name(data.name), data.description[:255]
    s.default_configuration = _alive(FieldConfiguration, data.default_configuration_id,
                                     "Configuración de campos inválida o borrada")
    entries = _entries(data.entries, "configuration_id", FieldConfiguration,
                       "Configuración de campos inválida o borrada")
    _apply_default(FieldConfigurationScheme, s, data.is_default, "esquema predeterminado")
    _save(s, "Ya existe un esquema de configuración de campos con ese nombre")
    s.entries.all().delete()
    for itype, config in entries:
        FieldConfigurationSchemeEntry.objects.create(scheme=s, issue_type=itype,
                                                     configuration=config)
    return s


@router.post("/field-configuration-schemes", response={201: FieldConfigurationSchemeOut})
def create_fcs(request, data: FieldConfigurationSchemeIn):
    _admin(request.user)
    return 201, _fcs_out(_save_fcs(FieldConfigurationScheme(), data))


@router.put("/field-configuration-schemes/{sid}", response=FieldConfigurationSchemeOut)
def update_fcs(request, sid: int, data: FieldConfigurationSchemeIn):
    _admin(request.user)
    return _fcs_out(_save_fcs(_get(FieldConfigurationScheme, sid, "Esquema no encontrado"),
                              data))


@router.delete("/field-configuration-schemes/{sid}", response={204: None})
def delete_fcs(request, sid: int, permanent: bool = False):
    _admin(request.user)
    s = _get(FieldConfigurationScheme, sid, "Esquema no encontrado", permanent=permanent)
    _ensure_not_default(s, "Es el esquema predeterminado: marca otro antes de borrarlo")
    if not permanent:
        softdelete.ensure_unused((s.projects.count(), "proyecto", "proyectos"))
    softdelete.delete(s, request.user, permanent=permanent)
    return 204, None


@router.post("/field-configuration-schemes/{sid}/restore",
             response=FieldConfigurationSchemeOut)
def restore_fcs(request, sid: int):
    _admin(request.user)
    s = softdelete.get_deleted_or_404(FieldConfigurationScheme, sid, "Esquema no encontrado")
    ids = {s.default_configuration_id, *s.entries.values_list("configuration_id", flat=True)}
    if FieldConfiguration.all_objects.deleted().filter(id__in=ids).exists():
        raise Conflict("Restaura primero las configuraciones de campos que usa este esquema",
                       code="deleted_dependency")
    return _fcs_out(softdelete.restore(s, "Ya existe un esquema activo con ese nombre"))


# ------------------------------------------------------------------ screens

def _screen_out(s: Screen) -> dict:
    tabs = list(s.tabs.prefetch_related("screen_fields"))
    keys = [f.field for t in tabs for f in t.screen_fields.all()]
    labels = fieldrules.labels_for(keys)
    alive_cf = set(CustomField.objects.filter(
        id__in=[int(k[3:]) for k in keys if fieldrules.is_custom(k)]).values_list("id",
                                                                                   flat=True))
    kinds = dict(CustomField.objects.filter(id__in=alive_cf).values_list("id", "kind"))

    def ref(k):
        if fieldrules.is_custom(k):
            return {"key": k, "label": labels[k], "kind": kinds[int(k[3:])], "system": False}
        return {"key": k, "label": labels[k], "kind": fieldrules.SYSTEM_KINDS.get(k, "text"),
                "system": True}

    visible = [k for k in keys if not fieldrules.is_custom(k) or int(k[3:]) in alive_cf]
    from apps.workflows.models import Transition

    schemes = ScreenScheme.objects.filter(
        Q(default_screen=s) | Q(create_screen=s) | Q(edit_screen=s) | Q(view_screen=s))
    transitions = Transition.objects.filter(screen=s, workflow__deleted_at__isnull=True) \
        .select_related("workflow").order_by("workflow__name", "position")
    return {
        "id": s.id, "name": s.name, "description": s.description, "is_default": s.is_default,
        "tabs": [{"id": t.id, "name": t.name,
                  "fields": [ref(f.field) for f in t.screen_fields.all() if f.field in visible]}
                 for t in tabs],
        "screen_schemes": [_ref(x) for x in schemes],
        "transitions": [{"workflow_id": t.workflow_id, "workflow_name": t.workflow.name,
                         "transition_id": t.id, "transition_name": t.name}
                        for t in transitions],
        "deleted_at": softdelete.iso(s.deleted_at),
    }


@router.get("/screens", response=list[ScreenOut])
def list_screens(request, deleted: bool = False):
    _admin(request.user)
    return [_screen_out(s) for s in softdelete.deleted_queryset(Screen, request.user, deleted)]


@router.get("/screens/{sid}", response=ScreenOut)
def get_screen(request, sid: int):
    _admin(request.user)
    return _screen_out(_get(Screen, sid, "Pantalla no encontrada"))


@transaction.atomic
def _save_screen(s: Screen, data: ScreenIn) -> Screen:
    s.name, s.description = _name(data.name), data.description[:255]
    if not data.tabs:
        raise ValidationFailed("La pantalla necesita al menos una pestaña", code="tabs")
    seen: set[str] = set()
    for tab in data.tabs:
        for key in tab.fields:
            if key in seen:
                raise ValidationFailed(f"El campo {key} está repetido en la pantalla",
                                       code="tabs")
            seen.add(key)
            _check_key(key)
    _apply_default(Screen, s, data.is_default, "pantalla predeterminada")
    _save(s, "Ya existe una pantalla con ese nombre")
    # fields of deleted custom fields stay on the screen (they come back with the field)
    kept = list(ScreenField.objects.filter(screen=s, custom_field__deleted_at__isnull=False)
                .values_list("field", "custom_field_id"))
    s.tabs.all().delete()
    pos = 0
    tab_obj = None
    for i, tab in enumerate(data.tabs):
        tab_obj = ScreenTab.objects.create(screen=s, position=i,
                                           name=tab.name.strip()[:80] or f"Pestaña {i + 1}")
        rows = []
        for key in tab.fields:
            rows.append(ScreenField(
                screen=s, tab=tab_obj, field=key, position=pos,
                custom_field_id=int(key[3:]) if fieldrules.is_custom(key) else None))
            pos += 1
        ScreenField.objects.bulk_create(rows)
    ScreenField.objects.bulk_create([
        ScreenField(screen=s, tab=tab_obj, field=key, custom_field_id=cid, position=pos + n)
        for n, (key, cid) in enumerate(kept) if key not in seen])
    fieldrules.invalidate()
    return s


@router.post("/screens", response={201: ScreenOut})
def create_screen(request, data: ScreenIn):
    _admin(request.user)
    return 201, _screen_out(_save_screen(Screen(), data))


@router.put("/screens/{sid}", response=ScreenOut)
def update_screen(request, sid: int, data: ScreenIn):
    _admin(request.user)
    return _screen_out(_save_screen(_get(Screen, sid, "Pantalla no encontrada"), data))


@router.delete("/screens/{sid}", response={204: None})
def delete_screen(request, sid: int, permanent: bool = False):
    from apps.workflows.models import Transition

    _admin(request.user)
    s = _get(Screen, sid, "Pantalla no encontrada", permanent=permanent)
    _ensure_not_default(s, "Es la pantalla predeterminada: marca otra antes de borrarla")
    if not permanent:
        softdelete.ensure_unused(
            (ScreenScheme.objects.filter(Q(default_screen=s) | Q(create_screen=s)
                                         | Q(edit_screen=s) | Q(view_screen=s)).count(),
             "esquema de pantallas", "esquemas de pantallas"),
            (Transition.objects.filter(screen=s, workflow__deleted_at__isnull=True).count(),
             "transición", "transiciones"),
        )
    softdelete.delete(s, request.user, permanent=permanent)
    return 204, None


@router.post("/screens/{sid}/restore", response=ScreenOut)
def restore_screen(request, sid: int):
    _admin(request.user)
    s = softdelete.get_deleted_or_404(Screen, sid, "Pantalla no encontrada")
    return _screen_out(softdelete.restore(s, "Ya existe una pantalla activa con ese nombre"))


# ------------------------------------------------------------------ screen schemes

def _ss_out(s: ScreenScheme) -> dict:
    itss = IssueTypeScreenScheme.objects.filter(
        Q(default_screen_scheme=s) | Q(entries__screen_scheme=s)).distinct()
    return {
        "id": s.id, "name": s.name, "description": s.description, "is_default": s.is_default,
        "default_screen": _ref(s.default_screen), "create_screen": _ref(s.create_screen),
        "edit_screen": _ref(s.edit_screen), "view_screen": _ref(s.view_screen),
        "issue_type_screen_schemes": [_ref(x) for x in itss],
        "deleted_at": softdelete.iso(s.deleted_at),
    }


SS_RELATED = ("default_screen", "create_screen", "edit_screen", "view_screen")


@router.get("/screen-schemes", response=list[ScreenSchemeOut])
def list_screen_schemes(request, deleted: bool = False):
    _admin(request.user)
    qs = softdelete.deleted_queryset(ScreenScheme, request.user, deleted)
    return [_ss_out(s) for s in qs.select_related(*SS_RELATED)]


@router.get("/screen-schemes/{sid}", response=ScreenSchemeOut)
def get_screen_scheme(request, sid: int):
    _admin(request.user)
    return _ss_out(_get(ScreenScheme, sid, "Esquema de pantallas no encontrado"))


@transaction.atomic
def _save_ss(s: ScreenScheme, data: ScreenSchemeIn) -> ScreenScheme:
    s.name, s.description = _name(data.name), data.description[:255]
    bad = "Pantalla inválida o borrada"
    s.default_screen = _alive(Screen, data.default_screen_id, bad)
    for op in ("create", "edit", "view"):
        sid = getattr(data, f"{op}_screen_id")
        setattr(s, f"{op}_screen", _alive(Screen, sid, bad) if sid else None)
    _apply_default(ScreenScheme, s, data.is_default, "esquema de pantallas predeterminado")
    _save(s, "Ya existe un esquema de pantallas con ese nombre")
    return s


@router.post("/screen-schemes", response={201: ScreenSchemeOut})
def create_screen_scheme(request, data: ScreenSchemeIn):
    _admin(request.user)
    return 201, _ss_out(_save_ss(ScreenScheme(), data))


@router.put("/screen-schemes/{sid}", response=ScreenSchemeOut)
def update_screen_scheme(request, sid: int, data: ScreenSchemeIn):
    _admin(request.user)
    return _ss_out(_save_ss(_get(ScreenScheme, sid, "Esquema de pantallas no encontrado"), data))


@router.delete("/screen-schemes/{sid}", response={204: None})
def delete_screen_scheme(request, sid: int, permanent: bool = False):
    _admin(request.user)
    s = _get(ScreenScheme, sid, "Esquema de pantallas no encontrado", permanent=permanent)
    _ensure_not_default(s, "Es el esquema de pantallas predeterminado: marca otro antes de "
                           "borrarlo")
    if not permanent:
        softdelete.ensure_unused((
            IssueTypeScreenScheme.objects.filter(
                Q(default_screen_scheme=s) | Q(entries__screen_scheme=s)).distinct().count(),
            "esquema de pantallas por tipo", "esquemas de pantallas por tipo"))
    softdelete.delete(s, request.user, permanent=permanent)
    return 204, None


@router.post("/screen-schemes/{sid}/restore", response=ScreenSchemeOut)
def restore_screen_scheme(request, sid: int):
    _admin(request.user)
    s = softdelete.get_deleted_or_404(ScreenScheme, sid, "Esquema de pantallas no encontrado")
    ids = [getattr(s, f"{r}_id") for r in SS_RELATED]
    if Screen.all_objects.deleted().filter(id__in=[i for i in ids if i]).exists():
        raise Conflict("Restaura primero las pantallas que usa este esquema",
                       code="deleted_dependency")
    return _ss_out(softdelete.restore(s, "Ya existe un esquema de pantallas activo con ese "
                                         "nombre"))


# ------------------------------------------------------------------ issue type screen schemes

def _itss_out(s: IssueTypeScreenScheme) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description, "is_default": s.is_default,
        "default_screen_scheme": _ref(s.default_screen_scheme),
        "entries": [{"issue_type": type_ref(e.issue_type), "screen_scheme": _ref(e.screen_scheme)}
                    for e in s.entries.select_related("issue_type", "screen_scheme")
                    .order_by("issue_type__position", "issue_type_id")],
        "projects": _project_refs(s.projects.all()),
        "deleted_at": softdelete.iso(s.deleted_at),
    }


@router.get("/issue-type-screen-schemes", response=list[IssueTypeScreenSchemeOut])
def list_itss(request, deleted: bool = False):
    _admin(request.user)
    qs = softdelete.deleted_queryset(IssueTypeScreenScheme, request.user, deleted)
    return [_itss_out(s) for s in qs.select_related("default_screen_scheme")]


@router.get("/issue-type-screen-schemes/{sid}", response=IssueTypeScreenSchemeOut)
def get_itss(request, sid: int):
    _admin(request.user)
    return _itss_out(_get(IssueTypeScreenScheme, sid, "Esquema no encontrado"))


@transaction.atomic
def _save_itss(s: IssueTypeScreenScheme, data: IssueTypeScreenSchemeIn):
    s.name, s.description = _name(data.name), data.description[:255]
    bad = "Esquema de pantallas inválido o borrado"
    s.default_screen_scheme = _alive(ScreenScheme, data.default_screen_scheme_id, bad)
    entries = _entries(data.entries, "screen_scheme_id", ScreenScheme, bad)
    _apply_default(IssueTypeScreenScheme, s, data.is_default, "esquema predeterminado")
    _save(s, "Ya existe un esquema de pantallas por tipo con ese nombre")
    s.entries.all().delete()
    for itype, ss in entries:
        IssueTypeScreenSchemeEntry.objects.create(scheme=s, issue_type=itype, screen_scheme=ss)
    return s


@router.post("/issue-type-screen-schemes", response={201: IssueTypeScreenSchemeOut})
def create_itss(request, data: IssueTypeScreenSchemeIn):
    _admin(request.user)
    return 201, _itss_out(_save_itss(IssueTypeScreenScheme(), data))


@router.put("/issue-type-screen-schemes/{sid}", response=IssueTypeScreenSchemeOut)
def update_itss(request, sid: int, data: IssueTypeScreenSchemeIn):
    _admin(request.user)
    return _itss_out(_save_itss(_get(IssueTypeScreenScheme, sid, "Esquema no encontrado"), data))


@router.delete("/issue-type-screen-schemes/{sid}", response={204: None})
def delete_itss(request, sid: int, permanent: bool = False):
    _admin(request.user)
    s = _get(IssueTypeScreenScheme, sid, "Esquema no encontrado", permanent=permanent)
    _ensure_not_default(s, "Es el esquema predeterminado: marca otro antes de borrarlo")
    if not permanent:
        softdelete.ensure_unused((s.projects.count(), "proyecto", "proyectos"))
    softdelete.delete(s, request.user, permanent=permanent)
    return 204, None


@router.post("/issue-type-screen-schemes/{sid}/restore", response=IssueTypeScreenSchemeOut)
def restore_itss(request, sid: int):
    _admin(request.user)
    s = softdelete.get_deleted_or_404(IssueTypeScreenScheme, sid, "Esquema no encontrado")
    ids = {s.default_screen_scheme_id, *s.entries.values_list("screen_scheme_id", flat=True)}
    if ScreenScheme.all_objects.deleted().filter(id__in=ids).exists():
        raise Conflict("Restaura primero los esquemas de pantallas que usa este esquema",
                       code="deleted_dependency")
    return _itss_out(softdelete.restore(s, "Ya existe un esquema activo con ese nombre"))


# ------------------------------------------------------------------ projects

def _project(user, key: str) -> Project:
    p = Project.objects.filter(key=key.upper()).first()
    if p is None or not has_perm(user, p, Perm.BROWSE):
        raise NotFound("Proyecto no encontrado")
    return p


def _project_schemes_out(p: Project, user) -> dict:
    b = fieldrules.bundle(p)
    return {"field_configuration_scheme": b["fcs"], "issue_type_screen_scheme": b["itss"],
            "can_change": softdelete.is_system_admin(user)}


@router.get("/projects/{key}/field-schemes", response=ProjectFieldSchemesOut)
def project_field_schemes(request, key: str):
    return _project_schemes_out(_project(request.user, key), request.user)


@router.put("/projects/{key}/field-schemes", response=ProjectFieldSchemesOut)
@transaction.atomic
def set_project_field_schemes(request, key: str, data: ProjectFieldSchemesIn):
    """Like Jira, only system admins choose a project's schemes."""
    p = _project(request.user, key)
    _admin(request.user)
    fields = data.dict(exclude_unset=True)
    if "field_configuration_scheme_id" in fields:
        p.field_configuration_scheme = _alive(
            FieldConfigurationScheme, data.field_configuration_scheme_id,
            "Esquema de configuración de campos inválido o borrado")
    if "issue_type_screen_scheme_id" in fields:
        p.issue_type_screen_scheme = _alive(
            IssueTypeScreenScheme, data.issue_type_screen_scheme_id,
            "Esquema de pantallas por tipo inválido o borrado")
    p.save(update_fields=["field_configuration_scheme", "issue_type_screen_scheme",
                          "updated_at"])
    from apps.core import events

    events.publish_project(p.id, "project.updated", {"id": p.id}, actor_id=request.user.id)
    return _project_schemes_out(p, request.user)


@router.get("/projects/{key}/field-rules", response=ProjectFieldRulesOut)
def project_field_rules(request, key: str):
    """Everything the UI needs, resolved per issue type of the project: screens (create /
    edit / view, fields in order with their tabs), required / hidden fields, descriptions
    and, for every transition, its screen and validator fields."""
    p = _project(request.user, key)
    require(request.user, p, Perm.BROWSE)
    return fieldrules.project_rules(p, list(p.issue_types.all()))
