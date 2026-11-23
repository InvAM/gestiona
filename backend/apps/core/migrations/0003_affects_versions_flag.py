from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.defaults import AFFECTS_VERSIONS_TYPES

    IssueType = apps.get_model("issues", "IssueType")
    IssueType._base_manager.filter(name__in=AFFECTS_VERSIONS_TYPES).update(
        has_affects_versions=True)


class Migration(migrations.Migration):
    """The seeded bug type shows «Versión afectada» (flag instead of comparing names)."""

    dependencies = [
        ("core", "0002_seed_flags"),
        ("issues", "0006_type_and_project_defaults"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
