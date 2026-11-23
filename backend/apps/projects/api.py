from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Conflict, NotFound, ValidationFailed
from apps.core.schemas import (
    IssueTypeOut,
    NamedRef,
    PriorityOut,
    ResolutionOut,
    StatusOut,
    UserRef,
    priority_ref,
    status_ref,
    type_ref,
    user_ref,
)

from . import services
from .models import Component, Perm, Project, ProjectCategory, ProjectMember, Role, Version
from .permissions import project_perms, require, visible_projects

router = Router(tags=["projects"])


# ------------------------------------------------------------------ schemas

class ProjectOut(Schema):
    id: int
    key: str
    name: str
    description: str
    template: str
    access: str
    avatar: str
    color: str
    lead: UserRef
    default_assignee: str
    is_archived: bool
    starred: bool
    category: NamedRef | None
    issue_count: int | None = None
    created_at: str


class ProjectIn(Schema):
    name: str
    key: str
    template: str = "scrum"
    description: str = ""
    lead_id: int | None = None
    access: str = "limited"


class ProjectPatch(Schema):
    name: str | None = None
    description: str | None = None
    access: str | None = None
    default_assignee: str | None = None
    avatar: str | None = None
    color: str | None = None
    lead_id: int | None = None
    category_id: int | None = None
    issue_type_ids: list[int] | None = None
    default_issue_type_id: int | None = None  # null clears it
    archived: bool | None = None


class RoleOut(Schema):
    id: int
    name: str
    description: str
    permissions: list[str]
    is_default: bool
    is_system: bool = False
    locked_permissions: list[str] = []
    in_use: int = 0  # memberships using the role
    member_count: int = 0  # deprecated alias of in_use
    builtin: bool = False  # deprecated alias of is_system
    deleted_at: str | None = None


class RoleIn(Schema):
    name: str
    description: str = ""
    permissions: list[str]
    is_default: bool = False


class PermissionOut(Schema):
    key: str
    label: str
    always: bool = False  # every role gets it (the backend adds it on save)


class MemberOut(Schema):
    user: UserRef
    role: RoleOut


class MemberIn(Schema):
    role_id: int | None = None


class ComponentOut(Schema):
    id: int
    name: str
    description: str
    lead: UserRef | None
    issue_count: int = 0
    deleted_at: str | None = None


class ComponentIn(Schema):
    name: str
    description: str = ""
    lead_id: int | None = None


class VersionOut(Schema):
    id: int
    name: str
    description: str
    status: str
    start_date: date | None
    release_date: date | None
    released_at: str | None
    issue_count: int = 0
    done_count: int = 0
    deleted_at: str | None = None


class VersionIn(Schema):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    release_date: date | None = None


class CustomFieldOut(Schema):
    id: int
    name: str
    description: str
    kind: str
    options: list[dict]
    required: bool
    issue_type_ids: list[int]


class LinkTypeOut(Schema):
    id: int
    name: str
    outward: str
    inward: str


class BoardRef(Schema):
    id: int
    name: str
    kind: str


class IssueTypeWorkflowOut(Schema):
    issue_type_id: int
    workflow_id: int
    workflow_name: str
    initial_status_id: int
    status_ids: list[int]


class ProjectCategoryOut(Schema):
    id: int
    name: str
    description: str
    project_count: int = 0
    deleted_at: str | None = None


class ProjectCategoryIn(Schema):
    name: str
    description: str = ""


class ProjectMetaOut(Schema):
    project: ProjectOut
    permissions: list[str]
    issue_types: list[IssueTypeOut]
    statuses: list[StatusOut]
    statuses_by_type: dict[str, list[int]]
    issue_type_workflows: list[IssueTypeWorkflowOut]
    default_issue_type_id: int | None
    priorities: list[PriorityOut]
    resolutions: list[ResolutionOut]
    components: list[ComponentOut]
    versions: list[VersionOut]
    custom_fields: list[CustomFieldOut]
    link_types: list[LinkTypeOut]
    boards: list[BoardRef]


