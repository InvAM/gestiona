"""Column catalogue of the «Lista» view and row serialization.

The frontend never hard-codes a field: it asks `GET /projects/{key}/list/meta` for the
columns (standard fields + the project's custom fields), each with its label, the kind of
editor it needs, the PATCH field it writes and the JQL name it sorts by. The same ids are
accepted by the CSV export (`GET /search/export?columns=...`).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from apps.core.errors import ValidationFailed
from apps.core.schemas import priority_ref, status_ref, type_ref, user_ref
from apps.issues.models import HISTORY_FIELD_LABELS, CustomField, Issue, IssueType
from apps.projects.models import Perm
from apps.projects.permissions import project_perms
from apps.search.jql import is_orderable

# Labels not present in the history vocabulary (GET /meta → issue_fields).
EXTRA_LABELS = {"updated": "Actualizada", "resolved": "Resuelta", "epic": "Épica",
                "team": "Equipo"}


@dataclass(frozen=True)
class Column:
    id: str
    kind: str
    field: str | None  # PATCH /issues/{key} field (None = read-only or special editor)
    sort: str | None  # JQL ORDER BY name (None = not sortable)
    width: int
    default: bool = False
    label_key: str | None = None  # key in HISTORY_FIELD_LABELS when it differs from id

    @property
    def label(self) -> str:
        k = self.label_key or self.id
        return HISTORY_FIELD_LABELS.get(k) or EXTRA_LABELS.get(k) or k


# Display order of the column chooser; `default` = visible on a fresh layout.
STANDARD_COLUMNS: list[Column] = [
    Column("type", "type", "issue_type", "type", 64, True, "issue_type"),
    Column("key", "key", None, "key", 110, True),
    Column("summary", "text", "summary", "summary", 380, True),
    Column("status", "status", None, "status", 150, True),
    Column("assignee", "user", "assignee", "assignee", 180, True),
    Column("priority", "priority", "priority", "priority", 120, True),
    Column("parent", "parent", "parent", "parent", 200, True),
    Column("due_date", "date", "due_date", "due", 130, True),
    Column("reporter", "user", "reporter", "reporter", 180),
    Column("labels", "labels", "labels", "labels", 180),
    Column("components", "components", "components", "component", 180),
    Column("fix_versions", "versions", "fix_versions", "fixVersion", 170),
    Column("affects_versions", "versions", "affects_versions", "affectedVersion", 170),
    Column("sprint", "sprint", "sprint", "sprint", 170),
    Column("story_points", "number", "story_points", "storypoints", 100),
    Column("original_estimate", "duration", "original_estimate", "originalEstimate", 130),
    Column("remaining_estimate", "duration", "remaining_estimate", "remainingEstimate",
           130),
    Column("time_spent", "duration", None, "timeSpent", 130),
    Column("start_date", "date", "start_date", "startdate", 130),
    Column("flagged", "bool", "flagged", "flagged", 100),
    Column("resolution", "resolution", None, "resolution", 140),
    Column("created", "datetime", None, "created", 130),
    Column("updated", "datetime", None, "updated", 130),
    Column("resolved", "datetime", None, "resolved", 130),
]
STANDARD_BY_ID = {c.id: c for c in STANDARD_COLUMNS}


def has_team_field() -> bool:
    """`Issue.team` is added by the planning app; the column appears once it exists."""
    try:
        Issue._meta.get_field("team")
    except FieldDoesNotExist:
        return False
    return True


def team_is_editable() -> bool:
    """True once PATCH /issues/{key} accepts `team` (planning app)."""
    from apps.issues.api import IssuePatch
    from apps.issues.services import EDITABLE_FIELDS

    return "team" in IssuePatch.model_fields and "team" in EDITABLE_FIELDS


def project_custom_fields(project):
    return CustomField.objects.filter(Q(projects__isnull=True) | Q(projects=project)) \
        .distinct().prefetch_related("issue_types").order_by("position", "id")


def column_catalog(project) -> list[dict]:
    cols = [{"id": c.id, "label": c.label, "kind": c.kind, "field": c.field, "sort": c.sort,
             "width": c.width, "default": c.default, "custom_field_id": None,
             "custom_kind": None} for c in STANDARD_COLUMNS]
    if has_team_field():
        cols.append({"id": "team", "label": HISTORY_FIELD_LABELS.get("team")
                     or EXTRA_LABELS["team"], "kind": "team",
                     "field": "team" if team_is_editable() else None,
                     "sort": "team" if is_orderable("team") else None,
                     "width": 160, "default": False, "custom_field_id": None,
                     "custom_kind": None})
    for cf in project_custom_fields(project):
        cols.append({"id": f"cf:{cf.id}", "label": cf.name, "kind": "custom",
                     "field": "custom_fields", "sort": f"cf[{cf.id}]",  # every kind sorts
                     "width": 220 if cf.kind == "textarea" else 170, "default": False,
                     "custom_field_id": cf.id, "custom_kind": cf.kind})
    return cols


# ------------------------------------------------------------------ rows

def row_queryset(qs):
    rels = ["project", "issue_type", "status", "priority", "assignee", "reporter", "resolution",
            "sprint", "parent", "parent__issue_type", "parent__parent",
            "parent__parent__issue_type"]
    if has_team_field():
        rels.append("team")
    # A correlated count (not a JOIN + GROUP BY over every matching row): with ORDER BY +
    # LIMIT, Postgres sorts first and only counts the children of the returned page.
    children = (Issue.objects.filter(parent=OuterRef("pk")).order_by().values("parent")
                .annotate(n=Count("id")).values("n"))
    return qs.select_related(*rels).prefetch_related(
        "components", "fix_versions", "affects_versions",
    ).annotate(n_children=Coalesce(Subquery(children, output_field=IntegerField()), 0))


def epic_of(i: Issue) -> Issue | None:
    p = i.parent
    if p is None:
        return None
    if p.issue_type.level == IssueType.Level.EPIC:
        return p
    if i.issue_type.level == IssueType.Level.SUBTASK and p.parent and \
            p.parent.issue_type.level == IssueType.Level.EPIC:
        return p.parent
    return None


def _named(objs) -> list[dict]:
    return [{"id": o.id, "name": o.name} for o in objs]


class RowContext:
    """Per-request caches: permissions by project, custom-field user ids to resolve."""

    def __init__(self, user):
        self.user = user
        self._perms: dict[int, set[str]] = {}
        self.user_ids: set[int] = set()
        self._user_cf = {str(i) for i in CustomField.objects.filter(
            kind__in=[CustomField.Kind.USER, CustomField.Kind.MULTIUSER]
        ).values_list("id", flat=True)}

    def perms(self, issue: Issue) -> list[str]:
        p = self._perms.get(issue.project_id)
        if p is None:
            p = project_perms(self.user, issue.project)
            self._perms[issue.project_id] = p
        if issue.is_archived:  # read-only, same rule as IssueOut.permissions
            p = p & {Perm.BROWSE.value, Perm.ADMINISTER.value, Perm.DELETE_ISSUES.value}
        return sorted(p)

    def collect_users(self, custom: dict) -> None:
        for k, v in custom.items():
            if k in self._user_cf:
                for uid in v if isinstance(v, list) else [v]:
                    if isinstance(uid, int):
                        self.user_ids.add(uid)

    def users(self) -> dict[str, dict]:
        User = get_user_model()
        return {str(u.id): user_ref(u) for u in User.objects.filter(id__in=self.user_ids)}


def row_out(i: Issue, ctx: RowContext, group=None) -> dict:
    from apps.boards.api import epic_ref

    custom = {k: v for k, v in (i.custom_fields or {}).items() if k.isdigit()}
    ctx.collect_users(custom)
    parent = i.parent
    row = {
        "id": i.id, "key": i.key, "project_key": i.project.key, "summary": i.summary,
        "type": type_ref(i.issue_type), "status": status_ref(i.status),
        "priority": priority_ref(i.priority),
        "resolution": {"id": i.resolution.id, "name": i.resolution.name}
        if i.resolution else None,
        "assignee": user_ref(i.assignee), "reporter": user_ref(i.reporter),
        "parent": {"id": parent.id, "key": parent.key, "summary": parent.summary,
                   "type": type_ref(parent.issue_type)} if parent else None,
        "epic": epic_ref(epic_of(i)),
        "labels": i.labels,
        "components": _named(i.components.all()),
        "fix_versions": _named(i.fix_versions.all()),
        "affects_versions": _named(i.affects_versions.all()),
        "sprint": {"id": i.sprint.id, "name": i.sprint.name, "state": i.sprint.state}
        if i.sprint else None,
        "story_points": i.story_points,
        "original_estimate": i.original_estimate,
        "remaining_estimate": i.remaining_estimate,
        "time_spent": i.time_spent,
        "start_date": i.start_date.isoformat() if i.start_date else None,
        "due_date": i.due_date.isoformat() if i.due_date else None,
        "flagged": i.flagged,
        "custom_fields": custom,
        "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat(),
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "is_archived": i.is_archived,
        "children_count": getattr(i, "n_children", 0),
        "permissions": ctx.perms(i),
        "group": group,
        "team": None,
    }
    if has_team_field():
        team = getattr(i, "team", None)
        row["team"] = {"id": team.id, "name": team.name} if team else None
    return row


# ------------------------------------------------------------------ CSV

def _duration(seconds: int | None) -> str:
    """Jira format (1d = 8h, 1w = 5d), same as the UI."""
    if not seconds:
        return ""
    out, rest = [], int(seconds)
    for unit, size in (("w", 5 * 8 * 3600), ("d", 8 * 3600), ("h", 3600), ("m", 60)):
        n, rest = divmod(rest, size)
        if n:
            out.append(f"{n}{unit}")
    return " ".join(out) or "0m"


def _iso(d) -> str:
    return d.isoformat() if d else ""


def resolve_export_columns(ids: list[str]) -> tuple[list[str], dict[int, CustomField]]:
    """Validate column ids for the export. Returns (ids, custom fields by id)."""
    cf_ids = []
    for c in ids:
        if c in STANDARD_BY_ID or (c == "team" and has_team_field()):
            continue
        if c.startswith("cf:") and c[3:].isdigit():
            cf_ids.append(int(c[3:]))
            continue
        raise ValidationFailed(f"Columna desconocida: {c}", code="columns")
    cfs = {cf.id: cf for cf in CustomField.objects.filter(id__in=cf_ids)}
    missing = [i for i in cf_ids if i not in cfs]
    if missing:
        raise ValidationFailed(f"Columna desconocida: cf:{missing[0]}", code="columns")
    return ids, cfs


def column_labels(ids: list[str], cfs: dict[int, CustomField]) -> list[str]:
    out = []
    for c in ids:
        if c.startswith("cf:"):
            out.append(cfs[int(c[3:])].name)
        elif c == "team":
            out.append(EXTRA_LABELS["team"])
        else:
            out.append(STANDARD_BY_ID[c].label)
    return out


def _custom_text(cf: CustomField, value, users: dict[int, str]) -> str:
    if value in (None, "", []):
        return ""
    options = {o.get("id"): o.get("value") for o in cf.options or []}
    if cf.kind == CustomField.Kind.SELECT:
        return str(options.get(value, value))
    if cf.kind in (CustomField.Kind.MULTISELECT, CustomField.Kind.CHECKBOX):
        return ", ".join(str(options.get(v, v)) for v in value)
    if cf.kind == CustomField.Kind.USER:
        return users.get(value, "")
    if cf.kind == CustomField.Kind.MULTIUSER:
        return ", ".join(users.get(v, "") for v in value)
    if cf.kind == CustomField.Kind.LABELS:
        return " ".join(value)
    return str(value)


def export_values(issues: list[Issue], ids: list[str], cfs: dict[int, CustomField]):
    """Yield one CSV row per issue with the values of `ids` (already validated)."""
    user_cf = {str(cf.id) for cf in cfs.values()
               if cf.kind in (CustomField.Kind.USER, CustomField.Kind.MULTIUSER)}
    uids: set[int] = set()
    for i in issues:
        for k in user_cf:
            v = (i.custom_fields or {}).get(k)
            uids.update(x for x in (v if isinstance(v, list) else [v]) if isinstance(x, int))
    User = get_user_model()
    users = {u.id: u.display_name for u in User.objects.filter(id__in=uids)}

    def value(i: Issue, c: str) -> str:
        if c.startswith("cf:"):
            cf = cfs[int(c[3:])]
            return _custom_text(cf, (i.custom_fields or {}).get(c[3:]), users)
        match c:
            case "key":
                return i.key
            case "type":
                return i.issue_type.name
            case "summary":
                return i.summary
            case "status":
                return i.status.name
            case "assignee":
                return i.assignee.display_name if i.assignee else ""
            case "reporter":
                return i.reporter.display_name if i.reporter else ""
            case "priority":
                return i.priority.name
            case "parent":
                return i.parent.key if i.parent else ""
            case "labels":
                return " ".join(i.labels)
            case "components":
                return ", ".join(x.name for x in i.components.all())
            case "fix_versions":
                return ", ".join(x.name for x in i.fix_versions.all())
            case "affects_versions":
                return ", ".join(x.name for x in i.affects_versions.all())
            case "sprint":
                return i.sprint.name if i.sprint else ""
            case "story_points":
                return "" if i.story_points is None else f"{i.story_points.normalize():f}"
            case "original_estimate" | "remaining_estimate" | "time_spent":
                return _duration(getattr(i, c))
            case "start_date" | "due_date":
                return _iso(getattr(i, c))
            case "flagged":
                return "Sí" if i.flagged else ""
            case "resolution":
                return i.resolution.name if i.resolution else ""
            case "created":
                return _iso(i.created_at)
            case "updated":
                return _iso(i.updated_at)
            case "resolved":
                return _iso(i.resolved_at)
            case "team":
                team = getattr(i, "team", None)
                return team.name if team else ""
        return ""

    for i in issues:
        yield [value(i, c) for c in ids]
