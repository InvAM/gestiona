from datetime import date

from django.db.models import Q
from ninja import Router, Schema

from apps.core.errors import Forbidden
from apps.core.schemas import UserRef, user_ref

from .models import AuditEntry

router = Router(tags=["audit"])


class AuditOut(Schema):
    id: int
    created_at: str
    actor: UserRef | None
    actor_email: str
    category: str
    category_display: str
    action: str
    method: str
    path: str
    project_key: str
    object_repr: str
    details: dict
    ip: str | None


class AuditPage(Schema):
    total: int
    items: list[AuditOut]


@router.get("/admin/audit", response=AuditPage)
def list_audit(request, q: str = "", category: str = "", actor_id: int | None = None,
               project: str = "", since: date | None = None, until: date | None = None,
               start: int = 0, limit: int = 50):
    if not (request.user.is_staff or request.user.is_superuser):
        raise Forbidden("Solo los administradores pueden ver la auditoría")
    qs = AuditEntry.objects.select_related("actor")
    if category:
        qs = qs.filter(category=category)
    if actor_id:
        qs = qs.filter(actor_id=actor_id)
    if project:
        qs = qs.filter(project_key=project.upper())
    if since:
        qs = qs.filter(created_at__date__gte=since)
    if until:
        qs = qs.filter(created_at__date__lte=until)
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(object_repr__icontains=q)
                       | Q(actor_email__icontains=q) | Q(path__icontains=q))
    limit = max(1, min(limit, 200))
    return {
        "total": qs.count(),
        "items": [{
            "id": e.id, "created_at": e.created_at.isoformat(), "actor": user_ref(e.actor),
            "actor_email": e.actor_email, "category": e.category,
            "category_display": e.get_category_display(), "action": e.action,
            "method": e.method, "path": e.path, "project_key": e.project_key,
            "object_repr": e.object_repr, "details": e.details, "ip": e.ip,
        } for e in qs[start:start + limit]],
    }
