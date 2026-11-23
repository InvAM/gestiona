"""Minimal SCIM 2.0 server (RFC 7643/7644) for user provisioning from Entra ID, Okta, etc.

Users only (no groups). DELETE deactivates instead of deleting so issue history is kept.
Auth: `Authorization: Bearer <token>` with a token created in Administración → SCIM.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ApiToken

User = get_user_model()
SCIM_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
CT = "application/scim+json"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return "gst_" + secrets.token_urlsafe(32)


def _resp(data, status=200):
    return JsonResponse(data, status=status, content_type=CT)


def _error(status: int, detail: str, scim_type: str | None = None):
    body = {"schemas": [ERROR], "status": str(status), "detail": detail}
    if scim_type:
        body["scimType"] = scim_type
    return _resp(body, status)


def _auth(request) -> ApiToken | None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return None
    token = ApiToken.objects.filter(token_hash=hash_token(header[7:].strip()),
                                    revoked_at__isnull=True).first()
    if token is None or "scim" not in token.scopes:
        return None
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token


def _base(request) -> str:
    return request.build_absolute_uri("/scim/v2")


def user_resource(request, u) -> dict:
    parts = (u.full_name or "").split(" ", 1)
    return {
        "schemas": [SCIM_USER], "id": str(u.id), "externalId": u.external_id or None,
        "userName": u.email, "displayName": u.display_name, "active": u.is_active,
        "name": {"formatted": u.full_name, "givenName": parts[0] if parts else "",
                 "familyName": parts[1] if len(parts) > 1 else ""},
        "emails": [{"value": u.email, "primary": True, "type": "work"}],
        "title": u.job_title or None,
        "meta": {"resourceType": "User", "created": u.date_joined.isoformat(),
                 "lastModified": (u.last_login or u.date_joined).isoformat(),
                 "location": f"{_base(request)}/Users/{u.id}"},
    }


def _email_of(data: dict) -> str:
    emails = data.get("emails") or []
    primary = next((e for e in emails if e.get("primary")), emails[0] if emails else None)
    email = (primary or {}).get("value") or data.get("userName") or ""
    return str(email).strip().lower()


def _name_of(data: dict) -> str:
    n = data.get("name") or {}
    full = n.get("formatted") or " ".join(x for x in (n.get("givenName"), n.get("familyName"))
                                          if x)
    return (full or data.get("displayName") or "").strip()[:150]


def _bool(v) -> bool:
    return v if isinstance(v, bool) else str(v).strip().lower() == "true"


def _apply(u, data: dict) -> None:
    email = _email_of(data)
    if email:
        u.email = email
    name = _name_of(data)
    if name:
        u.full_name = name
    if "active" in data:
        u.is_active = _bool(data["active"])
    if "externalId" in data:
        u.external_id = str(data.get("externalId") or "")[:255]
    if "title" in data:
        u.job_title = str(data.get("title") or "")[:120]


_FILTER = re.compile(r'^\s*(userName|externalId|emails\.value|emails)\s+eq\s+"([^"]*)"\s*$', re.I)


@csrf_exempt
def users(request):
    if _auth(request) is None:
        return _error(401, "Token inválido")
    if request.method == "GET":
        qs = User.objects.filter(is_bot=False).order_by("id")
        flt = request.GET.get("filter")
        if flt:
            m = _FILTER.match(flt)
            if not m:
                return _error(400, "Filtro no soportado", "invalidFilter")
            attr, value = m.group(1).lower(), m.group(2)
            qs = qs.filter(external_id=value) if attr == "externalid" \
                else qs.filter(email__iexact=value)
        start = max(int(request.GET.get("startIndex") or 1), 1)
        count = max(0, min(int(request.GET.get("count") or 100), 200))
        total = qs.count()
        items = [user_resource(request, u) for u in qs[start - 1:start - 1 + count]]
        return _resp({"schemas": [LIST], "totalResults": total, "startIndex": start,
                      "itemsPerPage": len(items), "Resources": items})
    if request.method == "POST":
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return _error(400, "JSON inválido", "invalidSyntax")
        email = _email_of(data)
        if not email or "@" not in email:
            return _error(400, "userName / emails es obligatorio", "invalidValue")
        if User.objects.filter(email__iexact=email).exists():
            return _error(409, "Ya existe un usuario con ese email", "uniqueness")
        u = User(email=email, is_active=True)
        u.set_unusable_password()  # signs in through SSO
        _apply(u, data)
        try:
            with transaction.atomic():
                u.save()
        except IntegrityError:
            return _error(409, "Ya existe un usuario con ese email", "uniqueness")
        return _resp(user_resource(request, u), 201)
    return _error(405, "Método no permitido")


@csrf_exempt
def user_detail(request, user_id: str):
    if _auth(request) is None:
        return _error(401, "Token inválido")
    u = User.objects.filter(pk=user_id, is_bot=False).first() if user_id.isdigit() else None
    if u is None:
        return _error(404, "Usuario no encontrado")
    if request.method == "GET":
        return _resp(user_resource(request, u))
    if request.method == "DELETE":
        u.is_active = False  # keep history: deprovision = deactivate
        u.save(update_fields=["is_active"])
        return HttpResponse(status=204)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return _error(400, "JSON inválido", "invalidSyntax")
    if request.method == "PUT":
        _apply(u, data)
    elif request.method == "PATCH":
        for op in data.get("Operations") or []:
            kind = str(op.get("op", "")).lower()
            path, value = op.get("path"), op.get("value")
            if kind not in ("replace", "add", "remove"):
                return _error(400, f"Operación no soportada: {kind}", "invalidSyntax")
            if path is None and isinstance(value, dict):
                _apply(u, value)
                continue
            p = str(path or "")
            if p == "active":
                u.is_active = False if kind == "remove" else _bool(value)
            elif p in ("userName", 'emails[type eq "work"].value', "emails"):
                v = value[0].get("value") if isinstance(value, list) and value else value
                if v:
                    u.email = str(v).lower()
            elif p in ("name.formatted", "displayName"):
                u.full_name = str(value or "")[:150]
            elif p in ("name.givenName", "name.familyName"):
                parts = (u.full_name or "").split(" ", 1) + [""]
                given, family = parts[0], parts[1]
                if p.endswith("givenName"):
                    given = str(value or "")
                else:
                    family = str(value or "")
                u.full_name = f"{given} {family}".strip()[:150]
            elif p == "externalId":
                u.external_id = str(value or "")[:255]
            elif p == "title":
                u.job_title = str(value or "")[:120]
            # unknown attributes are ignored, as allowed by most IdPs
    else:
        return _error(405, "Método no permitido")
    try:
        with transaction.atomic():
            u.save()
    except IntegrityError:
        return _error(409, "Ya existe un usuario con ese email", "uniqueness")
    return _resp(user_resource(request, u))


@csrf_exempt
def groups(request):
    if _auth(request) is None:
        return _error(401, "Token inválido")
    if request.method == "GET":
        return _resp({"schemas": [LIST], "totalResults": 0, "startIndex": 1,
                      "itemsPerPage": 0, "Resources": []})
    return _error(501, "Los grupos no se sincronizan; asigna proyectos desde Gestiona")


@csrf_exempt
def service_provider_config(request):
    return _resp({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0,
                                               "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False}, "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token",
                                   "description": "Token creado en Gestiona", "primary": True}],
    })


@csrf_exempt
def resource_types(request):
    return _resp({"schemas": [LIST], "totalResults": 1, "Resources": [{
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": "User",
        "name": "User", "endpoint": "/Users", "schema": SCIM_USER}]})
