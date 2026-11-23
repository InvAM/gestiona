import pytest
from django.contrib.auth import get_user_model

from apps.imports.adf import AdfConverter
from apps.imports.jira_importer import JiraImporter, parse_sprint
from apps.imports.models import ImportedObject, ImportJob

from .fake_jira import FakeJira, adf, build_issues

pytestmark = pytest.mark.django_db
User = get_user_model()


def _job(admin, projects=None, **options):
    return ImportJob.objects.create(
        created_by=admin, base_url="https://acme.atlassian.net", auth_email="a@acme.com",
        auth_token="secret-token",
        projects=projects or [{"key": "PAY", "target_key": "PAY", "access": "limited"}],
        options=options,
    )


# --------------------------------------------------------------------------- ADF

def test_adf_conversion_covers_common_nodes():
    conv = AdfConverter(lambda acc, label: (42, "Ana") if acc == "acc-ana" else None)
    doc = conv.convert({"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "T"}]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "hola", "marks": [{"type": "strong"}, {"type": "em"}]},
            {"type": "mention", "attrs": {"id": "acc-ana", "text": "@Ana"}},
            {"type": "mention", "attrs": {"id": "acc-x", "text": "@Otro"}},
            {"type": "inlineCard", "attrs": {"url": "https://x.dev/a"}},
            {"type": "text", "text": "js", "marks": [{"type": "link",
                                                       "attrs": {"href": "javascript:alert(1)"}}]},
        ]},
        {"type": "panel", "attrs": {"panelType": "info"}, "content": [adf("nota")["content"][0]]},
        {"type": "taskList", "content": [
            {"type": "taskItem", "attrs": {"state": "DONE"},
             "content": [{"type": "text", "text": "hecho"}]}]},
        {"type": "codeBlock", "attrs": {"language": "python"},
         "content": [{"type": "text", "text": "print(1)"}]},
        {"type": "table", "content": [{"type": "tableRow", "content": [
            {"type": "tableHeader", "content": [adf("h")["content"][0]]}]}]},
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"alt": "x.png"}}]},
        {"type": "extension", "attrs": {"extensionKey": "macro"}},
    ]})
    types = [n["type"] for n in doc["content"]]
    assert types == ["heading", "paragraph", "blockquote", "taskList", "codeBlock", "table",
                     "paragraph"]
    para = doc["content"][1]["content"]
    assert para[0]["marks"] == [{"type": "bold"}, {"type": "italic"}]
    assert para[1] == {"type": "mention", "attrs": {"id": "42", "label": "Ana"}}
    assert para[2] == {"type": "text", "text": "@Otro"}
    assert para[3]["marks"][0]["attrs"]["href"] == "https://x.dev/a"
    assert "marks" not in para[4]  # unsafe link dropped, text kept
    assert doc["content"][3]["content"][0]["attrs"] == {"checked": True}
    assert doc["content"][6]["content"][0]["text"] == "📎 x.png"


def test_adf_plain_string_and_empty():
    conv = AdfConverter()
    assert conv.convert(None) is None
    assert conv.convert("línea 1\r\nlínea 2")["content"][1]["content"][0]["text"] == "línea 2"


def test_parse_server_sprint_string():
    raw = ("com.atlassian.greenhopper.service.sprint.Sprint@1a[id=12,rapidViewId=3,"
           "state=ACTIVE,name=Sprint, con coma,goal=,startDate=2026-01-01T00:00:00.000Z,"
           "endDate=<null>,completeDate=<null>,sequence=12]")
    s = parse_sprint(raw)
    assert s["id"] == "12" and s["state"] == "active" and s["name"] == "Sprint, con coma"
    assert s["endDate"] is None


# --------------------------------------------------------------------------- import

