# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The local server: one page on http://127.0.0.1:<port>/ and its state on /state.json, for this computer's own
browser only.

It listens on the loopback only (127.0.0.1, and [::1] at the same port so that nobody else answers for localhost), and
checks every request before any work: Host (DNS rebinding), Origin, Sec-Fetch-Site and Sec-Fetch-Dest (other sites
and other local pages, other ports included), method and path. Ordinary reads use GET/HEAD on / and /state.json;
optional advisor actions additionally require a page token and JSON POST with an exact Origin. A refused request
never reads the repository. The repository is read once every MIN_INTERVAL seconds at most, however many pages ask.
Standard library only, safe under -I.
"""
from __future__ import annotations

import errno
import copy
import hmac
import http.server
import json
import socket
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlsplit

from . import TOOL
from . import advisor as ADVISOR
from . import page as PAGE
from . import view as VIEW

HOST = "127.0.0.1"
MIN_INTERVAL = 5.0  # seconds between two readings of the repository, whatever the number of open pages
MAX_CONNECTIONS = 32  # concurrent accepted connections; past this one gets an immediate 503, never a thread
REQUEST_TIMEOUT = 10
PATHS = {"/": ("document",), "/state.json": ("empty", "document")}  # each path, with the Sec-Fetch-Dest it accepts
ADVISOR_PATHS = {"/advisor/status": "GET", "/advisor/preview": "POST", "/advisor/analyze": "POST",
                 "/advisor/automate": "POST", "/advisor/revoke": "POST"}
MAX_ADVISOR_BODY = 196_608
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

    def page(self, lang: str = "en") -> dict:
        """A fresh completed reading, or a neutral shell; HTML never waits for Git."""
        failed = False
        if self._lock.acquire(blocking=False):
            try:
                if self._at is not None and self._clock() - self._at < MIN_INTERVAL:
                    if self._error is None and self._view is not None:
                        return self._view
                    failed = self._error is not None
            finally:
                self._lock.release()
        settings = getattr(self._collector, "settings", None)
        lang = getattr(settings, "lang", lang)
        if failed:
            value = VIEW.error_view(self._now(), "live", "unavailable", lang=lang, tool=TOOL,
                                    repository=getattr(self._collector, "name", ""))
            value["settings"] = settings.public() if settings else {}
            return value
        return VIEW.loading_view(self._now(), lang, TOOL, getattr(self._collector, "name", ""),
                                 settings.public() if settings else {})

    def peek(self) -> dict | None:
        """Copy a completed observation without starting or waiting for Git. Used only on explicit advisor actions."""
        if not self._lock.acquire(blocking=False):
            return None
        try:
            value = self._view if self._error is None else None
        finally:
            self._lock.release()
        # Views are replaced, never mutated after publication. Copy outside the collector lock.
        return copy.deepcopy(value) if value is not None else None

    def refresh_if_idle(self) -> dict | None:
        """An explicitly authorized auto check, at most once per advisor interval. Reuse the normal scan/cache.

        Taking the scan lock is nonblocking: a concurrent browser scan wins and this check is skipped. The
        collector is never used concurrently, its parallel-reading checks and shared deadline remain intact.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._at is None or self._clock() - self._at >= MIN_INTERVAL:
                try:
                    self._view, self._error = self._collector.snapshot(self._now(), "live"), None
                except Exception as exc:
                    self._error = exc
                self._at = self._clock()
            value = self._view if self._error is None else None
        finally:
            self._lock.release()
        return copy.deepcopy(value) if value is not None else None


