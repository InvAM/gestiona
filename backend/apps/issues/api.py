from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import Case, Count, F, Func, Q, Value, When
from django.http import FileResponse
from django.utils import timezone
from ninja import File, Router, Schema, UploadedFile

from apps.core.errors import NotFound, ValidationFailed
from apps.core.schemas import (
    IssueRef,
    IssueTypeOut,
    NamedRef,
    PriorityOut,
    ResolutionOut,
    StatusOut,
    UserRef,
    issue_ref,
    priority_ref,
    status_ref,
    type_ref,
    user_ref,
)
from apps.projects.models import Perm, Project
from apps.projects.permissions import has_perm, project_perms, visible_projects

from . import services
from .models import Attachment, Comment, Issue, IssueLink, IssueLinkType, WebLink, Worklog

router = Router(tags=["issues"])


# ------------------------------------------------------------------ schemas

class SprintRef(Schema):
    id: int
    name: str
    state: str


class ProjectRef(Schema):
    id: int
    key: str
    name: str
    avatar: str
    color: str


class LinkOut(Schema):
    id: int
    type: NamedRef
    direction: str  # outward | inward
    label: str
    issue: IssueRef


class WebLinkOut(Schema):
    id: int
    url: str
    title: str


class AttachmentOut(Schema):
    id: int
    filename: str
    size: int
    mime_type: str
    url: str
    created_at: str
    uploaded_by: UserRef | None


class ChildOut(IssueRef):
    story_points: Decimal | None = None


class IssueOut(Schema):
    id: int
    key: str
    is_archived: bool = False
    archived_at: str | None = None
    project: ProjectRef
    summary: str
    description: Any = None
    type: IssueTypeOut
    status: StatusOut
    priority: PriorityOut
    resolution: ResolutionOut | None
    resolved_at: str | None
    assignee: UserRef | None
    reporter: UserRef | None
    parent: IssueRef | None
    labels: list[str]
    components: list[NamedRef]
    fix_versions: list[NamedRef]
    affects_versions: list[NamedRef]
    sprint: SprintRef | None
    closed_sprints: list[SprintRef]
    team: NamedRef | None = None
    story_points: Decimal | None
    original_estimate: int | None
    remaining_estimate: int | None
    time_spent: int
    start_date: date | None
    due_date: date | None
    flagged: bool
    custom_fields: dict
    rank: str
    created_at: str
    updated_at: str
    status_changed_at: str | None
    watching: bool
    watcher_count: int
    voted: bool
    vote_count: int
    children: list[ChildOut]
    links: list[LinkOut]
    web_links: list[WebLinkOut]
    attachments: list[AttachmentOut]
    permissions: list[str]


class IssueCreateIn(Schema):
    project: str
    issue_type_id: int
    summary: str
    description: Any = None
    priority_id: int | None = None
    assignee_id: int | None = None
    reporter_id: int | None = None
    parent_id: int | None = None
    labels: list[str] | None = None
    component_ids: list[int] | None = None
    fix_version_ids: list[int] | None = None
    affects_version_ids: list[int] | None = None
    sprint_id: int | None = None
    story_points: Decimal | None = None
    original_estimate: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    custom_fields: dict | None = None
    status_id: int | None = None
    team_id: int | None = None


class IssuePatch(Schema):
    summary: str | None = None
    description: Any = None
    issue_type: int | None = None
    priority: int | None = None
    assignee: int | None = None
    reporter: int | None = None
    parent: int | None = None
    labels: list[str] | None = None
    components: list[int] | None = None
    fix_versions: list[int] | None = None
    affects_versions: list[int] | None = None
    sprint: int | None = None
    team: int | None = None
    story_points: Decimal | None = None
    original_estimate: int | None = None
    remaining_estimate: int | None = None
    start_date: date | None = None
    due_date: date | None = None
    flagged: bool | None = None
    custom_fields: dict | None = None


class ResolvedScreenFieldOut(Schema):
    key: str
    required: bool
    description: str = ""


class ResolvedScreenTabOut(Schema):
    id: int | None
    name: str
    fields: list[ResolvedScreenFieldOut]


class ResolvedScreenOut(Schema):
    id: int | None
    name: str
    tabs: list[ResolvedScreenTabOut]
    fields: list[str]


