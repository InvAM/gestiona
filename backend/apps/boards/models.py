from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class Board(SoftDeleteModel, TimeStampedModel):
    """A project's board. Soft-deletable: ``Board.objects`` / ``project.boards`` hide the
    papelera, ``Board.all_objects`` includes it.

    What belongs to the board (columns, quick filters, sprints) is NOT touched by a soft
    delete, so a restore brings it all back. FKs towards Board:

    * ``BoardColumn.board`` / ``QuickFilter.board`` → CASCADE: part of the board.
    * ``Sprint.board`` → CASCADE at the ORM level (a project hard delete must still work),
      but ``DELETE /boards/{id}?permanent=true`` answers 409 while any sprint holds issues
      (current or closed-sprint history); only empty sprints are purged with the board.
    * ``plans.PlanTeam.board`` → SET_NULL: the team falls back to fixed iterations.
    """

    class Kind(models.TextChoices):
        SCRUM = "scrum", "Scrum"
        KANBAN = "kanban", "Kanban"

    class Swimlanes(models.TextChoices):
        NONE = "none", "Ninguno"
        ASSIGNEE = "assignee", "Responsable"
        EPIC = "epic", "Épica"
        PRIORITY = "priority", "Prioridad"
        STORIES = "stories", "Historias (subtareas)"

    class Estimation(models.TextChoices):
        STORY_POINTS = "story_points", "Puntos de historia"
        ORIGINAL_ESTIMATE = "original_estimate", "Estimación original"
        ISSUE_COUNT = "issue_count", "Cantidad de incidencias"

    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SCRUM)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="boards")
    filter_jql = models.TextField(blank=True, help_text="Filtro adicional (JQL) del tablero")
    swimlanes = models.CharField(max_length=10, choices=Swimlanes.choices, default=Swimlanes.NONE)
    estimation = models.CharField(
        max_length=20, choices=Estimation.choices, default=Estimation.STORY_POINTS
    )
    # Kanban: show issues in backlog column instead of board (kanban backlog)
    kanban_backlog = models.BooleanField(default=False)
    # Kanban: hide done issues older than N days (0 = never hide)
    hide_done_after_days = models.PositiveIntegerField(default=14)
    card_fields = models.JSONField(default=list, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "tablero"
        verbose_name_plural = "tableros"

    def __str__(self) -> str:
        return self.name


class BoardColumn(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="columns")
    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)
    statuses = models.ManyToManyField("workflows.Status", blank=True, related_name="+")
    min_issues = models.PositiveIntegerField(null=True, blank=True)
    max_issues = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]


class QuickFilterManager(models.Manager):
    """Quick filters of boards in the papelera are hidden everywhere (list view, JQL
    helpers…) without each caller having to remember it."""

    def get_queryset(self):
        return super().get_queryset().filter(board__deleted_at__isnull=True)


class AllQuickFiltersManager(models.Manager):
    """Every quick filter, including those of boards in the papelera."""


class QuickFilter(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="quick_filters")
    name = models.CharField(max_length=60)
    jql = models.TextField()
    description = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)

    objects = QuickFilterManager()
    all_objects = AllQuickFiltersManager()

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "filtro rápido"
        verbose_name_plural = "filtros rápidos"


class Sprint(TimeStampedModel):
    class State(models.TextChoices):
        FUTURE = "future", "Futuro"
        ACTIVE = "active", "Activo"
        CLOSED = "closed", "Cerrado"

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="sprints")
    name = models.CharField(max_length=80)
    goal = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.FUTURE)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    # snapshot taken at start / close (for reports)
    start_snapshot = models.JSONField(default=dict, blank=True)
    close_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "sprint"
        verbose_name_plural = "sprints"

    def __str__(self) -> str:
        return self.name


class SprintScopeChange(models.Model):
    """Issue added/removed/estimated during an active sprint (burndown data)."""

    class Kind(models.TextChoices):
        ADDED = "added", "Agregada"
        REMOVED = "removed", "Quitada"
        ESTIMATE = "estimate", "Estimación cambiada"
        COMPLETED = "completed", "Completada"
        REOPENED = "reopened", "Reabierta"

    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, related_name="scope_changes")
    issue = models.ForeignKey("issues.Issue", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    value_before = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    value_after = models.DecimalField(max_digits=10, decimal_places=1, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
