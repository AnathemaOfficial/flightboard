# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the page, the local server and the command line of flightboard.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import base64
import builtins
import contextlib
import copy
import email.message
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, HOSTILE, NOW, Repository, load, roadmap_settings

page = load("page")
server = load("server")
cli = load("cli")
collector_module = load("collector")
view_module = load("view")
Settings = load("config").Settings

DATA_BLOCK = re.compile(r'<script type="application/json" id="flightboard-data">(.*?)</script>', re.S)
CODE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
# Fields the page's script reads from the view; a renamed key must fail here, not in the browser.
FIELDS = {
    "sessions": ("id", "name", "kind", "branch", "head", "head_date", "subject", "created", "ahead", "behind",
                 "modified", "untracked", "conflicted", "kept", "last_activity", "activity", "stage", "operation",
                 "advice", "ledger", "reason", "reason_text", "changes", "decisions", "sections", "tasks", "inferred",
                 "commits", "pushed", "hidden_changes", "files_read", "files_issue", "files_issue_text", "gone"),
    "changes": ("task", "title", "from", "to", "new", "removed", "uncommitted", "back"),
    "events": ("at", "task", "title", "from", "to", "where", "sha", "subject", "uncommitted", "approx"),
    "moves": ("at", "sha", "via", "approx"),
    "milestones": ("id", "title", "track", "total", "active", "counts", "unmerged", "planned", "forecast", "gap"),
    "kpis": ("active", "active_10", "done_main", "done_main_10", "done_live", "done_live_10", "review_live",
             "review_live_10", "progress_live", "blocked_live", "active_live", "active_live_10"),
    "waiting": ("kind", "verb", "text", "since"),
    "history": ("at", "sha", "via", "counts", "counts_10", "active", "active_10"),
    "daily": ("day", "done_main", "review_main", "done_live", "review_live"),
    "main": ("state", "reason_text", "ref", "head", "date", "subject", "updated_at", "note_text", "valid", "error"),
    "ledger": ("kind", "releases", "missing"),
    "yours": ("decisions", "tasks"),
}


def embedded(html: str) -> dict:
    match = DATA_BLOCK.search(html)
    if match is None:
        raise AssertionError("data block missing")
    return json.loads(match.group(1))


def read_all(raw: socket.socket) -> bytes:
    """Everything the server sends before it closes the connection: one recv may hold only the headers, the body
    coming in a second write. A reset after the answer (the server closed with request bytes still unread) ends the
    reading too."""
    chunks = []
    while True:
        try:
            chunk = raw.recv(65536)
        except (ConnectionResetError, ConnectionAbortedError):
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def headers(**values: str) -> email.message.Message:
    message = email.message.Message()
    for key, value in values.items():
        message[key.replace("_", "-")] = value
    return message