class IssueTransitionOut(Schema):
    id: int
    name: str
    to: StatusOut
    require_resolution: bool
    require_comment: bool
    screen: ResolvedScreenOut | None = None  # fields asked while transitioning
    required_fields: list[str] = []  # «campos obligatorios» validator


class IssueTransitionIn(Schema):
    transition_id: int | None = None
    to_status_id: int | None = None
    resolution_id: int | None = None
    comment: Any = None
    # values of the transition screen: PATCH format ("custom_fields": {...}) or "cf:<id>" keys
    fields: dict[str, Any] | None = None


class RankIn(Schema):
    issue_ids: list[int]
    before_id: int | None = None
    after_id: int | None = None


class CommentOut(Schema):
    id: int
    author: UserRef | None
    body: Any
    created_at: str
    updated_at: str
    edited: bool
    can_edit: bool
    can_delete: bool


class CommentIn(Schema):
    body: Any


class LinkIn(Schema):
    link_type_id: int
    target: str  # key or id
    direction: str = "outward"


class WebLinkIn(Schema):
    url: str
    title: str = ""


class WorklogOut(Schema):
    id: int
    author: UserRef | None
    time_spent: int
    started_at: str
    comment: str
    created_at: str


class WorklogIn(Schema):
    time_spent: int
    started_at: datetime | None = None
    comment: str = ""
    remaining_estimate: int | None = None


class HistoryOut(Schema):
    id: int
    actor: UserRef | None
    created_at: str
    items: list[dict]


class WatchersOut(Schema):
    watching: bool
    watchers: list[UserRef]


class CloneIn(Schema):
    summary: str | None = None


class IssueMoveIn(Schema):
    project: str
    # source issue type id -> target issue type id; source status id -> target status id
    type_map: dict[str, int] = {}
    status_map: dict[str, int] = {}
    # values for the target's required fields (PATCH format or "cf:<id>" keys)
    fields: dict[str, Any] = {}


class BulkIn(Schema):
    issue_ids: list[int]
    changes: IssuePatch | None = None
    add_labels: list[str] | None = None
    remove_labels: list[str] | None = None
    transition_to_status_id: int | None = None
    resolution_id: int | None = None
    watch: bool | None = None
    move: IssueMoveIn | None = None
    delete: bool = False
    archive: bool = False
    notify: bool = True


class BulkOut(Schema):
    updated: list[str]
    failed: list[dict]


# ------------------------------------------------------------------ serialization

def _sprint(s):
    return {"id": s.id, "name": s.name, "state": s.state} if s else None


def _named(objs):
    return [{"id": o.id, "name": o.name} for o in objs]


def _attachment(a: Attachment) -> dict:
    return {
        "id": a.id, "filename": a.filename, "size": a.size, "mime_type": a.mime_type,
        "url": f"/api/v1/attachments/{a.id}/download", "created_at": a.created_at.isoformat(),
        "uploaded_by": user_ref(a.uploaded_by),
    }


def _ref_qs():
    return Issue.objects.select_related("issue_type", "status", "priority", "assignee")


