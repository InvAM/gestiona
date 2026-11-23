"""Realtime event fan-out over Django Channels. Events are sent after DB commit."""

from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

log = logging.getLogger(__name__)


def project_group(project_id: int) -> str:
    return f"project.{project_id}"


def user_group(user_id: int) -> str:
    return f"user.{user_id}"


def _send(group: str, event: str, payload: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group, {"type": "gestiona.event", "event": event, "payload": payload}
        )
    except Exception:  # realtime is best-effort; never break the request
        log.warning("realtime publish failed: %s %s", group, event, exc_info=True)


def publish_project(project_id: int, event: str, payload: dict, *, actor_id=None) -> None:
    payload = {**payload, "actor_id": actor_id}
    transaction.on_commit(lambda: _send(project_group(project_id), event, payload))


def publish_user(user_id: int, event: str, payload: dict) -> None:
    transaction.on_commit(lambda: _send(user_group(user_id), event, payload))
