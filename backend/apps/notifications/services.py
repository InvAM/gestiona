from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import transaction

_muted: ContextVar[bool] = ContextVar("gestiona_notifications_muted", default=False)


@contextmanager
def muted(active: bool = True) -> Iterator[None]:
    """Suppress notifications inside the block (bulk edits with "no notificar")."""
    token = _muted.set(active or _muted.get())
    try:
        yield
    finally:
        _muted.reset(token)


def queue_notifications(*, actor_id: int, issue_id: int, event: str, recipients: set[int],
                        mentioned: set[int], data: dict) -> None:
    if _muted.get():
        return
    from .tasks import deliver_notifications

    payload = dict(actor_id=actor_id, issue_id=issue_id, event=event,
                   recipients=sorted(recipients), mentioned=sorted(mentioned), data=data)
    transaction.on_commit(lambda: deliver_notifications.delay(**payload))
