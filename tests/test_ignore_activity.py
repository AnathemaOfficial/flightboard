# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Ignore-unevaluated untracked names never establish trusted ordinary-file activity."""
from __future__ import annotations

import json
import os
import unittest
from datetime import timedelta
from pathlib import Path

from tests.fixtures import GIT, NOW, load
from tests.test_git_limits import runs
from tests.test_modes import Plain, by_name

collector_module = load("collector")
Settings = load("config").Settings


@unittest.skipIf(GIT is None, "git absent")
class IgnoreActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.repo.commit(self.repo.root, "tasks.json", json.dumps({"tasks": [
            {"id": "LOT-1", "status": "awaiting_review"}]}), "docs: lot", "08:40")
        self.tree = self.repo.worktree("lot-1", "codex/lot-1")
        self.repo.commit(self.tree, ".gitignore", "*.py\n", "docs: exclusions", "09:00")
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

    def assert_unevaluated(self, card: dict) -> None:
        self.assertTrue(card["files_read"])
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("ignore", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], "")
        self.assertEqual(card["tracking"], {"state": "unknown", "reason": "partial"})
        self.assertEqual(card["untracked"], 1)  # unknown exclusion keeps the conservative candidate counter

    def test_an_ignored_direct_bracket_name_is_not_positive_evidence(self) -> None:
        self.write("generated[1].py")
        self.assertEqual(self.repo.git("status", "--porcelain", where=self.tree), "")
        self.assert_unevaluated(self.card())

    def test_an_ignored_bracket_leaf_in_a_plain_folder_is_not_positive_evidence(self) -> None:
        self.write("new-folder/generated[1].py")
        self.assertEqual(self.repo.git("status", "--porcelain", where=self.tree), "")
        self.assert_unevaluated(self.card())

    def test_an_unqueryable_folder_does_not_trust_its_ignored_leaves(self) -> None:
        self.write("output[1]/generated.py")
        self.assertEqual(self.repo.git("status", "--porcelain", where=self.tree), "")
        self.assert_unevaluated(self.card())

    def test_a_nonignored_bracket_name_still_has_unknown_exclusion_state(self) -> None:
        self.write("notes[1].txt")
        self.assertIn("notes[1].txt", self.repo.git("status", "--porcelain", where=self.tree))
        self.assert_unevaluated(self.card())

    def test_an_eligible_old_sibling_does_not_inherit_an_ignored_file_date(self) -> None:
        self.write("new-folder/generated[1].py", self.new)
        self.write("new-folder/visible.txt", self.old)
        card = self.card()
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("ignore", card["file_activity_partial_reasons"])
        self.assertEqual(card["tracking"], {"state": "unknown", "reason": "partial"})

    def test_an_eligible_new_sibling_keeps_positive_evidence_with_the_partial_caveat(self) -> None:
        self.write("new-folder/generated[1].py", NOW - timedelta(minutes=15))
        self.write("new-folder/visible.txt", self.new)
        with runs() as calls:
            card = self.card()
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("ignore", card["file_activity_partial_reasons"])
        self.assertEqual(card["tracking"], {"state": "check", "reason": "settled"})
        self.assertEqual(card["untracked"], 1)
        queries = [command for command, _ in calls if "check-ignore" in command
                   and f"--work-tree={self.tree}" in command]
        self.assertEqual(len(queries), 2)  # existing root and descendant batches, no extra Git process

    def test_a_confirmed_ignored_parent_covers_unqueryable_descendant_names(self) -> None:
        self.repo.commit(self.tree, ".gitignore", "*.py\nnew-folder/skip/\n", "docs: ignored parent", "09:10")
        self.write("new-folder/skip/generated[1].py", self.new)
        self.write("new-folder/visible.txt", self.old)
        card = self.card()
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_partial_reasons"], [])
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        self.assertEqual(card["untracked"], 1)

    def test_a_known_modified_tracked_bracket_name_needs_no_ignore_evaluation(self) -> None:
        path = self.write("tracked[1].py", self.old)
        self.repo.git("add", "-f", path.name, where=self.tree)
        self.repo.git("commit", "-q", "-m", "feat: tracked file", where=self.tree)
        path.write_text("changed work\n", encoding="utf-8")
        self.stamp(path, self.new)
        card = self.card()
        self.assertEqual(card["modified"], 1)
        self.assertEqual(card["untracked"], 0)
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_partial_reasons"], [])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))


if __name__ == "__main__":
    unittest.main()