# ------------------------------------------------------------------ helpers

def project_out(p: Project, user, issue_count: int | None = None) -> dict:
    starred = getattr(p, "_starred", None)
    if starred is None:
        starred = p.starred_by.filter(pk=user.pk).exists()
    return {
        "id": p.id, "key": p.key, "name": p.name, "description": p.description,
        "template": p.template, "access": p.access, "avatar": p.avatar, "color": p.color,
        "lead": user_ref(p.lead), "default_assignee": p.default_assignee,
        "is_archived": p.is_archived, "starred": starred,
        "category": {"id": p.category.id, "name": p.category.name} if p.category else None,
        "issue_count": issue_count, "created_at": p.created_at.isoformat(),
    }


def get_project(user, key: str, perm: str = Perm.BROWSE) -> Project:
    p = Project.objects.select_related("lead", "category", "workflow").filter(
        key=key.upper()
    ).first()
    if p is None:
        raise NotFound("Proyecto no encontrado")
    require(user, p, perm)
    return p


def role_out(r: Role, in_use: int | None = None) -> dict:
    if in_use is None:
        in_use = getattr(r, "n_members", None)
    if in_use is None:
        in_use = r.memberships.count()
    return {"id": r.id, "name": r.name, "description": r.description,
            "permissions": list(r.permissions), "is_default": r.is_default,
            "is_system": r.is_system, "locked_permissions": list(r.locked_permissions or []),
            "in_use": in_use, "member_count": in_use, "builtin": r.is_system,
            "deleted_at": softdelete.iso(r.deleted_at)}


def version_out(v: Version) -> dict:
    return {
        "id": v.id, "name": v.name, "description": v.description, "status": v.status,
        "start_date": v.start_date, "release_date": v.release_date,
        "released_at": v.released_at.isoformat() if v.released_at else None,
        "issue_count": getattr(v, "n_issues", 0), "done_count": getattr(v, "n_done", 0),
        "deleted_at": softdelete.iso(v.deleted_at),
    }


def component_out(c: Component) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description,
            "lead": user_ref(c.lead), "issue_count": getattr(c, "n_issues", 0),
            "deleted_at": softdelete.iso(c.deleted_at)}


def _versions_qs(p: Project, deleted: bool = False):
    qs = p.versions.deleted() if deleted else p.versions.alive()
    return qs.annotate(
        n_issues=Count("fix_issues", distinct=True),
        n_done=Count("fix_issues", filter=Q(fix_issues__status__category="done"), distinct=True),
    )


def _components_qs(p: Project, deleted: bool = False):
    qs = p.components.deleted() if deleted else p.components.alive()
    return qs.select_related("lead").annotate(n_issues=Count("issues", distinct=True))


# ------------------------------------------------------------------ projects

@router.get("/projects", response=list[ProjectOut])
def list_projects(request, q: str = "", archived: bool = False, starred: bool = False):
    user = request.user
    qs = visible_projects(user).select_related("lead", "category").filter(is_archived=archived)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(key__icontains=q))
    if starred:
        qs = qs.filter(starred_by=user)
    qs = qs.annotate(n=Count("issues", distinct=True))
    starred_ids = set(user.starred_projects.values_list("id", flat=True))
    out = []
    for p in qs.order_by("name"):
        p._starred = p.id in starred_ids
        out.append(project_out(p, user, p.n))
    return out


class KeyOut(Schema):
    key: str


@router.get("/projects/suggest-key", response=KeyOut)
def suggest_key(request, name: str):
    base = services.suggest_key(name)
    key, i = base, 1
    while Project.objects.filter(key=key).exists():
        i += 1
        key = f"{base[:9]}{i}"[:10]
    return {"key": key}


@router.post("/projects", response={201: ProjectOut})
def create_project(request, data: ProjectIn):
    p = services.create_project(request.user, **data.dict())
    return 201, project_out(p, request.user, 0)


