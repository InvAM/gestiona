from django.utils import timezone
from ninja import Router, Schema

from apps.core.schemas import UserRef, user_ref

from .models import Event, Notification, NotificationPreference

router = Router(tags=["notifications"])


class NotificationOut(Schema):
    id: int
    event: str
    actor: UserRef | None
    issue_key: str | None
    issue_summary: str | None
    data: dict
    read: bool
    created_at: str


class ReadIn(Schema):
    ids: list[int] | None = None
    all: bool = False


class PrefOut(Schema):
    event: str
    label: str
    in_app: bool
    email: bool


class PrefIn(Schema):
    event: str
    in_app: bool
    email: bool


def _out(n: Notification) -> dict:
    return {
        "id": n.id, "event": n.event, "actor": user_ref(n.actor),
        "issue_key": n.issue.key if n.issue else n.data.get("key"),
        "issue_summary": n.issue.summary if n.issue else n.data.get("summary"),
        "data": n.data, "read": n.read_at is not None, "created_at": n.created_at.isoformat(),
    }


@router.get("/notifications", response=list[NotificationOut])
def list_notifications(request, unread: bool = False, limit: int = 50, before_id: int | None
                       = None):
    qs = Notification.objects.filter(recipient=request.user).select_related("actor", "issue")
    if unread:
        qs = qs.filter(read_at__isnull=True)
    if before_id:
        qs = qs.filter(id__lt=before_id)
    return [_out(n) for n in qs[: min(limit, 100)]]


class CountOut(Schema):
    unread: int


@router.get("/notifications/count", response=CountOut)
def unread_count(request):
    return {"unread": Notification.objects.filter(recipient=request.user,
                                                  read_at__isnull=True).count()}


@router.post("/notifications/read", response={204: None})
def mark_read(request, data: ReadIn):
    qs = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
    if not data.all:
        qs = qs.filter(id__in=data.ids or [])
    qs.update(read_at=timezone.now())
    return 204, None


@router.post("/notifications/unread", response={204: None})
def mark_unread(request, data: ReadIn):
    Notification.objects.filter(recipient=request.user, id__in=data.ids or []).update(
        read_at=None
    )
    return 204, None


@router.get("/notifications/preferences", response=list[PrefOut])
def get_prefs(request):
    prefs = {p.event: p for p in NotificationPreference.objects.filter(user=request.user)}
    return [
        {"event": e.value, "label": e.label,
         "in_app": prefs[e.value].in_app if e.value in prefs else True,
         "email": prefs[e.value].email if e.value in prefs else e != Event.ISSUE_UPDATED}
        for e in Event
    ]


@router.put("/notifications/preferences", response=list[PrefOut])
def set_prefs(request, data: list[PrefIn]):
    valid = set(Event.values)
    for p in data:
        if p.event in valid:
            NotificationPreference.objects.update_or_create(
                user=request.user, event=p.event,
                defaults={"in_app": p.in_app, "email": p.email},
            )
    return get_prefs(request)
