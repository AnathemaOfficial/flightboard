# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tracking diagnostics describe temporal observations without changing task progress."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import unittest

from tests.fixtures import BASE, encoded, load, roadmap

view = load("view")
NOW = datetime.fromisoformat("2026-11-17T21:00:00-05:00")
OLD = "2026-11-15T18:00:00-05:00"
RECENT = "2026-11-17T20:00:00-05:00"


def observed(**changes) -> dict:
    card = view.unreadable_session({"id": "worker", "name": "worker", "kind": "worktree",
                                    "tip": "a" * 40, "operation": ""}, "")
    card.update(files_read=True, files_issue="", file_activity_complete=True, ledger="ok", error="",
                ledger_file_modified_at=OLD, last_write=RECENT, last_activity=RECENT, activity="recent",
                file_activity_observed_at=RECENT, file_activity_partial_reasons=[],
                modified=1, branch="topic", kept=0)
    card.update(changes)
    return card


def build(card: dict | list[dict], **context_changes) -> dict:
    adapter = roadmap()
    ledger = adapter.parse(encoded(BASE))
    context = {"lang": "en", "ledger": ledger, "ledger_adapter": adapter, "ledger_missing": "",
               "ref": "refs/heads/main", "sha": "a" * 40, "head": {"at": NOW.timestamp(), "subject": "main"},
               "note": [], "note_text": "", "limits": {}, "planted": False, "tool": "flightboard",
               "repository": "demo", "entries": []}
    context.update(context_changes)
    return view.build_view(NOW, "live", context, [card] if isinstance(card, dict) else card, [])