def issue_out(issue: Issue, user) -> dict:
    p = issue.project
    perms = project_perms(user, p)
    if issue.is_archived:  # read-only: only viewing, restoring (admin) and deleting remain
        perms = perms & {Perm.BROWSE.value, Perm.ADMINISTER.value, Perm.DELETE_ISSUES.value}
    children = _ref_qs().filter(parent=issue).order_by("rank")
    links = []
    for link in IssueLink.objects.filter(source=issue).select_related(
        "link_type", "target__issue_type", "target__status", "target__priority",
        "target__assignee", "target__project",
    ):
        if has_perm(user, link.target.project, Perm.BROWSE):
            links.append({"id": link.id, "type": {"id": link.link_type.id,
                                                  "name": link.link_type.name},
                          "direction": "outward", "label": link.link_type.outward,
                          "issue": issue_ref(link.target)})
    for link in IssueLink.objects.filter(target=issue).select_related(
        "link_type", "source__issue_type", "source__status", "source__priority",
        "source__assignee", "source__project",
    ):
        if has_perm(user, link.source.project, Perm.BROWSE):
            links.append({"id": link.id, "type": {"id": link.link_type.id,
                                                  "name": link.link_type.name},
                          "direction": "inward", "label": link.link_type.inward,
                          "issue": issue_ref(link.source)})
    watcher_ids = set(issue.watchers.values_list("id", flat=True))
    voter_ids = set(issue.voters.values_list("id", flat=True))
    return {
        "id": issue.id, "key": issue.key,
        "project": {"id": p.id, "key": p.key, "name": p.name, "avatar": p.avatar,
                    "color": p.color},
        "summary": issue.summary, "description": issue.description,
        "type": type_ref(issue.issue_type), "status": status_ref(issue.status),
        "priority": priority_ref(issue.priority),
        "resolution": {"id": issue.resolution.id, "name": issue.resolution.name,
                       "description": issue.resolution.description}
        if issue.resolution else None,
        "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None,
        "assignee": user_ref(issue.assignee), "reporter": user_ref(issue.reporter),
        "parent": issue_ref(issue.parent) if issue.parent else None,
        "labels": issue.labels,
        "components": _named(issue.components.all()),
        "fix_versions": _named(issue.fix_versions.all()),
        "affects_versions": _named(issue.affects_versions.all()),
        "sprint": _sprint(issue.sprint),
        "closed_sprints": [_sprint(s) for s in issue.closed_sprints.all()],
        "team": {"id": issue.team.id, "name": issue.team.name} if issue.team else None,
        "story_points": issue.story_points,
        "original_estimate": issue.original_estimate,
        "remaining_estimate": issue.remaining_estimate,
        "time_spent": issue.time_spent,
        "start_date": issue.start_date, "due_date": issue.due_date,
        "flagged": issue.flagged, "custom_fields": issue.custom_fields, "rank": issue.rank,
        "is_archived": issue.is_archived,
        "archived_at": issue.archived_at.isoformat() if issue.archived_at else None,
        "created_at": issue.created_at.isoformat(), "updated_at": issue.updated_at.isoformat(),
        "status_changed_at": issue.status_changed_at.isoformat()
        if issue.status_changed_at else None,
        "watching": user.id in watcher_ids, "watcher_count": len(watcher_ids),
        "voted": user.id in voter_ids, "vote_count": len(voter_ids),
        "children": [{**issue_ref(c), "story_points": c.story_points} for c in children],
        "links": links,
        "web_links": [{"id": w.id, "url": w.url, "title": w.title}
                      for w in issue.web_links.all()],
        "attachments": [_attachment(a) for a in issue.attachments.select_related("uploaded_by")],
        "permissions": sorted(perms),
    }


def _comment_out(c: Comment, user, perms: set[str]) -> dict:
    own = c.author_id == user.id
    return {
        "id": c.id, "author": user_ref(c.author), "body": c.body,
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
        "edited": c.edited,
        "can_edit": (own and Perm.ADD_COMMENTS in perms) or Perm.EDIT_ALL_COMMENTS in perms,
        "can_delete": (own and Perm.ADD_COMMENTS in perms) or Perm.DELETE_ALL_COMMENTS in perms,
    }


def _get(user, key: str) -> Issue:
    return services.get_issue_or_404(user, key)


def _detail(user, issue_id: int) -> dict:
    return issue_out(services.get_issue_or_404(user, issue_id), user)


# ------------------------------------------------------------------ issues

@router.post("/issues", response={201: IssueOut})
def create_issue(request, data: IssueCreateIn):
    project = Project.objects.filter(key=data.project.upper()).first()
    if project is None:
        raise NotFound("Proyecto no encontrado")
    payload = data.dict()
    payload.pop("project")
    issue = services.create_issue(request.user, project, services.IssueInput(**payload))
    return 201, _detail(request.user, issue.id)


