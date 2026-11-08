# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the ledger side of flightboard: reading, changes, the live overlay and main's history. Pure functions: no
git, no file.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import copy
import json
import unittest
from datetime import timedelta
from unittest import mock

from tests.fixtures import BASE, NOW, decision, encoded, ledger, light, load, roadmap

overlay = load("overlay")
view = load("view")
gitreads = load("gitreads")
roadmap_module = load("ledgers.roadmap")
rules = load("ledgers.roadmap_rules")
text = load("text")


def change(tid: str, before: str | None, after: str | None, uncommitted: bool = False, owner: str = "claude") -> dict:
    return {"task": tid, "title": f"Task {tid}", "milestone": "M0", "owner": owner, "from": before, "to": after,
            "new": before is None, "removed": after is None, "uncommitted": uncommitted, "back": False}


def session(name: str, changes: list[dict], overlay_it: bool = True, head: dict | None = None) -> dict:
    return {"name": name, "changes": changes, "overlay": overlay_it, "_head_tasks": head or {}}


class ParseLedgerTest(unittest.TestCase):
    def test_a_valid_ledger(self) -> None:
        parsed = roadmap().parse(encoded(BASE))
        self.assertTrue(parsed["valid"], parsed["error"])
        self.assertEqual(parsed["updated_at"], "2026-11-06")
        self.assertEqual(parsed["tasks"]["FB-007"]["owner"], "owner")
        self.assertEqual(parsed["tasks"]["FB-001"]["title"], "Task FB-001")

    def test_an_invalid_ledger_is_read_but_marked(self) -> None:
        raw = ledger({**BASE, "FB-003": "done"})
        raw["tasks"][2]["evidence"] = []
        parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
        self.assertFalse(parsed["valid"])
        self.assertIn("FB-003", parsed["error"])

    def test_what_is_not_a_ledger_gives_none(self) -> None:
        for data in (None, b"", b"{", b"[]", b'{"tasks": 3}', b'{"tasks": []}', b"<<<<<<< HEAD\n{}",
                     b"\xff\xfe\x00", b'{"tasks": [], "tasks": []}', b'{"tasks": [{"id": "FB-001", "x": NaN}]}',
                     b'{"a": Infinity}', b"[" * 100000):
            with self.subTest(data=data[:30] if data else data):
                self.assertIsNone(roadmap().parse(data))

    def test_odd_sections_are_not_a_ledger(self) -> None:
        for key, value in (("decisions", 1), ("decisions", True), ("milestones", 3), ("external_dependencies", "x")):
            with self.subTest(key=key, value=value):
                raw = ledger(BASE)
                raw[key] = value
                self.assertIsNone(roadmap().parse(json.dumps(raw).encode("utf-8")))

    def test_a_huge_ledger_is_read_but_never_validated(self) -> None:
        raw = ledger(BASE)
        raw["tasks"][1]["dependencies"] = ["FB-001"]
        raw["external_dependencies"] = [{"id": "EXT:x"}]
        self.assertEqual(roadmap_module.sizes(raw), {"tasks": 7, "dependencies": 1, "exit_citations": 2,
                                                     "milestones": 2, "external_dependencies": 1, "decisions": 0})
        for name, value in (("tasks", 6), ("dependencies", 0), ("exit_citations", 1), ("milestones", 1),
                            ("external_dependencies", 0)):
            with self.subTest(name=name), mock.patch.dict(roadmap_module.MAX_VALIDATED, {name: value}), \
                    mock.patch.object(rules, "validate_ledger", side_effect=AssertionError("validated")):
                parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
                self.assertFalse(parsed["valid"])
                self.assertEqual(parsed["error"], f"ledger too big to be validated here (too many {name})")
                self.assertEqual(sorted(parsed["tasks"]), sorted(BASE))

    def test_an_impossible_date_is_empty(self) -> None:
        self.assertEqual(text.iso(10 ** 15, NOW.tzinfo), "")
        self.assertTrue(text.iso(1794020762, NOW.tzinfo).startswith("2026-11-"))

    def test_an_oversized_ledger_is_not_read(self) -> None:
        data = encoded(BASE)
        with mock.patch.object(roadmap_module, "MAX_LEDGER_BYTES", len(data) - 1):
            self.assertIsNone(roadmap().parse(data))

    def test_odd_task_entries_are_skipped_and_text_cleaned(self) -> None:
        raw = ledger(BASE)
        raw["tasks"][0]["title_fr"] = "title\u202e\u0000 hidden" + "x" * 500
        raw["tasks"] += [3, {"id": "not-an-id", "status": "done"}, {"id": "FB-009", "status": "finished"},
                         {"id": "FB-009", "status": ["done"]}]
        parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
        self.assertEqual(sorted(parsed["tasks"]), sorted(BASE))
        title = parsed["tasks"]["FB-001"]["title"]
        self.assertNotIn("\u202e", title)
        self.assertLessEqual(len(title), 200)

    def test_a_validator_crash_means_invalid(self) -> None:
        with mock.patch.object(rules, "validate_ledger", side_effect=OverflowError):
            self.assertFalse(roadmap().parse(encoded(BASE))["valid"])


