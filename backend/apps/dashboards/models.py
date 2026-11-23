from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class Dashboard(SoftDeleteModel, TimeStampedModel):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Privado"
        PUBLIC = "public", "Toda la organización"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboards"
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    columns = models.PositiveSmallIntegerField(default=2)
    starred_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="starred_dashboards"
    )

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "panel"
        verbose_name_plural = "paneles"

    def __str__(self) -> str:
        return self.name


class Gadget(TimeStampedModel):
    class Kind(models.TextChoices):
        FILTER_RESULTS = "filter_results", "Resultados de filtro"
        PIE = "pie", "Gráfico circular"
        STATS = "stats", "Estadísticas de incidencias"
        CREATED_VS_RESOLVED = "created_vs_resolved", "Creadas vs. resueltas"
        TWO_D = "two_d", "Estadísticas bidimensionales"
        ASSIGNED_TO_ME = "assigned_to_me", "Asignadas a mí"
        ACTIVITY = "activity", "Flujo de actividad"
        SPRINT_BURNDOWN = "sprint_burndown", "Burndown del sprint"
        TEXT = "text", "Texto"
        CONTROL_CHART = "control_chart", "Gráfico de control"
        CYCLE_TIME = "cycle_time", "Tiempo de ciclo"

    dashboard = models.ForeignKey(Dashboard, on_delete=models.CASCADE, related_name="gadgets")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    title = models.CharField(max_length=120, blank=True)
    config = models.JSONField(default=dict, blank=True)
    column = models.PositiveSmallIntegerField(default=0)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["column", "position", "id"]
        verbose_name = "gadget"
        verbose_name_plural = "gadgets"
