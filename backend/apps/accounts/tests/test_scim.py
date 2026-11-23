import json

import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def scim(api, admin, client):
    api.login(admin)
    r = api.post("/admin/api-tokens", {"name": "Entra ID"})
    assert r.status_code == 201, r.content
    token = r.json()["token"]
    assert r.json()["scim_url"].endswith("/scim/v2")
    client.logout()

    def call(method, path, body=None, tok=token):
        kw = {"HTTP_AUTHORIZATION": f"Bearer {tok}"}
        if body is not None:
            kw["data"] = json.dumps(body)
            kw["content_type"] = "application/scim+json"
        return getattr(client, method)(f"/scim/v2{path}", **kw)

    call.token_id = r.json()["id"]
    return call


def test_requires_valid_token(scim):
    assert scim("get", "/Users", tok="nope").status_code == 401


def test_provision_update_and_deprovision(scim):
    r = scim("post", "/Users", {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "Lucia.Gomez@Empresa.com", "externalId": "aad-123", "active": True,
        "name": {"givenName": "Lucía", "familyName": "Gómez"},
        "emails": [{"value": "Lucia.Gomez@Empresa.com", "primary": True}],
    })
    assert r.status_code == 201, r.content
    uid = r.json()["id"]
    u = User.objects.get(pk=uid)
    assert u.email == "lucia.gomez@empresa.com" and u.full_name == "Lucía Gómez"
    assert u.external_id == "aad-123" and u.is_active and not u.has_usable_password()

    assert scim("post", "/Users", {"userName": "lucia.gomez@empresa.com"}).status_code == 409
    found = scim("get", '/Users?filter=userName eq "lucia.gomez@empresa.com"').json()
    assert found["totalResults"] == 1 and found["Resources"][0]["id"] == uid
    assert scim("get", '/Users?filter=externalId eq "aad-123"').json()["totalResults"] == 1

    # Entra ID style PATCH (string booleans, path-based ops)
    patch_schema = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
    r = scim("patch", f"/Users/{uid}", {"schemas": [patch_schema],
                                        "Operations": [{"op": "Replace", "path": "title",
                                                        "value": "Diseñadora"},
                                                       {"op": "Replace", "path": "active",
                                                        "value": "False"}]})
    assert r.status_code == 200, r.content
    u.refresh_from_db()
    assert u.job_title == "Diseñadora" and not u.is_active

    # Okta style PATCH without path
    scim("patch", f"/Users/{uid}", {"Operations": [{"op": "replace",
                                                    "value": {"active": True}}]})
    u.refresh_from_db()
    assert u.is_active

    assert scim("delete", f"/Users/{uid}").status_code == 204
    u.refresh_from_db()
    assert not u.is_active  # deactivated, never deleted


def test_revoked_token_stops_working(scim, api, admin):
    api.login(admin)
    assert api.delete(f"/admin/api-tokens/{scim.token_id}").status_code == 204
    assert scim("get", "/Users").status_code == 401


def test_discovery_endpoints(client):
    assert client.get("/scim/v2/ServiceProviderConfig").json()["patch"]["supported"]


def test_oidc_provider_listed(client, settings):
    settings.SOCIALACCOUNT_PROVIDERS = {"openid_connect": {"APPS": [
        {"provider_id": "oidc", "name": "Okta", "client_id": "x", "secret": "y",
         "settings": {"server_url": "https://example.okta.com"}}]}}
    cfg = client.get("/api/v1/auth/config").json()
    assert cfg["providers"] == ["oidc"] and cfg["provider_names"] == {"oidc": "Okta"}
