"""SSRF / DNS-rebinding guard (bugs 7 and 8): netguard itself and the Jira client."""

import ipaddress
import logging

import pytest
import requests

from apps.imports import netguard
from apps.imports.jira_client import JiraClient, JiraError, normalize_base_url

from .nethelpers import OTHER_PUBLIC_IP, PUBLIC_IP, LocalServer, route_public_to

INTERNAL = ["127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254",
            "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "::1", "fe80::1", "fc00::1",
            "::ffff:127.0.0.1", "2002:7f00:1::1", "ff02::1"]


@pytest.mark.parametrize("ip", INTERNAL)
def test_non_public_addresses_are_rejected(ip):
    assert not netguard.is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", [PUBLIC_IP, "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_accepted(ip):
    assert netguard.is_public_ip(ipaddress.ip_address(ip))


def test_check_url_resolves_every_address(fake_dns):
    fake_dns.hosts["mixed.example"] = [PUBLIC_IP, "10.0.0.7"]  # one bad record is enough
    with pytest.raises(netguard.UnsafeURL) as e:
        netguard.check_url("https://mixed.example/x")
    assert e.value.internal
    fake_dns.hosts["ok.example"] = [PUBLIC_IP]
    assert netguard.check_url("https://ok.example/x") == PUBLIC_IP
    assert netguard.check_url("http://10.0.0.7:8080/", allow_private=True) == "10.0.0.7"
    fake_dns.hosts["nx.example"] = []
    with pytest.raises(netguard.UnsafeURL, match="No se pudo resolver"):
        netguard.check_url("https://nx.example/")
    for bad in ("ftp://ok.example/", "https://", "javascript:alert(1)", "http://ok.example:99999/"):
        with pytest.raises(netguard.UnsafeURL):
            netguard.check_url(bad)


def test_connection_is_pinned_to_the_validated_address(monkeypatch, fake_dns):
    """DNS rebinding: the first lookup answers a public IP, later ones 127.0.0.1. The HTTP
    stack must connect to the address that was validated, with the original Host header."""
    answers = iter([[PUBLIC_IP]] + [["127.0.0.1"]] * 10)
    fake_dns.hosts["rebind.example"] = lambda: next(answers)
    with LocalServer() as server:
        attempts = route_public_to(monkeypatch, server)
        session = netguard.guarded_session()
        resp = session.get("http://rebind.example/hook", timeout=5, allow_redirects=False)
    assert resp.status_code == 200
    assert attempts == [(PUBLIC_IP, 80)]
    assert fake_dns.calls.count("rebind.example") == 1
    assert server.requests[0][2]["Host"] == "rebind.example"


def test_https_keeps_sni_and_certificate_hostname(fake_dns):
    adapter = netguard.GuardedAdapter()
    req = requests.Request("GET", "https://jira.example:8443/rest").prepare()
    req._gestiona_pin = ("jira.example", PUBLIC_IP)
    host, pool = adapter.build_connection_pool_key_attributes(req, True)
    assert host == {"scheme": "https", "host": PUBLIC_IP, "port": 8443}
    assert pool["server_hostname"] == "jira.example"
    assert pool["assert_hostname"] == "jira.example"


def test_every_redirect_hop_is_validated(monkeypatch, fake_dns):
    fake_dns.hosts["evil.example"] = ["169.254.169.254"]
    with LocalServer() as server:
        server.routes["/go"] = (302, {"Location": "http://evil.example/latest/meta-data"}, b"")
        attempts = route_public_to(monkeypatch, server)
        with pytest.raises(netguard.UnsafeURL):
            netguard.guarded_session().get("http://public.example/go", timeout=5)
    assert attempts == [(PUBLIC_IP, 80)]  # never connected to the metadata address


def test_environment_proxies_are_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.0.0.1:3128")
    assert netguard.guarded_session().trust_env is False


# --------------------------------------------------------------------------- Jira client

def test_jira_base_url_must_be_public(fake_dns, settings):
    fake_dns.hosts["jira.corp"] = ["10.20.30.40"]
    with pytest.raises(JiraError) as e:
        normalize_base_url("https://jira.corp")
    assert "IMPORTS_ALLOW_PRIVATE" in e.value.message
    with pytest.raises(JiraError):
        JiraClient("https://jira.corp", "", "token")
    with pytest.raises(JiraError):
        JiraClient("http://127.0.0.1:8000", "", "token")
    with pytest.raises(JiraError, match="usuario"):
        normalize_base_url("https://user:pw@acme.atlassian.net")

    settings.IMPORTS_ALLOW_PRIVATE = True
    assert JiraClient("https://jira.corp", "", "token").base_url == "https://jira.corp"


