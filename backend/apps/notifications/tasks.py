from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from apps.core import events

from .models import Event, Notification, NotificationPreference

log = logging.getLogger(__name__)

SUBJECTS = {
    Event.ISSUE_CREATED: "{actor} creó {key}",
    Event.ISSUE_ASSIGNED: "{actor} te asignó {key}",
    Event.ISSUE_UPDATED: "{actor} actualizó {key}",
    Event.ISSUE_TRANSITIONED: "{actor} cambió el estado de {key}",
    Event.COMMENT_ADDED: "{actor} comentó en {key}",
    Event.MENTIONED: "{actor} te mencionó en {key}",
}


@shared_task(bind=True, max_retries=3, default_retry_delay=10, acks_late=True)
def deliver_notifications(self, *, actor_id, issue_id, event, recipients, mentioned, data):
    from apps.issues.models import Issue
    from apps.projects.models import Perm
    from apps.projects.permissions import has_perm

    User = get_user_model()
    issue = Issue.objects.select_related("project").filter(pk=issue_id).first()
    if issue is None:
        return
    actor = User.objects.filter(pk=actor_id).first()
    targets: dict[int, str] = {uid: event for uid in recipients}
    for uid in mentioned:
        targets[uid] = Event.MENTIONED
    targets.pop(actor_id, None)  # never notify yourself
    if not targets:
        return
    users = {u.id: u for u in User.objects.filter(id__in=targets, is_active=True, is_bot=False)}
    prefs = {
        (p.user_id, p.event): p
        for p in NotificationPreference.objects.filter(user_id__in=users)
    }
    for uid, ev in targets.items():
        user = users.get(uid)
        if user is None or not has_perm(user, issue.project, Perm.BROWSE):
            continue
        pref = prefs.get((uid, ev))
        if pref is not None and not pref.in_app and not pref.email:
            continue
        n = Notification.objects.create(
            recipient=user, actor=actor, event=ev, issue=issue,
            data={**data, "key": issue.key, "summary": issue.summary},
        )
        if pref is None or pref.in_app:
            events._send(events.user_group(uid), "notification.created", {"id": n.id})
        if (pref is None or pref.email) and ev != Event.ISSUE_UPDATED:
            send_notification_email.delay(n.id)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_notification_email(self, notification_id: int):
    n = Notification.objects.select_related("recipient", "actor", "issue").filter(
        pk=notification_id
    ).first()
    if n is None or n.emailed_at or n.issue is None:
        return
    actor = n.actor.display_name if n.actor else "Alguien"
    subject = SUBJECTS.get(n.event, "{actor} actualizó {key}").format(actor=actor, key=n.issue.key)
    url = f"{settings.FRONTEND_URL}/browse/{n.issue.key}"
    lines = [f"{n.issue.key}: {n.issue.summary}", ""]
    if n.event == Event.ISSUE_TRANSITIONED:
        lines.append(f"Estado: {n.data.get('from')} → {n.data.get('to')}")
    lines += ["", f"Ver incidencia: {url}", "", "— Gestiona"]
    try:
        send_mail(f"[Gestiona] {subject}", "\n".join(lines), None, [n.recipient.email])
    except Exception as exc:  # pragma: no cover - network
        log.warning("email failed for notification %s", n.id, exc_info=True)
        raise self.retry(exc=exc) from exc
    n.emailed_at = timezone.now()
    n.save(update_fields=["emailed_at"])