@router.get("/issues/picker", response=list[IssueRef])
def issue_picker(request, q: str = "", project: str | None = None, exclude: str | None = None,
                 level: int | None = None, limit: int = 20):
    """Quick search by key or summary (links, parent selection, global search box)."""
    qs = _ref_qs().filter(project__in=visible_projects(request.user), is_archived=False)
    if project:
        qs = qs.filter(project__key=project.upper())
    if level is not None:
        qs = qs.filter(issue_type__level=level)
    if exclude:
        qs = qs.exclude(key=exclude.upper())
    q = q.strip()
    if q:
        qs = qs.filter(Q(key__istartswith=q) | Q(summary__icontains=q)).order_by(
            Case(When(key__iexact=q, then=Value(0)), default=Value(1)), "-updated_at"
        )
    else:
        from apps.search.models import RecentItem

        recent = list(RecentItem.objects.filter(user=request.user, kind="issue")
                      .values_list("object_id", flat=True)[:limit])
        if recent:
            issues = {i.id: i for i in qs.filter(id__in=recent)}
            return [issue_ref(issues[i]) for i in recent if i in issues]
        qs = qs.order_by("-updated_at")
    return [issue_ref(i) for i in qs[: min(limit, 50)]]


# static /issues/* routes must be declared before /issues/{key}

@router.post("/issues/rank", response={204: None})
def rank(request, data: RankIn):
    issues = list(Issue.objects.select_related("project").filter(id__in=data.issue_ids))
    if len(issues) != len(set(data.issue_ids)):
        raise NotFound("Incidencia no encontrada")
    before = Issue.objects.filter(pk=data.before_id).first() if data.before_id else None
    after = Issue.objects.filter(pk=data.after_id).first() if data.after_id else None
    services.rank_issues(request.user, issues, before=before, after=after)
    return 204, None


BULK_LIMIT = 1000


def _field_errors(exc) -> dict:
    """Per-field errors of a field-rules 422, for the bulk `failed` rows."""
    details = getattr(exc, "details", None)
    if getattr(exc, "code", None) == "fields" and isinstance(details, dict):
        return {"fields": details.get("fields") or {}}
    return {}


@router.post("/issues/bulk", response=BulkOut)
def bulk(request, data: BulkIn):
    """Apply the same change to many issues. Each issue succeeds or fails on its own."""
    from apps.core.errors import ApiError, ValidationFailed
    from apps.notifications.services import muted
    from apps.projects.models import Project

    ids = list(dict.fromkeys(data.issue_ids))
    if not ids:
        raise ValidationFailed("No hay incidencias seleccionadas")
    if len(ids) > BULK_LIMIT:
        raise ValidationFailed(f"Máximo {BULK_LIMIT} incidencias por operación")
    target = None
    if data.move:
        target = Project.objects.filter(key=data.move.project.upper()).first()
        if target is None or not has_perm(request.user, target, Perm.BROWSE):
            raise NotFound("Proyecto destino no encontrado")
    changes = data.changes.dict(exclude_unset=True) if data.changes else {}
    issues = {i.id: i for i in Issue.objects.select_related("project", "issue_type")
              .filter(id__in=ids)}
    # parents first so subtasks archived along with them are skipped afterwards
    order =sorted(issues.values(), key=lambda i: i.issue_type.level == -1)
    updated, failed = [], []
    with muted(not data.notify):
        if target is not None:
            # epics first, selected children stay linked to the moved epic (services.move_issues)
            visible = []
            for issue in order:
                if has_perm(request.user, issue.project, Perm.BROWSE):
                    visible.append(issue)
                else:
                    failed.append({"key": issue.key, "message": "Incidencia no encontrada"})

            def on_error(issue, exc):
                failed.append({"key": issue.key, "message": getattr(exc, "message", None)
                               or "La incidencia ya no existe", **_field_errors(exc)})

            moved = services.move_issues(request.user, visible, target,
                                         type_map=data.move.type_map,
                                         status_map=data.move.status_map,
                                         fields=data.move.fields, on_error=on_error)
            return {"updated": [m.key for m in moved], "failed": failed}
        for issue in order:
            key = issue.key
            try:
                if not has_perm(request.user, issue.project, Perm.BROWSE):
                    raise NotFound("Incidencia no encontrada")
                if data.delete:
                    services.delete_issue(request.user, issue)
                    updated.append(key)
                    continue
                if data.archive:
                    if issue.issue_type.level == -1 and issue.parent_id in issues:
                        updated.append(key)  # archived together with its parent
                        continue
                    services.archive_issue(request.user, issue)
                    updated.append(key)
                    continue
                patch = dict(changes)
                if data.add_labels or data.remove_labels:
                    labels = [x for x in issue.labels if x not in set(data.remove_labels or [])]
                    labels += [x for x in data.add_labels or [] if x not in labels]
                    patch["labels"] = labels
                if patch:
                    services.update_issue(request.user, issue, patch)
                to_status = data.transition_to_status_id
                if to_status and issue.status_id != to_status:
                    services.transition_issue(request.user, issue,
                                              to_status_id=data.transition_to_status_id,
                                              resolution_id=data.resolution_id)
                if data.watch is not None:
                    services.set_watching(request.user, issue, data.watch)
                updated.append(key)
            except ApiError as e:
                failed.append({"key": key, "message": e.message, **_field_errors(e)})
            except Issue.DoesNotExist:
                failed.append({"key": key, "message": "La incidencia ya no existe"})
    return {"updated": updated, "failed": failed}


