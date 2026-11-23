from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ImportJob(TimeStampedModel):
    class Source(models.TextChoices):
        JIRA = "jira", "Jira"

    class State(models.TextChoices):
        PENDING = "pending", "En cola"
        RUNNING = "running", "Importando"
        DONE = "done", "Completado"
        PARTIAL = "partial", "Completado con errores"
        FAILED = "failed", "Fallido"

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.JIRA)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    base_url = models.URLField(max_length=500)
    auth_email = models.CharField(max_length=254, blank=True)
    # Credential is kept only while the job runs and wiped when it finishes.
    auth_token = models.TextField(blank=True)
    # [{"key": "ABC", "target_key": "ABC", "target_name": "..."}]
    projects = models.JSONField(default=list)
    options = models.JSONField(default=dict, blank=True)
    # {"stage": "...", "project": "ABC", "done": 10, "total": 120}
    progress = models.JSONField(default=dict, blank=True)
    # [{"level": "info|warning|error", "message": "...", "at": iso}]
    log = models.JSONField(default=list, blank=True)
    # [{"key": "ABC", "project_id": 1, "issues": 120, "comments": 30, ...}]
    result = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Importación {self.source} #{self.pk} ({self.state})"


class ImportedObject(models.Model):
    """Maps an external id to the Gestiona object created for it (users, issues...).
    Lets later imports reuse placeholder users and link across projects."""

    source = models.CharField(max_length=10, default="jira")
    site = models.CharField(max_length=255, help_text="Host de origen")
    kind = models.CharField(max_length=20)  # user | issue
    external_id = models.CharField(max_length=128)
    object_id = models.BigIntegerField()
    job = models.ForeignKey(ImportJob, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "site", "kind", "external_id"], name="unique_imported_object"
            )
        ]
        indexes = [models.Index(fields=["kind", "object_id"])]
