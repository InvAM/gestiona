"""Automation engine: "when X happens, if Y, then do Z".

Services call `dispatch()` after a change; matching rules run in a Celery task after commit,
acting as the "Automatización" bot user (no login, full project permissions). Loops are
prevented by ignoring bot-made changes unless a rule opts in, plus a hard depth limit.
"""

from __future__ import annotations

import logging
import re
import time
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.core.errors import ApiError, ValidationFailed

from .models import AutomationLog, AutomationRule, Trigger

log = logging.getLogger(__name__)
User = get_user_model()

BOT_EMAIL = "automatizacion@gestiona.invalid"
MAX_DEPTH = 5
SCHEDULED_LIMIT = 500
_depth: ContextVar[int] = ContextVar("gestiona_automation_depth", default=0)
# While a rule runs, events it causes are collected here and queued once at the end, so a
# rule that edits an issue three times fires downstream rules once (no 2^n fan-out).
_buffer: ContextVar[dict | None] = ContextVar("gestiona_automation_buffer", default=None)

ACTION_TYPES = {
    "transition", "assign", "edit", "comment", "create_subtasks", "notify", "add_watcher",
    "webhook",
}
CONDITION_TYPES = {"jql", "children_done"}
ASSIGN_TO = {"user", "reporter", "trigger_user", "lead", "unassigned"}
NOTIFY_TO = {"assignee", "reporter", "watchers", "trigger_user"}


# --------------------------------------------------------------------------- bot user

def bot_user():
    user = User.objects.filter(email=BOT_EMAIL).first()
    if user is None:
        user = User(email=BOT_EMAIL, full_name="Automatización", is_bot=True, is_active=True)
        user.set_unusable_password()
        user.save()
    return user


# --------------------------------------------------------------------------- dispatch

def dispatch(trigger: str, issue, actor, context: dict | None = None) -> None:
    """Queue the rules listening to `trigger` for this issue (runs after commit)."""
    if getattr(issue, "is_archived", False):
        return  # archived issues are read-only: no automation runs on them
    depth = _depth.get()
    if depth >= MAX_DEPTH:
        log.warning("automation depth limit reached for %s on %s", trigger, issue.key)
        return
    qs = AutomationRule.objects.filter(enabled=True, trigger=trigger).filter(
        Q(project_id=issue.project_id) | Q(project__isnull=True)
    )
    if getattr(actor, "is_bot", False):
        qs = qs.filter(allow_rule_triggers=True)
    ids = list(qs.values_list("id", flat=True))
    if not ids:
        return
    payload = {"rule_ids": ids, "issue_id": issue.id, "actor_id": actor.id if actor else None,
               "context": dict(context or {}), "depth": depth + 1}
    buffer = _buffer.get()
    if buffer is not None:
        key = (trigger, issue.id)
        if key in buffer:
            prev = buffer[key]["context"]
            if "fields" in payload["context"]:
                prev["fields"] = sorted(set(prev.get("fields") or [])
                                        | set(payload["context"]["fields"]))
            if "to" in payload["context"]:
                prev["to"] = payload["context"]["to"]
        else:
            buffer[key] = payload
        return
    _queue(payload)


def _queue(payload: dict) -> None:
    from .tasks import run_rules

    transaction.on_commit(lambda: run_rules.delay(**payload))


def run_rules(rule_ids: list[int], issue_id: int, actor_id: int | None, context: dict,
              depth: int) -> None:
    from apps.issues.models import Issue

    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    for rule in AutomationRule.objects.filter(id__in=rule_ids, enabled=True).order_by("id"):
        issue = Issue.objects.select_related("project", "issue_type", "status", "parent") \
            .filter(pk=issue_id, is_archived=False).first()
        if issue is None:  # deleted or archived since the event was queued
            return
        execute_rule(rule, issue, actor, context, depth=depth)


# --------------------------------------------------------------------------- execution

def trigger_matches(rule: AutomationRule, context: dict) -> bool:
    cfg = rule.trigger_config or {}
    if rule.trigger == Trigger.ISSUE_TRANSITIONED:
        froms, tos = cfg.get("from_status_ids") or [], cfg.get("to_status_ids") or []
        if froms and context.get("from") not in froms:
            return False
        if tos and context.get("to") not in tos:
            return False
    elif rule.trigger == Trigger.ISSUE_UPDATED:
        fields = set(cfg.get("fields") or [])
        if fields and not fields & set(context.get("fields") or []):
            return False
    return True


