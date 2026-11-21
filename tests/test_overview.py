# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The overview separates declarations, observed publication and unevaluated product evidence."""
from __future__ import annotations

import copy
import unittest
from unittest import mock

from tests.fixtures import NOW, load

overview = load("overview")


def context(**changes):
    publication = {
        "remote": {"state": "fresh", "complete": True},
        "main": {"state": "equal", "ahead": 0, "behind": 0},
        "unpublished": {"state": "exact", "unique_commits": 0, "candidate_commits": 0},
        "coverage": {"worktree_files_total": 0, "working_files_read": 0, "working_files_unknown": 0,
                     "working_ledgers_read": 0, "working_ledgers_unknown": 0},
        "queue": [], "queue_total": 0, "queue_more": 0, "alerts": [],
    }
    found = {"repository": "demo", "sha": "a" * 40, "ledger_adapter": None,
             "ledger": {"valid": True, "tasks": {}, "raw": {}}, "ledger_missing": "",
             "limits": {}, "planted": False, "publication": publication}
    found.update(changes)
    return found


def task(status, *, main=None, sources=None, conflict=False):
    return {"status": status, "status_main": main, "sources": sources or [],
            "conflict": conflict, "collision": False}


class OverviewTest(unittest.TestCase):
    def build(self, found=None, *, live=None, sessions=None, waiting=None, nexts=None):
        return overview.build(found or context(), live or {}, sessions or [], waiting or [], nexts or [])

    def test_equal_main_does_not_hide_pending_or_dirty_work(self):
        found = context()
        found["publication"]["unpublished"].update(unique_commits=8, candidate_commits=8)
        result = self.build(found, sessions=[{"id": "local", "kind": "worktree", "modified": 2,
                                             "files_read": True, "file_activity_complete": True}])
        self.assertEqual(result["banner"], {"state": "attention", "code": "local_work"})

    def test_already_published_branch_outside_main_still_needs_review(self):
        sessions = [{"id": "topic", "name": "topic", "kind": "branch", "ahead": 2,
                     "branch": "topic", "head": "bbbbbbb", "tasks": []}]
        result = self.build(sessions=sessions)
        self.assertEqual(result["banner"], {"state": "attention", "code": "review_pending"})
        action = result["actions"][0]
        self.assertEqual((action["kind"], action["branch"], action["head"]),
                         ("review_publication", "topic", "bbbbbbb"))

    def test_omitted_tasks_do_not_mix_with_omitted_worktree_counts(self):
        session = {"id": "dirty", "kind": "worktree", "modified": 1, "files_read": True,
                   "file_activity_complete": True, "tasks": [f"A-{i}" for i in range(15)]}
        action = next(item for item in self.build(sessions=[session])["actions"]
                      if item["kind"] == "inspect_worktree")
        self.assertEqual((action["more"], action["tasks_more"]), (0, 5))

    def test_incomplete_reads_take_priority_over_local_work(self):
        for change in ("coverage", "history", "branches", "invalid", "files", "planted"):
            with self.subTest(change=change):
                found = context()
                found["publication"]["unpublished"]["candidate_commits"] = 8
                sessions = []
                if change == "coverage":
                    found["publication"]["coverage"]["working_files_unknown"] = 1
                elif change == "history":
                    found["limits"]["history_cut"] = True
                elif change == "branches":
                    found["limits"]["branches_cut"] = 2
                elif change == "invalid":
                    found["ledger"]["valid"] = False
                elif change == "planted":
                    found["planted"] = True
                else:
                    sessions = [{"id": "unread", "kind": "worktree", "files_read": False}]
                result = self.build(found, sessions=sessions)
                self.assertEqual(result["banner"]["state"], "partial")
                self.assertEqual(result["actions"][0]["kind"], "repair_reading")

    def test_branch_and_remote_read_failures_prevent_clear_and_next_task_actions(self):
        failures = ({"reason": "commit_history_unreadable"}, {"reason": "invalid_ledger"},
                    {"error": "ledger validation failed"}, {"operation": "merge"})
        for kind in ("branch", "remote"):
            for failure in failures:
                with self.subTest(kind=kind, failure=failure):
                    session = {"id": "topic", "kind": kind, "ahead": 0, **failure}
                    result = self.build(sessions=[session], nexts=[{"id": "NEXT-1"}])
                    self.assertEqual(result["banner"], {"state": "partial", "code": "reading_partial"})
                    self.assertEqual(result["actions"][0]["kind"], "repair_reading")
                    self.assertNotIn("prepare_next", [item["kind"] for item in result["actions"]])

    def test_healthy_git_only_sessions_do_not_require_working_file_activity(self):
        for kind in ("branch", "remote"):
            with self.subTest(kind=kind):
                session = {"id": "topic", "kind": kind, "ahead": 0, "files_read": False,
                           "file_activity_complete": False, "reason": "", "error": "", "operation": ""}
                result = self.build(sessions=[session], nexts=[{"id": "NEXT-1"}])
                self.assertEqual(result["banner"]["state"], "clear")
                self.assertIn("prepare_next", [item["kind"] for item in result["actions"]])

    def test_gone_sessions_do_not_turn_an_unreadable_old_folder_into_a_current_read_failure(self):
        for kind in ("checkout", "worktree", "branch", "remote"):
            with self.subTest(kind=kind):
                session = {"id": "gone", "kind": kind, "ahead": 0, "gone": True,
                           "reason": "commit_history_unreadable", "error": "invalid ledger", "operation": "merge"}
                self.assertEqual(self.build(sessions=[session])["banner"]["state"], "clear")

    def test_clear_requires_fresh_complete_github_and_valid_ledger(self):
        self.assertEqual(self.build()["banner"]["state"], "clear")
        for remote in ({"state": "disabled"}, {"state": "stale", "complete": True},
                       {"state": "fresh", "complete": False}):
            with self.subTest(remote=remote):
                found = context()
                found["publication"]["remote"] = remote
                self.assertEqual(self.build(found)["banner"]["state"], "unverified")
        found = context()
        found["publication"]["main"]["state"] = "unknown"
        self.assertEqual(self.build(found)["banner"]["state"], "unverified")
        self.assertEqual(self.build(context(ledger=None))["banner"]["code"], "ledger_unavailable")

    def test_missing_or_inconsistent_coverage_does_not_establish_no_gap(self):
        for coverage in ({}, {"worktree_files_total": 1, "working_files_read": 0, "working_files_unknown": 0,
                             "working_ledgers_read": 1, "working_ledgers_unknown": 0}):
            with self.subTest(coverage=coverage):
                found = context()
                found["publication"]["coverage"] = coverage
                result = self.build(found, nexts=[{"id": "NEXT-1"}])
                self.assertEqual(result["banner"]["state"], "partial")
                self.assertNotIn("prepare_next", [item["kind"] for item in result["actions"]])

    def test_progress_counts_unique_claims_and_separate_denominators(self):
        found = context()
        found["ledger"]["tasks"] = {"A-1": {"status": "done"}, "A-2": {"status": "planned"}}
        source = {"applied": True, "uncommitted": True, "to": "awaiting_review"}
        live = {"A-1": task("done", main="done"),
                "A-2": task("awaiting_review", main="planned", sources=[source, source]),
                "NEW-1": task("in_progress"),
                "COLLISION-1": task("done", conflict=True)}
        progress = self.build(found, live=live)["progress"]
        self.assertEqual(progress["main"], {"total": 2, "done": 1, "review": 0, "in_progress": 0})
        self.assertEqual(progress["live"], {"total": 3, "done": 1, "review": 1, "in_progress": 1})
        self.assertEqual(progress["uncommitted_tasks"], 1)
        self.assertEqual(progress["local_only_tasks"], 1)
        self.assertEqual(progress["conflicts"], 1)

    def test_generic_tasks_cannot_turn_arbitrary_evidence_into_product_proof(self):
        found = context(ledger_adapter=type("Tasks", (), {"kind": "tasks", "path": "tasks.json"})())
        found["ledger"]["tasks"] = {"A-1": {"status": "done"}}
        found["ledger"]["raw"] = {"tasks": [{"id": "A-1", "status": "done", "evidence": "passed"}]}
        evidence = self.build(found)["evidence"]
        self.assertEqual(evidence["state"], "unsupported")
        self.assertEqual(evidence["verification"], "not_evaluated")
        self.assertIsNone(evidence["referenced_tasks"])
        self.assertEqual(evidence["references"], [])

    def test_roadmap_references_remain_main_only_and_match_the_observed_status(self):
        found = context(ledger_adapter=type("Roadmap", (), {"kind": "roadmap", "path": "roadmap.json"})())
        proof = {"kind": "tests", "at": "2026-11-06", "ref": "commit:abcdef1"}
        found["ledger"]["tasks"] = {"A-1": {"status": "planned"}, "A-2": {"status": "done"}}
        found["ledger"]["raw"] = {"tasks": [
            {"id": "A-1", "status": "done", "evidence": [proof]},
            {"id": "A-2", "status": "done", "evidence": [proof]},
            {"id": "FOREIGN-1", "status": "done", "evidence": [proof]}]}
        evidence = self.build(found, live={"A-1": task("done", main="planned")})["evidence"]
        self.assertEqual(evidence["state"], "references_only")
        self.assertEqual((evidence["referenced_tasks"], evidence["reference_count"]), (1, 1))
        self.assertEqual(evidence["references"], [{"task": "A-2", "status": "done", **proof}])
        self.assertEqual(evidence["scope"], "main")
        self.assertEqual(evidence["verification"], "not_evaluated")

    def test_reference_output_is_bounded_and_never_claims_a_validation(self):
        found = context(ledger_adapter=type("Roadmap", (), {"kind": "roadmap", "path": "roadmap.json"})())
        found["ledger"]["tasks"] = {f"A-{i}": {"status": "done"} for i in range(30)}
        found["ledger"]["raw"] = {"tasks": [{"id": tid, "status": "done", "evidence": [
            {"kind": "doc", "at": "2026-11-06", "ref": "documentation"}]}
            for tid in found["ledger"]["tasks"]]}
        evidence = self.build(found)["evidence"]
        self.assertEqual(evidence["reference_count"], 30)
        self.assertLessEqual(len(evidence["references"]), 12)
        self.assertEqual(evidence["references_more"], 30 - len(evidence["references"]))
        self.assertEqual(evidence["verification"], "not_evaluated")

    def test_partial_or_invalid_roadmap_evidence_has_no_exact_reference_total(self):
        found = context(ledger_adapter=type("Roadmap", (), {"kind": "roadmap", "path": "roadmap.json"})())
        found["ledger"]["tasks"] = {"A-1": {"status": "done"}}
        refs = [{"kind": "tests", "at": "2026-11-06", "ref": "commit:" + str(i)} for i in range(30)]
        found["ledger"]["raw"] = {"tasks": [{"id": "A-1", "status": "done", "evidence": refs}]}
        evidence = self.build(found)["evidence"]
        self.assertTrue(evidence["partial"])
        self.assertIsNone(evidence["reference_count"])
        found["ledger"]["valid"] = False
        self.assertEqual(self.build(found)["evidence"]["state"], "unavailable")

    def test_long_reference_display_does_not_merge_distinct_full_references(self):
        found = context(ledger_adapter=type("Roadmap", (), {"kind": "roadmap", "path": "roadmap.json"})())
        found["ledger"]["tasks"] = {"A-1": {"status": "done"}}
        refs = [{"kind": "doc", "at": "2026-11-06", "ref": "x" * 300 + suffix} for suffix in ("a", "b")]
        found["ledger"]["raw"] = {"tasks": [{"id": "A-1", "status": "done", "evidence": refs}]}
        self.assertEqual(self.build(found)["evidence"]["reference_count"], 2)

    def test_prepared_actions_are_bounded_stable_context_not_an_execution(self):
        found = context(ledger_adapter=type("Tasks", (), {"kind": "tasks", "path": "tasks.json"})())
        found["publication"]["unpublished"].update(unique_commits=1000, candidate_commits=1000)
        found["publication"].update(queue_total=500, queue_more=400)
        found["publication"]["queue"] = [{"id": "commits:" + "b" * 40, "kind": "commits",
                                            "head": "b" * 40, "branches": ["topic"], "worktrees": []}]
        sessions = [{"id": str(i), "name": "worker" + str(i), "kind": "worktree", "modified": 1,
                     "files_read": True, "file_activity_complete": True, "tracking": {"state": "check"},
                     "branch": "topic", "head": "bbbbbbb", "tasks": ["A-1"]} for i in range(30)]
        first = self.build(found, sessions=sessions)["actions"]
        self.assertLessEqual(len(first), 8)
        self.assertEqual(first, self.build(found, sessions=list(reversed(sessions)))["actions"])
        publication = next(item for item in first if item["kind"] == "review_publication")
        self.assertEqual(publication["head"], "b" * 40)
        self.assertEqual(publication["more"], 400)
        self.assertIn("queue_capped", publication["limits"])
        self.assertTrue(all(item["repository"] == "demo" and item["main_head"] == "a" * 40 for item in first))
        self.assertTrue(all(item["observed_at"] == "" for item in first))
        self.assertTrue(all("command" not in item and "prompt" not in item for item in first))

    def test_overview_does_no_io_and_does_not_mutate_the_snapshot(self):
        found = context()
        before = copy.deepcopy(found)
        with mock.patch("builtins.open", side_effect=AssertionError("file IO")), \
                mock.patch("subprocess.run", side_effect=AssertionError("process IO")):
            self.build(found)
        self.assertEqual(found, before)

    def test_loading_and_error_never_offer_actions_or_proven_progress(self):
        view = load("view")
        for result in (view.error_view(NOW, "live", "no_repository"), view.loading_view(NOW)):
            self.assertIn(result["overview"]["banner"]["state"], ("loading", "unavailable"))
            self.assertEqual(result["overview"]["actions"], [])
            self.assertFalse(result["overview"]["progress"]["available"])

    def test_real_view_uses_the_complete_live_model_before_task_detail_limits(self):
        from tests.fixtures import BASE, encoded, roadmap

        adapter = roadmap()
        found = context(ledger_adapter=adapter, ledger=adapter.parse(encoded(BASE)))
        found.update(lang="en", ref="refs/heads/main", head={}, note=[], note_text="", tool="flightboard")
        result = load("view").build_view(NOW, "live", found, [], [])
        self.assertEqual(result["overview"]["progress"]["main"]["total"], result["kpis"]["active"])
        self.assertEqual(result["overview"]["progress"]["live"]["done"], result["kpis"]["done_live"])
        self.assertEqual(result["overview"]["evidence"]["verification"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
