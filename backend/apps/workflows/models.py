from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import ALIVE, SoftDeleteModel, TimeStampedModel


class StatusCategory(models.TextChoices):
    TODO = "todo", "Por hacer"
    IN_PROGRESS = "in_progress", "En curso"
    DONE = "done", "Listo"


class Status(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    category = models.CharField(
        max_length=12, choices=StatusCategory.choices, default=StatusCategory.TODO
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "estado"
        verbose_name_plural = "estados"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="status_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class Workflow(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    initial_status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+")
    statuses = models.ManyToManyField(Status, through="WorkflowStatus", related_name="workflows")
    templates = ArrayField(
        models.CharField(max_length=20), default=list, blank=True,
        help_text="Plantillas de proyecto (scrum, kanban, business) que usan este flujo",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "flujo de trabajo"
        verbose_name_plural = "flujos de trabajo"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="workflow_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name

    def ordered_statuses(self):
        return [ws.status for ws in self.workflow_statuses.select_related("status").all()]


class WorkflowStatus(models.Model):
    workflow = models.ForeignKey(
        Workflow, on_delete=models.CASCADE, related_name="workflow_statuses"
    )
    status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+")
    position = models.PositiveIntegerField(default=0)
    # coordinates for the workflow diagram editor
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "estado de flujo"
        verbose_name_plural = "estados de flujo"
        constraints = [
            models.UniqueConstraint(fields=["workflow", "status"], name="unique_workflow_status")
        ]


class Transition(TimeStampedModel):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="transitions")
    name = models.CharField(max_length=80)
    to_status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+")
    # empty from_statuses => global transition (allowed from any status)
    from_statuses = models.ManyToManyField(Status, blank=True, related_name="+")
    position = models.PositiveIntegerField(default=0)
    # conditions
    only_assignee = models.BooleanField(default=False)
    required_roles = models.ManyToManyField("projects.Role", blank=True, related_name="+")
    # validators / screen
    require_resolution = models.BooleanField(default=False)
    require_comment = models.BooleanField(default=False)
    # Transition screen (fields asked while transitioning) and the «campos obligatorios»
    # validator: field keys (IssuePatch names or "cf:<id>") that must have a value.
    screen = models.ForeignKey(
        "issues.Screen", null=True, blank=True, on_delete=models.PROTECT,
        related_name="transitions",
    )
    required_fields = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    # post functions
    set_resolution = models.ForeignKey(
        "issues.Resolution", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    clear_resolution = models.BooleanField(default=False)
    assign_to_current_user = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "transición"
        verbose_name_plural = "transiciones"

    def __str__(self) -> str:
        return f"{self.workflow}: {self.name} → {self.to_status}"

    @property
    def is_global(self) -> bool:
        return not self.from_statuses.exists()


class WorkflowMapping(models.Model):
    """Optional per-issue-type workflow override inside a project."""

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="workflow_mappings"
    )
    issue_type = models.ForeignKey("issues.IssueType", on_delete=models.PROTECT, related_name="+")
    workflow = models.ForeignKey(Workflow, on_delete=models.PROTECT, related_name="mappings")

    class Meta:
        verbose_name = "flujo por tipo"
        verbose_name_plural = "flujos por tipo"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "issue_type"], name="unique_workflow_mapping"
            )
        ]