def test_full_project_import(admin, member):
    from apps.boards.models import Sprint
    from apps.issues.models import Attachment, Comment, CustomField, Issue, IssueLink
    from apps.projects.models import Project
    from apps.search.jql import compile_jql

    job = _job(admin)
    fake = FakeJira()
    JiraImporter(job, fake).run()
    job.refresh_from_db()
    assert job.state == ImportJob.State.DONE, job.log
    assert job.auth_token == ""  # credential wiped
    assert job.result[0]["issues"] == 4

    project = Project.objects.get(key="PAY")
    assert project.name == "Pagos" and project.issue_counter == 5
    assert project.workflow.name == "Jira PAY"
    names = [s.name for s in project.workflow.ordered_statuses()]
    assert names[0] == "To Do" and names[-1] == "Done" and "QA Review" in names
    assert project.memberships.filter(user=admin, role__name="Administrador").exists()
    # Ana matched by email → existing member user, not a placeholder; lead falls back to her
    assert project.lead == member

    issues = {i.key: i for i in Issue.objects.filter(project=project)}
    assert set(issues) == {"PAY-1", "PAY-2", "PAY-3", "PAY-5"}
    epic, story, sub, bug = (issues[k] for k in ("PAY-1", "PAY-2", "PAY-3", "PAY-5"))
    assert epic.issue_type.level == 1 and story.parent_id == epic.id
    assert sub.parent_id == story.id and sub.sprint_id == story.sprint_id
    assert story.status.name == "QA Review" and story.story_points == 5
    assert story.labels == ["pagos", "q1_2026"]
    assert story.original_estimate == 7200 and story.time_spent == 3600
    assert story.created_at.year == 2025 and story.updated_at.month == 1
    assert [c.name for c in story.components.all()] == ["Backend"]
    assert [v.name for v in story.fix_versions.all()] == ["v1.0"]
    assert bug.resolution is not None and bug.resolved_at.day == 20
    assert bug.priority.name == "Blocker"
    assert epic.rank < story.rank < sub.rank < bug.rank

    # mention resolved to the matched user
    para = story.description["content"][0]["content"]
    assert para[1] == {"type": "mention",
                       "attrs": {"id": str(member.id), "label": member.display_name}}

    # placeholder for user with hidden email
    luis = story.assignee
    assert luis.full_name == "Luis Hidden" and not luis.is_active
    assert luis.email.endswith("@importado.invalid")
    assert ImportedObject.objects.filter(kind="user", external_id="acc-luis").exists()

    # sprints
    active = Sprint.objects.get(board__project=project, name="Sprint 7")
    assert active.state == "active" and active.goal == "Pagos"
    assert story.sprint == active
    assert list(story.closed_sprints.values_list("name", flat=True)) == ["Sprint 6"]
    assert bug.sprint is None
    assert Sprint.objects.filter(board__project=project, name="Sprint 8", state="future").exists()

    # comments: truncated block → fetched all
    assert "comments:PAY-2" in fake.calls
    comments = list(Comment.objects.filter(issue=story).order_by("created_at"))
    assert len(comments) == 2 and comments[1].edited and comments[0].created_at.day == 2
    assert story.worklogs.get().time_spent == 3600

    # history: created + status change (Rank skipped)
    hist = list(story.history.order_by("created_at"))
    assert hist[0].items == [{"field": "created"}]
    assert hist[1].items[0]["field"] == "status" and len(hist[1].items) == 1

    att = Attachment.objects.get(issue=story)
    assert att.filename == "boceto.png" and att.size == 11 and att.file.read() == b"PNGDATA1234"

    link = IssueLink.objects.get()
    assert link.source == story and link.target == bug and link.link_type.name == "Blocks"

    cf = CustomField.objects.get(name="Canal")
    assert cf.kind == "select" and cf.options[0]["value"] == "Web"
    assert story.custom_fields[str(cf.id)] == cf.options[0]["id"]
    assert not CustomField.objects.filter(name="Vacío").exists()  # never used → not created

    # full text search works on imported data
    qs = Issue.objects.filter(compile_jql('text ~ "checkout"', user=admin).q)
    assert list(qs.values_list("key", flat=True)) == ["PAY-5"]


