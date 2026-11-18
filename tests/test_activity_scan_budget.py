# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Complete ordinary source-tree dating within shared work and fallback-I/O bounds."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain, by_name

files = load("files")
collector_module = load("collector")
gitreads = load("gitreads")
Settings = load("config").Settings


class ObservedActivityTest(unittest.TestCase):
    def test_failed_legacy_lookups_are_not_retried_before_a_later_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            late = root / "late.py"
            late.write_text("new work\n", encoding="utf-8")
            new = NOW - timedelta(hours=1)
            os.utime(late, (new.timestamp(), new.timestamp()))
            actual = files.os.lstat
            attempted = []

            def lstat(path, *args, **kwargs):
                if Path(path).parent == root:
                    attempted.append(Path(path).name)
                return actual(path, *args, **kwargs)

            with mock.patch.object(files, "MAX_DATED", 3), mock.patch.object(files.os, "lstat", lstat):
                result = files.activity_info(root, root, ["missing.py", "absent.py"],
                                             ["missing.py", "absent.py", "late.py"], {}, set())
            self.assertEqual(attempted, ["missing.py", "absent.py", "late.py"])
            self.assertEqual(result["observed"], new)
            self.assertEqual(result["reasons"], ["unreadable"])

    def test_already_observed_leaves_beyond_two_hundred_need_no_fallback_stat(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new = NOW - timedelta(days=2), NOW - timedelta(hours=1)
            names, observed = [], {}
            for number in range(240):
                path = root / f"work-{number:03}.py"
                path.write_text("work\n", encoding="utf-8")
                when = new if number == 239 else old
                os.utime(path, (when.timestamp(), when.timestamp()))
                names.append(path.name)
                observed[path.name] = path.stat()
            with mock.patch.object(files.os, "lstat", side_effect=AssertionError("metadata already observed")):
                result = files.activity_info(root, root, [], names, observed, set())
            self.assertTrue(result["complete"], result)
            self.assertEqual(result["observed"], new)
            self.assertEqual(result["reasons"], [])

    def test_failed_fallbacks_spend_the_same_allowance_and_do_not_hide_cached_late_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = root / "late.py"
            latest.write_text("latest\n", encoding="utf-8")
            new = NOW - timedelta(hours=1)
            os.utime(latest, (new.timestamp(), new.timestamp()))
            observed = {"late.py": latest.stat()}
            names = [f"missing-{number:03}.py" for number in range(230)] + ["late.py"]
            actual = files.os.lstat
            attempted = []

            def lstat(path, *args, **kwargs):
                if Path(path).name.startswith("missing-"):
                    attempted.append(Path(path).name)
                return actual(path, *args, **kwargs)

            with mock.patch.object(files.os, "lstat", lstat):
                result = files.activity_info(root, root, [], names, observed, set())
            self.assertFalse(result["complete"])
            self.assertIn("limit", result["reasons"])
            self.assertIn("unreadable", result["reasons"])
            self.assertEqual(len(attempted), 200)
            self.assertEqual(result["observed"], new)

    def test_legacy_and_trusted_dates_share_the_extra_metadata_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = [f"work-{number:03}.py" for number in range(220)]
            for name in names:
                (root / name).write_text("work\n", encoding="utf-8")
            actual = files.os.lstat
            attempted = []

            def lstat(path, *args, **kwargs):
                if Path(path).name.startswith("work-"):
                    attempted.append(Path(path).name)
                return actual(path, *args, **kwargs)

            with mock.patch.object(files.os, "lstat", lstat):
                result = files.activity_info(root, root, names[:150], names, {}, set())
            self.assertFalse(result["complete"])
            self.assertIn("limit", result["reasons"])
            self.assertEqual(len(attempted), 200)
            self.assertEqual(len(set(attempted)), 200)


class SharedTraversalBudgetTest(unittest.TestCase):
    def test_disappearing_prefix_entry_keeps_the_known_exhaustion_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "work"
            folder.mkdir()
            leaf = folder / "work.py"
            leaf.write_text("work\n", encoding="utf-8")
            actual = files._entry_info

            def vanished(entry):
                Path(entry.path).unlink()

                class FreshEntry:
                    name, path = entry.name, entry.path

                    @staticmethod
                    def stat(*, follow_symlinks=False):
                        return os.stat(entry.path, follow_symlinks=follow_symlinks)

                return actual(FreshEntry())  # Windows DirEntry may retain metadata from its directory listing

            reasons = set()
            with mock.patch.object(files, "_entry_info", vanished):
                found = files.children(root, root, "work/", budget=files.Budget(entries=1), reasons=reasons)
            self.assertIsNone(found)
            self.assertEqual(reasons, {"limit"})

    def test_directory_iterator_is_bounded_and_observed_prefix_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "work"
            folder.mkdir()
            later = root / "later"
            later.mkdir()
            for number in range(20):
                (folder / f"work-{number:02}.py").write_text("work\n", encoding="utf-8")
                (later / f"work-{number:02}.py").write_text("work\n", encoding="utf-8")
            actual = files.os.scandir
            consumed, opened = [], []

            @contextlib.contextmanager
            def scandir(path):
                opened.append(Path(path))
                with actual(path) as entries:
                    def records():
                        for entry in entries:
                            consumed.append(entry.name)
                            yield entry
                    yield records()

            observations, reasons = {}, set()
            budget = files.Budget(entries=3)
            with mock.patch.object(files, "MAX_LIST_ENTRIES", 5), mock.patch.object(files.os, "scandir", scandir):
                found = files.children(root, root, "work/", budget=budget,
                                       observations=observations, reasons=reasons)
                next_found = files.children(root, root, "later/", budget=budget,
                                            observations=observations, reasons=reasons)
            self.assertEqual(len(consumed), 3)
            self.assertEqual(opened, [folder])
            self.assertEqual(budget.left, 0)
            self.assertIsNotNone(found)
            self.assertEqual(len(found["leaves"]), 3)
            self.assertEqual(len(observations), 3)
            self.assertFalse(found["complete"])
            self.assertFalse(next_found["complete"])
            self.assertEqual(next_found["leaves"], [])
            self.assertEqual(reasons, {"limit"})
            self.assertFalse(files.all_ignored(found, set(found["leaves"])))

    def test_deadline_interrupts_directory_iteration_before_the_next_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "work"
            folder.mkdir()
            for number in range(20):
                (folder / f"work-{number:02}.py").write_text("work\n", encoding="utf-8")
            actual = files.os.scandir
            budget = files.Budget(entries=30)
            consumed = []

            @contextlib.contextmanager
            def scandir(path):
                with actual(path) as entries:
                    def records():
                        for entry in entries:
                            consumed.append(entry.name)
                            budget.deadline = 0
                            yield entry
                    yield records()

            with mock.patch.object(files.os, "scandir", scandir):
                with self.assertRaises(files.ReadingTooLong):
                    files.children(root, root, "work/", budget=budget)
            self.assertEqual(len(consumed), 1)

    def test_exhaustion_stops_before_listing_the_next_candidate_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("first", "second"):
                (root / name).mkdir()
                (root / name / "work.py").write_text("work\n", encoding="utf-8")
            budget = files.Budget(entries=1)
            reasons = set()
            first = files.children(root, root, "first/", budget=budget, reasons=reasons)
            self.assertEqual(first["leaves"], ["first/work.py"])
            actual = files._entries
            listed = []

            def entries(path, **kwargs):
                listed.append(Path(path))
                return actual(path, **kwargs)

            with mock.patch.object(files, "_entries", entries):
                second = files.children(root, root, "second/", budget=budget, reasons=reasons)
            self.assertFalse(second["complete"])
            self.assertEqual(second["leaves"], [])
            self.assertEqual(listed, [])
            self.assertEqual(reasons, {"limit"})

    def test_expired_deadline_stops_before_another_directory_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "work").mkdir()
            budget = files.Budget(entries=20, deadline=0)
            with mock.patch.object(files, "_entries", side_effect=AssertionError("expired traversal listed")):
                with self.assertRaises(files.ReadingTooLong):
                    files.children(root, root, "work/", budget=budget)

    def test_deadline_is_checked_between_entry_metadata_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "work"
            folder.mkdir()
            for name in ("first.py", "second.py", "third.py"):
                (folder / name).write_text("work\n", encoding="utf-8")
            budget = files.Budget(entries=20)
            observed = {}
            actual = files._entry_info

            def info(entry):
                result = actual(entry)
                budget.deadline = 0
                return result

            with mock.patch.object(files, "_entry_info", info):
                with self.assertRaises(files.ReadingTooLong):
                    files.children(root, root, "work/", budget=budget, observations=observed)
            self.assertEqual(len(observed), 1)
            self.assertLess(budget.left, 20)


