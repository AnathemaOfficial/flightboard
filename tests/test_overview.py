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

    def test_present_worktree_kept_files_prevent_clear_without_being_called_uncommitted(self):
        for kind in ("checkout", "worktree"):
            with self.subTest(kind=kind):
                session = {"id": "kept-tree", "kind": kind, "ahead": 0, "modified": 0, "untracked": 0,
                           "conflicted": 0, "kept": 2, "files_read": True, "file_activity_complete": True}
                result = self.build(sessions=[session])
                self.assertEqual(result["banner"], {"state": "attention", "code": "local_work"})
                self.assertFalse(overview._dirty(session))
                self.assertNotIn("inspect_worktree", [item["kind"] for item in result["actions"]])

    def test_no_kept_files_and_inapplicable_kept_fields_do_not_create_local_work(self):
        for kind, kept, gone in (("checkout", 0, False), ("worktree", 0, False),
                                 ("checkout", 2, True), ("worktree", 2, True),
                                 ("branch", 2, False), ("remote", 2, False)):
            with self.subTest(kind=kind, kept=kept, gone=gone):
                session = {"id": "kept-tree", "kind": kind, "ahead": 0, "kept": kept, "gone": gone,
                           "files_read": True, "file_activity_complete": True}
                self.assertEqual(self.build(sessions=[session])["banner"]["state"], "clear")

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

    def test_a_real_git_only_worktree_does_not_require_an_unconfigured_ledger(self):
        head = "a" * 40
        session = {"id": "checkout", "name": "demo", "kind": "checkout", "ahead": 0, "ledger": "none",
                   "files_read": True, "file_activity_complete": True}
        publication = load("publication").build(
            NOW, {"refs/heads/main": {"sha": head}},
            [{"id": "checkout", "tip": head, "ref": "refs/heads/main", "working_directory_readable": True}],
            [session], {"state": "fresh", "complete": True, "heads": {"main": head}},
            {"parents": {}, "complete": True, "comparison_source": "github"}, {"state": "equal"}, {})
        self.assertEqual(publication["coverage"]["working_ledgers_unknown"], 1)
        result = self.build(context(ledger=None, ledger_adapter=None, publication=publication), sessions=[session])
        self.assertEqual(result["banner"], {"state": "unverified", "code": "ledger_unavailable"})
        self.assertNotIn("repair_reading", [item["kind"] for item in result["actions"]])

    def test_git_only_ignores_ledger_coverage_fields_but_configured_adapters_require_them(self):
        for fields in ({}, {"working_ledgers_read": 5, "working_ledgers_unknown": 0},
                       {"working_ledgers_read": False, "working_ledgers_unknown": "unknown"},
                       {"working_ledgers_read": 0, "working_ledgers_unknown": 1}):
            with self.subTest(fields=fields):
                found = context(ledger=None, ledger_adapter=None)
                found["publication"]["coverage"] = {"worktree_files_total": 1, "working_files_read": 1,
                                                     "working_files_unknown": 0, **fields}
                session = {"id": "checkout", "kind": "checkout", "ledger": "none", "files_read": True,
                           "file_activity_complete": True}
                self.assertEqual(self.build(found, sessions=[session])["banner"]["code"], "ledger_unavailable")
                found["ledger_adapter"] = load("ledgers.tasks").TasksLedger("tasks.json")
                result = self.build(found, sessions=[session])
                self.assertEqual(result["banner"]["state"], "partial")
                self.assertEqual(result["actions"][0]["kind"], "repair_reading")

    def test_git_only_still_reports_file_and_generic_reading_problems(self):
        for problem in ({"files_read": False}, {"file_activity_complete": False},
                        {"reason": "commit_history_unreadable"}, {"error": "read error"}, {"operation": "merge"}):
            with self.subTest(problem=problem):
                session = {"id": "checkout", "kind": "checkout", "ledger": "none", "files_read": True,
                           "file_activity_complete": True, **problem}
                result = self.build(context(ledger=None, ledger_adapter=None), sessions=[session])
                self.assertEqual(result["banner"]["state"], "partial")
                self.assertEqual(result["actions"][0]["kind"], "repair_reading")

    def test_known_stashed_work_prevents_a_clear_banner_without_dirty_files_or_pending_commits(self):
        item = {"kind": "branch", "ref": "refs/heads/topic"}
        held = load("held")
        state = held.stash_states([item], held.stashed([{"via": "WIP on topic: aaaaaaa saved work"}]),
                                  "refs/remotes/origin/")[0]
        self.assertEqual(state, "stashed")
        session = {"id": "topic", "kind": "branch", "ahead": 0, "stash": state}
        self.assertEqual(self.build(sessions=[session])["banner"], {"state": "attention", "code": "local_work"})
        session["stash"] = held.stash_states([item], held.stashed([]), "refs/remotes/origin/")[0]
        self.assertEqual(session["stash"], "")
        self.assertEqual(self.build(sessions=[session])["banner"]["state"], "clear")

    def test_unreadable_stash_is_partial_only_for_present_sessions(self):
        held = load("held")
        for kind in ("checkout", "worktree", "branch", "remote"):
            with self.subTest(kind=kind):
                state = held.stash_states([{"kind": kind}], held.stashed(None), "refs/remotes/origin/")[0]
                self.assertEqual(state, "unknown")
                session = {"id": "topic", "kind": kind, "ahead": 0, "stash": state,
                           "files_read": True, "file_activity_complete": True}
                result = self.build(sessions=[session], nexts=[{"id": "NEXT-1"}])
                self.assertEqual(result["banner"], {"state": "partial", "code": "reading_partial"})
                self.assertEqual(result["actions"][0]["kind"], "repair_reading")
                self.assertNotIn("prepare_next", [item["kind"] for item in result["actions"]])
                session["gone"] = True
                result = self.build(sessions=[session])
                self.assertEqual(result["banner"]["state"], "clear")
                self.assertEqual(result["actions"], [])

    def test_unmatched_stash_is_global_work_without_an_invented_session_target(self):
        held = load("held")
        state = held.stash_states([{"kind": "branch", "ref": "refs/heads/topic"}],
                                  held.stashed([{"via": "opaque stash"}]), "refs/remotes/origin/")[0]
        self.assertEqual(state, "unmatched")
        result = self.build(sessions=[{"id": "topic", "kind": "branch", "ahead": 0, "stash": state}])
        self.assertEqual(result["banner"], {"state": "attention", "code": "local_work"})
        self.assertEqual(result["actions"], [])

    def test_retained_detached_work_prevents_clear_even_without_pending_refs_or_dirty_files(self):
        held = load("held")
        item = {"moves": {"dropped": ("b" * 40,)}}
        retained = held.left_behind(item, lambda values: set(values), lambda commit: False)
        self.assertEqual(retained, 1)
        session = {"id": "worker", "kind": "worktree", "ahead": 0, "left_behind": retained,
                   "files_read": True, "file_activity_complete": True}
        self.assertEqual(self.build(sessions=[session])["banner"], {"state": "attention", "code": "local_work"})
        session["left_behind"] = held.left_behind(item, lambda values: set(values), lambda commit: True)
        self.assertEqual(session["left_behind"], 0)
        self.assertEqual(self.build(sessions=[session])["banner"]["state"], "clear")

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

    def test_stacked_publication_targets_the_tip_not_an_ancestor_alias(self):
        ancestor, tip, main = "a" * 40, "b" * 40, "c" * 40
        trees = [{"id": "a-base-worktree", "tip": ancestor, "working_directory_readable": True},
                 {"id": "z-top-worktree", "tip": tip, "working_directory_readable": True}]
        mapped = [{"id": tree["id"], "name": tree["id"], "kind": "worktree", "head": tree["tip"][:7],
                   "branch": "a-base" if tree["tip"] == ancestor else "z-top", "files_read": True,
                   "file_activity_complete": True, "ledger": "ok"} for tree in trees]
        for sessions in ([], mapped):
            with self.subTest(session_mapping=bool(sessions)):
                publication = load("publication").build(
                    NOW, {"refs/heads/main": {"sha": main}, "refs/heads/a-base": {"sha": ancestor},
                          "refs/heads/z-top": {"sha": tip}}, trees, sessions,
                    {"state": "fresh", "complete": True, "heads": {"main": main}},
                    {"parents": {ancestor: (main,), tip: (ancestor,)}, "complete": True,
                     "comparison_source": "github"}, {"state": "equal"}, {})
                row = publication["queue"][0]
                self.assertEqual(row["branches"], ["a-base", "z-top"])
                self.assertEqual(row["worktrees"], ["a-base-worktree", "z-top-worktree"])
                found = context(publication=publication)
                action = next(item for item in self.build(found, sessions=sessions)["actions"]
                              if item["kind"] == "review_publication")
                self.assertEqual(action["head"], tip)
                self.assertEqual(action["target"], tip)
                self.assertEqual(action["branch"], "")
                self.assertEqual(action["worktree"], "")

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
