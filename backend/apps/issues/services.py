"""Issue domain services. All mutations go through here (API, admin actions, automation)."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.postgres.search import SearchVector
from django.db import transaction
from django.db.models import F, Max, Min, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core import events
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.ranking import key_between
from apps.core.richtext import InvalidDocument, mentions, to_text, validate_doc
from apps.projects.models import Component, Perm, Project, Version
from apps.projects.permissions import assignable_users, has_perm, require
from apps.workflows.models import Status, StatusCategory, Transition, Workflow

from . import fieldrules
from .models import (
    Attachment,
    Comment,
    CustomField,
    Issue,
    IssueHistory,
    IssueLink,
    IssueLinkType,
    IssueType,
    Priority,
    Resolution,
    WebLink,
    Worklog,
)

User = get_user_model()

SIMPLE_FIELDS = {
    "summary", "story_points", "original_estimate", "remaining_estimate", "start_date",
    "due_date", "flagged",
}
FK_FIELDS = {"issue_type", "priority", "assignee", "reporter", "parent", "sprint", "team"}
M2M_FIELDS = {"components", "fix_versions", "affects_versions"}
EDITABLE_FIELDS = (
    SIMPLE_FIELDS | FK_FIELDS | M2M_FIELDS | {"description", "labels", "custom_fields"}
)


# --------------------------------------------------------------------------- helpers

def workflow_for(project: Project, issue_type: IssueType) -> Workflow:
    mapping = project.workflow_mappings.filter(issue_type=issue_type).select_related("workflow")
    m = mapping.first()
    return m.workflow if m else project.workflow


def _display(field: str, value: Any) -> str | None:
    if value is None:
        return None
    if field in FK_FIELDS:
        if isinstance(value, Issue):
            return value.key
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value)


def _raw(value: Any) -> Any:
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, (Decimal, date)):
        return str(value)
    if isinstance(value, list):
        return [_raw(v) for v in value]
    return value


def _item(field, old, new):
    return {
        "field": field,
        "from": _raw(old), "from_display": _display(field, old),
        "to": _raw(new), "to_display": _display(field, new),
    }


def update_search_vector(issue_ids: list[int]) -> None:
    from django.db.models import OuterRef, Subquery, TextField
    from django.db.models.aggregates import StringAgg
    from django.db.models.functions import Cast

    comments = (
        Comment.objects.filter(issue=OuterRef("pk"))
        .values("issue")
        .annotate(t=StringAgg("body_text", delimiter=Value(" ")))
        .values("t")[:1]
    )
    Issue.objects.filter(id__in=issue_ids).update(
        search_vector=SearchVector(Cast("key", TextField()), Cast("summary", TextField()),
                                   weight="A", config="simple")
        + SearchVector("description_text", weight="B", config="simple")
        + SearchVector(Coalesce(Subquery(comments, output_field=TextField()),
                                Value("", output_field=TextField())),
                       weight="C", config="simple")
    )


def _ensure_active(*issues: Issue) -> None:
    """Archived issues are read-only: only viewing, restoring and deleting remain."""
    for issue in issues:
        if issue.is_archived:
            raise ValidationFailed(f"{issue.key} está archivada; restáurala para modificarla",
                                   code="archived")


def _ensure_parent_active(parent: Issue | None) -> None:
    if parent is not None and parent.is_archived:
        raise ValidationFailed(f"La incidencia principal {parent.key} está archivada",
                               code="parent")


def _end_rank(project: Project) -> str:
    last = Issue.objects.filter(project=project).aggregate(m=Max("rank"))["m"]
    return key_between(last, None)


def _check_assignable(project: Project, user) -> None:
    if user is None:
        return
    if not user.is_active or not assignable_users(project).filter(pk=user.pk).exists():
        raise ValidationFailed(f"{user} no puede ser asignado en este proyecto", code="assignee")


def _validate_parent(project: Project, issue_type: IssueType, parent: Issue | None,
                     issue: Issue | None = None) -> None:
    if issue_type.level == IssueType.Level.SUBTASK:
        if parent is None:
            raise ValidationFailed("Una subtarea necesita una incidencia principal", code="parent")
        if parent.issue_type.level != IssueType.Level.STANDARD:
            raise ValidationFailed(
                "El principal de una subtarea debe ser una incidencia estándar", code="parent"
            )
    elif issue_type.level == IssueType.Level.STANDARD:
        if parent is not None and parent.issue_type.level != IssueType.Level.EPIC:
            raise ValidationFailed("El principal debe ser una épica", code="parent")
    elif parent is not None:
        raise ValidationFailed("Una épica no puede tener principal", code="parent")
    if parent is not None:
        if parent.project_id != project.id:
            raise ValidationFailed("El principal debe pertenecer al mismo proyecto", code="parent")
        if issue is not None and parent.id == issue.id:
            raise ValidationFailed("Una incidencia no puede ser su propio principal", code="parent")
    if issue is not None:
        if issue_type.level != IssueType.Level.STANDARD and issue.children.exists() and \
                issue_type.level != issue.issue_type.level:
            raise ValidationFailed(
                "No se puede cambiar el tipo: la incidencia tiene hijas", code="issue_type"
            )


def _validate_sprint(project: Project, sprint) -> None:
    if sprint is None:
        return
    if sprint.board.project_id != project.id:
        raise ValidationFailed("El sprint no pertenece a este proyecto", code="sprint")
    if sprint.state == "closed":
        raise ValidationFailed("No se puede agregar a un sprint cerrado", code="sprint")
    if sprint.board.deleted_at is not None:  # [Z] board in the papelera: its sprints are frozen
        raise ValidationFailed("El sprint es de un tablero eliminado", code="sprint")


def _clean_labels(labels) -> list[str]:
    seen: list[str] = []
    for raw in labels or []:
        label = str(raw).strip().replace(" ", "_")[:60]
        if label and label not in seen:
            seen.append(label)
    return seen


def _clean_custom_fields(project: Project, issue_type: IssueType, values: dict) -> dict:
    if not values:
        return {}
    fields = {
        str(f.id): f for f in CustomField.objects.filter(id__in=[int(k) for k in values
                                                                  if str(k).isdigit()])
    }
    clean: dict[str, Any] = {}
    for key, value in values.items():
        field = fields.get(str(key))
        if field is None:
            raise ValidationFailed(f"Campo personalizado desconocido: {key}", code="custom_fields")
        if field.projects.exists() and not field.projects.filter(pk=project.pk).exists():
            raise ValidationFailed(f"El campo {field.name} no aplica a este proyecto")
        if value in (None, "", []):
            clean[str(key)] = None
            continue
        kind = field.kind
        option_ids = {o.get("id") for o in field.options}
        if kind == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as e:
                raise ValidationFailed(f"{field.name}: debe ser un número") from e
        elif kind in ("select",) and value not in option_ids:
            raise ValidationFailed(f"{field.name}: opción inválida")
        elif kind in ("multiselect", "checkbox"):
            if not isinstance(value, list) or not set(value) <= option_ids:
                raise ValidationFailed(f"{field.name}: opciones inválidas")
        elif kind == "user":
            if not User.objects.filter(pk=value, is_active=True).exists():
                raise ValidationFailed(f"{field.name}: usuario inválido")
        elif kind == "multiuser":
            if not isinstance(value, list) or User.objects.filter(pk__in=value).count() != len(
                set(value)
            ):
                raise ValidationFailed(f"{field.name}: usuarios inválidos")
        elif kind == "labels":
            value = _clean_labels(value)
        elif kind in ("text", "url") and len(str(value)) > 255:
            raise ValidationFailed(f"{field.name}: máximo 255 caracteres")
        clean[str(key)] = value
    return clean


# --------------------------------------------------------------------------- create

@dataclass
class IssueInput:
    issue_type_id: int
    summary: str
    description: Any = None
    priority_id: int | None = None
    assignee_id: int | None = None
    reporter_id: int | None = None
    parent_id: int | None = None
    labels: list[str] | None = None
    component_ids: list[int] | None = None
    fix_version_ids: list[int] | None = None
    affects_version_ids: list[int] | None = None
    sprint_id: int | None = None
    story_points: Decimal | None = None
    original_estimate: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    custom_fields: dict | None = None
    status_id: int | None = None
    team_id: int | None = None


@transaction.atomic
def create_issue(actor, project: Project, data: IssueInput, *, mode: str = "create") -> Issue:
    """`mode` (field rules, see fieldrules.check_create): "create" (API, quick create,
    automation), "form" (request forms) or "clone"."""
    require(actor, project, Perm.CREATE_ISSUES)
    project = Project.objects.select_for_update().get(pk=project.pk)

    issue_type = project.issue_types.filter(pk=data.issue_type_id).first()
    if issue_type is None:
        raise ValidationFailed("Tipo de incidencia no válido para el proyecto", code="issue_type")
    summary = (data.summary or "").strip()
    if not summary:
        raise ValidationFailed("El resumen es obligatorio", code="summary")
    if len(summary) > 255:
        raise ValidationFailed("El resumen admite máximo 255 caracteres", code="summary")

    priority = (
        Priority.objects.filter(pk=data.priority_id).first() if data.priority_id
        else Priority.objects.filter(is_default=True).first() or Priority.objects.first()
    )
    if priority is None:
        raise ValidationFailed("Prioridad inválida", code="priority")

    parent = None
    if data.parent_id:
        parent = Issue.objects.select_related("issue_type").filter(pk=data.parent_id).first()
        if parent is None:
            raise ValidationFailed("Incidencia principal no encontrada", code="parent")
        _ensure_parent_active(parent)
    _validate_parent(project, issue_type, parent)

    assignee = None
    if data.assignee_id:
        assignee = User.objects.filter(pk=data.assignee_id).first()
        if assignee and assignee != actor and not has_perm(actor, project, Perm.ASSIGN_ISSUES):
            raise Forbidden("No tienes permiso para asignar incidencias")
        _check_assignable(project, assignee)
    elif project.default_assignee == Project.DefaultAssignee.LEAD:
        assignee = project.lead

    reporter = actor
    if data.reporter_id and data.reporter_id != actor.id:
        reporter = User.objects.filter(pk=data.reporter_id, is_active=True).first() or actor

    workflow = workflow_for(project, issue_type)
    status = workflow.initial_status
    if data.status_id:
        status = workflow.statuses.filter(pk=data.status_id).first() or status

    sprint = None
    if issue_type.level == IssueType.Level.SUBTASK and parent is not None:
        sprint = parent.sprint
    elif data.sprint_id:
        from apps.boards.models import Sprint

        sprint = Sprint.objects.select_related("board").filter(pk=data.sprint_id).first()
        _validate_sprint(project, sprint)

    team = None
    if data.team_id:
        from apps.plans.models import Team

        team = Team.objects.filter(pk=data.team_id).first()
        if team is None:
            raise ValidationFailed("Equipo inválido", code="team")

    try:
        description = validate_doc(data.description)
    except InvalidDocument as e:
        raise ValidationFailed(str(e), code="description") from e

    custom = _clean_custom_fields(project, issue_type, data.custom_fields or {})
    labels = _clean_labels(data.labels)
    comps = list(Component.objects.filter(project=project, id__in=data.component_ids)) \
        if data.component_ids else []
    fixv = list(Version.objects.filter(project=project, id__in=data.fix_version_ids)) \
        if data.fix_version_ids else []
    affv = list(Version.objects.filter(project=project, id__in=data.affects_version_ids)) \
        if data.affects_version_ids else []
    cf_values = {f"cf:{k}": v for k, v in custom.items()}
    fieldrules.check_create(
        project, issue_type, mode=mode,
        provided={
            "description": data.description, "priority": data.priority_id,
            "assignee": data.assignee_id, "parent": data.parent_id, "labels": data.labels,
            "reporter": data.reporter_id if data.reporter_id != actor.id else None,
            "components": data.component_ids, "fix_versions": data.fix_version_ids,
            "affects_versions": data.affects_version_ids, "sprint": data.sprint_id,
            "story_points": data.story_points, "original_estimate": data.original_estimate,
            "start_date": data.start_date, "due_date": data.due_date, "team": data.team_id,
            **cf_values,
        },
        effective={
            "summary": summary, "issue_type": issue_type.id, "description": description,
            "priority": priority.id, "assignee": assignee.id if assignee else None,
            "reporter": reporter.id if reporter else None,
            "parent": parent.id if parent else None, "labels": labels,
            "components": [c.id for c in comps], "fix_versions": [v.id for v in fixv],
            "affects_versions": [v.id for v in affv], "sprint": sprint.id if sprint else None,
            "story_points": data.story_points, "original_estimate": data.original_estimate,
            "remaining_estimate": data.original_estimate, "start_date": data.start_date,
            "due_date": data.due_date, "team": team.id if team else None, "flagged": False,
            **cf_values,
        },
    )

    project.issue_counter += 1
    project.save(update_fields=["issue_counter", "updated_at"])
    now = timezone.now()
    issue = Issue.objects.create(
        project=project,
        number=project.issue_counter,
        key=f"{project.key}-{project.issue_counter}",
        issue_type=issue_type,
        summary=summary,
        description=description,
        description_text=to_text(description),
        status=status,
        status_changed_at=now,
        priority=priority,
        assignee=assignee,
        reporter=reporter,
        parent=parent,
        labels=labels,
        sprint=sprint,
        team=team,
        story_points=data.story_points,
        original_estimate=data.original_estimate,
        remaining_estimate=data.original_estimate,
        start_date=data.start_date,
        due_date=data.due_date,
        rank=_end_rank(project),
        custom_fields=custom,
    )
    if status.category == StatusCategory.DONE:
        issue.resolution = Resolution.objects.filter(is_default=True).first()
        issue.resolved_at = now
        issue.save(update_fields=["resolution", "resolved_at"])
    if comps:
        issue.components.set(comps)
    if fixv:
        issue.fix_versions.set(fixv)
    if affv:
        issue.affects_versions.set(affv)
    issue.watchers.add(*{u for u in (actor, assignee) if u and not getattr(u, "is_bot", False)})
    IssueHistory.objects.create(issue=issue, actor=actor, items=[{"field": "created"}])
    update_search_vector([issue.id])

    if sprint and sprint.state == "active":
        from apps.boards.services import record_scope_change

        record_scope_change(sprint, issue, "added", None, issue.story_points)

    events.publish_project(project.id, "issue.created", {"id": issue.id, "key": issue.key},
                           actor_id=actor.id)
    _notify(actor, issue, "issue_created", mentioned=mentions(description))
    _automation("issue_created", issue, actor)
    return issue


# --------------------------------------------------------------------------- update

def _resolve_fk(field: str, value, project: Project, issue: Issue):
    if value is None:
        return None
    if field == "issue_type":
        obj = project.issue_types.filter(pk=value).first()
    elif field == "priority":
        obj = Priority.objects.filter(pk=value).first()
    elif field in ("assignee", "reporter"):
        obj = User.objects.filter(pk=value).first()
    elif field == "parent":
        obj = Issue.objects.select_related("issue_type").filter(pk=value).first()
    elif field == "sprint":
        from apps.boards.models import Sprint

        obj = Sprint.objects.select_related("board").filter(pk=value).first()
    elif field == "team":
        from apps.plans.models import Team

        obj = Team.objects.filter(pk=value).first()  # deleted teams cannot be chosen
    else:  # pragma: no cover
        raise ValueError(field)
    if obj is None:
        raise ValidationFailed(f"Valor inválido para {field}", code=field)
    return obj


def _check_edit_perms(actor, issue: Issue, changes: dict, only_assignee: bool) -> None:
    project = issue.project
    if only_assignee:
        new_assignee = changes["assignee"]
        if new_assignee != actor.id:
            require(actor, project, Perm.ASSIGN_ISSUES)
        else:
            require(actor, project, Perm.BROWSE)
            if not has_perm(actor, project, Perm.ASSIGN_ISSUES) and \
                    not has_perm(actor, project, Perm.EDIT_ISSUES):
                raise Forbidden("No tienes permiso para asignarte esta incidencia")
    else:
        require(actor, project, Perm.EDIT_ISSUES)
        if "assignee" in changes and changes["assignee"] != issue.assignee_id:
            require(actor, project, Perm.ASSIGN_ISSUES)


@transaction.atomic
def update_issue(actor, issue: Issue, changes: dict[str, Any], *, mode: str = "edit") -> Issue:
    """Apply a partial update. `changes` keys are field names; FK fields take ids,
    M2M fields take id lists.

    `mode`: "edit" (API, bulk, automation: permissions + edit screen, see
    fieldrules.check_edit). "transition" / "move" apply the values of a transition screen or
    of a move (the caller already checked them against the transition screen / the target's
    missing required fields); the screen check is theirs, NOT the permissions:
    * move: the same permissions as an edit, in the target project (edit + assign);
    * transition: like Jira, the transition permission (checked by the caller) lets the
      transition screen set its fields, except the assignee, which needs `assign_issues`."""
    issue = Issue.objects.select_for_update(of=("self",)).select_related(
        "project", "issue_type", "sprint", "parent"
    ).get(pk=issue.pk)
    project = issue.project
    _ensure_active(issue)
    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        raise ValidationFailed(f"Campos no editables: {', '.join(sorted(unknown))}")

    only_assignee = set(changes) == {"assignee"}
    if mode in ("edit", "move"):
        _check_edit_perms(actor, issue, changes, only_assignee)
    elif mode == "transition":
        require(actor, project, Perm.TRANSITION_ISSUES)
        if "assignee" in changes and changes["assignee"] != issue.assignee_id:
            require(actor, project, Perm.ASSIGN_ISSUES)
    else:  # pragma: no cover
        raise ValueError(mode)

    items: list[dict] = []
    old_sprint = issue.sprint
    old_points = issue.story_points
    m2m_updates: dict[str, list] = {}
    old_assignee_id = issue.assignee_id

    for field, value in changes.items():
        if field == "summary":
            value = (value or "").strip()
            if not value:
                raise ValidationFailed("El resumen es obligatorio", code="summary")
            if len(value) > 255:
                raise ValidationFailed("Máximo 255 caracteres", code="summary")
        if field in SIMPLE_FIELDS:
            old = getattr(issue, field)
            if field == "story_points" and value is not None:
                value = Decimal(str(value))
                if value < 0:
                    raise ValidationFailed("Los puntos no pueden ser negativos")
            if field in ("original_estimate", "remaining_estimate") and value is not None \
                    and value < 0:
                raise ValidationFailed("La estimación no puede ser negativa")
            if old != value:
                setattr(issue, field, value)
                items.append(_item(field, old, value))
        elif field in FK_FIELDS:
            old = getattr(issue, field)
            new = _resolve_fk(field, value, project, issue)
            if field == "parent" and new is not None and new.pk != issue.parent_id:
                _ensure_parent_active(new)
            if (old.pk if old else None) != (new.pk if new else None):
                setattr(issue, field, new)
                items.append(_item(field, old, new))
        elif field == "description":
            try:
                doc = validate_doc(value)
            except InvalidDocument as e:
                raise ValidationFailed(str(e), code="description") from e
            if doc != issue.description:
                issue.description = doc
                issue.description_text = to_text(doc)
                items.append({"field": "description", "from_display": None, "to_display": None})
        elif field == "labels":
            new = _clean_labels(value)
            if new != issue.labels:
                items.append(_item("labels", issue.labels, new))
                issue.labels = new
        elif field == "custom_fields":
            clean = _clean_custom_fields(project, issue.issue_type, value or {})
            merged = {**issue.custom_fields, **clean}
            for k, v in clean.items():
                if issue.custom_fields.get(k) != v:
                    cf = CustomField.objects.filter(pk=int(k)).first()
                    items.append({
                        "field": f"cf:{k}", "field_name": cf.name if cf else k,
                        "from": issue.custom_fields.get(k), "to": v,
                        "from_display": _display("cf", issue.custom_fields.get(k)),
                        "to_display": _display("cf", v),
                    })
            issue.custom_fields = {k: v for k, v in merged.items() if v is not None}
        elif field in M2M_FIELDS:
            model = Component if field == "components" else Version
            objs = list(model.objects.filter(project=project, id__in=value or []))
            if len(objs) != len(set(value or [])):
                raise ValidationFailed(f"Valores inválidos para {field}", code=field)
            current = list(getattr(issue, field).all())
            if {o.id for o in current} != {o.id for o in objs}:
                items.append(_item(field, [str(o) for o in current], [str(o) for o in objs]))
                m2m_updates[field] = objs

    if "issue_type" in changes or "parent" in changes:
        _validate_parent(project, issue.issue_type, issue.parent, issue)
        if issue.issue_type.level == IssueType.Level.SUBTASK and issue.parent:
            issue.sprint = issue.parent.sprint
    if "assignee" in changes:
        _check_assignable(project, issue.assignee)
    if "sprint" in changes:
        if issue.issue_type.level == IssueType.Level.SUBTASK:
            raise ValidationFailed("Las subtareas siguen el sprint de su principal", code="sprint")
        _validate_sprint(project, issue.sprint)
    if "issue_type" in changes:
        # keep current status if valid in the new workflow, else move to initial
        wf = workflow_for(project, issue.issue_type)
        if not wf.statuses.filter(pk=issue.status_id).exists():
            old_status = issue.status
            issue.status = wf.initial_status
            issue.status_changed_at = timezone.now()
            items.append(_item("status", old_status, issue.status))

    if not items:
        return issue
    if mode == "edit":
        changed = [i["field"] for i in items if i["field"] != "status"]
        fieldrules.check_edit(
            issue, fieldrules.resolve(project, issue.issue_type), changed=changed,
            value=lambda key: fieldrules.issue_value(issue, key, m2m_updates),
            assign_only=only_assignee, type_changed="issue_type" in changed,
        )

    issue.save()
    for field, objs in m2m_updates.items():
        getattr(issue, field).set(objs)
    if issue.sprint_id != (old_sprint.id if old_sprint else None) and \
            issue.issue_type.level != IssueType.Level.SUBTASK:
        Issue.objects.filter(parent=issue, issue_type__level=IssueType.Level.SUBTASK).update(
            sprint=issue.sprint
        )
    if issue.assignee_id and issue.assignee_id != old_assignee_id:
        issue.watchers.add(issue.assignee_id)

    IssueHistory.objects.create(issue=issue, actor=actor, items=items)
    if {"summary", "description"} & set(changes):
        update_search_vector([issue.id])

    from apps.boards.services import track_issue_sprint_change

    track_issue_sprint_change(issue, old_sprint, old_points)

    events.publish_project(
        project.id, "issue.updated",
        {"id": issue.id, "key": issue.key, "fields": [i["field"] for i in items]},
        actor_id=actor.id,
    )
    if issue.assignee_id and issue.assignee_id != old_assignee_id:
        _notify(actor, issue, "issue_assigned", recipients={issue.assignee_id})
    else:
        _notify(actor, issue, "issue_updated", data={"fields": [i["field"] for i in items]},
                mentioned=mentions(issue.description) if "description" in changes else None)
    fields = [i["field"] for i in items]
    _automation("issue_updated", issue, actor, {"fields": fields})
    if "assignee" in fields:
        _automation("issue_assigned", issue, actor, {"assignee_id": issue.assignee_id})
    return issue


# --------------------------------------------------------------------------- transitions

def available_transitions(actor, issue: Issue) -> list[Transition]:
    project = issue.project
    if not has_perm(actor, project, Perm.TRANSITION_ISSUES):
        return []
    wf = workflow_for(project, issue.issue_type)
    result = []
    membership_role = None
    for t in wf.transitions.prefetch_related("from_statuses", "required_roles").select_related(
        "to_status"
    ):
        froms = list(t.from_statuses.all())
        if froms and issue.status_id not in {s.id for s in froms}:
            continue
        if t.to_status_id == issue.status_id:
            continue
        privileged = actor.is_superuser or getattr(actor, "is_bot", False)
        if t.only_assignee and issue.assignee_id != actor.id and not privileged:
            continue
        roles = list(t.required_roles.all())
        if roles and not privileged:
            if membership_role is None:
                m = project.memberships.filter(user=actor).first()
                membership_role = m.role_id if m else -1
            if membership_role not in {r.id for r in roles}:
                continue
        result.append(t)
    return result


@transaction.atomic
def transition_issue(actor, issue: Issue, *, transition_id: int | None = None,
                     to_status_id: int | None = None, resolution_id: int | None = None,
                     comment: Any = None, fields: dict | None = None) -> Issue:
    """`fields`: values of the transition screen (PATCH format, or "cf:<id>" keys). They must
    be on the transition's screen; the configuration's required fields on that screen and the
    transition's «campos obligatorios» validator must end up with a value. The values are
    applied (normal history) right before the status change, all in one transaction."""
    def locked():
        return Issue.objects.select_for_update(of=("self",)).select_related(
            "project", "issue_type", "status", "sprint"
        ).get(pk=issue.pk)

    issue = locked()
    require(actor, issue.project, Perm.TRANSITION_ISSUES)
    _ensure_active(issue)
    options = available_transitions(actor, issue)
    if transition_id is not None:
        transition = next((t for t in options if t.id == transition_id), None)
    else:
        transition = next((t for t in options if t.to_status_id == to_status_id), None)
    if transition is None:
        raise ValidationFailed("Transición no permitida desde el estado actual", code="transition")

    if transition.require_comment and not comment:
        raise ValidationFailed("Esta transición requiere un comentario", code="comment")
    values = fieldrules.normalize(fields)
    fieldrules.check_transition(issue, fieldrules.resolve(issue.project, issue.issue_type),
                                transition, values)
    if values:
        update_issue(actor, issue, fieldrules.to_patch(values), mode="transition")
        issue = locked()
    old_status, old_resolution = issue.status, issue.resolution
    new_status = transition.to_status
    items = [_item("status", old_status, new_status)]
    issue.status = new_status
    issue.status_changed_at = timezone.now()

    resolution = None
    if resolution_id:
        resolution = Resolution.objects.filter(pk=resolution_id).first()
        if resolution is None:
            raise ValidationFailed("Resolución inválida", code="resolution")
    elif transition.set_resolution_id:
        resolution = transition.set_resolution
    if transition.require_resolution and resolution is None:
        raise ValidationFailed("Debes elegir una resolución", code="resolution")

    if new_status.category == StatusCategory.DONE:
        issue.resolution = resolution or Resolution.objects.filter(is_default=True).first()
        issue.resolved_at = issue.resolved_at or timezone.now()
    elif transition.clear_resolution or old_status.category == StatusCategory.DONE:
        issue.resolution = None
        issue.resolved_at = None
    if issue.resolution_id != (old_resolution.id if old_resolution else None):
        items.append(_item("resolution", old_resolution, issue.resolution))

    if transition.assign_to_current_user and issue.assignee_id != actor.id:
        _check_assignable(issue.project, actor)
        items.append(_item("assignee", issue.assignee, actor))
        issue.assignee = actor
    issue.save()
    IssueHistory.objects.create(issue=issue, actor=actor, items=items)

    if issue.sprint and issue.sprint.state == "active":
        from apps.boards.services import record_scope_change

        was_done = old_status.category == StatusCategory.DONE
        is_done = new_status.category == StatusCategory.DONE
        if is_done and not was_done:
            record_scope_change(issue.sprint, issue, "completed", issue.story_points,
                                issue.story_points)
        elif was_done and not is_done:
            record_scope_change(issue.sprint, issue, "reopened", issue.story_points,
                                issue.story_points)

    if comment:
        add_comment(actor, issue, comment, _skip_perm=True)
    events.publish_project(
        issue.project_id, "issue.updated",
        {"id": issue.id, "key": issue.key, "fields": ["status"]}, actor_id=actor.id,
    )
    _notify(actor, issue, "issue_transitioned",
            data={"from": old_status.name, "to": new_status.name})
    _automation("issue_transitioned", issue, actor, {"from": old_status.id, "to": new_status.id})
    return issue


# --------------------------------------------------------------------------- ranking

@transaction.atomic
def rank_issues(actor, issues: list[Issue], *, before: Issue | None = None,
                after: Issue | None = None) -> None:
    """Move `issues` (keeping their relative order) right before `before` or right after
    `after`. Exactly one anchor must be given."""
    if not issues:
        return
    project = issues[0].project
    if any(i.project_id != project.id for i in issues):
        raise ValidationFailed("Las incidencias deben ser del mismo proyecto")
    require(actor, project, Perm.EDIT_ISSUES)
    _ensure_active(*issues)
    if (before is None) == (after is None):
        raise ValidationFailed("Indica exactamente una referencia (before / after)")
    ids = {i.id for i in issues}
    qs = Issue.objects.filter(project=project).exclude(id__in=ids)
    if before is not None:
        if before.id in ids:
            raise ValidationFailed("Referencia inválida")
        high = before.rank
        low = qs.filter(rank__lt=high).aggregate(m=Max("rank"))["m"]
    else:
        if after.id in ids:
            raise ValidationFailed("Referencia inválida")
        low = after.rank
        high = qs.filter(rank__gt=low).aggregate(m=Min("rank"))["m"]
    ordered = sorted(issues, key=lambda i: i.rank)
    cur = low
    for issue in ordered:
        cur = key_between(cur, high)
        Issue.objects.filter(pk=issue.pk).update(rank=cur)
    events.publish_project(project.id, "issue.ranked", {"ids": [i.id for i in ordered]},
                           actor_id=actor.id)


# --------------------------------------------------------------------------- delete

@transaction.atomic
def delete_issue(actor, issue: Issue) -> None:
    require(actor, issue.project, Perm.DELETE_ISSUES)
    project_id, issue_id, key = issue.project_id, issue.id, issue.key
    if issue.issue_type.level == IssueType.Level.EPIC:
        Issue.objects.filter(parent=issue).update(parent=None)
    for a in issue.attachments.all():
        a.file.delete(save=False)
    issue.delete()
    events.publish_project(project_id, "issue.deleted", {"id": issue_id, "key": key},
                           actor_id=actor.id)


# --------------------------------------------------------------------------- comments

@transaction.atomic
def add_comment(actor, issue: Issue, body: Any, *, _skip_perm: bool = False) -> Comment:
    if not _skip_perm:
        require(actor, issue.project, Perm.ADD_COMMENTS)
    _ensure_active(issue)
    try:
        doc = validate_doc(body)
    except InvalidDocument as e:
        raise ValidationFailed(str(e), code="body") from e
    text = to_text(doc)
    if not text and not doc:
        raise ValidationFailed("El comentario está vacío", code="body")
    comment = Comment.objects.create(issue=issue, author=actor, body=doc, body_text=text)
    if not getattr(actor, "is_bot", False):
        issue.watchers.add(actor)
    Issue.objects.filter(pk=issue.pk).update(updated_at=timezone.now())
    update_search_vector([issue.id])
    events.publish_project(issue.project_id, "comment.created",
                           {"issue_id": issue.id, "id": comment.id}, actor_id=actor.id)
    _notify(actor, issue, "comment_added", data={"comment_id": comment.id},
            mentioned=mentions(doc))
    _automation("comment_added", issue, actor, {"comment_id": comment.id})
    return comment


@transaction.atomic
def edit_comment(actor, comment: Comment, body: Any) -> Comment:
    issue = comment.issue
    if comment.author_id != actor.id:
        require(actor, issue.project, Perm.EDIT_ALL_COMMENTS)
    else:
        require(actor, issue.project, Perm.ADD_COMMENTS)
    _ensure_active(issue)
    try:
        doc = validate_doc(body)
    except InvalidDocument as e:
        raise ValidationFailed(str(e), code="body") from e
    before = mentions(comment.body)
    comment.body = doc
    comment.body_text = to_text(doc)
    comment.edited = True
    comment.save()
    update_search_vector([issue.id])
    events.publish_project(issue.project_id, "comment.updated",
                           {"issue_id": issue.id, "id": comment.id}, actor_id=actor.id)
    new_mentions = mentions(doc) - before
    if new_mentions:
        _notify(actor, issue, "mentioned", recipients=set(), mentioned=new_mentions,
                data={"comment_id": comment.id})
    return comment


@transaction.atomic
def delete_comment(actor, comment: Comment) -> None:
    issue = comment.issue
    if comment.author_id != actor.id:
        require(actor, issue.project, Perm.DELETE_ALL_COMMENTS)
    else:
        require(actor, issue.project, Perm.ADD_COMMENTS)
    _ensure_active(issue)
    cid = comment.id
    comment.delete()
    update_search_vector([issue.id])
    events.publish_project(issue.project_id, "comment.deleted",
                           {"issue_id": issue.id, "id": cid}, actor_id=actor.id)


# --------------------------------------------------------------------------- attachments

BLOCKED_EXTENSIONS = {"exe", "bat", "cmd", "com", "msi", "scr", "ps1", "vbs", "js", "jar"}


@transaction.atomic
def add_attachment(actor, issue: Issue, upload) -> Attachment:
    from django.conf import settings

    require(actor, issue.project, Perm.CREATE_ATTACHMENTS)
    _ensure_active(issue)
    max_bytes = settings.MAX_ATTACHMENT_MB * 1024 * 1024
    if upload.size > max_bytes:
        raise ValidationFailed(f"El archivo supera {settings.MAX_ATTACHMENT_MB} MB")
    name = (upload.name or "archivo").replace("\\", "/").split("/")[-1][:200]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationFailed("Tipo de archivo no permitido")
    att = Attachment(
        issue=issue, filename=name, size=upload.size,
        mime_type=(upload.content_type or "application/octet-stream")[:120],
        uploaded_by=actor,
    )
    att.file.save(name, upload, save=False)
    att.save()
    IssueHistory.objects.create(
        issue=issue, actor=actor,
        items=[{"field": "attachment", "from": None, "from_display": None,
                "to": att.id, "to_display": name}],
    )
    events.publish_project(issue.project_id, "issue.updated",
                           {"id": issue.id, "key": issue.key, "fields": ["attachment"]},
                           actor_id=actor.id)
    return att


@transaction.atomic
def delete_attachment(actor, att: Attachment) -> None:
    issue = att.issue
    if att.uploaded_by_id != actor.id:
        require(actor, issue.project, Perm.DELETE_ALL_ATTACHMENTS)
    else:
        require(actor, issue.project, Perm.CREATE_ATTACHMENTS)
    _ensure_active(issue)
    name = att.filename
    att.file.delete(save=False)
    att.delete()
    IssueHistory.objects.create(
        issue=issue, actor=actor,
        items=[{"field": "attachment", "from": None, "from_display": name,
                "to": None, "to_display": None}],
    )
    events.publish_project(issue.project_id, "issue.updated",
                           {"id": issue.id, "key": issue.key, "fields": ["attachment"]},
                           actor_id=actor.id)


# --------------------------------------------------------------------------- links

@transaction.atomic
def link_issues(actor, source: Issue, target: Issue, link_type: IssueLinkType) -> IssueLink:
    require(actor, source.project, Perm.LINK_ISSUES)
    require(actor, target.project, Perm.BROWSE)
    if source.id == target.id:
        raise ValidationFailed("No se puede vincular una incidencia consigo misma")
    _ensure_active(source, target)
    link, created = IssueLink.objects.get_or_create(
        link_type=link_type, source=source, target=target, defaults={"created_by": actor}
    )
    if created:
        for issue, other, label in ((source, target, link_type.outward),
                                    (target, source, link_type.inward)):
            IssueHistory.objects.create(
                issue=issue, actor=actor,
                items=[{"field": "link", "from": None, "from_display": None,
                        "to": other.id, "to_display": f"{label} {other.key}"}],
            )
            events.publish_project(issue.project_id, "issue.updated",
                                   {"id": issue.id, "key": issue.key, "fields": ["links"]},
                                   actor_id=actor.id)
    return link


@transaction.atomic
def unlink(actor, link: IssueLink) -> None:
    require(actor, link.source.project, Perm.LINK_ISSUES)
    _ensure_active(link.source, link.target)
    for issue, other, label in ((link.source, link.target, link.link_type.outward),
                                (link.target, link.source, link.link_type.inward)):
        IssueHistory.objects.create(
            issue=issue, actor=actor,
            items=[{"field": "link", "from": other.id, "from_display": f"{label} {other.key}",
                    "to": None, "to_display": None}],
        )
        events.publish_project(issue.project_id, "issue.updated",
                               {"id": issue.id, "key": issue.key, "fields": ["links"]},
                               actor_id=actor.id)
    link.delete()


@transaction.atomic
def add_web_link(actor, issue: Issue, url: str, title: str = "") -> WebLink:
    require(actor, issue.project, Perm.LINK_ISSUES)
    _ensure_active(issue)
    if not url.lower().startswith(("http://", "https://")):
        raise ValidationFailed("La URL debe empezar con http:// o https://")
    wl = WebLink.objects.create(issue=issue, url=url, title=title[:255], created_by=actor)
    events.publish_project(issue.project_id, "issue.updated",
                           {"id": issue.id, "key": issue.key, "fields": ["links"]},
                           actor_id=actor.id)
    return wl


@transaction.atomic
def delete_web_link(actor, wl: WebLink) -> None:
    issue = wl.issue
    require(actor, issue.project, Perm.LINK_ISSUES)
    _ensure_active(issue)
    wl.delete()
    events.publish_project(issue.project_id, "issue.updated",
                           {"id": issue.id, "key": issue.key, "fields": ["links"]},
                           actor_id=actor.id)


# --------------------------------------------------------------------------- worklogs

@transaction.atomic
def log_work(actor, issue: Issue, *, time_spent: int, started_at, comment: str = "",
             remaining: int | None = None) -> Worklog:
    require(actor, issue.project, Perm.LOG_WORK)
    if time_spent <= 0:
        raise ValidationFailed("El tiempo debe ser mayor a cero")
    issue = Issue.objects.select_for_update().get(pk=issue.pk)
    _ensure_active(issue)
    wl = Worklog.objects.create(issue=issue, author=actor, time_spent=time_spent,
                                started_at=started_at, comment=comment)
    old_spent = issue.time_spent
    issue.time_spent += time_spent
    if remaining is not None:
        issue.remaining_estimate = max(0, remaining)
    elif issue.remaining_estimate is not None:
        issue.remaining_estimate = max(0, issue.remaining_estimate - time_spent)
    issue.save(update_fields=["time_spent", "remaining_estimate", "updated_at"])
    IssueHistory.objects.create(issue=issue, actor=actor,
                                items=[_item("time_spent", old_spent, issue.time_spent)])
    events.publish_project(issue.project_id, "issue.updated",
                           {"id": issue.id, "key": issue.key, "fields": ["time_spent"]},
                           actor_id=actor.id)
    return wl


@transaction.atomic
def delete_worklog(actor, wl: Worklog) -> None:
    issue = wl.issue
    if wl.author_id != actor.id:
        require(actor, issue.project, Perm.ADMINISTER)
    else:
        require(actor, issue.project, Perm.LOG_WORK)
    _ensure_active(issue)
    Issue.objects.filter(pk=issue.pk).update(time_spent=max(0, issue.time_spent - wl.time_spent))
    wl.delete()


# --------------------------------------------------------------------------- watchers / votes

def set_watching(actor, issue: Issue, watching: bool, user=None) -> None:
    require(actor, issue.project, Perm.BROWSE)
    target = user or actor
    if target != actor:
        require(actor, issue.project, Perm.ADMINISTER)
    if watching:
        # archived issues are read-only and notify nobody; leaving the watch list stays allowed
        _ensure_active(issue)
        issue.watchers.add(target)
    else:
        issue.watchers.remove(target)


def set_vote(actor, issue: Issue, vote: bool) -> None:
    require(actor, issue.project, Perm.BROWSE)
    _ensure_active(issue)
    if issue.reporter_id == actor.id:
        raise ValidationFailed("No puedes votar por tu propia incidencia")
    if vote:
        issue.voters.add(actor)
    else:
        issue.voters.remove(actor)


# --------------------------------------------------------------------------- clone

@transaction.atomic
def clone_issue(actor, issue: Issue, summary: str | None = None) -> Issue:
    _ensure_active(issue)  # the clone gets linked to the original, which is read-only
    data = IssueInput(
        issue_type_id=issue.issue_type_id,
        summary=(summary or f"CLONAR - {issue.summary}")[:255],
        description=issue.description,
        priority_id=issue.priority_id,
        assignee_id=issue.assignee_id,
        parent_id=issue.parent_id,
        labels=list(issue.labels),
        component_ids=list(issue.components.values_list("id", flat=True)),
        fix_version_ids=list(issue.fix_versions.values_list("id", flat=True)),
        affects_version_ids=list(issue.affects_versions.values_list("id", flat=True)),
        story_points=issue.story_points,
        original_estimate=issue.original_estimate,
        due_date=issue.due_date,
        custom_fields=issue.custom_fields,
        team_id=issue.team_id if issue.team and not issue.team.is_deleted else None,
    )
    clone = create_issue(actor, issue.project, data, mode="clone")
    clone_type = IssueLinkType.objects.filter(is_clone=True).order_by("id").first()
    if clone_type:
        link_issues(actor, clone, issue, clone_type)
    return clone


# --------------------------------------------------------------------------- archive

@transaction.atomic
def archive_issue(actor, issue: Issue) -> Issue:
    """Archive an issue and its subtasks (read-only, hidden from boards and search)."""
    require(actor, issue.project, Perm.ADMINISTER)
    if issue.is_archived:
        return issue
    is_sub = issue.issue_type.level == IssueType.Level.SUBTASK
    if issue.parent_id and is_sub and not issue.parent.is_archived:
        raise ValidationFailed("Archiva la incidencia principal; sus subtareas la siguen",
                               code="archived")
    now = timezone.now()
    ids = [issue.id, *Issue.objects.filter(
        parent=issue, issue_type__level=IssueType.Level.SUBTASK).values_list("id", flat=True)]
    # Only the issue and its subtasks are archived. Children of an epic keep their parent
    # link (they show the epic as archived) so restoring the epic brings the hierarchy back.
    Issue.objects.filter(id__in=ids).update(is_archived=True, archived_at=now,
                                            archived_by=actor, sprint=None)
    for iid in ids:
        IssueHistory.objects.create(issue_id=iid, actor=actor, items=[
            {"field": "archived", "from": False, "to": True, "from_display": "No",
             "to_display": "Sí"}])
    events.publish_project(issue.project_id, "issue.deleted", {"id": issue.id, "key": issue.key},
                           actor_id=actor.id)
    issue.refresh_from_db()
    return issue


@transaction.atomic
def restore_issue(actor, issue: Issue) -> Issue:
    require(actor, issue.project, Perm.ADMINISTER)
    if not issue.is_archived:
        return issue
    if issue.parent_id and issue.parent.is_archived and \
            issue.issue_type.level == IssueType.Level.SUBTASK:
        raise ValidationFailed(f"Restaura primero {issue.parent.key}", code="archived")
    Project.objects.select_for_update().filter(pk=issue.project_id).first()  # serialize ranks
    ids = [issue.id, *Issue.objects.filter(parent=issue, is_archived=True,
                                           issue_type__level=IssueType.Level.SUBTASK)
           .order_by("rank", "id").values_list("id", flat=True)]
    # each restored issue goes to the end of the backlog with its own, increasing rank
    rank = Issue.objects.filter(project_id=issue.project_id).aggregate(m=Max("rank"))["m"]
    for iid in ids:
        rank = key_between(rank, None)
        Issue.objects.filter(pk=iid).update(is_archived=False, archived_at=None,
                                            archived_by=None, rank=rank)
    for iid in ids:
        IssueHistory.objects.create(issue_id=iid, actor=actor, items=[
            {"field": "archived", "from": True, "to": False, "from_display": "Sí",
             "to_display": "No"}])
    events.publish_project(issue.project_id, "issue.created", {"id": issue.id, "key": issue.key},
                           actor_id=actor.id)
    issue.refresh_from_db()
    return issue


# --------------------------------------------------------------------------- move

def _target_type(target: Project, issue: Issue, type_map: dict) -> IssueType:
    wanted = type_map.get(str(issue.issue_type_id)) or type_map.get(issue.issue_type_id)
    if wanted:
        t = target.issue_types.filter(pk=wanted).first()
        if t is None:
            raise ValidationFailed("Tipo de incidencia no válido en el proyecto destino",
                                   code="issue_type")
        if t.level != issue.issue_type.level:
            raise ValidationFailed(f"{issue.key}: el tipo destino debe ser del mismo nivel "
                                   f"({issue.issue_type.get_level_display()})", code="issue_type")
        return t
    if target.issue_types.filter(pk=issue.issue_type_id).exists():
        return issue.issue_type
    same_level = target.issue_types.filter(level=issue.issue_type.level).first()
    if same_level is None:
        raise ValidationFailed(
            f"{target.key} no tiene un tipo de nivel {issue.issue_type.get_level_display()}",
            code="issue_type",
        )
    return same_level


@transaction.atomic
def move_issue(actor, issue: Issue, target: Project, *, type_map: dict | None = None,
               status_map: dict | None = None, keep_children: Collection[int] = (),
               fields: dict | None = None, fields_mode: str = "strict",
               _with_parent: bool = False) -> Issue:
    """Move an issue (and its subtasks) to another project. It gets a new key; the old one
    keeps resolving through IssueKeyAlias.

    The issue must satisfy the create rules of the target project and type (its required
    fields on the create screen, fieldrules.check_move); `fields` (PATCH format) fills the
    missing ones and is applied to every moved issue where the field exists and is visible.

    The parent link survives only when the parent already lives in the target project (for
    instance an epic moved earlier in the same bulk operation). When moving an epic, its
    children listed in `keep_children` stay linked because they are about to be moved too;
    see `move_issues`."""
    from apps.boards.services import track_issue_sprint_change

    from .models import IssueKeyAlias

    type_map, status_map = type_map or {}, status_map or {}
    issue = Issue.objects.select_for_update(of=("self",)).select_related(
        "project", "issue_type", "status", "sprint", "parent", "parent__issue_type"
    ).get(pk=issue.pk)
    source = issue.project
    _ensure_active(issue)
    if source.id == target.id:
        raise ValidationFailed("La incidencia ya está en ese proyecto", code="project")
    if issue.issue_type.level == IssueType.Level.SUBTASK and not _with_parent:
        raise ValidationFailed("Las subtareas se mueven junto con su principal", code="project")
    require(actor, source, Perm.EDIT_ISSUES)
    require(actor, source, Perm.DELETE_ISSUES)
    require(actor, target, Perm.CREATE_ISSUES)
    target = Project.objects.select_for_update().get(pk=target.pk)

    new_type = _target_type(target, issue, type_map)
    wf = workflow_for(target, new_type)
    status = issue.status
    mapped = status_map.get(str(issue.status_id)) or status_map.get(issue.status_id)
    if mapped:
        status = wf.statuses.filter(pk=mapped).first() or wf.initial_status
    elif not wf.statuses.filter(pk=issue.status_id).exists():
        status = wf.statuses.filter(category=issue.status.category).first() or wf.initial_status

    old_key, old_sprint, old_points = issue.key, issue.sprint, issue.story_points
    target.issue_counter += 1
    target.save(update_fields=["issue_counter", "updated_at"])
    items = [
        _item("project", source, target),
        {"field": "key", "from": old_key, "from_display": old_key,
         "to": f"{target.key}-{target.issue_counter}",
         "to_display": f"{target.key}-{target.issue_counter}"},
    ]
    if new_type.id != issue.issue_type_id:
        items.append(_item("issue_type", issue.issue_type, new_type))
    if status.id != issue.status_id:
        items.append(_item("status", issue.status, status))
        issue.status_changed_at = timezone.now()

    # project-scoped references: map by name, drop the rest
    comps = list(Component.objects.filter(
        project=target, name__in=issue.components.values_list("name", flat=True)))
    fixv = list(Version.objects.filter(
        project=target, name__in=issue.fix_versions.values_list("name", flat=True)))
    affv = list(Version.objects.filter(
        project=target, name__in=issue.affects_versions.values_list("name", flat=True)))
    if not _with_parent and issue.parent_id and issue.parent.project_id != target.id:
        items.append(_item("parent", issue.parent, None))
        issue.parent = None
    cf_allowed = {
        str(i) for i in CustomField.objects.filter(
            id__in=[int(k) for k in issue.custom_fields if str(k).isdigit()]
        ).filter(Q(projects__isnull=True) | Q(projects=target)).values_list("id", flat=True)
    }

    IssueKeyAlias.objects.filter(key=f"{target.key}-{target.issue_counter}").delete()
    IssueKeyAlias.objects.create(key=old_key, issue=issue)
    issue.project = target
    issue.number = target.issue_counter
    issue.key = f"{target.key}-{target.issue_counter}"
    issue.issue_type = new_type
    issue.status = status
    issue.sprint = None
    issue.rank = _end_rank(target)
    issue.custom_fields = {k: v for k, v in issue.custom_fields.items() if k in cf_allowed}
    if status.category == StatusCategory.DONE and issue.resolution_id is None:
        issue.resolution = Resolution.objects.filter(is_default=True).first()
        issue.resolved_at = timezone.now()
    elif status.category != StatusCategory.DONE:
        issue.resolution, issue.resolved_at = None, None
    if issue.assignee_id and not assignable_users(target).filter(pk=issue.assignee_id).exists():
        items.append(_item("assignee", issue.assignee, None))
        issue.assignee = None
    rules = fieldrules.resolve(target, new_type)
    after = {"components": comps, "fix_versions": fixv, "affects_versions": affv}
    extra = fieldrules.movable_values(
        rules, fieldrules.normalize(fields), mode="lenient" if _with_parent else fields_mode,
        current=lambda key: fieldrules.issue_value(issue, key, after))
    if extra:  # filling fields is an edit in the target project: same permissions
        require(actor, target, Perm.EDIT_ISSUES)
        if extra.get("assignee") is not None:
            require(actor, target, Perm.ASSIGN_ISSUES)
    fieldrules.check_move(old_key, rules, target, new_type, value=lambda key: extra[key]
                          if key in extra else fieldrules.issue_value(issue, key, after))
    issue.save()
    issue.components.set(comps)
    issue.fix_versions.set(fixv)
    issue.affects_versions.set(affv)
    if issue.issue_type.level == IssueType.Level.EPIC:
        Issue.objects.filter(parent=issue).exclude(project=target) \
            .exclude(id__in=list(keep_children)).update(parent=None)
    IssueHistory.objects.create(issue=issue, actor=actor, items=items)
    update_search_vector([issue.id])
    track_issue_sprint_change(issue, old_sprint, old_points)
    if extra:
        update_issue(actor, issue, fieldrules.to_patch(extra), mode="move")
        issue.refresh_from_db()

    for sub in Issue.objects.filter(parent=issue, issue_type__level=IssueType.Level.SUBTASK) \
            .exclude(project=target):
        move_issue(actor, sub, target, type_map=type_map, status_map=status_map,
                   fields=fields, _with_parent=True)

    payload = {"id": issue.id, "key": issue.key, "old_key": old_key}
    events.publish_project(source.id, "issue.deleted", payload, actor_id=actor.id)
    events.publish_project(target.id, "issue.created", payload, actor_id=actor.id)
    _notify(actor, issue, "issue_updated", data={"fields": ["project"], "old_key": old_key})
    return issue


def move_issues(actor, issues: Iterable[Issue], target: Project, *,
                type_map: dict | None = None, status_map: dict | None = None,
                fields: dict | None = None, on_error=None) -> list[Issue]:
    """Move several issues, each one on its own (a failure does not stop the rest).

    Epics go first, then standard issues, then subtasks. Children selected together with
    their epic keep the link to the (already moved) epic; subtasks travel with their parent.
    If a child fails to move after its epic did, it is detached so no parent link crosses
    projects. `on_error(issue, exc)` receives each ApiError / DoesNotExist; returns the moved
    top-level issues in processing order."""
    from apps.core.errors import ApiError

    selected = {i.id: i for i in issues}
    order = sorted(selected.values(), key=lambda i: (-i.issue_type.level, i.id))
    moved: list[Issue] = []
    moved_along: set[int] = set()
    for issue in order:
        if issue.id in moved_along:
            continue  # already moved together with its parent
        try:
            result = move_issue(actor, issue, target, type_map=type_map, status_map=status_map,
                                keep_children=selected.keys(), fields=fields,
                                fields_mode="fill")
        except (ApiError, Issue.DoesNotExist) as e:
            if on_error is None:
                raise
            on_error(issue, e)
            continue
        moved_along.update(Issue.objects.filter(
            parent=result, issue_type__level=IssueType.Level.SUBTASK).values_list("id", flat=True))
        moved.append(result)
    _detach_cross_project_parents(actor, selected.keys())
    return moved


@transaction.atomic
def _detach_cross_project_parents(actor, issue_ids: Collection[int]) -> None:
    stranded = Issue.objects.select_related("parent").filter(
        id__in=list(issue_ids), parent__isnull=False).exclude(parent__project=F("project"))
    for issue in stranded:
        IssueHistory.objects.create(issue=issue, actor=actor,
                                    items=[_item("parent", issue.parent, None)])
        Issue.objects.filter(pk=issue.pk).update(parent=None)
        events.publish_project(issue.project_id, "issue.updated",
                               {"id": issue.id, "key": issue.key, "fields": ["parent"]},
                               actor_id=actor.id)


# --------------------------------------------------------------------------- notifications

def _automation(trigger: str, issue: Issue, actor, context: dict | None = None) -> None:
    from apps.automation.engine import dispatch

    dispatch(trigger, issue, actor, context)


def _notify(actor, issue: Issue, event: str, *, recipients: set[int] | None = None,
            mentioned: set[int] | None = None, data: dict | None = None) -> None:
    from apps.notifications.services import queue_notifications

    if recipients is None:
        recipients = set(issue.watchers.values_list("id", flat=True))
        for uid in (issue.assignee_id, issue.reporter_id):
            if uid:
                recipients.add(uid)
    queue_notifications(
        actor_id=actor.id, issue_id=issue.id, event=event,
        recipients=recipients, mentioned=mentioned or set(), data=data or {},
    )


def get_issue_or_404(actor, key_or_id: str | int) -> Issue:
    qs = Issue.objects.select_related(
        "project", "issue_type", "status", "priority", "assignee", "reporter", "resolution",
        "parent", "parent__issue_type", "parent__status", "sprint",
    )
    s = str(key_or_id)
    issue = qs.filter(pk=int(s)).first() if s.isdigit() else qs.filter(key=s.upper()).first()
    if issue is None and not s.isdigit():
        from .models import IssueKeyAlias

        alias = IssueKeyAlias.objects.filter(key=s.upper()).values_list("issue_id", flat=True)
        issue = qs.filter(pk__in=alias).first()
    if issue is None or not has_perm(actor, issue.project, Perm.BROWSE):
        raise NotFound("Incidencia no encontrada")
    return issue


__all__ = [
    "IssueInput", "create_issue", "update_issue", "transition_issue", "available_transitions",
    "rank_issues", "delete_issue", "add_comment", "edit_comment", "delete_comment",
    "add_attachment", "delete_attachment", "link_issues", "unlink", "add_web_link",
    "delete_web_link", "log_work", "delete_worklog", "set_watching", "set_vote", "clone_issue",
    "get_issue_or_404", "move_issue", "move_issues", "archive_issue", "restore_issue",
    "workflow_for", "Status",
]
