from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.errors import Forbidden, ValidationFailed
from apps.core.schemas import UserRef, user_ref
from apps.projects.models import Project, project_key_validator

from .jira_client import JiraClient, JiraError, normalize_base_url
from .models import ImportJob

router = Router(tags=["imports"])


def _require_admin(user):
    if not (user.is_staff or user.is_superuser):
        raise Forbidden("Solo los administradores pueden importar datos")


class JiraCredentialsIn(Schema):
    base_url: str
    email: str = ""
    token: str


class JiraProjectOut(Schema):
    key: str
    name: str
    type: str | None = None
    exists: bool


class JiraPreviewOut(Schema):
    account: str
    deployment: str
    projects: list[JiraProjectOut]


class ImportProjectIn(Schema):
    key: str
    target_key: str | None = None
    target_name: str | None = None
    access: str = Project.Access.LIMITED


class ImportOptionsIn(Schema):
    attachments: bool = True
    history: bool = True
    create_users: bool = True
    web_links: bool = False
    max_attachment_mb: int = 200


class JiraImportIn(JiraCredentialsIn):
    projects: list[ImportProjectIn]
    options: ImportOptionsIn = ImportOptionsIn()


class ImportJobOut(Schema):
    id: int
    source: str
    state: str
    state_display: str
    base_url: str
    created_by: UserRef | None
    projects: list[dict]
    options: dict
    progress: dict
    log: list[dict]
    result: list[dict]
    error: str
    created_at: str
    started_at: str | None
    finished_at: str | None


def _out(job: ImportJob) -> dict:
    return {
        "id": job.id, "source": job.source, "state": job.state,
        "state_display": job.get_state_display(), "base_url": job.base_url,
        "created_by": user_ref(job.created_by), "projects": job.projects,
        "options": job.options, "progress": job.progress, "log": job.log,
        "result": job.result, "error": job.error, "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _client(data: JiraCredentialsIn) -> JiraClient:
    if not data.token.strip():
        raise ValidationFailed("El token es obligatorio", code="token")
    try:
        return JiraClient(data.base_url, data.email.strip(), data.token.strip())
    except JiraError as e:
        raise ValidationFailed(e.message, code="base_url") from e


@router.post("/imports/jira/preview", response=JiraPreviewOut)
def jira_preview(request, data: JiraCredentialsIn):
    """Check the credentials and list the Jira projects the account can see."""
    _require_admin(request.user)
    client = _client(data)
    try:
        me = client.myself()
        projects = client.projects()
    except JiraError as e:
        raise ValidationFailed(e.message, code="jira") from e
    existing = set(Project.objects.values_list("key", flat=True))
    return {
        "account": me.get("displayName") or me.get("name") or "",
        "deployment": "cloud" if client.is_cloud else "server",
        "projects": [
            {"key": p.get("key"), "name": p.get("name") or p.get("key"),
             "type": p.get("projectTypeKey"), "exists": p.get("key") in existing}
            for p in projects if p.get("key")
        ],
    }


@router.post("/imports/jira", response={201: ImportJobOut})
def jira_import(request, data: JiraImportIn):
    _require_admin(request.user)
    if not data.projects:
        raise ValidationFailed("Elige al menos un proyecto", code="projects")
    try:
        base_url = normalize_base_url(data.base_url)
    except JiraError as e:
        raise ValidationFailed(e.message, code="base_url") from e
    if not data.token.strip():
        raise ValidationFailed("El token es obligatorio", code="token")
    seen: set[str] = set()
    specs = []
    for p in data.projects:
        target = (p.target_key or p.key).strip().upper()
        try:
            project_key_validator(target)
        except DjangoValidationError as e:
            raise ValidationFailed(f"{target}: {e.messages[0]}", code="target_key") from e
        if target in seen:
            raise ValidationFailed(f"La clave {target} está repetida", code="target_key")
        if Project.objects.filter(key=target).exists():
            raise ValidationFailed(f"Ya existe un proyecto con la clave {target}",
                                   code="target_key")
        if p.access not in Project.Access.values:
            raise ValidationFailed("Acceso inválido", code="access")
        seen.add(target)
        specs.append({"key": p.key.strip(), "target_key": target,
                      "target_name": (p.target_name or "").strip() or None, "access": p.access})
    opts = data.options.dict()
    opts["max_attachment_mb"] = max(1, min(int(opts["max_attachment_mb"]), 2048))
    job = ImportJob.objects.create(
        created_by=request.user, base_url=base_url, auth_email=data.email.strip(),
        auth_token=data.token.strip(), projects=specs, options=opts,
        progress={"stage": "queued"},
    )
    from .tasks import run_import

    transaction.on_commit(lambda: run_import.delay(job.id))
    return 201, _out(job)


@router.get("/imports", response=list[ImportJobOut])
def list_imports(request):
    _require_admin(request.user)
    return [_out(j) for j in ImportJob.objects.select_related("created_by")[:50]]


@router.get("/imports/{job_id}", response=ImportJobOut)
def get_import(request, job_id: int):
    _require_admin(request.user)
    return _out(get_object_or_404(ImportJob.objects.select_related("created_by"), pk=job_id))
