"""Import projects from Jira (Cloud or Server/Data Center) into Gestiona.

Writes directly through the ORM (no notifications, no realtime events, no permission checks
beyond "job owner is a Gestiona admin") and keeps Jira's keys, numbers, dates and authors.

Per project: statuses → workflow, issue types, priorities, resolutions, components, versions,
board + sprints, issues (rank order), parents/epics, comments, worklogs, history, attachments,
custom fields. Issue links are resolved at the end so links across imported projects work.
A project that fails is rolled back (deleted) and the job continues with the next one.
"""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import get_user_model
from django.core.files import File
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.core.ranking import key_between
from apps.core.richtext import to_text
from apps.issues.models import (
    Attachment,
    Comment,
    CustomField,
    Issue,
    IssueHistory,
    IssueLink,
    IssueLinkType,
    IssueType,
    Priority,
    Resolution,
    WebLink,
    Worklog,
)
from apps.issues.services import _clean_labels, update_search_vector
from apps.projects.models import (
    Component,
    Project,
    ProjectMember,
    Role,
    Version,
    project_key_validator,
)
from apps.workflows.models import Status, StatusCategory, Transition, Workflow, WorkflowStatus

from .adf import AdfConverter, adf_to_text
from .jira_client import JiraClient, JiraError
from .models import ImportedObject, ImportJob

log = logging.getLogger(__name__)
User = get_user_model()

CATEGORY = {"new": StatusCategory.TODO, "indeterminate": StatusCategory.IN_PROGRESS,
            "done": StatusCategory.DONE}
CATEGORY_ORDER = {StatusCategory.TODO: 0, StatusCategory.IN_PROGRESS: 1, StatusCategory.DONE: 2}

CF_PREFIX = "com.atlassian.jira.plugin.system.customfieldtypes:"
CF_KINDS = {
    "textfield": CustomField.Kind.TEXT,
    "textarea": CustomField.Kind.TEXTAREA,
    "float": CustomField.Kind.NUMBER,
    "datepicker": CustomField.Kind.DATE,
    "datetime": CustomField.Kind.DATETIME,
    "select": CustomField.Kind.SELECT,
    "radiobuttons": CustomField.Kind.SELECT,
    "multiselect": CustomField.Kind.MULTISELECT,
    "multicheckboxes": CustomField.Kind.CHECKBOX,
    "userpicker": CustomField.Kind.USER,
    "multiuserpicker": CustomField.Kind.MULTIUSER,
    "url": CustomField.Kind.URL,
    "labels": CustomField.Kind.LABELS,
}
STORY_POINT_NAMES = {
    "story points", "story point estimate", "puntos de historia",
    "estimación de puntos de historia", "estimacion de puntos de historia",
}
START_DATE_NAMES = {"start date", "fecha de inicio", "target start"}
FLAGGED_NAMES = {"flagged", "marcado", "impedimento"}

# changelog field (lowercase) → Gestiona history field
HISTORY_FIELDS = {
    "status": "status", "assignee": "assignee", "priority": "priority", "summary": "summary",
    "resolution": "resolution", "description": "description", "labels": "labels",
    "sprint": "sprint", "issuetype": "issue_type", "reporter": "reporter",
    "fix version": "fix_versions", "version": "affects_versions", "component": "components",
    "duedate": "due_date", "parent": "parent", "epic link": "parent",
    "parent link": "parent", "story points": "story_points",
    "story point estimate": "story_points", "timeoriginalestimate": "original_estimate",
    "timeestimate": "remaining_estimate", "timespent": "time_spent", "flagged": "flagged",
    "attachment": "attachment", "link": "link",
}
HISTORY_SKIP = {"rank", "workflow", "worklogid", "worklogtimespent", "comment"}
SPRINT_STATES = {"closed": "closed", "active": "active", "future": "future"}


class ImportAborted(Exception):
    pass


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    d = parse_datetime(s)
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if timezone.is_naive(d):
        d = timezone.make_aware(d, timezone.get_default_timezone())
    return d


def _date(value):
    if not value:
        return None
    d = parse_date(str(value)[:10])
    return d


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value)).quantize(Decimal("0.1"))
    except (InvalidOperation, ValueError):
        return None
    return d if 0 <= d < Decimal("100000") else None


