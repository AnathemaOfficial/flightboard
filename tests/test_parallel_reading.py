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
            self.assertEqual(self.reader._parallel_results([0], status, parallel_eligible=True), [])
            status.assert_not_called()

        class CustomGit(gitreads.Git):
            pass

        self.reader.git = CustomGit()
        read = mock.Mock()
        self.assertEqual(self.reader._parallel_results(jobs, read), [])
        self.assertEqual(self.reader._parallel_results([0], read, parallel_eligible=True), [])
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
        initial_submitted = threading.Event()
        initial_started = threading.Barrier(collector_module.READ_WORKERS)
        expired = threading.Event()
        submitted, deadline_checks = [], []
        active, started = 0, 0
        submit = collector_module.ThreadPoolExecutor.submit
        time_left = gitreads.Git.time_left

        def tracked_submit(pool, read, *args, **kwargs):
            future = submit(pool, read, *args, **kwargs)
            submitted.append(args[0])
            if len(submitted) == collector_module.READ_WORKERS:
                initial_submitted.set()
            return future

        def checked_time_left(git):
            if git is self.reader.git:
                deadline_checks.append(git.deadline)
            return time_left(git)

        def read(job, git):
            nonlocal active, started
            with lock:
                active += 1
                started += 1
            try:
                if not initial_submitted.wait(timeout=5):
                    raise AssertionError("the initial batch was not submitted")
                initial_started.wait(timeout=5)
                if job == 0:
                    self.reader.git.deadline = time.monotonic() - 1
                    expired.set()
                elif not expired.wait(timeout=5):
                    raise AssertionError("the deadline did not expire before the first completion")
                return job
            finally:
                with lock:
                    active -= 1

        with mock.patch.object(collector_module.ThreadPoolExecutor, "submit", tracked_submit), \
                mock.patch.object(gitreads.Git, "time_left", checked_time_left), \
                self.assertRaises(gitreads.ReadingTooLong):
            self.reader._parallel_results(list(range(collector_module.PARALLEL_MIN)), read)
        self.assertTrue(expired.is_set())
        self.assertEqual(submitted, list(range(collector_module.READ_WORKERS)))
        self.assertEqual(len(deadline_checks), collector_module.READ_WORKERS + 1)
        self.assertTrue(all(value is None for value in deadline_checks[:-1]))
        self.assertIsNotNone(deadline_checks[-1])
        self.assertEqual(started, collector_module.READ_WORKERS)
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

    def test_reciprocal_remote_relations_share_the_failed_direction(self) -> None:
        bad = ("a" * 40, "b" * 40)
        relations = [bad, bad[::-1]] + [(f"{number:040x}", f"{number + 100:040x}")
                                       for number in range(collector_module.PARALLEL_MIN - 1)]
        attempts, runners = [], []
        unavailable = gitreads.GitFailed("temporarily unreadable direction")

        def ancestor(git, common, older, newer):
            attempts.append((older, newer))
            runners.append(git)
            if (older, newer) == bad:
                raise unavailable
            return False

        refs = {"refs/remotes/origin/forward": {"sha": bad[0]},
                "refs/remotes/origin/reverse": {"sha": bad[1]}}
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor):
            self.reader._prefetch_remote_relations(relations)
            self.assertIsNone(self.reader._guarded_remote(refs, "refs/heads/forward", bad[1]))
            self.assertIsNone(self.reader._guarded_remote(refs, "refs/heads/reverse", bad[0]))
        self.assertIs(self.reader._ancestor_failures[bad], unavailable)
        self.assertEqual(attempts.count(bad), 1, "reciprocal workers repeated the failed direction")
        self.assertTrue(all(git is not self.reader.git for git in runners),
                        "the reverse of a failed direction fell back to the parent runner")
        self.assertEqual(len(self.reader._ancestors), 2 * (collector_module.PARALLEL_MIN - 1) + 1)

    def test_reciprocal_remote_relations_keep_both_directions_in_forked_readers(self) -> None:
        pairs = [(f"{number + 100:040x}", f"{number + 200:040x}")
                 for number in range(collector_module.PARALLEL_MIN)]
        requested = [direction for pair in pairs for direction in (pair, pair[::-1])]
        attempts, forks = [], []
        actual_fork = gitreads.Git.fork

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def ancestor(git, common, older, newer):
            attempts.append((git, (older, newer)))
            return (older, newer) in pairs

        refs = {f"refs/remotes/origin/{number}": {"sha": older}
                for number, (older, _) in enumerate(requested)}
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                mock.patch.object(gitreads.Git, "fork", fork):
            self.reader._prefetch_remote_relations(requested)
            for number, (_, newer) in enumerate(requested):
                self.assertEqual(self.reader._remote(refs, f"refs/heads/{number}", newer),
                                 "ahead" if number % 2 == 0 else "behind")
        self.assertEqual([pair for _, pair in attempts].count(pairs[0]), 1)
        self.assertEqual(len(attempts), len(requested))
        self.assertTrue(forks, "the reciprocal batch never used forked readers")
        self.assertTrue(all(git is not self.reader.git and any(git is child for child in forks)
                            for git, _ in attempts), "a reciprocal read fell back to the parent runner")
        self.assertEqual(set(self.reader._ancestors), set(requested))

    def test_reciprocal_remote_relations_retain_a_failed_reverse_after_a_true_forward(self) -> None:
        pair = ("a" * 40, "b" * 40)
        requested = [pair, pair[::-1]] + [(f"{number:040x}", f"{number + 100:040x}")
                                         for number in range(collector_module.PARALLEL_MIN - 1)]
        unavailable = gitreads.GitFailed("temporarily unreadable reverse direction")
        attempts = []

        def ancestor(git, common, older, newer):
            attempts.append((git, (older, newer)))
            if (older, newer) == pair[::-1]:
                raise unavailable
            return True

        refs = {"refs/remotes/origin/forward": {"sha": pair[0]},
                "refs/remotes/origin/reverse": {"sha": pair[1]}}
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor):
            self.reader._prefetch_remote_relations(requested)
            self.assertEqual(self.reader._remote(refs, "refs/heads/forward", pair[1]), "ahead")
            self.assertIsNone(self.reader._guarded_remote(refs, "refs/heads/reverse", pair[0]))
        self.assertIs(self.reader._ancestors[pair], True)
        self.assertIs(self.reader._ancestor_failures[pair[::-1]], unavailable)
        self.assertTrue(all(git is not self.reader.git for git, _ in attempts))
        self.assertEqual([direction for _, direction in attempts].count(pair[::-1]), 1)

    def test_a_single_requested_ancestry_orientation_stops_after_a_true_result(self) -> None:
        pairs = [(f"{number:040x}", f"{number + 100:040x}")
                 for number in range(collector_module.PARALLEL_MIN)]
        attempts = []

        def ancestor(git, common, older, newer):
            attempts.append((older, newer))
            return True

        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor):
            self.reader._prefetch_remote_relations(pairs)
        self.assertCountEqual(attempts, pairs)
        self.assertEqual(set(self.reader._ancestors), set(pairs))

    def test_later_reciprocal_prefetch_reuses_direction_failures_without_parent_reads(self) -> None:
        pairs = [(f"{number + 100:040x}", f"{number + 200:040x}")
                 for number in range(collector_module.PARALLEL_MIN)]
        reverse = [pair[::-1] for pair in pairs]
        unavailable = {pair: gitreads.GitFailed(f"temporarily unreadable direction {number}")
                       for number, pair in enumerate(pairs)}
        attempts, forks = [], []
        actual_fork = gitreads.Git.fork

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def ancestor(git, common, older, newer):
            pair = (older, newer)
            attempts.append((git, pair))
            if pair in unavailable:
                raise unavailable[pair]
            return False

        refs = {f"refs/remotes/origin/{number}": {"sha": older}
                for number, (older, _) in enumerate(reverse)}
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                mock.patch.object(gitreads.Git, "fork", fork):
            self.reader._prefetch_remote_relations(pairs)
            self.assertEqual(set(self.reader._ancestor_failures), set(pairs))
            self.assertEqual(self.reader._ancestors, {})
            first_forks = len(forks)
            self.reader._prefetch_remote_relations(reverse)
            for number, (_, newer) in enumerate(reverse):
                self.assertIsNone(self.reader._guarded_remote(refs, f"refs/heads/{number}", newer))
        self.assertGreater(len(forks), first_forks, "the later reversed batch never used its worker pool")
        self.assertTrue(all(git is not self.reader.git and any(git is child for child in forks)
                            for git, _ in attempts), "the later reciprocal batch fell back to the parent runner")
        self.assertCountEqual([pair for _, pair in attempts], pairs + reverse)
        self.assertEqual(self.reader._ancestors, dict.fromkeys(reverse, False))
        self.assertTrue(all(self.reader._ancestor_failures[pair] is error for pair, error in unavailable.items()))

    def test_mixed_cached_phase_keeps_its_one_unread_relation_in_a_forked_reader(self) -> None:
        pairs = [(f"{number + 100:040x}", f"{number + 200:040x}")
                 for number in range(collector_module.PARALLEL_MIN)]
        bad, unavailable = pairs[-1], gitreads.GitFailed("temporarily unreadable direction")
        later = pairs[:-1] + [bad[::-1]]
        attempts, forks = [], []
        actual_fork = gitreads.Git.fork

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def ancestor(git, common, older, newer):
            pair = (older, newer)
            attempts.append((git, pair))
            if pair == bad:
                raise unavailable
            return pair != bad[::-1]

        refs = {f"refs/remotes/origin/{number}": {"sha": older}
                for number, (older, _) in enumerate(later)}
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                mock.patch.object(gitreads.Git, "fork", fork):
            self.reader._prefetch_remote_relations(pairs)
            self.assertEqual(set(self.reader._ancestors), set(pairs[:-1]))
            self.assertIs(self.reader._ancestor_failures[bad], unavailable)
            first_forks = len(forks)
            self.reader._prefetch_remote_relations(later)
            for number, (_, newer) in enumerate(later):
                self.assertEqual(self.reader._guarded_remote(refs, f"refs/heads/{number}", newer),
                                 "ahead" if number < len(later) - 1 else None)
        self.assertEqual(len(forks) - first_forks, 1, "cache hits disabled the eligible phase's worker pool")
        self.assertTrue(all(git is not self.reader.git and any(git is child for child in forks)
                            for git, _ in attempts), "the mixed phase fell back to the parent runner")
        self.assertCountEqual([pair for _, pair in attempts], pairs + [bad[::-1]])
        self.assertIs(self.reader._ancestor_failures[bad], unavailable)

    def test_small_ancestry_phases_stay_sequential_even_with_repeated_or_identity_pairs(self) -> None:
        pairs = [(f"{number + 100:040x}", f"{number + 200:040x}")
                 for number in range(collector_module.PARALLEL_MIN - 1)]
        inputs = [pairs, [pairs[0]] * collector_module.PARALLEL_MIN,
                  [(f"{number:040x}", f"{number:040x}") for number in range(collector_module.PARALLEL_MIN)]
                  + [pairs[0]]]
        for requested in inputs:
            with self.subTest(requested=requested):
                reader = collector_module.Collector(Path(self.temporary.name).resolve())
                attempts = []

                def ancestor(git, common, older, newer):
                    attempts.append((git, (older, newer)))
                    return True

                with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                        mock.patch.object(gitreads.Git, "fork") as fork:
                    reader._prefetch_remote_relations(requested)
                    distinct = list(dict.fromkeys(pair for pair in requested if pair[0] != pair[1]))
                    refs = {f"refs/remotes/origin/{number}": {"sha": older}
                            for number, (older, _) in enumerate(distinct)}
                    for number, (_, newer) in enumerate(distinct):
                        self.assertEqual(reader._remote(refs, f"refs/heads/{number}", newer), "ahead")
                fork.assert_not_called()
                self.assertTrue(all(git is reader.git for git, _ in attempts))
                self.assertEqual([pair for _, pair in attempts], distinct)

    def test_fully_cached_ancestry_phase_starts_no_pool_and_runs_no_git(self) -> None:
        pairs = [(f"{number + 100:040x}", f"{number + 200:040x}")
                 for number in range(collector_module.PARALLEL_MIN)]
        self.reader._ancestors.update(dict.fromkeys(pairs, True))
        refs = {f"refs/remotes/origin/{number}": {"sha": older}
                for number, (older, _) in enumerate(pairs)}
        with mock.patch.object(gitreads.Git, "is_ancestor") as ancestor, \
                mock.patch.object(collector_module, "ThreadPoolExecutor") as pool:
            self.reader._prefetch_remote_relations(pairs)
            for number, (_, newer) in enumerate(pairs):
                self.assertEqual(self.reader._remote(refs, f"refs/heads/{number}", newer), "ahead")
        ancestor.assert_not_called()
        pool.assert_not_called()


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
        actual_fork = gitreads.Git.fork
        forks, failed_runners = [], []
        failed, attempts = True, 0

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def counts(git, common, base, current):
            nonlocal attempts
            if (base, current) == (main, tip):
                attempts += 1
                if failed:
                    failed_runners.append(git)
                    raise gitreads.GitFailed("temporarily unavailable graph")
            return actual(git, common, base, current)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "counts", counts), mock.patch.object(gitreads.Git, "fork", fork):
            first = reader.snapshot(NOW)
            self.assertEqual(first["main"]["state"], "ok", first["main"])
            card = next(card for card in first["sessions"] if card["name"] == self.trees[0].name)
            self.assertEqual(card["reason"], "distance_unreadable")
            self.assertEqual(attempts, 1, "failed prefetch ran again in the sequential path")
            self.assertEqual(len(failed_runners), 1)
            self.assertIsNot(failed_runners[0], reader.git)
            self.assertTrue(any(child is failed_runners[0] for child in forks),
                            "the failing pair did not exercise its forked prefetch runner")
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
        actual_fork = gitreads.Git.fork
        forks, failed_runners = [], []
        failed, attempts = True, 0

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def commits(git, common, base, current, limit=gitreads.MAX_COMMITS):
            nonlocal attempts
            if (base, current, limit) == (main, tip, gitreads.MAX_SESSION_COMMITS + 1):
                attempts += 1
                if failed:
                    failed_runners.append(git)
                    raise gitreads.GitFailed("temporarily unavailable range")
            return actual(git, common, base, current, limit)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "commits", commits), mock.patch.object(gitreads.Git, "fork", fork):
            first = reader.snapshot(NOW)
            self.assertEqual(first["main"]["state"], "ok", first["main"])
            card = next(card for card in first["sessions"] if card["name"] == self.trees[0].name)
            self.assertEqual(card["reason"], "commit_history_unreadable")
            self.assertEqual(attempts, 1, "failed prefetch ran again in the sequential path")
            self.assertEqual(len(failed_runners), 1)
            self.assertIsNot(failed_runners[0], reader.git)
            self.assertTrue(any(child is failed_runners[0] for child in forks),
                            "the failing range did not exercise its forked prefetch runner")
            failed = False
            second = reader.snapshot(NOW)
        card = next(card for card in second["sessions"] if card["name"] == self.trees[0].name)
        self.assertTrue(card["files_read"], card)
        self.assertEqual(card["reason"], "")
        self.assertEqual(attempts, 2)

    def test_failed_remote_ancestry_is_read_once_and_recovers_on_the_next_snapshot(self) -> None:
        tips = [self.repo.git("rev-parse", "HEAD", where=tree) for tree in self.trees]
        branches = [self.repo.git("branch", "--show-current", where=tree) for tree in self.trees]
        remotes = [f"refs/remotes/origin/{branch}" for branch in branches]

        def clean_refs():
            for remote in remotes:
                self.repo.git("update-ref", "-d", remote)

        self.addCleanup(clean_refs)  # cleanup also covers a partially completed setup
        for number, remote in enumerate(remotes):
            self.repo.git("update-ref", remote, tips[(number + 1) % len(tips)])
        actual, actual_fork = gitreads.Git.is_ancestor, gitreads.Git.fork
        try:
            for bad in ((tips[1], tips[0]), (tips[0], tips[1])):
                with self.subTest(failed_pair=bad):
                    reader = collector_module.Collector(self.repo.root, self.settings)
                    failed, attempts, forks, queries = True, [], [], []
                    unavailable = gitreads.GitFailed("temporarily unavailable remote ancestry")

                    def fork(git):
                        child = actual_fork(git)
                        forks.append(child)
                        return child

                    def ancestor(git, common, older, newer):
                        queries.append((older, newer))
                        if (older, newer) == bad:
                            attempts.append(git)
                            if failed:
                                raise unavailable
                        return actual(git, common, older, newer)

                    with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                            mock.patch.object(gitreads.Git, "fork", fork):
                        first = reader.snapshot(NOW)
                        self.assertEqual(first["main"]["state"], "ok", first["main"])
                        cards = {card["name"]: card for card in first["sessions"]}
                        unread = cards[self.trees[0].name]
                        self.assertEqual(unread["reason"], "read_failed", unread)
                        self.assertFalse(unread["files_read"], unread)
                        self.assertEqual(unread["remote"], "", unread)
                        self.assertFalse(unread["pushed"], unread)
                        self.assertTrue(all(cards[tree.name]["files_read"] for tree in self.trees[1:]), cards)
                        self.assertEqual(len(attempts), 1, "failed remote prefetch ran again sequentially")
                        self.assertIsNot(attempts[0], reader.git)
                        self.assertTrue(any(child is attempts[0] for child in forks))
                        if bad == (tips[0], tips[1]):
                            self.assertIs(reader._ancestors[(tips[1], tips[0])], False)
                            self.assertEqual(queries.count((tips[1], tips[0])), 1,
                                             "successful forward ancestry was lost with the reverse failure")
                        failed = False
                        second = reader.snapshot(NOW)
                    self.assertEqual(second["main"]["state"], "ok", second["main"])
                    self.assertEqual(len(attempts), 2)
                    card = next(card for card in second["sessions"] if card["name"] == self.trees[0].name)
                    self.assertEqual(card["remote"], "diverged")
        finally:
            clean_refs()

    def test_failed_remote_ancestry_of_a_branch_preserves_the_other_sessions(self) -> None:
        tips = [self.repo.git("rev-parse", "HEAD", where=tree) for tree in self.trees]
        branches = [f"refs/heads/unheld-{number}" for number in range(len(tips))]
        remotes = [branch.replace("refs/heads/", "refs/remotes/origin/") for branch in branches]

        def clean_refs():
            for name in branches + remotes:
                self.repo.git("update-ref", "-d", name)

        self.addCleanup(clean_refs)
        for number, (branch, remote) in enumerate(zip(branches, remotes)):
            self.repo.git("update-ref", branch, tips[number])
            self.repo.git("update-ref", remote, tips[(number + 1) % len(tips)])
        actual, attempts = gitreads.Git.is_ancestor, []
        bad = (tips[1], tips[0])

        def ancestor(git, common, older, newer):
            if (older, newer) == bad:
                attempts.append(git)
                raise gitreads.GitFailed("temporarily unavailable branch ancestry")
            return actual(git, common, older, newer)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor):
            found = reader.snapshot(NOW)
        self.assertEqual(found["main"]["state"], "ok", found["main"])
        cards = {card["name"]: card for card in found["sessions"]}
        self.assertEqual(cards["unheld-0"]["reason"], "read_failed", cards["unheld-0"])
        self.assertEqual(cards["unheld-0"]["remote"], "")
        self.assertFalse(cards["unheld-0"]["pushed"])
        self.assertTrue(all(cards[tree.name]["files_read"] for tree in self.trees), cards)
        self.assertTrue(all(cards[f"unheld-{number}"]["reason"] == "" for number in range(1, len(tips))), cards)
        self.assertEqual(len(attempts), 1)
        self.assertIsNot(attempts[0], reader.git, "branch failure did not exercise the parallel prefetch")

    def test_remote_ancestry_shared_deadline_still_fails_the_whole_reading(self) -> None:
        tip = self.repo.git("rev-parse", "HEAD", where=self.trees[0])
        remote = "refs/remotes/origin/topic-0"
        other = self.repo.git("rev-parse", "HEAD", where=self.trees[1])
        self.addCleanup(self.repo.git, "update-ref", "-d", remote)
        self.repo.git("update-ref", remote, other)
        actual, attempted = gitreads.Git.is_ancestor, []

        def ancestor(git, common, older, newer):
            if (older, newer) == (other, tip):
                attempted.append((older, newer))
                raise gitreads.ReadingTooLong("the whole reading exceeded its time budget")
            return actual(git, common, older, newer)

        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor):
            found = collector_module.Collector(self.repo.root, self.settings).snapshot(NOW)
        self.assertEqual(attempted, [(other, tip)])
        self.assertEqual(found["main"]["state"], "unreadable")
        self.assertEqual(found["main"]["reason"], "git_failed")

    def test_forked_remote_ancestry_deadline_still_fails_the_whole_reading(self) -> None:
        tips = [self.repo.git("rev-parse", "HEAD", where=tree) for tree in self.trees]
        remotes = [f"refs/remotes/origin/topic-{number}" for number in range(len(tips))]

        def clean_refs():
            for remote in remotes:
                self.repo.git("update-ref", "-d", remote)

        self.addCleanup(clean_refs)
        for number, remote in enumerate(remotes):
            self.repo.git("update-ref", remote, tips[(number + 1) % len(tips)])
        actual, actual_fork = gitreads.Git.is_ancestor, gitreads.Git.fork
        attempted, forks = [], []
        bad = (tips[1], tips[0])

        def fork(git):
            child = actual_fork(git)
            forks.append(child)
            return child

        def ancestor(git, common, older, newer):
            if (older, newer) == bad:
                attempted.append(git)
                raise gitreads.ReadingTooLong("the forked reading exceeded its shared time budget")
            return actual(git, common, older, newer)

        reader = collector_module.Collector(self.repo.root, self.settings)
        with mock.patch.object(gitreads.Git, "is_ancestor", ancestor), \
                mock.patch.object(gitreads.Git, "fork", fork):
            found = reader.snapshot(NOW)
        self.assertEqual(len(attempted), 1)
        self.assertIsNot(attempted[0], reader.git)
        self.assertTrue(any(attempted[0] is child for child in forks), "the deadline never hit a forked reader")
        self.assertEqual(found["main"]["state"], "unreadable")
        self.assertEqual(found["main"]["reason"], "git_failed")

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
