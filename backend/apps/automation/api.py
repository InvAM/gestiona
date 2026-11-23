from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import UserRef, user_ref
from apps.projects.models import Perm, Project
from apps.projects.permissions import has_perm, require

from . import engine
from .models import AutomationLog, AutomationRule, Trigger

router = Router(tags=["automation"])


class RuleIn(Schema):
    name: str
    description: str = ""
    enabled: bool = True
    trigger: str
    trigger_config: dict = {}
    conditions: list[dict] = []
    actions: list[dict]
    allow_rule_triggers: bool = False


class RuleOut(Schema):
    id: int
    name: str
    description: str
    project_key: str | None
    enabled: bool
    trigger: str
    trigger_display: str
    trigger_config: dict
    conditions: list[dict]
    actions: list[dict]
    allow_rule_triggers: bool
    created_by: UserRef | None
    run_count: int
    last_run_at: str | None
    next_run_at: str | None
    last_status: str | None
    updated_at: str
    deleted_at: str | None = None


class RuleLogOut(Schema):
    id: int
    rule_id: int
    rule_name: str
    issue_key: str
    status: str
    message: str
    actions_done: list[str]
    duration_ms: int
    created_at: str


class ManualRuleOut(Schema):
    id: int
    name: str


class TemplateTypeOption(Schema):
    id: int
    name: str
    jql_value: str


class TemplateParamOut(Schema):
    key: str
    label: str
    kind: str
    token: str
    levels: list[int]
    options: list[TemplateTypeOption]
    value: int | None
    jql_value: str | None


class RuleTemplateOut(Schema):
    key: str
    name: str
    description: str
    params: list[TemplateParamOut]
    ready: bool
    draft: dict | None
    draft_template: dict


def _iso(d):
    return d.isoformat() if d else None


def _out(r: AutomationRule) -> dict:
    last = r.logs.values_list("status", flat=True).first()
    return {
        "id": r.id, "name": r.name, "description": r.description,
        "project_key": r.project.key if r.project else None, "enabled": r.enabled,
        "trigger": r.trigger, "trigger_display": r.get_trigger_display(),
        "trigger_config": r.trigger_config, "conditions": r.conditions, "actions": r.actions,
        "allow_rule_triggers": r.allow_rule_triggers, "created_by": user_ref(r.created_by),
        "run_count": r.run_count, "last_run_at": _iso(r.last_run_at),
        "next_run_at": _iso(r.next_run_at), "last_status": last,
        "updated_at": r.updated_at.isoformat(), "deleted_at": _iso(r.deleted_at),
    }


def _log_out(entry: AutomationLog) -> dict:
    return {
        "id": entry.id, "rule_id": entry.rule_id, "rule_name": entry.rule.name,
        "issue_key": entry.issue_key, "status": entry.status, "message": entry.message,
        "actions_done": entry.actions_done, "duration_ms": entry.duration_ms,
        "created_at": entry.created_at.isoformat(),
    }


def _scope(user, project_key: str | None) -> Project | None:
    """Project rules need project admin; global rules need system admin."""
    if project_key:
        project = Project.objects.filter(key=project_key.upper()).first()
        if project is None:
            raise NotFound("Proyecto no encontrado")
        require(user, project, Perm.ADMINISTER)
        return project
    if not (user.is_staff or user.is_superuser):
        raise Forbidden("Solo los administradores pueden gestionar reglas globales")
    return None


def _rule(user, rule_id: int, *, deleted: bool = False) -> AutomationRule:
    base = AutomationRule.all_objects.deleted() if deleted else AutomationRule.objects
    rule = get_object_or_404(base.select_related("project", "created_by"), pk=rule_id)
    _scope(user, rule.project.key if rule.project else None)
    return rule


@router.get("/automation/templates", response=list[RuleTemplateOut])
def list_templates(request, project: str | None = None):
    """Rule templates built with the project's real types/statuses (see templates.py)."""
    from .templates import build_templates

    return build_templates(_scope(request.user, project))


@router.get("/automation/rules", response=list[RuleOut])
def list_rules(request, project: str | None = None, deleted: bool = False):
    """`deleted=true` lists the papelera (project admin / system admin for global rules)."""
    scope = _scope(request.user, project)
    base = AutomationRule.all_objects.deleted() if deleted else AutomationRule.objects
    qs = base.select_related("project", "created_by")
    qs = qs.filter(project=scope) if scope else qs.filter(project__isnull=True)
    return [_out(r) for r in qs]