def _children_done(issue) -> bool:
    from apps.workflows.models import StatusCategory

    children = issue.children.all()
    return children.exists() and not children.exclude(
        status__category=StatusCategory.DONE).exists()


def conditions_pass(rule: AutomationRule, issue, bot) -> tuple[bool, str]:
    from apps.issues.models import Issue
    from apps.search.jql import compile_jql

    for cond in rule.conditions or []:
        kind = cond.get("type")
        if kind == "jql":
            q = compile_jql(cond.get("jql") or "", user=bot, project=issue.project).q
            if not Issue.objects.filter(pk=issue.pk).filter(q).exists():
                return False, f"No cumple la condición JQL: {cond.get('jql')}"
        elif kind == "children_done":
            target = issue.parent if cond.get("of") == "parent" else issue
            if target is None or not _children_done(target):
                who = "la principal" if cond.get("of") == "parent" else "la incidencia"
                return False, f"No todas las hijas de {who} están listas"
    return True, ""


def execute_rule(rule: AutomationRule, issue, actor, context: dict | None = None, *,
                 depth: int = 1) -> AutomationLog | None:
    context = context or {}
    if not trigger_matches(rule, context):
        return None
    if issue.is_archived:
        return AutomationLog.objects.create(
            rule=rule, issue=issue, issue_key=issue.key, status=AutomationLog.Status.NO_MATCH,
            message="La incidencia está archivada; no se ejecutan acciones",
        )
    bot = bot_user()
    start = time.monotonic()
    token = _depth.set(depth)
    buffer_token = _buffer.set({})
    done: list[str] = []
    status, message = AutomationLog.Status.SUCCESS, ""
    try:
        ok, why = conditions_pass(rule, issue, bot)
        if not ok:
            status, message = AutomationLog.Status.NO_MATCH, why
        else:
            for action in rule.actions or []:
                done.append(run_action(rule, action, issue, actor, bot))
                issue.refresh_from_db()
    except ApiError as e:
        status, message = AutomationLog.Status.FAILURE, e.message
    except Exception as e:  # never let a rule crash the worker silently
        log.exception("automation rule %s failed on %s", rule.pk, issue.key)
        status, message = AutomationLog.Status.FAILURE, getattr(e, "message", None) or str(e)
    finally:
        pending = _buffer.get() or {}
        _buffer.reset(buffer_token)
        _depth.reset(token)
    for payload in pending.values():
        _queue(payload)
    AutomationRule.objects.filter(pk=rule.pk).update(
        run_count=F("run_count") + 1, last_run_at=timezone.now()
    )
    entry = AutomationLog.objects.create(
        rule=rule, issue=issue, issue_key=issue.key, status=status, message=message[:2000],
        actions_done=done, duration_ms=int((time.monotonic() - start) * 1000),
    )
    _prune_logs(rule)
    return entry


def _prune_logs(rule: AutomationRule, keep: int = 500) -> None:
    qs = AutomationLog.objects.filter(rule=rule).values_list("id", flat=True)
    ids = list(qs[keep:keep + 200])
    if ids:
        AutomationLog.objects.filter(id__in=ids).delete()


# --------------------------------------------------------------------------- templates

_VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def render(template: str, issue, actor) -> str:
    values = {
        "issue.key": issue.key, "issue.summary": issue.summary,
        "issue.status": issue.status.name, "issue.priority": issue.priority.name,
        "issue.type": issue.issue_type.name,
        "issue.assignee": issue.assignee.display_name if issue.assignee else "Sin asignar",
        "issue.reporter": issue.reporter.display_name if issue.reporter else "",
        "issue.project": issue.project.name, "issue.project.key": issue.project.key,
        "issue.due_date": issue.due_date.isoformat() if issue.due_date else "",
        "issue.url": f"{settings.FRONTEND_URL}/browse/{issue.key}",
        "trigger.user": actor.display_name if actor else "Automatización",
        "now": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
    }
    return _VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), template or "")


