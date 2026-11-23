"""The Jira importer is exempt from the field rules (screens / required fields): it brings in
what Jira had, even when Gestiona would require more (decision documented in
apps/issues/fieldrules.py)."""

import pytest

from apps.imports.jira_importer import JiraImporter
from apps.imports.models import ImportJob

from .fake_jira import FakeJira

pytestmark = pytest.mark.django_db


def test_import_ignores_required_fields(admin):
    from apps.issues import fieldrules
    from apps.issues.models import FieldConfiguration, FieldConfigurationItem, Issue
    from apps.projects.models import Project

    config = FieldConfiguration.objects.get(is_default=True)
    for key in ("team", "due_date"):  # nothing imported from the fake Jira has a team
        FieldConfigurationItem.objects.create(configuration=config, field=key, required=True)

    job = ImportJob.objects.create(
        created_by=admin, base_url="https://acme.atlassian.net", auth_email="a@acme.com",
        auth_token="secret-token", projects=[{"key": "PAY", "target_key": "PAY",
                                              "access": "limited"}])
    JiraImporter(job, FakeJira()).run()
    job.refresh_from_db()
    assert job.state == ImportJob.State.DONE, job.log
    project = Project.objects.get(key="PAY")
    assert Issue.objects.filter(project=project).count() == 4
    assert not Issue.objects.filter(project=project, team__isnull=False).exists()
    # the imported project gets the default schemes, so the rules apply from now on
    assert project.field_configuration_scheme.is_default
    issue = Issue.objects.filter(project=project).first()
    assert "team" in fieldrules.resolve(project, issue.issue_type).create_required
