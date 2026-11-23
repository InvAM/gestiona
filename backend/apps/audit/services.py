"""Audit trail of administrative changes and sign-ins.

Every successful mutating API call that touches configuration (users, projects, members,
workflows, fields, boards, automation, imports, issue deletion/move/archive) is recorded by
`AuditMiddleware`. Sign-ins come from Django's auth signals.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import AuditEntry

log = logging.getLogger(__name__)
C = AuditEntry.Category
SENSITIVE = re.compile(r"pass|token|secret|key_|api_key|credential", re.I)
MAX_DETAIL = 4000

# (methods, path regex under /api/v1/, category, action)
RULES: list[tuple[set[str], re.Pattern, str, str]] = [
    ({"POST"}, r"^admin/users$", C.USERS, "Usuario creado / invitado"),
    ({"PATCH"}, r"^admin/users/(?P<id>\d+)$", C.USERS, "Usuario modificado"),
    ({"POST"}, r"^admin/users/(?P<id>\d+)/invite$", C.USERS, "Invitación reenviada"),
    ({"POST"}, r"^admin/api-tokens$", C.USERS, "Token de API creado"),
    ({"DELETE"}, r"^admin/api-tokens/(?P<id>\d+)$", C.USERS, "Token de API revocado"),
    ({"POST"}, r"^projects$", C.PROJECTS, "Proyecto creado"),
    ({"PATCH"}, r"^projects/(?P<key>[^/]+)$", C.PROJECTS, "Proyecto modificado"),
    ({"DELETE"}, r"^projects/(?P<key>[^/]+)$", C.PROJECTS, "Proyecto eliminado"),
    ({"PUT", "POST"}, r"^projects/(?P<key>[^/]+)/members/(?P<id>\d+)$", C.MEMBERS,
     "Miembro agregado / rol cambiado"),
    ({"DELETE"}, r"^projects/(?P<key>[^/]+)/members/(?P<id>\d+)$", C.MEMBERS,
     "Miembro quitado"),
    ({"PUT"}, r"^projects/(?P<key>[^/]+)/workflow$", C.WORKFLOW, "Flujo del proyecto cambiado"),
    ({"PUT", "POST", "DELETE"}, r"^projects/(?P<key>[^/]+)/workflow-mappings.*$", C.WORKFLOW,
     "Flujo por tipo cambiado"),
    ({"POST", "PATCH", "DELETE"},
     r"^projects/(?P<key>[^/]+)/(components|versions)(/\d+(/restore)?)?$",
     C.PROJECTS, "Componentes / versiones"),
    ({"POST", "PUT", "PATCH", "DELETE"}, r"^workflows(/\d+(/restore)?)?$", C.WORKFLOW,
     "Flujo de trabajo"),
    ({"POST", "PUT", "PATCH", "DELETE"},
     r"^(statuses|issue-types|priorities|resolutions|custom-fields|link-types|roles"
     r"|project-categories)(/.*)?$",
     C.CONFIG, "Configuración global"),
    ({"POST"}, r"^projects/(?P<key>[^/]+)/boards$", C.BOARDS, "Tablero creado"),
    ({"PATCH", "PUT", "DELETE"}, r"^boards/\d+(/columns)?$", C.BOARDS, "Tablero modificado"),
    ({"POST", "PUT", "DELETE"}, r"^automation/rules(/\d+)?(/enabled|/restore)?$", C.AUTOMATION,
     "Regla de automatización"),
    ({"POST"}, r"^imports/jira$", C.IMPORTS, "Importación desde Jira iniciada"),
    ({"DELETE"}, r"^issues/(?P<issue>[^/]+)$", C.ISSUES, "Incidencia eliminada"),
    ({"POST"}, r"^issues/(?P<issue>[^/]+)/move$", C.ISSUES, "Incidencia movida"),
    ({"POST"}, r"^issues/(?P<issue>[^/]+)/archive$", C.ISSUES, "Incidencia archivada"),
    ({"POST"}, r"^issues/(?P<issue>[^/]+)/restore$", C.ISSUES, "Incidencia restaurada"),
]
RULES = [(m, re.compile(p), c, a) for m, p, c, a in RULES]


def _scrub(value, depth=0):
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        return {k: ("***" if SENSITIVE.search(str(k)) else _scrub(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return value[:500]
    return value


def record(*, request=None, actor=None, category: str, action: str, project_key: str = "",
           object_repr: str = "", details: dict | None = None, status_code: int | None = None):
    try:
        actor = actor or (request.user if request is not None and
                          getattr(request, "user", None) and request.user.is_authenticated
                          else None)
        details = _scrub(details or {})
        if len(json.dumps(details, default=str)) > MAX_DETAIL:
            details = {"truncated": True}
        meta = getattr(request, "META", None) or {}
        with transaction.atomic():  # savepoint: a failure here never breaks the caller
            return AuditEntry.objects.create(
                actor=actor, actor_email=getattr(actor, "email", "") or "", category=category,
                action=action[:120], project_key=(project_key or "")[:10].upper(),
                object_repr=(object_repr or "")[:200], details=details,
                status_code=status_code,
                method=(getattr(request, "method", None) or "")[:8],
                path=(getattr(request, "path", None) or "")[:300],
                ip=meta.get("REMOTE_ADDR") or None,
                user_agent=str(meta.get("HTTP_USER_AGENT", ""))[:300],
            )
    except Exception:  # auditing must never break the request
        log.exception("audit record failed")
        return None


def match(method: str, path: str):
    if not path.startswith("/api/v1/"):
        return None
    sub = path[len("/api/v1/"):].rstrip("/")
    for methods, rx, category, action in RULES:
        if method in methods:
            m = rx.match(sub)
            if m:
                return category, action, m.groupdict()
    return None


def prune() -> int:
    days = getattr(settings, "AUDIT_RETENTION_DAYS", 365)
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = AuditEntry.objects.filter(created_at__lt=cutoff).delete()
    return deleted
