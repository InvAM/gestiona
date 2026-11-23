"""In-memory stand-in for JiraClient with a small but realistic Cloud project."""

from __future__ import annotations

from apps.imports.jira_client import JiraError


def adf(*paragraphs):
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs
    ]}


ANA = {"accountId": "acc-ana", "displayName": "Ana Pérez", "emailAddress": "member@test.local"}
LUIS = {"accountId": "acc-luis", "displayName": "Luis Hidden"}  # email hidden by privacy

STATUSES = [
    {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
    {"id": "3", "name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    {"id": "4", "name": "QA Review", "statusCategory": {"key": "indeterminate"}},
    {"id": "10", "name": "Done", "statusCategory": {"key": "done"}},
]
TYPES = [
    {"id": "100", "name": "Epic", "hierarchyLevel": 1},
    {"id": "101", "name": "Story", "hierarchyLevel": 0},
    {"id": "102", "name": "Bug", "hierarchyLevel": 0},
    {"id": "103", "name": "Sub-task", "hierarchyLevel": -1, "subtask": True},
]
SPRINT_ACTIVE = {"id": 7, "name": "Sprint 7", "state": "active", "goal": "Pagos",
                 "startDate": "2026-01-05T09:00:00.000Z", "endDate": "2026-01-19T09:00:00.000Z",
                 "originBoardId": 1}
SPRINT_CLOSED = {"id": 6, "name": "Sprint 6", "state": "closed",
                 "startDate": "2025-12-15T09:00:00.000Z", "endDate": "2025-12-29T09:00:00.000Z",
                 "completeDate": "2025-12-29T10:00:00.000Z", "originBoardId": 1}


def _issue(jid, key, summary, itype, status, **fields):
    base = {
        "summary": summary, "issuetype": itype, "status": status,
        "priority": {"name": "High"}, "created": "2025-12-01T10:00:00.000+0000",
        "updated": "2026-01-10T12:00:00.000+0000", "reporter": ANA, "labels": [],
        "comment": {"comments": [], "total": 0}, "worklog": {"worklogs": [], "total": 0},
        "attachment": [], "issuelinks": [], "components": [], "fixVersions": [],
    }
    base.update(fields)
    return {"id": jid, "key": key, "fields": base, "changelog": {"histories": [], "total": 0}}


def build_issues():
    epic = _issue("1001", "PAY-1", "Pagos online", TYPES[0], STATUSES[1],
                  description=adf("Épica de pagos"))
    story = _issue(
        "1002", "PAY-2", "Pagar con tarjeta", TYPES[1], STATUSES[2],
        parent={"id": "1001", "key": "PAY-1"}, assignee=LUIS,
        description={"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Hablar con "},
                {"type": "mention", "attrs": {"id": "acc-ana", "text": "@Ana Pérez"}},
                {"type": "text", "text": " y ", "marks": [{"type": "strong"}]},
            ]},
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"alt": "boceto.png"}}]},
        ]},
        customfield_10020=[SPRINT_CLOSED, SPRINT_ACTIVE], customfield_10016=5,
        customfield_10050={"id": "9001", "value": "Web"}, labels=["pagos", "q1 2026"],
        components=[{"id": "50", "name": "Backend"}], fixVersions=[{"id": "60"}],
        comment={"comments": [{"author": ANA, "body": adf("Primer comentario"),
                               "created": "2025-12-02T10:00:00.000+0000",
                               "updated": "2025-12-02T10:00:00.000+0000"}], "total": 2},
        worklog={"worklogs": [{"author": LUIS, "timeSpentSeconds": 3600,
                               "started": "2026-01-06T09:00:00.000+0000",
                               "comment": adf("Diseño")}], "total": 1},
        timeoriginalestimate=7200, timeestimate=3600, timespent=3600,
        attachment=[{"id": "a1", "filename": "boceto.png", "size": 11, "mimeType": "image/png",
                     "content": "https://acme.atlassian.net/rest/api/3/attachment/content/a1",
                     "author": ANA, "created": "2025-12-03T10:00:00.000+0000"}],
        issuelinks=[{"type": {"name": "Blocks", "outward": "blocks", "inward": "is blocked by"},
                     "outwardIssue": {"key": "PAY-5"}}],
    )
    story["changelog"] = {"total": 1, "histories": [{
        "author": ANA, "created": "2026-01-07T10:00:00.000+0000",
        "items": [{"field": "status", "fromString": "To Do", "toString": "QA Review",
                   "from": "1", "to": "4"},
                  {"field": "Rank", "fromString": "", "toString": "Ranked higher"}],
    }]}
    subtask = _issue("1003", "PAY-3", "Validar CVV", TYPES[3], STATUSES[0],
                     parent={"id": "1002", "key": "PAY-2"})
    bug = _issue("1005", "PAY-5", "Error en el checkout", TYPES[2], STATUSES[3],
                 resolution={"name": "Done"}, resolutiondate="2025-12-20T10:00:00.000+0000",
                 customfield_10020=[SPRINT_CLOSED], priority={"name": "Blocker"},
                 issuelinks=[{"type": {"name": "Blocks", "outward": "blocks",
                                       "inward": "is blocked by"},
                              "inwardIssue": {"key": "PAY-2"}}])
    return [epic, story, subtask, bug]


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def iter_content(self, size):
        yield self.data


