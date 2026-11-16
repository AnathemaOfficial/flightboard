# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Dependency display limits must never turn an unmet prerequisite into readiness."""
from __future__ import annotations

import json
import unittest

from tests.fixtures import BASE, ledger, load, roadmap

base = load("ledgers.base")
ledgers = load("ledgers")
overlay = load("overlay")
tasks = load("ledgers.tasks")
view = load("view")


def roadmap_with_many_dependencies(blocked: bool) -> tuple[dict, list[str]]:
    dependencies = [f"FB-{index}" for index in range(100, 201)]
    raw = ledger({**BASE, **dict.fromkeys(dependencies, "done"), "FB-300": "planned"})
    target = next(item for item in raw["tasks"] if item["id"] == "FB-300")
    target.update(dependencies=dependencies, priority="P1")
    if blocked:
        next(item for item in raw["tasks"] if item["id"] == dependencies[-1])["status"] = "blocked"
    return raw, dependencies


def task_file_with_dependencies(count: int, blocked: bool = False) -> tuple[bytes, list[str]]:
    dependencies = [f"T-{index}" for index in range(count)]
    items = [{"id": tid, "status": "done"} for tid in dependencies]
    if blocked:
        items[-1]["status"] = "blocked"
    items.append({"id": "TARGET", "status": "planned", "depends_on": dependencies, "priority": "P1"})
    return json.dumps({"version": 1, "tasks": items}).encode("utf-8"), dependencies


class DependencyDecisionTest(unittest.TestCase):
    def test_a_valid_roadmap_keeps_its_101st_blocking_dependency(self) -> None:
        board = roadmap()
        raw, dependencies = roadmap_with_many_dependencies(blocked=True)
        parsed = board.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(parsed["valid"], parsed["error"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertNotIn("FB-300", [item["id"] for item in view._next(live, [], board, raw, {"M0": 0})])
        details = view._details({"FB-300"}, live, [])
        self.assertEqual(details["FB-300"]["dependencies"], dependencies)
        self.assertEqual(details["FB-300"]["waiting_on"], [dependencies[-1]])

    def test_a_valid_roadmap_with_101_satisfied_dependencies_can_still_start(self) -> None:
        board = roadmap()
        raw, dependencies = roadmap_with_many_dependencies(blocked=False)
        parsed = board.parse(json.dumps(raw).encode("utf-8"))
        self.assertTrue(parsed["valid"], parsed["error"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertIn("FB-300", [item["id"] for item in view._next(live, [], board, raw, {"M0": 0})])
        self.assertEqual(view._details({"FB-300"}, live, [])["FB-300"]["dependencies"], dependencies)

    def test_an_oversized_task_list_stays_invalid_without_hiding_its_last_blocker(self) -> None:
        board = ledgers.make("tasks", "tasks.json")
        data, dependencies = task_file_with_dependencies(base.MAX_DEPENDENCIES + 1, blocked=True)
        parsed = board.parse(data)
        self.assertFalse(parsed["valid"])
        self.assertIn("at most", parsed["error"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertNotIn("TARGET", [item["id"] for item in view._next(live, [], board, parsed["raw"], {})])
        details = view._details({"TARGET"}, live, [])
        self.assertEqual(details["TARGET"]["dependencies"], dependencies)
        self.assertEqual(details["TARGET"]["waiting_on"], [dependencies[-1]])

    def test_the_simple_task_files_dependency_limit_is_still_accepted(self) -> None:
        board = ledgers.make("tasks", "tasks.json")
        data, dependencies = task_file_with_dependencies(base.MAX_DEPENDENCIES)
        parsed = board.parse(data)
        self.assertTrue(parsed["valid"], parsed["error"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertIn("TARGET", [item["id"] for item in view._next(live, [], board, parsed["raw"], {})])
        self.assertEqual(parsed["tasks"]["TARGET"]["dependencies"], dependencies)

    def test_many_repeated_dependencies_are_invalid_and_do_not_grow_the_details(self) -> None:
        raw = {"version": 1, "tasks": [{"id": "T-1", "status": "done"},
                                      {"id": "TARGET", "status": "planned", "depends_on": ["T-1"] * 200_000}]}
        data = json.dumps(raw).encode("utf-8")
        self.assertLess(len(data), tasks.MAX_TASK_FILE_BYTES)
        parsed = ledgers.make("tasks", "tasks.json").parse(data)
        self.assertFalse(parsed["valid"])
        self.assertIn("declared twice", parsed["error"])
        live, _ = overlay.overlay(parsed["tasks"], [])
        self.assertEqual(view._details({"TARGET"}, live, [])["TARGET"]["dependencies"], ["T-1"])


if __name__ == "__main__":
    unittest.main()
