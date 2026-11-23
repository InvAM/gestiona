import logging

from celery import shared_task
from django.core.mail import send_mail

log = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def run_rules(rule_ids, issue_id, actor_id, context, depth):
    from .engine import run_rules as _run

    _run(rule_ids, issue_id, actor_id, context, depth)


@shared_task(ignore_result=True)
def tick():
    """Every minute (Celery beat): run scheduled rules that are due."""
    from .engine import run_scheduled

    run_scheduled()


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def send_automation_email(self, subject: str, body: str, emails: list[str]):
    try:
        send_mail(subject, f"{body}\n\n— Automatización de Gestiona", None, emails)
    except Exception as exc:  # pragma: no cover - network
        log.warning("automation email failed", exc_info=True)
        raise self.retry(exc=exc) from exc
