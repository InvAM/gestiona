"""Planes (equivalente a Jira Advanced Roadmaps): planificación entre proyectos.

* ``Plan``: fuentes (proyectos + JQL opcional), acceso y unidad de estimación.
* ``Team``: equipos compartidos entre planes; ``Issue.team`` apunta aquí (PROTECT).
* ``PlanTeam``: equipo dentro de un plan y, opcionalmente, el tablero cuyos sprints marcan
  sus iteraciones (sin tablero → iteraciones de longitud fija del plan).
* ``IterationCapacity``: capacidad sobrescrita para un sprint o una iteración fija.
* ``PlanRelease``: versión entre proyectos (agrupa versiones de varios proyectos).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import ALIVE, SoftDeleteModel, TimeStampedModel


class Team(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="teams")
    # Default capacity per iteration; the plan decides which unit it uses.
    capacity_points = models.DecimalField(
        max_digits=8, decimal_places=1, null=True, blank=True,
        help_text="Capacidad por iteración en puntos de historia",
    )
    capacity_hours = models.DecimalField(
        max_digits=8, decimal_places=1, null=True, blank=True,
        help_text="Capacidad por iteración en horas",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "equipo"
        verbose_name_plural = "equipos"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE, name="team_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class Plan(SoftDeleteModel, TimeStampedModel):
    class Access(models.TextChoices):
        PRIVATE = "private", "Privado"
        SHARED = "shared", "Usuarios concretos"
        PUBLIC = "public", "Toda la organización"

    class Estimation(models.TextChoices):
        STORY_POINTS = "story_points", "Puntos de historia"
        HOURS = "hours", "Horas (estimación original)"

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plans"
    )
    projects = models.ManyToManyField("projects.Project", blank=True, related_name="plans")
    filter_jql = models.TextField(blank=True, help_text="Filtro adicional (JQL) de las fuentes")
    access = models.CharField(max_length=10, choices=Access.choices, default=Access.PRIVATE)
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="shared_plans"
    )
    estimation = models.CharField(
        max_length=20, choices=Estimation.choices, default=Estimation.STORY_POINTS
    )
    # Fixed-length iterations for teams without sprints.
    iteration_days = models.PositiveSmallIntegerField(default=14)
    iteration_start = models.DateField(
        null=True, blank=True, help_text="Inicio de la primera iteración fija"
    )
    teams = models.ManyToManyField(Team, through="PlanTeam", blank=True, related_name="plans")

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "plan"
        verbose_name_plural = "planes"

    def __str__(self) -> str:
        return self.name


class PlanTeam(models.Model):
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_teams")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="plan_teams")
    # Scrum board whose sprints are this team's iterations (null → fixed iterations).
    board = models.ForeignKey(
        "boards.Board", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["team__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "team"], name="plan_team_uniq")
        ]


class IterationCapacity(models.Model):
    """Capacity override of a team in one iteration (a sprint, or a fixed iteration by its
    start date)."""

    plan_team = models.ForeignKey(PlanTeam, on_delete=models.CASCADE, related_name="capacities")
    sprint = models.ForeignKey(
        "boards.Sprint", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    iteration_start = models.DateField(null=True, blank=True)
    capacity = models.DecimalField(max_digits=8, decimal_places=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan_team", "sprint"], condition=models.Q(sprint__isnull=False),
                name="capacity_sprint_uniq",
            ),
            models.UniqueConstraint(
                fields=["plan_team", "iteration_start"],
                condition=models.Q(sprint__isnull=True), name="capacity_iteration_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(sprint__isnull=False) | models.Q(iteration_start__isnull=False),
                name="capacity_has_iteration",
            ),
        ]


class PlanRelease(TimeStampedModel):
    """Cross-project release: groups versions of several projects with one target date."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="releases")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    versions = models.ManyToManyField("projects.Version", blank=True, related_name="plan_releases")

    class Meta:
        ordering = ["target_date", "name", "id"]
        verbose_name = "versión entre proyectos"
        verbose_name_plural = "versiones entre proyectos"

    def __str__(self) -> str:
        return self.name


class PlanView(TimeStampedModel):
    """Per user and plan layout of the timeline (grouping, filters, scale and what is
    collapsed). Shape validated by `apps.plans.api.PlanViewIn`. Survives the plan's soft
    delete; goes away with the permanent delete (CASCADE)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="views")
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "vista de plan"
        verbose_name_plural = "vistas de plan"
        constraints = [
            models.UniqueConstraint(fields=["user", "plan"], name="plan_view_user_plan_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.plan}"