class ChangesTest(unittest.TestCase):
    def test_changes_are_measured_against_the_base(self) -> None:
        base = light({"FB-001": "planned", "FB-002": "in_progress", "FB-003": "ready"})
        head = light({"FB-001": "done", "FB-002": "in_progress", "FB-004": "planned"})
        changes = overlay.task_changes(base, head)
        self.assertEqual([(c["task"], c["from"], c["to"], c["new"], c["removed"]) for c in changes],
                         [("FB-001", "planned", "done", False, False), ("FB-003", "ready", None, False, True),
                          ("FB-004", None, "planned", True, False)])
        self.assertFalse(any(c["uncommitted"] for c in changes))

    def test_a_change_absent_from_the_last_commit_is_uncommitted(self) -> None:
        base = light({"FB-001": "planned", "FB-002": "planned", "FB-003": "ready"})
        tip = light({"FB-001": "in_progress", "FB-002": "done", "FB-003": "ready"})
        head = light({"FB-001": "done", "FB-002": "done", "FB-004": "ready"})
        flags = {c["task"]: c["uncommitted"] for c in overlay.task_changes(base, head, tip)}
        self.assertEqual(flags, {"FB-001": True, "FB-002": False, "FB-003": True, "FB-004": True})

    def test_a_move_back_is_marked(self) -> None:
        changes = overlay.task_changes(light({"FB-001": "done"}), light({"FB-001": "in_progress"}))
        self.assertTrue(changes[0]["back"])
        self.assertFalse(overlay.task_changes(light({"FB-001": "done"}), light({"FB-001": "dropped"}))[0]["back"])

    def test_decisions_and_other_sections(self) -> None:
        base = roadmap().parse(encoded(BASE))
        head = roadmap().parse(encoded(BASE, decisions=[decision()]))
        found = overlay.decision_changes(base["decisions"], head["decisions"])
        self.assertEqual([(d["id"], d["new"], d["quote"]) for d in found], [("ADR-0099", True, "Yes, switch over")])
        raw = copy.deepcopy(head["raw"])
        raw["capacity"]["claude_sessions_per_week"] = 99
        self.assertEqual(roadmap().section_changes(head["raw"], raw), ["capacity"])


class OverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.main = light({**BASE, "FB-002": "awaiting_review"})

    def live(self, *sessions: dict) -> dict:
        return overlay.overlay(self.main, list(sessions))[0]

    def test_without_session_the_live_view_is_main(self) -> None:
        live = self.live()
        self.assertEqual({tid: e["status"] for tid, e in live.items()}, {**BASE, "FB-002": "awaiting_review"})
        self.assertFalse(any(e["sources"] or e["conflict"] or e["new"] or e["collision"] for e in live.values()))

    def test_a_change_applies_when_main_still_holds_the_base(self) -> None:
        live = self.live(session("a", [change("FB-001", "planned", "in_progress", uncommitted=True)]))
        self.assertEqual((live["FB-001"]["status"], live["FB-001"]["status_main"]), ("in_progress", "planned"))
        self.assertEqual(live["FB-001"]["sources"], [{"session": "a", "from": "planned", "to": "in_progress",
                                                      "uncommitted": True, "applied": True, "reason": "", "other": "",
                                                      "governed": ""}])

    def test_a_change_main_already_holds_is_clean(self) -> None:
        live = self.live(session("a", [change("FB-002", "in_progress", "awaiting_review")]))
        self.assertEqual(live["FB-002"]["status"], "awaiting_review")
        self.assertFalse(live["FB-002"]["conflict"])

    def test_when_main_moved_elsewhere_main_stays(self) -> None:
        for after in ("done", "ready", "blocked"):
            with self.subTest(after=after):
                live = self.live(session("a", [change("FB-002", "in_progress", after)]))
                self.assertEqual((live["FB-002"]["status"], live["FB-002"]["conflict"]), ("awaiting_review", True))
                self.assertEqual(live["FB-002"]["sources"][0]["reason"], "main_changed")

    def test_two_sessions_moving_a_task_differently_leave_main(self) -> None:
        live = self.live(session("b", [change("FB-001", "planned", "done")]),
                         session("a", [change("FB-001", "planned", "in_progress")]))
        self.assertEqual((live["FB-001"]["status"], live["FB-001"]["conflict"]), ("planned", True))
        self.assertEqual((live["FB-001"]["sources"][1]["reason"], live["FB-001"]["sources"][1]["other"]),
                         ("changed_elsewhere", "a"))
        same = self.live(session("b", [change("FB-001", "planned", "done")]),
                         session("a", [change("FB-001", "planned", "done")]))
        self.assertEqual((same["FB-001"]["status"], same["FB-001"]["conflict"]), ("done", False))

    def test_owner_and_reviewer_tasks_never_move_here(self) -> None:
        live = self.live(session("a", [change("FB-007", "ready", "done", owner="owner")]))
        self.assertEqual(live["FB-007"]["status"], "ready")
        source = live["FB-007"]["sources"][0]
        self.assertFalse(source["applied"])
        self.assertEqual((source["governed"], source["reason"]), ("owner", "governed"))
        reviewed = self.live(session("a", [change("FB-003", "ready", "done", owner="reviewer")]))
        self.assertEqual(reviewed["FB-003"]["status"], "ready")
        self.assertEqual((reviewed["FB-003"]["sources"][0]["governed"], reviewed["FB-003"]["sources"][0]["reason"]),
                         ("reviewer", "governed"))

    def test_a_session_not_allowed_to_overlay_changes_nothing(self) -> None:
        live = self.live(session("a", [change("FB-001", "planned", "done")], overlay_it=False))
        self.assertEqual((live["FB-001"]["status"], live["FB-001"]["sources"]), ("planned", []))

    def test_a_new_task_and_an_id_collision(self) -> None:
        x = light({**BASE, "FB-139": "planned"}, titles={"FB-139": "One task"})
        y = light({**BASE, "FB-139": "ready"}, titles={"FB-139": "Another task"})
        live = self.live(session("x", [change("FB-139", None, "planned")], head=x))
        self.assertTrue(live["FB-139"]["new"])
        self.assertIsNone(live["FB-139"]["status_main"])
        both = self.live(session("x", [change("FB-139", None, "planned")], head=x),
                         session("y", [change("FB-139", None, "ready")], head=y))
        self.assertTrue(both["FB-139"]["collision"])
        self.assertEqual(both["FB-139"]["status"], "planned")

    def test_a_removal_is_reported_never_applied(self) -> None:
        live = self.live(session("a", [change("FB-003", "ready", None)]))
        self.assertEqual(live["FB-003"]["status"], "ready")
        self.assertIsNone(live["FB-003"]["sources"][0]["to"])
        self.assertEqual(live["FB-003"]["sources"][0]["reason"], "removed")

    def test_what_main_cannot_hold_becomes_a_note(self) -> None:
        main = light({key: value for key, value in BASE.items() if key != "FB-003"})
        gone = session("a", [change("FB-003", "ready", "awaiting_review"), change("FB-004", "planned", None)])
        both_removed = session("b", [change("FB-003", "ready", None)])
        owner_task = light({**BASE, "FB-140": "done"})
        owner_task["FB-140"]["owner"] = "owner"
        added = session("c", [change("FB-140", None, "done", owner="owner")], head=owner_task)
        live, notes = overlay.overlay(main, [gone, both_removed, added])
        self.assertNotIn("FB-003", live)
        self.assertNotIn("FB-140", live)
        self.assertEqual([(note["kind"], note["task"], note["session"]) for note in notes],
                         [("orphan", "FB-003", "a"), ("governed", "FB-140", "c")])
        self.assertEqual(notes[1]["owner"], "owner")
        self.assertEqual(live["FB-004"]["status"], "planned")

    def test_the_order_of_sessions_never_matters(self) -> None:
        a = session("a", [change("FB-001", "planned", "dropped")])
        b = session("b", [change("FB-001", "planned", "done")])
        self.assertEqual(self.live(a, b), self.live(b, a))


