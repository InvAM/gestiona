from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import (
    ALIVE,
    SoftDeleteManager,
    SoftDeleteModel,
    SoftDeleteQuerySet,
    TimeStampedModel,
)


class Perm(models.TextChoices):
    BROWSE = "browse", "Ver proyecto"
    CREATE_ISSUES = "create_issues", "Crear incidencias"
    EDIT_ISSUES = "edit_issues", "Editar incidencias"
    DELETE_ISSUES = "delete_issues", "Eliminar incidencias"
    ASSIGN_ISSUES = "assign_issues", "Asignar incidencias"
    ASSIGNABLE = "assignable", "Puede ser asignado"
    TRANSITION_ISSUES = "transition_issues", "Cambiar estado"
    MANAGE_SPRINTS = "manage_sprints", "Gestionar sprints"
    ADD_COMMENTS = "add_comments", "Comentar"
    EDIT_ALL_COMMENTS = "edit_all_comments", "Editar todos los comentarios"
    DELETE_ALL_COMMENTS = "delete_all_comments", "Eliminar todos los comentarios"
    CREATE_ATTACHMENTS = "create_attachments", "Adjuntar archivos"
    DELETE_ALL_ATTACHMENTS = "delete_all_attachments", "Eliminar todos los adjuntos"
    LINK_ISSUES = "link_issues", "Vincular incidencias"
    LOG_WORK = "log_work", "Registrar trabajo"
    ADMINISTER = "administer", "Administrar proyecto"


ALL_PERMS = [p.value for p in Perm]
VIEWER_PERMS = [Perm.BROWSE.value, Perm.ADD_COMMENTS.value]
MEMBER_PERMS = [
    p for p in ALL_PERMS
    if p not in {
        Perm.ADMINISTER.value, Perm.DELETE_ISSUES.value, Perm.EDIT_ALL_COMMENTS.value,
        Perm.DELETE_ALL_COMMENTS.value, Perm.DELETE_ALL_ATTACHMENTS.value,
    }
]


class RoleQuerySet(SoftDeleteQuerySet):
    def default_role(self):
        """Role given to a member added without an explicit role."""
        return self.filter(is_default=True).order_by("id").first()

    def admin_role(self):
        """Role given to a project's lead / creator: the one whose `administer` permission
        is locked (system Administrador, whatever it is called now). Falls back to any role
        that grants `administer`."""
        admin = Perm.ADMINISTER.value
        return (
            self.filter(locked_permissions__contains=[admin]).order_by("-is_system", "id").first()
            or self.filter(permissions__contains=[admin]).order_by("-is_system", "id").first()
        )


class RoleManager(SoftDeleteManager.from_queryset(RoleQuerySet)):
    pass


class AllRolesManager(models.Manager.from_queryset(RoleQuerySet)):
    pass


class Role(SoftDeleteModel, TimeStampedModel):
    """Project role with its permission set. Behaviour never depends on the role's name:
    system roles are flagged with `is_system` and keep `locked_permissions`."""

    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)
    permissions = ArrayField(models.CharField(max_length=40, choices=Perm.choices), default=list)
    is_default = models.BooleanField(
        default=False, help_text="Rol asignado al agregar un miembro sin rol explícito"
    )
    is_system = models.BooleanField(
        default=False, help_text="Rol del sistema: no se puede eliminar"
    )
    locked_permissions = models.JSONField(
        default=list, blank=True, help_text="Permisos que no se pueden quitar de este rol"
    )

    objects = RoleManager()
    all_objects = AllRolesManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "rol"
        verbose_name_plural = "roles"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE, name="role_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


project_key_validator = RegexValidator(
    r"^[A-Z][A-Z0-9]{1,9}$",
    "La clave debe empezar con una letra mayúscula y tener de 2 a 10 caracteres (A-Z, 0-9).",
)


