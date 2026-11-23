"""Outbound HTTP guard against SSRF and DNS rebinding.

Used by the Jira importer and by automation webhooks. Every request made through
`guarded_session()` is checked right before connecting:

1. the URL must be http(s) with a host;
2. the host is resolved once (``getaddrinfo``) and *every* address must be public
   (not private, loopback, link-local, reserved, multicast, unspecified, shared/CGNAT...),
   unless the caller allows private networks;
3. the connection is pinned to the validated address, so a second DNS lookup by the HTTP
   stack cannot be steered elsewhere (DNS rebinding). The ``Host`` header, TLS SNI and
   certificate verification keep using the original hostname.

Redirects are validated hop by hop because each hop goes through the same adapter.
Proxies and ``.netrc`` from the environment are ignored (``trust_env = False``) so the
pinning cannot be bypassed.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

__all__ = [
    "UnsafeURL", "is_public_ip", "resolve_public", "check_url", "GuardedAdapter",
    "guarded_session",
]


class UnsafeURL(Exception):
    """The URL is malformed or points to a forbidden address. `message` is user-facing."""

    def __init__(self, message: str, *, internal: bool = False):
        super().__init__(message)
        self.message = message
        self.internal = internal  # True when rejected because the address is not public


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped or ip.sixtofour
        if mapped is not None:
            return is_public_ip(mapped)
        if ip.teredo is not None:
            return all(is_public_ip(x) for x in ip.teredo)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified or not ip.is_global
    )


def _parse(url: str):
    try:
        parts = urlsplit(url or "")
        port = parts.port
    except ValueError as e:
        raise UnsafeURL("La URL no es válida") from e
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURL("La URL debe ser http:// o https://")
    return parts, port or (443 if parts.scheme == "https" else 80)


def resolve_public(host: str, port: int, *, allow_private: bool = False) -> str:
    """Resolve `host` and return the address to connect to. Raises UnsafeURL if the name
    does not resolve or any of its addresses is non-public (unless `allow_private`)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        raise UnsafeURL(f"No se pudo resolver {host}") from e
    addrs: list[str] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]  # drop IPv6 scope id
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as e:
            raise UnsafeURL(f"No se pudo resolver {host}") from e
        if not allow_private and not is_public_ip(ip):
            raise UnsafeURL(f"{host} apunta a una dirección interna o reservada", internal=True)
        if raw not in addrs:
            addrs.append(raw)
    if not addrs:
        raise UnsafeURL(f"No se pudo resolver {host}")
    return addrs[0]


def check_url(url: str, *, allow_private: bool = False) -> str:
    """Validate `url` (scheme, host, resolved addresses). Returns the pinned address."""
    parts, port = _parse(url)
    return resolve_public(parts.hostname, port, allow_private=allow_private)


class GuardedAdapter(HTTPAdapter):
    """HTTPAdapter that validates the destination of every request and pins the
    connection to the validated IP address."""

    def __init__(self, *, allow_private: bool = False, **kw):
        self.allow_private = allow_private
        super().__init__(**kw)

    def send(self, request, *args, **kwargs):
        parts, port = _parse(request.url)
        ip = resolve_public(parts.hostname, port, allow_private=self.allow_private)
        request._gestiona_pin = (parts.hostname, ip)
        # http.client would otherwise derive Host from the (pinned) connection address
        request.headers["Host"] = parts.netloc.rsplit("@", 1)[-1]
        return super().send(request, *args, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert)
        pin = getattr(request, "_gestiona_pin", None)
        if pin is None:  # pragma: no cover - send() always sets it
            raise UnsafeURL("Petición sin validar")
        hostname, ip = pin
        host_params["host"] = ip
        if host_params.get("scheme") == "https":
            pool_kwargs["server_hostname"] = hostname  # SNI
            pool_kwargs["assert_hostname"] = hostname  # certificate check
        return host_params, pool_kwargs


def guarded_session(*, allow_private: bool = False, max_redirects: int = 5) -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # no env proxies / netrc: they would bypass the pinning
    session.max_redirects = max_redirects
    adapter = GuardedAdapter(allow_private=allow_private)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
