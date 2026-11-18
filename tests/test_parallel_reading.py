# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Bounded parallel reads keep snapshot state, refusal behavior and fresh file observations."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain

collector_module = load("collector")
gitreads = load("gitreads")
Settings = load("config").Settings


class ParallelRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.reader = collector_module.Collector(Path(self.temporary.name).resolve())

    def test_git_forks_keep_the_snapshot_context_without_mutable_runner_state(self) -> None:
        git = self.reader.git
        git.blank = ("-c", "filter.example.clean=")
        git.graph, git.deadline = True, time.monotonic() + 12
        child = git.fork()
        self.assertIsNot(child, git)
        self.assertEqual((child.remote, child.blank, child.graph, child.deadline),
                         (git.remote, git.blank, git.graph, git.deadline))
        git.blank, git.graph, git.deadline = (), False, None
        self.assertEqual(child.blank, ("-c", "filter.example.clean="))
        self.assertTrue(child.graph)
        self.assertIsNotNone(child.deadline)
        self.assertLessEqual(child.time_left(), gitreads.GIT_TIMEOUT)

    def test_pool_is_bounded_and_results_keep_input_order(self) -> None:
        barrier = threading.Barrier(collector_module.READ_WORKERS)
        lock = threading.Lock()
        active, peak, threads = 0, 0, set()
        parent = threading.get_ident()

        def read(job, git):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                threads.add(threading.get_ident())
            try:
                barrier.wait(timeout=5)
                return job * 2
            finally:
                with lock:
                    active -= 1

        jobs = list(range(collector_module.PARALLEL_MIN))
        values = self.reader._parallel_results(jobs, read)
        self.assertEqual([(job, value) for job, value, error in values], [(job, job * 2) for job in jobs])
        self.assertTrue(all(error is None for _, _, error in values))
        self.assertEqual(peak, collector_module.READ_WORKERS)
        self.assertNotIn(parent, threads)
        self.assertEqual(active, 0)

    def test_custom_or_instance_modified_git_is_left_sequential(self) -> None:
        jobs = list(range(collector_module.PARALLEL_MIN))
        with mock.patch.object(self.reader.git, "status") as status:
            self.assertEqual(self.reader._parallel_results(jobs, status), [])
            status.assert_not_called()

        class CustomGit(gitreads.Git):
            pass

        self.reader.git = CustomGit()
        read = mock.Mock()
        self.assertEqual(self.reader._parallel_results(jobs, read), [])
        read.assert_not_called()

    def test_a_slow_first_job_does_not_stop_unrelated_queued_reads(self) -> None:
        later_started = threading.Event()

        def read(job, git):
            if job == 0:
                if not later_started.wait(timeout=3):
                    raise AssertionError("the first read blocked unrelated queued work")
            elif job >= collector_module.READ_WORKERS:
                later_started.set()
            return job * 2

        jobs = list(range(collector_module.PARALLEL_MIN))
        values = self.reader._parallel_results(jobs, read)
        self.assertTrue(all(error is None for _, _, error in values), values)
        self.assertEqual([(job, value) for job, value, _ in values], [(job, job * 2) for job in jobs])

    def test_small_sets_use_the_sequential_path(self) -> None:
        read = mock.Mock()
        self.assertEqual(self.reader._parallel_results(list(range(collector_module.PARALLEL_MIN - 1)), read), [])
        read.assert_not_called()

    def test_deadline_stops_new_submissions_and_drains_running_reads(self) -> None:
        lock = threading.Lock()
        active, started = 0, 0

        def slow(job, git):
            nonlocal active, started
            with lock:
                active += 1
                started += 1
            try:
                time.sleep(0.65)
                return job
            finally:
                with lock:
                    active -= 1

        started_reading = threading.Event()
        actual = slow

        def expire_after_start(job, git):
            self.reader.git.deadline = time.monotonic() - 1
            started_reading.set()
            return actual(job, git)

        with self.assertRaises(gitreads.ReadingTooLong):
            self.reader._parallel_results(list(range(collector_module.PARALLEL_MIN)), expire_after_start)
        self.assertTrue(started_reading.is_set())
        self.assertGreater(started, 0)
        self.assertLessEqual(started, collector_module.READ_WORKERS)
        self.assertEqual(active, 0, "a worker survived the failed reading")

    def test_failed_graph_prefetch_propagates_without_a_sequential_retry(self) -> None:
        main = "a" * 40
        tips = [f"{number:040x}" for number in range(collector_module.PARALLEL_MIN)]
        bad = tips[0]

        failed = gitreads.GitFailed("retry this pair on the next reading")
        attempts = []

        def counts(git, common, base, tip):
            if tip == bad:
                attempts.append(tip)
                raise failed
            return 0, 1

        with mock.patch.object(gitreads.Git, "counts", counts), \
                mock.patch.object(gitreads.Git, "merge_bases", return_value=[main]):
            self.reader._prefetch_pairs(main, tips)
            with self.assertRaises(gitreads.GitFailed) as caught:
                self.reader._pair(main, bad)
        self.assertNotIn((main, bad), self.reader._pairs)
        self.assertEqual(len(self.reader._pairs), len(tips) - 1)
        self.assertIs(caught.exception, failed)
        self.assertEqual(attempts, [bad])

    def test_worker_file_results_are_published_only_when_the_parent_consumes_them(self) -> None:
        jobs = [{"id": str(number), "path": Path(self.temporary.name)}
                for number in range(collector_module.PARALLEL_MIN)]
        threads = set()
        lock = threading.Lock()

        def read(reader, item, planted, git):
            with lock:
                threads.add(threading.get_ident())
            self.assertEqual(reader._tracked, {})
            self.assertEqual(reader._used, set())
            return [], [], "", {item["id"]}, {"last_write": None, "observed": None,
                                               "complete": True, "reasons": []}

        with mock.patch.object(collector_module.Collector, "_read_files_of", read):
            self.reader._prefetch_working_files(jobs, False)
        self.assertEqual(self.reader._tracked, {})
        self.assertNotIn(threading.get_ident(), threads)
        for job in jobs:
            self.assertEqual(self.reader._files_of(job, False),
                             ([], [], "", {"last_write": None, "observed": None,
                                           "complete": True, "reasons": []}))
            self.assertEqual(self.reader._tracked[job["id"]], {job["id"]})
        self.assertEqual(self.reader._prefetched_files, {})