@unittest.skipIf(GIT is None, "git absent")
class SourceTreeActivityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.repo.commit(self.repo.root, "tasks.json", json.dumps({"tasks": [
            {"id": "LOT-1", "status": "awaiting_review"}]}), "docs: lot", "08:40")
        self.tree = self.repo.worktree("lot-1", "codex/lot-1")
        self.old, self.new = NOW - timedelta(days=2), NOW - timedelta(hours=1)
        self.stamp(self.tree / "tasks.json", self.old)
        self.reader = collector_module.Collector(self.repo.root, Settings(ledger="tasks", read_seconds=60))

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

    def test_three_hundred_source_leaves_are_complete_in_one_bounded_traversal(self) -> None:
        for number in range(300):
            self.write(f"evidence/run-{number:03}.json", self.old)
        newest = self.write("evidence/zz-current.json", self.new)
        self.stamp(newest.parent, self.old)
        card = self.card()
        self.assertTrue(card["file_activity_complete"], card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))
        self.assertEqual(card["untracked"], 1)

    def test_normal_six_level_source_tree_is_not_a_depth_truncation(self) -> None:
        self.write("evidence/lot/final/reviews/model/checks/result.json")
        card = self.card()
        self.assertTrue(card["file_activity_complete"], card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))

    def test_a_candidate_folder_replaced_before_listing_is_not_treated_as_empty(self) -> None:
        folder = self.tree / "source"
        folder.mkdir()
        actual = files.os.scandir
        replaced = []

        def scandir(path):
            if Path(path) == folder and not replaced:
                folder.rmdir()
                folder.write_text("new ordinary work\n", encoding="utf-8")
                self.stamp(folder, self.new)
                replaced.append(folder)
            return actual(path)

        with mock.patch.object(files.os, "scandir", scandir):
            card = self.card()
        self.assertEqual(replaced, [folder])
        self.assertTrue(folder.is_file())
        self.assertTrue(card["files_read"])
        self.assertEqual(card["untracked"], 1)
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("folder", card["file_activity_partial_reasons"])
        recovered = self.card()
        self.assertEqual(recovered["untracked"], 1)
        self.assertTrue(recovered["file_activity_complete"])
        self.assertEqual(recovered["file_activity_partial_reasons"], [])
        self.assertEqual(recovered["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))

    def test_an_ignored_candidate_root_is_pruned_without_listing_its_children(self) -> None:
        self.repo.commit(self.tree, ".gitignore", "generated/\n", "docs: exclusions", "09:00")
        self.write("generated/private.log")
        self.write("source/current.py", self.old)
        actual = files._entries

        def entries(path, **kwargs):
            if Path(path) == self.tree / "generated":
                raise AssertionError("ignored root must not be enumerated")
            return actual(path, **kwargs)

        with mock.patch.object(files, "_entries", entries):
            card = self.card()
        self.assertTrue(card["file_activity_complete"], card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        self.assertEqual(card["untracked"], 1)

    def test_separate_candidate_folders_share_one_scan_entry_budget(self) -> None:
        for folder in ("first", "second"):
            for number in range(20):
                self.write(f"{folder}/work-{number:02}.py", self.old)
        with mock.patch.object(files, "MAX_ACTIVITY_ENTRIES", 30, create=True):
            card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("limit", card["file_activity_partial_reasons"])
        self.assertEqual(card["untracked"], 2)

    def test_failed_descendant_ignore_batch_does_not_trust_nested_dates(self) -> None:
        changed = self.tree / "app.py"
        changed.write_text("changed\n", encoding="utf-8")
        self.stamp(changed, self.old)
        self.write("source/work.py", self.new)
        self.write("direct.py", self.old)
        actual = gitreads.Git.ignored

        def ignored(git, git_dir, work_tree, paths):
            if work_tree == self.tree and "source/work.py" in paths:
                raise gitreads.GitFailed("descendant batch unavailable")
            return actual(git, git_dir, work_tree, paths)

        with mock.patch.object(gitreads.Git, "ignored", ignored):
            card = self.card()
        self.assertFalse(card["file_activity_complete"])
        self.assertIn("ignore", card["file_activity_partial_reasons"])
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        self.assertEqual((card["modified"], card["untracked"]), (1, 2))

    def test_same_reader_rechecks_an_ignored_root_after_rules_change(self) -> None:
        self.repo.commit(self.tree, ".gitignore", "generated/\n", "docs: exclusions", "09:00")
        leaf = self.write("generated/result.py", self.new)
        self.write("source/old.py", self.old)
        first = self.card()
        self.assertEqual(first["untracked"], 1)
        self.assertEqual(first["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))
        (self.tree / ".gitignore").write_text("# no exclusions\n", encoding="utf-8")
        self.stamp(self.tree / ".gitignore", self.old)
        self.stamp(leaf.parent, self.old)
        second = self.card()
        self.assertEqual(second["untracked"], 2)
        self.assertTrue(second["file_activity_complete"])
        self.assertEqual(second["file_activity_observed_at"], self.new.isoformat(timespec="seconds"))


if __name__ == "__main__":
    unittest.main()
