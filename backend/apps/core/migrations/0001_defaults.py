from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.defaults import ensure_defaults

    ensure_defaults(apps)


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0001_initial"),
        ("issues", "0002_initial"),
        ("projects", "0002_initial"),
        ("boards", "0002_initial"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
