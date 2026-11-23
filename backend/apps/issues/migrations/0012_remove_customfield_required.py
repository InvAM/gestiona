from django.db import migrations


class Migration(migrations.Migration):
    """`CustomField.required` moved to the field configurations (0011 copied it)."""

    dependencies = [
        ("issues", "0011_default_field_rules"),
    ]

    operations = [
        migrations.RemoveField(model_name="customfield", name="required"),
    ]
