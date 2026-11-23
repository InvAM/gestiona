"""GET /meta — the single source of truth for the choices/enums the UI needs.

Labels live here (Spanish), the frontend must not keep its own copies. Everything is read
from the models / engine constants, so adding a value to an enum shows up automatically.
"""

from __future__ import annotations

from ninja import Router, Schema

from apps.analytics.schemas import AnalyticsMetaOut
from apps.analytics.scope import analytics_meta
from apps.automation.api import RuleTemplateOut

router = Router(tags=["meta"])


class MetaChoice(Schema):
    value: str
    label: str
    description: str = ""


class MetaIntChoice(Schema):
    value: int
    label: str


class MetaActionChoice(MetaChoice):
    admin_only: bool = False


class MetaGroupByChoice(MetaChoice):
    two_d: bool = True  # usable as an axis of the two-dimensional table


class MetaFormFieldChoice(MetaChoice):
    always_required: bool = False


class MetaPermissionChoice(MetaChoice):
    always: bool = False  # granted to every role


class MetaFieldKindChoice(MetaChoice):
    has_options: bool = False


class MetaSystemFieldChoice(MetaChoice):
    kind: str
    locked: bool = False  # always required, never hidden (summary, issue type)


class MetaAutomationOut(Schema):
    triggers: list[MetaChoice]
    conditions: list[MetaChoice]
    actions: list[MetaActionChoice]
    editable_fields: list[MetaChoice]
    edit_action_fields: list[MetaChoice]
    assign_to: list[MetaChoice]
    notify_to: list[MetaChoice]
    action_targets: list[MetaChoice]
    schedule_every: list[MetaChoice]
    weekdays: list[MetaIntChoice]
    variables: list[MetaChoice]
    log_statuses: list[MetaChoice]
    templates: list[RuleTemplateOut]


class MetaPlansOut(Schema):
    access: list[MetaChoice]
    estimations: list[MetaChoice]
    capacity_modes: list[MetaChoice]


def plans_meta() -> dict:
    from apps.plans.models import Plan

    return {
        "access": choices(Plan.Access, {
            Plan.Access.PRIVATE: "Solo tú",
            Plan.Access.SHARED: "Tú y los usuarios que elijas",
            Plan.Access.PUBLIC: "Cualquier usuario con sesión",
        }),
        "estimations": choices(Plan.Estimation),
        "capacity_modes": [
            {"value": "sprints", "label": "Sprints del tablero",
             "description": "Las iteraciones son los sprints del tablero del equipo"},
            {"value": "fixed", "label": "Iteraciones fijas",
             "description": "Iteraciones de longitud fija definidas en el plan"},
        ],
    }


class MetaOut(Schema):
    automation: MetaAutomationOut
    gadget_kinds: list[MetaChoice]
    group_by_fields: list[MetaGroupByChoice]
    form_builtin_fields: list[MetaFormFieldChoice]
    audit_categories: list[MetaChoice]
    permissions: list[MetaPermissionChoice]
    status_categories: list[MetaChoice]
    issue_type_levels: list[MetaIntChoice]
    custom_field_kinds: list[MetaFieldKindChoice]
    issue_fields: list[MetaChoice]
    project_templates: list[MetaChoice]
    project_access: list[MetaChoice]
    project_default_assignee: list[MetaChoice]
    version_statuses: list[MetaChoice]
    board_kinds: list[MetaChoice]
    board_swimlanes: list[MetaChoice]
    board_estimations: list[MetaChoice]
    sprint_states: list[MetaChoice]
    dashboard_visibility: list[MetaChoice]
    filter_visibility: list[MetaChoice]
    form_access: list[MetaChoice]
    notification_events: list[MetaChoice]
    analytics: AnalyticsMetaOut
    plans: MetaPlansOut
    screen_operations: list[MetaChoice]
    system_fields: list[MetaSystemFieldChoice]


def choices(enum, descriptions: dict | None = None) -> list[dict]:
    descriptions = descriptions or {}
    return [{"value": c.value, "label": str(c.label), "description": descriptions.get(c, "")}
            for c in enum]


def int_choices(enum) -> list[dict]:
    return [{"value": int(c.value), "label": str(c.label)} for c in enum]


