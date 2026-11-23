from datetime import datetime, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.automation import engine
from apps.automation.models import AutomationLog, AutomationRule

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(django_capture_on_commit_callbacks):
    """Execute on_commit callbacks (rules run after commit) inside the block."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


def _rule(project, **kw):
    kw.setdefault("name", "Regla")
    kw.setdefault("trigger", "issue_created")
    return AutomationRule.objects.create(project=project, **kw)


def _status(project, category):
    return project.workflow.statuses.filter(category=category).first()


def test_created_rule_assigns_comments_and_labels(run, project, admin, member, make_issue):
    _rule(project, actions=[
        {"type": "assign", "to": "user", "user_id": member.id},
        {"type": "comment", "body": "Hola {{issue.assignee}}, revisa {{issue.key}}"},
        {"type": "edit", "add_labels": ["triage"], "fields": {"due_in_days": 3}},
    ])
    with run():
        issue = make_issue("Nueva")
    issue.refresh_from_db()
    assert issue.assignee == member and issue.labels == ["triage"]
    assert issue.due_date == timezone.localdate() + timedelta(days=3)
    comment = issue.comments.get()
    assert comment.author.is_bot and comment.body_text == f"Hola Miembro Uno, revisa {issue.key}"
    assert not issue.watchers.filter(is_bot=True).exists()
    entry = AutomationLog.objects.get()
    assert entry.status == "success" and len(entry.actions_done) == 3


def test_jql_condition_filters(run, project, make_issue):
    _rule(project, conditions=[{"type": "jql", "jql": "type = Error"}],
          actions=[{"type": "edit", "fields": {"flagged": True}}])
    with run():
        task = make_issue("Tarea")
        bug = make_issue("Bug", type_name="Error")
    task.refresh_from_db()
    bug.refresh_from_db()
    assert not task.flagged and bug.flagged
    assert list(AutomationLog.objects.order_by("id").values_list("status", flat=True)) == \
        ["no_match", "success"]


def test_transition_trigger_closes_parent_when_children_done(run, project, admin, make_issue):
    from apps.issues.services import transition_issue

    done = _status(project, "done")
    _rule(project, trigger="issue_transitioned", trigger_config={"to_status_ids": [done.id]},
          conditions=[{"type": "children_done", "of": "parent"}],
          actions=[{"type": "transition", "status_id": done.id, "target": "parent"}])
    story = make_issue("Historia", type_name="Historia")
    s1 = make_issue("S1", type_name="Subtarea", parent_id=story.id)
    s2 = make_issue("S2", type_name="Subtarea", parent_id=story.id)
    with run():
        transition_issue(admin, s1, to_status_id=done.id)
    story.refresh_from_db()
    assert story.status != done  # s2 still open
    with run():
        transition_issue(admin, s2, to_status_id=done.id)
    story.refresh_from_db()
    assert story.status == done and story.resolution is not None


def test_bot_changes_do_not_retrigger_unless_allowed(run, project, make_issue, member):
    # rule A comments on every update; rule B listens to comments
    _rule(project, name="A", trigger="issue_updated", trigger_config={"fields": ["priority"]},
          actions=[{"type": "comment", "body": "prioridad cambiada"}])
    b = _rule(project, name="B", trigger="comment_added",
              actions=[{"type": "edit", "add_labels": ["comentada"]}])
    issue = make_issue("X")
    from apps.issues.services import update_issue

    with run():
        update_issue(member, issue, {"priority": 1})
    issue.refresh_from_db()
    assert issue.comments.count() == 1 and issue.labels == []
    b.allow_rule_triggers = True
    b.save()
    with run():
        update_issue(member, issue, {"priority": 2})
    issue.refresh_from_db()
    assert issue.labels == ["comentada"]


def test_self_loop_is_bounded(run, project, make_issue):
    _rule(project, trigger="issue_updated", allow_rule_triggers=True,
          actions=[{"type": "edit", "fields": {"story_points": None}, "add_labels": ["x"]},
                   {"type": "edit", "remove_labels": ["x"]}])
    from apps.issues.services import update_issue

    issue = make_issue("Loop")
    with run():
        update_issue(issue.reporter, issue, {"summary": "Loop 2"})
    assert AutomationLog.objects.count() <= engine.MAX_DEPTH


def test_failure_is_logged_and_other_rules_continue(run, project, make_issue):
    _rule(project, name="mala", actions=[{"type": "transition", "status_id": 999999}])
    _rule(project, name="buena", actions=[{"type": "edit", "add_labels": ["ok"]}])
    with run():
        issue = make_issue("Y")
    issue.refresh_from_db()
    assert issue.labels == ["ok"]
    bad = AutomationLog.objects.get(rule__name="mala")
    assert bad.status == "failure" and bad.message


def test_notify_sends_email(run, project, member, make_issue):
    _rule(project, actions=[{"type": "notify", "to": ["assignee"],
                             "subject": "Nueva: {{issue.key}}", "body": "{{issue.summary}}"}])
    with run():
        issue = make_issue("Correo", assignee_id=member.id)
    assert len(mail.outbox) >= 1
    msg = next(m for m in mail.outbox if m.subject == f"Nueva: {issue.key}")
    assert msg.to == [member.email] and "Correo" in msg.body


def test_global_rule_applies_to_every_project(run, project, admin, make_issue):
    _rule(None, actions=[{"type": "edit", "add_labels": ["global"]}])
    with run():
        issue = make_issue("G")
    issue.refresh_from_db()
    assert issue.labels == ["global"]


def test_scheduled_rule(project, make_issue):
    issue = make_issue("Vencida", due_date=timezone.localdate() - timedelta(days=1))
    make_issue("Al día")
    rule = _rule(project, trigger="scheduled",
                 trigger_config={"every": "day", "time": "08:00",
                                 "jql": "due < now() AND resolution = Unresolved"},
                 actions=[{"type": "edit", "fields": {"flagged": True}}])
    assert engine.run_scheduled() == 0  # first pass only schedules
    rule.refresh_from_db()
    assert rule.next_run_at is not None
    assert engine.run_scheduled(rule.next_run_at + timedelta(seconds=1)) == 1
    issue.refresh_from_db()
    assert issue.flagged
    assert project.issues.filter(flagged=True).count() == 1


def test_next_run():
    tz = timezone.get_default_timezone()
    base = timezone.make_aware(datetime(2026, 3, 4, 10, 30), tz)  # Wednesday
    assert timezone.localtime(engine.next_run({"every": "day", "time": "09:00"}, base)).day == 5
    assert timezone.localtime(engine.next_run({"every": "day", "time": "11:00"}, base)).hour == 11
    wk = timezone.localtime(engine.next_run({"every": "week", "time": "09:00", "weekday": 0},
                                            base))
    assert wk.weekday() == 0 and wk.day == 9
    hr = timezone.localtime(engine.next_run({"every": "hour", "time": "00:15"}, base))
    assert (hr.hour, hr.minute) == (11, 15)


# --------------------------------------------------------------------------- API

def test_api_crud_and_permissions(api, admin, member, project):
    body = {"name": "Asignar errores", "trigger": "issue_created",
            "conditions": [{"type": "jql", "jql": "type = Error"}],
            "actions": [{"type": "assign", "to": "lead"}]}
    api.login(member)
    assert api.post("/automation/rules?project=GES", body).status_code == 403
    assert api.get("/automation/rules").status_code == 403  # global rules: admins only
    api.login(admin)
    r = api.post("/automation/rules?project=GES", body)
    assert r.status_code == 201, r.content
    rid = r.json()["id"]
    assert api.get("/automation/rules?project=GES").json()[0]["name"] == "Asignar errores"
    bad = {**body, "conditions": [{"type": "jql", "jql": "type = = ="}]}
    assert api.put(f"/automation/rules/{rid}", bad).status_code == 422
    assert api.post(f"/automation/rules/{rid}/enabled", {"enabled": False}).json()["enabled"] \
        is False
    assert api.delete(f"/automation/rules/{rid}").status_code == 204


def test_api_rejects_internal_webhooks_and_non_admin_webhooks(api, admin, member, project):
    from apps.projects.models import Role
    from apps.projects.services import set_member

    body = {"name": "Hook", "trigger": "issue_created",
            "actions": [{"type": "webhook", "url": "http://127.0.0.1:8000/admin/"}]}
    api.login(admin)
    r = api.post("/automation/rules?project=GES", body)
    assert r.status_code == 422 and "interna" in r.json()["message"]
    set_member(admin, project, member.id, Role.objects.get(name="Administrador").id)
    api.login(member)  # project admin, not system admin
    body["actions"][0]["url"] = "https://hooks.example.com/x"
    r = api.post("/automation/rules?project=GES", body)
    assert r.status_code == 422 and "administradores del sistema" in r.json()["message"]


def test_manual_rule_from_issue(api, admin, project, make_issue):
    rule = _rule(project, name="Escalar", trigger="manual",
                 actions=[{"type": "edit", "fields": {"priority": 1}, "add_labels": ["esc"]}])
    issue = make_issue("M")
    api.login(admin)
    assert api.get(f"/issues/{issue.key}/automation").json() == [{"id": rule.id,
                                                                  "name": "Escalar"}]
    r = api.post(f"/issues/{issue.key}/automation/{rule.id}")
    assert r.status_code == 200 and r.json()["status"] == "success", r.content
    issue.refresh_from_db()
    assert issue.labels == ["esc"] and issue.priority_id == 1


def test_bot_is_hidden_from_user_lists(api, admin, project):
    engine.bot_user()
    api.login(admin)
    emails = [u["email"] for u in api.get("/users?limit=100").json()]
    assert engine.BOT_EMAIL not in emails
    assert engine.BOT_EMAIL not in [u["email"] for u in api.get("/admin/users").json()]