# --------------------------------------------------------------------------- actions

def _target(action: dict, issue):
    if action.get("target") == "parent":
        return issue.parent
    return issue


def run_action(rule: AutomationRule, action: dict, issue, actor, bot) -> str:
    from apps.issues import services
    from apps.issues.models import Issue

    kind = action.get("type")
    target = _target(action, issue)
    if target is None:
        return f"{kind}: la incidencia no tiene principal, se omite"
    target = Issue.objects.select_related("project", "issue_type", "status", "priority",
                                          "assignee", "reporter").get(pk=target.pk)
    if target.is_archived:
        return f"{kind}: {target.key} está archivada, se omite"

    if kind == "transition":
        status_id = int(action["status_id"])
        if target.status_id == status_id:
            return f"{target.key} ya estaba en ese estado"
        services.transition_issue(bot, target, to_status_id=status_id,
                                  resolution_id=action.get("resolution_id"))
        target.refresh_from_db()
        return f"{target.key} → {target.status.name}"

    if kind == "assign":
        to = action.get("to")
        uid = {
            "user": action.get("user_id"), "reporter": target.reporter_id,
            "trigger_user": actor.id if actor and not actor.is_bot else None,
            "lead": target.project.lead_id, "unassigned": None,
        }.get(to)
        if to != "unassigned" and uid is None:
            return f"{target.key}: no hay a quién asignar"
        if target.assignee_id == uid:
            return f"{target.key}: ya estaba asignada"
        if uid is not None and not _assignable(target.project, uid):
            # checked at run time too: the user may have lost access after the rule was saved
            raise ValidationFailed(f"{target.key}: el usuario elegido no se puede asignar en "
                                   f"{target.project.key}")
        services.update_issue(bot, target, {"assignee": uid})
        return f"{target.key} asignada"

    if kind == "edit":
        changes: dict[str, Any] = {}
        fields = action.get("fields") or {}
        for f in ("priority", "story_points", "flagged"):
            if f in fields:
                changes[f] = fields[f]
        if "due_in_days" in fields:
            days = fields["due_in_days"]
            changes["due_date"] = None if days is None else \
                timezone.localdate() + timedelta(days=int(days))
        add, remove = action.get("add_labels") or [], set(action.get("remove_labels") or [])
        if add or remove:
            labels = [x for x in target.labels if x not in remove]
            changes["labels"] = labels + [x for x in add if x not in labels]
        if changes:
            services.update_issue(bot, target, changes)
        return f"{target.key} editada ({', '.join(changes) or 'sin cambios'})"

    if kind == "comment":
        text = render(action.get("body") or "", target, actor).strip()
        if not text:
            return "comentario vacío, se omite"
        services.add_comment(bot, target, text)
        return f"comentario en {target.key}"

    if kind == "create_subtasks":
        from apps.issues.models import IssueType

        if target.issue_type.level != IssueType.Level.STANDARD:
            return f"{target.key}: solo las incidencias estándar tienen subtareas"
        sub_type = target.project.issue_types.filter(level=IssueType.Level.SUBTASK).first()
        if sub_type is None:
            raise ValidationFailed("El proyecto no tiene tipo Subtarea")
        keys = []
        for summary in action.get("summaries") or []:
            summary = render(summary, target, actor).strip()
            if summary:
                sub = services.create_issue(bot, target.project, services.IssueInput(
                    issue_type_id=sub_type.id, summary=summary[:255], parent_id=target.id))
                keys.append(sub.key)
        return f"subtareas creadas: {', '.join(keys) or 'ninguna'}"

    if kind == "add_watcher":
        user = User.objects.filter(pk=action.get("user_id"), is_active=True,
                                   is_bot=False).first()
        if user is None:
            return "observador no encontrado"
        if not _can_browse(user, target.project):
            return f"{user.display_name} no tiene acceso a {target.project.key}, se omite"
        target.watchers.add(user)
        return f"{user.display_name} observa {target.key}"

    if kind == "notify":
        recipients, skipped = _recipients(action, target, actor)
        if not recipients:
            return "sin destinatarios" + (f" ({skipped} sin acceso)" if skipped else "")
        subject = render(action.get("subject") or "[Gestiona] {{issue.key}}", target, actor)
        body = render(action.get("body") or "{{issue.key}}: {{issue.summary}}\n{{issue.url}}",
                      target, actor)
        from .tasks import send_automation_email

        emails = sorted(recipients)
        transaction.on_commit(lambda: send_automation_email.delay(subject[:200], body, emails))
        extra = f"; {skipped} omitido(s) sin acceso" if skipped else ""
        return f"correo a {len(emails)} persona(s){extra}"

    if kind == "webhook":
        return _webhook(rule, action, target, actor)

    raise ValidationFailed(f"Acción desconocida: {kind}")


