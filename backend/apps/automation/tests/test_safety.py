"""Automation safety: archived issues (bug 5), recipients/assignees with access (bug 6) and
webhooks pinned to the validated address (bug 8)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.automation import engine
from apps.automation.models import AutomationLog, AutomationRule
from apps.imports.tests.nethelpers import PUBLIC_IP, LocalServer, install_dns, route_public_to

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    return lambda: django_capture_on_commit_callbacks(execute=True)


@pytest.fixture
def dns(monkeypatch):
    return install_dns(monkeypatch)


@pytest.fixture
def private(admin):
    from apps.projects.services import create_project

    return create_project(admin, name="Privado", key="PRV", access="private")


def _rule(project, **kw):
    kw.setdefault("name", "Regla")
    kw.setdefault("trigger", "issue_created")
    return AutomationRule.objects.create(project=project, **kw)


# --------------------------------------------------------------------------- bug 5

def test_no_rule_runs_on_archived_issues(run, project, admin, make_issue):
    from apps.issues.services import archive_issue

    issue = make_issue("Archivada", type_name="Historia")
    archive_issue(admin, issue)
    issue.refresh_from_db()
    rule = _rule(project, trigger="issue_updated",
                 actions=[{"type": "edit", "fields": {"flagged": True}}])

    # dispatch ignores archived issues
    with run() as callbacks:
        engine.dispatch("issue_updated", issue, admin, {"fields": ["summary"]})
    assert callbacks == []
    # an event queued before the archive is dropped by the worker
    engine.run_rules([rule.id], issue.id, admin.id, {"fields": ["summary"]}, 1)
    assert not AutomationLog.objects.exists()
    # direct execution (manual rules) logs why nothing happened
    entry = engine.execute_rule(rule, issue, admin, {})
    assert entry.status == "no_match" and "archivada" in entry.message
    issue.refresh_from_db()
    assert not issue.flagged


def test_scheduled_rules_skip_archived_issues(project, admin, make_issue):
    from apps.issues.services import archive_issue

    yesterday = timezone.localdate() - timedelta(days=1)
    live = make_issue("Viva", due_date=yesterday)
    gone = make_issue("Archivada", due_date=yesterday)
    archive_issue(admin, gone)
    rule = _rule(project, trigger="scheduled",
                 trigger_config={"every": "day", "time": "08:00", "jql": "due < now()"},
                 actions=[{"type": "edit", "fields": {"flagged": True}}])
    engine.run_scheduled()
    rule.refresh_from_db()
    assert engine.run_scheduled(rule.next_run_at + timedelta(seconds=1)) == 1
    live.refresh_from_db()
    gone.refresh_from_db()
    assert live.flagged and not gone.flagged
    assert list(AutomationLog.objects.values_list("issue_id", flat=True)) == [live.id]


def test_actions_on_archived_parent_are_skipped(run, project, admin, make_issue):
    from apps.issues.services import archive_issue, update_issue

    epic = make_issue("Épica", type_name="Épica")
    child = make_issue("Hija", type_name="Historia", parent_id=epic.id)
    archive_issue(admin, epic)  # the child stays active and linked to the archived epic
    _rule(project, trigger="issue_updated",
          actions=[{"type": "comment", "target": "parent", "body": "hola"}])
    with run():
        update_issue(admin, child, {"summary": "Hija editada"})
    entry = AutomationLog.objects.get()
    assert entry.status == "success" and "archivada" in entry.actions_done[0]
    assert not epic.comments.exists()


# --------------------------------------------------------------------------- bug 6

def _body(actions, **kw):
    return {"name": "R", "trigger": "issue_created", "actions": actions, **kw}


def test_validate_rule_rejects_users_without_access(api, admin, outsider, private, project):
    api.login(admin)
    for action in (
        {"type": "notify", "user_ids": [outsider.id]},
        {"type": "add_watcher", "user_id": outsider.id},
        {"type": "assign", "to": "user", "user_id": outsider.id},
    ):
        r = api.post("/automation/rules?project=PRV", _body([action]))
        assert r.status_code == 422, (action, r.content)
        assert r.json()["message"]
    r = api.post("/automation/rules?project=PRV",
                 _body([{"type": "notify", "user_ids": [admin.id]}]))
    assert r.status_code == 201, r.content
    r = api.post("/automation/rules?project=PRV",
                 _body([{"type": "notify", "user_ids": ["x"]}]))
    assert r.status_code == 422


def test_validate_rule_assign_requires_assignable_user(admin, member, outsider, project):
    from apps.core.errors import ValidationFailed

    action = {"type": "assign", "to": "user", "user_id": outsider.id}
    # GES is "limited": outsiders can browse but are not assignable
    with pytest.raises(ValidationFailed, match="asignar"):
        engine.validate_rule(_body([action]), project=project, user=admin)
    ok = engine.validate_rule(_body([{**action, "user_id": member.id}]), project=project,
                              user=admin)
    assert ok["actions"][0]["user_id"] == member.id


def test_runtime_recipients_are_limited_to_people_with_access(run, admin, member, outsider,
                                                              private, make_issue):
    from apps.projects.models import Role
    from apps.projects.services import set_member

    set_member(admin, private, member.id, Role.objects.get(name="Miembro").id)
    # saved while both had access (or bypassing validation): checked again when it runs
    _rule(private, actions=[
        {"type": "notify", "user_ids": [member.id, outsider.id], "subject": "S {{issue.key}}"},
        {"type": "add_watcher", "user_id": outsider.id},
    ])
    with run():
        issue = make_issue("Secreta", project=private)
    sent = [m for m in mail.outbox if m.subject == f"S {issue.key}"]
    assert len(sent) == 1 and sent[0].to == [member.email]
    assert not issue.watchers.filter(pk=outsider.pk).exists()
    entry = AutomationLog.objects.get()
    assert "1 omitido" in entry.actions_done[0] and "no tiene acceso" in entry.actions_done[1]


def test_global_rules_are_checked_against_each_issue_project(run, admin, outsider, private,
                                                             project, make_issue):
    rule = engine.validate_rule(_body([{"type": "notify", "user_ids": [outsider.id],
                                        "subject": "G {{issue.key}}"}]),
                                project=None, user=admin)
    AutomationRule.objects.create(project=None, **rule)
    with run():
        public_issue = make_issue("Visible")  # GES is limited: outsider can browse
        hidden = make_issue("Oculta", project=private)
    subjects = {m.subject: m.to for m in mail.outbox}
    assert subjects.get(f"G {public_issue.key}") == [outsider.email]
    assert f"G {hidden.key}" not in subjects


def test_runtime_assign_rejects_users_who_lost_access(run, admin, member, private, make_issue):
    from apps.projects.models import Role
    from apps.projects.services import remove_member, set_member

    set_member(admin, private, member.id, Role.objects.get(name="Miembro").id)
    _rule(private, actions=[{"type": "assign", "to": "user", "user_id": member.id}])
    remove_member(admin, private, member.id)
    with run():
        issue = make_issue("Sin acceso", project=private)
    issue.refresh_from_db()
    assert issue.assignee_id != member.id
    entry = AutomationLog.objects.get()
    assert entry.status == "failure" and "asignar" in entry.message


# --------------------------------------------------------------------------- bug 8

def _webhook(rule_project, url):
    return _rule(rule_project, actions=[{"type": "webhook", "url": url}])


def test_webhook_is_pinned_to_the_validated_address(run, monkeypatch, dns, project,
                                                    make_issue):
    answers = iter([[PUBLIC_IP]] + [["127.0.0.1"]] * 10)  # DNS rebinding after the check
    dns.hosts["hooks.example"] = lambda: next(answers)
    with LocalServer() as server:
        attempts = route_public_to(monkeypatch, server)
        _webhook(project, "http://hooks.example/in")
        with run():
            make_issue("Hook")
    entry = AutomationLog.objects.get()
    assert entry.status == "success", entry.message
    assert attempts == [(PUBLIC_IP, 80)]
    method, path, headers = server.requests[0]
    assert (method, path, headers["Host"]) == ("POST", "/in", "hooks.example")


def test_webhook_rejects_internal_address_at_run_time(run, monkeypatch, dns, project,
                                                      make_issue):
    dns.hosts["hooks.example"] = ["10.0.0.8"]  # public when saved, internal now
    with LocalServer() as server:
        attempts = route_public_to(monkeypatch, server)
        _webhook(project, "http://hooks.example/in")
        with run():
            make_issue("Hook")
    entry = AutomationLog.objects.get()
    assert entry.status == "failure" and "interna" in entry.message
    assert attempts == []


def test_webhook_private_addresses_allowed_by_setting(run, monkeypatch, dns, settings,
                                                      project, make_issue):
    settings.AUTOMATION_WEBHOOK_ALLOW_PRIVATE = True
    dns.hosts["hooks.internal"] = ["10.0.0.8"]
    with LocalServer() as server:
        attempts = route_public_to(monkeypatch, server, public_ips=())
        _webhook(project, "http://hooks.internal/in")
        with run():
            make_issue("Hook")
    # connection attempted to the (pinned) private address; refused by the test double
    assert attempts == [("10.0.0.8", 80)]
    assert "no se pudo conectar" in AutomationLog.objects.get().message


def test_webhook_does_not_follow_redirects(run, monkeypatch, dns, project, make_issue):
    with LocalServer() as server:
        server.routes["/in"] = (307, {"Location": "http://hooks.example/other"}, b"")
        route_public_to(monkeypatch, server)
        _webhook(project, "http://hooks.example/in")
        with run():
            make_issue("Hook")
    entry = AutomationLog.objects.get()
    assert entry.status == "failure" and "redirección" in entry.message
    assert [r[1] for r in server.requests] == ["/in"]


def test_check_webhook_url_rejects_internal_dns(dns):
    from apps.core.errors import ValidationFailed

    dns.hosts["meta.example"] = ["169.254.169.254"]
    with pytest.raises(ValidationFailed, match="interna"):
        engine.check_webhook_url("https://meta.example/x")
    with pytest.raises(ValidationFailed):
        engine.check_webhook_url("gopher://x")
    engine.check_webhook_url("https://ok.example/x")
