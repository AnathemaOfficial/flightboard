# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The first HTML response never waits for a repository reading or invents verdicts."""
from __future__ import annotations

import http.client
import json
import re
import threading
import unittest

from tests.fixtures import NOW, load

server = load("server")
page = load("page")
view = load("view")
Settings = load("config").Settings


class Collector:
    def __init__(self) -> None:
        self.calls = 0
        self.name = "large-project"
        self.settings = Settings(lang="fr", read_seconds=120, max_worktrees=300)
        self.failure = False
        self.started, self.release = threading.Event(), threading.Event()
        self.release.set()

    def snapshot(self, now, mode="live"):
        self.calls += 1
        self.started.set()
        if not self.release.wait(5):
            raise RuntimeError("test reading was not released")
        if self.failure:
            raise RuntimeError("reading failed")
        value = view.error_view(now, mode, "read_failed", repository=self.name)
        value["main"].update(state="ok", valid=True, reason="", reason_text="")
        value["waiting"] = [{"kind": "merge", "text": "old verdict"}]
        return value


def embedded(body: bytes) -> dict:
    match = re.search(r'<script type="application/json" id="flightboard-data">(.*?)</script>',
                      body.decode("utf-8"), re.S)
    return json.loads(match.group(1))


class FirstPageTest(unittest.TestCase):
    def test_a_shell_exposes_metadata_without_starting_a_reading(self):
        collector = Collector()
        value = server.Snapshots(collector, now=lambda: NOW).page()
        self.assertEqual(collector.calls, 0)
        self.assertEqual(value["main"]["state"], "loading")
        self.assertEqual(value["repository"], "large-project")
        self.assertEqual(value["settings"]["read_seconds"], 120)
        self.assertEqual(value["settings"]["max_worktrees"], 300)
        self.assertEqual(value["i18n"]["lang"], "fr")
        self.assertEqual(value["i18n"]["labels"]["source"]["loading"], "lecture en cours")
        self.assertEqual(value["sessions"], [])
        self.assertEqual(value["waiting"], [])
        self.assertEqual(value["kpis"]["ready"], 0)
        self.assertEqual(value["sources"][0]["state"], "loading")

    def test_only_a_fresh_completed_reading_is_used_in_html(self):
        clock = [100.0]
        collector = Collector()
        snapshots = server.Snapshots(collector, clock=lambda: clock[0], now=lambda: NOW)
        complete = snapshots.get()
        self.assertIs(snapshots.page(), complete)
        clock[0] += server.MIN_INTERVAL
        self.assertEqual(snapshots.page()["main"]["state"], "loading")
        self.assertEqual(snapshots.page()["waiting"], [])
        self.assertEqual(collector.calls, 1)

    def test_a_failed_reading_cannot_reappear_as_old_verdicts_in_html(self):
        clock = [100.0]
        collector = Collector()
        snapshots = server.Snapshots(collector, clock=lambda: clock[0], now=lambda: NOW)
        self.assertTrue(snapshots.get()["waiting"])
        clock[0] += server.MIN_INTERVAL
        collector.failure = True
        with self.assertRaises(RuntimeError):
            snapshots.get()
        value = snapshots.page()
        self.assertEqual(value["main"]["state"], "unreadable")
        self.assertEqual(value["waiting"], [])
        self.assertEqual(value["sessions"], [])
        self.assertEqual(value["settings"]["read_seconds"], 120)
        self.assertEqual(collector.calls, 2)

    def test_html_and_head_return_while_json_is_still_reading(self):
        collector = Collector()
        snapshots = server.Snapshots(collector, clock=lambda: 100.0, now=lambda: NOW)
        application = server.make_server(snapshots, page.template(), 0, lang="fr")
        worker = threading.Thread(target=application.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(application.server_close)
        self.addCleanup(application.shutdown)
        port = application.server_address[1]

        def request(path="/", method="GET", host=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request(method, path, headers={"Host": host or f"127.0.0.1:{port}"})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        # Opening the first page, including HEAD, does not start any repository work.
        status, headers, body = request()
        self.assertEqual(status, 200)
        self.assertEqual(embedded(body)["main"]["state"], "loading")
        self.assertEqual(headers["Content-Security-Policy"], page.policy(page.template()))
        head_status, head_headers, head_body = request(method="HEAD")
        self.assertEqual(head_status, 200)
        self.assertEqual(head_headers["Content-Security-Policy"], page.policy(page.template()))
        self.assertTrue(head_headers["Content-Type"].startswith("text/html"))
        self.assertGreater(int(head_headers["Content-Length"]), 0)
        self.assertEqual(head_body, b"")
        self.assertEqual(collector.calls, 0)

        collector.release.clear()
        state_result, page_result, errors = [], [], []
        html_done = threading.Event()

        def read_json():
            try:
                state_result.append(request("/state.json"))
            except Exception as error:
                errors.append(error)

        def read_html():
            try:
                page_result.append(request())
                page_result.append(request(method="HEAD"))
                page_result.append(request(host="other.example"))
            except Exception as error:
                errors.append(error)
            finally:
                html_done.set()

        state_worker = threading.Thread(target=read_json, daemon=True)
        html_worker = threading.Thread(target=read_html, daemon=True)
        state_worker.start()
        try:
            self.assertTrue(collector.started.wait(1))
            html_worker.start()
            returned_before_release = html_done.wait(2)
        finally:
            collector.release.set()
            state_worker.join(3)
            if html_worker.ident is not None:
                html_worker.join(3)
        self.assertTrue(returned_before_release, "HTML waited for the blocked repository reading")
        self.assertEqual(errors, [])
        self.assertEqual(embedded(page_result[0][2])["main"]["state"], "loading")
        self.assertEqual(embedded(page_result[0][2])["waiting"], [])
        self.assertEqual(page_result[1][0], 200)
        self.assertEqual(page_result[1][1]["Content-Security-Policy"], page.policy(page.template()))
        self.assertTrue(page_result[1][1]["Content-Type"].startswith("text/html"))
        self.assertGreater(int(page_result[1][1]["Content-Length"]), 0)
        self.assertEqual(page_result[1][2], b"")
        self.assertEqual(page_result[2][0], 403)
        self.assertEqual(collector.calls, 1)
        self.assertEqual(json.loads(state_result[0][2])["main"]["state"], "ok")
        self.assertEqual(snapshots.page()["main"]["state"], "ok")


if __name__ == "__main__":
    unittest.main()