@unittest.skipIf(GIT is None, "git absent")
class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Repository()
        cls.base_view = collector_module.Collector(cls.repo.root, roadmap_settings()).snapshot(NOW)
        cls.template = page.template()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def view(self) -> dict:
        return copy.deepcopy(self.base_view)

    def page(self, view: dict | None = None) -> str:
        return page.render(view or self.view(), self.template)

    def test_the_view_round_trips_through_the_page_and_the_json(self) -> None:
        view = self.view()
        self.assertEqual(embedded(self.page(view)), json.loads(json.dumps(view)))
        state = json.loads(page.state_json(view), parse_constant=lambda name: self.fail(name))
        self.assertEqual(state, json.loads(json.dumps(view)))
        with self.assertRaises(ValueError):
            page.state_json({"x": float("nan")})
        with self.assertRaises(ValueError):
            page.render({"x": float("inf")}, self.template)

    def test_only_the_page_script_may_run(self) -> None:
        html = self.page()
        meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        scripts = CODE_SCRIPT.findall(html)
        self.assertEqual(len(scripts), 1)
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode("ascii")
        header = page.policy(self.template)
        for policy in (meta, header):
            with self.subTest(policy=policy[:40]):
                for part in ("default-src 'none'", "connect-src 'self'", "base-uri 'none'", "form-action 'none'",
                             "require-trusted-types-for 'script'", "trusted-types 'none'",
                             f"script-src 'sha256-{digest}'"):
                    self.assertIn(part, policy)
                self.assertNotIn("img-src", policy)
        self.assertIn("frame-ancestors 'none'", header)
        for marker in ("__SCRIPT_HASH__", "__FLIGHTBOARD_JSON__"):
            self.assertNotIn(marker, html)

    def test_source_text_cannot_leave_the_data_block(self) -> None:
        view = self.view()
        view["sessions"][0]["subject"] = HOSTILE
        view["events"][0]["title"] = HOSTILE
        view["waiting"][0]["text"] = HOSTILE
        view["i18n"]["messages"]["page.waiting"] = HOSTILE
        html = self.page(view)
        self.assertEqual(html.count("</script>"), 2)
        self.assertNotIn("<img src=x", html)
        self.assertEqual(embedded(html)["waiting"][0]["text"], HOSTILE)

    def test_unicode_line_separators_are_escaped(self) -> None:
        view = self.view()
        view["resume"] = "before\u2028after\u2029end"
        html = self.page(view)
        self.assertNotIn("\u2028", html)
        self.assertEqual(embedded(html)["resume"], "before\u2028after\u2029end")

    def test_the_page_talks_only_to_its_own_server(self) -> None:
        template = self.template
        self.assertIsNone(re.search(r"(?i)\b(?:src|href|action|srcset)\s*=\s*[\"']?\s*(?:[a-z]+:)?//", template))
        self.assertEqual(re.findall(r"https?://[^\s'\"]*", template), [SVG_NAMESPACE])
        self.assertEqual(template.count("fetch("), 1)
        self.assertRegex(template, r"fetch\('state\.json',")
        self.assertRegex(template, r"const polling = data\.mode === 'live' && \(location\.protocol === 'http:'")
        for forbidden in ("@import", "url(", "<link", "<iframe", "XMLHttpRequest", "eval(", "new Function",
                          "WebSocket", "sendBeacon", "window.open", "import(", "location.href", "location.assign",
                          "github.com", "sessionStorage", "document.cookie", "DOMParser", "setTimeout('",
                          'setTimeout("', "setInterval('", 'setInterval("', " style=", "'style'", "<a ", "srcdoc"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, template)
        self.assertIsNone(re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|srcdoc", template))
        self.assertEqual(re.findall(r"localStorage\.\w+\(([^,)]+)", template), ["SEEN_KEY", "SEEN_KEY"])
        self.assertEqual(template.count("__FLIGHTBOARD_JSON__"), 1)

    def test_dark_mode_reduced_motion_and_own_keys(self) -> None:
        self.assertIn("@media(prefers-color-scheme:dark)", self.template)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.template)
        self.assertIn("Object.hasOwn", self.template)

    def test_the_page_script_and_the_view_agree(self) -> None:
        html = self.page()
        script = CODE_SCRIPT.search(html).group(1)
        for element in re.findall(r"\$\('([\w-]+)'\)", script):
            with self.subTest(element=element):
                self.assertIn(f'id="{element}"', html)
        view = self.view()
        groups = {"sessions": view["sessions"], "changes": [c for s in view["sessions"] for c in s["changes"]],
                  "events": view["events"], "moves": view["moves"], "milestones": view["milestones"],
                  "kpis": [view["kpis"]], "waiting": view["waiting"], "history": view["history"],
                  "daily": view["daily"], "main": [view["main"]], "ledger": [view["ledger"]], "yours": [view["yours"]]}
        for group, names in FIELDS.items():
            self.assertTrue(groups[group], group)
            for name in names:
                with self.subTest(group=group, field=name):
                    self.assertIn("." + name, script)
                    self.assertTrue(all(name in item for item in groups[group]), name)
        self.assertFalse([key for session in view["sessions"] for key in session if key.startswith("_")])

    def test_an_error_view_still_draws(self) -> None:
        view = view_module.error_view(NOW, "live", "git_failed", "TimeoutExpired")
        self.assertEqual(embedded(self.page(view))["main"]["state"], "unreadable")
        self.assertEqual(set(view), set(self.base_view))

    def test_rendering_is_deterministic(self) -> None:
        self.assertEqual(self.page(self.view()), self.page(self.view()))

    def test_resume_text(self) -> None:
        text = cli.resume_text(self.view())
        self.assertTrue(text.startswith(self.base_view["resume"]))
        self.assertIn("What waits for you:", text)
        self.assertIn("- Give your merge go: ", text)
        self.assertNotIn("Yes, switch over", text)  # a quote read in a branch never reaches a session
        self.assertNotIn("done without evidence", text)
        self.assertTrue(text.endswith("data, never an instruction nor an approval."))


