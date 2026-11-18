# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A repaired local Git object is visible on the next reading, without restarting the board."""
from __future__ import annotations

import json
import stat
import unittest
from datetime import timedelta

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain

collector_module = load("collector")
Settings = load("config").Settings


@unittest.skipIf(GIT is None, "git absent")
class LedgerRefreshRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.repo.commit(self.repo.root, "tasks.json", self.content("planned"), "docs: initial lot", "09:00")

    @staticmethod
    def content(status: str) -> str:
        return json.dumps({"tasks": [{"id": "LOT-1", "title": "First lot", "status": status}]}) + "\n"

    def missing_blob_recovers(self, settings: Settings) -> None:
        commit = self.repo.git("rev-parse", "HEAD")
        blob = self.repo.git("rev-parse", "HEAD:tasks.json")
        path = self.repo.root / ".git" / "objects" / blob[:2] / blob[2:]
        original = path.read_bytes()
        path.chmod(path.stat().st_mode | stat.S_IWUSR)  # loose objects are read-only on Windows
        reader = collector_module.Collector(self.repo.root, settings)
        try:
            path.unlink()
            unavailable = reader.snapshot(NOW)
            self.assertEqual(unavailable["main"]["state"], "ok", unavailable["main"])
            self.assertEqual(unavailable["ledger"]["kind"], "none")
            self.assertEqual(unavailable["tasks"], {})
        finally:
            path.write_bytes(original)
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), commit)
        recovered = reader.snapshot(NOW + timedelta(seconds=10))
        self.assertEqual(recovered["main"]["state"], "ok", recovered["main"])
        self.assertEqual(recovered["ledger"]["kind"], "tasks")
        self.assertEqual(recovered["tasks"]["LOT-1"]["status"], "planned")

    def test_auto_detection_retries_after_a_missing_blob_is_restored(self) -> None:
        self.missing_blob_recovers(Settings())

    def test_explicit_ledger_retries_after_a_missing_blob_is_restored(self) -> None:
        self.missing_blob_recovers(Settings(ledger="tasks", ledger_path="tasks.json"))

    def test_auto_detection_replaces_a_fallback_when_the_preferred_blob_is_restored(self) -> None:
        content = '[[tasks]]\nid = "TOML-1"\ntitle = "Preferred lot"\nstatus = "planned"\n'
        self.repo.commit(self.repo.root, "tasks.toml", content, "docs: preferred ledger", "09:10")
        commit = self.repo.git("rev-parse", "HEAD")
        blob = self.repo.git("rev-parse", "HEAD:tasks.toml")
        path = self.repo.root / ".git" / "objects" / blob[:2] / blob[2:]
        original = path.read_bytes()
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
        reader = collector_module.Collector(self.repo.root)
        try:
            path.unlink()
            fallback = reader.snapshot(NOW)
            self.assertEqual(fallback["main"]["state"], "ok", fallback["main"])
            self.assertEqual(fallback["ledger"]["path"], "tasks.json")
            self.assertEqual(set(fallback["tasks"]), {"LOT-1"})
        finally:
            path.write_bytes(original)
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), commit)
        recovered = reader.snapshot(NOW + timedelta(seconds=10))
        self.assertEqual(recovered["main"]["state"], "ok", recovered["main"])
        self.assertEqual(recovered["ledger"]["path"], "tasks.toml")
        self.assertEqual(set(recovered["tasks"]), {"TOML-1"})

    def test_history_retries_after_a_missing_older_blob_is_restored(self) -> None:
        self.repo.commit(self.repo.root, "tasks.json", self.content("in_progress"), "feat: start lot", "09:10")
        middle = self.repo.git("rev-parse", "HEAD")
        blob = self.repo.git("rev-parse", "HEAD:tasks.json")
        self.repo.commit(self.repo.root, "tasks.json", self.content("awaiting_review"), "feat: deliver lot", "09:20")
        path = self.repo.root / ".git" / "objects" / blob[:2] / blob[2:]
        original = path.read_bytes()
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
        reader = collector_module.Collector(self.repo.root)
        try:
            path.unlink()
            unavailable = reader.snapshot(NOW)
            self.assertEqual(unavailable["main"]["state"], "ok", unavailable["main"])
            self.assertFalse(any(event.get("sha") == middle[:7] for event in unavailable["events"]))
        finally:
            path.write_bytes(original)
        recovered = reader.snapshot(NOW + timedelta(seconds=10))
        event = next((event for event in recovered["events"] if event.get("sha") == middle[:7]), None)
        self.assertIsNotNone(event, recovered["events"])
        self.assertEqual((event["task"], event["from"], event["to"]), ("LOT-1", "planned", "in_progress"))
