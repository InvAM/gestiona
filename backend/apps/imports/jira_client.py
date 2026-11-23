"""Thin Jira REST client (Cloud v3 and Server/Data Center v2) used by the importer.

All traffic goes through `netguard`: the Jira host must resolve to public addresses (unless
``IMPORTS_ALLOW_PRIVATE`` is enabled), connections are pinned to the validated address and
API calls never follow redirects. Remote error bodies are logged, never returned to users.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from .netguard import GuardedAdapter, UnsafeURL, check_url, guarded_session

log = logging.getLogger(__name__)


class JiraError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


def allow_private() -> bool:
    return bool(getattr(settings, "IMPORTS_ALLOW_PRIVATE", False))


def _unsafe(e: UnsafeURL) -> JiraError:
    if e.internal:
        return JiraError(f"{e.message}. Por seguridad no se permite importar desde redes "
                         "internas (configura IMPORTS_ALLOW_PRIVATE=true para permitirlo)")
    return JiraError(e.message)


def normalize_base_url(url: str, *, resolve: bool = True) -> str:
    """Canonical base URL. With `resolve`, also checks the host resolves to public IPs."""
    url = (url or "").strip().rstrip("/")
    try:
        parsed = urlparse(url)
        parsed.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError as e:
        raise JiraError("La URL de Jira no es válida") from e
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise JiraError("La URL debe empezar con https:// (por ejemplo https://empresa.atlassian.net)")
    if parsed.username or parsed.password:
        raise JiraError("La URL no debe incluir usuario ni contraseña")
    if parsed.query or parsed.fragment:
        raise JiraError("La URL no debe incluir parámetros (?...) ni fragmentos (#...)")
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    if resolve:
        try:
            check_url(base, allow_private=allow_private())
        except UnsafeURL as e:
            raise _unsafe(e) from e
    return base


class JiraClient:
    PAGE = 100

    def __init__(self, base_url: str, email: str, token: str, *, session=None, timeout=60):
        self.base_url = normalize_base_url(base_url)
        self.host = urlparse(self.base_url).netloc
        if session is None:
            session = guarded_session(allow_private=allow_private())
        else:
            session.trust_env = False
            adapter = GuardedAdapter(allow_private=allow_private())
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        self.session = session
        self.timeout = timeout
        if email:
            self.session.auth = (email, token)
        else:  # Server / Data Center personal access token
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers.setdefault("Accept", "application/json")
        self.session.headers.setdefault("User-Agent", "Gestiona-Importer/1.0")
        self._cloud: bool | None = None

    # ------------------------------------------------------------------ transport
    def _request(self, method: str, path: str, *, params=None, json=None, stream=False,
                 follow_redirects=False):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        if urlparse(url).netloc != self.host:
            raise JiraError("URL fuera del sitio de Jira configurado")
        for attempt in range(6):
            try:
                # the adapter re-validates and pins the address on every attempt and hop
                resp = self.session.request(method, url, params=params, json=json,
                                            timeout=self.timeout, stream=stream,
                                            allow_redirects=follow_redirects)
            except UnsafeURL as e:
                raise _unsafe(e) from e
            except requests.TooManyRedirects as e:
                raise JiraError("Jira redirigió demasiadas veces") from e
            except requests.RequestException as e:
                if attempt == 5:
                    log.warning("jira request failed: %s %s", method, url, exc_info=True)
                    raise JiraError(f"No se pudo conectar con Jira ({type(e).__name__})") from e
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in (429, 502, 503, 504) and attempt < 5:
                wait = resp.headers.get("Retry-After")
                resp.close()
                time.sleep(min(float(wait), 60) if wait and wait.isdigit() else 2 ** attempt)
                continue
            if 300 <= resp.status_code < 400:
                resp.close()
                raise JiraError(f"Jira respondió con una redirección (HTTP {resp.status_code}); "
                                "revisa la URL (¿falta https:// o el dominio correcto?)",
                                resp.status_code)
            if resp.status_code == 401:
                raise JiraError("Credenciales inválidas (revisa el email y el token)", 401)
            if resp.status_code == 403:
                raise JiraError("La cuenta no tiene permiso para esta operación en Jira", 403)
            if resp.status_code == 404:
                raise JiraError(f"No encontrado en Jira: {urlparse(url).path}", 404)
            if resp.status_code >= 400:
                body = "" if stream else resp.text[:2000]
                log.warning("jira %s %s -> HTTP %s: %s", method, url, resp.status_code, body)
                resp.close()
                raise JiraError(f"Jira respondió con un error (HTTP {resp.status_code})",
                                resp.status_code)
            return resp
        raise JiraError("Jira no respondió tras varios intentos")  # pragma: no cover

    def get(self, path: str, **params) -> Any:
        return self._request("GET", path, params=params or None).json()

    def post(self, path: str, body: dict) -> Any:
        return self._request("POST", path, json=body).json()

    @property
    def api(self) -> str:
        return "/rest/api/3" if self.is_cloud else "/rest/api/2"

    @property
    def is_cloud(self) -> bool:
        if self._cloud is None:
            if self.host.endswith(".atlassian.net"):
                self._cloud = True
            else:
                info = self.get("/rest/api/2/serverInfo")
                self._cloud = info.get("deploymentType") == "Cloud"
        return self._cloud

    # ------------------------------------------------------------------ resources
    def myself(self) -> dict:
        return self.get(f"{self.api}/myself")

    def projects(self) -> list[dict]:
        if self.is_cloud:
            return list(self._paged(f"{self.api}/project/search", "values"))
        return self.get(f"{self.api}/project")

    def project(self, key: str) -> dict:
        return self.get(f"{self.api}/project/{key}")

    def project_statuses(self, key: str) -> list[dict]:
        return self.get(f"{self.api}/project/{key}/statuses")

    def components(self, key: str) -> list[dict]:
        return self.get(f"{self.api}/project/{key}/components")

    def versions(self, key: str) -> list[dict]:
        return self.get(f"{self.api}/project/{key}/versions")

    def fields(self) -> list[dict]:
        return self.get(f"{self.api}/field")

    def count(self, jql: str) -> int:
        if self.is_cloud:
            try:
                return int(self.post(f"{self.api}/search/approximate-count", {"jql": jql})
                           .get("count", 0))
            except JiraError:
                return 0
        return int(self.get(f"{self.api}/search", jql=jql, maxResults=0).get("total", 0))

    def search(self, jql: str, *, expand: str = "changelog") -> Iterator[dict]:
        if self.is_cloud:
            token = None
            while True:
                params = {"jql": jql, "fields": "*all", "expand": expand,
                          "maxResults": self.PAGE}
                if token:
                    params["nextPageToken"] = token
                data = self.get(f"{self.api}/search/jql", **params)
                yield from data.get("issues", [])
                token = data.get("nextPageToken")
                if not token or data.get("isLast"):
                    return
        else:
            start = 0
            while True:
                data = self.get(f"{self.api}/search", jql=jql, fields="*all", expand=expand,
                                startAt=start, maxResults=self.PAGE)
                issues = data.get("issues", [])
                yield from issues
                start += len(issues)
                if not issues or start >= data.get("total", 0):
                    return

    def comments(self, key: str) -> list[dict]:
        return list(self._paged(f"{self.api}/issue/{key}/comment", "comments"))

    def worklogs(self, key: str) -> list[dict]:
        return list(self._paged(f"{self.api}/issue/{key}/worklog", "worklogs"))

    def changelog(self, key: str) -> list[dict]:
        if not self.is_cloud:
            data = self.get(f"{self.api}/issue/{key}", expand="changelog", fields="none")
            return (data.get("changelog") or {}).get("histories", [])
        return list(self._paged(f"{self.api}/issue/{key}/changelog", "values"))

    def remote_links(self, key: str) -> list[dict]:
        return self.get(f"{self.api}/issue/{key}/remotelink")

    def boards(self, project_key: str) -> list[dict]:
        try:
            return list(self._paged("/rest/agile/1.0/board", "values",
                                    projectKeyOrId=project_key))
        except JiraError:
            return []

    def sprints(self, board_id: int) -> list[dict]:
        try:
            return list(self._paged(f"/rest/agile/1.0/board/{board_id}/sprint", "values"))
        except JiraError:  # kanban boards have no sprints
            return []

    def download(self, url: str):
        # Jira Cloud answers attachment downloads with a redirect to its media service; each
        # hop is validated by the guarded adapter and credentials are dropped on host change.
        return self._request("GET", url, stream=True, follow_redirects=True)

    # ------------------------------------------------------------------ paging
    def _paged(self, path: str, items_key: str, **params) -> Iterator[dict]:
        start = 0
        while True:
            data = self.get(path, startAt=start, maxResults=self.PAGE, **params)
            items = data.get(items_key, []) if isinstance(data, dict) else data
            yield from items
            start += len(items)
            total = data.get("total") if isinstance(data, dict) else None
            if not items or data.get("isLast") or (total is not None and start >= total):
                return
