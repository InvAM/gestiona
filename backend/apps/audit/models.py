from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    class Category(models.TextChoices):
        AUTH = "auth", "Acceso"
        USERS = "users", "Usuarios"
        PROJECTS = "projects", "Proyectos"
        MEMBERS = "members", "Miembros"
        CONFIG = "config", "Configuración"
        WORKFLOW = "workflow", "Flujos"
        BOARDS = "boards", "Tableros"
        AUTOMATION = "automation", "Automatización"
        IMPORTS = "imports", "Importaciones"
        ISSUES = "issues", "Incidencias"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    actor_email = models.CharField(max_length=254, blank=True)
    category = models.CharField(max_length=12, choices=Category.choices, db_index=True)
    action = models.CharField(max_length=120)
    method = models.CharField(max_length=8, blank=True)
    path = models.CharField(max_length=300, blank=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    project_key = models.CharField(max_length=10, blank=True, db_index=True)
    object_repr = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_email} {self.action}"
