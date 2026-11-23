from django.db import migrations

# Field keys of the system fields, in the order the issue view shows them today
# (apps/issues/fieldrules.py → SYSTEM_FIELDS). Inlined: migrations must not depend on code
# that may change later.
SYSTEM_KEYS = [
    "summary", "issue_type", "description", "priority", "assignee", "reporter", "labels",
    "components", "fix_versions", "affects_versions", "start_date", "due_date",
    "original_estimate", "remaining_estimate", "story_points", "sprint", "parent", "team",
    "flagged",
]


def forwards(apps, schema_editor):
    """Defaults that keep today's behaviour: everything optional except summary / type (and
    the custom fields flagged `required`), one screen with every field, assigned to every
    project."""
    CustomField = apps.get_model("issues", "CustomField")
    FieldConfiguration = apps.get_model("issues", "FieldConfiguration")
    FieldConfigurationItem = apps.get_model("issues", "FieldConfigurationItem")
    FieldConfigurationScheme = apps.get_model("issues", "FieldConfigurationScheme")
    Screen = apps.get_model("issues", "Screen")
    ScreenTab = apps.get_model("issues", "ScreenTab")
    ScreenField = apps.get_model("issues", "ScreenField")
    ScreenScheme = apps.get_model("issues", "ScreenScheme")
    IssueTypeScreenScheme = apps.get_model("issues", "IssueTypeScreenScheme")
    Project = apps.get_model("projects", "Project")

    config = FieldConfiguration.objects.create(
        name="Configuración de campos predeterminada", is_default=True,
        description="Todos los campos opcionales salvo el resumen y el tipo",
    )
    for cf in CustomField.objects.filter(required=True):
        FieldConfigurationItem.objects.create(configuration=config, field=f"cf:{cf.id}",
                                              custom_field=cf, required=True)
    fcs = FieldConfigurationScheme.objects.create(
        name="Esquema de configuración de campos predeterminado", is_default=True,
        default_configuration=config,
    )

    screen = Screen.objects.create(name="Pantalla predeterminada", is_default=True,
                                   description="Todos los campos")
    tab = ScreenTab.objects.create(screen=screen, name="General", position=0)
    pos = 0
    for key in SYSTEM_KEYS:
        ScreenField.objects.create(screen=screen, tab=tab, field=key, position=pos)
        pos += 1
    for cf in CustomField.objects.filter(deleted_at__isnull=True).order_by("position", "id"):
        ScreenField.objects.create(screen=screen, tab=tab, field=f"cf:{cf.id}",
                                   custom_field=cf, position=pos)
        pos += 1
    ss = ScreenScheme.objects.create(name="Esquema de pantallas predeterminado",
                                     is_default=True, default_screen=screen)
    itss = IssueTypeScreenScheme.objects.create(
        name="Esquema de pantallas por tipo predeterminado", is_default=True,
        default_screen_scheme=ss,
    )
    Project.objects.update(field_configuration_scheme=fcs, issue_type_screen_scheme=itss)


def backwards(apps, schema_editor):
    CustomField = apps.get_model("issues", "CustomField")
    FieldConfigurationItem = apps.get_model("issues", "FieldConfigurationItem")
    ids = [int(f[3:]) for f in FieldConfigurationItem.objects.filter(
        configuration__is_default=True, required=True, field__startswith="cf:",
    ).values_list("field", flat=True)]
    CustomField.objects.filter(id__in=ids).update(required=True)
    Project = apps.get_model("projects", "Project")
    Project.objects.update(field_configuration_scheme=None, issue_type_screen_scheme=None)
    for name in ("IssueTypeScreenScheme", "ScreenScheme", "ScreenField", "ScreenTab",
                 "FieldConfigurationScheme", "FieldConfigurationItem"):
        apps.get_model("issues", name).objects.all().delete()
    apps.get_model("workflows", "Transition").objects.update(screen=None)
    apps.get_model("issues", "Screen").objects.all().delete()
    apps.get_model("issues", "FieldConfiguration").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0010_field_rules"),
        ("projects", "0005_field_schemes"),
        ("workflows", "0003_transition_screen"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