@router.post("/automation/rules", response={201: RuleOut})
def create_rule(request, data: RuleIn, project: str | None = None):
    scope = _scope(request.user, project)
    clean = engine.validate_rule(data.dict(), project=scope, user=request.user)
    rule = AutomationRule.objects.create(project=scope, created_by=request.user, **clean)
    if rule.trigger == Trigger.SCHEDULED:
        from django.utils import timezone

        rule.next_run_at = engine.next_run(rule.trigger_config, timezone.now())
        rule.save(update_fields=["next_run_at"])
    return 201, _out(rule)


@router.get("/automation/rules/{rule_id}", response=RuleOut)
def get_rule(request, rule_id: int):
    return _out(_rule(request.user, rule_id))


@router.put("/automation/rules/{rule_id}", response=RuleOut)
def update_rule(request, rule_id: int, data: RuleIn):
    from django.utils import timezone

    rule = _rule(request.user, rule_id)
    clean = engine.validate_rule(data.dict(), project=rule.project, user=request.user)
    for k, v in clean.items():
        setattr(rule, k, v)
    rule.next_run_at = engine.next_run(rule.trigger_config, timezone.now()) \
        if rule.trigger == Trigger.SCHEDULED else None
    rule.save()
    return _out(rule)


class ToggleIn(Schema):
    enabled: bool


@router.post("/automation/rules/{rule_id}/enabled", response=RuleOut)
def toggle_rule(request, rule_id: int, data: ToggleIn):
    rule = _rule(request.user, rule_id)
    rule.enabled = data.enabled
    rule.save(update_fields=["enabled", "updated_at"])
    return _out(rule)


@router.delete("/automation/rules/{rule_id}", response={204: None})
def delete_rule(request, rule_id: int):
    """Soft delete: the rule stops running; its audit log is kept."""
    _rule(request.user, rule_id).soft_delete()
    return 204, None


@router.post("/automation/rules/{rule_id}/restore", response=RuleOut)
def restore_rule(request, rule_id: int):
    from django.utils import timezone

    rule = _rule(request.user, rule_id, deleted=True)
    softdelete.restore(rule)
    if rule.trigger == Trigger.SCHEDULED:
        rule.next_run_at = engine.next_run(rule.trigger_config, timezone.now())
        rule.save(update_fields=["next_run_at"])
    return _out(rule)


@router.get("/automation/logs", response=list[RuleLogOut])
def list_logs(request, project: str | None = None, rule_id: int | None = None,
              limit: int = 100):
    scope = _scope(request.user, project)
    qs = AutomationLog.objects.select_related("rule")
    qs = qs.filter(rule__project=scope) if scope else qs.filter(rule__project__isnull=True)
    if rule_id:
        qs = qs.filter(rule_id=rule_id)
    return [_log_out(e) for e in qs[: min(limit, 500)]]


@router.get("/issues/{key}/automation", response=list[ManualRuleOut])
def manual_rules(request, key: str):
    from apps.issues.services import get_issue_or_404

    issue = get_issue_or_404(request.user, key)
    if not has_perm(request.user, issue.project, Perm.EDIT_ISSUES):
        return []
    qs = AutomationRule.objects.filter(enabled=True, trigger=Trigger.MANUAL).filter(
        Q(project=issue.project) | Q(project__isnull=True))
    return [{"id": r.id, "name": r.name} for r in qs]


@router.post("/issues/{key}/automation/{rule_id}", response=RuleLogOut)
def run_manual(request, key: str, rule_id: int):
    from apps.issues.services import get_issue_or_404

    issue = get_issue_or_404(request.user, key)
    require(request.user, issue.project, Perm.EDIT_ISSUES)
    rule = AutomationRule.objects.filter(
        Q(project=issue.project) | Q(project__isnull=True), pk=rule_id, enabled=True,
        trigger=Trigger.MANUAL,
    ).first()
    if rule is None:
        raise NotFound("Regla no encontrada")
    entry = engine.execute_rule(rule, issue, request.user, {"manual": True})
    if entry is None:  # pragma: no cover - manual rules have no trigger filter
        raise ValidationFailed("La regla no aplica")
    return _log_out(entry)
