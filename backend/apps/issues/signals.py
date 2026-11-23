"""Keep the field-rules cache (apps/issues/fieldrules.py) fresh, and add new custom fields to
the default screen (like Jira)."""

from django.db.models.signals import m2m_changed, post_delete, post_save

from . import fieldrules

PROJECT_RULE_FIELDS = {"workflow", "field_configuration_scheme", "issue_type_screen_scheme"}


def _invalidate(sender, **kwargs):
    if kwargs.get("raw"):
        return
    fieldrules.invalidate()


def _project_saved(sender, instance, created, update_fields=None, raw=False, **kwargs):
    if raw:
        return
    if created or update_fields is None or PROJECT_RULE_FIELDS & set(update_fields):
        fieldrules.invalidate()


def _custom_field_saved(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        fieldrules.add_to_default_screen(instance)
    fieldrules.invalidate()


def connect():
    from apps.projects.models import Project
    from apps.workflows.models import Transition, WorkflowMapping

    from . import models as m

    for model in (m.FieldConfiguration, m.FieldConfigurationItem, m.FieldConfigurationScheme,
                  m.FieldConfigurationSchemeEntry, m.Screen, m.ScreenTab, m.ScreenField,
                  m.ScreenScheme, m.IssueTypeScreenScheme, m.IssueTypeScreenSchemeEntry,
                  m.IssueType, Transition, WorkflowMapping):
        post_save.connect(_invalidate, sender=model, dispatch_uid=f"fieldrules-save-{model}")
        post_delete.connect(_invalidate, sender=model, dispatch_uid=f"fieldrules-del-{model}")
    post_save.connect(_custom_field_saved, sender=m.CustomField,
                      dispatch_uid="fieldrules-cf-save")
    post_delete.connect(_invalidate, sender=m.CustomField, dispatch_uid="fieldrules-cf-del")
    post_save.connect(_project_saved, sender=Project, dispatch_uid="fieldrules-project-save")
    for through in (m.CustomField.projects.through, m.CustomField.issue_types.through,
                    Project.issue_types.through):
        m2m_changed.connect(_invalidate, sender=through,
                            dispatch_uid=f"fieldrules-m2m-{through}")