def test_jira_host_is_revalidated_before_each_request(monkeypatch, fake_dns):
    """The host was public when the client was built (e.g. when the job was queued) but
    now resolves internally: the request is refused before connecting."""
    answers = iter([[PUBLIC_IP], ["10.0.0.5"], ["10.0.0.5"]])
    fake_dns.hosts["jira.example"] = lambda: next(answers)
    client = JiraClient("https://jira.example", "a@b.c", "t")
    attempts: list = []

    def create_connection(address, *a, **k):
        attempts.append(address)
        raise OSError("test: no network")

    monkeypatch.setattr("urllib3.util.connection.create_connection", create_connection)
    with pytest.raises(JiraError, match="interna"):
        client.get("/rest/api/2/myself")
    assert attempts == []


def test_jira_errors_do_not_leak_remote_body(monkeypatch, fake_dns, caplog):
    with LocalServer() as server:
        server.routes["/rest/api/2/boom"] = (500, {}, b"Traceback: SECRET-INTERNAL-DETAIL")
        route_public_to(monkeypatch, server)
        client = JiraClient("http://jira.example", "a@b.c", "t")
        with caplog.at_level(logging.WARNING, logger="apps.imports.jira_client"), \
                pytest.raises(JiraError) as e:
            client.get("/rest/api/2/boom")
    assert e.value.status == 500
    assert e.value.message == "Jira respondió con un error (HTTP 500)"
    assert "SECRET" not in e.value.message
    assert "SECRET-INTERNAL-DETAIL" in caplog.text  # full detail only in the server log


def test_jira_api_calls_do_not_follow_redirects(monkeypatch, fake_dns):
    with LocalServer() as server:
        server.routes["/rest/api/2/myself"] = (
            302, {"Location": "http://jira.example/elsewhere"}, b"")
        route_public_to(monkeypatch, server)
        client = JiraClient("http://jira.example", "a@b.c", "t")
        with pytest.raises(JiraError, match="redirección"):
            client.get("/rest/api/2/myself")
    assert [r[1] for r in server.requests] == ["/rest/api/2/myself"]


def test_jira_download_follows_validated_redirects_without_credentials(monkeypatch, fake_dns):
    fake_dns.hosts["media.example"] = [OTHER_PUBLIC_IP]
    fake_dns.hosts["metadata.example"] = ["169.254.169.254"]
    with LocalServer() as server:
        server.routes["/rest/api/3/attachment/content/1"] = (
            303, {"Location": "http://media.example/file/1?token=x"}, b"")
        server.routes["/file/1"] = (200, {"Content-Type": "text/plain"}, b"contenido")
        server.routes["/rest/api/3/attachment/content/2"] = (
            302, {"Location": "http://metadata.example/latest"}, b"")
        attempts = route_public_to(monkeypatch, server)
        client = JiraClient("http://jira.example", "a@b.c", "secret-token")
        resp = client.download("http://jira.example/rest/api/3/attachment/content/1")
        assert resp.content == b"contenido"
        with pytest.raises(JiraError, match="interna"):
            client.download("http://jira.example/rest/api/3/attachment/content/2")
    first, media = server.requests[0], server.requests[1]
    assert "Authorization" in first[2]
    assert media[2]["Host"] == "media.example" and "Authorization" not in media[2]
    assert ("169.254.169.254", 80) not in attempts
    with pytest.raises(JiraError, match="fuera del sitio"):
        client.download("http://other.example/x")


@pytest.mark.django_db
def test_importer_revalidates_the_job_url(admin, fake_dns):
    from apps.imports.jira_importer import JiraImporter, run_job
    from apps.imports.models import ImportJob

    fake_dns.hosts["jira.corp"] = ["192.168.0.10"]  # was public when the job was queued
    job = ImportJob.objects.create(created_by=admin, base_url="https://jira.corp",
                                   auth_email="", auth_token="t", projects=[{"key": "PAY"}],
                                   options={})
    with pytest.raises(JiraError):
        JiraImporter(job)
    job = run_job(job.id)
    job.refresh_from_db()
    assert job.state == ImportJob.State.FAILED and "interna" in job.error
    assert job.auth_token == "" and job.finished_at is not None


@pytest.mark.django_db
def test_api_rejects_internal_jira(api, admin, fake_dns):
    fake_dns.hosts["jira.corp"] = ["10.0.0.1"]
    api.login(admin)
    body = {"base_url": "https://jira.corp", "email": "", "token": "t"}
    r = api.post("/imports/jira/preview", body)
    assert r.status_code == 422 and "interna" in r.json()["message"]
    r = api.post("/imports/jira", {**body, "projects": [{"key": "PAY"}]})
    assert r.status_code == 422 and "interna" in r.json()["message"]