@router.get("/projects/{key}", response=ProjectOut)
def project_detail(request, key: str):
    p = get_project(request.user, key)
    _touch_recent(request.user, "project", p.id)
    return project_out(p, request.user, p.issues.count())


@router.patch("/projects/{key}", response=ProjectOut)
def update_project(request, key: str, data: ProjectPatch):
    p = get_project(request.user, key)
    p = services.update_project(request.user, p, **data.dict(exclude_unset=True))
    return project_out(p, request.user)


@router.delete("/projects/{key}", response={204: None})
def delete_project(request, key: str):
    p = get_project(request.user, key)
    services.delete_project(request.user, p)
    return 204, None


@router.post("/projects/{key}/star", response={204: None})
def star_project(request, key: str):
    get_project(request.user, key).starred_by.add(request.user)
    return 204, None


@router.delete("/projects/{key}/star", response={204: None})
def unstar_project(request, key: str):
    get_project(request.user, key).starred_by.remove(request.user)
    return 204, None


@router.get("/projects/{key}/meta", response=ProjectMetaOut)
def project_meta(request, key: str):
    from apps.boards.models import Board
    from apps.issues.models import CustomField, IssueLinkType, Priority, Resolution
    from apps.workflows.models import Status

    p = get_project(request.user, key)
    types = list(p.issue_types.all())  # default manager: deleted types are not offered
    workflows = {t.id: services_workflow_for(p, t) for t in types}
    wf_statuses = {tid: [s.id for s in wf.ordered_statuses()] for tid, wf in workflows.items()}
    status_ids = {sid for ids in wf_statuses.values() for sid in ids}
    statuses = {s.id: s for s in Status.objects.filter(id__in=status_ids)}
    ordered_status_ids: list[int] = []
    for ids in wf_statuses.values():
        for sid in ids:
            if sid not in ordered_status_ids:
                ordered_status_ids.append(sid)
    cfs = CustomField.objects.filter(Q(projects__isnull=True) | Q(projects=p)).distinct() \
        .prefetch_related("issue_types")
    versions = _versions_qs(p)
    components = _components_qs(p)
    # compat `required`: the project's default field configuration (per type: field-rules)
    from apps.issues import fieldrules

    cfs = list(cfs)
    cf_required = fieldrules.required_in(fieldrules.bundle(p)["fc_default"],
                                         [f"cf:{c.id}" for c in cfs])
    return {
        "project": project_out(p, request.user),
        "permissions": sorted(project_perms(request.user, p)),
        "issue_types": [type_ref(t) for t in types],
        "statuses": [status_ref(statuses[i]) for i in ordered_status_ids],
        "statuses_by_type": {str(k): v for k, v in wf_statuses.items()},
        "default_issue_type_id": _default_type_id(p, types),
        "issue_type_workflows": [
            {"issue_type_id": tid, "workflow_id": wf.id, "workflow_name": wf.name,
             "initial_status_id": wf.initial_status_id, "status_ids": wf_statuses[tid]}
            for tid, wf in workflows.items()
        ],
        "priorities": [priority_ref(x) for x in Priority.objects.all()],
        "resolutions": [{"id": r.id, "name": r.name, "description": r.description}
                        for r in Resolution.objects.all()],
        "components": [component_out(c) for c in components],
        "versions": [version_out(v) for v in versions],
        "custom_fields": [
            {"id": c.id, "name": c.name, "description": c.description, "kind": c.kind,
             "options": c.options, "required": f"cf:{c.id}" in cf_required,
             "issue_type_ids": [t.id for t in c.issue_types.all()]}
            for c in cfs
        ],
        "link_types": [{"id": lt.id, "name": lt.name, "outward": lt.outward,
                        "inward": lt.inward} for lt in IssueLinkType.objects.all()],
        "boards": [{"id": b.id, "name": b.name, "kind": b.kind}
                   for b in Board.objects.filter(project=p)],
    }


