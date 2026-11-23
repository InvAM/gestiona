"""Default reference data. Idempotent; used by a data migration and tests."""

STATUSES = [
    ("Backlog", "todo"),
    ("Por hacer", "todo"),
    ("En curso", "in_progress"),
    ("En revisión", "in_progress"),
    ("Listo", "done"),
]

ISSUE_TYPES = [
    # name, icon, color, level, description
    ("Épica", "epic", "#904EE2", 1, "Gran cuerpo de trabajo que agrupa incidencias."),
    ("Historia", "story", "#63BA3C", 0, "Funcionalidad expresada como objetivo del usuario."),
    ("Tarea", "task", "#4BADE8", 0, "Trabajo que hay que hacer."),
    ("Error", "bug", "#E5493A", 0, "Problema que impide o afecta el funcionamiento."),
    ("Subtarea", "subtask", "#4BADE8", -1, "Parte más pequeña de una incidencia."),
]

PRIORITIES = [
    ("Más alta", "highest", "#CD1317", False),
    ("Alta", "high", "#E9494A", False),
    ("Media", "medium", "#E97F33", True),
    ("Baja", "low", "#2D8738", False),
    ("Más baja", "lowest", "#57A55A", False),
]

RESOLUTIONS = [
    ("Hecho", "El trabajo se completó.", True),
    ("No se hará", "No se trabajará en esta incidencia.", False),
    ("Duplicado", "La incidencia duplica otra existente.", False),
    ("No se puede reproducir", "No fue posible reproducir el problema.", False),
]

LINK_TYPES = [
    ("Bloqueo", "bloquea", "está bloqueada por"),
    ("Clonación", "clona", "es clonada por"),
    ("Duplicado", "duplica", "está duplicada por"),
    ("Relación", "se relaciona con", "se relaciona con"),
]

WORKFLOWS = {
    "Flujo de software": ["Por hacer", "En curso", "En revisión", "Listo"],
    "Flujo de tareas": ["Por hacer", "En curso", "Listo"],
}

# Seed flags. Runtime code never looks rows up by these names: it reads the flags/fields
# below (Role.is_system / locked_permissions / is_default, IssueType.templates,
# Workflow.templates), so admins can rename anything.
SYSTEM_ROLES = {
    "Administrador": ["administer"],  # name -> locked permissions
    "Miembro": [],
    "Observador": [],
}
TEMPLATE_WORKFLOWS = {
    "Flujo de software": ["scrum", "kanban"],
    "Flujo de tareas": ["business"],
}
AFFECTS_VERSIONS_TYPES = ["Error"]
# Link types that are planning dependencies (IssueLinkType.is_dependency, used by plans).
DEPENDENCY_LINK_TYPES = ["Bloqueo"]
# Link type created when cloning (IssueLinkType.is_clone).
CLONE_LINK_TYPES = ["Clonación"]
TEMPLATE_TYPES = {
    "Épica": ["scrum", "kanban"],
    "Historia": ["scrum", "kanban"],
    "Tarea": ["scrum", "kanban", "business"],
    "Error": ["scrum", "kanban"],
    "Subtarea": ["scrum", "kanban", "business"],
}


def _has_field(model, name: str) -> bool:
    return any(f.name == name for f in model._meta.get_fields())