@unittest.skipIf(GIT is None, "git absent")
class ParallelSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Plain()
        cls.addClassCleanup(cls.repo.close)
        cls.trees = [cls.repo.worktree(f"worker-{number}", f"topic-{number}")
                     for number in range(collector_module.PARALLEL_MIN)]
        for number, tree in enumerate(cls.trees):
            cls.repo.commit(tree, "app.py", f"print({number + 10})\n", f"worker {number}", "09:00")
        cls.settings = Settings(read_seconds=60)

    def test_parallel_and_sequential_snapshots_match(self) -> None:
        with mock.patch.object(collector_module, "PARALLEL_MIN", 100_000):
            sequential = collector_module.Collector(self.repo.root, self.settings).snapshot(NOW)
        actual = gitreads.Git.fork
        forks = []

        def fork(git):
            child = actual(git)
            forks.append(child)
            return child

        with mock.patch.object(gitreads.Git, "fork", fork):
            parallel = collector_module.Collector(self.repo.root, self.settings).snapshot(NOW)
        self.assertTrue(forks, "the comparison never exercised parallel reads")
        self.assertEqual(parallel["main"]["state"], "ok", parallel["main"])
        self.assertEqual(parallel, sequential)

    def test_a_failed_pair_is_read_once_and_retried_on_the_next_snapshot(self) -> None:
        main = self.repo.git("rev-parse", "main")
        tip = self.repo.git("rev-parse", "HEAD", where=self.trees[0])
        actual = gitreads.Git.counts
        failed, attempts = True, 0

        def counts(git, common, base, current):
            nonlocal attempts
            if (base, current) == (main, tip):
                attempts += 1
                if failed:
                    raise gitreads.GitFailed("temporarily unavailable graph")
            return actual(git, common, base, current)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "counts", counts):
            first = reader.snapshot(NOW)
            self.assertEqual(first["main"]["state"], "ok", first["main"])
            card = next(card for card in first["sessions"] if card["name"] == self.trees[0].name)
            self.assertEqual(card["reason"], "distance_unreadable")
            self.assertEqual(attempts, 1, "failed prefetch ran again in the sequential path")
            failed = False
            second = reader.snapshot(NOW)
        card = next(card for card in second["sessions"] if card["name"] == self.trees[0].name)
        self.assertTrue(card["files_read"], card)
        self.assertEqual(card["reason"], "")
        self.assertEqual(attempts, 2)

    def test_a_failed_range_is_read_once_and_retried_on_the_next_snapshot(self) -> None:
        main = self.repo.git("rev-parse", "main")
        tip = self.repo.git("rev-parse", "HEAD", where=self.trees[0])
        actual = gitreads.Git.commits
        failed, attempts = True, 0

        def commits(git, common, base, current, limit=gitreads.MAX_COMMITS):
            nonlocal attempts
            if (base, current, limit) == (main, tip, gitreads.MAX_SESSION_COMMITS + 1):
                attempts += 1
                if failed:
                    raise gitreads.GitFailed("temporarily unavailable range")
            return actual(git, common, base, current, limit)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "commits", commits):
            first = reader.snapshot(NOW)
            self.assertEqual(first["main"]["state"], "ok", first["main"])
            card = next(card for card in first["sessions"] if card["name"] == self.trees[0].name)
            self.assertEqual(card["reason"], "commit_history_unreadable")
            self.assertEqual(attempts, 1, "failed prefetch ran again in the sequential path")
            failed = False
            second = reader.snapshot(NOW)
        card = next(card for card in second["sessions"] if card["name"] == self.trees[0].name)
        self.assertTrue(card["files_read"], card)
        self.assertEqual(card["reason"], "")
        self.assertEqual(attempts, 2)

    def test_changed_files_and_ignore_rules_are_read_again_on_refresh(self) -> None:
        reader = collector_module.Collector(self.repo.root, self.settings)
        tree = self.trees[0]
        baseline = reader.snapshot(NOW)
        self.assertEqual(baseline["main"]["state"], "ok", baseline["main"])
        changed, ignored = tree / "app.py", tree / "generated.txt"
        before = changed.read_bytes()
        try:
            changed.write_text("print('new work')\n", encoding="utf-8")
            ignored.write_text("new\n", encoding="utf-8")
            (tree / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
            current = reader.snapshot(NOW)
            card = next(card for card in current["sessions"] if card["name"] == tree.name)
            self.assertTrue(card["files_read"], card)
            self.assertGreater(card["modified"], 0)
            # .gitignore itself is new; generated.txt must remain excluded on this reading.
            self.assertEqual(card["untracked"], 1)
            (tree / ".gitignore").write_text("different-name\n", encoding="utf-8")
            refreshed = reader.snapshot(NOW)
            card = next(card for card in refreshed["sessions"] if card["name"] == tree.name)
            self.assertEqual(card["untracked"], 2)
        finally:
            changed.write_bytes(before)
            ignored.unlink(missing_ok=True)
            (tree / ".gitignore").unlink(missing_ok=True)
        self.assertEqual(reader._prefetched_files, {})

    def test_new_workers_do_not_see_old_tracked_names_and_kept_counts_stay_fresh(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        trees = [repo.worktree(f"kept-{number}", f"kept-{number}")
                 for number in range(collector_module.PARALLEL_MIN)]
        exclude = repo.root / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "kept/\n", encoding="utf-8")
        for tree in trees:
            (tree / "kept").mkdir()
            (tree / "kept" / "retained.txt").write_text("retained work\n", encoding="utf-8")
        reader = collector_module.Collector(repo.root, Settings(read_seconds=60, kept=("kept",)))
        reader._tracked = {tree.name: {"kept/retained.txt"} for tree in trees}
        actual = collector_module.Collector._read_files_of

        def traced(instance, item, planted, git):
            self.assertEqual(instance._tracked, {}, "old tracked names survived into worker reads")
            return actual(instance, item, planted, git)

        with mock.patch.object(collector_module.Collector, "_read_files_of", traced):
            first = reader.snapshot(NOW)
        worktrees = [card for card in first["sessions"] if card["kind"] == "worktree"]
        self.assertEqual(len(worktrees), len(trees))
        self.assertTrue(all(card["files_read"] and card["kept"] == 1 for card in worktrees), worktrees)
        folder = trees[0] / "kept"
        previous_time = folder.stat()
        (folder / "another.txt").write_text("another retained file\n", encoding="utf-8")
        os.utime(folder, ns=(previous_time.st_atime_ns, previous_time.st_mtime_ns))
        second = reader.snapshot(NOW)
        card = next(card for card in second["sessions"] if card["name"] == trees[0].name)
        self.assertTrue(card["files_read"], card)
        self.assertEqual(card["kept"], 2, "retained work was hidden by an old directory timestamp")

    def test_bad_index_is_never_passed_to_status_and_recovers_after_replacement(self) -> None:
        tree = self.trees[0]
        index = self.repo.root / ".git" / "worktrees" / tree.name / "index"
        before = index.read_bytes()
        status = gitreads.Git.status
        called, lock = [], threading.Lock()

        def traced(git, git_dir, work_tree):
            with lock:
                called.append(work_tree)
            return status(git, git_dir, work_tree)

        reader = collector_module.Collector(self.repo.root, self.settings)
        try:
            index.write_bytes(b"not an index\n")
            with mock.patch.object(gitreads.Git, "status", traced):
                bad = reader.snapshot(NOW)
            card = next(card for card in bad["sessions"] if card["name"] == tree.name)
            self.assertFalse(card["files_read"])
            self.assertNotIn(tree, called)
            self.assertNotIn(card.get("advice"), ("ready_to_merge", "ended"))
        finally:
            index.write_bytes(before)
        repaired = reader.snapshot(NOW)
        card = next(card for card in repaired["sessions"] if card["name"] == tree.name)
        self.assertTrue(card["files_read"], card)
        self.assertEqual(reader._prefetched_files, {})
