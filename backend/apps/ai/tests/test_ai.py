import json
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.django_db


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


@pytest.fixture
def fake_ai(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "test-key"

    def install(payload, stop_reason="end_turn"):
        msgs = FakeMessages(payload, stop_reason)
        client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
        monkeypatch.setattr("apps.ai.service._client", lambda: client)
        return msgs

    return install


def test_disabled_without_key(api, admin, make_issue, settings):
    settings.ANTHROPIC_API_KEY = ""
    issue = make_issue("X")
    api.login(admin)
    assert api.get("/ai/status").json() == {"enabled": False, "model": None}
    assert api.post(f"/ai/issues/{issue.key}/summary").status_code == 503


def test_summary_sends_issue_context_and_returns_structured(api, admin, make_issue, fake_ai):
    from apps.issues.services import add_comment

    issue = make_issue("Pagos con tarjeta", description="Integrar pasarela")
    add_comment(admin, issue, "Decidimos usar la pasarela A")
    msgs = fake_ai({"summary": "Integrar pagos", "key_points": ["Pasarela A"],
                    "open_questions": [], "next_steps": ["Firmar contrato"]})
    api.login(admin)
    r = api.post(f"/ai/issues/{issue.key}/summary")
    assert r.status_code == 200, r.content
    assert r.json()["key_points"] == ["Pasarela A"]
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert "Integrar pasarela" in content and "Decidimos usar la pasarela A" in content


def test_summary_respects_permissions(api, admin, outsider, fake_ai):
    from apps.issues.models import IssueType
    from apps.issues.services import IssueInput, create_issue
    from apps.projects.services import create_project

    secret = create_project(admin, name="Secreto", key="SEC", access="private")
    issue = create_issue(admin, secret, IssueInput(
        issue_type_id=IssueType.objects.get(name="Tarea").id, summary="Confidencial"))
    msgs = fake_ai({"summary": "", "key_points": [], "open_questions": [], "next_steps": []})
    api.login(outsider)
    assert api.post(f"/ai/issues/{issue.key}/summary").status_code == 404
    assert msgs.calls == []  # nothing was sent to the model


def test_jql_is_validated(api, admin, project, fake_ai):
    fake_ai({"jql": "project = GES AND resolution = Unresolved", "explanation": "Abiertas"})
    api.login(admin)
    r = api.post("/ai/jql", {"question": "¿qué está abierto en GES?"})
    assert r.status_code == 200 and r.json()["jql"].startswith("project = GES")
    fake_ai({"jql": "project = = =", "explanation": "?"})
    assert api.post("/ai/jql", {"question": "algo raro"}).status_code == 422


def test_refusal_and_draft(api, admin, project, types, fake_ai):
    api.login(admin)
    fake_ai({}, stop_reason="refusal")
    r = api.post("/ai/draft", {"project": "GES", "issue_type_id": types["Historia"].id,
                               "summary": "Login con Google"})
    assert r.status_code == 422 and r.json()["code"] == "ai_refusal"
    fake_ai({"description": "Permitir login", "acceptance_criteria": ["Botón visible"],
             "subtasks": ["Configurar OAuth"]})
    r = api.post("/ai/draft", {"project": "GES", "issue_type_id": types["Historia"].id,
                               "summary": "Login con Google"})
    assert r.json()["subtasks"] == ["Configurar OAuth"]


def test_rate_limit(api, admin, make_issue, fake_ai, monkeypatch):
    monkeypatch.setattr("apps.ai.service.RATE_LIMIT", 2)
    issue = make_issue("X")
    fake_ai({"summary": "", "key_points": [], "open_questions": [], "next_steps": []})
    api.login(admin)
    assert api.post(f"/ai/issues/{issue.key}/summary").status_code == 200
    assert api.post(f"/ai/issues/{issue.key}/summary").status_code == 200
    assert api.post(f"/ai/issues/{issue.key}/summary").status_code == 422
