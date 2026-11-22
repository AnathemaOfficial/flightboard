# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Consent, frozen payloads, bounded scheduling and independence from Git reads."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.fixtures import load

advisor = load("advisor")

CONFIG = {"protocol": "openai", "endpoint": "https://api.example.com/v1", "model": "chosen-model",
          "max_output_tokens": 1024}


class AdvisorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.board = {"tool": {"name": "flightboard"}, "repository": "example", "mode": "live",
                      "generated_at": "2026-11-21T12:00:00Z", "main": {"state": "ok", "valid": True},
                      "overview": {"progress": {"main": {"done": 1}}}}
        self.calls = []
        self.clock = 100.0

        def provider(config, key, question, context):
            self.calls.append((config, key, question, copy.deepcopy(context)))
            return {"text": "Review repo:proof.md before publishing.", "usage": {"input_tokens": 12,
                                                                                  "output_tokens": 8}}

        self.service = advisor.Advisor(self.root, lambda: copy.deepcopy(self.board), provider=provider,
                                       clock=lambda: self.clock, schedule=False)
        self.addCleanup(self.service.close)

    def request(self, **changes):
        return {"config": CONFIG, "question": "What needs attention?", "repo_files": [], "local_files": [],
                "consent_board": True, "consent_repo": False, "consent_local": False, **changes}

    def preview(self, **changes):
        return self.service.preview(self.request(**changes))["preview"]

    def analyze_args(self, preview, **changes):
        return {"preview_id": preview["id"], "sha256": preview["sha256"], "consent_send": True,
                "api_key": "synthetic-test-key", **changes}

    def finish(self):
        deadline = time.monotonic() + 3
        while self.service.status()["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertNotEqual(self.service.status()["state"], "running")
        return self.service.status()

    def test_default_does_no_work_and_read_consent_is_enforced(self):
        self.assertEqual(self.service.status()["state"], "disabled")
        for changes in ({"consent_board": False}, {"repo_files": ["proof.md"]},
                        {"local_files": [str(self.root / "proof.md")]}):
            with self.subTest(changes=changes), self.assertRaises(advisor.AdvisorError):
                self.preview(**changes)
        self.assertEqual(self.calls, [])

    def test_preview_is_local_and_send_uses_frozen_bytes(self):
        path = self.root / "proof.md"
        path.write_text("original proof", encoding="utf-8")
        preview = self.preview(repo_files=["proof.md"], consent_repo=True)
        self.assertEqual(self.calls, [])
        path.write_text("changed after preview", encoding="utf-8")
        preview["context"]["files"][0]["text"] = "mutated returned value"
        self.service.analyze(self.analyze_args(preview))
        status = self.finish()
        self.assertEqual(self.calls[0][3]["files"][0]["text"], "original proof")
        self.assertEqual(status["result"]["usage"]["input_tokens"], 12)
        self.assertNotIn("synthetic-test-key", str(status))
        with self.assertRaises(advisor.AdvisorError):
            self.service.analyze(self.analyze_args(preview))

    def test_send_requires_exact_preview_and_separate_consent(self):
        preview = self.preview()
        for changes in ({"consent_send": False}, {"sha256": "a" * 64}, {"preview_id": "other"}):
            with self.subTest(changes=changes), self.assertRaises(advisor.AdvisorError):
                self.service.analyze(self.analyze_args(preview, **changes))
        self.assertEqual(self.calls, [])
        self.clock += advisor.AUTH_SECONDS + 1
        with self.assertRaises(advisor.AdvisorError):
            self.service.analyze(self.analyze_args(preview))

    def test_revoke_discards_inflight_result_and_blocks_another_call_until_done(self):
        started, release = threading.Event(), threading.Event()

        def slow(*args):
            started.set()
            release.wait(3)
            return {"text": "obsolete", "usage": {}}

        self.service._provider = slow
        preview = self.preview()
        self.service.analyze(self.analyze_args(preview))
        self.assertTrue(started.wait(2))
        before = time.monotonic()
        self.service.status()
        self.assertLess(time.monotonic() - before, 0.1)
        self.service.revoke()
        with self.assertRaises(advisor.AdvisorError):
            self.preview()
        release.set()
        self.service.wait_idle(3)
        self.assertEqual(self.service.status()["state"], "revoked")
        self.assertNotIn("obsolete", str(self.service.status()))

    def test_automatic_counts_attempts_only_changed_context_and_exhausts_total_cap(self):
        self.board["publication"] = {"remote": {"state": "fresh", "checked_at": "now", "_expires_at": 500}}
        preview = self.preview()
        args = self.analyze_args(preview, consent_automatic=True, interval_minutes=15, max_calls=2)
        self.service.automate(args)
        self.finish()
        self.assertEqual(len(self.calls), 1)
        self.clock += 901
        self.board["generated_at"] = "2026-11-21T12:15:00Z"
        self.board["publication"]["remote"].update(checked_at="later", _expires_at=800)
        self.service.check_automatic()
        self.assertEqual(len(self.calls), 1, "a new scan timestamp alone cannot spend a call")
        self.clock += 901
        self.board["overview"]["progress"]["main"]["done"] = 2
        self.service.check_automatic()
        status = self.finish()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(status["automatic"]["enabled"])
        self.assertEqual(status["automatic"]["remaining"], 0)
        self.assertIsNone(self.service._auto_key)
        self.clock += 901
        self.service.check_automatic()
        self.assertEqual(len(self.calls), 2)

    def test_private_observer_metadata_never_enters_shared_context(self):
        self.board["publication"] = {"remote": {"state": "fresh", "_expires_at": 123.45}}
        preview = self.preview()
        self.assertNotIn("_expires_at", str(preview["context"]))

    def test_revoking_before_worker_entry_suppresses_the_provider_call(self):
        entered, release = threading.Event(), threading.Event()
        run = self.service._run

        def gated(*args):
            entered.set()
            release.wait(3)
            run(*args)

        self.service._run = gated
        preview = self.preview()
        self.service.analyze(self.analyze_args(preview))
        self.assertTrue(entered.wait(2))
        self.service.revoke()
        release.set()
        self.assertTrue(self.service.wait_idle(3))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.status()["state"], "revoked")

    def test_automatic_unavailable_check_is_visible_and_expiry_clears_key(self):
        preview = self.preview()
        self.service.automate(self.analyze_args(preview, consent_automatic=True, interval_minutes=15, max_calls=4))
        self.finish()
        self.assertEqual(self.service.status()["authorization"]["config"]["model"], CONFIG["model"])
        self.service._refresh_snapshot = lambda: None
        self.clock += 901
        self.service.check_automatic()
        self.assertEqual(self.service.status()["error"], "automatic_context_unavailable")
        self.assertEqual(len(self.calls), 1)
        self.service._refresh_snapshot = lambda: copy.deepcopy(self.board)
        self.clock += 901
        self.service.check_automatic()
        self.assertNotIn("error", self.service.status())
        self.assertEqual(len(self.calls), 1)
        self.clock += advisor.AUTH_SECONDS
        self.assertFalse(self.service.status()["automatic"]["enabled"])
        self.assertIsNone(self.service._auto_key)
        self.service.revoke()
        self.assertNotIn("selection", self.service._auto)
        self.assertNotIn("question", self.service._auto)

    def test_automatic_requires_future_sharing_consent_and_valid_bounds(self):
        preview = self.preview()
        for changes in ({"consent_automatic": False}, {"interval_minutes": 0}, {"max_calls": 0},
                        {"max_calls": True}, {"max_calls": 21}):
            args = self.analyze_args(preview, consent_automatic=True, interval_minutes=15, max_calls=2)
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(advisor.AdvisorError):
                self.service.automate(args)
        self.assertEqual(self.calls, [])

    def test_automatic_failure_consumes_cap_without_retry_and_revocation_stops_scheduler(self):
        def failed(*args):
            self.calls.append(args)
            raise RuntimeError("synthetic-test-key must never escape")

        self.service._provider = failed
        preview = self.preview()
        self.service.automate(self.analyze_args(preview, consent_automatic=True, interval_minutes=15, max_calls=1))
        status = self.finish()
        self.assertEqual(status["state"], "error")
        self.assertNotIn("synthetic-test-key", str(status))
        self.assertEqual(status["automatic"]["used"], 1)
        self.assertFalse(status["automatic"]["enabled"])
        self.service.revoke()
        self.clock += 901
        self.service.check_automatic()
        self.assertEqual(len(self.calls), 1)

    def test_no_board_read_when_unavailable_or_scanning(self):
        self.service._snapshot = lambda: None
        with self.assertRaises(advisor.AdvisorError):
            self.preview()
        self.assertEqual(self.calls, [])

    def test_worker_and_scheduler_start_failure_release_credentials_and_capacity(self):
        preview = self.preview()
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("synthetic failure")):
            self.service.analyze(self.analyze_args(preview))
        self.assertEqual(self.service.status()["state"], "error")
        self.assertIsNone(self.service._thread)
        self.assertFalse(self.service._active)
        self.assertNotIn("synthetic-test-key", str(vars(self.service)))
        self.service._schedule = True
        preview = self.preview()
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(advisor.AdvisorError):
                self.service.automate(self.analyze_args(preview, consent_automatic=True, interval_minutes=15, max_calls=4))
        self.assertIsNone(self.service._scheduler)
        self.assertIsNone(self.service._auto_key)
        self.assertFalse(self.service.status()["automatic"]["enabled"])
        self.assertEqual(self.calls, [])
