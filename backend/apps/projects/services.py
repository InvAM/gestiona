from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.core import events
from apps.core.errors import Conflict, Forbidden, ValidationFailed
from apps.issues.models import IssueType
from apps.workflows.models import Workflow

from .models import Component, Perm, Project, ProjectMember, Role, Version
from .permissions import require

User = get_user_model()


def template_workflow(template: str) -> Workflow | None:
    """Workflow flagged for the template (`Workflow.templates`), else the oldest one."""
    return (Workflow.objects.filter(templates__contains=[template]).order_by("id").first()
            or Workflow.objects.order_by("id").first())


def template_issue_types(template: str):
    """Issue types flagged for the template (`IssueType.templates`), else every standard and
    sub-task type."""
    qs = IssueType.objects.filter(templates__contains=[template])
    if not qs.exists():
        qs = IssueType.objects.filter(
            level__in=[IssueType.Level.STANDARD, IssueType.Level.SUBTASK])
    return qs


def suggest_key(name: str) -> str:
    words = [w for w in "".join(c if c.isalnum() else " " for c in name.upper()).split() if w]
    if not words:
        return "PROJ"
    key = "".join(w[0] for w in words) if len(words) > 1 else words[0][:4]
    key = "".join(c for c in key if c.isalnum())[:10]
    if not key[0].isalpha():
        key = "P" + key
    return key[:10] if len(key) >= 2 else (key + "X")


def can_create_projects(user) -> bool:
    return user.is_authenticated and (user.is_staff or user.is_superuser)


@transaction.atomic
def create_project(actor, *, name: str, key: str, template: str = "scrum",
                   description: str = "", lead_id: int | None = None,
                   access: str = Project.Access.LIMITED) -> Project:
    if not can_create_projects(actor):
        raise Forbidden("Solo los administradores pueden crear proyectos")
    key = (key or "").strip().upper()
    name = (name or "").strip()
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    if template not in Project.Template.values:
        raise ValidationFailed("Plantilla inválida", code="template")
    if Project.objects.filter(key=key).exists():
        raise Conflict("Ya existe un proyecto con esa clave", code="key")
    if Project.objects.filter(name__iexact=name).exists():
        raise Conflict("Ya existe un proyecto con ese nombre", code="name")
    lead = User.objects.filter(pk=lead_id, is_active=True).first() if lead_id else actor
    if lead is None:
        raise ValidationFailed("Responsable inválido", code="lead")
    workflow = template_workflow(template)
    if workflow is None:
        raise ValidationFailed("No hay ningún flujo de trabajo configurado", code="workflow")
    admin_role = Role.objects.admin_role()
    if admin_role is None:
        raise ValidationFailed("No hay ningún rol con permiso de administrar proyectos",
                               code="role")
    project = Project(
        key=key, name=name, template=template, description=description, lead=lead,
        workflow=workflow, created_by=actor, access=access,
    )
    project.full_clean(exclude=["workflow", "lead", "created_by", "category"])
    try:
        project.save()
    except IntegrityError as e:
        raise Conflict("La clave o el nombre ya existen") from e
    project.issue_types.set(template_issue_types(template))
    ProjectMember.objects.create(project=project, user=lead, role=admin_role)
    if actor != lead:
        ProjectMember.objects.get_or_create(project=project, user=actor,
                                            defaults={"role": admin_role})
    from apps.boards.services import create_default_board

    create_default_board(project, actor)
    return project


