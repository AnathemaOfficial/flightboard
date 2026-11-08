# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The local server: one page on http://127.0.0.1:<port>/ and its state on /state.json, for this computer's own
browser only.

It listens on the loopback only (127.0.0.1, and [::1] at the same port so that nobody else answers for localhost), and
checks every request before any work: Host (DNS rebinding), Origin, Sec-Fetch-Site and Sec-Fetch-Dest (other sites
and other local pages, other ports included), method (GET and HEAD) and path (/ and /state.json). A refused request
never reads the repository. The repository is read once every MIN_INTERVAL seconds at most, however many pages ask.
Standard library only, safe under -I.
"""
from __future__ import annotations

import errno
import http.server
import socket
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from . import TOOL
from . import page as PAGE
from . import view as VIEW

HOST = "127.0.0.1"
MIN_INTERVAL = 5.0  # seconds between two readings of the repository, whatever the number of open pages
REQUEST_TIMEOUT = 10
PATHS = {"/": ("document",), "/state.json": ("empty", "document")}  # each path, with the Sec-Fetch-Dest it accepts
COMMON_HEADERS = (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                  ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                  ("Cross-Origin-Resource-Policy", "same-origin"), ("Cross-Origin-Opener-Policy", "same-origin"))
STATUS_OF = {"method": 405, "not_found": 404}


def now_local() -> datetime:
    return datetime.now().astimezone()


class Snapshots:
    """The state the server hands out: one reading of the repository at most every MIN_INTERVAL seconds, counted from
    the end of the last one, however many pages ask at once. A failed reading counts too: its error is given back
    until the interval ends, so a broken repository is never read in a loop."""

    def __init__(self, collector, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = now_local) -> None:
        self._collector = collector
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._view: dict | None = None
        self._error: Exception | None = None
        self._at: float | None = None

    def get(self) -> dict:
        with self._lock:
            if self._at is None or self._clock() - self._at >= MIN_INTERVAL:
                try:
                    self._view, self._error = self._collector.snapshot(self._now(), "live"), None
                except Exception as exc:  # kept and given back until the interval ends
                    self._error = exc
                self._at = self._clock()
            if self._error is not None:
                raise self._error
            return self._view


def refusal(method: str, target: str, headers, port: int) -> str | None:
    """Why a request is refused (a code), or None; checked before any work. Host alone stops DNS rebinding; Origin,
    Sec-Fetch-Site and Sec-Fetch-Dest stop other sites and other local pages (other ports included) and keep the
    state from being loaded as a script, an image or a frame."""
    hosts = headers.get_all("Host") or []
    if len(hosts) != 1 or hosts[0] not in (f"127.0.0.1:{port}", f"localhost:{port}"):
        return "host"
    origins = headers.get_all("Origin") or []
    if len(origins) > 1 or (origins and origins[0] not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")):
        return "origin"
    sites = headers.get_all("Sec-Fetch-Site") or []
    if len(sites) > 1 or (sites and sites[0] not in ("same-origin", "none")):
        return "cross_site"
    if method not in ("GET", "HEAD"):
        return "method"
    path = urlsplit(target).path
    if path not in PATHS:
        return "not_found"
    destinations = headers.get_all("Sec-Fetch-Dest") or []
    if len(destinations) > 1 or (destinations and destinations[0] not in PATHS[path]):
        return "destination"
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    """GET and HEAD on / and /state.json, for this computer's own browser only."""

    server_version = "flightboard"
    sys_version = ""
    timeout = REQUEST_TIMEOUT

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the name comes from the base class
        return  # quiet: a request line may carry anything, and nothing here is worth a log

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """The standard library's own errors (bad request line, header too long…), without echoing anything."""
        self.close_connection = True
        self._send(code, b"refused\n", "text/plain; charset=utf-8", PAGE.DATA_POLICY, self.command == "HEAD")

    def _send(self, status: int, body: bytes, content_type: str, csp: str, head: bool = False) -> None:
        self.send_response(status)
        for key, value in (("Content-Type", content_type), ("Content-Length", str(len(body))),
                           ("Content-Security-Policy", csp), *COMMON_HEADERS):
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _answer(self) -> None:
        head = self.command == "HEAD"
        reason = refusal(self.command, self.path, self.headers, self.server.server_address[1])
        if reason is not None:
            self._send(STATUS_OF.get(reason, 403), f"refused: {reason}\n".encode("ascii"),
                       "text/plain; charset=utf-8", PAGE.DATA_POLICY, head)
            return
        state = urlsplit(self.path).path == "/state.json"
        try:
            view = self.server.snapshots.get()
            body = PAGE.state_json(view) if state else None
        except Exception as exc:  # the collector degrades on its own; this is the last guard of a request
            print(f"reading impossible: {type(exc).__name__}", file=sys.stderr)
            view = body = None
        if state:
            if body is None:
                self._send(503, b'{"error":"unreadable"}', "application/json; charset=utf-8", PAGE.DATA_POLICY, head)
            else:
                self._send(200, body, "application/json; charset=utf-8", PAGE.DATA_POLICY, head)
            return
        try:  # encoded here too: a text UTF-8 cannot hold (a lone surrogate) gets the error page, never no answer
            html = PAGE.render(view, self.server.template).encode("utf-8") if view is not None else None
        except ValueError:  # a value JSON or UTF-8 cannot hold: never sent
            html = None
        if html is None:
            html = PAGE.render(VIEW.error_view(now_local(), "live", "unavailable", lang=self.server.lang, tool=TOOL),
                               self.server.template).encode("utf-8")
        self._send(200, html, "text/html; charset=utf-8", self.server.policy, head)

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _answer


class Server(http.server.ThreadingHTTPServer):
    """A threaded server on the loopback. No address reuse: on Windows another program could share the port."""

    daemon_threads = True
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class Server6(Server):
    """The same server on [::1]: a browser asked for localhost tries ::1 first, so the board holds that address too,
    and no other program can answer there in its place."""

    address_family = socket.AF_INET6


def make_server(snapshots: Snapshots, template: str, port: int, host: str = HOST, lang: str = "en") -> Server:
    server = (Server6 if ":" in host else Server)((host, port), Handler)
    server.snapshots = snapshots
    server.template = template
    server.policy = PAGE.policy(template)
    server.lang = lang
    return server


def make_servers(snapshots: Snapshots, template: str, port: int, lang: str = "en") -> list[Server]:
    """The board on 127.0.0.1, and on [::1] at the same port when this computer has IPv6. A port taken on either is
    an error: the page must never be served by someone else at the address the owner opens."""
    first = make_server(snapshots, template, port, lang=lang)
    try:
        second = make_server(snapshots, template, first.server_address[1], "::1", lang)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, "winerror", None) in (10013, 10048):
            first.server_close()
            raise
        return [first]  # no IPv6 here: nobody can listen on ::1 either
    return [first, second]
