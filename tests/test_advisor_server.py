# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Real loopback requests: permissions, strict bodies and bounded independent advisor work."""
from __future__ import annotations

import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from tests.fixtures import load

server, page, advisor = load("server"), load("page"), load("advisor")


class Collector:
    def __init__(self, root):
        self.root, self.calls = root, 0
        self.view = {"tool": {"name": "flightboard"}, "repository": "example", "mode": "live",
                     "generated_at": "2026-11-21T12:00:00Z", "main": {"state": "ok", "valid": True},
                     "overview": {"progress": {"main": {"done": 1}}}}

    def snapshot(self, *args):
        self.calls += 1
        return copy.deepcopy(self.view)


class AdvisorServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.clock = 100.0
        self.collector = Collector(self.root)
        self.snapshots = server.Snapshots(self.collector, clock=lambda: self.clock)
        self.snapshots.get()
        self.sent = []

        def provider(config, key, question, context):
            self.sent.append((key, context))
            return {"text": "Read-only advice <script>untrusted</script>", "usage": {"input_tokens": 1}}

        self.advisor = advisor.Advisor(self.root, self.snapshots.peek, provider=provider, clock=lambda: self.clock,
                                       schedule=False, refresh_snapshot=self.snapshots.refresh_if_idle)
        self.addCleanup(self.advisor.close)
        self.http = server.make_server(self.snapshots, page.template(), 0, advisor=self.advisor)
        self.port = self.http.server_address[1]
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(3)

    def request(self, path, method="POST", value=None, extra=None, token=True, origin=True, raw=None):
        body = raw if raw is not None else json.dumps(value or {}).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = [("Host", f"127.0.0.1:{self.port}")]
        if token:
            headers.append(("X-Flightboard-Advisor", self.advisor.token))
        if method == "POST" and origin:
            headers.append(("Origin", f"http://127.0.0.1:{self.port}"))
        if method == "POST":
            headers += [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
        headers += extra or []
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for key, item in headers:
                connection.putheader(key, item)
            connection.endheaders(body if method == "POST" else None)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def preview(self):
        status, raw = self.request("/advisor/preview", value={
            "config": {"protocol": "openai", "endpoint": "https://api.example.com/v1", "model": "chosen"},
            "question": "What remains?", "repo_files": [], "local_files": [], "consent_board": True})
        self.assertEqual(status, 200, raw)
        return json.loads(raw)["preview"]

    def test_preview_and_analysis_are_separate_and_never_enter_state_json(self):
        preview = self.preview()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.collector.calls, 1, "preview must not initiate another scan")
        request = {"preview_id": preview["id"], "sha256": preview["sha256"], "consent_send": True,
                   "api_key": "synthetic-private-key"}
        status, raw = self.request("/advisor/analyze", value=request)
        self.assertEqual(status, 200, raw)
        self.assertTrue(self.advisor.wait_idle(3))
        status, raw = self.request("/advisor/status", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["state"], "complete")
        self.assertNotIn(b"synthetic-private-key", raw)
        _, state = self.request("/state.json", method="GET")
        self.assertNotIn(b"private-key", state)
        self.assertNotIn(b"Read-only advice", state)
        self.assertNotIn(self.advisor.token.encode(), state)
        _, html = self.request("/", method="GET")
        self.assertNotIn(b"synthetic-private-key", html)
        self.assertNotIn(b"Read-only advice", html)

    def test_origin_token_method_and_query_guards_do_no_context_work(self):
        cases = [("/advisor/preview", {"origin": False}), ("/advisor/status", {"method": "GET", "token": False}),
                 ("/advisor/preview", {"token": False}), ("/advisor/preview?key=private", {}),
                 ("/advisor/preview", {"extra": [("Origin", "http://evil.example")]}),
                 ("/advisor/preview", {"extra": [("X-Flightboard-Advisor", self.advisor.token)]}),
                 ("/advisor/preview", {"extra": [("Sec-Fetch-Dest", "document")]}),
                 ("/advisor/analyze", {"method": "GET"}), ("/state.json", {})]
        for path, changes in cases:
            with self.subTest(path=path, changes=changes):
                status, _ = self.request(path, **changes)
                self.assertIn(status, (403, 404, 405))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.advisor.status()["state"], "disabled")

    def test_duplicate_chunked_oversized_and_non_json_bodies_are_refused(self):
        for extras, raw in [([("Content-Length", "2")], b"{}"),
                            ([("Content-Length", str(server.MAX_ADVISOR_BODY + 1))], b"{}"),
                            ([("Transfer-Encoding", "chunked")], b"{}"),
                            ([("Content-Type", "text/plain")], b"{}"),
                            ([], b'{"consent_board":false,"consent_board":true}'),
                            ([], b'{"x":NaN}'), ([], b'[]'), ([], b'\xff')]:
            with self.subTest(extras=extras, raw=raw):
                status, body = self.request("/advisor/preview", extra=extras, raw=raw)
                self.assertEqual(status, 400, body)
                self.assertEqual(json.loads(body)["error"], "body_invalid")
        self.assertEqual(self.sent, [])

    def test_automatic_refreshes_after_browser_closed_but_uses_existing_scan_cache(self):
        preview = self.preview()
        status, raw = self.request("/advisor/automate", value={"preview_id": preview["id"],
            "sha256": preview["sha256"], "consent_send": True, "consent_automatic": True,
            "api_key": "synthetic-private-key", "interval_minutes": 15, "max_calls": 2})
        self.assertEqual(status, 200, raw)
        self.assertTrue(self.advisor.wait_idle(3))
        self.collector.view["overview"]["progress"]["main"]["done"] = 2
        self.clock += 901
        self.advisor.check_automatic()  # no ordinary HTTP state poll since the page was closed
        self.assertTrue(self.advisor.wait_idle(3))
        self.assertEqual(self.collector.calls, 2)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1][1]["board"]["overview"]["progress"]["main"]["done"], 2)
        self.snapshots.get()
        self.assertEqual(self.collector.calls, 2, "an ordinary poll reuses the automatic check's scan")

    def test_cache_capture_never_waits_for_another_scan_or_mutates_published_view(self):
        view = self.snapshots.peek()
        view["main"]["state"] = "changed"
        self.assertEqual(self.snapshots.peek()["main"]["state"], "ok")
        with self.snapshots._lock:
            start = time.monotonic()
            self.assertIsNone(self.snapshots.peek())
            self.assertIsNone(self.snapshots.refresh_if_idle())
            self.assertLess(time.monotonic() - start, 0.1)
        self.assertEqual(self.collector.calls, 1)

    def test_provider_latency_does_not_block_ordinary_cached_http_refresh(self):
        entered, release = threading.Event(), threading.Event()

        def slow(*args):
            entered.set()
            release.wait(3)
            return {"text": "synthetic result", "usage": {}}

        self.advisor._provider = slow
        preview = self.preview()
        status, raw = self.request("/advisor/analyze", value={"preview_id": preview["id"],
            "sha256": preview["sha256"], "consent_send": True, "api_key": "synthetic-private-key"})
        self.assertEqual(status, 200, raw)
        self.assertTrue(entered.wait(2))
        try:
            before = time.monotonic()
            status, raw = self.request("/state.json", method="GET")
            self.assertEqual(status, 200, raw)
            self.assertLess(time.monotonic() - before, 0.5)
            self.assertEqual(self.collector.calls, 1)
        finally:
            release.set()
            self.assertTrue(self.advisor.wait_idle(3))

    def test_snapshot_pages_have_no_advisor_token_and_dual_listeners_share_authority(self):
        html = page.render(self.collector.view, page.template())
        self.assertNotIn(self.advisor.token, html)
        servers = server.make_servers(self.snapshots, page.template(), 0)
        try:
            self.assertTrue(all(s.advisor is servers[0].advisor for s in servers))
        finally:
            for item in servers:
                item.server_close()