class Project(TimeStampedModel):
    class Template(models.TextChoices):
        SCRUM = "scrum", "Scrum"
        KANBAN = "kanban", "Kanban"
        BUSINESS = "business", "Gestión de tareas"

    class Access(models.TextChoices):
        OPEN = "open", "Abierto"  # todos pueden ver y crear
        LIMITED = "limited", "Limitado"  # todos ven, solo miembros editan
        PRIVATE = "private", "Privado"  # solo miembros

    class DefaultAssignee(models.TextChoices):
        UNASSIGNED = "unassigned", "Sin asignar"
        LEAD = "lead", "Responsable del proyecto"

    key = models.CharField(max_length=10, unique=True, validators=[project_key_validator])
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    template = models.CharField(max_length=20, choices=Template.choices, default=Template.SCRUM)
    access = models.CharField(max_length=10, choices=Access.choices, default=Access.LIMITED)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="led_projects"
    )
    default_assignee = models.CharField(
        max_length=12, choices=DefaultAssignee.choices, default=DefaultAssignee.UNASSIGNED
    )
    avatar = models.CharField(max_length=40, default="rocket", help_text="Icono del proyecto")
    color = models.CharField(max_length=9, default="#0052CC")
    category = models.ForeignKey(
        "ProjectCategory", null=True, blank=True, on_delete=models.SET_NULL, related_name="projects"
    )
    issue_types = models.ManyToManyField("issues.IssueType", related_name="projects", blank=True)
    default_issue_type = models.ForeignKey(
        "issues.IssueType", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Tipo preseleccionado al crear incidencias (vacío = primer tipo estándar)",
    )
    workflow = models.ForeignKey(
        "workflows.Workflow", on_delete=models.PROTECT, related_name="projects"
    )
    # Field rules (Jira company-managed). Empty = the scheme flagged `is_default`; new
    # projects get the default ones on creation (see save()).
    field_configuration_scheme = models.ForeignKey(
        "issues.FieldConfigurationScheme", null=True, blank=True, on_delete=models.PROTECT,
        related_name="projects",
    )
    issue_type_screen_scheme = models.ForeignKey(
        "issues.IssueTypeScreenScheme", null=True, blank=True, on_delete=models.PROTECT,
        related_name="projects",
    )
    issue_counter = models.PositiveIntegerField(default=0)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ProjectMember", related_name="projects"
    )
    starred_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="starred_projects", blank=True
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "proyecto"
        verbose_name_plural = "proyectos"

    def __str__(self) -> str:
        return f"{self.key} · {self.name}"

    def save(self, *args, **kwargs):
        self.key = self.key.upper()
        if self._state.adding:
            from apps.issues.models import FieldConfigurationScheme, IssueTypeScreenScheme

            if self.field_configuration_scheme_id is None:
                self.field_configuration_scheme = FieldConfigurationScheme.objects.filter(
                    is_default=True).first()
            if self.issue_type_screen_scheme_id is None:
                self.issue_type_screen_scheme = IssueTypeScreenScheme.objects.filter(
                    is_default=True).first()
        super().save(*args, **kwargs)


class ProjectCategory(SoftDeleteModel, TimeStampedModel):
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoría de proyecto"
        verbose_name_plural = "categorías de proyecto"
        constraints = [
            models.UniqueConstraint(fields=["name"], condition=ALIVE,
                                    name="project_category_name_alive_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class ProjectMember(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")

    class Meta:
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_project_member")
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.project.key} ({self.role})"


class Component(SoftDeleteModel, TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "componente"
        verbose_name_plural = "componentes"
        # M2M from issues must keep showing deleted components → related managers see all
        # rows; selectors filter with `.alive()` / `Component.objects`.
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], condition=ALIVE,
                                    name="unique_component_name")
        ]

    def __str__(self) -> str:
        return self.name


class Version(SoftDeleteModel, TimeStampedModel):
    class Status(models.TextChoices):
        UNRELEASED = "unreleased", "No publicada"
        RELEASED = "released", "Publicada"
        ARCHIVED = "archived", "Archivada"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="versions")
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNRELEASED)
    start_date = models.DateField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "versión"
        verbose_name_plural = "versiones"
        default_manager_name = "all_objects"  # see Component
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], condition=ALIVE,
                                    name="unique_version_name")
        ]

    def __str__(self) -> str:
        return self.name