def refusal(method: str, target: str, headers, port: int) -> str | None:
    """Why a request is refused (a code), or None; checked before any work. Host alone stops DNS rebinding; Origin,
    Sec-Fetch-Site and Sec-Fetch-Dest stop other sites and other local pages (other ports included) and keep the
    state from being loaded as a script, an image or a frame."""
    names = (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")  # the addresses this server holds
    hosts = headers.get_all("Host") or []
    if len(hosts) != 1 or hosts[0] not in names:
        return "host"
    origins = headers.get_all("Origin") or []
    if len(origins) > 1 or (origins and origins[0] not in [f"http://{name}" for name in names]):
        return "origin"
    sites = headers.get_all("Sec-Fetch-Site") or []
    if len(sites) > 1 or (sites and sites[0] not in ("same-origin", "none")):
        return "cross_site"
    path = urlsplit(target).path
    if path in ADVISOR_PATHS:
        if method != ADVISOR_PATHS[path]:
            return "method"
        if urlsplit(target).query or urlsplit(target).fragment:
            return "not_found"
        if (method == "POST" and len(origins) != 1) or (origins and origins[0] != f"http://{hosts[0]}"):
            return "origin"
        destinations = headers.get_all("Sec-Fetch-Dest") or []
        if len(destinations) > 1 or (destinations and destinations[0] != "empty"):
            return "destination"
        return None
    if method not in ("GET", "HEAD"):
        return "method"
    if path not in PATHS:
        return "not_found"
    destinations = headers.get_all("Sec-Fetch-Dest") or []
    if len(destinations) > 1 or (destinations and destinations[0] not in PATHS[path]):
        return "destination"
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    """Ordinary board reads and separately guarded advisor actions, for this computer's own browser only."""

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
            self.close_connection = True
            self._send(STATUS_OF.get(reason, 403), f"refused: {reason}\n".encode("ascii"),
                       "text/plain; charset=utf-8", PAGE.DATA_POLICY, head)
            return
        if urlsplit(self.path).path in ADVISOR_PATHS:
            self._advisor_answer()
            return
        state = urlsplit(self.path).path == "/state.json"
        try:
            view = self.server.snapshots.get() if state else self.server.snapshots.page(self.server.lang)
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
            html = PAGE.render(view, self.server.template, self.server.advisor.token).encode("utf-8") if view is not None else None
        except ValueError:  # a value JSON or UTF-8 cannot hold: never sent
            html = None
        if html is None:
            html = PAGE.render(VIEW.error_view(now_local(), "live", "unavailable", lang=self.server.lang, tool=TOOL),
                               self.server.template, self.server.advisor.token).encode("utf-8")
        self._send(200, html, "text/html; charset=utf-8", self.server.policy, head)

    def _advisor_answer(self) -> None:
        """The only state-changing endpoints. A page token + exact Origin bind consent to this local board."""
        self.close_connection = True
        tokens = self.headers.get_all("X-Flightboard-Advisor") or []
        if len(tokens) != 1 or not tokens[0].isascii() or not hmac.compare_digest(tokens[0], self.server.advisor.token):
            self._send(403, b'{"error":"token_required"}', "application/json; charset=utf-8", PAGE.DATA_POLICY)
            return
        path = urlsplit(self.path).path
        try:
            if self.headers.get_all("Transfer-Encoding"):
                raise ADVISOR.AdvisorError("body_invalid")
            if self.command == "GET":
                if self.headers.get_all("Content-Length") not in (None, ["0"]):
                    raise ADVISOR.AdvisorError("body_invalid")
                value = self.server.advisor.status()
            else:
                lengths = self.headers.get_all("Content-Length") or []
                types = self.headers.get_all("Content-Type") or []
                if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
                        or len(lengths[0]) > 9 or not 1 <= int(lengths[0]) <= MAX_ADVISOR_BODY
                        or types != ["application/json"]):
                    raise ADVISOR.AdvisorError("body_invalid")
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    raise ADVISOR.AdvisorError("body_invalid")

                def object_pairs(pairs):
                    result = {}
                    for key, item in pairs:
                        if key in result:
                            raise ValueError("duplicate key")
                        result[key] = item
                    return result

                def reject_constant(_):
                    raise ValueError("invalid number")

                request = json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs, parse_constant=reject_constant)
                if not isinstance(request, dict):
                    raise ADVISOR.AdvisorError("body_invalid")
                actions = {"/advisor/preview": self.server.advisor.preview, "/advisor/analyze": self.server.advisor.analyze,
                           "/advisor/automate": self.server.advisor.automate,
                           "/advisor/revoke": lambda _: self.server.advisor.revoke()}
                value = actions[path](request)
            self._send(200, PAGE.state_json(value), "application/json; charset=utf-8", PAGE.DATA_POLICY)
        except ADVISOR.AdvisorError as exc:
            self._send(exc.status, PAGE.state_json({"error": exc.code}), "application/json; charset=utf-8", PAGE.DATA_POLICY)
        except (ValueError, TypeError, RecursionError, OSError, AttributeError):
            self._send(400, b'{"error":"body_invalid"}', "application/json; charset=utf-8", PAGE.DATA_POLICY)

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _answer


class Server(http.server.ThreadingHTTPServer):
    """A threaded server on the loopback. No address reuse: on Windows another program could share the port."""

    daemon_threads = True
    allow_reuse_address = False
    allow_reuse_port = False
    capacity = threading.BoundedSemaphore(MAX_CONNECTIONS)  # an idle flood never spawns threads without end

    def server_close(self) -> None:
        if getattr(self, "owns_advisor", False):
            self.advisor.close()
        super().server_close()

    def process_request(self, request, client_address) -> None:
        if not self.capacity.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class Server6(Server):
    """The same server on [::1]: a browser asked for localhost tries ::1 first, so the board holds that address too,
    and no other program can answer there in its place."""

    address_family = socket.AF_INET6


def make_server(snapshots: Snapshots, template: str, port: int, host: str = HOST, lang: str = "en",
                advisor: ADVISOR.Advisor | None = None) -> Server:
    server = (Server6 if ":" in host else Server)((host, port), Handler)
    server.snapshots = snapshots
    server.template = template
    server.policy = PAGE.policy(template)
    server.lang = lang
    server.owns_advisor = advisor is None
    server.advisor = advisor or ADVISOR.Advisor(getattr(snapshots._collector, "root", None), snapshots.peek,
                                               refresh_snapshot=snapshots.refresh_if_idle)
    return server


def make_servers(snapshots: Snapshots, template: str, port: int, lang: str = "en",
                 advisor: ADVISOR.Advisor | None = None) -> list[Server]:
    """The board on 127.0.0.1, and on [::1] at the same port when this computer has IPv6. A port taken on either is
    an error: the page must never be served by someone else at the address the owner opens."""
    first = make_server(snapshots, template, port, lang=lang, advisor=advisor)
    try:
        second = make_server(snapshots, template, first.server_address[1], "::1", lang, first.advisor)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, "winerror", None) in (10013, 10048):
            first.server_close()
            raise
        return [first]  # no IPv6 here: nobody can listen on ::1 either
    return [first, second]
