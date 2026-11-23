from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class Trigger(models.TextChoices):
    ISSUE_CREATED = "issue_created", "Incidencia creada"
    ISSUE_TRANSITIONED = "issue_transitioned", "Incidencia cambió de estado"
    ISSUE_UPDATED = "issue_updated", "Campo actualizado"
    ISSUE_ASSIGNED = "issue_assigned", "Incidencia asignada"
    COMMENT_ADDED = "comment_added", "Comentario agregado"
    SCHEDULED = "scheduled", "Programada"
    MANUAL = "manual", "Manual (desde la incidencia)"


# Descriptions for the rule editor (exposed by GET /meta → automation.triggers).
TRIGGER_DESCRIPTIONS = {
    Trigger.ISSUE_CREATED: "Cada vez que se crea una incidencia",
    Trigger.ISSUE_TRANSITIONED: "Cuando una incidencia pasa de un estado a otro",
    Trigger.ISSUE_UPDATED: "Cuando se edita alguno de los campos elegidos",
    Trigger.ISSUE_ASSIGNED: "Cuando cambia el responsable",
    Trigger.COMMENT_ADDED: "Cuando alguien comenta",
    Trigger.SCHEDULED: "Cada hora, día o semana sobre las incidencias de un JQL",
    Trigger.MANUAL: "Se ejecuta desde el menú de la incidencia",
}


# Labels for the values the engine accepts. The engine (apps/automation/engine.py) keeps its
# own sets; apps/automation/tests checks that both stay in sync.
class ConditionType(models.TextChoices):
    JQL = "jql", "La incidencia cumple un JQL"
    CHILDREN_DONE = "children_done", "Todas las hijas están listas"


class ActionType(models.TextChoices):
    TRANSITION = "transition", "Cambiar estado"
    ASSIGN = "assign", "Asignar"
    EDIT = "edit", "Editar campos"
    COMMENT = "comment", "Comentar"
    CREATE_SUBTASKS = "create_subtasks", "Crear subtareas"
    NOTIFY = "notify", "Enviar correo"
    ADD_WATCHER = "add_watcher", "Agregar observador"
    WEBHOOK = "webhook", "Llamar webhook"


ADMIN_ONLY_ACTIONS = {ActionType.WEBHOOK}


class AssignTo(models.TextChoices):
    USER = "user", "Una persona"
    REPORTER = "reporter", "El informador"
    TRIGGER_USER = "trigger_user", "Quien disparó la regla"
    LEAD = "lead", "El responsable del proyecto"
    UNASSIGNED = "unassigned", "Sin asignar"


class NotifyTo(models.TextChoices):
    ASSIGNEE = "assignee", "Responsable"
    REPORTER = "reporter", "Informador"
    WATCHERS = "watchers", "Observadores"
    TRIGGER_USER = "trigger_user", "Quien disparó la regla"


class ActionTarget(models.TextChoices):
    ISSUE = "issue", "La incidencia"
    PARENT = "parent", "La incidencia principal"


class ScheduleEvery(models.TextChoices):
    HOUR = "hour", "Cada hora"
    DAY = "day", "Cada día"
    WEEK = "week", "Cada semana"


WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


class WatchedField(models.TextChoices):
    """Fields an `issue_updated` trigger can listen to (history field names)."""

    SUMMARY = "summary", "Resumen"
    DESCRIPTION = "description", "Descripción"
    PRIORITY = "priority", "Prioridad"
    ASSIGNEE = "assignee", "Responsable"
    REPORTER = "reporter", "Informador"
    LABELS = "labels", "Etiquetas"
    SPRINT = "sprint", "Sprint"
    STORY_POINTS = "story_points", "Puntos"
    START_DATE = "start_date", "Inicio"
    DUE_DATE = "due_date", "Vencimiento"
    ISSUE_TYPE = "issue_type", "Tipo"
    PARENT = "parent", "Principal"
    FIX_VERSIONS = "fix_versions", "Versión"
    AFFECTS_VERSIONS = "affects_versions", "Versión afectada"
    COMPONENTS = "components", "Componentes"
    FLAGGED = "flagged", "Impedimento"


class EditActionField(models.TextChoices):
    """Keys accepted by an `edit` action (`fields` dict + label lists)."""

    PRIORITY = "priority", "Prioridad"
    STORY_POINTS = "story_points", "Puntos"
    FLAGGED = "flagged", "Impedimento"
    DUE_IN_DAYS = "due_in_days", "Vencimiento en N días"
    ADD_LABELS = "add_labels", "Agregar etiquetas"
    REMOVE_LABELS = "remove_labels", "Quitar etiquetas"


TEMPLATE_VARIABLES = [
    ("{{issue.key}}", "Clave"),
    ("{{issue.summary}}", "Resumen"),
    ("{{issue.status}}", "Estado"),
    ("{{issue.priority}}", "Prioridad"),
    ("{{issue.type}}", "Tipo"),
    ("{{issue.assignee}}", "Responsable"),
    ("{{issue.reporter}}", "Informador"),
    ("{{issue.project}}", "Proyecto"),
    ("{{issue.project.key}}", "Clave del proyecto"),
    ("{{issue.due_date}}", "Vencimiento"),
    ("{{issue.url}}", "Enlace"),
    ("{{trigger.user}}", "Quien disparó la regla"),
    ("{{now}}", "Fecha y hora actual"),
]


class AutomationRule(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    # null = global rule (applies to every project), only system admins manage those
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE,
        related_name="automation_rules",
    )
    enabled = models.BooleanField(default=True)
    trigger = models.CharField(max_length=24, choices=Trigger.choices)
    # issue_transitioned: {"from_status_ids": [], "to_status_ids": []}
    # issue_updated: {"fields": ["priority", ...]}
    # scheduled: {"every": "hour|day|week", "time": "09:00", "weekday": 0, "jql": "..."}
    trigger_config = models.JSONField(default=dict, blank=True)
    # [{"type": "jql", "jql": "..."}, {"type": "children_done"}, ...]
    conditions = models.JSONField(default=list, blank=True)
    # [{"type": "transition", "status_id": 3}, {"type": "comment", "body": "..."}, ...]
    actions = models.JSONField(default=list)
    allow_rule_triggers = models.BooleanField(
        default=False, help_text="Permitir que cambios hechos por otras reglas disparen esta regla"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    run_count = models.PositiveIntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "regla de automatización"
        verbose_name_plural = "reglas de automatización"
        indexes = [models.Index(fields=["trigger", "enabled"])]

    def __str__(self) -> str:
        return self.name


class AutomationLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Correcto"
        FAILURE = "failure", "Error"
        NO_MATCH = "no_match", "Sin coincidencias"

    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="logs")
    issue = models.ForeignKey(
        "issues.Issue", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issue_key = models.CharField(max_length=24, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    message = models.TextField(blank=True)
    actions_done = models.JSONField(default=list, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
