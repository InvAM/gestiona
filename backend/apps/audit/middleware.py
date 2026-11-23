import json

from .models import AuditEntry
from .services import match, record

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
BULK_PATH = "/api/v1/issues/bulk"


class AuditMiddleware:
    """Records successful configuration changes made through the API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in MUTATING or not request.path.startswith("/api/v1/"):
            return self.get_response(request)
        is_bulk = request.path.rstrip("/") == BULK_PATH
        hit = match(request.method, request.path)
        body = None
        if (hit or is_bulk) and request.content_type == "application/json":
            try:
                body = json.loads(request.body or b"{}")
            except (ValueError, UnicodeDecodeError):
                body = None
        response = self.get_response(request)
        if response.status_code >= 400:
            return response
        if hit:
            category, action, groups = hit
            details = {"body": body} if body else {}
            if groups.get("id"):
                details["id"] = groups["id"]
            record(request=request, category=category, action=action,
                   project_key=groups.get("key", ""),
                   object_repr=groups.get("issue") or groups.get("key") or "",
                   details=details, status_code=response.status_code)
        elif is_bulk and isinstance(body, dict) and (body.get("delete") or body.get("move")):
            try:
                result = json.loads(response.content or b"{}")
            except ValueError:
                result = {}
            action = "Eliminación masiva" if body.get("delete") else "Movimiento masivo"
            record(request=request, category=AuditEntry.Category.ISSUES, action=action,
                   object_repr=f"{len(result.get('updated', []))} incidencias",
                   details={"updated": result.get("updated", [])[:200],
                            "move": body.get("move")},
                   status_code=response.status_code)
        return response
