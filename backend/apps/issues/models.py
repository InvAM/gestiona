import os

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.core.models import ALIVE, SoftDeleteModel, TimeStampedModel


class IssueType(SoftDeleteModel, TimeStampedModel):
    class Level(models.IntegerChoices):
        SUBTASK = -1, "Subtarea"
        STANDARD = 0, "Estándar"
        EPIC = 1, "Épica"

    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=40, default="task")
    color = models.CharField(max_length=9, default="#4BADE8")
    level = models.SmallIntegerField(choices=Level.choices, default=Level.STANDARD)
    position = models.PositiveIntegerField(default=0)
    templates = ArrayField(
        models.CharField(max_length=20), default=list, blank=True,
        help_text="Plantillas de proyecto (scrum, kanban, business) que incluyen este tipo",
    )
    has_affects_versions = models.BooleanField(
        default=False, help_text="Muestra el campo «Versión afectada» (típico de errores)"
    )

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "tipo de incidencia"
        verbose_name_plural = "tipos de incidencia"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="issue_type_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class Priority(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=40)
    icon = models.CharField(max_length=40, default="medium")
    color = models.CharField(max_length=9, default="#FFAB00")
    position = models.PositiveIntegerField(default=0, help_text="0 = más alta")
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["position"]
        verbose_name = "prioridad"
        verbose_name_plural = "prioridades"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="priority_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class Resolution(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        verbose_name = "resolución"
        verbose_name_plural = "resoluciones"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="resolution_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class CustomField(SoftDeleteModel, TimeStampedModel):
    class Kind(models.TextChoices):
        TEXT = "text", "Texto corto"
        TEXTAREA = "textarea", "Párrafo"
        NUMBER = "number", "Número"
        DATE = "date", "Fecha"
        DATETIME = "datetime", "Fecha y hora"
        SELECT = "select", "Lista desplegable"
        MULTISELECT = "multiselect", "Selección múltiple"
        CHECKBOX = "checkbox", "Casillas"
        USER = "user", "Usuario"
        MULTIUSER = "multiuser", "Varios usuarios"
        URL = "url", "URL"
        LABELS = "labels", "Etiquetas"

    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    # Removed options are kept with "deleted": true so issues that use them still render.
    options = models.JSONField(
        default=list, blank=True, help_text='[{"id": "a", "value": "A", "deleted": false}]'
    )
    projects = models.ManyToManyField(
        "projects.Project", blank=True, related_name="custom_fields",
        help_text="Vacío = disponible en todos los proyectos",
    )
    issue_types = models.ManyToManyField(IssueType, blank=True, related_name="+")
    # «Obligatorio» lives in the field configurations (FieldConfigurationItem); the
    # /custom-fields API maps its `required` to the default configuration.
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "campo personalizado"
        verbose_name_plural = "campos personalizados"

    def active_options(self) -> list[dict]:
        return [o for o in self.options or [] if not o.get("deleted")]

    def __str__(self) -> str:
        return self.name


class Issue(TimeStampedModel):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="issues")
    number = models.PositiveIntegerField()
    key = models.CharField(max_length=24, unique=True, editable=False)
    issue_type = models.ForeignKey(IssueType, on_delete=models.PROTECT, related_name="issues")
    summary = models.CharField(max_length=255)
    description = models.JSONField(null=True, blank=True, help_text="Documento ProseMirror")
    description_text = models.TextField(blank=True, editable=False)
    status = models.ForeignKey("workflows.Status", on_delete=models.PROTECT, related_name="issues")
    status_changed_at = models.DateTimeField(null=True, blank=True)
    priority = models.ForeignKey(Priority, on_delete=models.PROTECT, related_name="issues")
    resolution = models.ForeignKey(
        Resolution, null=True, blank=True, on_delete=models.PROTECT, related_name="issues"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_issues",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="reported_issues",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    labels = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    components = models.ManyToManyField("projects.Component", blank=True, related_name="issues")
    fix_versions = models.ManyToManyField(
        "projects.Version", blank=True, related_name="fix_issues"
    )
    affects_versions = models.ManyToManyField(
        "projects.Version", blank=True, related_name="affected_issues"
    )
    sprint = models.ForeignKey(
        "boards.Sprint", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues"
    )
    closed_sprints = models.ManyToManyField("boards.Sprint", blank=True, related_name="+")
    team = models.ForeignKey(
        "plans.Team", null=True, blank=True, on_delete=models.PROTECT, related_name="issues"
    )
    story_points = models.DecimalField(max_digits=6, decimal_places=1, null=True, blank=True)
    original_estimate = models.PositiveIntegerField(null=True, blank=True, help_text="segundos")
    remaining_estimate = models.PositiveIntegerField(null=True, blank=True, help_text="segundos")
    time_spent = models.PositiveIntegerField(default=0, help_text="segundos")
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    rank = models.CharField(max_length=128, db_collation="C", db_index=True)
    custom_fields = models.JSONField(default=dict, blank=True)
    flagged = models.BooleanField(default=False)
    watchers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="watched_issues"
    )
    voters = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    search_vector = SearchVectorField(null=True, editable=False)
    # Archived issues are read-only and hidden from boards, backlog and search.
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["rank"]
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="unique_issue_number")
        ]
        indexes = [
            GinIndex(fields=["search_vector"], name="issue_search_gin"),
            GinIndex(fields=["labels"], name="issue_labels_gin"),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["sprint", "rank"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.key} {self.summary}"


class IssueLinkType(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=60)
    outward = models.CharField(max_length=60)  # "bloquea"
    inward = models.CharField(max_length=60)  # "está bloqueada por"
    # Planning dependency: the source (outward) must finish before the target starts.
    # Plans draw these links as arrows and flag date conflicts.
    is_dependency = models.BooleanField(
        default=False, help_text="Dependencia en planes: el origen debe terminar antes"
    )
    # Link created between a clone (source) and its original (target) when cloning.
    is_clone = models.BooleanField(
        default=False, help_text="Vínculo que se crea al clonar una incidencia"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "tipo de vínculo"
        verbose_name_plural = "tipos de vínculo"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="link_type_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class IssueLink(TimeStampedModel):
    link_type = models.ForeignKey(IssueLinkType, on_delete=models.PROTECT, related_name="links")
    source = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="outward_links")
    target = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="inward_links")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "vínculo"
        verbose_name_plural = "vínculos"
        constraints = [
            models.UniqueConstraint(
                fields=["link_type", "source", "target"], name="unique_issue_link"
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")), name="issue_link_not_self"
            ),
        ]