class HistoryTest(unittest.TestCase):
    def test_versions_keep_only_moves_that_changed_a_task(self) -> None:
        ledgers = {"1" * 40: {"tasks": light(BASE)}, "2" * 40: {"tasks": light(BASE)},
                   "3" * 40: None, "4" * 40: {"tasks": light({**BASE, "FB-002": "awaiting_review"})}}
        entries = [{"sha": sha, "at": 1_000 * index, "via": f"v{index}", "approx": False}
                   for index, sha in enumerate(ledgers)]
        versions = overlay.history_versions(entries, ledgers)
        self.assertEqual([version["via"] for version in versions], ["v0", "v3"])
        events = overlay.history_events(versions, NOW.tzinfo)
        self.assertEqual([(e["task"], e["from"], e["to"], e["sha"], e["subject"]) for e in events],
                         [("FB-002", "in_progress", "awaiting_review", "4444444", "v3")])

    def test_daily_counts(self) -> None:
        events = [{"at": (NOW - timedelta(days=days)).isoformat(), "to": to, "where": where}
                  for days, to, where in ((0, "done", "main"), (0, "awaiting_review", "a"), (1, "done", "a"),
                                          (2, "in_progress", "main"), (30, "done", "main"))]
        days = overlay.daily(events, NOW, zone=NOW.tzinfo)
        self.assertEqual(len(days), overlay.DAYS)
        self.assertEqual(days[-1], {"day": "2026-11-07", "done_main": 1, "review_main": 0, "done_live": 0,
                                    "review_live": 1})
        self.assertEqual(days[-2]["done_live"], 1)
        self.assertEqual(sum(d["done_main"] for d in days), 1)