class TrackingViewTest(unittest.TestCase):
    def state(self, card: dict, enabled: bool = True) -> dict:
        return view.tracking(card, enabled, NOW)

    def test_recent_work_without_a_named_lot_is_a_check(self) -> None:
        self.assertEqual(self.state(observed()), {"state": "check", "reason": "unassigned"})

    def test_old_known_review_lots_do_not_hide_recent_work(self) -> None:
        for status in ("awaiting_review", "done", "dropped"):
            with self.subTest(status=status):
                card = observed(tasks=["FB-001"], _head_tasks={"FB-001": {"status": status}})
                self.assertEqual(self.state(card), {"state": "check", "reason": "settled"})

    def test_work_on_an_ongoing_lot_is_informational(self) -> None:
        for status in ("planned", "ready", "in_progress", "blocked"):
            with self.subTest(status=status):
                card = observed(tasks=["FB-001"], _head_tasks={"FB-001": {"status": status}})
                self.assertEqual(self.state(card), {"state": "info", "reason": "ongoing"})

    def test_unknown_task_status_cannot_establish_an_association(self) -> None:
        for task in ({}, {"status": "alien"}):
            with self.subTest(task=task):
                self.assertEqual(self.state(observed(tasks=["FB-001"], _head_tasks={"FB-001": task})),
                                 {"state": "unknown", "reason": "task_state"})

    def test_unreadable_data_is_unknown(self) -> None:
        for change in ({"files_read": False}, {"reason": "outside"},
                       {"ledger": "unreadable"}, {"error": "invalid"}, {"operation": "merge"}):
            with self.subTest(change=change):
                self.assertEqual(self.state(observed(**change))["state"], "unknown")

    def test_refused_empty_counts_do_not_establish_a_clean_session(self) -> None:
        self.assertEqual(self.state(observed(files_read=False, modified=0, untracked=0))["state"], "unknown")

    def test_associations_beyond_the_display_cap_are_considered(self) -> None:
        tasks = {f"FB-{number:03}": {"status": "awaiting_review"} for number in range(41)}
        tasks["FB-040"]["status"] = "in_progress"
        self.assertEqual(self.state(observed(tasks=list(tasks), _head_tasks=tasks)),
                         {"state": "info", "reason": "ongoing"})

    def test_bad_missing_or_future_dates_are_unknown(self) -> None:
        for date in ("", "not a date", None, "2026-11-18T21:00:00-05:00"):
            for field in ("file_activity_observed_at", "ledger_file_modified_at"):
                with self.subTest(date=date, field=field):
                    self.assertEqual(self.state(observed(**{field: date}))["state"], "unknown")

    def test_ledger_only_edit_does_not_claim_coverage_or_progress(self) -> None:
        for last in (RECENT, OLD):
            card = observed(last_write=last, file_activity_observed_at=last,
                            ledger_file_modified_at=RECENT, updated_at="2026-11-15")
            self.assertEqual(self.state(card), {"state": "none", "reason": ""})

    def test_partial_regular_file_evidence_can_prove_a_temporal_gap(self) -> None:
        for status, expected in (("awaiting_review", "check"), ("in_progress", "info")):
            with self.subTest(status=status):
                card = observed(file_activity_complete=False, file_activity_partial_reasons=["limit", "depth"],
                                tasks=["FB-001"], _head_tasks={"FB-001": {"status": status}})
                self.assertEqual(self.state(card)["state"], expected)

    def test_partial_without_newer_regular_file_evidence_stays_unknown(self) -> None:
        for written in (OLD, "", None):
            with self.subTest(written=written):
                card = observed(file_activity_complete=False, file_activity_observed_at=written,
                                file_activity_partial_reasons=["limit"])
                self.assertEqual(self.state(card), {"state": "unknown", "reason": "partial"})
        self.assertEqual(self.state(observed(file_activity_complete=False, modified=0, untracked=0)),
                         {"state": "unknown", "reason": "partial"})

    def test_a_directory_or_untrusted_candidate_time_never_substitutes_for_file_evidence(self) -> None:
        for reason in ("folder", "ignore", "unsafe"):
            with self.subTest(reason=reason):
                card = observed(file_activity_complete=False, file_activity_observed_at="",
                                last_write=RECENT, file_activity_partial_reasons=[reason])
                self.assertEqual(self.state(card), {"state": "unknown", "reason": "partial"})

    def test_git_only_and_clean_local_sessions_need_no_tracking_notice(self) -> None:
        self.assertEqual(self.state(observed(), False), {"state": "none", "reason": ""})
        self.assertEqual(self.state(observed(modified=0, untracked=0, last_write="")),
                         {"state": "none", "reason": ""})

    def test_healthy_refs_without_a_worktree_have_no_local_file_tracking(self) -> None:
        for kind in ("branch", "remote"):
            with self.subTest(kind=kind):
                card = observed(kind=kind, modified=0, untracked=0, file_activity_complete=False,
                                file_activity_observed_at="", ledger_file_modified_at="")
                self.assertEqual(self.state(card), {"state": "none", "reason": ""})
                self.assertEqual(self.state({**card, "reason": "read_failed"})["state"], "unknown")

    def test_files_written_during_the_reading_use_its_completion_bound(self) -> None:
        end = NOW + timedelta(seconds=2)
        card = observed(file_activity_observed_at=(NOW + timedelta(seconds=1)).isoformat(),
                        ledger_file_modified_at=(NOW - timedelta(seconds=1)).isoformat())
        value = build(card, observed_until=end)
        self.assertEqual(value["sessions"][0]["tracking"], {"state": "check", "reason": "unassigned"})
        future = build({**card, "file_activity_observed_at": (end + timedelta(seconds=1)).isoformat()},
                       observed_until=end)
        self.assertEqual(future["sessions"][0]["tracking"], {"state": "unknown", "reason": "dates"})
        self.assertEqual(value["generated_at"], NOW.isoformat(timespec="seconds"))

    def test_tracking_reminders_cannot_hide_preservation_alerts_at_the_waiting_cap(self) -> None:
        cards = [observed(id=f"worker-{number}", name=f"worker-{number}", activity="active")
                 for number in range(35)]
        cards.append(observed(id="preserve", name="preserve", stash="here", activity="active",
                              modified=0, file_activity_observed_at="", last_write=""))
        value = build(cards)
        self.assertEqual(len(value["waiting"]), 30)
        self.assertEqual(value["waiting"][0]["kind"], "alert")
        self.assertEqual(value["waiting"][0]["session"], "preserve")
        self.assertTrue(any(item["kind"] == "tracking" for item in value["waiting"]))

    def test_build_adds_diagnostics_without_changing_tasks_events_or_advice(self) -> None:
        card = observed(tasks=["FB-001"], _head_tasks={"FB-001": {"status": "awaiting_review"}})
        before = copy.deepcopy(card)
        warning = build(card)
        quiet = build({**card, "ledger_file_modified_at": RECENT})
        self.assertEqual(warning["sessions"][0]["tracking"]["state"], "check")
        for key in ("tasks", "events", "kpis", "daily", "history", "next"):
            self.assertEqual(warning[key], quiet[key], key)
        self.assertEqual(warning["sessions"][0]["advice"], quiet["sessions"][0]["advice"])
        self.assertEqual(card, before)

    def test_only_checks_enter_waiting_and_safe_text_contains_no_branch_prose(self) -> None:
        machine = chr(67) + ":/private"
        card = observed(tasks=["FB-001"], _head_tasks={"FB-001": {"status": "awaiting_review"}},
                        name=f"RAW-NAME {machine}", branch="RAW-BRANCH", subject="RAW-SUBJECT")
        card["tracking"] = self.state(card)
        items = view.Waiting("en").tracking([card])
        self.assertEqual(len(items), 1)
        safe = items[0]["safe"]
        self.assertIn("FB-001", safe)
        for text in ("RAW-NAME", machine, "RAW-BRANCH", "RAW-SUBJECT"):
            self.assertNotIn(text, safe)
        for state in ("info", "unknown", "none"):
            self.assertEqual(view.Waiting("en").tracking([{**card, "tracking": {"state": state}}]), [])


if __name__ == "__main__":
    unittest.main()