class WebLink(TimeStampedModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="web_links")
    url = models.URLField(max_length=2000)
    title = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )


class Comment(TimeStampedModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="comments"
    )
    body = models.JSONField(help_text="Documento ProseMirror")
    body_text = models.TextField(blank=True)
    edited = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]


def attachment_path(instance, filename):
    return f"attachments/{instance.issue.project.key}/{instance.issue.key}/{filename}"


class Attachment(TimeStampedModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, max_length=500)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    mime_type = models.CharField(max_length=120)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def extension(self) -> str:
        return os.path.splitext(self.filename)[1].lower().lstrip(".")


class Worklog(TimeStampedModel):
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="worklogs")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="worklogs"
    )
    time_spent = models.PositiveIntegerField(help_text="segundos")
    started_at = models.DateTimeField()
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


# UI labels of the `field` keys stored in IssueHistory.items (GET /meta → issue_fields).
# Custom fields are stored as "cf:<id>" with their own `field_name`.
HISTORY_FIELD_LABELS = {
    "summary": "Resumen", "description": "Descripción", "status": "Estado",
    "priority": "Prioridad", "assignee": "Responsable", "reporter": "Informador",
    "issue_type": "Tipo", "parent": "Principal", "sprint": "Sprint", "labels": "Etiquetas",
    "story_points": "Puntos de historia", "resolution": "Resolución",
    "components": "Componentes", "fix_versions": "Versión de corrección",
    "affects_versions": "Versión afectada", "due_date": "Fecha de vencimiento",
    "start_date": "Fecha de inicio", "original_estimate": "Estimación original",
    "remaining_estimate": "Estimación restante", "time_spent": "Tiempo registrado",
    "flagged": "Marcada", "attachment": "Adjunto", "link": "Vínculo", "project": "Proyecto",
    "key": "Clave", "archived": "Archivada", "created": "Creada", "team": "Equipo",
}


class IssueHistory(models.Model):
    """One change event (may contain several field changes)."""

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # [{"field": "status", "from": 1, "from_display": "Por hacer", "to": 2, "to_display": "..."}]
    items = models.JSONField(default=list)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "issue history"


class IssueKeyAlias(models.Model):
    """Previous key of an issue that was moved to another project (old links keep working)."""

    key = models.CharField(max_length=24, unique=True)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="key_aliases")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.key} → {self.issue.key}"


# --------------------------------------------------------------------------- field rules
# Jira (company-managed) model. Field keys are the IssuePatch names ("summary", "assignee"…)
# or "cf:<id>" for custom fields; the catalog and the resolution live in
# apps/issues/fieldrules.py.

def _one_default(name: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(fields=["is_default"],
                                   condition=models.Q(is_default=True, deleted_at__isnull=True),
                                   name=name)


class FieldConfiguration(SoftDeleteModel, TimeStampedModel):
    """Per field: required, hidden and help text. Fields without an item are optional,
    visible and have no description (so new custom fields need no rows)."""

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(
        default=False,
        help_text="Configuración predeterminada (el «obligatorio» de los campos personalizados)",
    )

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "configuración de campos"
        verbose_name_plural = "configuraciones de campos"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="field_configuration_name_alive_uniq"),
            _one_default("field_configuration_one_default"),
        ]

    def __str__(self) -> str:
        return self.name