class FakeJira:
    host = "acme.atlassian.net"
    is_cloud = True

    def __init__(self, projects=None, fail_on: str | None = None):
        self._projects = projects or {"PAY": build_issues()}
        self.fail_on = fail_on
        self.calls: list[str] = []

    def myself(self):
        return {"displayName": "Admin Jira"}

    def projects(self):
        return [{"key": k, "name": f"Proyecto {k}", "projectTypeKey": "software"}
                for k in self._projects]

    def project(self, key):
        if key == self.fail_on:
            raise JiraError("boom", 500)
        return {"key": key, "name": "Pagos" if key == "PAY" else f"Proyecto {key}",
                "description": "Equipo de pagos", "lead": ANA, "issueTypes": TYPES,
                "projectTypeKey": "software"}

    def project_statuses(self, key):
        return [{"id": t["id"], "name": t["name"], "statuses": STATUSES} for t in TYPES]

    def components(self, key):
        return [{"id": "50", "name": "Backend"}]

    def versions(self, key):
        return [{"id": "60", "name": "v1.0", "released": False, "releaseDate": "2026-02-01"}]

    def fields(self):
        return [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10020", "name": "Sprint", "custom": True,
             "schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
            {"id": "customfield_10016", "name": "Story point estimate", "custom": True,
             "schema": {"type": "number", "custom": "com.atlassian.jira.plugin.system."
                                                    "customfieldtypes:float"}},
            {"id": "customfield_10050", "name": "Canal", "custom": True,
             "schema": {"type": "option", "custom": "com.atlassian.jira.plugin.system."
                                                    "customfieldtypes:select"}},
            {"id": "customfield_10051", "name": "Vacío", "custom": True,
             "schema": {"type": "string", "custom": "com.atlassian.jira.plugin.system."
                                                    "customfieldtypes:textfield"}},
        ]

    def count(self, jql):
        return 4

    def search(self, jql, expand="changelog"):
        key = jql.split('"')[1]
        yield from self._projects[key]

    def comments(self, key):
        self.calls.append(f"comments:{key}")
        return [
            {"author": ANA, "body": adf("Primer comentario"),
             "created": "2025-12-02T10:00:00.000+0000", "updated": "2025-12-02T10:00:00.000+0000"},
            {"author": LUIS, "body": adf("Segundo, editado"),
             "created": "2025-12-04T10:00:00.000+0000", "updated": "2025-12-05T10:00:00.000+0000"},
        ]

    def worklogs(self, key):
        return []

    def changelog(self, key):
        return []

    def remote_links(self, key):
        return []

    def boards(self, key):
        return [{"id": 1, "name": f"Tablero {key}", "type": "scrum"}]

    def sprints(self, board_id):
        future = {"id": 8, "name": "Sprint 8", "state": "future", "originBoardId": 1}
        return [SPRINT_CLOSED, SPRINT_ACTIVE, future]

    def download(self, url):
        return FakeResponse(b"PNGDATA1234")