def automation_meta(project=None) -> dict:
    from apps.automation.models import (
        ADMIN_ONLY_ACTIONS,
        TEMPLATE_VARIABLES,
        TRIGGER_DESCRIPTIONS,
        WEEKDAYS,
        ActionTarget,
        ActionType,
        AssignTo,
        AutomationLog,
        ConditionType,
        EditActionField,
        NotifyTo,
        ScheduleEvery,
        Trigger,
        WatchedField,
    )
    from apps.automation.templates import build_templates

    return {
        "triggers": choices(Trigger, TRIGGER_DESCRIPTIONS),
        "conditions": choices(ConditionType),
        "actions": [{**c, "admin_only": c["value"] in ADMIN_ONLY_ACTIONS}
                    for c in choices(ActionType)],
        "editable_fields": choices(WatchedField),
        "edit_action_fields": choices(EditActionField),
        "assign_to": choices(AssignTo),
        "notify_to": choices(NotifyTo),
        "action_targets": choices(ActionTarget),
        "schedule_every": choices(ScheduleEvery),
        "weekdays": [{"value": i, "label": d} for i, d in enumerate(WEEKDAYS)],
        "variables": [{"value": v, "label": label, "description": ""}
                      for v, label in TEMPLATE_VARIABLES],
        "log_statuses": choices(AutomationLog.Status),
        "templates": build_templates(project),
    }


@router.get("/meta", response=MetaOut)
def meta(request, project: str | None = None):
    """Choices for every enum the UI renders. `project` (key) builds the automation
    templates with that project's types and statuses; without it they use global data."""
    from apps.audit.models import AuditEntry
    from apps.boards.models import Board, Sprint
    from apps.dashboards.gadgets import GADGET_DESCRIPTIONS, GROUP_FIELD_LABELS, NOT_TWO_D
    from apps.dashboards.models import Dashboard
    from apps.forms.api import BUILTIN as FORM_BUILTIN
    from apps.forms.models import IssueForm
    from apps.issues import fieldrules
    from apps.issues.models import HISTORY_FIELD_LABELS, CustomField, IssueType
    from apps.notifications.models import Event
    from apps.projects.models import Perm, Project, Version
    from apps.projects.permissions import require
    from apps.search.models import SavedFilter
    from apps.workflows.api import OPTION_KINDS
    from apps.workflows.models import StatusCategory

    from .errors import NotFound

    scope = None
    if project:
        scope = Project.objects.filter(key=project.upper()).first()
        if scope is None:
            raise NotFound("Proyecto no encontrado")
        require(request.user, scope, Perm.BROWSE)

    return {
        "automation": automation_meta(scope),
        "gadget_kinds": [{"value": k.value, "label": str(k.label), "description": d}
                         for k, d in GADGET_DESCRIPTIONS.items()],
        "group_by_fields": [{"value": k, "label": label, "description": "",
                             "two_d": k not in NOT_TWO_D}
                            for k, label in GROUP_FIELD_LABELS.items()],
        "form_builtin_fields": [{"value": k, "label": label, "description": "",
                                 "always_required": k == "summary"}
                                for k, label in FORM_BUILTIN.items()],
        "audit_categories": choices(AuditEntry.Category),
        "permissions": [{**c, "always": c["value"] == Perm.BROWSE} for c in choices(Perm)],
        "status_categories": choices(StatusCategory),
        "issue_type_levels": int_choices(IssueType.Level),
        "custom_field_kinds": [{**c, "has_options": c["value"] in OPTION_KINDS}
                               for c in choices(CustomField.Kind)],
        "issue_fields": [{"value": k, "label": v, "description": ""}
                         for k, v in HISTORY_FIELD_LABELS.items()],
        "project_templates": choices(Project.Template),
        "project_access": choices(Project.Access),
        "project_default_assignee": choices(Project.DefaultAssignee),
        "version_statuses": choices(Version.Status),
        "board_kinds": choices(Board.Kind),
        "board_swimlanes": choices(Board.Swimlanes),
        "board_estimations": choices(Board.Estimation),
        "sprint_states": choices(Sprint.State),
        "dashboard_visibility": choices(Dashboard.Visibility),
        "filter_visibility": choices(SavedFilter.Visibility),
        "form_access": choices(IssueForm.Access),
        "notification_events": choices(Event),
        "analytics": analytics_meta(),
        "plans": plans_meta(),
        "screen_operations": [{"value": k, "label": v, "description": ""}
                              for k, v in fieldrules.OPERATION_LABELS.items()],
        "system_fields": [{"value": k, "label": label, "description": "", "kind": kind,
                           "locked": k in fieldrules.LOCKED}
                          for k, label, kind in fieldrules.SYSTEM_FIELDS],
    }
