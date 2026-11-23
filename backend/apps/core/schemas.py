from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ninja import Schema


class ErrorOut(Schema):
    code: str
    message: str
    details: Any = None


class OkOut(Schema):
    ok: bool = True


class UserRef(Schema):
    id: int
    name: str
    email: str
    initials: str
    color: str
    avatar_url: str | None = None
    active: bool = True


class IssueTypeOut(Schema):
    id: int
    name: str
    icon: str
    color: str
    level: int
    description: str = ""
    has_affects_versions: bool = False


class StatusOut(Schema):
    id: int
    name: str
    category: str


class PriorityOut(Schema):
    id: int
    name: str
    icon: str
    color: str
    position: int
    is_default: bool = False


class ResolutionOut(Schema):
    id: int
    name: str
    description: str = ""


class NamedRef(Schema):
    id: int
    name: str


class IssueRef(Schema):
    id: int
    key: str
    summary: str
    type: IssueTypeOut
    status: StatusOut
    priority: PriorityOut | None = None
    assignee: UserRef | None = None
    is_archived: bool = False


class Page(Schema):
    total: int
    start: int
    limit: int


def user_ref(u) -> dict | None:
    if u is None:
        return None
    return {
        "id": u.id, "name": u.display_name, "email": u.email, "initials": u.initials,
        "color": u.avatar_color, "avatar_url": u.avatar.url if u.avatar else None,
        "active": u.is_active,
    }


def type_ref(t) -> dict:
    return {"id": t.id, "name": t.name, "icon": t.icon, "color": t.color, "level": t.level,
            "description": t.description, "has_affects_versions": t.has_affects_versions}


def status_ref(s) -> dict:
    return {"id": s.id, "name": s.name, "category": s.category}


def priority_ref(p) -> dict | None:
    if p is None:
        return None
    return {"id": p.id, "name": p.name, "icon": p.icon, "color": p.color, "position": p.position,
            "is_default": p.is_default}


def issue_ref(i) -> dict:
    return {
        "id": i.id, "key": i.key, "summary": i.summary, "type": type_ref(i.issue_type),
        "status": status_ref(i.status), "priority": priority_ref(i.priority),
        "assignee": user_ref(i.assignee), "is_archived": i.is_archived,
    }


__all__ = [
    "Schema", "ErrorOut", "OkOut", "UserRef", "IssueTypeOut", "StatusOut", "PriorityOut",
    "ResolutionOut", "NamedRef", "IssueRef", "Page", "user_ref", "type_ref", "status_ref",
    "priority_ref", "issue_ref", "date", "datetime",
]
