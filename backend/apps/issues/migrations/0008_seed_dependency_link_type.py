from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.defaults import DEPENDENCY_LINK_TYPES

    IssueLinkType = apps.get_model("issues", "IssueLinkType")
    IssueLinkType._base_manager.filter(name__in=DEPENDENCY_LINK_TYPES).update(is_dependency=True)


class Migration(migrations.Migration):
    """The seeded blocking link type is a planning dependency (plans read the flag, never
    the name, so admins can rename it or flag other types)."""

    dependencies = [
        ("core", "0001_defaults"),
        ("issues", "0007_team_and_dependency_flag"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
