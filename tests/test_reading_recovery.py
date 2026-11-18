# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Independent scan failures, guarded prefixes and file-time ordering survive one reading."""
from __future__ import annotations

import json
import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain, by_name

collector_module = load("collector")
files = load("files")
gitreads = load("gitreads")
Settings = load("config").Settings


@unittest.skipIf(GIT is None, "git absent")
class ReadingRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.repo.commit(self.repo.root, "tasks.json", json.dumps({"tasks": [
            {"id": "LOT-1", "status": "awaiting_review"}]}), "docs: lot", "08:40")
        self.tree = self.repo.worktree("lot-1", "codex/lot-1")
        self.old, self.new = NOW - timedelta(days=2), NOW - timedelta(hours=1)
        self.stamp(self.tree / "tasks.json", self.old)
        self.reader = collector_module.Collector(self.repo.root, Settings(ledger="tasks", ledger_path="tasks.json",
                                                                        read_seconds=60))

    @staticmethod
    def stamp(path: Path, when) -> None:
        os.utime(path, (when.timestamp(), when.timestamp()))

    def write(self, name: str, when=None) -> Path:
        path = self.tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("work\n", encoding="utf-8")
        self.stamp(path, when or self.new)
        return path

    def card(self) -> dict:
        state = self.reader.snapshot(NOW)
        self.assertEqual(state["main"]["state"], "ok", state["main"])
        return by_name(state)[self.tree.name]

    def fill_folder(self) -> None:
        for number in range(3):
            self.write(f"new-folder/{number}.txt")

    def test_a_guarded_prefix_stays_partial_and_supplies_known_new_file_evidence(self) -> None:
        self.fill_folder()
        with mock.patch.object(files, "MAX_ACTIVITY_ENTRIES", 2):
            card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("limit", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))
        self.assertEqual(card["tracking"], {"state": "check", "reason": "settled"})
        self.assertEqual(card["untracked"], 1)

    def test_scan_limit_survives_a_separate_descendant_ignore_failure(self) -> None:
        self.fill_folder()
        actual = gitreads.Git.ignored

        def ignored(git, git_dir, tree, paths):
            if tree == self.tree and any(name.startswith("new-folder/") and name != "new-folder/" for name in paths):
                raise gitreads.GitFailed("descendant exclusions unavailable")
            return actual(git, git_dir, tree, paths)

        with mock.patch.object(files, "MAX_ACTIVITY_ENTRIES", 2), \
                mock.patch.object(gitreads.Git, "ignored", ignored):
            card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertTrue({"limit", "ignore"} <= set(card["file_activity_partial_reasons"]))
        self.assertEqual(card["file_activity_observed_at"], "")
        self.assertEqual(card["tracking"], {"state": "unknown", "reason": "partial"})
        self.assertEqual(card["untracked"], 1)

    def test_subsecond_file_order_is_preserved_only_for_tracking_observations(self) -> None:
        second = NOW - timedelta(seconds=2)
        ledger_time, file_time = second.replace(microsecond=100_000), second.replace(microsecond=900_000)
        self.stamp(self.tree / "tasks.json", ledger_time)
        self.write("app.py", file_time)
        card = self.card()
        self.assertEqual(card["ledger_file_modified_at"], ledger_time.isoformat())
        self.assertEqual(card["file_activity_observed_at"], file_time.isoformat())
        self.assertEqual(card["last_write"], file_time.isoformat(timespec="seconds"))
        self.assertEqual(card["tracking"], {"state": "check", "reason": "settled"})

    def test_a_file_written_during_collection_is_within_the_completed_reading(self) -> None:
        actual = collector_module.Collector._read_files_of
        clock, written = [0.0], False

        def read_files(reader, item, planted, git):
            nonlocal written
            if item["path"] == self.tree and not written:
                written = True
                self.write("current.txt", NOW + timedelta(milliseconds=1500))
                clock[0] = 2.0
            return actual(reader, item, planted, git)

        with mock.patch.object(collector_module.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(collector_module.Collector, "_read_files_of", read_files):
            card = self.card()
        self.assertTrue(written)
        self.assertEqual(card["tracking"], {"state": "check", "reason": "settled"})


if __name__ == "__main__":
    unittest.main()