def _can_browse(user, project) -> bool:
    from apps.projects.models import Perm
    from apps.projects.permissions import has_perm

    return user.is_active and not getattr(user, "is_bot", False) and \
        has_perm(user, project, Perm.BROWSE)


def _assignable(project, user_id) -> bool:
    from apps.projects.permissions import assignable_users

    return assignable_users(project).filter(pk=user_id).exists()


def _recipients(action: dict, issue, actor) -> tuple[set[str], int]:
    """E-mail addresses to notify, limited to people who can see the issue's project.
    Returns (emails, number of people skipped for lack of access)."""
    ids: set[int] = set()
    for who in action.get("to") or []:
        if who == "assignee" and issue.assignee_id:
            ids.add(issue.assignee_id)
        elif who == "reporter" and issue.reporter_id:
            ids.add(issue.reporter_id)
        elif who == "watchers":
            ids |= set(issue.watchers.values_list("id", flat=True))
        elif who == "trigger_user" and actor:
            ids.add(actor.id)
    ids |= {int(u) for u in action.get("user_ids") or [] if str(u).isdigit()}
    users = User.objects.filter(id__in=ids, is_active=True, is_bot=False) \
        .exclude(email__endswith=".invalid")
    emails, skipped = set(), 0
    for user in users:
        if _can_browse(user, issue.project):
            emails.add(user.email)
        else:
            skipped += 1
    return emails, skipped


def _allow_private_webhooks() -> bool:
    return bool(getattr(settings, "AUTOMATION_WEBHOOK_ALLOW_PRIVATE", False))


def _webhook_error(e) -> ValidationFailed:
    if e.internal:
        return ValidationFailed(
            "El webhook apunta a una dirección interna (configura "
            "AUTOMATION_WEBHOOK_ALLOW_PRIVATE=true para permitirlo)"
        )
    return ValidationFailed(f"URL de webhook inválida: {e.message}")


def check_webhook_url(url: str) -> None:
    """Validate a webhook URL when saving a rule (scheme, host and resolved addresses)."""
    from apps.imports.netguard import UnsafeURL, check_url

    try:
        check_url(url, allow_private=_allow_private_webhooks())
    except UnsafeURL as e:
        raise _webhook_error(e) from e


def _webhook(rule: AutomationRule, action: dict, issue, actor) -> str:
    import requests

    from apps.imports.netguard import UnsafeURL, guarded_session

    url = action.get("url") or ""
    payload = {
        "rule": {"id": rule.id, "name": rule.name},
        "issue": {
            "key": issue.key, "summary": issue.summary, "status": issue.status.name,
            "priority": issue.priority.name, "type": issue.issue_type.name,
            "assignee": issue.assignee.email if issue.assignee else None,
            "project": issue.project.key, "url": f"{settings.FRONTEND_URL}/browse/{issue.key}",
        },
        "user": actor.email if actor and not actor.is_bot else None,
    }
    if action.get("body"):
        payload["text"] = render(action["body"], issue, actor)
    # The guarded session re-validates the destination right before connecting and pins the
    # connection to the checked address (no DNS rebinding); redirects are never followed.
    session = guarded_session(allow_private=_allow_private_webhooks())
    try:
        resp = session.post(url, json=payload, timeout=10, allow_redirects=False,
                            headers={"User-Agent": "Gestiona-Automation/1.0"})
        resp.close()
    except UnsafeURL as e:
        raise _webhook_error(e) from e
    except requests.RequestException as e:
        log.warning("webhook of rule %s failed", rule.pk, exc_info=True)
        raise ValidationFailed(f"Webhook falló: no se pudo conectar ({type(e).__name__})") from e
    finally:
        session.close()
    if 300 <= resp.status_code < 400:
        raise ValidationFailed(f"Webhook respondió con una redirección ({resp.status_code}); "
                               "no se siguen redirecciones")
    if resp.status_code >= 400:
        raise ValidationFailed(f"Webhook respondió {resp.status_code}")
    return f"webhook {resp.status_code}"


