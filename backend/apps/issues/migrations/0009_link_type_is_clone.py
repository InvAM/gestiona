from django.db import migrations, models


def forwards(apps, schema_editor):
    from apps.core.defaults import CLONE_LINK_TYPES

    IssueLinkType = apps.get_model("issues", "IssueLinkType")
    IssueLinkType._base_manager.filter(name__in=CLONE_LINK_TYPES).update(is_clone=True)


class Migration(migrations.Migration):
    """Cloning finds its link type by flag, not by name (admins can rename it)."""

    dependencies = [
        ("issues", "0008_seed_dependency_link_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuelinktype",
            name="is_clone",
            field=models.BooleanField(
                default=False, help_text="Vínculo que se crea al clonar una incidencia"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