def _default_type_id(p: Project, types: list) -> int | None:
    """Project's configured default type if still offered, else the first standard type."""
    from apps.issues.models import IssueType

    if p.default_issue_type_id and any(t.id == p.default_issue_type_id for t in types):
        return p.default_issue_type_id
    candidates = [t for t in types if t.level == IssueType.Level.STANDARD] or types
    return candidates[0].id if candidates else None


def services_workflow_for(project, issue_type):
    from apps.issues.services import workflow_for

    return workflow_for(project, issue_type)


# ------------------------------------------------------------------ members & roles

@router.get("/roles", response=list[RoleOut])
def list_roles(request, deleted: bool = False):
    qs = softdelete.deleted_queryset(Role, request.user, deleted)
    return [role_out(r) for r in qs.annotate(n_members=Count("memberships"))]


@router.get("/permissions", response=list[PermissionOut])
def list_permissions(request):
    return [{"key": p.value, "label": p.label, "always": p == Perm.BROWSE} for p in Perm]


def _require_system_admin(user):
    softdelete.require_system_admin(user, "Solo los administradores pueden gestionar roles")


def _perm_labels(keys) -> str:
    labels = {p.value: p.label for p in Perm}
    return ", ".join(f"«{labels.get(k, k)}»" for k in sorted(keys))


@transaction.atomic
def _save_role(role: Role, data: RoleIn) -> Role:
    name = data.name.strip()[:60]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    if Role.objects.filter(name__iexact=name).exclude(pk=role.pk).exists():
        raise ValidationFailed("Ya existe un rol con ese nombre", code="name")
    perms = sorted(set(data.permissions))
    unknown = set(perms) - {p.value for p in Perm}
    if unknown:
        raise ValidationFailed(f"Permisos desconocidos: {', '.join(unknown)}", code="permissions")
    if Perm.BROWSE.value not in perms:
        perms.append(Perm.BROWSE.value)  # every role can at least see the project
    # Protection comes from flags, never from the role's (renameable) name.
    missing = set(role.locked_permissions or []) - set(perms)
    if missing:
        raise ValidationFailed(f"El rol «{role.name}» debe conservar {_perm_labels(missing)}",
                               code="permissions")
    role.name, role.description, role.permissions = name, data.description[:255], perms
    if data.is_default:
        Role.objects.exclude(pk=role.pk).update(is_default=False)
    role.is_default = data.is_default or (role.is_default and role.pk is not None and
                                          not Role.objects.exclude(pk=role.pk)
                                          .filter(is_default=True).exists())
    try:
        with transaction.atomic():
            role.save()
    except IntegrityError as e:
        raise ValidationFailed("Ya existe un rol con ese nombre", code="name") from e
    return role


@router.post("/roles", response={201: RoleOut})
def create_role(request, data: RoleIn):
    _require_system_admin(request.user)
    return 201, role_out(_save_role(Role(), data))


@router.put("/roles/{role_id}", response=RoleOut)
def update_role(request, role_id: int, data: RoleIn):
    _require_system_admin(request.user)
    role = Role.objects.filter(pk=role_id).first()
    if role is None:
        raise NotFound("Rol no encontrado")
    return role_out(_save_role(role, data))


@router.delete("/roles/{role_id}", response={204: None})
def delete_role(request, role_id: int, permanent: bool = False):
    from apps.workflows.models import Transition

    _require_system_admin(request.user)
    manager = Role.all_objects if permanent else Role.objects
    role = manager.filter(pk=role_id).first()
    if role is None:
        raise NotFound("Rol no encontrado")
    if role.is_system:
        raise ValidationFailed("Los roles del sistema no se pueden eliminar",
                               code="system_role")
    if role.is_default and role.deleted_at is None:
        raise Conflict("Es el rol por defecto: elige otro antes de borrarlo", code="is_default")
    if not permanent:
        softdelete.ensure_unused(
            (role.memberships.count(), "membresía", "membresías"),
            (Transition.objects.filter(required_roles=role, workflow__deleted_at__isnull=True)
             .count(), "transición", "transiciones"),
        )
    softdelete.delete(role, request.user, permanent=permanent)
    return 204, None


