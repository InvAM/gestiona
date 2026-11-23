import pytest

from apps.audit.models import AuditEntry

pytestmark = pytest.mark.django_db


def test_config_changes_are_audited_and_secrets_scrubbed(api, admin, project, member):
    api.login(admin)
    assert api.patch("/projects/GES", {"name": "Core renombrado"}).status_code == 200
    r = api.post("/imports/jira", {"base_url": "https://acme.atlassian.net", "email": "a@b.c",
                                   "token": "super-secreto", "projects": [{"key": "ACME"}]})
    assert r.status_code == 201
    api.get("/projects/GES/meta")  # reads are not audited
    api.patch("/projects/NOPE", {"name": "x"})  # failures are not audited

    entries = list(AuditEntry.objects.order_by("id"))
    actions = [e.action for e in entries if e.category != "auth"]
    assert actions == ["Proyecto modificado", "Importación desde Jira iniciada"]
    proj = next(e for e in entries if e.action == "Proyecto modificado")
    assert proj.project_key == "GES" and proj.actor == admin
    assert proj.details["body"] == {"name": "Core renombrado"}
    imp = next(e for e in entries if e.category == "imports")
    assert imp.details["body"]["token"] == "***"
    assert "super-secreto" not in str(imp.details)


def test_issue_delete_and_bulk_are_audited(api, admin, make_issue):
    a, b = make_issue("A"), make_issue("B")
    api.login(admin)
    api.delete(f"/issues/{a.key}")
    api.post("/issues/bulk", {"issue_ids": [b.id], "delete": True})
    acts = list(AuditEntry.objects.filter(category="issues").order_by("id")
                .values_list("action", "object_repr"))
    assert acts == [("Incidencia eliminada", a.key), ("Eliminación masiva", "1 incidencias")]


def test_login_events(client, admin):
    client.post("/_allauth/browser/v1/auth/login",
                {"email": admin.email, "password": "mala-clave-123"},
                content_type="application/json")
    client.post("/_allauth/browser/v1/auth/login",
                {"email": admin.email, "password": "clave-segura-123"},
                content_type="application/json")
    acts = list(AuditEntry.objects.filter(category="auth").values_list("action", flat=True))
    assert "Inicio de sesión fallido" in acts and "Inicio de sesión" in acts


def test_audit_api_admin_only_and_filters(api, admin, member, project):
    api.login(admin)
    api.patch("/projects/GES", {"description": "x"})
    api.login(member)
    assert api.get("/admin/audit").status_code == 403
    api.login(admin)
    page = api.get("/admin/audit?category=projects").json()
    assert page["total"] == 1 and page["items"][0]["project_key"] == "GES"
    assert api.get("/admin/audit?q=renombrar-nada").json()["total"] == 0


def test_prune(admin, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.services import prune

    old = AuditEntry.objects.create(category="auth", action="viejo")
    AuditEntry.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))
    AuditEntry.objects.create(category="auth", action="nuevo")
    settings.AUDIT_RETENTION_DAYS = 365
    assert prune() == 1
    assert list(AuditEntry.objects.values_list("action", flat=True)) == ["nuevo"]
