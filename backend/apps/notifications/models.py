from django.conf import settings
from django.db import models


class Event(models.TextChoices):
    ISSUE_CREATED = "issue_created", "Incidencia creada"
    ISSUE_ASSIGNED = "issue_assigned", "Incidencia asignada"
    ISSUE_UPDATED = "issue_updated", "Incidencia actualizada"
    ISSUE_TRANSITIONED = "issue_transitioned", "Cambio de estado"
    COMMENT_ADDED = "comment_added", "Nuevo comentario"
    MENTIONED = "mentioned", "Mención"
    ISSUE_DELETED = "issue_deleted", "Incidencia eliminada"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    event = models.CharField(max_length=24, choices=Event.choices)
    issue = models.ForeignKey(
        "issues.Issue", null=True, on_delete=models.CASCADE, related_name="+"
    )
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "read_at"])]


class NotificationPreference(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs"
    )
    event = models.CharField(max_length=24, choices=Event.choices)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="unique_notification_pref")
        ]