@router.get("/issues/{key}", response=IssueOut)
def get_issue(request, key: str):
    issue = _get(request.user, key)
    from apps.search.models import RecentItem

    RecentItem.objects.update_or_create(user=request.user, kind="issue", object_id=issue.id)
    return issue_out(issue, request.user)


@router.patch("/issues/{key}", response=IssueOut)
def patch_issue(request, key: str, data: IssuePatch):
    issue = _get(request.user, key)
    services.update_issue(request.user, issue, data.dict(exclude_unset=True))
    return _detail(request.user, issue.id)


@router.delete("/issues/{key}", response={204: None})
def delete_issue(request, key: str):
    services.delete_issue(request.user, _get(request.user, key))
    return 204, None


@router.post("/issues/{key}/clone", response={201: IssueOut})
def clone_issue(request, key: str, data: CloneIn):
    clone = services.clone_issue(request.user, _get(request.user, key), data.summary)
    return 201, _detail(request.user, clone.id)


@router.get("/issues/{key}/transitions", response=list[IssueTransitionOut])
def list_transitions(request, key: str):
    from . import fieldrules

    issue = _get(request.user, key)
    rules = fieldrules.resolve(issue.project, issue.issue_type)
    return [
        {"id": t.id, "name": t.name, "to": status_ref(t.to_status),
         "require_resolution": t.require_resolution, "require_comment": t.require_comment,
         **rules.transition(t)}
        for t in services.available_transitions(request.user, issue)
    ]


@router.post("/issues/{key}/transitions", response=IssueOut)
def do_transition(request, key: str, data: IssueTransitionIn):
    issue = _get(request.user, key)
    services.transition_issue(request.user, issue, **data.dict())
    return _detail(request.user, issue.id)


@router.post("/issues/{key}/archive", response=IssueOut)
def archive(request, key: str):
    issue = _get(request.user, key)
    services.archive_issue(request.user, issue)
    return _detail(request.user, issue.id)


@router.post("/issues/{key}/restore", response=IssueOut)
def restore(request, key: str):
    issue = _get(request.user, key)
    services.restore_issue(request.user, issue)
    return _detail(request.user, issue.id)


class ArchivedIssueOut(Schema):
    id: int
    key: str
    summary: str
    type: IssueTypeOut
    status: StatusOut
    archived_at: str | None
    archived_by: UserRef | None


@router.get("/projects/{pkey}/archived-issues", response=list[ArchivedIssueOut])
def archived_issues(request, pkey: str, q: str = "", limit: int = 100):
    from apps.projects.models import Project

    project = Project.objects.filter(key=pkey.upper()).first()
    if project is None or not has_perm(request.user, project, Perm.BROWSE):
        raise NotFound("Proyecto no encontrado")
    qs = Issue.objects.filter(project=project, is_archived=True).select_related(
        "issue_type", "status", "archived_by").order_by("-archived_at")
    if q:
        qs = qs.filter(Q(key__icontains=q) | Q(summary__icontains=q))
    return [{
        "id": i.id, "key": i.key, "summary": i.summary, "type": type_ref(i.issue_type),
        "status": status_ref(i.status),
        "archived_at": i.archived_at.isoformat() if i.archived_at else None,
        "archived_by": user_ref(i.archived_by),
    } for i in qs[: min(limit, 500)]]