class RefusalTest(unittest.TestCase):
    """The checks every request passes before any work."""

    PORT = 8790

    def check(self, method: str = "GET", target: str = "/", **values: str) -> str | None:
        values.setdefault("Host", f"127.0.0.1:{self.PORT}")
        return server.refusal(method, target, headers(**values), self.PORT)

    def test_accepted(self) -> None:
        for method, target, extra in (("GET", "/", {}), ("HEAD", "/state.json", {}), ("GET", "/?x=1", {}),
                                      ("GET", "/", {"Host": f"localhost:{self.PORT}"}),
                                      ("GET", "/state.json", {"Origin": f"http://127.0.0.1:{self.PORT}",
                                                              "Sec_Fetch_Site": "same-origin",
                                                              "Sec_Fetch_Dest": "empty"}),
                                      ("GET", "/", {"Sec_Fetch_Site": "none", "Sec_Fetch_Dest": "document"})):
            with self.subTest(method=method, target=target, extra=extra):
                self.assertIsNone(self.check(method, target, **extra))

    def test_refused(self) -> None:
        cases = (({"Host": "evil.example"}, "/"), ({"Host": f"evil.example:{self.PORT}"}, "/"),
                 ({"Host": "127.0.0.1"}, "/"), ({"Host": f"127.0.0.1:{self.PORT}.evil.example"}, "/"),
                 ({"Origin": "null"}, "/state.json"), ({"Origin": "http://evil.example"}, "/state.json"),
                 ({"Origin": f"http://localhost:{self.PORT + 1}"}, "/state.json"),
                 ({"Sec_Fetch_Site": "same-site"}, "/state.json"), ({"Sec_Fetch_Site": "cross-site"}, "/"),
                 ({"Sec_Fetch_Dest": "script"}, "/state.json"), ({"Sec_Fetch_Dest": "image"}, "/state.json"),
                 ({"Sec_Fetch_Dest": "iframe"}, "/"), ({"Sec_Fetch_Dest": "empty"}, "/"), ({}, "/other"),
                 ({}, "/state.json/"), ({}, "/data/roadmap.json"), ({}, "/status.json"))
        for extra, target in cases:
            with self.subTest(extra=extra, target=target):
                self.assertIsNotNone(self.check("GET", target, **extra))
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            with self.subTest(method=method):
                self.assertEqual(self.check(method, "/state.json"), "method")
        message = headers(Host=f"127.0.0.1:{self.PORT}")
        message["Host"] = "evil.example"
        self.assertEqual(server.refusal("GET", "/", message, self.PORT), "host")
        self.assertEqual(server.refusal("GET", "/", headers(), self.PORT), "host")