def apply_seed_flags(apps=None):
    """Mark seeded rows with the flags runtime code relies on. Idempotent; only touches rows
    that still carry the seed name and have no flags yet."""
    if apps is None:
        from django.apps import apps as global_apps

        apps = global_apps
    Role = apps.get_model("projects", "Role")
    IssueType = apps.get_model("issues", "IssueType")
    Workflow = apps.get_model("workflows", "Workflow")
    if _has_field(Role, "is_system"):
        for name, locked in SYSTEM_ROLES.items():
            for role in Role._base_manager.filter(name=name, is_system=False):
                role.is_system = True
                role.locked_permissions = sorted(set(role.locked_permissions or []) | set(locked))
                perms = set(role.permissions or [])
                if not perms >= set(role.locked_permissions):
                    role.permissions = sorted(perms | set(role.locked_permissions))
                role.save(update_fields=["is_system", "locked_permissions", "permissions"])
    if _has_field(IssueType, "templates"):
        for name, templates in TEMPLATE_TYPES.items():
            IssueType._base_manager.filter(name=name, templates=[]).update(templates=templates)
    if _has_field(IssueType, "has_affects_versions"):
        IssueType._base_manager.filter(name__in=AFFECTS_VERSIONS_TYPES).update(
            has_affects_versions=True)
    IssueLinkType = apps.get_model("issues", "IssueLinkType")
    if _has_field(IssueLinkType, "is_dependency"):
        IssueLinkType._base_manager.filter(name__in=DEPENDENCY_LINK_TYPES).update(
            is_dependency=True)
    if _has_field(IssueLinkType, "is_clone"):
        IssueLinkType._base_manager.filter(name__in=CLONE_LINK_TYPES).update(is_clone=True)
    if _has_field(Workflow, "templates"):
        for name, templates in TEMPLATE_WORKFLOWS.items():
            Workflow._base_manager.filter(name=name, templates=[]).update(templates=templates)


def ensure_defaults(apps=None):
    if apps is None:
        from django.apps import apps as global_apps

        apps = global_apps
    Status = apps.get_model("workflows", "Status")
    Workflow = apps.get_model("workflows", "Workflow")
    WorkflowStatus = apps.get_model("workflows", "WorkflowStatus")
    Transition = apps.get_model("workflows", "Transition")
    IssueType = apps.get_model("issues", "IssueType")
    Priority = apps.get_model("issues", "Priority")
    Resolution = apps.get_model("issues", "Resolution")
    IssueLinkType = apps.get_model("issues", "IssueLinkType")
    Role = apps.get_model("projects", "Role")

    from apps.projects.models import ALL_PERMS, MEMBER_PERMS, VIEWER_PERMS

    statuses = {}
    for name, cat in STATUSES:
        statuses[name], _ = Status.objects.get_or_create(name=name, defaults={"category": cat})

    for i, (name, icon, color, level, desc) in enumerate(ISSUE_TYPES):
        IssueType.objects.get_or_create(
            name=name,
            defaults={"icon": icon, "color": color, "level": level, "description": desc,
                      "position": i},
        )
    for i, (name, icon, color, default) in enumerate(PRIORITIES):
        Priority.objects.get_or_create(
            name=name, defaults={"icon": icon, "color": color, "position": i, "is_default": default}
        )
    done = None
    for i, (name, desc, default) in enumerate(RESOLUTIONS):
        r, _ = Resolution.objects.get_or_create(
            name=name, defaults={"description": desc, "is_default": default, "position": i}
        )
        if default:
            done = r
    for name, out, inw in LINK_TYPES:
        IssueLinkType.objects.get_or_create(name=name, defaults={"outward": out, "inward": inw})

    Role.objects.get_or_create(
        name="Administrador",
        defaults={"permissions": ALL_PERMS, "description": "Control total del proyecto"},
    )
    Role.objects.get_or_create(
        name="Miembro",
        defaults={"permissions": MEMBER_PERMS, "is_default": True,
                  "description": "Crea y trabaja incidencias"},
    )
    Role.objects.get_or_create(
        name="Observador",
        defaults={"permissions": VIEWER_PERMS, "description": "Solo lectura y comentarios"},
    )

    for wf_name, names in WORKFLOWS.items():
        wf, created = Workflow.objects.get_or_create(
            name=wf_name, defaults={"initial_status": statuses[names[0]]}
        )
        if not created:
            continue
        for pos, n in enumerate(names):
            WorkflowStatus.objects.create(
                workflow=wf, status=statuses[n], position=pos, x=pos * 220, y=0
            )
            # simplified workflow: every status reachable from any status (global transitions)
            Transition.objects.create(
                workflow=wf, name=n, to_status=statuses[n], position=pos,
                set_resolution=done if statuses[n].category == "done" else None,
                clear_resolution=statuses[n].category != "done",
            )
    apply_seed_flags(apps)
