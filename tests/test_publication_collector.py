# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Real local Git publication reads stay bounded and reuse unchanged graph evidence."""
from datetime import timedelta
import unittest
from unittest import mock

from tests.fixtures import GIT, NOW, git_starts, load
from tests.test_modes import Plain

collector = load("collector")
gitreads = load("gitreads")


@unittest.skipIf(GIT is None, "git absent")
class PublicationCollectorTest(unittest.TestCase):
    def setUp(self):
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.main = self.repo.git("rev-parse", "main")
        self.repo.git("update-ref", "refs/remotes/origin/main", self.main)
        self.tree = self.repo.worktree("first", "first")
        self.repo.commit(self.tree, "one.py", "one\n", "first", "09:00")
        self.first = self.repo.git("rev-parse", "HEAD", where=self.tree)
        self.repo.git("branch", "second", self.first)
        self.repo.git("checkout", "-q", "second", where=self.tree)
        self.repo.commit(self.tree, "two.py", "two\n", "second", "10:00")
        self.second = self.repo.git("rev-parse", "HEAD", where=self.tree)

    def read(self, reader=None):
        # The view integration is owned by another worker; exercise the collector's context directly.
        actual = collector.VIEW.build_view
        with mock.patch.object(collector.VIEW, "build_view",
                               side_effect=lambda now, mode, context, sessions, versions, settings:
                               {**actual(now, mode, context, sessions, versions, settings),
                                "publication": context["publication"]}):
            return (reader or collector.Collector(self.repo.root)).snapshot(NOW)

    def test_union_graph_has_two_unique_commits_for_a_stack(self):
        graph = gitreads.Git().publication_graph(self.repo.root / ".git", [self.first, self.second], [self.main])
        self.assertTrue(graph["complete"])
        self.assertEqual(set(graph["parents"]), {self.first, self.second})

    def test_graph_cap_and_invalid_limit_are_explicit(self):
        graph = gitreads.Git().publication_graph(self.repo.root / ".git", [self.second], [self.main], limit=1)
        self.assertFalse(graph["complete"])
        self.assertEqual(graph["reason"], "cut")
        with self.assertRaises(gitreads.GitRefused):
            gitreads.Git().publication_graph(self.repo.root / ".git", [self.second], [self.main], limit=True)

    def test_upstream_can_differ_from_branch_name(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        self.repo.git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        self.repo.git("config", "branch.second.remote", "origin")
        self.repo.git("config", "branch.second.merge", "refs/heads/review-stack")
        self.repo.git("update-ref", "refs/remotes/origin/review-stack", self.second)
        info = gitreads.Git().refs(self.repo.root / ".git")["refs/heads/second"]
        self.assertEqual(info["upstream"], "refs/remotes/origin/review-stack")
        self.assertEqual(info["upstream_ref"], "refs/heads/review-stack")
        found = self.read()
        session = next(row for row in found["sessions"] if row["name"] == "first")
        self.assertEqual(session["remote"], "pushed")

    def test_disabled_github_keeps_candidates_and_cached_graph(self):
        reader = collector.Collector(self.repo.root)
        first = self.read(reader)["publication"]
        self.assertEqual(first["unpublished"]["candidate_commits"], 2)
        self.assertIsNone(first["unpublished"]["unique_commits"])
        with mock.patch.object(gitreads.Git, "publication_graph", side_effect=AssertionError("graph rerun")):
            second = self.read(reader)["publication"]
        self.assertEqual(first["queue"], second["queue"])

    def test_renamed_upstream_does_not_hide_unrelated_same_name_remote_branch(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        self.repo.git("config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        self.repo.git("config", "branch.second.remote", "origin")
        self.repo.git("config", "branch.second.merge", "refs/heads/review-stack")
        self.repo.git("update-ref", "refs/remotes/origin/review-stack", self.second)
        cloud = self.repo.worktree("cloud", "cloud")
        self.repo.commit(cloud, "cloud.py", "cloud\n", "remote only", "11:00")
        cloud_tip = self.repo.git("rev-parse", "HEAD", where=cloud)
        self.repo.git("update-ref", "refs/remotes/origin/second", cloud_tip)
        found = self.read()
        remote = next((row for row in found["sessions"] if row["name"] == "origin/second"), None)
        self.assertIsNotNone(remote, "a differently tracked local branch cannot hide this remote session")
        self.assertEqual(remote["head"], cloud_tip[:7])

    def test_fresh_heads_unknown_locally_never_become_exact(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        observer = mock.Mock()
        observer.current.return_value = {"state": "fresh", "complete": True,
                                         "heads": {"main": self.main, "cloud": "e" * 40},
                                         "pull_requests": []}
        found = self.read(collector.Collector(self.repo.root, github=observer))["publication"]
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertEqual(found["unpublished"]["state"], "partial")

    def test_fresh_heads_make_union_exact_without_fetch(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        observer = mock.Mock()
        observer.current.return_value = {"state": "fresh", "complete": True, "heads": {"main": self.main},
                                         "pull_requests": []}
        found = self.read(collector.Collector(self.repo.root, github=observer))["publication"]
        self.assertEqual(found["unpublished"]["unique_commits"], 2)
        self.assertEqual(found["main"]["state"], "equal")
        observer.current.assert_called_once_with("example/repo")

    def test_fresh_empty_github_does_not_exclude_local_main_history(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        observer = mock.Mock()
        observer.current.return_value = {"state": "fresh", "complete": True, "heads": {}, "pull_requests": []}
        found = self.read(collector.Collector(self.repo.root, github=observer))["publication"]
        expected = len(self.repo.git("rev-list", self.second).splitlines())
        self.assertEqual(found["unpublished"]["unique_commits"], expected)

    def test_first_observed_alert_retains_age_without_new_git_reads(self):
        reader = collector.Collector(self.repo.root)
        found = self.read(reader)["publication"]
        first = next(row for row in found["alerts"] if row["code"] == "publication_pending")
        self.assertEqual(first["first_seen_at"], NOW.isoformat(timespec="seconds"))
        with git_starts() as starts:
            reader.snapshot(NOW + timedelta(hours=25))
        self.assertFalse([args for args, _ in starts if "rev-list" in args])

    def test_shallow_repository_never_reports_complete_publication(self):
        (self.repo.root / ".git" / "shallow").write_text(self.main + "\n", encoding="ascii")
        found = self.read()["publication"]
        self.assertIsNone(found["unpublished"]["unique_commits"])

    def test_unrelated_published_branch_does_not_reset_observed_delay(self):
        reader = collector.Collector(self.repo.root)
        first = self.read(reader)["publication"]
        observed = next(row for row in first["alerts"] if row["code"] == "publication_pending")["first_seen_at"]
        tree = self.repo.worktree("published", "published")
        self.repo.commit(tree, "published.py", "published\n", "published", "11:00")
        head = self.repo.git("rev-parse", "HEAD", where=tree)
        self.repo.git("update-ref", "refs/remotes/origin/published", head)
        found = reader.snapshot(NOW + timedelta(hours=25))["publication"]
        pending = next(row for row in found["alerts"] if row["code"] == "publication_pending")
        self.assertEqual(pending["first_seen_at"], observed)
        self.assertIn("publication_overdue", {row["code"] for row in found["alerts"]})

    def test_github_refresh_source_changes_preserve_commit_observation_age(self):
        self.repo.git("config", "remote.origin.url", "https://github.com/example/repo.git")
        observer = mock.Mock()
        evidence = {"state": "fresh", "repository": "example/repo", "complete": True,
                    "heads": {"main": self.main}, "pull_requests": []}
        observer.current.return_value = evidence
        reader = collector.Collector(self.repo.root, github=observer)
        self.read(reader)
        for hours, state in ((1, "stale"), (25, "fresh")):
            observer.current.return_value = {**evidence, "state": state}
            found = reader.snapshot(NOW + timedelta(hours=hours))["publication"]
            pending = next(row for row in found["alerts"] if row["code"] == "publication_pending")
            self.assertEqual(pending["first_seen_at"], NOW.isoformat(timespec="seconds"))


if __name__ == "__main__":
    unittest.main()