def _int(value) -> int | None:
    try:
        return max(int(value), 0) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_sprint(value) -> dict | None:
    """Cloud returns dicts; old Server/DC returns 'com.atlassian...Sprint@x[id=1,name=..]'."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or "[" not in value:
        return None
    inner = value[value.index("[") + 1: value.rindex("]")]
    pairs = dict(re.findall(r"(\w+)=(.*?)(?=,\w+=|$)", inner))
    if "id" not in pairs:
        return None
    return {
        "id": pairs.get("id"), "name": pairs.get("name") or f"Sprint {pairs['id']}",
        "state": (pairs.get("state") or "future").lower(), "goal": pairs.get("goal") or "",
        "startDate": None if pairs.get("startDate") in ("<null>", "") else pairs.get("startDate"),
        "endDate": None if pairs.get("endDate") in ("<null>", "") else pairs.get("endDate"),
        "completeDate": None if pairs.get("completeDate") in ("<null>", "")
        else pairs.get("completeDate"),
    }


class _OptionSet:
    """Options of a select-like custom field, growing as new Jira values appear."""

    def __init__(self, options: list[dict]):
        self.options = {o["id"]: o for o in options}
        self.by_value = {str(o["value"]).lower(): o["id"] for o in options}
        self.dirty = False

    def id_for(self, jo) -> str | None:
        if not isinstance(jo, dict):
            jo = {"value": str(jo)}
        value = str(jo.get("value") or jo.get("name") or "").strip()
        if not value:
            return None
        if value.lower() in self.by_value:
            return self.by_value[value.lower()]
        oid = f"j{jo.get('id') or len(self.options) + 1}"
        while oid in self.options:
            oid += "x"
        self.options[oid] = {"id": oid, "value": value[:120]}
        self.by_value[value.lower()] = oid
        self.dirty = True
        return oid

    def as_list(self) -> list[dict]:
        return list(self.options.values())


@dataclass
class FieldMap:
    sprint: str | None = None
    story_points: list[str] = field(default_factory=list)
    epic_link: str | None = None
    start_date: str | None = None
    flagged: str | None = None
    custom: dict[str, dict] = field(default_factory=dict)  # jira id -> {name, kind}

    @classmethod
    def from_fields(cls, fields: list[dict]) -> FieldMap:
        fm = cls()
        for f in fields:
            fid, name = f.get("id"), (f.get("name") or "").strip()
            schema = f.get("schema") or {}
            custom = schema.get("custom") or ""
            lname = name.lower()
            if not f.get("custom"):
                continue
            if custom == "com.pyxis.greenhopper.jira:gh-sprint":
                fm.sprint = fid
            elif custom == "com.pyxis.greenhopper.jira:gh-epic-link":
                fm.epic_link = fid
            elif lname in STORY_POINT_NAMES and schema.get("type") == "number":
                fm.story_points.append(fid)
            elif lname in START_DATE_NAMES and schema.get("type") in ("date", "datetime"):
                fm.start_date = fm.start_date or fid
            elif lname in FLAGGED_NAMES and custom.endswith("multicheckboxes"):
                fm.flagged = fid
            elif custom.startswith(CF_PREFIX) and custom[len(CF_PREFIX):] in CF_KINDS:
                fm.custom[fid] = {"name": name[:80], "kind": CF_KINDS[custom[len(CF_PREFIX):]]}
        return fm


@dataclass
class ProjectStats:
    key: str
    target_key: str
    project_id: int | None = None
    issues: int = 0
    comments: int = 0
    worklogs: int = 0
    attachments: int = 0
    history: int = 0
    sprints: int = 0
    custom_fields: int = 0


class JiraImporter:
    def __init__(self, job: ImportJob, client: JiraClient | None = None):
        self.job = job
        self.client = client or JiraClient(job.base_url, job.auth_email, job.auth_token)
        self.site = self.client.host
        self.actor = job.created_by
        opts = job.options or {}
        self.opt_attachments = opts.get("attachments", True)
        self.opt_history = opts.get("history", True)
        self.opt_create_users = opts.get("create_users", True)
        self.opt_web_links = opts.get("web_links", False)
        self.max_attachment = int(opts.get("max_attachment_mb", 200)) * 1024 * 1024
        self.users: dict[str, Any] = {}
        self.issue_by_key: dict[str, Issue] = {}
        self.pending_links: list[tuple[int, dict]] = []
        self.users_created = 0
        self.converter = AdfConverter(self._resolve_mention)
        self.fields: FieldMap | None = None

    # ------------------------------------------------------------------ job bookkeeping
    def _log(self, level: str, message: str) -> None:
        entry = {"level": level, "message": message[:1000], "at": timezone.now().isoformat()}
        self.job.log = [*self.job.log, entry][-500:]
        ImportJob.objects.filter(pk=self.job.pk).update(log=self.job.log)
        getattr(log, "warning" if level != "info" else "info")("import %s: %s", self.job.pk,
                                                                message)

    def _progress(self, **kw) -> None:
        self.job.progress = {**self.job.progress, **kw}
        ImportJob.objects.filter(pk=self.job.pk).update(progress=self.job.progress)

    def run(self) -> ImportJob:
        job = self.job
        job.state = ImportJob.State.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["state", "started_at", "updated_at"])
        results: list[dict] = []
        failures = 0
        try:
            self.fields = FieldMap.from_fields(self.client.fields())
            for spec in job.projects:
                stats = ProjectStats(key=spec["key"],
                                     target_key=(spec.get("target_key") or spec["key"]).upper())
                try:
                    self._import_project(spec, stats)
                    results.append({**stats.__dict__, "ok": True})
                    self._log("info", f"{stats.key}: {stats.issues} incidencias importadas como "
                                      f"{stats.target_key}")
                except Exception as e:  # keep going with the other projects
                    failures += 1
                    msg = e.message if isinstance(e, (JiraError,)) else str(e)
                    log.exception("import %s project %s failed", job.pk, stats.key)
                    self._log("error", f"{stats.key}: {msg}")
                    self._rollback(stats)
                    results.append({**stats.__dict__, "ok": False, "error": msg,
                                    "project_id": None})
            self._progress(stage="links", project=None)
            self._create_links()
            job.state = (ImportJob.State.FAILED if failures == len(job.projects)
                         else ImportJob.State.PARTIAL if failures else ImportJob.State.DONE)
        except Exception as e:
            log.exception("import %s failed", job.pk)
            job.state = ImportJob.State.FAILED
            job.error = e.message if isinstance(e, JiraError) else str(e)
            self._log("error", job.error)
        job.result = results
        job.progress = {**job.progress, "stage": "finished", "users_created": self.users_created}
        job.finished_at = timezone.now()
        job.auth_token = ""  # never keep the credential
        job.save(update_fields=["state", "result", "progress", "finished_at", "auth_token",
                                "error", "updated_at"])
        return job

    def _rollback(self, stats: ProjectStats) -> None:
        if not stats.project_id:
            return
        project = Project.objects.filter(pk=stats.project_id).first()
        if project is None:
            return
        for att in Attachment.objects.filter(issue__project=project):
            att.file.delete(save=False)
        workflow = project.workflow
        self.issue_by_key = {k: v for k, v in self.issue_by_key.items()
                             if v.project_id != project.id}
        self.pending_links = [(i, link) for i, link in self.pending_links
                              if Issue.objects.filter(pk=i).exclude(project=project).exists()]
        project.delete()
        if workflow.name.startswith("Jira ") and not workflow.projects.exists():
            workflow.delete()

    # ------------------------------------------------------------------ users
    def _user(self, ju: dict | None):
        if not ju:
            return None
        ext = ju.get("accountId") or ju.get("key") or ju.get("name")
        if not ext:
            return None
        if ext in self.users:
            return self.users[ext]
        user = None
        io = ImportedObject.objects.filter(source="jira", site=self.site, kind="user",
                                           external_id=ext).first()
        if io:
            user = User.objects.filter(pk=io.object_id).first()
        email = (ju.get("emailAddress") or "").strip().lower()
        name = (ju.get("displayName") or ju.get("name") or "Usuario de Jira").strip()[:150]
        if user is None and email:
            user = User.objects.filter(email__iexact=email).first()
        if user is None:
            same_name = list(User.objects.filter(full_name__iexact=name)[:2])
            if len(same_name) == 1:
                user = same_name[0]
        if user is None:
            if not self.opt_create_users:
                self.users[ext] = None
                return None
            slug = re.sub(r"[^a-z0-9]+", "-", str(ext).lower()).strip("-")[:60] or "usuario"
            user = User.objects.create_user(
                email=email or f"jira-{slug}@importado.invalid", password=None,
                full_name=name, is_active=False,
            )
            self.users_created += 1
        ImportedObject.objects.get_or_create(
            source="jira", site=self.site, kind="user", external_id=ext,
            defaults={"object_id": user.pk, "job": self.job},
        )
        self.users[ext] = user
        return user

    def _resolve_mention(self, account_id: str, label: str):
        user = self.users.get(account_id)
        if user is None and account_id:
            io = ImportedObject.objects.filter(source="jira", site=self.site, kind="user",
                                               external_id=account_id).first()
            user = User.objects.filter(pk=io.object_id).first() if io else None
        return (user.pk, user.display_name) if user else None

    # ------------------------------------------------------------------ lookups
    def _status(self, js: dict) -> Status:
        name = (js.get("name") or "Sin estado").strip()[:60]
        st = Status.objects.filter(name__iexact=name).first()
        if st is None:
            cat = CATEGORY.get(((js.get("statusCategory") or {}).get("key")), StatusCategory.TODO)
            st = Status.objects.create(name=name, category=cat)
        return st

    def _issue_type(self, jt: dict) -> IssueType:
        name = (jt.get("name") or "Tarea").strip()[:60]
        it = IssueType.objects.filter(name__iexact=name).first()
        if it is None:
            level = jt.get("hierarchyLevel")
            if level is None:
                level = -1 if jt.get("subtask") else 0
            level = -1 if level < 0 else (1 if level >= 1 else 0)
            icon = {-1: "subtask", 1: "epic"}.get(level, "task")
            if level == 0 and ("bug" in name.lower() or "error" in name.lower()):
                icon = "bug"
            it = IssueType.objects.create(
                name=name, level=level, icon=icon,
                description=(jt.get("description") or "")[:255],
                position=IssueType.objects.count(),
            )
        return it

    def _priority(self, jp: dict | None) -> Priority:
        if not jp:
            return Priority.objects.filter(is_default=True).first() or Priority.objects.first()
        name = (jp.get("name") or "").strip()[:40]
        pr = Priority.objects.filter(name__iexact=name).first()
        if pr is None:
            pr = Priority.objects.create(name=name or "Media", position=Priority.objects.count())
        return pr

    def _resolution(self, jr: dict | None) -> Resolution | None:
        if not jr:
            return None
        name = (jr.get("name") or "").strip()[:60]
        res = Resolution.objects.filter(name__iexact=name).first()
        if res is None and name:
            res = Resolution.objects.create(name=name, position=Resolution.objects.count())
        return res

    # ------------------------------------------------------------------ project
    def _import_project(self, spec: dict, stats: ProjectStats) -> None:
        c = self.client
        key, target_key = spec["key"], stats.target_key
        self._progress(stage="project", project=key, done=0, total=0)
        project_key_validator(target_key)
        if Project.objects.filter(key=target_key).exists():
            raise ImportAborted(f"Ya existe un proyecto con la clave {target_key} en Gestiona")
        jp = c.project(key)
        name = (spec.get("target_name") or jp.get("name") or target_key).strip()[:80]
        if Project.objects.filter(name__iexact=name).exists():
            name = f"{name[:70]} (Jira)"
            if Project.objects.filter(name__iexact=name).exists():
                raise ImportAborted(f"Ya existe un proyecto llamado {name}")

        # ---- statuses / workflow
        status_by_id: dict[str, Status] = {}
        ordered: list[Status] = []
        for group in c.project_statuses(key):
            for js in group.get("statuses", []):
                st = self._status(js)
                status_by_id[str(js.get("id"))] = st
                if st not in ordered:
                    ordered.append(st)
        if not ordered:
            ordered = [self._status({"name": "Por hacer", "statusCategory": {"key": "new"}})]
        ordered.sort(key=lambda s: CATEGORY_ORDER.get(s.category, 0))
        workflow = self._create_workflow(target_key, ordered)

        # ---- types
        type_by_id: dict[str, IssueType] = {}
        for jt in jp.get("issueTypes", []):
            type_by_id[str(jt.get("id"))] = self._issue_type(jt)

        boards = c.boards(key)
        jboard = next((b for b in boards if b.get("type") == "scrum"),
                      boards[0] if boards else None)
        if jp.get("projectTypeKey") == "business":
            template = Project.Template.BUSINESS
        elif jboard and jboard.get("type") == "kanban":
            template = Project.Template.KANBAN
        else:
            template = Project.Template.SCRUM

        lead = self._user(jp.get("lead"))
        if lead is None or not lead.is_active:
            lead = self.actor
        access = spec.get("access") or Project.Access.LIMITED
        description = jp.get("description") or ""
        project = Project.objects.create(
            key=target_key, name=name, description=description if isinstance(description, str)
            else adf_to_text(description), template=template, access=access, lead=lead,
            workflow=workflow, created_by=self.actor,
        )
        stats.project_id = project.id
        project.issue_types.set(set(type_by_id.values()))
        admin_role = Role.objects.admin_role()
        member_role = Role.objects.default_role()
        for u in {lead, self.actor}:
            ProjectMember.objects.get_or_create(project=project, user=u,
                                                defaults={"role": admin_role})

        # ---- components / versions
        components = {}
        for jc in c.components(key):
            comp, _ = Component.objects.get_or_create(
                project=project, name=(jc.get("name") or "")[:80],
                defaults={"description": (jc.get("description") or "")[:2000],
                          "lead": self._user(jc.get("lead"))},
            )
            components[str(jc.get("id"))] = comp
        versions = {}
        for pos, jv in enumerate(c.versions(key)):
            status = Version.Status.ARCHIVED if jv.get("archived") else \
                Version.Status.RELEASED if jv.get("released") else Version.Status.UNRELEASED
            ver, _ = Version.objects.get_or_create(
                project=project, name=(jv.get("name") or "")[:80],
                defaults={
                    "description": (jv.get("description") or "")[:2000], "status": status,
                    "start_date": _date(jv.get("startDate")),
                    "release_date": _date(jv.get("releaseDate")), "position": pos,
                    "released_at": _dt(jv.get("releaseDate")) if jv.get("released") else None,
                },
            )
            versions[str(jv.get("id"))] = ver

        # ---- board + sprints
        from apps.boards.models import Board, Sprint
        from apps.boards.services import create_default_board

        board = create_default_board(project, self.actor)
        if jboard:
            board.name = (jboard.get("name") or board.name)[:80]
            board.save(update_fields=["name"])
        sprints: dict[str, Sprint] = {}

        def sprint_for(js: dict) -> Sprint:
            sid = str(js.get("id"))
            if sid not in sprints:
                state = SPRINT_STATES.get(str(js.get("state", "")).lower(), "future")
                sprints[sid] = Sprint.objects.create(
                    board=board, name=(js.get("name") or f"Sprint {sid}")[:80],
                    goal=js.get("goal") or "", state=state,
                    start_date=_dt(js.get("startDate")), end_date=_dt(js.get("endDate")),
                    completed_at=_dt(js.get("completeDate")), position=len(sprints),
                )
            return sprints[sid]

        if board.kind == Board.Kind.SCRUM:
            for b in boards:
                if b.get("type") != "scrum":
                    continue
                for js in c.sprints(b["id"]):
                    if js.get("originBoardId") in (None, b["id"]):
                        sprint_for(js)

        # ---- issues
        fm = self.fields
        try:
            total = c.count(f'project = "{key}"')
        except JiraError:
            total = 0
        self._progress(stage="issues", project=key, done=0, total=total)
        rank = None
        max_number = 0
        parents: list[tuple[Issue, str]] = []
        cf_values: dict[str, list[tuple[Issue, Any]]] = {}
        members: set = set()
        try:
            iterator = c.search(f'project = "{key}" ORDER BY Rank ASC')
            first = next(iterator, None)
        except JiraError as e:
            if e.status != 400:
                raise
            iterator = c.search(f'project = "{key}" ORDER BY created ASC')
            first = next(iterator, None)

        def all_issues():
            if first is not None:
                yield first
                yield from iterator

        for ji in all_issues():
            f = ji.get("fields") or {}
            try:
                number = int(str(ji["key"]).rsplit("-", 1)[1])
            except (ValueError, IndexError):
                number = max_number + 1
            if Issue.objects.filter(project=project, number=number).exists():
                number = max_number + 1
            max_number = max(max_number, number)
            rank = key_between(rank, None)
            jt = f.get("issuetype") or {}
            itype = type_by_id.get(str(jt.get("id"))) or self._issue_type(jt)
            if not project.issue_types.filter(pk=itype.pk).exists():
                project.issue_types.add(itype)
            js = f.get("status") or {}
            status = status_by_id.get(str(js.get("id"))) or self._status(js)
            if not workflow.workflow_statuses.filter(status=status).exists():
                self._add_status(workflow, status)
            assignee = self._user(f.get("assignee"))
            reporter = self._user(f.get("reporter") or f.get("creator"))
            for u in (assignee, reporter):
                if u is not None and u.is_active:
                    members.add(u)
            description = self.converter.convert(f.get("description"))
            points = None
            for fid in fm.story_points:
                points = _decimal(f.get(fid))
                if points is not None:
                    break
            sprint, closed = None, []
            if fm.sprint and f.get(fm.sprint):
                parsed = [p for p in (parse_sprint(v) for v in f.get(fm.sprint) or []) if p]
                for p in parsed:
                    sp = sprint_for(p)
                    if sp.state == "closed":
                        closed.append(sp)
                    else:
                        sprint = sp
            resolution = self._resolution(f.get("resolution"))
            created = _dt(f.get("created")) or timezone.now()
            issue = Issue.objects.create(
                project=project, number=number, key=f"{target_key}-{number}",
                issue_type=itype, summary=(f.get("summary") or ji["key"])[:255],
                description=description, description_text=to_text(description),
                status=status, status_changed_at=_dt(f.get("statuscategorychangedate")) or created,
                priority=self._priority(f.get("priority")), resolution=resolution,
                resolved_at=_dt(f.get("resolutiondate")),
                assignee=assignee, reporter=reporter, labels=_clean_labels(f.get("labels")),
                sprint=sprint, story_points=points,
                original_estimate=_int(f.get("timeoriginalestimate")),
                remaining_estimate=_int(f.get("timeestimate")),
                time_spent=_int(f.get("timespent")) or 0,
                start_date=_date(f.get(fm.start_date)) if fm.start_date else None,
                due_date=_date(f.get("duedate")), rank=rank,
                flagged=bool(fm.flagged and f.get(fm.flagged)),
            )
            if status.category == StatusCategory.DONE and resolution is None:
                issue.resolution = Resolution.objects.filter(is_default=True).first()
                issue.resolved_at = issue.resolved_at or _dt(f.get("updated")) or created
                Issue.objects.filter(pk=issue.pk).update(resolution=issue.resolution,
                                                         resolved_at=issue.resolved_at)
            if closed:
                issue.closed_sprints.set(closed)
            comps = [components[str(x.get("id"))] for x in f.get("components") or []
                     if str(x.get("id")) in components]
            if comps:
                issue.components.set(comps)
            fixv = [versions[str(x.get("id"))] for x in f.get("fixVersions") or []
                    if str(x.get("id")) in versions]
            if fixv:
                issue.fix_versions.set(fixv)
            affv = [versions[str(x.get("id"))] for x in f.get("versions") or []
                    if str(x.get("id")) in versions]
            if affv:
                issue.affects_versions.set(affv)
            watchers = {u for u in (assignee, reporter) if u is not None}
            if watchers:
                issue.watchers.add(*watchers)

            parent_key = (f.get("parent") or {}).get("key") or \
                (f.get(fm.epic_link) if fm.epic_link else None)
            if parent_key:
                parents.append((issue, str(parent_key)))
            for link in f.get("issuelinks") or []:
                self.pending_links.append((issue.id, link))
            for fid in fm.custom:
                v = f.get(fid)
                if v not in (None, "", [], {}):
                    cf_values.setdefault(fid, []).append((issue, v))

            ImportedObject.objects.get_or_create(
                source="jira", site=self.site, kind="issue", external_id=str(ji.get("id")),
                defaults={"object_id": issue.pk, "job": self.job},
            )
            self.issue_by_key[str(ji["key"])] = issue

            stats.comments += self._comments(issue, ji)
            stats.worklogs += self._worklogs(issue, ji)
            if self.opt_history:
                stats.history += self._history(issue, ji, reporter, created)
            if self.opt_attachments:
                stats.attachments += self._attachments(issue, f.get("attachment") or [])
            if self.opt_web_links:
                self._web_links(issue, ji["key"])
            Issue.objects.filter(pk=issue.pk).update(
                created_at=created, updated_at=_dt(f.get("updated")) or created
            )
            stats.issues += 1
            if stats.issues % 25 == 0:
                self._progress(done=stats.issues, total=max(total, stats.issues))

        # ---- parents
        for issue, pkey in parents:
            parent = self.issue_by_key.get(pkey)
            if parent is None or parent.project_id != project.id:
                self._log("warning", f"{issue.key}: principal {pkey} no está en el proyecto")
                continue
            child_level, parent_level = issue.issue_type.level, parent.issue_type.level
            ok = (child_level == IssueType.Level.SUBTASK and parent_level == 0) or \
                (child_level == 0 and parent_level == IssueType.Level.EPIC)
            if not ok:
                self._log("warning", f"{issue.key}: jerarquía con {pkey} no compatible, se omite")
                continue
            upd = {"parent": parent}
            if child_level == IssueType.Level.SUBTASK:
                upd["sprint"] = parent.sprint
            Issue.objects.filter(pk=issue.pk).update(**upd)

        stats.custom_fields = self._custom_fields(project, cf_values)
        stats.sprints = len(sprints)

        # ---- wrap up
        for u in members - {lead, self.actor}:
            ProjectMember.objects.get_or_create(project=project, user=u,
                                                defaults={"role": member_role})
        Project.objects.filter(pk=project.pk).update(issue_counter=max_number)
        ids = list(Issue.objects.filter(project=project).values_list("id", flat=True))
        for i in range(0, len(ids), 500):
            update_search_vector(ids[i:i + 500])
        self._progress(done=stats.issues, total=stats.issues)

    def _create_workflow(self, key: str, statuses: list[Status]) -> Workflow:
        name, n = f"Jira {key}", 1
        while Workflow.objects.filter(name=name).exists():
            n += 1
            name = f"Jira {key} ({n})"
        initial = next((s for s in statuses if s.category == StatusCategory.TODO), statuses[0])
        wf = Workflow.objects.create(name=name, initial_status=initial,
                                     description="Importado desde Jira")
        for st in statuses:
            self._add_status(wf, st)
        return wf

    def _add_status(self, wf: Workflow, st: Status) -> None:
        pos = wf.workflow_statuses.count()
        WorkflowStatus.objects.create(workflow=wf, status=st, position=pos, x=pos * 220, y=0)
        Transition.objects.create(workflow=wf, name=st.name[:80], to_status=st, position=pos)

    # ------------------------------------------------------------------ children
    def _comments(self, issue: Issue, ji: dict) -> int:
        block = (ji.get("fields") or {}).get("comment") or {}
        items = block.get("comments") or []
        if block.get("total", len(items)) > len(items):
            items = self.client.comments(ji["key"])
        objs, times = [], []
        for jc in items:
            doc = self.converter.convert(jc.get("body"))
            if not doc:
                continue
            created = _dt(jc.get("created")) or timezone.now()
            updated = _dt(jc.get("updated")) or created
            objs.append(Comment(issue=issue, author=self._user(jc.get("author")), body=doc,
                                body_text=to_text(doc),
                                edited=abs((updated - created).total_seconds()) > 60))
            times.append((created, updated))
        return self._bulk_with_times(Comment, objs, times)

    def _worklogs(self, issue: Issue, ji: dict) -> int:
        block = (ji.get("fields") or {}).get("worklog") or {}
        items = block.get("worklogs") or []
        if block.get("total", len(items)) > len(items):
            items = self.client.worklogs(ji["key"])
        objs, times = [], []
        for jw in items:
            spent = _int(jw.get("timeSpentSeconds"))
            if not spent:
                continue
            started = _dt(jw.get("started")) or timezone.now()
            objs.append(Worklog(issue=issue, author=self._user(jw.get("author")),
                                time_spent=spent, started_at=started,
                                comment=adf_to_text(jw.get("comment"))[:5000]))
            created = _dt(jw.get("created")) or started
            times.append((created, _dt(jw.get("updated")) or created))
        count = self._bulk_with_times(Worklog, objs, times)
        if count and not issue.time_spent:
            total = sum(o.time_spent for o in objs)
            Issue.objects.filter(pk=issue.pk).update(time_spent=total)
        return count

    def _history(self, issue: Issue, ji: dict, reporter, created) -> int:
        log_block = ji.get("changelog") or {}
        histories = log_block.get("histories") or []
        if log_block.get("total", len(histories)) > len(histories):
            try:
                histories = self.client.changelog(ji["key"])
            except JiraError:
                pass
        rows = [IssueHistory(issue=issue, actor=reporter, items=[{"field": "created"}])]
        times = [created]
        for h in histories:
            items = []
            for it in h.get("items") or []:
                fname = str(it.get("field") or "")
                lower = fname.lower()
                if lower in HISTORY_SKIP:
                    continue
                mapped = HISTORY_FIELDS.get(lower)
                entry = {
                    "field": mapped or f"jira:{lower}", "from": it.get("from"),
                    "to": it.get("to"), "from_display": it.get("fromString"),
                    "to_display": it.get("toString"),
                }
                if mapped is None:
                    entry["field_name"] = fname[:80]
                if mapped == "description":
                    entry["from_display"] = entry["to_display"] = None
                if mapped in ("original_estimate", "remaining_estimate", "time_spent"):
                    entry["from"], entry["to"] = _int(it.get("from")), _int(it.get("to"))
                items.append(entry)
            if items:
                rows.append(IssueHistory(issue=issue, actor=self._user(h.get("author")),
                                         items=items))
                times.append(_dt(h.get("created")) or created)
        IssueHistory.objects.bulk_create(rows)
        for row, t in zip(rows, times, strict=True):
            row.created_at = t
        IssueHistory.objects.bulk_update(rows, ["created_at"])
        return len(rows) - 1

    def _attachments(self, issue: Issue, items: list[dict]) -> int:
        count = 0
        for ja in items:
            name = (ja.get("filename") or "archivo").replace("\\", "/").split("/")[-1][:200]
            size = _int(ja.get("size")) or 0
            url = ja.get("content")
            if not url:
                continue
            if size > self.max_attachment:
                self._log("warning", f"{issue.key}: adjunto {name} omitido (demasiado grande)")
                continue
            try:
                resp = self.client.download(url)
                with tempfile.TemporaryFile() as tmp:
                    written = 0
                    for chunk in resp.iter_content(1 << 20):
                        written += len(chunk)
                        if written > self.max_attachment:
                            raise JiraError("demasiado grande")
                        tmp.write(chunk)
                    tmp.seek(0)
                    att = Attachment(
                        issue=issue, filename=name, size=written,
                        mime_type=(ja.get("mimeType") or "application/octet-stream")[:120],
                        uploaded_by=self._user(ja.get("author")),
                    )
                    att.file.save(name, File(tmp, name=name), save=False)
                    att.save()
                created = _dt(ja.get("created"))
                if created:
                    Attachment.objects.filter(pk=att.pk).update(created_at=created)
                count += 1
            except JiraError as e:
                self._log("warning", f"{issue.key}: no se pudo descargar {name}: {e.message}")
        return count

    def _web_links(self, issue: Issue, key: str) -> None:
        try:
            links = self.client.remote_links(key)
        except JiraError:
            return
        for rl in links or []:
            obj = rl.get("object") or {}
            url = obj.get("url") or ""
            if url.startswith(("http://", "https://")):
                WebLink.objects.create(issue=issue, url=url[:2000],
                                       title=(obj.get("title") or "")[:255])

    @staticmethod
    def _bulk_with_times(model, objs: list, times: list[tuple]) -> int:
        if not objs:
            return 0
        model.objects.bulk_create(objs)
        for obj, (created, updated) in zip(objs, times, strict=True):
            obj.created_at, obj.updated_at = created, updated
        model.objects.bulk_update(objs, ["created_at", "updated_at"])
        return len(objs)

    # ------------------------------------------------------------------ custom fields
    def _custom_fields(self, project: Project, values: dict[str, list[tuple[Issue, Any]]]) -> int:
        fm = self.fields
        created = 0
        for fid, pairs in values.items():
            meta = fm.custom[fid]
            kind = meta["kind"]
            cf = CustomField.objects.filter(name__iexact=meta["name"], kind=kind).first()
            if cf is None:
                cf = CustomField.objects.create(name=meta["name"], kind=kind,
                                                position=CustomField.objects.count())
                cf.projects.add(project)
                created += 1
            elif cf.projects.exists():
                cf.projects.add(project)
            opts = _OptionSet(cf.options)
            opt_id = opts.id_for

            updates: list[Issue] = []
            for issue, raw in pairs:
                v: Any
                if kind == CustomField.Kind.SELECT:
                    v = opt_id(raw)
                elif kind in (CustomField.Kind.MULTISELECT, CustomField.Kind.CHECKBOX):
                    v = [x for x in (opt_id(o) for o in (raw if isinstance(raw, list) else [raw]))
                         if x]
                elif kind == CustomField.Kind.USER:
                    u = self._user(raw if isinstance(raw, dict) else None)
                    v = u.pk if u else None
                elif kind == CustomField.Kind.MULTIUSER:
                    v = [u.pk for u in (self._user(x) for x in raw or []) if u]
                elif kind == CustomField.Kind.NUMBER:
                    try:
                        v = float(raw)
                    except (TypeError, ValueError):
                        v = None
                elif kind == CustomField.Kind.LABELS:
                    v = _clean_labels(raw)
                elif kind == CustomField.Kind.TEXTAREA:
                    v = adf_to_text(raw)[:20000]
                elif kind in (CustomField.Kind.TEXT, CustomField.Kind.URL):
                    v = (raw if isinstance(raw, str) else adf_to_text(raw))[:255]
                elif kind == CustomField.Kind.DATE:
                    d = _date(raw)
                    v = d.isoformat() if d else None
                elif kind == CustomField.Kind.DATETIME:
                    d = _dt(raw)
                    v = d.isoformat() if d else None
                else:
                    v = None
                if v in (None, "", []):
                    continue
                issue.custom_fields = {**issue.custom_fields, str(cf.id): v}
                updates.append(issue)
            if opts.dirty:
                cf.options = opts.as_list()
                cf.save(update_fields=["options", "updated_at"])
            if updates:
                Issue.objects.bulk_update(updates, ["custom_fields"])
        return created

    # ------------------------------------------------------------------ links
    def _issue_from_key(self, key: str | None) -> Issue | None:
        if not key:
            return None
        if key in self.issue_by_key:
            return self.issue_by_key[key]
        return None

    def _create_links(self) -> None:
        types: dict[str, IssueLinkType] = {}
        for source_id, link in self.pending_links:
            jt = link.get("type") or {}
            tname = (jt.get("name") or "Relates").strip()[:60]
            if tname not in types:
                lt = IssueLinkType.objects.filter(name__iexact=tname).first()
                if lt is None:
                    lt = IssueLinkType.objects.create(
                        name=tname, outward=(jt.get("outward") or tname)[:60],
                        inward=(jt.get("inward") or tname)[:60],
                    )
                types[tname] = lt
            lt = types[tname]
            if link.get("outwardIssue"):
                src_id = source_id
                target = self._issue_from_key(link["outwardIssue"].get("key"))
                tgt_id = target.id if target else None
            else:
                other = self._issue_from_key((link.get("inwardIssue") or {}).get("key"))
                src_id, tgt_id = (other.id if other else None), source_id
            if not src_id or not tgt_id or src_id == tgt_id:
                continue
            with transaction.atomic():
                IssueLink.objects.get_or_create(link_type=lt, source_id=src_id,
                                                target_id=tgt_id,
                                                defaults={"created_by": self.actor})


def run_job(job_id: int) -> ImportJob:
    job = ImportJob.objects.select_related("created_by").get(pk=job_id)
    if job.state not in (ImportJob.State.PENDING,):
        return job
    try:
        importer = JiraImporter(job)  # re-validates the Jira URL (it may resolve elsewhere now)
    except JiraError as e:
        log.warning("import %s refused: %s", job.pk, e.message)
        now = timezone.now()
        job.state = ImportJob.State.FAILED
        job.error = e.message
        job.log = [*job.log, {"level": "error", "message": e.message[:1000],
                              "at": now.isoformat()}]
        job.started_at = job.finished_at = now
        job.auth_token = ""  # never keep the credential
        job.save(update_fields=["state", "error", "log", "started_at", "finished_at",
                                "auth_token", "updated_at"])
        return job
    return importer.run()
