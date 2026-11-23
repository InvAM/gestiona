import pytest

pytestmark = pytest.mark.django_db


def test_custom_role_grants_exact_permissions(api, admin, member, project, make_issue):
    api.login(admin)
    perms = [p["key"] for p in api.get("/permissions").json()]
    assert "administer" in perms and "browse" in perms
    r = api.post("/roles", {"name": "Cliente", "description": "Solo ve y comenta",
                            "permissions": ["add_comments", "create_issues"]})
    assert r.status_code == 201, r.content
    role = r.json()
    assert set(role["permissions"]) == {"browse", "add_comments", "create_issues"}
    api.put(f"/projects/GES/members/{member.id}", {"role_id": role["id"]})

    issue = make_issue("Tarea")
    api.login(member)
    meta = api.get("/projects/GES/meta").json()
    assert set(meta["permissions"]) >= {"browse", "add_comments", "create_issues"}
    assert "edit_issues" not in meta["permissions"]
    assert api.patch(f"/issues/{issue.key}", {"summary": "x"}).status_code == 403
    assert api.post(f"/issues/{issue.key}/comments", {"body": "ok"}).status_code == 201


def test_role_rules(api, admin, member, project):
    api.login(member)
    assert api.post("/roles", {"name": "X", "permissions": []}).status_code == 403
    api.login(admin)
    roles = {r["name"]: r for r in api.get("/roles").json()}
    adm = roles["Administrador"]
    assert adm["is_system"] and adm["builtin"] and adm["in_use"] >= 1
    assert adm["locked_permissions"] == ["administer"]
    bad = api.put(f"/roles/{adm['id']}", {"name": "Administrador", "permissions": ["browse"]})
    assert bad.status_code == 422
    assert api.delete(f"/roles/{roles['Miembro']['id']}").status_code == 422
    assert api.post("/roles", {"name": "miembro", "permissions": []}).status_code == 422
    new = api.post("/roles", {"name": "Temporal", "permissions": [], "is_default": True}).json()
    roles = {r["name"]: r for r in api.get("/roles").json()}
    assert roles["Temporal"]["is_default"] and not roles["Miembro"]["is_default"]
    assert api.delete(f"/roles/{new['id']}").status_code == 409  # default role
    miembro = roles["Miembro"]
    api.put(f"/roles/{miembro['id']}", {**miembro, "is_default": True})
    assert api.delete(f"/roles/{new['id']}").status_code == 204
