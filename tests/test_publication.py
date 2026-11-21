# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Publication evidence is unique, bounded and independent from task declarations."""
from datetime import timedelta
import json
import unittest
from unittest import mock

from tests.fixtures import NOW, load


class PublicationTest(unittest.TestCase):
    def summary(self, *, remote=None, graph=None, refs=None, worktrees=None, sessions=None, first_seen=None):
        return load("publication").build(
            NOW, refs or {"refs/heads/main": {"sha": "a" * 40},
                          "refs/heads/first": {"sha": "b" * 40},
                          "refs/heads/second": {"sha": "c" * 40}},
            worktrees or [], sessions or [], remote or {"state": "fresh", "complete": True, "heads": {}},
            graph or {"parents": {"b" * 40: ("a" * 40,), "c" * 40: ("b" * 40,)},
                      "complete": True, "comparison_source": "github"},
            {"state": "equal", "ahead": 0, "behind": 0, "comparison_source": "github"}, first_seen or {})

    def test_stack_and_aliases_count_each_commit_once(self):
        found = self.summary(refs={"refs/heads/main": {"sha": "a" * 40},
                                   "refs/heads/first": {"sha": "b" * 40},
                                   "refs/heads/second": {"sha": "c" * 40},
                                   "refs/heads/alias": {"sha": "c" * 40}})
        self.assertEqual(found["unpublished"]["unique_commits"], 2)
        self.assertEqual(len(found["queue"]), 1)
        self.assertEqual(set(found["queue"][0]["branches"]), {"first", "second", "alias"})
        self.assertEqual(found["queue"][0]["commit_count"], 2)

    def test_detached_worktree_and_dirty_work_need_no_task_changes(self):
        found = self.summary(worktrees=[{"id": "detached", "tip": "c" * 40, "kind": "worktree",
                                        "reason": "", "working_directory_readable": True}],
                             sessions=[{"id": "detached", "kind": "worktree", "name": "detached",
                                        "files_read": True, "file_activity_complete": True,
                                        "modified": 2, "untracked": 1, "ledger": "ok"}])
        self.assertIn("detached", found["queue"][0]["worktrees"])
        dirty = [row for row in found["queue"] if row["kind"] == "dirty"]
        self.assertEqual(dirty[0]["files"], 3)
        self.assertIn("uncommitted_work", {a["code"] for a in found["alerts"]})

    def test_shared_ancestor_branch_does_not_combine_divergent_tips(self):
        found = self.summary(refs={"refs/heads/base": {"sha": "b" * 40},
                                   "refs/heads/left": {"sha": "c" * 40},
                                   "refs/heads/right": {"sha": "d" * 40}},
                             graph={"parents": {"b" * 40: (), "c" * 40: ("b" * 40,),
                                                "d" * 40: ("b" * 40,)},
                                    "complete": True, "comparison_source": "github"})
        self.assertEqual(found["unpublished"]["unique_commits"], 3)
        self.assertEqual(len(found["queue"]), 2)
        self.assertEqual({tuple(row["branches"]) for row in found["queue"]},
                         {("base", "left"), ("base", "right")})
        self.assertEqual([row["commit_count"] for row in found["queue"]], [2, 2])

    def test_pull_request_branch_name_alone_does_not_prove_association(self):
        found = self.summary(remote={"state": "fresh", "complete": True, "heads": {},
                                     "pull_requests": [{"number": 1, "head": "second", "head_sha": "d" * 40},
                                                       {"number": 2, "head": "renamed", "head_sha": "c" * 40}]})
        self.assertEqual([pr["number"] for pr in found["queue"][0]["pull_requests"]], [2])

    def test_published_local_head_with_open_pr_remains_visible_for_review(self):
        found = self.summary(graph={"parents": {}, "complete": True, "comparison_source": "github"},
                             remote={"state": "fresh", "complete": True, "heads": {"second": "c" * 40},
                                     "pull_requests": [{"number": 2, "head": "second", "head_sha": "c" * 40},
                                                       {"number": 3, "head": "first", "head_sha": "d" * 40}]})
        self.assertEqual(found["unpublished"]["unique_commits"], 0)
        self.assertEqual(len(found["queue"]), 1)
        self.assertEqual(found["queue"][0]["kind"], "review")
        self.assertEqual(found["queue"][0]["state"], "pr_open")
        self.assertEqual(found["queue"][0]["candidate_count"], 0)
        self.assertEqual(found["queue"][0]["pull_requests"][0]["number"], 2)
        self.assertIn("publication_review", {row["code"] for row in found["alerts"]})

    def test_unwalked_tip_does_not_disappear_from_a_partial_graph(self):
        found = self.summary(graph={"parents": {"b" * 40: ()}, "complete": False, "reason": "cut",
                                    "comparison_source": "github"},
                             remote={"state": "fresh", "complete": True, "heads": {"main": "a" * 40}})
        self.assertEqual({row["head"] for row in found["queue"]}, {"b" * 40, "c" * 40})
        missing = next(row for row in found["queue"] if row["head"] == "c" * 40)
        self.assertEqual(missing["state"], "unknown")
        self.assertIsNone(missing["commit_count"])

    def test_review_rows_bound_aliases_and_include_detached_worktrees(self):
        refs = {f"refs/heads/alias-{index:02d}": {"sha": "c" * 40} for index in range(60)}
        trees = [{"id": f"detached-{index:02d}", "kind": "worktree", "tip": "c" * 40,
                  "reason": "outside"} for index in range(60)]
        found = self.summary(refs=refs, worktrees=trees,
                             graph={"parents": {}, "complete": True, "comparison_source": "github"},
                             remote={"state": "fresh", "complete": True, "heads": {"review": "c" * 40},
                                     "pull_requests": [{"number": 2, "head_sha": "c" * 40}]})
        row = found["queue"][0]
        self.assertEqual(row["kind"], "review")
        self.assertEqual((len(row["branches"]), row["branches_more"]), (50, 10))
        self.assertEqual((len(row["worktrees"]), row["worktrees_more"]), (50, 10))

    def test_large_dag_visits_each_selected_tip_once_and_bounds_display_only(self):
        publication = load("publication")
        shas = [f"{number:040x}" for number in range(1, 1001)]
        parents = {sha: (shas[index - 1],) if index else () for index, sha in enumerate(shas[:500])}
        parents.update({sha: (shas[499],) for sha in shas[500:]})
        refs = {f"refs/heads/branch-{index:04d}": {"sha": sha} for index, sha in enumerate(shas)}
        worktrees = [{"id": f"tree-{index}", "tip": shas[499], "kind": "worktree", "reason": "outside"}
                     for index in range(70)]
        with mock.patch.object(publication, "_reachable", wraps=publication._reachable) as reachable:
            found = self.summary(refs=refs, worktrees=worktrees,
                                 graph={"parents": parents, "complete": True, "comparison_source": "github"})
        self.assertLessEqual(reachable.call_count, len(shas))
        self.assertEqual(found["unpublished"]["unique_commits"], 1000)
        self.assertEqual(len(found["queue"]), 100)
        self.assertEqual(found["queue_more"], 400)
        self.assertEqual(found["queue_total"], 500)
        for row in found["queue"]:
            self.assertEqual(row["commit_count"], 501)
            self.assertEqual(len(row["branches"]), 50)
            self.assertEqual(row["branches_more"], 451)
            self.assertEqual(len(row["worktrees"]), 50)
            self.assertEqual(row["worktrees_more"], 20)

    def test_shared_ancestor_pull_requests_cannot_expand_the_response(self):
        base = "a" * 40
        leaves = [f"{number:040x}" for number in range(1, 101)]
        parents = {base: (), **{tip: (base,) for tip in leaves}}
        refs = {"refs/heads/base": {"sha": base},
                **{f"refs/heads/leaf-{index}": {"sha": tip} for index, tip in enumerate(leaves)}}
        prs = [{"number": number, "title": "Review " + "x" * 150, "head_sha": base,
                "head": "base", "base": "main", "url": f"https://github.com/example/repository/pull/{number}"}
               for number in range(1, 501)]
        found = self.summary(refs=refs,
                             graph={"parents": parents, "complete": True, "comparison_source": "github"},
                             remote={"state": "fresh", "complete": True, "heads": {}, "pull_requests": prs})
        self.assertEqual(len(found["queue"]), 100)
        self.assertLessEqual(sum(len(row["pull_requests"]) for row in found["queue"]), 1000)
        self.assertTrue(all(row["pull_requests_more"] == 490 for row in found["queue"]))
        self.assertLess(len(json.dumps(found).encode("utf-8")), 1_000_000)

    def test_missing_or_clipped_graph_never_reports_exact_total(self):
        for reason in ("missing_objects", "shallow", "cut"):
            with self.subTest(reason=reason):
                found = self.summary(graph={"parents": {"c" * 40: ("b" * 40,)}, "complete": False,
                                            "reason": reason, "comparison_source": "github"})
                self.assertIsNone(found["unpublished"]["unique_commits"])
                self.assertIsNone(found["queue"][0]["commit_count"])

    def test_cached_refs_are_candidates_without_fresh_github_proof(self):
        found = self.summary(remote={"state": "disabled", "complete": False, "heads": {}},
                             graph={"parents": {"c" * 40: ()}, "complete": True,
                                    "comparison_source": "local_tracking_refs"})
        self.assertEqual(found["unpublished"]["state"], "unknown")
        self.assertIsNone(found["unpublished"]["unique_commits"])
        self.assertEqual(found["unpublished"]["candidate_commits"], 1)

    def test_coverage_excludes_branch_only_and_does_not_confuse_committed_ledger(self):
        found = self.summary(worktrees=[{"id": "outside", "kind": "worktree", "tip": "c" * 40,
                                        "reason": "outside", "working_directory_readable": False}],
                             sessions=[{"id": "outside", "kind": "worktree", "files_read": False,
                                        "ledger": "ok"}, {"id": "branch", "kind": "branch", "files_read": True}])
        self.assertEqual(found["coverage"]["working_files_unknown"], 1)
        self.assertEqual(found["coverage"]["working_ledgers_read"], 0)
        self.assertEqual(found["coverage"]["branch_sessions"], 1)

    def test_alert_age_is_first_observation_not_commit_time(self):
        old = (NOW - timedelta(hours=25)).isoformat()
        found = self.summary(first_seen={"publication_pending": old})
        alert = next(a for a in found["alerts"] if a["code"] == "publication_pending")
        self.assertEqual(alert["first_seen_at"], old)
        self.assertIn("publication_overdue", {a["code"] for a in found["alerts"]})


if __name__ == "__main__":
    unittest.main()