@router.post("/roles/{role_id}/restore", response=RoleOut)
def restore_role(request, role_id: int):
    _require_system_admin(request.user)
    role = softdelete.get_deleted_or_404(Role, role_id, "Rol no encontrado")
    return role_out(softdelete.restore(role, "Ya existe un rol activo con ese nombre"))


@router.get("/projects/{key}/members", response=list[MemberOut])
def list_members(request, key: str):
    p = get_project(request.user, key)
    ms = list(ProjectMember.objects.filter(project=p).select_related("user", "role"))
    counts = dict(ProjectMember.objects.filter(role_id__in={m.role_id for m in ms})
                  .values_list("role_id").annotate(n=Count("id")))
    return [{"user": user_ref(m.user), "role": role_out(m.role, counts.get(m.role_id, 0))}
            for m in ms]


@router.put("/projects/{key}/members/{user_id}", response=MemberOut)
def set_member(request, key: str, user_id: int, data: MemberIn):
    p = get_project(request.user, key)
    m = services.set_member(request.user, p, user_id, data.role_id)
    return {"user": user_ref(m.user), "role": role_out(m.role)}


@router.delete("/projects/{key}/members/{user_id}", response={204: None})
def remove_member(request, key: str, user_id: int):
    p = get_project(request.user, key)
    services.remove_member(request.user, p, user_id)
    return 204, None


# ------------------------------------------------------------------ components

@router.get("/projects/{key}/components", response=list[ComponentOut])
def list_components(request, key: str, deleted: bool = False):
    p = get_project(request.user, key, Perm.ADMINISTER if deleted else Perm.BROWSE)
    return [component_out(c) for c in _components_qs(p, deleted)]


@router.post("/projects/{key}/components", response={201: ComponentOut})
def create_component(request, key: str, data: ComponentIn):
    p = get_project(request.user, key)
    return 201, component_out(services.save_component(request.user, p, None, **data.dict()))


@router.patch("/projects/{key}/components/{cid}", response=ComponentOut)
def update_component(request, key: str, cid: int, data: ComponentIn):
    p = get_project(request.user, key)
    c = p.components.alive().filter(pk=cid).first()
    if c is None:
        raise NotFound("Componente no encontrado")
    return component_out(services.save_component(request.user, p, c,
                                                 **data.dict(exclude_unset=True)))


@router.delete("/projects/{key}/components/{cid}", response={204: None})
def delete_component(request, key: str, cid: int):
    """Soft delete: issues keep showing the component; it is no longer offered."""
    p = get_project(request.user, key, Perm.ADMINISTER)
    c = p.components.alive().filter(pk=cid).first()
    if c is None:
        raise NotFound("Componente no encontrado")
    c.soft_delete()
    return 204, None


@router.post("/projects/{key}/components/{cid}/restore", response=ComponentOut)
def restore_component(request, key: str, cid: int):
    p = get_project(request.user, key, Perm.ADMINISTER)
    c = p.components.deleted().filter(pk=cid).first()
    if c is None:
        raise NotFound("Componente no encontrado")
    softdelete.restore(c, "Ya existe un componente activo con ese nombre")
    return component_out(_components_qs(p).get(pk=c.pk))


# ------------------------------------------------------------------ versions

@router.get("/projects/{key}/versions", response=list[VersionOut])
def list_versions(request, key: str, deleted: bool = False):
    p = get_project(request.user, key, Perm.ADMINISTER if deleted else Perm.BROWSE)
    return [version_out(v) for v in _versions_qs(p, deleted)]


@router.post("/projects/{key}/versions", response={201: VersionOut})
def create_version(request, key: str, data: VersionIn):
    p = get_project(request.user, key)
    return 201, version_out(services.save_version(request.user, p, None,
                                                  **data.dict(exclude_unset=True)))