class RulesTest(unittest.TestCase):
    def test_task_ids_in_names_and_messages(self) -> None:
        known = {"FB-M3-11", "FB-M3-07", "FB-210"}
        texts = ["claude/fb-m3-11-export-a1b2c3", "commit: csv export (FB-M3-07)", "FB-210 done",
                 "fb-m3-110 is not one", "FB-999 unknown", "FB-M3-07 again"]
        self.assertEqual(view.infer_tasks(texts, known), ["FB-M3-11", "FB-M3-07", "FB-210"])

    def test_activity_thresholds(self) -> None:
        for when, expected in ((NOW - timedelta(minutes=3), "active"), (NOW - timedelta(minutes=50), "recent"),
                               (NOW - timedelta(hours=5), "quiet"), (None, "unknown"),
                               (NOW + timedelta(minutes=2), "active")):
            with self.subTest(when=when):
                self.assertEqual(view.activity(when, NOW), expected)

    def test_advice_never_says_more_than_the_state(self) -> None:
        live = {"FB-001": {"status": "done", "status_main": "done"},
                "FB-002": {"status": "awaiting_review", "status_main": "awaiting_review"},
                "FB-003": {"status": "done", "status_main": "awaiting_review"}}
        base = {"kind": "worktree", "ahead": 1, "stage": "committed", "tasks": ["FB-001"], "reason": "",
                "activity": "quiet", "kept": 0, "files_read": True,
                "_head_tasks": {"FB-001": {"status": "awaiting_review"}}}
        self.assertEqual(view._advice(base, live), "ready_to_merge")
        for override in ({"activity": "active"}, {"stage": "uncommitted"}, {"reason": "invalid_ledger"},
                         {"tasks": []}, {"_head_tasks": {"FB-001": {"status": "in_progress"}}},
                         {"files_read": False}):
            with self.subTest(override=override):
                self.assertEqual(view._advice({**base, **override}, live), "open")
        merged = {**base, "ahead": 0, "stage": "merged"}
        self.assertEqual(view._advice(merged, live), "ended")
        # modified files not read: nothing says it is all in main
        self.assertEqual(view._advice({**merged, "files_read": False}, live), "merged")
        self.assertEqual(view._advice({**merged, "tasks": ["FB-002"]}, live), "keep_for_review")
        self.assertEqual(view._advice({**merged, "kept": 2}, live), "keep_files")
        self.assertEqual(view._advice({**merged, "kind": "checkout"}, live), "")
        # another session's unmerged claim never ends a session: main still holds the review
        self.assertEqual(view._advice({**merged, "tasks": ["FB-003"]}, live), "keep_for_review")
        dropped = {**live, "FB-001": {"status": "dropped", "status_main": "dropped"}}
        self.assertEqual(view._advice(merged, dropped), "ended")  # a task dropped in main leaves nothing waiting

    def test_a_copy_the_remote_carried_further_is_never_in_main(self) -> None:
        state = {"conflicted": 0, "operation": "", "modified": 0, "untracked": 0, "kind": "worktree", "ahead": 0,
                 "remote": "behind"}
        self.assertEqual(view._stage(state), "behind_origin")
        self.assertEqual(view._stage({**state, "remote": "pushed"}), "merged")
        self.assertEqual(view._stage({**state, "kind": "checkout"}), "up_to_date")
        session_ = {**state, "stage": "behind_origin", "tasks": ["FB-001"], "reason": "", "activity": "quiet",
                    "kept": 0, "files_read": True, "_head_tasks": {}}
        live = {"FB-001": {"status": "done", "status_main": "done"}}
        self.assertEqual(view._advice(session_, live), "open")  # never "ended" while the remote holds more
        self.assertEqual(view._advice({**session_, "gone": True, "stage": "merged"}, live), "gone")


def card(name: str, **values) -> dict:
    """A session as the view reads it, with only what a test sets."""
    return {"name": name, "kind": "branch", "advice": "", "stage": "committed", "decisions": [], "_changes": [],
            "reason": "", "reason_text": "", "activity": "quiet", "files_read": True, "tasks": [], "inferred": [],
            "last_activity": "", "ahead": 1, "operation": "", "stale": False, "_head_tasks": {}, **values}