# --------------------------------------------------------------------------- schedule

def next_run(config: dict, after: datetime) -> datetime:
    local = timezone.localtime(after)
    every = config.get("every") or "day"
    hh, mm = 9, 0
    try:
        hh, mm = (int(x) for x in str(config.get("time") or "09:00").split(":")[:2])
    except ValueError:
        pass
    if every == "hour":
        candidate = local.replace(minute=mm % 60, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(hours=1)
        return candidate
    candidate = local.replace(hour=hh % 24, minute=mm % 60, second=0, microsecond=0)
    if every == "week":
        weekday = int(config.get("weekday") or 0) % 7
        candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    elif candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def run_scheduled(now: datetime | None = None) -> int:
    """Run scheduled rules that are due. Returns how many rules ran."""
    from apps.issues.models import Issue
    from apps.search.jql import JQLError, compile_jql

    now = now or timezone.now()
    ran = 0
    rules = AutomationRule.objects.filter(enabled=True, trigger=Trigger.SCHEDULED)
    for rule in rules.filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)):
        if rule.next_run_at is None:  # first time: just schedule
            rule.next_run_at = next_run(rule.trigger_config, now)
            rule.save(update_fields=["next_run_at"])
            continue
        AutomationRule.objects.filter(pk=rule.pk).update(
            next_run_at=next_run(rule.trigger_config, now))
        bot = bot_user()
        try:
            compiled = compile_jql(rule.trigger_config.get("jql") or "", user=bot,
                                   project=rule.project)
        except JQLError as e:
            AutomationLog.objects.create(rule=rule, status=AutomationLog.Status.FAILURE,
                                         message=f"JQL inválido: {e.message}")
            continue
        qs = Issue.objects.select_related("project", "issue_type", "status", "parent") \
            .filter(compiled.q).filter(is_archived=False)
        if rule.project_id:
            qs = qs.filter(project_id=rule.project_id)
        issues = list(qs.order_by("id")[:SCHEDULED_LIMIT])
        if not issues:
            AutomationLog.objects.create(rule=rule, status=AutomationLog.Status.NO_MATCH,
                                         message="Ninguna incidencia coincide con el JQL")
        for issue in issues:
            execute_rule(rule, issue, None, {"scheduled": True})
        ran += 1
    return ran


# --------------------------------------------------------------------------- validation

def _rule_user(raw, message: str) -> int:
    try:
        uid = int(raw)
    except (TypeError, ValueError) as e:
        raise ValidationFailed(message, code="actions") from e
    if not User.objects.filter(pk=uid, is_active=True, is_bot=False).exists():
        raise ValidationFailed(message, code="actions")
    return uid


def _check_browse(ids: list[int], project, message: str) -> None:
    """Project rules: every chosen user must be able to browse the project. Global rules
    are checked against each issue's project when they run."""
    if project is None:
        return
    denied = [u for u in User.objects.filter(id__in=set(ids)).order_by("full_name", "id")
              if not _can_browse(u, project)]
    if denied:
        names = ", ".join(u.display_name for u in denied[:5])
        raise ValidationFailed(f"{message}: {names}", code="actions")


