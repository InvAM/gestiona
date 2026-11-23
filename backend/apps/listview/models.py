from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ListViewConfig(TimeStampedModel):
    """Per user and project layout of the «Lista» view (visible columns in order, widths,
    grouping). Shape validated by `apps.listview.api.ListViewConfigIn`."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="+")
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "configuración de la vista de lista"
        verbose_name_plural = "configuraciones de la vista de lista"
        constraints = [
            models.UniqueConstraint(fields=["user", "project"], name="unique_list_view_config")
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.project}"
