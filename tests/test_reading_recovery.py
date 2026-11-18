# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Independent scan failures, guarded prefixes and file-time ordering survive one reading."""
from __future__ import annotations

import contextlib
import io
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
cli = load("cli")


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
                result = actual(reader, item, planted, git)
                clock[0] = 2.0
                return result
            return actual(reader, item, planted, git)

        with mock.patch.object(collector_module.time, "monotonic", lambda: clock[0]), \
                mock.patch.object(collector_module.Collector, "_read_files_of", read_files):
            card = self.card()
        self.assertTrue(written)
        self.assertEqual(card["tracking"], {"state": "check", "reason": "settled"})

    def test_live_completion_clock_handles_forward_and_backward_wall_clock_adjustments(self) -> None:
        actual = collector_module.Collector._read_files_of
        cases = ((timedelta(minutes=1), timedelta(seconds=30), {"state": "check", "reason": "settled"}),
                 (-timedelta(minutes=1), timedelta(seconds=1), {"state": "unknown", "reason": "dates"}))
        for adjustment, file_offset, expected in cases:
            with self.subTest(adjustment=adjustment):
                self.write("current.txt", NOW + file_offset)
                monotonic, wall = [0.0], [NOW]

                def read_files(reader, item, planted, git):
                    result = actual(reader, item, planted, git)
                    if item["path"] == self.tree:
                        wall[0], monotonic[0] = NOW + adjustment, 2.0
                    return result

                reader = collector_module.Collector(self.repo.root, self.reader.settings,
                                                    completion_clock=lambda: wall[0])
                with mock.patch.object(collector_module.time, "monotonic", lambda: monotonic[0]), \
                        mock.patch.object(collector_module.Collector, "_read_files_of", read_files):
                    state = reader.snapshot(NOW)
                self.assertEqual(state["main"]["state"], "ok", state["main"])
                self.assertEqual(state["generated_at"], NOW.isoformat(timespec="seconds"))
                self.assertEqual(by_name(state)[self.tree.name]["tracking"], expected)

    def test_live_completion_clock_keeps_dates_after_completion_unknown(self) -> None:
        self.write("current.txt", NOW + timedelta(seconds=3))
        reader = collector_module.Collector(self.repo.root, self.reader.settings,
                                            completion_clock=lambda: NOW + timedelta(seconds=2))
        state = reader.snapshot(NOW)
        self.assertEqual(by_name(state)[self.tree.name]["tracking"], {"state": "unknown", "reason": "dates"})

    def test_live_server_supplies_the_completion_wall_clock_to_its_collector(self) -> None:
        self.write("current.txt", NOW + timedelta(seconds=30))
        actual_snapshots, states = cli.SERVER.Snapshots, []

        class Server:
            def __init__(self, snapshots):
                self.snapshots = snapshots

            def serve_forever(self, **kwargs):
                states.append(self.snapshots.get())

            def server_close(self):
                pass

        def snapshots(collector):
            return actual_snapshots(collector, now=lambda: NOW)

        def servers(snapshots, template, port, lang):
            return [Server(snapshots)]

        with mock.patch.object(cli.SERVER, "now_local", lambda: NOW + timedelta(minutes=1)), \
                mock.patch.object(cli.SERVER, "Snapshots", snapshots), \
                mock.patch.object(cli.SERVER, "make_servers", servers), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._serve(self.repo.root, self.reader.settings, 0), 0)
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0]["generated_at"], NOW.isoformat(timespec="seconds"))
        self.assertEqual(by_name(states[0])[self.tree.name]["tracking"], {"state": "check", "reason": "settled"})


@unittest.skipIf(GIT is None, "git absent")
class LiveParallelClockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Plain()
        cls.addClassCleanup(cls.repo.close)
        cls.trees = [cls.repo.worktree(f"clock-{number}", f"clock-{number}") for number in range(8)]
        for number, tree in enumerate(cls.trees):
            cls.repo.commit(tree, "app.py", f"print({number + 10})\n", f"clock worker {number}", "09:00")
        cls.settings = Settings(read_seconds=60)

    def reader(self):
        return collector_module.Collector(self.repo.root, self.settings, completion_clock=lambda: NOW)

    def test_live_clock_keeps_real_parallel_reads_and_unchanged_snapshot_semantics(self) -> None:
        with mock.patch.object(collector_module, "PARALLEL_MIN", 100_000):
            sequential = self.reader().snapshot(NOW)
        actual, forks = gitreads.Git.fork, []

        def fork(git):
            child = actual(git)
            forks.append(child)
            return child

        with mock.patch.object(gitreads.Git, "fork", fork):
            parallel = self.reader().snapshot(NOW)
        self.assertEqual(parallel["main"]["state"], "ok", parallel["main"])
        self.assertTrue(forks, "the live completion clock silently disabled parallel reads")
        self.assertEqual(parallel, sequential)

    def test_custom_instance_operation_stays_sequential_with_the_live_clock(self) -> None:
        reader = self.reader()
        actual_read, actual_fork, forks, read_ids = reader._read_files_of, gitreads.Git.fork, [], []

        def read(item, planted, git):
            read_ids.append(item["id"])
            return actual_read(item, planted, git)

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        with mock.patch.object(reader, "_read_files_of", read), mock.patch.object(gitreads.Git, "fork", fork):
            state = reader.snapshot(NOW)
        self.assertEqual(state["main"]["state"], "ok", state["main"])
        self.assertTrue(read_ids)
        self.assertTrue(all(card["files_read"] for card in state["sessions"]))
        self.assertEqual(forks, [], "a custom instance operation must not leak into forked reads")


if __name__ == "__main__":
    unittest.main()
