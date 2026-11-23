from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class SavedFilter(SoftDeleteModel, TimeStampedModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Privado"
        PROJECT = "project", "Miembros del proyecto"
        PUBLIC = "public", "Toda la organización"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    jql = models.TextField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="filters"
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    project = models.ForeignKey(
        "projects.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    columns = models.JSONField(default=list, blank=True)
    starred_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="starred_filters"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "filtro guardado"
        verbose_name_plural = "filtros guardados"

    def __str__(self) -> str:
        return self.name


class RecentItem(models.Model):
    """Recently viewed issues/projects/boards/filters for 'Recientes' menus."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10)  # issue | project | board | filter
    object_id = models.PositiveBigIntegerField()
    viewed_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-viewed_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "object_id"], name="unique_recent")
        ]