class ViewTest(unittest.TestCase):
    def test_a_review_waits_since_main_moved_it(self) -> None:
        live = {"FB-002": {"status": "awaiting_review", "status_main": "awaiting_review",
                           "sources": [{"session": "b", "to": "awaiting_review", "applied": True}]},
                "FB-003": {"status": "awaiting_review", "status_main": "ready",
                           "sources": [{"session": "a", "to": "awaiting_review", "applied": True},
                                       {"session": "c", "to": "awaiting_review", "applied": True}]}}
        events = [{"task": tid, "to": "awaiting_review", "where": where, "at": f"2026-11-07T{hour}:00:00-05:00"}
                  for tid, where, hour in (("FB-002", "b", "10"), ("FB-003", "c", "09"), ("FB-002", "main", "08"),
                                           ("FB-003", "a", "07"), ("FB-003", "z", "06"))]  # newest first
        self.assertEqual(view._review_since(live, events), {"FB-002": "2026-11-07T08:00:00-05:00",
                                                            "FB-003": "2026-11-07T07:00:00-05:00"})

    def test_a_move_main_already_holds_is_counted_once(self) -> None:
        live = {"FB-002": {"status_main": "awaiting_review",
                           "sources": [{"session": "b", "to": "awaiting_review", "applied": True}]},
                "FB-003": {"status_main": "ready",
                           "sources": [{"session": "a", "to": "awaiting_review", "applied": True}]}}
        events = [{"task": "FB-002", "where": "b"}, {"task": "FB-003", "where": "a"}, {"task": "FB-002", "where": "main"}]
        self.assertEqual([(m["task"], m["where"]) for m in view._applied_moves([], live, events)], [("FB-003", "a")])

    def test_a_task_the_live_view_lacks_is_shown_as_declared(self) -> None:
        live = overlay.overlay(light(BASE), [])[0]
        head = light({**BASE, "FB-150": "ready"})
        details = view._details({"FB-150", "FB-001", "FB-999"}, live, [card("claude/x", _head_tasks=head)])
        self.assertEqual(sorted(details), ["FB-001", "FB-150"])
        self.assertEqual((details["FB-150"]["status"], details["FB-150"]["status_main"],
                          details["FB-150"]["declared_in"]), ("ready", None, "claude/x"))
        self.assertEqual((details["FB-001"]["status_main"], details["FB-001"]["declared_in"]), ("planned", ""))

    def test_resume_lines_carry_no_branch_text(self) -> None:
        odd = {"id": "ADR-0124", "status": "STATUS-MARK free", "quote": "a quote", "new": True}
        notes = [{"kind": "governed", "task": "FB-302", "title": "x", "session": "claude/y", "to": "ready",
                  "owner": "reviewer"}]
        items = view.Waiting("en").all([card("claude/x", decisions=[odd])], {}, notes, [], None, True)
        safe = [item["safe"] for item in items]
        self.assertIn("ADR-0124 (unknown status), recorded in your name in claude/x (quote on the page)", safe)
        self.assertIn("claude/y adds FB-302, the reviewer's task (Ready): it enters only through main, with your "
                      "agreement", safe)
        self.assertFalse([line for line in safe if "STATUS-MARK" in line or "a quote" in line])

    def test_a_collision_keeps_main_task_in_its_milestone(self) -> None:
        main = light({**BASE, "FB-140": "in_progress"}, titles={"FB-140": "One task"})
        other = light({**BASE, "FB-140": "ready"}, titles={"FB-140": "Another task"})
        live = overlay.overlay(main, [session("x", [change("FB-140", None, "ready")], head=other)])[0]
        self.assertTrue(live["FB-140"]["collision"])
        m0 = next(row for row in roadmap().milestones(ledger(BASE), live, main) if row["id"] == "M0")
        self.assertEqual(m0["total"], sum(1 for task in main.values() if task["milestone"] == "M0"))
        self.assertEqual(m0["counts"]["in_progress"], 2)  # FB-002 and main's own FB-140

    def test_a_stale_branch_takes_no_task(self) -> None:
        live = overlay.overlay(light(BASE), [])[0]
        start = [change("FB-001", "planned", "in_progress")]
        order = {"M0": 0, "M1": 1}
        fresh = view._next(live, [card("claude/a", _changes=start)], roadmap(), ledger(BASE), order)
        stale = view._next(live, [card("claude/a", _changes=start, stale=True, reason="gone")], roadmap(),
                           ledger(BASE), order)
        self.assertNotIn("FB-001", [task["id"] for task in fresh])
        self.assertIn("FB-001", [task["id"] for task in stale])

    def test_a_session_whose_files_were_not_read_is_never_called_quiet(self) -> None:
        quiet = card("tree-a", kind="worktree", stage="uncommitted", activity="quiet")
        self.assertEqual([item["kind"] for item in view.Waiting("en").all([quiet], {}, [], [], None, True)],
                         ["session"])
        self.assertEqual(view.Waiting("en").all([{**quiet, "files_read": False, "activity": "unknown"}], {}, [], [],
                                                None, True), [])

    def test_one_review_slot_reads_right(self) -> None:
        live = {"FB-002": {"status": "awaiting_review", "status_main": "awaiting_review", "title": "x", "sources": [],
                           "conflict": False, "collision": False}}
        for slots, expected in ((1, "FB-002 (1 review planned per week)"), (2, "FB-002 (2 reviews planned per week)")):
            with self.subTest(slots=slots):
                items = view.Waiting("en").all([], live, [], [], slots, True)
                self.assertEqual([item["safe"] for item in items], [expected])

    def test_a_gone_folder_is_no_open_session(self) -> None:
        gone = card("tree-g", kind="worktree", stage="merged", advice="gone", gone=True, files_read=False, ahead=0)
        self.assertEqual(view._kpis({}, {}, [gone, card("claude/a")])["sessions"], 1)


