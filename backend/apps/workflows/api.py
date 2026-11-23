"""Global configuration endpoints (workflows, statuses, issue types, priorities, fields).

Every catalog here is soft-deletable (see apps/core/softdelete.py for the shared contract):
DELETE → papelera, ``?permanent=true`` → hard delete (409 if still referenced),
``POST …/{id}/restore`` and ``GET …?deleted=true`` for system admins.
"""

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Conflict, NotFound, ValidationFailed
from apps.core.schemas import (
    IssueTypeOut,
    PriorityOut,
    StatusOut,
    priority_ref,
    status_ref,
    type_ref,
)
from apps.issues.models import CustomField, IssueLinkType, IssueType, Priority, Resolution
from apps.projects.models import Perm, Project
from apps.projects.permissions import require

from .models import Status, StatusCategory, Transition, Workflow, WorkflowMapping, WorkflowStatus

router = Router(tags=["config"])


def _admin(user):
    softdelete.require_system_admin(user, "Solo administradores")


def _clean_templates(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    bad = set(values) - set(Project.Template.values)
    if bad:
        raise ValidationFailed(f"Plantilla de proyecto inválida: {', '.join(sorted(bad))}",
                               code="templates")
    return sorted(set(values))


# ------------------------------------------------------------------ schemas

class WorkflowStatusOut(Schema):
    status: StatusOut
    x: int
    y: int


class WorkflowTransitionOut(Schema):
    id: int
    name: str
    to_status_id: int
    from_status_ids: list[int]
    only_assignee: bool
    required_role_ids: list[int]
    require_resolution: bool
    require_comment: bool
    set_resolution_id: int | None
    clear_resolution: bool
    assign_to_current_user: bool
    screen_id: int | None = None
    required_fields: list[str] = []


class WorkflowOut(Schema):
    id: int
    name: str
    description: str
    initial_status_id: int
    statuses: list[WorkflowStatusOut]
    transitions: list[WorkflowTransitionOut]
    project_keys: list[str]
    templates: list[str] = []
    deleted_at: str | None = None


class WorkflowStatusIn(Schema):
    status_id: int
    x: int = 0
    y: int = 0


class WorkflowTransitionIn(Schema):
    name: str
    to_status_id: int
    from_status_ids: list[int] = []
    only_assignee: bool = False
    required_role_ids: list[int] = []
    require_resolution: bool = False
    require_comment: bool = False
    set_resolution_id: int | None = None
    clear_resolution: bool = False
    assign_to_current_user: bool = False
    screen_id: int | None = None  # transition screen (fields asked while transitioning)
    required_fields: list[str] = []  # «campos obligatorios» validator (field keys)


class WorkflowIn(Schema):
    name: str
    description: str = ""
    initial_status_id: int
    statuses: list[WorkflowStatusIn]
    transitions: list[WorkflowTransitionIn]
    templates: list[str] | None = None


class StatusIn(Schema):
    name: str
    category: str
    description: str = ""


class StatusAdminOut(StatusOut):
    description: str = ""
    deleted_at: str | None = None


class IssueTypeIn(Schema):
    name: str
    icon: str = "task"
    color: str = "#4BADE8"
    level: int = 0
    description: str = ""
    templates: list[str] | None = None
    has_affects_versions: bool | None = None


class IssueTypeAdminOut(IssueTypeOut):
    templates: list[str] = []
    deleted_at: str | None = None


class PriorityIn(Schema):
    name: str
    icon: str = "medium"
    color: str = "#E97F33"
    is_default: bool = False


class PriorityAdminOut(PriorityOut):
    is_default: bool = False
    deleted_at: str | None = None


class ResolutionIn(Schema):
    name: str
    description: str = ""
    is_default: bool = False


class ResolutionRow(Schema):
    id: int
    name: str
    description: str
    is_default: bool = False
    deleted_at: str | None = None


class LinkTypeRow(Schema):
    id: int
    name: str
    outward: str
    inward: str
    is_dependency: bool = False
    is_clone: bool = False
    deleted_at: str | None = None


class CustomFieldAdminOut(Schema):
    id: int
    name: str
    description: str
    kind: str
    options: list[dict]
    required: bool
    project_ids: list[int]
    issue_type_ids: list[int]
    deleted_at: str | None = None


class CustomFieldAdminIn(Schema):
    name: str
    description: str = ""
    kind: str
    options: list[dict] = []
    # compat: «obligatorio» in the default field configuration; omitted/null = unchanged
    required: bool | None = None
    project_ids: list[int] = []
    issue_type_ids: list[int] = []


class LinkTypeIn(Schema):
    name: str
    outward: str
    inward: str
    is_dependency: bool | None = None  # omitted = unchanged
    is_clone: bool | None = None  # omitted = unchanged; only one type can be the clone link


class MappingIn(Schema):
    issue_type_id: int
    workflow_id: int | None


# ------------------------------------------------------------------ workflows

def workflow_out(wf: Workflow) -> dict:
    return {
        "id": wf.id, "name": wf.name, "description": wf.description,
        "initial_status_id": wf.initial_status_id,
        "statuses": [{"status": status_ref(ws.status), "x": ws.x, "y": ws.y}
                     for ws in wf.workflow_statuses.select_related("status")],
        "transitions": [
            {"id": t.id, "name": t.name, "to_status_id": t.to_status_id,
             "from_status_ids": [s.id for s in t.from_statuses.all()],
             "only_assignee": t.only_assignee,
             "required_role_ids": [r.id for r in t.required_roles.all()],
             "require_resolution": t.require_resolution, "require_comment": t.require_comment,
             "set_resolution_id": t.set_resolution_id, "clear_resolution": t.clear_resolution,
             "assign_to_current_user": t.assign_to_current_user,
             "screen_id": t.screen_id, "required_fields": list(t.required_fields or [])}
            for t in wf.transitions.prefetch_related("from_statuses", "required_roles")
        ],
        "project_keys": list(wf.projects.values_list("key", flat=True)),
        "templates": list(wf.templates or []),
        "deleted_at": softdelete.iso(wf.deleted_at),
    }


@router.get("/workflows", response=list[WorkflowOut])
def list_workflows(request, deleted: bool = False):
    return [workflow_out(w) for w in softdelete.deleted_queryset(Workflow, request.user, deleted)]


@router.get("/workflows/{wid}", response=WorkflowOut)
def get_workflow(request, wid: int):
    wf = Workflow.objects.filter(pk=wid).first()
    if wf is None:
        raise NotFound("Flujo no encontrado")
    return workflow_out(wf)


def _save_workflow(wf: Workflow | None, data: WorkflowIn) -> Workflow:
    status_ids = [s.status_id for s in data.statuses]
    if not status_ids:
        raise ValidationFailed("El flujo necesita al menos un estado")
    if len(set(status_ids)) != len(status_ids):
        raise ValidationFailed("Estados duplicados")
    statuses = {s.id: s for s in Status.objects.filter(id__in=status_ids)}
    if len(statuses) != len(status_ids):
        raise ValidationFailed("Estado inválido")
    if data.initial_status_id not in statuses:
        raise ValidationFailed("El estado inicial debe pertenecer al flujo")
    from apps.issues import fieldrules
    from apps.issues.models import Screen

    screen_ids = {t.screen_id for t in data.transitions if t.screen_id}
    alive_screens = set(Screen.objects.filter(id__in=screen_ids).values_list("id", flat=True))
    for t in data.transitions:
        if t.to_status_id not in statuses or not set(t.from_status_ids) <= set(statuses):
            raise ValidationFailed(f"Transición «{t.name}» usa estados fuera del flujo")
        if t.screen_id and t.screen_id not in alive_screens:
            raise ValidationFailed(f"Transición «{t.name}»: la pantalla no existe o está "
                                   "borrada", code="screen")
        bad = [k for k in t.required_fields if not fieldrules.is_known_key(k)]
        if bad:
            raise ValidationFailed(f"Transición «{t.name}»: campo desconocido {bad[0]}",
                                   code="required_fields")
    if not any(s.category == StatusCategory.DONE for s in statuses.values()):
        raise ValidationFailed("El flujo necesita al menos un estado de categoría «Listo»")
    # Statuses being removed must not be in use by issues of projects using this workflow.
    if wf is not None:
        from apps.issues.models import Issue

        removed = set(wf.workflow_statuses.values_list("status_id", flat=True)) - set(status_ids)
        if removed and Issue.objects.filter(
            project__workflow=wf, status_id__in=removed
        ).exists():
            raise ValidationFailed(
                "Hay incidencias en estados que intentas quitar. Muévelas primero.",
                code="status_in_use",
            )
    templates = _clean_templates(data.templates)
    wf = wf or Workflow()
    wf.name = data.name.strip()[:80]
    if not wf.name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    wf.description = data.description
    wf.initial_status_id = data.initial_status_id
    if templates is not None:
        wf.templates = templates
    try:
        with transaction.atomic():
            wf.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un flujo con ese nombre", code="name") from e
    wf.workflow_statuses.all().delete()
    for pos, s in enumerate(data.statuses):
        WorkflowStatus.objects.create(workflow=wf, status_id=s.status_id, position=pos, x=s.x,
                                      y=s.y)
    wf.transitions.all().delete()
    for pos, t in enumerate(data.transitions):
        tr = Transition.objects.create(
            workflow=wf, name=t.name.strip()[:80] or statuses[t.to_status_id].name,
            to_status_id=t.to_status_id, position=pos, only_assignee=t.only_assignee,
            require_resolution=t.require_resolution, require_comment=t.require_comment,
            set_resolution_id=t.set_resolution_id, clear_resolution=t.clear_resolution,
            assign_to_current_user=t.assign_to_current_user, screen_id=t.screen_id,
            required_fields=list(dict.fromkeys(t.required_fields)),
        )
        tr.from_statuses.set(t.from_status_ids)
        tr.required_roles.set(t.required_role_ids)
    # keep board columns consistent: map new statuses into a column
    from apps.boards.models import BoardColumn

    for project in wf.projects.all():
        for board in project.boards.all():
            mapped = set(BoardColumn.statuses.through.objects.filter(
                boardcolumn__board=board).values_list("status_id", flat=True))
            for sid in status_ids:
                if sid not in mapped:
                    col = BoardColumn.objects.create(board=board, name=statuses[sid].name,
                                                     position=board.columns.count())
                    col.statuses.add(sid)
    return wf


@router.post("/workflows", response={201: WorkflowOut})
@transaction.atomic
def create_workflow(request, data: WorkflowIn):
    _admin(request.user)
    return 201, workflow_out(_save_workflow(None, data))


@router.put("/workflows/{wid}", response=WorkflowOut)
@transaction.atomic
def update_workflow(request, wid: int, data: WorkflowIn):
    _admin(request.user)
    wf = Workflow.objects.filter(pk=wid).first()
    if wf is None:
        raise NotFound("Flujo no encontrado")
    return workflow_out(_save_workflow(wf, data))


@router.delete("/workflows/{wid}", response={204: None})
def delete_workflow(request, wid: int, permanent: bool = False):
    _admin(request.user)
    wf = Workflow.all_objects.filter(pk=wid).first() if permanent else \
        Workflow.objects.filter(pk=wid).first()
    if wf is None:
        raise NotFound("Flujo no encontrado")
    if not permanent:
        softdelete.ensure_unused(
            (wf.projects.count(), "proyecto", "proyectos"),
            (wf.mappings.count(), "flujo por tipo", "flujos por tipo"),
        )
    softdelete.delete(wf, request.user, permanent=permanent)
    return 204, None


@router.post("/workflows/{wid}/restore", response=WorkflowOut)
def restore_workflow(request, wid: int):
    _admin(request.user)
    wf = softdelete.get_deleted_or_404(Workflow, wid, "Flujo no encontrado")
    deleted_statuses = Status.all_objects.deleted().filter(
        id__in=wf.workflow_statuses.values("status_id")).count()
    if deleted_statuses:
        raise Conflict("Restaura primero los estados borrados que usa este flujo",
                       code="deleted_dependency")
    return workflow_out(softdelete.restore(wf, "Ya existe un flujo activo con ese nombre"))


class WorkflowChangeIn(Schema):
    workflow_id: int
    status_map: dict[str, int] | None = None


@router.put("/projects/{key}/workflow", response={204: None})
@transaction.atomic
def set_project_workflow(request, key: str, data: WorkflowChangeIn):
    """Switch a project's workflow. `status_map` maps old status id → new status id for
    issues whose current status is not in the new workflow."""
    from apps.issues.models import Issue

    p = Project.objects.filter(key=key.upper()).first()
    if p is None:
        raise NotFound("Proyecto no encontrado")
    require(request.user, p, Perm.ADMINISTER)
    wf = Workflow.objects.filter(pk=data.workflow_id).first()
    if wf is None:
        raise NotFound("Flujo no encontrado")
    new_ids = set(wf.workflow_statuses.values_list("status_id", flat=True))
    status_map = {int(k): v for k, v in (data.status_map or {}).items()}
    orphan = set(Issue.objects.filter(project=p).exclude(status_id__in=new_ids)
                 .values_list("status_id", flat=True).distinct())
    missing = orphan - set(status_map)
    if missing:
        raise ValidationFailed("Indica a qué estado mover las incidencias existentes",
                               code="status_map_required",
                               details={"status_ids": sorted(missing)})
    for old, new in status_map.items():
        if new not in new_ids:
            raise ValidationFailed("Estado destino inválido")
        Issue.objects.filter(project=p, status_id=old).update(status_id=new)
    p.workflow = wf
    p.save(update_fields=["workflow", "updated_at"])
    from apps.boards.services import reset_columns_from_workflow

    for b in p.boards.all():
        reset_columns_from_workflow(b)
    return 204, None


@router.put("/projects/{key}/workflow-mappings", response={204: None})
@transaction.atomic
def set_workflow_mappings(request, key: str, data: list[MappingIn]):
    p = Project.objects.filter(key=key.upper()).first()
    if p is None:
        raise NotFound("Proyecto no encontrado")
    require(request.user, p, Perm.ADMINISTER)
    for m in data:
        if m.workflow_id is None:
            WorkflowMapping.objects.filter(project=p, issue_type_id=m.issue_type_id).delete()
        else:
            if not IssueType.objects.filter(pk=m.issue_type_id).exists():
                raise ValidationFailed("Tipo de incidencia inválido", code="issue_type")
            if not Workflow.objects.filter(pk=m.workflow_id).exists():
                raise ValidationFailed("Flujo inválido", code="workflow")
            WorkflowMapping.objects.update_or_create(
                project=p, issue_type_id=m.issue_type_id, defaults={"workflow_id": m.workflow_id}
            )
    return 204, None


# ------------------------------------------------------------------ statuses

def _status_out(s: Status) -> dict:
    return {**status_ref(s), "description": s.description,
            "deleted_at": softdelete.iso(s.deleted_at)}


@router.get("/statuses", response=list[StatusAdminOut])
def list_statuses(request, deleted: bool = False):
    return [_status_out(s) for s in softdelete.deleted_queryset(Status, request.user, deleted)]


@router.post("/statuses", response={201: StatusAdminOut})
def create_status(request, data: StatusIn):
    _admin(request.user)
    if data.category not in StatusCategory.values:
        raise ValidationFailed("Categoría inválida")
    name = data.name.strip()[:60]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    try:
        with transaction.atomic():
            s = Status.objects.create(name=name, category=data.category,
                                      description=data.description)
    except IntegrityError as e:
        raise Conflict("Ya existe un estado con ese nombre", code="name") from e
    return 201, _status_out(s)


@router.patch("/statuses/{sid}", response=StatusAdminOut)
def update_status(request, sid: int, data: StatusIn):
    _admin(request.user)
    s = Status.objects.filter(pk=sid).first()
    if s is None:
        raise NotFound("Estado no encontrado")
    if data.category not in StatusCategory.values:
        raise ValidationFailed("Categoría inválida")
    s.name, s.category, s.description = data.name.strip()[:60], data.category, data.description
    if not s.name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    try:
        with transaction.atomic():
            s.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un estado con ese nombre", code="name") from e
    return _status_out(s)


@router.delete("/statuses/{sid}", response={204: None})
def delete_status(request, sid: int, permanent: bool = False):
    _admin(request.user)
    manager = Status.all_objects if permanent else Status.objects
    s = manager.filter(pk=sid).first()
    if s is None:
        raise NotFound("Estado no encontrado")
    if not permanent:
        softdelete.ensure_unused(
            (Workflow.objects.filter(workflow_statuses__status=s).distinct().count(),
             "flujo de trabajo", "flujos de trabajo"),
        )
    softdelete.delete(s, request.user, permanent=permanent)
    return 204, None


@router.post("/statuses/{sid}/restore", response=StatusAdminOut)
def restore_status(request, sid: int):
    _admin(request.user)
    s = softdelete.get_deleted_or_404(Status, sid, "Estado no encontrado")
    return _status_out(softdelete.restore(s, "Ya existe un estado activo con ese nombre"))


# ------------------------------------------------------------------ issue types

def _type_out(t: IssueType) -> dict:
    return {**type_ref(t), "templates": list(t.templates or []),
            "deleted_at": softdelete.iso(t.deleted_at)}


@router.get("/issue-types", response=list[IssueTypeAdminOut])
def list_types(request, deleted: bool = False):
    return [_type_out(t) for t in softdelete.deleted_queryset(IssueType, request.user, deleted)]


def _apply_type(t: IssueType, data: IssueTypeIn) -> None:
    if data.level not in IssueType.Level.values:
        raise ValidationFailed("Nivel inválido", code="level")
    name = data.name.strip()[:60]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    t.name, t.icon, t.color = name, data.icon[:40], data.color[:9]
    t.level, t.description = data.level, data.description[:255]
    templates = _clean_templates(data.templates)
    if templates is not None:
        t.templates = templates
    if data.has_affects_versions is not None:
        t.has_affects_versions = data.has_affects_versions


@router.post("/issue-types", response={201: IssueTypeAdminOut})
def create_type(request, data: IssueTypeIn):
    _admin(request.user)
    t = IssueType(position=IssueType.all_objects.count())
    _apply_type(t, data)
    try:
        with transaction.atomic():
            t.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un tipo con ese nombre", code="name") from e
    return 201, _type_out(t)


@router.patch("/issue-types/{tid}", response=IssueTypeAdminOut)
def update_type(request, tid: int, data: IssueTypeIn):
    _admin(request.user)
    t = IssueType.objects.filter(pk=tid).first()
    if t is None:
        raise NotFound("Tipo no encontrado")
    if data.level != t.level and t.issues.exists():
        raise ValidationFailed("No se puede cambiar el nivel de un tipo en uso", code="level")
    _apply_type(t, data)
    try:
        with transaction.atomic():
            t.save()
    except IntegrityError as e:
        raise Conflict("Ya existe un tipo con ese nombre", code="name") from e
    return _type_out(t)


@router.delete("/issue-types/{tid}", response={204: None})
def delete_type(request, tid: int, permanent: bool = False):
    """Soft delete keeps existing issues of this type intact (they still show it); the type
    disappears from selectors, project metadata and JQL values."""
    from apps.forms.models import IssueForm

    _admin(request.user)
    manager = IssueType.all_objects if permanent else IssueType.objects
    t = manager.filter(pk=tid).first()
    if t is None:
        raise NotFound("Tipo no encontrado")
    if not permanent:
        # projects that would be left without any active type
        orphaned = Project.objects.filter(
            pk__in=Project.objects.filter(issue_types=t).values("pk")
        ).annotate(
            n=Count("issue_types", filter=Q(issue_types__deleted_at__isnull=True))
        ).filter(n__lte=1).count()
        if orphaned:
            raise Conflict(
                "No se puede borrar: es el único tipo de "
                + softdelete.count_phrase(orphaned, "proyecto", "proyectos"),
                code="in_use",
            )
        softdelete.ensure_unused(
            (IssueForm.objects.filter(issue_type=t).count(), "formulario", "formularios"),
        )
    softdelete.delete(t, request.user, permanent=permanent)
    return 204, None


@router.post("/issue-types/{tid}/restore", response=IssueTypeAdminOut)
def restore_type(request, tid: int):
    _admin(request.user)
    t = softdelete.get_deleted_or_404(IssueType, tid, "Tipo no encontrado")
    return _type_out(softdelete.restore(t, "Ya existe un tipo activo con ese nombre"))


# ------------------------------------------------------------------ priorities

def _priority_out(p: Priority) -> dict:
    return {**priority_ref(p), "is_default": p.is_default,
            "deleted_at": softdelete.iso(p.deleted_at)}


@router.get("/priorities", response=list[PriorityAdminOut])
def list_priorities(request, deleted: bool = False):
    return [_priority_out(p) for p in softdelete.deleted_queryset(Priority, request.user,
                                                                   deleted)]


def _save_priority(p: Priority, data: PriorityIn) -> Priority:
    name = data.name.strip()[:40]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    p.name, p.icon, p.color = name, data.icon[:40], data.color[:9]
    if data.is_default:
        Priority.objects.exclude(pk=p.pk).update(is_default=False)
        p.is_default = True
    elif p.is_default and p.pk:
        raise ValidationFailed("Elige otra prioridad por defecto en lugar de desmarcar esta",
                               code="is_default")
    try:
        with transaction.atomic():
            p.save()
    except IntegrityError as e:
        raise Conflict("Ya existe una prioridad con ese nombre", code="name") from e
    return p


@router.post("/priorities", response={201: PriorityAdminOut})
@transaction.atomic
def create_priority(request, data: PriorityIn):
    _admin(request.user)
    p = Priority(position=Priority.objects.count())
    return 201, _priority_out(_save_priority(p, data))


@router.put("/priorities/order", response=list[PriorityAdminOut])
@transaction.atomic
def reorder_priorities(request, ids: list[int]):
    _admin(request.user)
    for pos, pid in enumerate(ids):
        Priority.objects.filter(pk=pid).update(position=pos)
    return [_priority_out(p) for p in Priority.objects.all()]


@router.patch("/priorities/{pid}", response=PriorityAdminOut)
@transaction.atomic
def update_priority(request, pid: int, data: PriorityIn):
    _admin(request.user)
    p = Priority.objects.filter(pk=pid).first()
    if p is None:
        raise NotFound("Prioridad no encontrada")
    return _priority_out(_save_priority(p, data))


@router.delete("/priorities/{pid}", response={204: None})
def delete_priority(request, pid: int, permanent: bool = False):
    _admin(request.user)
    manager = Priority.all_objects if permanent else Priority.objects
    p = manager.filter(pk=pid).first()
    if p is None:
        raise NotFound("Prioridad no encontrada")
    if p.is_default and p.deleted_at is None:
        raise Conflict("Es la prioridad por defecto: elige otra antes de borrarla",
                       code="is_default")
    softdelete.delete(p, request.user, permanent=permanent)
    return 204, None


@router.post("/priorities/{pid}/restore", response=PriorityAdminOut)
def restore_priority(request, pid: int):
    _admin(request.user)
    p = softdelete.get_deleted_or_404(Priority, pid, "Prioridad no encontrada")
    return _priority_out(softdelete.restore(p, "Ya existe una prioridad activa con ese nombre"))


# ------------------------------------------------------------------ resolutions

def _resolution_out(r: Resolution) -> dict:
    return {"id": r.id, "name": r.name, "description": r.description,
            "is_default": r.is_default, "deleted_at": softdelete.iso(r.deleted_at)}


@router.get("/resolutions", response=list[ResolutionRow])
def list_resolutions(request, deleted: bool = False):
    return [_resolution_out(r) for r in softdelete.deleted_queryset(Resolution, request.user,
                                                                     deleted)]


def _save_resolution(r: Resolution, data: ResolutionIn) -> Resolution:
    name = data.name.strip()[:60]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    r.name, r.description = name, data.description[:255]
    if data.is_default:
        Resolution.objects.exclude(pk=r.pk).update(is_default=False)
        r.is_default = True
    elif r.is_default and r.pk:
        raise ValidationFailed("Elige otra resolución por defecto en lugar de desmarcar esta",
                               code="is_default")
    try:
        with transaction.atomic():
            r.save()
    except IntegrityError as e:
        raise Conflict("Ya existe una resolución con ese nombre", code="name") from e
    return r


@router.post("/resolutions", response={201: ResolutionRow})
@transaction.atomic
def create_resolution(request, data: ResolutionIn):
    _admin(request.user)
    r = Resolution(position=Resolution.objects.count())
    return 201, _resolution_out(_save_resolution(r, data))


@router.patch("/resolutions/{rid}", response=ResolutionRow)
@transaction.atomic
def update_resolution(request, rid: int, data: ResolutionIn):
    _admin(request.user)
    r = Resolution.objects.filter(pk=rid).first()
    if r is None:
        raise NotFound("Resolución no encontrada")
    return _resolution_out(_save_resolution(r, data))


@router.delete("/resolutions/{rid}", response={204: None})
def delete_resolution(request, rid: int, permanent: bool = False):
    _admin(request.user)
    manager = Resolution.all_objects if permanent else Resolution.objects
    r = manager.filter(pk=rid).first()
    if r is None:
        raise NotFound("Resolución no encontrada")
    if r.is_default and r.deleted_at is None:
        raise Conflict("Es la resolución por defecto: elige otra antes de borrarla",
                       code="is_default")
    if not permanent:
        softdelete.ensure_unused(
            (Transition.objects.filter(set_resolution=r, workflow__deleted_at__isnull=True)
             .count(), "transición", "transiciones"),
        )
    softdelete.delete(r, request.user, permanent=permanent)
    return 204, None


@router.post("/resolutions/{rid}/restore", response=ResolutionRow)
def restore_resolution(request, rid: int):
    _admin(request.user)
    r = softdelete.get_deleted_or_404(Resolution, rid, "Resolución no encontrada")
    return _resolution_out(softdelete.restore(r, "Ya existe una resolución activa con ese "
                                                 "nombre"))


# ------------------------------------------------------------------ link types

def _link_type_out(lt: IssueLinkType) -> dict:
    return {"id": lt.id, "name": lt.name, "outward": lt.outward, "inward": lt.inward,
            "is_dependency": lt.is_dependency, "is_clone": lt.is_clone,
            "deleted_at": softdelete.iso(lt.deleted_at)}


@router.get("/link-types", response=list[LinkTypeRow])
def list_link_types(request, deleted: bool = False):
    return [_link_type_out(lt) for lt in softdelete.deleted_queryset(IssueLinkType,
                                                                     request.user, deleted)]


def _save_link_type(lt: IssueLinkType, data: LinkTypeIn) -> IssueLinkType:
    lt.name, lt.outward, lt.inward = (data.name.strip()[:60], data.outward.strip()[:60],
                                      data.inward.strip()[:60])
    if not (lt.name and lt.outward and lt.inward):
        raise ValidationFailed("Nombre y descripciones son obligatorios", code="name")
    if data.is_dependency is not None:
        lt.is_dependency = data.is_dependency
    if data.is_clone is not None:
        lt.is_clone = data.is_clone
    try:
        with transaction.atomic():
            if lt.is_clone:
                IssueLinkType.all_objects.filter(is_clone=True).exclude(pk=lt.pk).update(
                    is_clone=False)
            lt.save()
    except IntegrityError as e:
        raise Conflict("Ya existe ese tipo de vínculo", code="name") from e
    return lt


@router.post("/link-types", response={201: LinkTypeRow})
def create_link_type(request, data: LinkTypeIn):
    _admin(request.user)
    return 201, _link_type_out(_save_link_type(IssueLinkType(), data))


@router.patch("/link-types/{lid}", response=LinkTypeRow)
def update_link_type(request, lid: int, data: LinkTypeIn):
    _admin(request.user)
    lt = IssueLinkType.objects.filter(pk=lid).first()
    if lt is None:
        raise NotFound("Tipo de vínculo no encontrado")
    return _link_type_out(_save_link_type(lt, data))


@router.delete("/link-types/{lid}", response={204: None})
def delete_link_type(request, lid: int, permanent: bool = False):
    """Existing links keep their type (and keep rendering); no new links can use it."""
    _admin(request.user)
    manager = IssueLinkType.all_objects if permanent else IssueLinkType.objects
    lt = manager.filter(pk=lid).first()
    if lt is None:
        raise NotFound("Tipo de vínculo no encontrado")
    softdelete.delete(lt, request.user, permanent=permanent)
    return 204, None


@router.post("/link-types/{lid}/restore", response=LinkTypeRow)
def restore_link_type(request, lid: int):
    _admin(request.user)
    lt = softdelete.get_deleted_or_404(IssueLinkType, lid, "Tipo de vínculo no encontrado")
    return _link_type_out(softdelete.restore(lt, "Ya existe un tipo de vínculo activo con ese "
                                                 "nombre"))


# ------------------------------------------------------------------ custom fields

def _cf_required(fields) -> set[int]:
    """Custom fields required in the default field configuration (compat `required`)."""
    from apps.issues import fieldrules

    config = fieldrules.default_configuration()
    keys = fieldrules.required_in(config.id if config else None,
                                  [f"cf:{c.id}" for c in fields])
    return {int(k[3:]) for k in keys}


def _cf_out(c: CustomField, required: set[int] | None = None) -> dict:
    if required is None:
        required = _cf_required([c])
    return {"id": c.id, "name": c.name, "description": c.description, "kind": c.kind,
            "options": c.options, "required": c.id in required,
            "project_ids": [p.id for p in c.projects.all()],
            "issue_type_ids": [t.id for t in c.issue_types.all()],
            "deleted_at": softdelete.iso(c.deleted_at)}


OPTION_KINDS = ("select", "multiselect", "checkbox")


def _clean_options(kind: str, options: list[dict], previous: list[dict] | None = None
                   ) -> list[dict]:
    """Normalise options. Options that existed before and are missing now (or come with
    "deleted": true) are kept as {"deleted": true} so issues using them still render; they
    are no longer offered in selectors. Sending an option again with its id restores it."""
    if kind not in OPTION_KINDS:
        return []
    out, seen = [], set()
    for i, o in enumerate(options):
        value = str(o.get("value", "")).strip()
        if not value:
            continue
        oid = str(o.get("id") or f"o{i}")
        if oid in seen:
            raise ValidationFailed("Opciones duplicadas", code="options")
        seen.add(oid)
        opt = {"id": oid, "value": value[:100]}
        if o.get("deleted"):
            opt["deleted"] = True
        out.append(opt)
    if not [o for o in out if not o.get("deleted")]:
        raise ValidationFailed("El campo necesita al menos una opción", code="options")
    for o in previous or []:
        oid = str(o.get("id"))
        if oid and oid not in seen:
            out.append({"id": oid, "value": str(o.get("value", ""))[:100], "deleted": True})
            seen.add(oid)
    return out


@router.get("/custom-fields", response=list[CustomFieldAdminOut])
def list_custom_fields(request, deleted: bool = False):
    qs = list(softdelete.deleted_queryset(CustomField, request.user, deleted)
              .prefetch_related("projects", "issue_types"))
    required = _cf_required(qs)
    return [_cf_out(c, required) for c in qs]


@router.post("/custom-fields", response={201: CustomFieldAdminOut})
@transaction.atomic
def create_custom_field(request, data: CustomFieldAdminIn):
    _admin(request.user)
    if data.kind not in CustomField.Kind.values:
        raise ValidationFailed("Tipo de campo inválido", code="kind")
    name = data.name.strip()[:80]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    c = CustomField.objects.create(name=name, description=data.description,
                                   kind=data.kind, options=_clean_options(data.kind,
                                                                          data.options),
                                   position=CustomField.all_objects.count())
    c.projects.set(data.project_ids)
    c.issue_types.set(data.issue_type_ids)
    if data.required:
        from apps.issues import fieldrules

        fieldrules.set_required_in_default(c, True)
    return 201, _cf_out(c)


@router.put("/custom-fields/{cid}", response=CustomFieldAdminOut)
@transaction.atomic
def update_custom_field(request, cid: int, data: CustomFieldAdminIn):
    _admin(request.user)
    c = CustomField.objects.filter(pk=cid).first()
    if c is None:
        raise NotFound("Campo no encontrado")
    if data.kind != c.kind:
        raise ValidationFailed("No se puede cambiar el tipo de un campo existente", code="kind")
    name = data.name.strip()[:80]
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    c.name, c.description = name, data.description
    c.options = _clean_options(c.kind, data.options, previous=c.options)
    c.save()
    c.projects.set(data.project_ids)
    c.issue_types.set(data.issue_type_ids)
    if data.required is not None:
        from apps.issues import fieldrules

        fieldrules.set_required_in_default(c, data.required)
    return _cf_out(c)


@router.delete("/custom-fields/{cid}", response={204: None})
@transaction.atomic
def delete_custom_field(request, cid: int, permanent: bool = False):
    """Soft delete keeps the values stored in issues (restore brings them back);
    `permanent` also erases them."""
    _admin(request.user)
    manager = CustomField.all_objects if permanent else CustomField.objects
    c = manager.filter(pk=cid).first()
    if c is None:
        raise NotFound("Campo no encontrado")
    if permanent:
        from apps.issues.models import Issue

        softdelete.require_system_admin(request.user)
        key = str(c.id)
        for issue in Issue.objects.filter(custom_fields__has_key=key).only("id",
                                                                           "custom_fields"):
            issue.custom_fields.pop(key, None)
            issue.save(update_fields=["custom_fields"])
    softdelete.delete(c, request.user, permanent=permanent)
    return 204, None


@router.post("/custom-fields/{cid}/restore", response=CustomFieldAdminOut)
def restore_custom_field(request, cid: int):
    _admin(request.user)
    c = softdelete.get_deleted_or_404(CustomField, cid, "Campo no encontrado")
    return _cf_out(softdelete.restore(c))