@router.patch("/projects/{key}/versions/{vid}", response=VersionOut)
def update_version(request, key: str, vid: int, data: VersionIn):
    p = get_project(request.user, key)
    v = p.versions.alive().filter(pk=vid).first()
    if v is None:
        raise NotFound("Versión no encontrada")
    return version_out(services.save_version(request.user, p, v,
                                             **data.dict(exclude_unset=True)))


@router.delete("/projects/{key}/versions/{vid}", response={204: None})
def delete_version(request, key: str, vid: int):
    """Soft delete: issues keep showing the version; it is no longer offered."""
    p = get_project(request.user, key, Perm.ADMINISTER)
    v = p.versions.alive().filter(pk=vid).first()
    if v is None:
        raise NotFound("Versión no encontrada")
    v.soft_delete()
    return 204, None


@router.post("/projects/{key}/versions/{vid}/restore", response=VersionOut)
def restore_version(request, key: str, vid: int):
    p = get_project(request.user, key, Perm.ADMINISTER)
    v = p.versions.deleted().filter(pk=vid).first()
    if v is None:
        raise NotFound("Versión no encontrada")
    softdelete.restore(v, "Ya existe una versión activa con ese nombre")
    return version_out(_versions_qs(p).get(pk=v.pk))


# ------------------------------------------------------------------ project categories

def _category_out(c: ProjectCategory) -> dict:
    return {"id": c.id, "name": c.name, "description": c.description,
            "project_count": getattr(c, "n_projects", 0),
            "deleted_at": softdelete.iso(c.deleted_at)}


def _save_category(c: ProjectCategory, data: ProjectCategoryIn) -> ProjectCategory:
    c.name, c.description = data.name.strip()[:60], data.description[:255]
    if not c.name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    try:
        with transaction.atomic():
            c.save()
    except IntegrityError as e:
        raise Conflict("Ya existe una categoría con ese nombre", code="name") from e
    c.n_projects = c.projects.count()
    return c


@router.get("/project-categories", response=list[ProjectCategoryOut])
def list_categories(request, deleted: bool = False):
    qs = softdelete.deleted_queryset(ProjectCategory, request.user, deleted)
    return [_category_out(c) for c in qs.annotate(n_projects=Count("projects"))]


@router.post("/project-categories", response={201: ProjectCategoryOut})
def create_category(request, data: ProjectCategoryIn):
    _require_system_admin(request.user)
    return 201, _category_out(_save_category(ProjectCategory(), data))


@router.patch("/project-categories/{cid}", response=ProjectCategoryOut)
def update_category(request, cid: int, data: ProjectCategoryIn):
    _require_system_admin(request.user)
    c = ProjectCategory.objects.filter(pk=cid).first()
    if c is None:
        raise NotFound("Categoría no encontrada")
    return _category_out(_save_category(c, data))


@router.delete("/project-categories/{cid}", response={204: None})
def delete_category(request, cid: int, permanent: bool = False):
    """Soft delete: projects keep showing their category; it is no longer offered."""
    _require_system_admin(request.user)
    manager = ProjectCategory.all_objects if permanent else ProjectCategory.objects
    c = manager.filter(pk=cid).first()
    if c is None:
        raise NotFound("Categoría no encontrada")
    softdelete.delete(c, request.user, permanent=permanent)
    return 204, None


@router.post("/project-categories/{cid}/restore", response=ProjectCategoryOut)
def restore_category(request, cid: int):
    _require_system_admin(request.user)
    c = softdelete.get_deleted_or_404(ProjectCategory, cid, "Categoría no encontrada")
    softdelete.restore(c, "Ya existe una categoría activa con ese nombre")
    c.n_projects = c.projects.count()
    return _category_out(c)


# ------------------------------------------------------------------ recents

def _touch_recent(user, kind: str, object_id: int) -> None:
    from apps.search.models import RecentItem

    RecentItem.objects.update_or_create(user=user, kind=kind, object_id=object_id)