def validate_rule(data: dict, *, project, user) -> dict:
    """Normalise and check a rule definition coming from the API."""
    from apps.issues.models import Priority
    from apps.search.jql import JQLError, compile_jql
    from apps.workflows.models import Status

    name = (data.get("name") or "").strip()
    if not name:
        raise ValidationFailed("El nombre es obligatorio", code="name")
    trigger = data.get("trigger")
    if trigger not in Trigger.values:
        raise ValidationFailed("Disparador inválido", code="trigger")
    cfg = data.get("trigger_config") or {}
    if trigger == Trigger.SCHEDULED:
        if cfg.get("every") not in ("hour", "day", "week"):
            raise ValidationFailed("Frecuencia inválida", code="trigger_config")
        if not re.match(r"^\d{1,2}:\d{2}$", str(cfg.get("time") or "09:00")):
            raise ValidationFailed("Hora inválida (HH:MM)", code="trigger_config")
        if not (cfg.get("jql") or "").strip():
            raise ValidationFailed("Una regla programada necesita un JQL", code="trigger_config")
    jqls = [cfg.get("jql")] if trigger == Trigger.SCHEDULED else []
    status_ids = set(cfg.get("from_status_ids") or []) | set(cfg.get("to_status_ids") or [])

    conditions = data.get("conditions") or []
    for c in conditions:
        if c.get("type") not in CONDITION_TYPES:
            raise ValidationFailed(f"Condición desconocida: {c.get('type')}", code="conditions")
        if c["type"] == "jql":
            jqls.append(c.get("jql"))
    for jql in jqls:
        try:
            compile_jql(jql or "", user=user, project=project)
        except JQLError as e:
            raise ValidationFailed(f"JQL inválido: {e.message}", code="jql") from e

    actions = data.get("actions") or []
    if not actions:
        raise ValidationFailed("Agrega al menos una acción", code="actions")
    for a in actions:
        kind = a.get("type")
        if kind not in ACTION_TYPES:
            raise ValidationFailed(f"Acción desconocida: {kind}", code="actions")
        if a.get("target") not in (None, "issue", "parent"):
            raise ValidationFailed("Destino de acción inválido", code="actions")
        if kind == "transition":
            if not a.get("status_id"):
                raise ValidationFailed("Elige el estado destino", code="actions")
            status_ids.add(a["status_id"])
        elif kind == "assign":
            if a.get("to") not in ASSIGN_TO:
                raise ValidationFailed("Asignación inválida", code="actions")
            if a["to"] == "user":
                a["user_id"] = _rule_user(a.get("user_id"), "Elige a quién asignar")
                if project is not None and not _assignable(project, a["user_id"]):
                    raise ValidationFailed("El usuario elegido no se puede asignar en este "
                                           "proyecto", code="actions")
        elif kind == "edit":
            pr = (a.get("fields") or {}).get("priority")
            if pr and not Priority.objects.filter(pk=pr).exists():
                raise ValidationFailed("Prioridad inválida", code="actions")
        elif kind == "comment" and not (a.get("body") or "").strip():
            raise ValidationFailed("El comentario está vacío", code="actions")
        elif kind == "create_subtasks" and not [s for s in a.get("summaries") or [] if s.strip()]:
            raise ValidationFailed("Indica al menos una subtarea", code="actions")
        elif kind == "notify":
            if not isinstance(a.get("to") or [], list) or \
                    not isinstance(a.get("user_ids") or [], list):
                raise ValidationFailed("Destinatarios inválidos", code="actions")
            if not (set(a.get("to") or []) <= NOTIFY_TO) or not (a.get("to") or a.get("user_ids")):
                raise ValidationFailed("Elige los destinatarios", code="actions")
            a["user_ids"] = [_rule_user(u, "Destinatario no encontrado")
                             for u in dict.fromkeys(a.get("user_ids") or [])]
            _check_browse(a["user_ids"], project, "No tienen acceso al proyecto")
        elif kind == "add_watcher":
            a["user_id"] = _rule_user(a.get("user_id"), "Elige el observador")
            _check_browse([a["user_id"]], project, "El observador no tiene acceso al proyecto")
        elif kind == "webhook":
            if not (user.is_staff or user.is_superuser):
                raise ValidationFailed("Solo los administradores del sistema pueden usar "
                                       "webhooks", code="actions")
            check_webhook_url(a.get("url") or "")
    known = set(Status.objects.filter(id__in=status_ids).values_list("id", flat=True))
    if status_ids - known:
        raise ValidationFailed("Estado inválido", code="status")

    return {
        "name": name[:120], "description": (data.get("description") or "")[:2000],
        "enabled": bool(data.get("enabled", True)), "trigger": trigger, "trigger_config": cfg,
        "conditions": conditions, "actions": actions,
        "allow_rule_triggers": bool(data.get("allow_rule_triggers", False)),
    }