@transaction.atomic
def update_project(actor, project: Project, **fields) -> Project:
    require(actor, project, Perm.ADMINISTER)
    if fields.get("category_id") is not None and fields["category_id"] != project.category_id:
        from .models import ProjectCategory

        if not ProjectCategory.objects.filter(pk=fields["category_id"]).exists():
            raise ValidationFailed("Categoría inválida", code="category")
    for k in ("name", "description", "access", "default_assignee", "avatar", "color",
              "category_id"):
        if k in fields and fields[k] is not None:
            setattr(project, k, fields[k])
    if "lead_id" in fields and fields["lead_id"]:
        lead = User.objects.filter(pk=fields["lead_id"], is_active=True).first()
        if lead is None:
            raise ValidationFailed("Responsable inválido")
        project.lead = lead
    if "key" in fields and fields["key"] and fields["key"].upper() != project.key:
        raise ValidationFailed("La clave del proyecto no se puede cambiar", code="key")
    if "issue_type_ids" in fields and fields["issue_type_ids"] is not None:
        types = IssueType.objects.filter(id__in=fields["issue_type_ids"])
        if not types.exists():
            raise ValidationFailed("El proyecto necesita al menos un tipo de incidencia")
        # deleted types are no longer offered, so they can't block the change
        in_use = set(IssueType.objects.filter(issues__project=project)
                     .values_list("id", flat=True).distinct())
        missing = in_use - {t.id for t in types}
        if missing:
            raise ValidationFailed("Hay incidencias usando un tipo que intentas quitar")
        project.issue_types.set(types)
    if "default_issue_type_id" in fields:
        tid = fields["default_issue_type_id"]
        if tid is not None and not project.issue_types.filter(pk=tid).exclude(
                level=IssueType.Level.SUBTASK).exists():
            raise ValidationFailed("El tipo por defecto debe ser un tipo del proyecto (no "
                                   "subtarea)", code="default_issue_type")
        project.default_issue_type_id = tid
    if "archived" in fields and fields["archived"] is not None:
        project.is_archived = bool(fields["archived"])
    project.full_clean(exclude=["workflow", "lead", "created_by", "category", "key"])
    project.save()
    events.publish_project(project.id, "project.updated", {"id": project.id}, actor_id=actor.id)
    return project


@transaction.atomic
def delete_project(actor, project: Project) -> None:
    if not actor.is_superuser:
        raise Forbidden("Solo un superadministrador puede eliminar proyectos")
    for issue in project.issues.all():
        for a in issue.attachments.all():
            a.file.delete(save=False)
    project.delete()


@transaction.atomic
def set_member(actor, project: Project, user_id: int, role_id: int | None) -> ProjectMember:
    require(actor, project, Perm.ADMINISTER)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        raise ValidationFailed("Usuario inválido")
    role = Role.objects.filter(pk=role_id).first() if role_id else Role.objects.default_role()
    if role is None:
        raise ValidationFailed("Rol inválido")
    member, _ = ProjectMember.objects.update_or_create(
        project=project, user=user, defaults={"role": role}
    )
    _ensure_admin_left(project)
    return member


@transaction.atomic
def remove_member(actor, project: Project, user_id: int) -> None:
    require(actor, project, Perm.ADMINISTER)
    if user_id == project.lead_id:
        raise ValidationFailed("No puedes quitar al responsable del proyecto")
    ProjectMember.objects.filter(project=project, user_id=user_id).delete()
    _ensure_admin_left(project)


def _ensure_admin_left(project: Project) -> None:
    has_admin = ProjectMember.objects.filter(
        project=project, role__permissions__contains=[Perm.ADMINISTER.value]
    ).exists()
    if not has_admin and not project.lead_id:
        raise ValidationFailed("El proyecto debe tener al menos un administrador")


@transaction.atomic
def save_component(actor, project: Project, component: Component | None, **fields) -> Component:
    require(actor, project, Perm.ADMINISTER)
    component = component or Component(project=project)
    for k in ("name", "description", "lead_id"):
        if k in fields:
            setattr(component, k, fields[k])
    if not (component.name or "").strip():
        raise ValidationFailed("El nombre es obligatorio")
    try:
        component.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un componente con ese nombre") from e
    return component


@transaction.atomic
def save_version(actor, project: Project, version: Version | None, **fields) -> Version:
    from django.utils import timezone

    require(actor, project, Perm.ADMINISTER)
    version = version or Version(project=project, position=project.versions.count())
    for k in ("name", "description", "start_date", "release_date", "status"):
        if k in fields and fields[k] is not None:
            setattr(version, k, fields[k])
    if not (version.name or "").strip():
        raise ValidationFailed("El nombre es obligatorio")
    if version.status not in Version.Status.values:
        raise ValidationFailed("Estado inválido")
    if version.status == Version.Status.RELEASED and version.released_at is None:
        version.released_at = timezone.now()
        if version.release_date is None:
            version.release_date = timezone.localdate()
    elif version.status == Version.Status.UNRELEASED:
        version.released_at = None
    if version.start_date and version.release_date and version.release_date < version.start_date:
        raise ValidationFailed("La fecha de publicación debe ser posterior al inicio")
    try:
        version.save()
    except IntegrityError as e:
        raise Conflict("Ya existe una versión con ese nombre") from e
    return version
