"""WebSocket endpoint: /ws/  — client subscribes to projects it can browse."""

from __future__ import annotations

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import events


class EventsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.groups_joined: set[str] = set()
        await self._join(events.user_group(user.id))
        await self.accept()

    async def disconnect(self, code):
        for g in getattr(self, "groups_joined", set()):
            await self.channel_layer.group_discard(g, self.channel_name)

    async def _join(self, group: str):
        await self.channel_layer.group_add(group, self.channel_name)
        self.groups_joined.add(group)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        if action == "subscribe_project":
            pid = content.get("project_id")
            if isinstance(pid, int) and await self._can_browse(pid):
                await self._join(events.project_group(pid))
                await self.send_json({"event": "subscribed", "payload": {"project_id": pid}})
        elif action == "unsubscribe_project":
            pid = content.get("project_id")
            g = events.project_group(pid) if isinstance(pid, int) else None
            if g in self.groups_joined:
                await self.channel_layer.group_discard(g, self.channel_name)
                self.groups_joined.discard(g)
        elif action == "ping":
            await self.send_json({"event": "pong"})

    @database_sync_to_async
    def _can_browse(self, project_id: int) -> bool:
        from apps.projects.models import Perm, Project
        from apps.projects.permissions import has_perm

        project = Project.objects.filter(pk=project_id).first()
        return bool(project and has_perm(self.scope["user"], project, Perm.BROWSE))

    async def gestiona_event(self, message):
        await self.send_json({"event": message["event"], "payload": message["payload"]})
