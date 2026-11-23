from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.defaults import apply_seed_flags

    apply_seed_flags(apps)


class Migration(migrations.Migration):
    """Flag the seeded roles / issue types / workflows so runtime code never needs their
    names (system roles keep `administer` locked, project templates pick types and workflow
    by `templates`)."""

    dependencies = [
        ("core", "0001_defaults"),
        ("projects", "0003_soft_delete"),
        ("issues", "0005_soft_delete"),
        ("workflows", "0002_soft_delete"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