@router.post("/issues/{key}/move", response=IssueOut)
def move(request, key: str, data: IssueMoveIn):
    from apps.projects.models import Project

    issue = _get(request.user, key)
    target = Project.objects.filter(key=data.project.upper()).first()
    if target is None or not has_perm(request.user, target, Perm.BROWSE):
        raise NotFound("Proyecto no encontrado")
    moved = services.move_issue(request.user, issue, target, type_map=data.type_map,
                                status_map=data.status_map, fields=data.fields)
    return _detail(request.user, moved.id)


# ------------------------------------------------------------------ history / children

@router.get("/issues/{key}/history", response=list[HistoryOut])
def history(request, key: str):
    issue = _get(request.user, key)
    return [
        {"id": h.id, "actor": user_ref(h.actor), "created_at": h.created_at.isoformat(),
         "items": h.items}
        for h in issue.history.select_related("actor")[:500]
    ]


# ------------------------------------------------------------------ comments

@router.get("/issues/{key}/comments", response=list[CommentOut])
def list_comments(request, key: str, order: str = "desc"):
    issue = _get(request.user, key)
    perms = project_perms(request.user, issue.project)
    qs = issue.comments.select_related("author").order_by(
        "-created_at" if order == "desc" else "created_at"
    )
    return [_comment_out(c, request.user, perms) for c in qs]


@router.post("/issues/{key}/comments", response={201: CommentOut})
def add_comment(request, key: str, data: CommentIn):
    issue = _get(request.user, key)
    c = services.add_comment(request.user, issue, data.body)
    return 201, _comment_out(c, request.user, project_perms(request.user, issue.project))


def _get_comment(user, cid: int) -> Comment:
    c = Comment.objects.select_related("issue__project", "author").filter(pk=cid).first()
    if c is None or not has_perm(user, c.issue.project, Perm.BROWSE):
        raise NotFound("Comentario no encontrado")
    return c


@router.patch("/comments/{cid}", response=CommentOut)
def edit_comment(request, cid: int, data: CommentIn):
    c = services.edit_comment(request.user, _get_comment(request.user, cid), data.body)
    return _comment_out(c, request.user, project_perms(request.user, c.issue.project))


@router.delete("/comments/{cid}", response={204: None})
def delete_comment(request, cid: int):
    services.delete_comment(request.user, _get_comment(request.user, cid))
    return 204, None


# ------------------------------------------------------------------ attachments

@router.post("/issues/{key}/attachments", response={201: list[AttachmentOut]})
def upload(request, key: str, files: File[list[UploadedFile]]):
    issue = _get(request.user, key)
    if not files:
        raise ValidationFailed("No se envió ningún archivo")
    out = [_attachment(services.add_attachment(request.user, issue, f)) for f in files[:20]]
    return 201, out


def _get_attachment(user, aid: int) -> Attachment:
    a = Attachment.objects.select_related("issue__project", "uploaded_by").filter(pk=aid).first()
    if a is None or not has_perm(user, a.issue.project, Perm.BROWSE):
        raise NotFound("Adjunto no encontrado")
    return a


INLINE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf",
                "text/plain", "video/mp4")


@router.get("/attachments/{aid}/download")
def download(request, aid: int, inline: bool = True):
    a = _get_attachment(request.user, aid)
    as_inline = inline and a.mime_type in INLINE_TYPES
    resp = FileResponse(a.file.open("rb"), as_attachment=not as_inline, filename=a.filename,
                        content_type=a.mime_type)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; media-src 'self'"
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@router.delete("/attachments/{aid}", response={204: None})
def delete_attachment(request, aid: int):
    services.delete_attachment(request.user, _get_attachment(request.user, aid))
    return 204, None


# ------------------------------------------------------------------ links

@router.post("/issues/{key}/links", response=IssueOut)
def create_link(request, key: str, data: LinkIn):
    issue = _get(request.user, key)
    other = _get(request.user, data.target)
    lt = IssueLinkType.objects.filter(pk=data.link_type_id).first()
    if lt is None:
        raise ValidationFailed("Tipo de vínculo inválido")
    if data.direction == "inward":
        services.link_issues(request.user, other, issue, lt)
    else:
        services.link_issues(request.user, issue, other, lt)
    return _detail(request.user, issue.id)


