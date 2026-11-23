from datetime import date
from typing import Any
from uuid import UUID

from django.db.models import F
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import IssueTypeOut, type_ref
from apps.issues.models import CustomField
from apps.projects.models import Perm, Project
from apps.projects.permissions import has_perm, require

from .models import IssueForm

router = Router(tags=["forms"])

BUILTIN = {
    "summary": "Resumen", "description": "Descripción", "priority": "Prioridad",
    "due_date": "Fecha límite", "labels": "Etiquetas", "components": "Componentes",
}


class FormFieldIn(Schema):
    field: str
    label: str = ""
    required: bool = False
    help: str = ""


class FormIn(Schema):
    name: str
    description: str = ""
    issue_type_id: int
    fields: list[FormFieldIn]
    default_labels: list[str] = []
    access: str = IssueForm.Access.ORGANIZATION
    is_active: bool = True
    success_message: str = ""


class FormOut(Schema):
    id: int
    slug: str
    name: str
    description: str
    project_key: str
    project_name: str
    issue_type: IssueTypeOut
    fields: list[dict]
    default_labels: list[str]
    access: str
    is_active: bool
    success_message: str
    submission_count: int
    deleted_at: str | None = None


class PublicField(Schema):
    field: str
    label: str
    required: bool
    help: str
    kind: str
    options: list[dict] = []


class PublicFormOut(Schema):
    slug: str
    name: str
    description: str
    project_key: str
    project_name: str
    fields: list[PublicField]


class SubmitIn(Schema):
    values: dict[str, Any]


class SubmitOut(Schema):
    key: str | None
    message: str
    can_view: bool


def _out(f: IssueForm) -> dict:
    return {
        "id": f.id, "slug": str(f.slug), "name": f.name, "description": f.description,
        "project_key": f.project.key, "project_name": f.project.name,
        "issue_type": type_ref(f.issue_type), "fields": f.fields,
        "default_labels": f.default_labels, "access": f.access, "is_active": f.is_active,
        "success_message": f.success_message, "submission_count": f.submission_count,
        "deleted_at": softdelete.iso(f.deleted_at),
    }


def _project_admin(user, key: str) -> Project:
    project = Project.objects.filter(key=key.upper()).first()
    if project is None:
        raise NotFound("Proyecto no encontrado")
    require(user, project, Perm.ADMINISTER)
    return project


def _clean(project: Project, data: FormIn) -> dict:
    name = data.name.strip()
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    itype = project.issue_types.filter(pk=data.issue_type_id).first()
    if itype is None or itype.level == -1:
        raise ValidationFailed("Elige un tipo de incidencia del proyecto (no subtarea)",
                               code="issue_type")
    if data.access not in IssueForm.Access.values:
        raise ValidationFailed("Acceso inválido", code="access")
    fields, seen = [], set()
    for f in data.fields:
        if f.field in seen:
            raise ValidationFailed(f"Campo repetido: {f.field}", code="fields")
        seen.add(f.field)
        if f.field.startswith("cf:"):
            cf = CustomField.objects.filter(pk=f.field[3:] if f.field[3:].isdigit() else 0).first()
            if cf is None:
                raise ValidationFailed("Campo personalizado inválido", code="fields")
            default_label = cf.name
        elif f.field in BUILTIN:
            default_label = BUILTIN[f.field]
        else:
            raise ValidationFailed(f"Campo desconocido: {f.field}", code="fields")
        fields.append({"field": f.field, "label": (f.label.strip() or default_label)[:120],
                       "required": f.required or f.field == "summary",
                       "help": f.help.strip()[:300]})
    if "summary" not in seen:
        fields.insert(0, {"field": "summary", "label": "Resumen", "required": True, "help": ""})
    # Field rules: every field required on create must be asked, and only fields on the
    # create screen can be (like Jira request types). Required ones are saved as required.
    from apps.issues import fieldrules

    default_labels = [str(x)[:60] for x in data.default_labels][:20]
    fieldrules.form_problems(project, itype, fields, default_labels).raise_if_any(
        "El formulario no cumple la configuración de campos del tipo: ")
    required = set(fieldrules.resolve(project, itype).create_required)
    for f in fields:
        f["required"] = f["required"] or f["field"] in required
    return {
        "name": name[:120], "description": data.description[:5000], "issue_type": itype,
        "fields": fields, "default_labels": default_labels,
        "access": data.access, "is_active": data.is_active,
        "success_message": data.success_message[:300],
    }


# ------------------------------------------------------------------ management

@router.get("/projects/{key}/forms", response=list[FormOut])
def list_forms(request, key: str, deleted: bool = False):
    project = _project_admin(request.user, key)
    base = IssueForm.all_objects.deleted() if deleted else IssueForm.objects
    return [_out(f) for f in base.filter(project=project).select_related("project",
                                                                          "issue_type")]


@router.post("/projects/{key}/forms", response={201: FormOut})
def create_form(request, key: str, data: FormIn):
    project = _project_admin(request.user, key)
    f = IssueForm.objects.create(project=project, created_by=request.user,
                                 **_clean(project, data))
    return 201, _out(f)


