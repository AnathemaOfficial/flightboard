# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Observed tracking dates stay separate from declared dates and expose incomplete dating."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain, by_name

files = load("files")
collector_module = load("collector")
Settings = load("config").Settings


class FileActivityMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.tree = self.root / "tree"
        self.tree.mkdir()
        self.old = datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)
        self.new = self.old + timedelta(days=2)

    def file(self, name: str, when: datetime) -> Path:
        path = self.tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("observed work\n", encoding="utf-8")
        os.utime(path, (when.timestamp(), when.timestamp()))
        return path

    def test_plain_files_are_dated_once_and_keep_the_compatibility_result(self) -> None:
        paths = [self.file("old.txt", self.old), self.file("new.txt", self.new)]
        actual_lstat = os.lstat
        observed = []

        def traced(path, *args, **kwargs):
            observed.append(Path(path))
            return actual_lstat(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", traced):
            result = files.last_write_info(self.tree, self.root, [path.name for path in paths])
        self.assertEqual(result, (self.new, True))
        self.assertEqual([observed.count(path) for path in paths], [1, 1])
        self.assertEqual(files.last_write(self.tree, self.root, [path.name for path in paths]), self.new)

    def test_skipped_or_missing_names_make_the_observation_incomplete(self) -> None:
        self.file("new.txt", self.new)
        for missing in ("absent.txt", "../outside.txt", "/absolute.txt"):
            with self.subTest(missing=missing):
                self.assertEqual(files.last_write_info(self.tree, self.root, ["new.txt", missing]),
                                 (self.new, False))

    def test_a_directory_time_is_not_complete_file_activity(self) -> None:
        folder = self.tree / "generated"
        folder.mkdir()
        self.file("generated/new.txt", self.new)
        os.utime(folder, (self.old.timestamp(), self.old.timestamp()))
        self.assertEqual(files.last_write_info(self.tree, self.root, ["generated/"]), (self.old, False))

    def test_the_dating_cap_keeps_the_unread_newest_file_unknown(self) -> None:
        paths = [self.file(f"file-{number}.txt", self.old) for number in range(files.MAX_DATED)]
        newest = self.file("beyond-cap.txt", self.new)
        actual_lstat = os.lstat
        observed = []

        def traced(path, *args, **kwargs):
            observed.append(Path(path))
            return actual_lstat(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", traced):
            result = files.last_write_info(self.tree, self.root, [path.name for path in paths] + [newest.name])
        self.assertEqual(result, (self.old, False))
        self.assertNotIn(newest, observed)

    def test_a_tree_outside_the_boundary_is_never_dated(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "new.txt").write_text("not authorized\n", encoding="utf-8")
        self.assertEqual(files.last_write_info(elsewhere, self.tree, ["new.txt"]), (None, False))

    def test_an_unrepresentable_date_is_incomplete(self) -> None:
        self.file("new.txt", self.new)
        broken = mock.Mock(fromtimestamp=mock.Mock(side_effect=OSError(22, "date out of range")))
        with mock.patch.object(files, "datetime", broken):
            self.assertEqual(files.last_write_info(self.tree, self.root, ["new.txt"]), (None, False))


@unittest.skipIf(GIT is None, "git absent")
class CollectorTrackingMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        contents = {"updated_at": "2026-11-01", "tasks": [
            {"id": "LOT-1", "title": "A declared lot", "owner": "codex", "status": "planned"}]}
        self.repo.commit(self.repo.root, "tasks.json", json.dumps(contents), "docs: declare lot", "08:40")
        self.tree = self.repo.worktree("lot-1", "codex/lot-1")
        self.old = NOW - timedelta(days=2)
        self.new = NOW - timedelta(hours=1)
        self.ledger = self.tree / "tasks.json"
        os.utime(self.ledger, (self.old.timestamp(), self.old.timestamp()))
        self.reader = collector_module.Collector(self.repo.root, Settings(ledger="tasks", ledger_path="tasks.json"))

    def card(self) -> dict:
        state = self.reader.snapshot(NOW)
        self.assertEqual(state["main"]["state"], "ok", state["main"])
        return by_name(state)[self.tree.name]

    def test_observed_ledger_and_file_times_remain_distinct_from_the_declared_date(self) -> None:
        work = self.tree / "app.py"
        work.write_text("print('new activity')\n", encoding="utf-8")
        os.utime(work, (self.new.timestamp(), self.new.timestamp()))
        actual = files.activity_info
        dated_trees = []

        def traced(tree, root, *rest):
            dated_trees.append(tree)
            return actual(tree, root, *rest)

        with mock.patch.object(files, "activity_info", traced):
            card = self.card()
        self.assertEqual(card["last_write"], self.new.isoformat(timespec="seconds"))
        self.assertEqual(card["ledger_file_modified_at"], self.old.isoformat(timespec="seconds"))
        self.assertEqual(card["updated_at"], "2026-11-01")
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(dated_trees.count(self.tree), 1)

    def test_invalid_or_missing_working_ledgers_have_no_trusted_save_time(self) -> None:
        for content in ("not json", '{"tasks":[{"id":"LOT-1","status":"unknown"}]}'):
            with self.subTest(content=content):
                self.ledger.write_text(content, encoding="utf-8")
                card = self.card()
                self.assertEqual(card["ledger_file_modified_at"], "")
        self.ledger.unlink()
        self.assertEqual(self.card()["ledger_file_modified_at"], "")

    def test_deletions_do_not_get_an_invented_activity_time(self) -> None:
        (self.tree / "app.py").unlink()
        card = self.card()
        self.assertEqual(card["last_write"], "")
        self.assertFalse(card["file_activity_complete"])
        self.assertEqual(card["ledger_file_modified_at"], self.old.isoformat(timespec="seconds"))

    def test_an_enumerated_untracked_directory_has_a_complete_file_date(self) -> None:
        folder = self.tree / "new-folder"
        folder.mkdir()
        leaf = folder / "notes.txt"
        leaf.write_text("new untracked work\n", encoding="utf-8")
        os.utime(leaf, (self.old.timestamp(), self.old.timestamp()))
        os.utime(folder, (self.new.timestamp(), self.new.timestamp()))
        card = self.card()
        self.assertEqual(card["last_write"], self.new.isoformat(timespec="seconds"))
        self.assertTrue(card["file_activity_complete"])
        self.assertEqual(card["file_activity_observed_at"], self.old.isoformat(timespec="seconds"))

    def test_merge_and_refused_worktrees_have_no_observed_ledger_time(self) -> None:
        git_dir = self.repo.root / ".git" / "worktrees" / self.tree.name
        (git_dir / "MERGE_HEAD").write_text(self.repo.git("rev-parse", "main") + "\n", encoding="ascii")
        merging = self.card()
        self.assertEqual(merging["ledger"], "merging")
        self.assertEqual(merging["ledger_file_modified_at"], "")
        (git_dir / "MERGE_HEAD").unlink()

        reader = collector_module.Collector(self.repo.root, Settings(worktrees=(("other",),), ledger="tasks"))
        state = reader.snapshot(NOW)
        refused = by_name(state)[self.tree.name]
        self.assertFalse(refused["files_read"])
        self.assertEqual(refused["ledger_file_modified_at"], "")
        self.assertFalse(refused["file_activity_complete"])
