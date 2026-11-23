import uuid

from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class IssueForm(SoftDeleteModel, TimeStampedModel):
    """A request form that creates an issue in a project (like Jira forms / intake)."""

    class Access(models.TextChoices):
        MEMBERS = "members", "Quienes pueden crear incidencias en el proyecto"
        ORGANIZATION = "organization", "Cualquier persona de la organización"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                                related_name="forms")
    slug = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    issue_type = models.ForeignKey("issues.IssueType", on_delete=models.PROTECT, related_name="+")
    # [{"field": "summary|description|priority|due_date|labels|components|cf:<id>",
    #   "label": "...", "required": bool, "help": "..."}]
    fields = models.JSONField(default=list)
    default_labels = models.JSONField(default=list, blank=True)
    access = models.CharField(max_length=14, choices=Access.choices, default=Access.ORGANIZATION)
    is_active = models.BooleanField(default=True)
    success_message = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                   on_delete=models.SET_NULL, related_name="+")
    submission_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "formulario"
        verbose_name_plural = "formularios"

    def __str__(self) -> str:
        return self.name
