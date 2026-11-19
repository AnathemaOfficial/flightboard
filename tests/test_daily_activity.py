# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Daily activity reuses already-read history and applied declarations; no Git or file fixtures."""
from __future__ import annotations

import copy
import unittest
from datetime import timedelta

from tests.fixtures import NOW, light, load

overlay = load("overlay")
view = load("view")


def event(before, after, *, where="main", at=None, **extra):
    return {"at": at or NOW.isoformat(), "from": before, "to": after, "where": where, **extra}


def session(name, base, head, *, allowed=True, at=None):
    changes = overlay.task_changes(base, head)
    return {"id": name, "name": name, "changes": changes, "_changes": changes,
            "_head_tasks": head, "overlay": allowed, "last_activity": at or NOW.isoformat(),
            "subject": "A declared status"}


def session_days(main, sessions):
    live, _ = overlay.overlay(main, sessions)
    events = view._session_events(sessions)
    events.sort(key=lambda item: item["at"], reverse=True)
    return overlay.daily(view._applied_moves(sessions, live, events), NOW, zone=NOW.tzinfo)


class DailyActivityTest(unittest.TestCase):
    def test_new_planned_and_initial_statuses_are_distinct_activity_categories(self):
        events = [event(None, "planned"), event(None, "in_progress", where="session"),
                  event(None, "done"), event(None, "awaiting_review", where="session")]
        day = overlay.daily(events, NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual(day, {"day": NOW.date().isoformat(), "new_main": 2, "new_live": 2,
                               "progress_main": 0, "progress_live": 1, "done_main": 1, "done_live": 0,
                               "review_main": 0, "review_live": 1})

    def test_existing_tasks_starting_count_without_becoming_new(self):
        day = overlay.daily([event("planned", "in_progress"), event("ready", "in_progress", where="a")],
                            NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual((day["progress_main"], day["progress_live"], day["new_main"], day["new_live"]),
                         (1, 1, 0, 0))

    def test_a_session_named_main_is_still_live_for_every_activity_category(self):
        declared = [event(None, "planned", session_id="worktree-main"),
                    event("planned", "in_progress", session_id="worktree-main"),
                    event("in_progress", "awaiting_review", session_id="worktree-main"),
                    event("awaiting_review", "done", session_id="worktree-main")]
        day = overlay.daily([event(None, "planned"), *declared], NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual(day, {"day": NOW.date().isoformat(), "new_main": 1, "new_live": 1,
                               "progress_main": 0, "progress_live": 1, "done_main": 0, "done_live": 1,
                               "review_main": 0, "review_live": 1})

    def test_missing_before_is_not_a_creation_and_removal_is_not_activity(self):
        events = [{"at": NOW.isoformat(), "to": "in_progress", "where": "main"},
                  event("planned", None), event(None, None)]
        day = overlay.daily(events, NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual(day["progress_main"], 1)
        self.assertEqual(sum(value for key, value in day.items() if key != "day"), 1)

    def test_invalid_naive_outside_and_future_dates_are_not_counted(self):
        bad = ["not a date", NOW.replace(tzinfo=None).isoformat(),
               (NOW - timedelta(days=overlay.DAYS)).isoformat(), (NOW + timedelta(days=1)).isoformat(),
               "9999-12-31T23:59:59-12:00"]
        days = overlay.daily([event(None, "in_progress", at=at) for at in bad], NOW, zone=NOW.tzinfo)
        self.assertEqual(len(days), overlay.DAYS)
        self.assertFalse(any(value for day in days for key, value in day.items() if key != "day"))

    def test_local_midnight_and_oldest_included_day_keep_the_existing_window(self):
        events = [event(None, "in_progress", at="2026-11-07T02:30:00Z"),
                  event(None, "planned", at=(NOW - timedelta(days=overlay.DAYS - 1)).isoformat())]
        days = overlay.daily(events, NOW, zone=NOW.tzinfo)
        self.assertEqual((days[-2]["new_main"], days[-2]["progress_main"]), (1, 1))
        self.assertEqual((days[-1]["new_main"], days[-1]["progress_main"]), (0, 0))
        self.assertEqual(days[0]["new_main"], 1)

    def test_initial_history_snapshot_is_not_reinvented_as_new_work(self):
        tasks = light({"FB-101": "planned"})
        first = {"at": NOW.timestamp() - 60, "sha": "a" * 40, "via": "baseline", "tasks": tasks}
        self.assertEqual(overlay.history_events([first], NOW.tzinfo), [])
        second = {"at": NOW.timestamp(), "sha": "b" * 40, "via": "add and start",
                  "tasks": light({"FB-101": "in_progress", "FB-102": "planned"})}
        day = overlay.daily(overlay.history_events([first, second], NOW.tzinfo), NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual((day["new_main"], day["progress_main"]), (1, 1))

    def test_equivalent_sessions_count_one_new_task_and_initial_start(self):
        main = light({"FB-101": "planned"})
        head = light({"FB-101": "planned", "FB-102": "in_progress"})
        sessions = [session(name, main, head) for name in ("a", "b")]
        day = session_days(main, sessions)[-1]
        self.assertEqual((day["new_live"], day["progress_live"]), (1, 1))

    def test_branch_addition_main_already_knows_is_not_counted_as_new_again(self):
        main = light({"FB-101": "planned"})
        head = light({"FB-101": "in_progress"})
        sessions = [session("a", main, head, at=(NOW - timedelta(minutes=2)).isoformat()),
                    session("b", {}, head)]
        live, _ = overlay.overlay(main, sessions)
        events = view._session_events(sessions)
        events.sort(key=lambda item: item["at"], reverse=True)
        original = copy.deepcopy(events)
        moves = view._applied_moves(sessions, live, events)
        self.assertEqual(len(moves), 1)
        self.assertIsNone(moves[0]["from"])
        self.assertFalse(moves[0]["new"])
        self.assertEqual(events, original, "normalizing chart events must not mutate public event declarations")
        day = overlay.daily(moves, NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual((day["new_live"], day["progress_live"]), (0, 1))

    def test_main_already_holds_a_start_so_only_its_history_counts(self):
        main = light({"FB-101": "in_progress"})
        sessions = [session("a", light({"FB-101": "planned"}), main)]
        live, _ = overlay.overlay(main, sessions)
        declared = view._session_events(sessions)
        moves = [event("planned", "in_progress")] + view._applied_moves(sessions, live, declared)
        day = overlay.daily(moves, NOW, zone=NOW.tzinfo)[-1]
        self.assertEqual((day["progress_main"], day["progress_live"], day["new_live"]), (1, 0, 0))

    def test_governed_disallowed_conflicting_and_colliding_work_stays_excluded(self):
        main = light({"FB-101": "planned", "FB-007": "ready"})
        allowed_head = light({"FB-101": "in_progress", "FB-007": "ready"})
        human_head = light({"FB-101": "planned", "FB-007": "in_progress", "FB-102": "planned"})
        human_head["FB-102"]["owner"] = "owner"
        contested = light({"FB-101": "done", "FB-007": "ready"})
        one = light({"FB-101": "planned", "FB-007": "ready", "FB-103": "planned"},
                    titles={"FB-103": "One identity"})
        two = light({"FB-101": "planned", "FB-007": "ready", "FB-103": "planned"},
                    titles={"FB-103": "Another identity"})
        sessions = [session("a", main, allowed_head), session("b", main, contested),
                    session("c", main, human_head), session("d", main, one), session("e", main, two),
                    session("z", main, allowed_head, allowed=False)]
        days = session_days(main, sessions)
        self.assertFalse(any(value for day in days for key, value in day.items() if key != "day"))


if __name__ == "__main__":
    unittest.main()
