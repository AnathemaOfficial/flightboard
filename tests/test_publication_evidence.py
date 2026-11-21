# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Publication follow-up evidence cannot hide sessions, invent completeness or reset known ages."""
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain

collector = load("collector")
gitreads = load("gitreads")


@unittest.skipIf(GIT is None, "git absent")
class PublicationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.main = self.repo.git("rev-parse", "main")
        self.feature, self.cloud = "b" * 40, "c" * 40
        self.reader = collector.Collector(self.repo.root)
        self.refs = {"refs/heads/main": {"sha": self.main},
                     "refs/heads/topic": {"sha": self.feature},
                     "refs/remotes/origin/main": {"sha": self.main}}
        self.trees = [{"id": "", "main": True, "name": "plain", "path": self.repo.root,
                       "head": {"ref": "refs/heads/main"}, "operation": {"branch": None}, "reason": ""}]
        self.remote = {"state": "fresh", "repository": "example/repo", "complete": True,
                       "heads": {"main": self.main}, "pull_requests": []}
        self.graph = {"parents": {self.feature: (self.main,)}, "complete": True, "reason": ""}
        self.identity = mock.patch.object(self.reader, "_github_current", side_effect=lambda: dict(self.remote))
        self.identity_mock = self.identity.start()
        self.addCleanup(self.identity.stop)
        self.exists = mock.patch.object(gitreads.Git, "commits_exist",
                                        side_effect=lambda _, shas: [True] * len(shas))
        self.exists.start()
        self.addCleanup(self.exists.stop)
        self.walk = mock.patch.object(gitreads.Git, "publication_graph", return_value=self.graph)
        self.walk_mock = self.walk.start()
        self.addCleanup(self.walk.stop)

    def read(self, now=NOW, *, main_ref="refs/heads/main"):
        return self.reader._publication(now, self.refs, self.trees, [], main_ref, self.main)

    def test_cached_graph_rechecks_published_objects_without_rewalking_when_unchanged(self):
        self.remote["heads"]["cloud"] = self.cloud
        self.assertEqual(self.read()["unpublished"]["state"], "exact")
        self.assertEqual(self.read()["unpublished"]["state"], "exact")
        self.assertEqual(self.walk_mock.call_count, 1)
        with mock.patch.object(gitreads.Git, "commits_exist",
                               side_effect=lambda _, shas: [sha != self.cloud for sha in shas]):
            found = self.read()
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertIn("missing_objects", {row["detail"] for row in found["alerts"]})

    def test_registered_unknown_tip_keeps_known_candidates_but_not_exact_total(self):
        self.trees.append({"id": "unknown", "main": False, "name": "unknown", "path": None,
                           "head": {"ref": None, "sha": None}, "operation": {"branch": None},
                           "reason": "head_unreadable"})
        found = self.read()
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertEqual(found["unpublished"]["candidate_commits"], 1)
        self.assertIn("unknown_tip", {row["detail"] for row in found["alerts"]})

    def test_remote_only_baseline_does_not_claim_equal_local_main(self):
        del self.refs["refs/heads/main"]
        self.trees[0]["head"] = {"ref": "refs/remotes/origin/main"}
        found = self.read(main_ref="refs/remotes/origin/main")
        self.assertEqual(found["main"]["state"], "unknown")
        self.assertEqual(found["main"]["local_head"], "")

    def test_inconclusive_read_preserves_commit_age_until_recovery(self):
        self.read()
        self.remote["heads"]["cloud"] = self.cloud
        with mock.patch.object(gitreads.Git, "publication_graph", side_effect=gitreads.GitFailed("temporary")):
            failed = self.read(NOW + timedelta(hours=24))
        self.assertIsNone(failed["unpublished"]["unique_commits"])
        self.assertNotIn("publication_overdue", {row["code"] for row in failed["alerts"]})
        recovered = self.read(NOW + timedelta(hours=25))
        pending = next(row for row in recovered["alerts"] if row["code"] == "publication_pending")
        self.assertEqual(pending["first_seen_at"], NOW.isoformat(timespec="seconds"))
        self.assertIn("publication_overdue", {row["code"] for row in recovered["alerts"]})

    def test_publication_timeout_leaves_completed_session_view_available(self):
        clock = [100.0]
        deadlines = []

        def late_walk(common, tips, published):
            deadlines.append(self.reader.git.deadline)
            clock[0] = self.reader.git.deadline + 0.01
            raise gitreads.ReadingTooLong("publication deadline")

        def completed_sessions(*args):
            clock[0] = self.reader.git.deadline - 2
            return {"main": {"state": "ok"}, "sessions": [{"id": "already-read"}],
                    "publication": self.read()}

        with mock.patch.object(collector.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(self.reader, "_snapshot", side_effect=completed_sessions), \
                mock.patch.object(gitreads.Git, "publication_graph", side_effect=late_walk):
            found = self.reader.snapshot(NOW)
        self.assertEqual(found["main"]["state"], "ok")
        self.assertEqual(found["sessions"], [{"id": "already-read"}])
        self.assertLess(deadlines[0], 112.0)
        self.assertIsNone(self.reader.git.deadline)

    def test_full_inconclusive_age_cache_retains_current_commit_before_old_entries(self):
        self.reader._publication_signature = (self.reader.remote,)
        oldest = (NOW - timedelta(days=2)).isoformat(timespec="seconds")
        self.reader._publication_commit_seen = {
            f"{number:040x}": oldest for number in range(collector.MAX_PUBLICATION_AGES)}
        self.graph.update(complete=False, reason="cut")
        self.read()
        self.assertTrue(self.feature in self.reader._publication_commit_seen,
                        "a current commit must not be evicted by older inconclusive entries")
        self.assertLessEqual(len(self.reader._publication_commit_seen), collector.MAX_PUBLICATION_AGES)
        recovered = self.read(NOW + timedelta(hours=25))
        pending = next(row for row in recovered["alerts"] if row["code"] == "publication_pending")
        self.assertEqual(pending["first_seen_at"], NOW.isoformat(timespec="seconds"))
        self.assertIn("publication_overdue", {row["code"] for row in recovered["alerts"]})

    def test_expired_observation_after_graph_cannot_emit_exact_or_private_token(self):
        clock = [4.0]
        self.remote["_expires_at"] = 5.0
        self.reader.github = SimpleNamespace(expired=lambda snapshot: clock[0] >= snapshot["_expires_at"])

        def walk(*args):
            clock[0] = 6.0
            return self.graph

        with mock.patch.object(gitreads.Git, "publication_graph", side_effect=walk):
            found = self.read()
        self.assertEqual(found["remote"]["state"], "stale")
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertNotIn("_expires_at", found["remote"])
        self.assertEqual(self.identity_mock.call_count, 1)

    def test_expiry_during_pure_build_reuses_original_heads_and_downgrades(self):
        clock = [4.0]
        self.remote["_expires_at"] = 5.0
        self.reader.github = SimpleNamespace(expired=lambda snapshot: clock[0] >= snapshot["_expires_at"])
        actual = collector.PUBLICATION.build

        def build(*args):
            result = actual(*args)
            clock[0] = 6.0
            return result

        with mock.patch.object(collector.PUBLICATION, "build", side_effect=build) as builds:
            found = self.read()
        self.assertEqual(found["remote"]["state"], "stale")
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertEqual(builds.call_count, 2)
        self.assertEqual(self.walk_mock.call_count, 1)

    def test_confirmed_publication_removes_old_observation_age(self):
        self.read()
        self.remote["heads"]["topic"] = self.feature
        with mock.patch.object(gitreads.Git, "publication_graph",
                               return_value={"parents": {}, "complete": True, "reason": ""}):
            self.read(NOW + timedelta(hours=1))
        self.assertEqual(self.reader._publication_commit_seen, {})
        del self.remote["heads"]["topic"]
        found = self.read(NOW + timedelta(hours=25))
        pending = next(row for row in found["alerts"] if row["code"] == "publication_pending")
        self.assertEqual(pending["first_seen_at"], (NOW + timedelta(hours=25)).isoformat(timespec="seconds"))

    def test_fetch_repository_uses_first_url_and_honors_empty_reset(self):
        observer = mock.Mock()
        observer.current.return_value = {"state": "pending"}
        reader = collector.Collector(self.repo.root, github=observer)
        self.repo.git("config", "--add", "remote.origin.url", "https://github.com/first/repo.git")
        self.repo.git("config", "--add", "remote.origin.url", "https://github.com/second/repo.git")
        reader._github_current()
        observer.current.assert_called_with("first/repo")
        self.repo.git("config", "--add", "remote.origin.url", "")
        self.repo.git("config", "--add", "remote.origin.url", "https://github.com/reset/repo.git")
        self.repo.git("config", "--add", "remote.origin.url", "https://github.com/mirror/repo.git")
        reader._github_current()
        observer.current.assert_called_with("reset/repo")

    def test_unsupported_first_fetch_url_does_not_select_github_mirror(self):
        observer = mock.Mock()
        reader = collector.Collector(self.repo.root, github=observer)
        self.repo.git("config", "--add", "remote.origin.url", "https://other.example/repo.git")
        self.repo.git("config", "--add", "remote.origin.url", "https://github.com/mirror/repo.git")
        reader._github_current()
        observer.current.assert_called_once_with("")


class PublicationRefParserTest(unittest.TestCase):
    def test_upstream_lookup_keeps_full_identity(self):
        branch = "/".join(["a" * 90] * 3)
        remote = "refs/remotes/origin/" + branch
        data = "\0".join(["refs/heads/topic", "a" * 40, "1", "", remote, "origin", "refs/heads/" + branch])
        found = gitreads.parse_refs(data.encode())["refs/heads/topic"]
        self.assertEqual(found["upstream"], remote)
        self.assertEqual(found["upstream_ref"], "refs/heads/" + branch)


if __name__ == "__main__":
    unittest.main()
