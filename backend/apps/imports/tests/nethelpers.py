"""Network test doubles shared by the netguard, Jira client and webhook tests.

- `FakeDNS` replaces ``socket.getaddrinfo`` (no real DNS lookups in tests).
- `LocalServer` is a tiny HTTP server on 127.0.0.1 that records what it receives.
- `route_public_to(server)` patches urllib3's socket factory so that connecting to the fake
  *public* address actually reaches the local server, while any other address fails. That
  lets tests exercise the real requests/urllib3 stack with public-looking hosts and assert
  which address a connection was pinned to.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"


class FakeDNS:
    """`hosts` maps a name to a list of IPs, or to a callable returning one (to simulate
    DNS rebinding). Unknown names resolve to PUBLIC_IP; IP literals resolve to themselves;
    an empty list means NXDOMAIN."""

    def __init__(self):
        self.hosts: dict = {}
        self.calls: list[str] = []

    def getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        self.calls.append(host)
        ips = self.hosts.get(host)
        if callable(ips):
            ips = ips()
        if ips is None:
            try:
                socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
                ips = [host]
            except OSError:
                ips = [PUBLIC_IP]
        if not ips:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        out = []
        for ip in ips:
            if ":" in ip:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0)))
            else:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)))
        return out


def install_dns(monkeypatch) -> FakeDNS:
    dns = FakeDNS()
    monkeypatch.setattr(socket, "getaddrinfo", dns.getaddrinfo)
    return dns


class LocalServer:
    """`routes[path] = (status, headers_dict, body_bytes)`; unknown paths answer 200 "ok".
    `requests` collects (method, path, headers) for everything received."""

    def __init__(self):
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.requests: list[tuple[str, str, dict]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                server.requests.append((self.command, self.path, dict(self.headers)))
                status, headers, body = server.routes.get(
                    self.path.split("?", 1)[0], (200, {"Content-Type": "application/json"},
                                                 b'{"ok": true}'))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _handle  # noqa: N815

            def log_message(self, *args):  # silence test output
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def route_public_to(monkeypatch, server: LocalServer, public_ips=(PUBLIC_IP, OTHER_PUBLIC_IP)):
    """Connections to `public_ips` reach `server`; anything else is refused. Returns the
    list of (host, port) the HTTP stack tried to connect to."""
    import urllib3.util.connection as u3conn

    attempts: list[tuple[str, int]] = []

    def create_connection(address, timeout=None, source_address=None, socket_options=None):
        attempts.append(address)
        if address[0] not in public_ips:
            raise ConnectionRefusedError(f"test: connection to {address[0]} refused")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout if isinstance(timeout, (int, float)) else 5)
        sock.connect(("127.0.0.1", server.port))
        return sock

    monkeypatch.setattr(u3conn, "create_connection", create_connection)
    return attempts
