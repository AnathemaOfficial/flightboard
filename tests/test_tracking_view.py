# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tracking diagnostics describe temporal observations without changing task progress."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
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

    def test_tracking_reminders_cannot_hide_a_task_awaiting_review(self) -> None:
        cards = [observed(id=f"worker-{number}", name=f"worker-{number}", activity="active")
                 for number in range(35)]
        adapter = roadmap()
        ledger = adapter.parse(encoded({**BASE, "FB-002": "awaiting_review"}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual(len(value["waiting"]), 30)
        self.assertEqual(value["waiting"][0]["kind"], "review")
        self.assertEqual(value["waiting"][0]["tasks"], ["FB-002"])
        self.assertTrue(any(item["kind"] == "tracking" for item in value["waiting"]))

    def test_visible_next_task_keeps_its_detail_when_reminders_exceed_the_detail_budget(self) -> None:
        adapter = load("ledgers").make("tasks", "tasks.json")
        history = [f"OLD-{number:03}" for number in range(520)]
        raw = {"version": 1, "tasks": [
            {"id": "NEXT-1", "title": "Next visible work", "status": "planned", "owner": "codex"},
            *({"id": tid, "title": "Past work", "status": "done", "owner": "codex"} for tid in history)]}
        ledger = adapter.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(ledger["valid"], ledger["error"])
        cards = []
        for number in range(13):
            names = history[number * 40:(number + 1) * 40]
            cards.append(observed(id=f"worker-{number}", name=f"worker-{number}", activity="active",
                                  tasks=names, _head_tasks={tid: ledger["tasks"][tid] for tid in names}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual([row["id"] for row in value["next"]], ["NEXT-1"])
        self.assertTrue(all(item["kind"] == "tracking" for item in value["waiting"]))
        reminder_ids = {tid for item in value["waiting"] for tid in item["tasks"]}
        self.assertEqual(len(reminder_ids), 520)
        self.assertTrue("NEXT-1" in value["tasks"], "the visible next task must retain its detail")
        self.assertEqual(value["tasks"]["NEXT-1"]["title"], "Next visible work")
        self.assertLessEqual(len(value["tasks"]), 500)

    def test_hidden_waiting_reminders_do_not_preempt_a_visible_session_task_detail(self) -> None:
        adapter = load("ledgers").make("tasks", "tasks.json")
        history = [f"OLD-{number:03}" for number in range(520)]
        raw = {"version": 1, "tasks": [
            {"id": "VISIBLE-1", "title": "Visible current work", "status": "in_progress", "owner": "codex"},
            *({"id": tid, "title": "Past work", "status": "done", "owner": "codex"} for tid in history)]}
        ledger = adapter.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(ledger["valid"], ledger["error"])
        cards = [observed(id=f"aa-{number:02}", name=f"aa-{number:02}", activity="active") for number in range(30)]
        cards.append(observed(id="ab-current", name="ab-current", activity="active", tasks=["VISIBLE-1"],
                              _head_tasks={"VISIBLE-1": ledger["tasks"]["VISIBLE-1"]}))
        for number in range(13):
            names = history[number * 40:(number + 1) * 40]
            cards.append(observed(id=f"zz-{number:02}", name=f"zz-{number:02}", activity="active", tasks=names,
                                  _head_tasks={tid: ledger["tasks"][tid] for tid in names}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual(value["next"], [])
        self.assertEqual(len(value["waiting"]), 30)
        self.assertTrue(all(not item["tasks"] for item in value["waiting"]))
        self.assertTrue("VISIBLE-1" in value["tasks"], "a visible card task must not lose detail to hidden reminders")
        self.assertEqual(value["tasks"]["VISIBLE-1"]["title"], "Visible current work")
        self.assertLessEqual(len(value["tasks"]), 500)

    def test_visible_reminder_ids_do_not_preempt_an_interactive_session_task_detail(self) -> None:
        adapter = load("ledgers").make("tasks", "tasks.json")
        history = [f"OLD-{number:03}" for number in range(520)]
        raw = {"version": 1, "tasks": [
            {"id": "VISIBLE-1", "title": "Visible current work", "status": "in_progress", "owner": "codex"},
            *({"id": tid, "title": "Past work", "status": "done", "owner": "codex"} for tid in history)]}
        ledger = adapter.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(ledger["valid"], ledger["error"])
        cards = []
        for number in range(13):
            names = history[number * 40:(number + 1) * 40]
            cards.append(observed(id=f"aa-{number:02}", name=f"aa-{number:02}", activity="active", tasks=names,
                                  _head_tasks={tid: ledger["tasks"][tid] for tid in names}))
        cards.append(observed(id="zz-current", name="zz-current", activity="active", tasks=["VISIBLE-1"],
                              _head_tasks={"VISIBLE-1": ledger["tasks"]["VISIBLE-1"]}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual(value["next"], [])
        self.assertTrue(all(item["kind"] == "tracking" for item in value["waiting"]))
        reminder_ids = {tid for item in value["waiting"] for tid in item["tasks"]}
        self.assertEqual(len(reminder_ids), 520)
        visible = next(card for card in value["sessions"] if card["id"] == "zz-current")
        self.assertEqual(visible["tasks"], ["VISIBLE-1"])
        self.assertTrue("VISIBLE-1" in value["tasks"], "visible reminders must not evict an interactive task detail")
        self.assertEqual(value["tasks"]["VISIBLE-1"]["title"], "Visible current work")
        self.assertLessEqual(len(value["tasks"]), 500)

    def test_quiet_session_history_does_not_preempt_a_current_card_task_detail(self) -> None:
        adapter = load("ledgers").make("tasks", "tasks.json")
        history = [f"OLD-{number:03}" for number in range(520)]
        raw = {"version": 1, "tasks": [
            {"id": "VISIBLE-1", "title": "Visible current work", "status": "in_progress", "owner": "codex"},
            *({"id": tid, "title": "Past work", "status": "done", "owner": "codex"} for tid in history)]}
        ledger = adapter.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(ledger["valid"], ledger["error"])
        cards = []
        for number in range(13):
            names = history[number * 40:(number + 1) * 40]
            cards.append(observed(id=f"aa-{number:02}", name=f"aa-{number:02}", tasks=names,
                                  ledger_file_modified_at=RECENT,
                                  _head_tasks={tid: ledger["tasks"][tid] for tid in names}))
        cards.append(observed(id="zz-current", name="zz-current", activity="active", tasks=["VISIBLE-1"],
                              _head_tasks={"VISIBLE-1": ledger["tasks"]["VISIBLE-1"]}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual(value["next"], [])
        self.assertEqual(len(value["waiting"]), 13)
        self.assertTrue(all(item["kind"] == "session" for item in value["waiting"]))
        self.assertEqual(sum(len(item["tasks"]) for item in value["waiting"]), 520)
        self.assertIn("VISIBLE-1", value["tasks"])
        self.assertEqual(value["tasks"]["VISIBLE-1"]["title"], "Visible current work")
        self.assertLessEqual(len(value["tasks"]), 500)

    def test_head_only_completed_tasks_do_not_preempt_a_current_card_task_detail(self) -> None:
        adapter = load("ledgers").make("tasks", "tasks.json")
        history = [f"OLD-{number:03}" for number in range(520)]
        main = {"version": 1, "tasks": [
            {"id": "VISIBLE-1", "title": "Visible current work", "status": "in_progress", "owner": "codex"}]}
        ledger = adapter.parse(json.dumps(main).encode("utf-8"))
        head = adapter.parse(json.dumps({"version": 1, "tasks": [
            {"id": tid, "title": "Past session work", "status": "done", "owner": "codex"}
            for tid in history]}).encode("utf-8"))
        self.assertTrue(ledger["valid"], ledger["error"])
        self.assertTrue(head["valid"], head["error"])
        cards = []
        for number in range(13):
            names = history[number * 40:(number + 1) * 40]
            cards.append(observed(id=f"aa-{number:02}", name=f"aa-{number:02}", activity="active", tasks=names,
                                  _head_tasks={tid: head["tasks"][tid] for tid in names}))
        cards.append(observed(id="zz-current", name="zz-current", activity="active", tasks=["VISIBLE-1"],
                              _head_tasks={"VISIBLE-1": ledger["tasks"]["VISIBLE-1"]}))
        value = build(cards, ledger=ledger, ledger_adapter=adapter)
        self.assertEqual(value["next"], [])
        self.assertTrue(all(item["kind"] == "tracking" for item in value["waiting"]))
        self.assertEqual(sum(len(item["tasks"]) for item in value["waiting"]), 520)
        self.assertIn("VISIBLE-1", value["tasks"])
        self.assertEqual(value["tasks"]["VISIBLE-1"]["title"], "Visible current work")
        historical = next(tid for tid in history if tid in value["tasks"])
        self.assertEqual(value["tasks"][historical]["status"], "done")
        self.assertTrue(value["tasks"][historical]["declared_in"].startswith("aa-"))
        self.assertLessEqual(len(value["tasks"]), 500)

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