def _form_admin(user, form_id: int, *, deleted: bool = False) -> IssueForm:
    base = IssueForm.all_objects.deleted() if deleted else IssueForm.objects
    f = base.select_related("project", "issue_type").filter(pk=form_id).first()
    if f is None:
        raise NotFound("Formulario no encontrado")
    require(user, f.project, Perm.ADMINISTER)
    return f


@router.put("/forms/{form_id}", response=FormOut)
def update_form(request, form_id: int, data: FormIn):
    f = _form_admin(request.user, form_id)
    for k, v in _clean(f.project, data).items():
        setattr(f, k, v)
    f.save()
    return _out(f)


@router.delete("/forms/{form_id}", response={204: None})
def delete_form(request, form_id: int):
    """Soft delete: the public link stops working; restoring reactivates it."""
    _form_admin(request.user, form_id).soft_delete()
    return 204, None


@router.post("/forms/{form_id}/restore", response=FormOut)
def restore_form(request, form_id: int):
    f = _form_admin(request.user, form_id, deleted=True)
    if f.issue_type.deleted_at is not None:
        from apps.core.errors import Conflict

        raise Conflict("Restaura primero el tipo de incidencia del formulario",
                       code="deleted_dependency")
    return _out(softdelete.restore(f))


# ------------------------------------------------------------------ filling in

def _public(user, slug: UUID) -> IssueForm:
    f = IssueForm.objects.select_related("project", "issue_type").filter(slug=slug).first()
    if f is None or not f.is_active or f.project.is_archived:
        raise NotFound("El formulario no existe o ya no está disponible")
    if f.access == IssueForm.Access.MEMBERS and \
            not has_perm(user, f.project, Perm.CREATE_ISSUES):
        raise Forbidden("Este formulario es solo para miembros del proyecto")
    return f


@router.get("/f/{slug}", response=PublicFormOut)
def get_public_form(request, slug: UUID):
    from apps.issues import fieldrules
    from apps.issues.models import Priority

    f = _public(request.user, slug)
    required = set(fieldrules.resolve(f.project, f.issue_type).create_required)
    out = []
    for fd in f.fields:
        fd = {**fd, "required": bool(fd.get("required")) or fd["field"] in required}
        kind, options = fd["field"], []
        if kind == "priority":
            options = [{"id": p.id, "value": p.name} for p in Priority.objects.all()]
        elif kind == "components":
            options = [{"id": c.id, "value": c.name} for c in f.project.components.alive()]
        elif kind.startswith("cf:"):
            cf = CustomField.objects.filter(pk=int(kind[3:])).first()
            if cf is None:  # deleted field: skip it
                continue
            kind, options = f"cf:{cf.kind}", cf.active_options()
        out.append({**fd, "kind": kind, "options": options})
    return {"slug": str(f.slug), "name": f.name, "description": f.description,
            "project_key": f.project.key, "project_name": f.project.name, "fields": out}


@router.post("/f/{slug}", response={201: SubmitOut})
def submit_form(request, slug: UUID, data: SubmitIn):
    from apps.automation.engine import bot_user
    from apps.issues import fieldrules
    from apps.issues.services import IssueInput, create_issue

    f = _public(request.user, slug)
    # the field configuration may have changed since the form was saved
    problems = fieldrules.form_problems(f.project, f.issue_type, f.fields, f.default_labels)
    if problems.errors:
        raise ValidationFailed(
            f"Este formulario no está disponible: {problems.message()}. Avisa al administrador "
            "del proyecto", code="form_outdated", details={"fields": problems.errors})
    v = data.values or {}
    for fd in f.fields:
        if fd.get("required") and v.get(fd["field"]) in (None, "", []):
            raise ValidationFailed(f"«{fd['label']}» es obligatorio", code=fd["field"])
    allowed = {fd["field"] for fd in f.fields}
    unknown = set(v) - allowed
    if unknown:
        raise ValidationFailed("Campos no permitidos en este formulario", code="values")

    custom = {k[3:]: val for k, val in v.items() if k.startswith("cf:")}
    due = v.get("due_date")
    payload = IssueInput(
        issue_type_id=f.issue_type_id, summary=str(v.get("summary") or "")[:255],
        description=v.get("description") or None,
        priority_id=int(v["priority"]) if v.get("priority") else None,
        labels=[*f.default_labels, *(v.get("labels") or [])],
        component_ids=[int(x) for x in v.get("components") or []],
        due_date=date.fromisoformat(due) if due else None,
        custom_fields=custom or None, reporter_id=request.user.id,
    )
    # Submitters without create permission (organisation-wide forms) file through the bot.
    can_create = has_perm(request.user, f.project, Perm.CREATE_ISSUES)
    actor = request.user if can_create else bot_user()
    issue = create_issue(actor, f.project, payload, mode="form")
    if not can_create:
        issue.watchers.add(request.user)
    IssueForm.objects.filter(pk=f.pk).update(submission_count=F("submission_count") + 1)
    can_view = has_perm(request.user, f.project, Perm.BROWSE)
    return 201, {"key": issue.key if can_view else None, "can_view": can_view,
                 "message": f.success_message or "¡Gracias! Recibimos tu solicitud."}