class FieldConfigurationItem(models.Model):
    configuration = models.ForeignKey(FieldConfiguration, on_delete=models.CASCADE,
                                      related_name="items")
    field = models.CharField(max_length=40)
    custom_field = models.ForeignKey(CustomField, null=True, blank=True,
                                     on_delete=models.CASCADE, related_name="+")
    required = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "campo de la configuración"
        verbose_name_plural = "campos de la configuración"
        constraints = [
            models.UniqueConstraint(fields=["configuration", "field"],
                                    name="unique_field_configuration_item"),
        ]


class FieldConfigurationScheme(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False,
                                     help_text="Se asigna a los proyectos nuevos")
    default_configuration = models.ForeignKey(FieldConfiguration, on_delete=models.PROTECT,
                                              related_name="default_in_schemes")

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "esquema de configuración de campos"
        verbose_name_plural = "esquemas de configuración de campos"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="field_configuration_scheme_name_alive_uniq"),
            _one_default("field_configuration_scheme_one_default"),
        ]

    def __str__(self) -> str:
        return self.name


class FieldConfigurationSchemeEntry(models.Model):
    scheme = models.ForeignKey(FieldConfigurationScheme, on_delete=models.CASCADE,
                               related_name="entries")
    issue_type = models.ForeignKey(IssueType, on_delete=models.PROTECT, related_name="+")
    configuration = models.ForeignKey(FieldConfiguration, on_delete=models.PROTECT,
                                      related_name="scheme_entries")

    class Meta:
        verbose_name = "configuración de un tipo"
        verbose_name_plural = "configuraciones de cada tipo"
        constraints = [
            models.UniqueConstraint(fields=["scheme", "issue_type"],
                                    name="unique_field_configuration_scheme_entry"),
        ]


class Screen(SoftDeleteModel, TimeStampedModel):
    """Ordered list of fields, split in tabs (always at least one)."""

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(
        default=False, help_text="Los campos personalizados nuevos se añaden a esta pantalla"
    )

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "pantalla"
        verbose_name_plural = "pantallas"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="screen_name_alive_uniq"),
            _one_default("screen_one_default"),
        ]

    def __str__(self) -> str:
        return self.name


class ScreenTab(models.Model):
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name="tabs")
    name = models.CharField(max_length=80)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "pestaña"
        verbose_name_plural = "pestañas"


class ScreenField(models.Model):
    screen = models.ForeignKey(Screen, on_delete=models.CASCADE, related_name="screen_fields")
    tab = models.ForeignKey(ScreenTab, on_delete=models.CASCADE, related_name="screen_fields")
    field = models.CharField(max_length=40)
    custom_field = models.ForeignKey(CustomField, null=True, blank=True,
                                     on_delete=models.CASCADE, related_name="+")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "campo de pantalla"
        verbose_name_plural = "campos de pantalla"
        constraints = [
            models.UniqueConstraint(fields=["screen", "field"], name="unique_screen_field"),
        ]


class ScreenScheme(SoftDeleteModel, TimeStampedModel):
    """Which screen each operation uses; an empty operation uses `default_screen`."""

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False)
    default_screen = models.ForeignKey(Screen, on_delete=models.PROTECT, related_name="+")
    create_screen = models.ForeignKey(Screen, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    edit_screen = models.ForeignKey(Screen, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    view_screen = models.ForeignKey(Screen, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "esquema de pantallas"
        verbose_name_plural = "esquemas de pantallas"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="screen_scheme_name_alive_uniq"),
            _one_default("screen_scheme_one_default"),
        ]

    def __str__(self) -> str:
        return self.name


class IssueTypeScreenScheme(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=255, blank=True)
    is_default = models.BooleanField(default=False,
                                     help_text="Se asigna a los proyectos nuevos")
    default_screen_scheme = models.ForeignKey(ScreenScheme, on_delete=models.PROTECT,
                                              related_name="default_in_type_schemes")

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "esquema de pantallas por tipo"
        verbose_name_plural = "esquemas de pantallas por tipo"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="issue_type_screen_scheme_name_alive_uniq"),
            _one_default("issue_type_screen_scheme_one_default"),
        ]

    def __str__(self) -> str:
        return self.name


class IssueTypeScreenSchemeEntry(models.Model):
    scheme = models.ForeignKey(IssueTypeScreenScheme, on_delete=models.CASCADE,
                               related_name="entries")
    issue_type = models.ForeignKey(IssueType, on_delete=models.PROTECT, related_name="+")
    screen_scheme = models.ForeignKey(ScreenScheme, on_delete=models.PROTECT,
                                      related_name="type_entries")

    class Meta:
        verbose_name = "esquema de pantallas de un tipo"
        verbose_name_plural = "esquemas de pantallas de cada tipo"
        constraints = [
            models.UniqueConstraint(fields=["scheme", "issue_type"],
                                    name="unique_issue_type_screen_scheme_entry"),
        ]
