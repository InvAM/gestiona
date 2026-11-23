from ninja import Router, Schema

from apps.core.errors import NotFound, ValidationFailed
from apps.projects.models import Perm, Project
from apps.projects.permissions import has_perm, require

from . import service

router = Router(tags=["ai"])


class AiStatusOut(Schema):
    enabled: bool
    model: str | None


class SummaryOut(Schema):
    summary: str
    key_points: list[str]
    open_questions: list[str]
    next_steps: list[str]


class DraftIn(Schema):
    project: str
    issue_type_id: int
    summary: str
    notes: str = ""


class DraftOut(Schema):
    description: str
    acceptance_criteria: list[str]
    subtasks: list[str]


class JqlIn(Schema):
    question: str
    project: str | None = None


class JqlOut(Schema):
    jql: str
    explanation: str


@router.get("/ai/status", response=AiStatusOut)
def ai_status(request):
    from django.conf import settings

    on = service.enabled()
    return {"enabled": on, "model": settings.AI_MODEL if on else None}


@router.post("/ai/issues/{key}/summary", response=SummaryOut)
def ai_summary(request, key: str):
    from apps.issues.services import get_issue_or_404

    issue = get_issue_or_404(request.user, key)
    return service.summarize_issue(request.user, issue)


@router.post("/ai/draft", response=DraftOut)
def ai_draft(request, data: DraftIn):
    project = Project.objects.filter(key=data.project.upper()).first()
    if project is None or not has_perm(request.user, project, Perm.BROWSE):
        raise NotFound("Proyecto no encontrado")
    require(request.user, project, Perm.CREATE_ISSUES)
    itype = project.issue_types.filter(pk=data.issue_type_id).first()
    if itype is None:
        raise ValidationFailed("Tipo de incidencia inválido", code="issue_type")
    if len(data.summary.strip()) < 4:
        raise ValidationFailed("Escribe primero un resumen", code="summary")
    return service.draft_issue(request.user, project, itype, data.summary, data.notes)


@router.post("/ai/jql", response=JqlOut)
def ai_jql(request, data: JqlIn):
    if len(data.question.strip()) < 3:
        raise ValidationFailed("Escribe una pregunta", code="question")
    return service.question_to_jql(request.user, data.question, data.project)