def test_reimport_reuses_placeholder_users(admin):
    JiraImporter(_job(admin), FakeJira()).run()
    before = User.objects.count()
    job = _job(admin, [{"key": "PAY", "target_key": "PAY2"}])
    JiraImporter(job, FakeJira()).run()
    job.refresh_from_db()
    assert job.state == "done"
    assert User.objects.count() == before


def test_partial_failure(admin):
    from apps.projects.models import Project

    fake = FakeJira(projects={"PAY": build_issues(), "BAD": []}, fail_on="BAD")
    job = _job(admin, [{"key": "BAD"}, {"key": "PAY"}])
    JiraImporter(job, fake).run()
    job.refresh_from_db()
    assert job.state == ImportJob.State.PARTIAL
    assert Project.objects.filter(key="PAY").exists()
    assert not Project.objects.filter(key="BAD").exists()
    assert job.result[0]["ok"] is False and "boom" in job.result[0]["error"]


def test_existing_key_is_rejected_without_side_effects(admin, project):
    from apps.workflows.models import Workflow

    job = _job(admin, [{"key": "PAY", "target_key": "GES"}])
    JiraImporter(job, FakeJira()).run()
    job.refresh_from_db()
    assert job.state == ImportJob.State.FAILED
    assert not Workflow.objects.filter(name__startswith="Jira ").exists()


def test_without_users_or_attachments(admin):
    from apps.issues.models import Attachment, Issue

    job = _job(admin, attachments=False, create_users=False, history=False)
    JiraImporter(job, FakeJira()).run()
    story = Issue.objects.get(key="PAY-2")
    assert story.assignee is None
    assert not Attachment.objects.exists()
    assert story.history.count() == 0


# --------------------------------------------------------------------------- API

def test_api_requires_admin(api, member):
    api.login(member)
    r = api.post("/imports/jira/preview", {"base_url": "https://x.atlassian.net",
                                           "email": "a@b.c", "token": "t"})
    assert r.status_code == 403
    assert api.get("/imports").status_code == 403


def test_api_preview_and_run(api, admin, monkeypatch, django_capture_on_commit_callbacks):
    import apps.imports.api as imports_api
    import apps.imports.jira_importer as importer

    monkeypatch.setattr(imports_api, "JiraClient", lambda *a, **k: FakeJira())
    monkeypatch.setattr(importer, "JiraClient", lambda *a, **k: FakeJira())
    api.login(admin)
    r = api.post("/imports/jira/preview", {"base_url": "https://acme.atlassian.net",
                                           "email": "a@acme.com", "token": "t"})
    assert r.status_code == 200, r.content
    assert r.json()["projects"] == [{"key": "PAY", "name": "Proyecto PAY", "type": "software",
                                     "exists": False}]

    with django_capture_on_commit_callbacks(execute=True):
        r = api.post("/imports/jira", {
            "base_url": "https://acme.atlassian.net", "email": "a@acme.com", "token": "t",
            "projects": [{"key": "PAY", "target_key": "pagos"}],
        })
    assert r.status_code == 201, r.content
    assert "token" not in r.json() and "auth_token" not in r.json()
    job = api.get(f"/imports/{r.json()['id']}").json()
    assert job["state"] == "done", job["log"]
    assert job["result"][0]["target_key"] == "PAGOS"
    assert api.get("/projects/PAGOS/meta").status_code == 200


def test_api_validates_keys(api, admin, project):
    api.login(admin)
    body = {"base_url": "https://acme.atlassian.net", "email": "", "token": "t"}
    r = api.post("/imports/jira", {**body, "projects": [{"key": "X", "target_key": "GES"}]})
    assert r.status_code == 422 and "GES" in r.json()["message"]
    r = api.post("/imports/jira", {**body, "projects": [{"key": "A", "target_key": "AB"},
                                                        {"key": "B", "target_key": "ab"}]})
    assert r.status_code == 422
    r = api.post("/imports/jira", {**body, "base_url": "ftp://x", "projects": [{"key": "A"}]})
    assert r.status_code == 422