@router.delete("/links/{lid}", response={204: None})
def delete_link(request, lid: int):
    link = IssueLink.objects.select_related("source__project", "target", "link_type").filter(
        pk=lid
    ).first()
    if link is None or not has_perm(request.user, link.source.project, Perm.BROWSE):
        raise NotFound("Vínculo no encontrado")
    services.unlink(request.user, link)
    return 204, None


@router.post("/issues/{key}/weblinks", response={201: WebLinkOut})
def add_weblink(request, key: str, data: WebLinkIn):
    w = services.add_web_link(request.user, _get(request.user, key), data.url, data.title)
    return 201, {"id": w.id, "url": w.url, "title": w.title}


@router.delete("/weblinks/{wid}", response={204: None})
def delete_weblink(request, wid: int):
    w = WebLink.objects.select_related("issue__project").filter(pk=wid).first()
    if w is None or not has_perm(request.user, w.issue.project, Perm.BROWSE):
        raise NotFound("Enlace no encontrado")
    services.delete_web_link(request.user, w)
    return 204, None


# ------------------------------------------------------------------ worklogs

def _worklog(w: Worklog) -> dict:
    return {"id": w.id, "author": user_ref(w.author), "time_spent": w.time_spent,
            "started_at": w.started_at.isoformat(), "comment": w.comment,
            "created_at": w.created_at.isoformat()}


@router.get("/issues/{key}/worklogs", response=list[WorklogOut])
def list_worklogs(request, key: str):
    issue = _get(request.user, key)
    return [_worklog(w) for w in issue.worklogs.select_related("author")]


@router.post("/issues/{key}/worklogs", response={201: WorklogOut})
def add_worklog(request, key: str, data: WorklogIn):
    issue = _get(request.user, key)
    w = services.log_work(request.user, issue, time_spent=data.time_spent,
                          started_at=data.started_at or timezone.now(), comment=data.comment,
                          remaining=data.remaining_estimate)
    return 201, _worklog(w)


@router.delete("/worklogs/{wid}", response={204: None})
def delete_worklog(request, wid: int):
    w = Worklog.objects.select_related("issue__project").filter(pk=wid).first()
    if w is None or not has_perm(request.user, w.issue.project, Perm.BROWSE):
        raise NotFound("Registro no encontrado")
    services.delete_worklog(request.user, w)
    return 204, None


# ------------------------------------------------------------------ watchers / votes

@router.get("/issues/{key}/watchers", response=WatchersOut)
def watchers(request, key: str):
    issue = _get(request.user, key)
    ws = list(issue.watchers.all())
    return {"watching": any(w.id == request.user.id for w in ws),
            "watchers": [user_ref(w) for w in ws]}


@router.post("/issues/{key}/watchers", response={204: None})
def watch(request, key: str, user_id: int | None = None):
    from django.contrib.auth import get_user_model

    issue = _get(request.user, key)
    target = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    services.set_watching(request.user, issue, True, target)
    return 204, None


@router.delete("/issues/{key}/watchers", response={204: None})
def unwatch(request, key: str, user_id: int | None = None):
    from django.contrib.auth import get_user_model

    issue = _get(request.user, key)
    target = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    services.set_watching(request.user, issue, False, target)
    return 204, None


@router.post("/issues/{key}/votes", response={204: None})
def vote(request, key: str):
    services.set_vote(request.user, _get(request.user, key), True)
    return 204, None


@router.delete("/issues/{key}/votes", response={204: None})
def unvote(request, key: str):
    services.set_vote(request.user, _get(request.user, key), False)
    return 204, None


# ------------------------------------------------------------------ labels

@router.get("/labels", response=list[str])
def labels(request, q: str = "", project: str | None = None):
    qs = Issue.objects.filter(project__in=visible_projects(request.user))
    if project:
        qs = qs.filter(project__key=project.upper())
    rows = (
        qs.annotate(label=Func(F("labels"), function="unnest"))
        .values("label").annotate(n=Count("id")).order_by("-n")
    )
    out = [r["label"] for r in rows if not q or q.lower() in r["label"].lower()]
    return out[:30]