class ParsersTest(unittest.TestCase):
    def test_staged_entries_are_never_cut_silently(self) -> None:
        raw = "".join(f"100644 {'a' * 40} 0\tf{index}.txt\0" for index in range(5)).encode("utf-8")
        self.assertEqual(len(gitreads.parse_staged(raw, 3)), 4)  # one more than the limit: the caller sees the cut
        self.assertEqual(len(gitreads.parse_staged(raw, 10)), 5)
        self.assertEqual(gitreads.parse_staged(b"160000 " + b"b" * 40 + b" 0\tsub\0", 3), [("160000", "sub")])

    def test_status_porcelain_v2(self) -> None:
        raw = ("1 .M N... 100644 100644 100644 " + "a" * 40 + " " + "b" * 40 + " data/roadmap.json\0"
               "1 D. N... 100644 000000 000000 " + "a" * 40 + " " + "0" * 40 + " old file.txt\0"
               "u UU N... 100644 100644 100644 100644 " + "a" * 40 + " " + "b" * 40 + " " + "c" * 40 + " conflict.md\0"
               "? scripts/new.py\0! ignored.log\0").encode("utf-8")
        self.assertEqual(gitreads.parse_status(raw),  # untracked names are never git's to list here
                         [{"kind": "modified", "path": "data/roadmap.json", "deleted": False},
                          {"kind": "modified", "path": "old file.txt", "deleted": True},
                          {"kind": "conflict", "path": "conflict.md", "deleted": False}])

    def test_refs_and_batches(self) -> None:
        sha = "a" * 40
        refs = gitreads.parse_refs(f"refs/heads/main\x00{sha}\x001794020762\nrefs/tags/x\x00{sha}\x001\n".encode())
        self.assertEqual(refs, {"refs/heads/main": {"sha": sha, "at": 1794020762}})
        self.assertEqual(gitreads.parse_batch_check(f"{sha} blob 12\n{sha}:x missing\n".encode(), 3),
                         [12, None, None])
        batch = f"{sha} blob 3\nabc\n{sha}:x missing\n{sha} tree 2\nzz\n".encode()
        self.assertEqual(gitreads.parse_batch(batch, 3), [b"abc", None, None])

    def test_revisions_and_refs_are_checked(self) -> None:
        for value in ("HEAD", "-n1", "a" * 39, "a" * 40 + "\n", "a" * 64, None):  # 64 digits: a ref name to git
            with self.subTest(value=value):
                with self.assertRaises(gitreads.GitRefused):
                    gitreads.sha(value)
        for value in ("main", "refs/heads/-x", "refs/heads/a..b", "refs/tags/v1", "refs/heads/x'y",
                      "refs/remotes/upstream/x"):
            with self.subTest(value=value):
                self.assertFalse(gitreads.is_ref(value))
        self.assertTrue(gitreads.is_ref("refs/heads/claude/fb-210-x"))
        self.assertTrue(gitreads.is_ref("refs/remotes/upstream/x", "upstream"))

    def test_the_environment_of_git_is_an_allowlist(self) -> None:
        env = gitreads.environment({"PATH": "p", "ANTHROPIC_API_KEY": "k", "GIT_DIR": "x", "OPENAI_API_KEY": "k",
                                    "SystemRoot": "s"})
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(env["PATH"], "p")
        for setting in ("core.attributesFile=", "core.excludesFile=", "core.fsmonitor=false", "filter.lfs.process=",
                        "core.warnAmbiguousRefs=false", "status.showStash=false", "index.sparse=false",
                        "index.threads=1", "core.longpaths=false", "log.showSignature=false"):
            with self.subTest(setting=setting):
                self.assertIn(setting, gitreads.SETTINGS)
        self.assertEqual(gitreads.GRAPH_OFF, ("-c", "core.commitGraph=false"))
        self.assertEqual(gitreads.SPARSE_OFF, ("-c", "core.sparseCheckout=false"))

    def test_a_path_given_to_git_is_plain(self) -> None:
        for value in ("data/../x.json", "a\nb", "/etc/passwd", "C" + ":/x", "a:b", "", "./x", "x/./y"):
            with self.subTest(value=value):
                with self.assertRaises(gitreads.GitRefused):
                    gitreads._path(value)
        self.assertEqual(gitreads._path(".flightboard/tasks.toml"), ".flightboard/tasks.toml")


if __name__ == "__main__":
    unittest.main()
