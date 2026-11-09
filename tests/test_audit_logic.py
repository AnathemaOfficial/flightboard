# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Regression scenarios for complete dependency checks and contested live declarations."""
from __future__ import annotations

import copy
import json
import unittest

from tests.fixtures import BASE, NOW, ledger, load, roadmap, task

ledgers = load("ledgers")
overlay = load("overlay")
view = load("view")
ledger_base = load("ledgers.base")


def parsed_tasks(items: list[dict]) -> dict:
    return ledgers.make("tasks", "tasks.json").parse(json.dumps({"tasks": items}).encode())


def session(name: str, base: dict, head: dict) -> dict:
    changes = [{**change, "at": NOW.isoformat(), "sha": ""}
               for change in overlay.task_changes(base, head)]
    return {"name": name, "overlay": True, "changes": changes, "_changes": changes, "_head_tasks": head,
            "advice": "open", "stale": False, "inferred": [], "last_activity": NOW.isoformat(), "subject": ""}


class AuditLogicTest(unittest.TestCase):
    def test_a_blocked_31st_dependency_prevents_starting_a_task_file_task(self) -> None:
        items = [{"id": f"D-{index}", "status": "done" if index < 31 else "blocked"}
                 for index in range(1, 32)]
        items.append({"id": "GO-1", "status": "planned", "depends_on": [f"D-{i}" for i in range(1, 32)]})
        parsed = parsed_tasks(items)
        self.assertTrue(parsed["valid"], parsed["error"])
        self.assertEqual(len(parsed["tasks"]["GO-1"]["dependencies"]), 31)
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertNotIn("GO-1", [task["id"] for task in view._next(
            live, [], ledgers.make("tasks", "tasks.json"), parsed["raw"], {})])

    def test_roadmap_keeps_all_dependencies_and_complete_external_ids(self) -> None:
        raw = ledger(BASE)
        extra = [task(f"FB-{index}", "done") for index in range(100, 130)]
        raw["tasks"].extend(extra)
        long_id = "Vendor:" + "a" * 41
        raw["external_dependencies"] = [{"id": long_id, "title_fr": "API", "owner": "qwen",
            "needed_by": ["FB-003"], "status": "in_progress", "observed_at": raw["updated_at"],
            "observed_ref": "commit:abcdef1", "observed_fr": "Waiting"}]
        raw["tasks"][2]["status"] = "planned"
        raw["tasks"][2]["dependencies"] = [t["id"] for t in extra] + [long_id]
        parsed = roadmap().parse(json.dumps(raw).encode())
        self.assertTrue(parsed["valid"], parsed["error"])
        self.assertEqual(parsed["tasks"]["FB-003"]["dependencies"], raw["tasks"][2]["dependencies"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertNotIn("FB-003", [t["id"] for t in view._next(live, [], roadmap(), raw, {})])
        raw["external_dependencies"][0]["status"] = "done"
        self.assertIn("FB-003", [t["id"] for t in view._next(live, [], roadmap(), raw, {})])

    def test_new_id_collisions_compare_complete_metadata(self) -> None:
        base = parsed_tasks([{"id": "D-1", "status": "blocked"}])["tasks"]
        first = {"id": "NEW-1", "title": "Deploy", "status": "planned", "owner": "codex",
                 "acceptance": ["first"] * 5 + ["sixth"], "priority": "P1"}
        variants = ({"owner": "qwen"}, {"depends_on": ["D-1"]},
                    {"acceptance": ["first"] * 5 + ["different sixth"]}, {"priority": "P2"},
                    {"title": "Deploy" + "x" * 300})
        for changed in variants:
            with self.subTest(changed=changed):
                one = parsed_tasks([{"id": "D-1", "status": "blocked"}, first])
                two = parsed_tasks([{"id": "D-1", "status": "blocked"}, {**first, **changed}])
                self.assertTrue(one["valid"] and two["valid"])
                live, _ = overlay.overlay(base, [session("a", base, one["tasks"]),
                                                session("b", base, two["tasks"])])
                self.assertTrue(live["NEW-1"]["collision"])
                self.assertFalse(any(source["applied"] for source in live["NEW-1"]["sources"]))

    def test_roadmap_collision_checks_metadata_beyond_display_limits(self) -> None:
        base_raw = ledger(BASE)
        base = roadmap().parse(json.dumps(base_raw).encode())["tasks"]
        one = copy.deepcopy(base_raw)
        one["tasks"].append(task("FB-100", "planned"))
        one["tasks"][-1]["acceptance_fr"] = ["same"] * 5 + ["sixth"]
        two = copy.deepcopy(one)
        two["tasks"][-1]["acceptance_fr"][-1] = "different"
        heads = [roadmap().parse(json.dumps(raw).encode()) for raw in (one, two)]
        self.assertTrue(all(head["valid"] for head in heads))
        live, _ = overlay.overlay(base, [session(name, base, head["tasks"]) for name, head in zip(("a", "b"), heads)])
        self.assertTrue(live["FB-100"]["collision"])

    def test_conflict_rolls_back_every_applied_source_including_later_agreement(self) -> None:
        base = parsed_tasks([{"id": "T-1", "status": "planned"}])["tasks"]
        sessions = [session(name, base, parsed_tasks([{"id": "T-1", "status": status}])["tasks"])
                    for name, status in (("a", "done"), ("b", "in_progress"), ("c", "done"))]
        live, _ = overlay.overlay(base, sessions)
        self.assertEqual(live["T-1"]["status"], "planned")
        self.assertTrue(live["T-1"]["conflict"])
        self.assertFalse(any(source["applied"] for source in live["T-1"]["sources"]))
        events = view._session_events(sessions)
        self.assertEqual(view._applied_moves(sessions, live, events), [])
        self.assertEqual(sum(day["done_live"] for day in overlay.daily(
            view._applied_moves(sessions, live, events), NOW)), 0)

    def test_a_contested_new_task_is_not_counted_or_forecast(self) -> None:
        adapter = roadmap()
        raw = ledger(BASE)
        main = adapter.parse(json.dumps(raw).encode())["tasks"]
        sessions = []
        for name, status in (("a", "done"), ("b", "in_progress"), ("c", "done")):
            declared = copy.deepcopy(raw)
            declared["tasks"].append(task("FB-100", status))
            parsed = adapter.parse(json.dumps(declared).encode())
            self.assertTrue(parsed["valid"], parsed["error"])
            sessions.append(session(name, main, parsed["tasks"]))
        live, _ = overlay.overlay(main, sessions)
        self.assertTrue(live["FB-100"]["conflict"])
        self.assertFalse(ledger_base.countable(live["FB-100"]))
        self.assertEqual(overlay.counts(live), overlay.counts(main))
        self.assertEqual(adapter.milestones(raw, live, main), adapter.milestones(raw, overlay.overlay(main, [])[0], main))
        self.assertEqual(view._kpis(main, live, [])["done_live"], 0)

    def test_a_new_metadata_collision_has_no_milestone_counts(self) -> None:
        heads = [parsed_tasks([{"id": "T-1", "status": "done", "owner": owner, "milestone": "M1"}])["tasks"]
                 for owner in ("codex", "qwen")]
        live, _ = overlay.overlay({}, [session(name, {}, head) for name, head in zip(("a", "b"), heads)])
        self.assertTrue(live["T-1"]["collision"])
        self.assertEqual(overlay.counts(live), {})
        row = ledger_base.milestone_row("M1", "First", "", list(live.values()), [])
        self.assertEqual((row["total"], row["active"], row["counts"], row["unmerged"]), (0, 0, {}, {}))

    def test_a_collision_restores_an_existing_main_task_after_an_applied_move(self) -> None:
        main = parsed_tasks([{"id": "T-1", "status": "planned", "owner": "codex"}])["tasks"]
        done = parsed_tasks([{"id": "T-1", "status": "done", "owner": "codex"}])["tasks"]
        different = parsed_tasks([{"id": "T-1", "status": "done", "owner": "qwen"}])["tasks"]
        live, _ = overlay.overlay(main, [session("a", main, done), session("b", {}, different)])
        self.assertTrue(live["T-1"]["collision"])
        self.assertEqual(live["T-1"]["status"], "planned")
        self.assertTrue(ledger_base.countable(live["T-1"]))
        self.assertEqual(overlay.counts(live), {"planned": 1})

    def test_sources_keep_stable_ids_when_session_display_names_match(self) -> None:
        main = parsed_tasks([{"id": "T-1", "status": "planned"}])["tasks"]
        done = parsed_tasks([{"id": "T-1", "status": "done"}])["tasks"]
        started = parsed_tasks([{"id": "T-1", "status": "in_progress"}])["tasks"]
        first = {**session("project", main, done), "id": "tree-a"}
        second = {**session("project", main, started), "id": "tree-b"}
        live, _ = overlay.overlay(main, [second, first])
        self.assertEqual(live, overlay.overlay(main, [first, second])[0])
        sources = live["T-1"]["sources"]
        self.assertEqual([source["session_id"] for source in sources], ["tree-a", "tree-b"])
        self.assertEqual([source["session"] for source in sources], ["project", "project"])
        self.assertEqual((sources[1]["other_id"], sources[1]["other"]), ("tree-a", "project"))


if __name__ == "__main__":
    unittest.main()