class FakeCollector:
    def __init__(self, view: dict | None = None, error: Exception | None = None, delay: float = 0.0) -> None:
        self.calls = 0
        self.view = view or view_module.error_view(NOW, "live", "read_failed", "test")
        self.error = error
        self.delay = delay

    def snapshot(self, now, mode="live") -> dict:
        self.calls += 1
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {**self.view, "mode": mode}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class SnapshotsTest(unittest.TestCase):
    def test_the_repository_is_read_at_most_once_per_interval(self) -> None:
        clock, collector = Clock(), FakeCollector()
        snapshots = server.Snapshots(collector, clock=clock)
        for moment in (100.0, 101.0, 104.9):
            clock.now = moment
            snapshots.get()
        self.assertEqual(collector.calls, 1)
        clock.now = 105.1
        snapshots.get()
        self.assertEqual(collector.calls, 2)

    def test_a_failed_reading_is_not_repeated_within_the_interval(self) -> None:
        clock, collector = Clock(), FakeCollector(error=RuntimeError("failure"))
        snapshots = server.Snapshots(collector, clock=clock)
        for moment in (100.0, 101.0, 104.0):
            clock.now = moment
            with self.assertRaises(RuntimeError):
                snapshots.get()
        self.assertEqual(collector.calls, 1)
        clock.now = 106.0
        with self.assertRaises(RuntimeError):
            snapshots.get()
        self.assertEqual(collector.calls, 2)

    def test_the_interval_counts_from_the_end_of_a_slow_reading(self) -> None:
        clock = Clock()
        collector = FakeCollector()
        real = collector.snapshot

        def slow(now, mode="live"):
            clock.now += 6.0  # a reading longer than the interval
            return real(now, mode)

        collector.snapshot = slow
        snapshots = server.Snapshots(collector, clock=clock)
        snapshots.get()
        clock.now += 1.0
        snapshots.get()
        self.assertEqual(collector.calls, 1)

    def test_concurrent_requests_cause_one_reading(self) -> None:
        collector = FakeCollector(delay=0.2)
        snapshots = server.Snapshots(collector)
        threads = [threading.Thread(target=snapshots.get) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(collector.calls, 1)


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.collector = FakeCollector()
        cls.template = page.template()
        cls.server = server.make_server(server.Snapshots(cls.collector), cls.template, 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def request(self, path: str = "/", method: str = "GET", host: str | None = None, extra: dict | None = None,
                port: int | None = None) -> tuple[int, dict, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=10)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host if host is not None else f"127.0.0.1:{port or self.port}")
            for key, value in (extra or {}).items():
                connection.putheader(key, value)
            connection.endheaders()
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def assert_common_headers(self, found: dict) -> None:
        for key, value in (("x-content-type-options", "nosniff"), ("cache-control", "no-store"),
                           ("referrer-policy", "no-referrer"), ("x-frame-options", "DENY"),
                           ("cross-origin-resource-policy", "same-origin")):
            self.assertEqual(found.get(key), value, key)
        self.assertIn("frame-ancestors 'none'", found["content-security-policy"])
        self.assertFalse([key for key in found if key.startswith("access-control")])

    def test_it_listens_on_the_loopback_only(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_the_page(self) -> None:
        status, found, body = self.request("/")
        self.assertEqual(status, 200)
        self.assert_common_headers(found)
        self.assertTrue(found["content-type"].startswith("text/html"))
        self.assertEqual(found["content-security-policy"], page.policy(self.template))
        self.assertNotIn("Python", found.get("server", ""))
        self.assertEqual(embedded(body.decode("utf-8"))["mode"], "live")

    def test_a_text_utf8_cannot_hold_still_gets_a_page(self) -> None:
        """A lone surrogate read in the repository left / unanswered: the page is encoded where its failure is
        caught, and the error page is sent instead."""
        view = {**view_module.error_view(NOW, "live", "read_failed", "test"), "repository": "\ud800"}
        other = server.make_server(server.Snapshots(FakeCollector(view)), self.template, 0)
        thread = threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            status, _, body = self.request("/", port=other.server_address[1])
        finally:
            other.shutdown()
            other.server_close()
            thread.join(5)
        self.assertEqual(status, 200)
        self.assertNotIn("\ud800", json.dumps(embedded(body.decode("utf-8"))))

    def test_the_state(self) -> None:
        status, found, body = self.request("/state.json", extra={"Sec-Fetch-Site": "same-origin",
                                                                 "Sec-Fetch-Dest": "empty"})
        self.assertEqual(status, 200)
        self.assert_common_headers(found)
        self.assertEqual(found["content-type"], "application/json; charset=utf-8")
        self.assertIn("sandbox", found["content-security-policy"])
        self.assertEqual(json.loads(body)["main"]["reason"], "read_failed")

    def test_refused_requests_never_read_the_repository(self) -> None:
        before = self.collector.calls
        for host, extra, path, method in (("evil.example", {}, "/state.json", "GET"),
                                          (None, {"Origin": "null"}, "/", "GET"),
                                          (None, {"Sec-Fetch-Site": "cross-site"}, "/state.json", "GET"),
                                          (None, {"Sec-Fetch-Dest": "script"}, "/state.json", "GET"),
                                          (None, {}, "/other", "GET"), (None, {}, "/state.json", "POST"),
                                          (None, {}, "/state.json", "OPTIONS")):
            with self.subTest(host=host, extra=extra, path=path, method=method):
                status, found, body = self.request(path, method, host, extra)
                self.assertIn(status, (403, 404, 405))
                self.assert_common_headers(found)
                self.assertEqual(found["content-type"], "text/plain; charset=utf-8")
                self.assertNotIn(b"main", body)
        self.assertEqual(self.collector.calls, before)

    def test_a_malformed_request_echoes_nothing(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            raw.sendall(b"GET /<script>alert(1)</script> HTTP/9.9\r\nHost: x\r\n\r\n")
            answer = read_all(raw)
        self.assertNotIn(b"<script>", answer)
        # a fixed body. Python up to 3.14.0 answers like HTTP/0.9, the body alone; later 3.14 releases send a status
        # line and headers first, ours included
        self.assertTrue(answer.endswith(b"refused\n"), answer[-300:])
        if answer != b"refused\n":
            self.assertIn(b"nosniff", answer)
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            raw.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n" + b"X-Long: " + b"a" * 70000 + b"\r\n\r\n")
            answer = read_all(raw)
        self.assertIn(b"nosniff", answer)
        self.assertNotIn(b"aaaa", answer)

    def test_an_idle_connection_does_not_delay_others(self) -> None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5):
            started = time.monotonic()
            status, _, _ = self.request("/state.json")
            self.assertEqual(status, 200)
            self.assertLess(time.monotonic() - started, 2.0)

    def test_head_answers_headers_only(self) -> None:
        status, found, body = self.request("/state.json", method="HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(found["content-length"]), 0)

    def test_a_second_server_cannot_take_the_port(self) -> None:
        with self.assertRaises(OSError):
            server.make_server(server.Snapshots(FakeCollector()), self.template, self.port)

    def test_localhost_on_ipv6_is_held_too(self) -> None:
        servers = server.make_servers(server.Snapshots(FakeCollector()), self.template, 0)
        try:
            if len(servers) < 2:
                self.skipTest("no IPv6 on this computer")
            port = servers[0].server_address[1]
            self.assertEqual(servers[1].server_address[:2], ("::1", port))
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as other:
                with self.assertRaises(OSError):
                    other.bind(("::1", port))
        finally:
            for found in servers:
                found.server_close()

    def test_a_failing_reading_answers_an_error(self) -> None:
        failing = server.make_server(server.Snapshots(FakeCollector(error=RuntimeError("failure"))), self.template, 0)
        thread = threading.Thread(target=failing.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            port = failing.server_address[1]
            with contextlib.redirect_stderr(io.StringIO()):
                status, _, body = self.request("/state.json", port=port)
                page_status, _, html = self.request("/", port=port)
        finally:
            failing.shutdown()
            failing.server_close()
            thread.join(5)
        self.assertEqual(status, 503)
        self.assertNotIn(b"failure", body)
        self.assertEqual(page_status, 200)
        self.assertEqual(embedded(html.decode("utf-8"))["main"]["state"], "unreadable")


class CommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._cache = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._cache.cleanup)
        self.cache = Path(self._cache.name).resolve() / "flightboard"
        patcher = mock.patch.object(cli, "cache_folder", return_value=self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, argv: list[str], root: Path | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv, root=root or Path(self._cache.name), now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_usage_errors(self) -> None:
        for argv in (["--port"], ["--port", "80"], ["--port", "abc"], ["--port", "70000"], ["--port", "８７９０"],
                     ["--output", "x.html"], ["--snapshot", "--port", "8790"], ["--unknown"],
                     ["--snapshot", "--snapshot"], ["--port", "8790", "--port", "8791"], ["8790"],
                     ["--resume", "--snapshot"], ["--resume", "--port", "8790"], ["--lang", "de"],
                     ["--ledger", "other"], ["--ledger-path", "tasks.toml"], ["--ledger", "tasks", "--ledger-path",
                                                                               "../x.toml"],
                     ["--main", "a..b"], ["--remote", "a/b"], ["--worktrees", "../x"], ["--worktrees", "C" + ":/x"],
                     ["--kept", "a/../b"], ["--stale-days", "0"], ["--active-minutes", "x"],
                     ["--active-minutes", "200", "--recent-minutes", "100"], ["--repo"], ["--export"],
                     ["--write", "x.html"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(argv)[0], 2)

    def test_a_busy_port_is_an_error(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            if port < 1024:
                self.skipTest("ephemeral port out of range")
            code, _, err = self.run_main(["--port", str(port)])
        self.assertEqual(code, 1)
        self.assertIn("port", err)

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_snapshot_outside_the_repository_and_the_resume(self) -> None:
        repo = Repository()
        self.addCleanup(repo.close)
        code, out, _ = self.run_main(["--snapshot", "--ledger", "roadmap"], root=repo.root)
        self.assertEqual(code, 0, out)
        written = Path(json.loads(out)["page"])
        self.assertEqual(written.parent, self.cache.resolve())
        self.assertTrue(written.name.startswith("demo-") and written.name.endswith(".html"))
        data = embedded(written.read_text(encoding="utf-8"))
        self.assertEqual((data["mode"], len(data["sessions"])), ("snapshot", 10))
        for argv in (["--snapshot", "--output", str(repo.root / "out.html")],
                     ["--snapshot", "--output", str(repo.root / ".claude" / "x.html")],
                     ["--snapshot", "--output", str(self.cache / "x.txt")],
                     ["--snapshot", "--output", str(self.cache / "aux.html")],
                     ["--snapshot", "--output", str(self.cache / "missing" / "x.html")]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(argv, root=repo.root)[0], 2)
        self.assertFalse((repo.root / "out.html").exists())
        chosen = Path(self._cache.name).resolve() / "board.html"
        self.assertEqual(self.run_main(["--snapshot", "--output", str(chosen)], root=repo.root)[0], 0)
        self.assertTrue(chosen.is_file())
        code, out, _ = self.run_main(["--resume"], root=repo.root)
        self.assertEqual(code, 0)
        self.assertIn("What waits for you:", out)
        code, out, _ = self.run_main(["--resume"], root=repo.a)  # from a session's own folder
        self.assertEqual(code, 0)
        self.assertIn("What waits for you:", out)
        code, out, _ = self.run_main(["--resume", "--lang", "fr"], root=repo.root)
        self.assertIn("Ce qui t'attend :", out)

    @unittest.skipIf(GIT is None, "git absent")
    def test_an_output_folder_is_resolved_and_never_inside_the_repository(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        from tests.test_files import make_link
        elsewhere = Path(self._cache.name).resolve() / "boards"
        elsewhere.mkdir()
        named = Path(self._cache.name).resolve() / "named"
        if not make_link(elsewhere, named):
            self.skipTest("this system does not let the test make a link")
        # a folder the owner names may be reached through a link (macOS's /tmp is one): it is resolved
        self.assertEqual(self.run_main(["--snapshot", "--output", str(named / "board.html")], root=repo.root)[0], 0)
        self.assertTrue((elsewhere / "board.html").is_file())
        back = Path(self._cache.name).resolve() / "back"
        if make_link(repo.root, back):  # a link that leads back into the repository
            self.assertEqual(self.run_main(["--snapshot", "--output", str(back / "x.html")], root=repo.root)[0], 2)
            self.assertFalse((repo.root / "x.html").exists())

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_snapshot_from_a_subfolder_stays_outside_the_repository(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        sub = repo.root / "docs" / "notes"
        sub.mkdir(parents=True)
        inner = repo.m / "src"
        inner.mkdir(parents=True, exist_ok=True)
        for start in (sub, inner):  # a folder of the main checkout, and one of a session's worktree
            for wanted in (start / ".." / "out.html", repo.root / "out.html", repo.root / ".git" / "out.html",
                           start / "out.html"):
                with self.subTest(start=start.name, wanted=str(wanted)):
                    self.assertEqual(self.run_main(["--snapshot", "--output", str(wanted)], root=start)[0], 2)
        previous = Path.cwd()
        os.chdir(sub)  # a relative --output is read from the current folder, as a shell gives it
        try:
            self.assertEqual(self.run_main(["--snapshot", "--output", "../../out.html"], root=sub)[0], 2)
        finally:
            os.chdir(previous)
        self.assertEqual([path for path in repo.root.rglob("out.html*")], [])
        # the default page is one file per repository, whatever folder of it the board starts from
        pages = set()
        for start in (repo.root, sub, inner):
            code, out, _ = self.run_main(["--snapshot"], root=start)
            self.assertEqual(code, 0, out)
            pages.add(Path(json.loads(out)["page"]))
        self.assertEqual(pages, {cli.default_output(repo.root)})

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_worktree_the_board_does_not_read_keeps_the_snapshot_out_of_its_repository(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        starts = [repo.root / "wt" / "x", repo.trees / "my session", repo.trees / "_x",  # git keeps "_x" as its id
                  repo.root.parent / "_odd", repo.root.parent / "été-1", repo.root.parent / "feat+x"]
        for index, start in enumerate(starts):
            repo.git("worktree", "add", "-q", "-b", f"claude/w{index}", str(start), "main")
        (starts[0] / "src").mkdir(exist_ok=True)
        moved = repo.trees / "moved"  # made outside, then moved in: it keeps the id it was given
        repo.git("worktree", "add", "-q", "-b", "claude/moved", str(repo.root.parent / "_first"), "main")
        repo.git("worktree", "move", str(repo.root.parent / "_first"), str(moved))
        wanted = [repo.root / "out.html", repo.root / ".git" / "out.html"]
        if os.name == "nt":
            wanted.append(Path("\\\\?\\" + str(repo.root)) / "out.html")
        for start in (*starts, starts[0] / "src", moved):  # each is a worktree the board refuses to read
            for output in wanted:
                with self.subTest(start=start.name, output=str(output)):
                    code, out, _ = self.run_main(["--snapshot", "--output", str(output)], root=start)
                    self.assertEqual(code, 2, out)
        self.assertEqual(list(repo.root.glob("*.html")) + list((repo.root / ".git").glob("*.html")), [])

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_worktree_of_a_bare_repository_keeps_the_snapshot_out_of_it(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        bare = repo.root.parent / "project.git"
        repo.git("clone", "-q", "--bare", str(repo.root), str(bare))
        tree = repo.root.parent / "bare-tree"
        repo.git("--git-dir", str(bare), "worktree", "add", "-q", "-b", "claude/b", str(tree), "main")
        for output in (bare / "page.html", bare / "worktrees" / "page.html"):
            with self.subTest(output=output.name):
                self.assertEqual(self.run_main(["--snapshot", "--output", str(output)], root=tree)[0], 2)
        self.assertEqual(list(bare.rglob("page.html")), [])

    def test_a_git_file_that_names_nothing_plain_lets_only_the_cache_be_written(self) -> None:
        base = Path(self._cache.name).resolve()
        folder = base / "odd"
        folder.mkdir()
        (folder / ".git").write_text("gitdir: //?/" + (base / "repo" / ".git" / "worktrees" / "x").as_posix() + "\n",
                                     encoding="utf-8")
        (base / "out").mkdir()
        self.assertEqual(self.run_main(["--snapshot", "--output", str(base / "out" / "page.html")], root=folder)[0], 2)
        self.assertEqual(self.run_main(["--snapshot"], root=folder)[0], 0)  # the board's own error page, in the cache

    def test_the_folder_a_git_file_names_is_never_looked_at(self) -> None:
        base = Path(self._cache.name).resolve()
        folder, claimed = base / "work", base / "far" / "away"
        folder.mkdir()
        claimed.mkdir(parents=True)
        (base / "out").mkdir()
        far = os.path.normcase(str(base / "far"))
        # every way the standard library looks at a path: Path.resolve goes through realpath, Path.open through open
        looks = [(os, name) for name in ("stat", "lstat", "scandir", "listdir", "open")] \
            + [(os.path, name) for name in ("isdir", "isfile", "exists", "lexists", "islink", "realpath")] \
            + [(builtins, "open"), (io, "open")]
        for text in (claimed / ".git" / "worktrees" / "x", base / "work" / ".." / "far" / "away" / ".git" / "worktrees"
                     / "x"):  # a path written plainly, or with ".." that git resolves and a text check would not
            (folder / ".git").write_text("gitdir: " + text.as_posix() + "\n", encoding="utf-8")
            seen: list[str] = []

            def spy(real):
                def look(path, *args, **kwargs):
                    if isinstance(path, (str, bytes, os.PathLike)):  # abspath folds "work/.." as the system would
                        seen.append(os.path.normcase(os.path.abspath(os.fsdecode(path))))
                    return real(path, *args, **kwargs)
                return look

            with self.subTest(text=text.as_posix()), contextlib.ExitStack() as stack:
                for owner, name in looks:
                    stack.enter_context(mock.patch.object(owner, name, spy(getattr(owner, name))))
                code = self.run_main(["--snapshot", "--output", str(base / "out" / "page.html")], root=folder)[0]
                self.assertEqual(code, 2)  # the board reads nothing here: only the cache may hold its error page
                self.assertEqual(self.run_main(["--snapshot"], root=folder)[0], 0)
            self.assertEqual([path for path in seen if path == far or path.startswith(far + os.sep)], [])
        self.assertEqual(list((base / "out").iterdir()), [])

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_folder_git_would_not_stop_at_lets_only_the_cache_be_written(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        stray = repo.root / "notes" / "draft"
        (stray / ".git").mkdir(parents=True)  # an empty .git folder: git skips it and finds the checkout above
        bare = repo.root.parent / "project.git"
        repo.git("clone", "-q", "--bare", str(repo.root), str(bare))
        for start, output in ((stray, repo.root / "stray.html"), (bare / "refs" / "heads", bare / "inside.html"),
                              (bare, bare / "inside.html")):
            with self.subTest(start=start.name):
                code, _, err = self.run_main(["--snapshot", "--output", str(output)], root=start)
                self.assertEqual(code, 2)
                self.assertIn("--output needs a repository the board can read", err)
                self.assertEqual(self.run_main(["--snapshot"], root=start)[0], 0)  # an error page, in the cache
        for part in ("HEAD", "objects", "refs"):  # an empty HEAD: still no git folder to git
            (stray / ".git" / part).mkdir() if part != "HEAD" else (stray / ".git" / part).write_text("")
        self.assertEqual(self.run_main(["--snapshot", "--output", str(repo.root / "s7.html")], root=stray)[0], 2)
        self.assertEqual(list(repo.root.glob("*.html")) + list(bare.glob("*.html")), [])

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_session_inside_a_checkout_whose_git_folder_lives_elsewhere_writes_nothing_there(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        base = repo.root.parent
        main, store = base / "main", base / "store" / "main-git"
        store.parent.mkdir()  # git makes the git folder, not its parent
        repo.git("clone", "-q", "--separate-git-dir", str(store), str(repo.root), str(main))
        repo.git("-C", str(main), "worktree", "add", "-q", "-b", "claude/x", str(main / ".claude" / "worktrees" / "x"))
        project = base / "proj"
        repo.git("clone", "-q", "--bare", str(repo.root), str(project / ".bare"))
        repo.git("--git-dir", str(project / ".bare"), "worktree", "add", "-q", str(project / "trunk"), "main")
        repo.git("-C", str(project / "trunk"), "worktree", "add", "-q", "-b", "claude/y",
                 str(project / "trunk" / ".claude" / "worktrees" / "y"))
        for start, outputs in ((main / ".claude" / "worktrees" / "x", (main / "board.html", store / "board.html")),
                               (project / "trunk" / ".claude" / "worktrees" / "y",
                                (project / "trunk" / "board.html", project / "board.html"))):
            for output in outputs:
                with self.subTest(start=start.name, output=output.parent.name):
                    self.assertEqual(self.run_main(["--snapshot", "--output", str(output)], root=start)[0], 2)
                    self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "NTFS keeps apart two names that str.lower folds together")
    @unittest.skipIf(GIT is None, "git absent")
    def test_a_lookalike_of_the_main_checkout_is_never_read(self) -> None:
        base = Path(self._cache.name).resolve()
        main, decoy = base / "keep-main", base / "Keep-main"  # a Kelvin sign: str.lower folds it, NTFS does not
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}

        def git(*args: str) -> None:
            subprocess.run([GIT, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c",
                            "commit.gpgsign=false", *args], check=True, capture_output=True, env=env)

        for folder in (main, decoy):
            git("init", "-q", "-b", "main", str(folder))
            git("-C", str(folder), "commit", "-q", "--allow-empty", "-m", "first")
        tree = main / ".claude" / "worktrees" / "x"
        git("-C", str(main), "worktree", "add", "-q", "-b", "claude/x", str(tree))
        (tree / ".git").unlink()  # git hides it on Windows: a hidden file cannot be opened for a new write
        (tree / ".git").write_text("gitdir: " + (decoy / ".git" / "worktrees" / "x").as_posix() + "\n",
                                   encoding="utf-8")
        root = collector_module.Collector(tree, Settings()).root
        self.assertEqual(str(root), str(main))  # its own parent folder, never the lookalike the text names
        for output in (main / "board.html", tree / "board.html"):
            with self.subTest(output=output.parent.name):
                self.assertEqual(self.run_main(["--snapshot", "--output", str(output)], root=tree)[0], 2)
                self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "nt", "a Windows way of writing a path")
    @unittest.skipIf(GIT is None, "git absent")
    def test_the_repository_written_another_way_is_still_the_repository(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        prefixed = "\\\\?\\" + str(repo.root)
        for argv in (["--snapshot", "--output", prefixed + "\\a.html"],
                     ["--snapshot", "--repo", prefixed, "--output", str(repo.root / "b.html")]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_main(argv, root=repo.root)[0], 2)
        self.assertEqual(list(repo.root.glob("*.html")), [])

    def test_a_loop_of_links_is_a_usage_error(self) -> None:
        base = Path(self._cache.name).resolve()
        first, second = base / "loop-a", base / "loop-b"
        try:
            os.symlink(second, first, target_is_directory=True)
            os.symlink(first, second, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system does not let the test make a link")
        for argv in (["--resume", "--repo", str(first)], ["--snapshot", "--output", str(first / "x.html")]):
            with self.subTest(argv=argv):  # Python 3.12 raises RuntimeError for such a loop, later ones OSError
                self.assertEqual(self.run_main(argv, root=base)[0], 2)

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_cache_folder_inside_the_repository_is_never_made(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        inside = repo.root / "cache" / "flightboard"
        with mock.patch.object(cli, "cache_folder", return_value=inside):
            self.assertEqual(self.run_main(["--snapshot"], root=repo.root)[0], 2)
        self.assertFalse((repo.root / "cache").exists())  # refused before anything is made

    @unittest.skipIf(GIT is None, "git absent")
    def test_a_snapshot_never_writes_through_a_link(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        victim = repo.root.parent / "victim.txt"
        victim.write_text("intact", encoding="utf-8")
        self.cache.mkdir(parents=True)
        output = cli.default_output(repo.root)
        partial = output.with_name(output.name + ".partial")
        try:
            os.link(victim, partial)
        except OSError:
            self.skipTest("this system does not let the test make a hard link")
        self.assertEqual(self.run_main(["--snapshot"], root=repo.root)[0], 0)
        self.assertEqual(victim.read_text(encoding="utf-8"), "intact")
        outside = repo.root.parent / "outside"
        outside.mkdir()
        shutil.rmtree(self.cache)
        from tests.test_files import make_link
        if not make_link(outside, self.cache):
            self.skipTest("this system does not let the test make a link")
        # refused by lstat before anything resolves the path: resolving would open the link's target
        self.assertEqual(self.run_main(["--snapshot"], root=repo.root)[0], 2)
        self.assertEqual(list(outside.iterdir()), [])
        inside = repo.root / "pages"
        inside.mkdir()
        shutil.rmtree(outside)
        os.unlink(self.cache) if self.cache.is_symlink() else os.rmdir(self.cache)
        if make_link(inside, self.cache):  # a link that leads back into the repository
            self.assertEqual(self.run_main(["--snapshot"], root=repo.root)[0], 2)
            self.assertEqual(list(inside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
