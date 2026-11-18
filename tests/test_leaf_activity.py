# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Bounded ordinary-file observations reuse the existing untracked-directory traversal."""
from __future__ import annotations

import json
import os
import unittest
from collections import Counter
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_files import make_link
from tests.test_modes import Plain, by_name

files = load("files")
collector_module = load("collector")
gitreads = load("gitreads")
Settings = load("config").Settings


@unittest.skipIf(GIT is None, "git absent")
class LeafActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.repo.commit(self.repo.root, "tasks.json", json.dumps({"tasks": [
            {"id": "LOT-1", "title": "Declared work", "status": "awaiting_review"}]}), "docs: lot", "08:40")
        self.tree = self.repo.worktree("lot-1", "codex/lot-1")
        self.old, self.new = NOW - timedelta(days=2), NOW - timedelta(hours=1)
        self.stamp(self.tree / "tasks.json", self.old)
        self.reader = collector_module.Collector(self.repo.root, Settings(ledger="tasks", read_seconds=60))

    @staticmethod
    def stamp(path: Path, value) -> None:
        os.utime(path, (value.timestamp(), value.timestamp()))

    def new_file(self, name: str, when=None) -> Path:
        path = self.tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("work\n", encoding="utf-8")
        self.stamp(path, when or self.new)
        return path

    def card(self) -> dict:
        state = self.reader.snapshot(NOW)
        self.assertEqual(state["main"]["state"], "ok", state["main"])
        return by_name(state)[self.tree.name]

    def test_recent_leaf_under_an_old_directory_is_complete_without_restat_or_walk(self) -> None:
        leaf = self.new_file("new-folder/work.py")
        folder = leaf.parent
        self.stamp(folder, self.old)
        actual_entries, actual_lstat = files._entries, files.os.lstat
        stats, walks, lstats = Counter(), Counter(), Counter()

        class Entry:
            def __init__(self, value):
                self.value = value

            def __getattr__(self, name):
                return getattr(self.value, name)

            def stat(self, **kwargs):
                stats[Path(self.value.path)] += 1
                return self.value.stat(**kwargs)

        def entries(path, **kwargs):
            found = actual_entries(path, **kwargs)
            walks[Path(path)] += 1
            return [Entry(entry) for entry in found] if found is not None else None

        def lstat(path, *args, **kwargs):
            lstats[Path(path)] += 1
            return actual_lstat(path, *args, **kwargs)

        with mock.patch.object(files, "_entries", entries), mock.patch.object(files.os, "lstat", lstat):
            card = self.card()
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_partial_reasons"], [])
        self.assertEqual(card["last_write"], self.old.isoformat(timespec="seconds"))
        self.assertEqual(card["untracked"], 1)
        self.assertEqual((walks[folder], stats[leaf], lstats[leaf]), (1, 1, 0))

    def test_ignored_parent_and_leaf_cannot_supply_positive_activity(self) -> None:
        self.repo.commit(self.tree, ".gitignore", "new-folder/skip/\nnew-folder/*.tmp\n", "docs: exclusions", "09:00")
        self.new_file("new-folder/visible.py", self.old)
        self.new_file("new-folder/skip/private.py", self.new)
        self.new_file("new-folder/generated.tmp", self.new)
        self.stamp(self.tree / "new-folder", self.old)
        card = self.card()
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["untracked"], 1)

    def test_a_leaf_is_read_again_by_the_same_collector_without_directory_time_change(self) -> None:
        leaf = self.new_file("new-folder/work.py", self.old)
        self.stamp(leaf.parent, self.old)
        self.assertEqual(self.card()["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        leaf.write_text("later work\n", encoding="utf-8")
        self.stamp(leaf, self.new)
        self.stamp(leaf.parent, self.old)
        current = self.card()
        self.assertEqual(current["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))
        self.assertTrue(current["file_activity_complete"])

    def test_flattened_files_reuse_observations_beyond_the_fallback_dating_cap(self) -> None:
        for number in range(199):
            self.new_file(f"tracked-{number:03}.py", self.old)
        self.repo.git("add", "-A", where=self.tree)
        self.repo.git("commit", "-q", "-m", "feat: base files", where=self.tree)
        for number in range(199):
            path = self.tree / f"tracked-{number:03}.py"
            path.write_text("changed\n", encoding="utf-8")
            self.stamp(path, self.old)
        self.new_file("new-folder/a.py", self.new)
        self.new_file("new-folder/b.py", self.new)
        card = self.card()
        self.assertEqual((card["modified"], card["untracked"]), (199, 1))
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_partial_reasons"], [])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))

    def test_depth_and_nested_git_stay_incomplete_without_directory_evidence(self) -> None:
        self.new_file("new-folder/a/b/c/d/e/f/g/h/work.py")
        card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("depth", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], "")
        nested = self.tree / "other-repo"
        nested.mkdir()
        (nested / ".git").write_text("never opened\n", encoding="utf-8")
        card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("folder", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], "")

    def test_large_historical_folders_do_not_hide_a_direct_candidate(self) -> None:
        for number in range(2001):
            self.new_file(f"historical/{number:03}.json", self.old)
        self.new_file("zz-new-work.py", self.new)
        card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("limit", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))

    def test_failed_ignore_checks_do_not_trust_new_candidates(self) -> None:
        self.new_file("new-folder/work.py")
        with mock.patch.object(gitreads.Git, "ignored", side_effect=gitreads.GitFailed("unavailable")):
            card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("ignore", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], "")

    def test_deletions_remain_explicitly_partial(self) -> None:
        (self.tree / "app.py").unlink()
        card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("deleted", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], "")

    def test_retained_metadata_does_not_grow_with_unchanged_tracked_files(self) -> None:
        for number in range(250):
            self.new_file(f"unchanged-{number:03}.py", self.old)
        self.repo.git("add", "-A", where=self.tree)
        self.repo.git("commit", "-q", "-m", "feat: unchanged files", where=self.tree)
        changed = self.tree / "app.py"
        changed.write_text("changed\n", encoding="utf-8")
        self.stamp(changed, self.new)
        self.new_file("new-folder/work.py", self.old)
        actual = files.untracked
        retained = []

        def traced(tree, root, tracked, *args, **kwargs):
            result = actual(tree, root, tracked, *args, **kwargs)
            if tree == self.tree:
                retained.append(set(kwargs["observations"]))
            return result

        with mock.patch.object(files, "untracked", traced):
            card = self.card()
        self.assertEqual(retained, [{"app.py", "new-folder"}])
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))

    def test_a_linked_child_is_not_followed_or_dated(self) -> None:
        outside = self.repo.root / "elsewhere"
        outside.mkdir()
        (outside / "private.py").write_text("not authorized\n", encoding="utf-8")
        parent = self.tree / "new-folder"
        parent.mkdir()
        if not make_link(outside, parent / "link"):
            self.skipTest("this system does not let the test make a link")
        card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertEqual(card["file_activity_observed_at"], "")


if __name__ == "__main__":
    unittest.main()
