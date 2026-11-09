# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Agent names never select a different task policy or forecast capacity."""
from __future__ import annotations

import copy
import json
import unittest

from tests.fixtures import BASE, ledger, load, roadmap

rules = load("ledgers.roadmap_rules")
ledgers = load("ledgers")
overlay = load("overlay")
view = load("view")
AGENTS = ("claude", "codex", "qwen", "mimo", "minimax", "kimi", "local_agent-2")


class MultiagentLedgerTest(unittest.TestCase):
    def test_renaming_agents_preserves_validation_forecast_and_next(self) -> None:
        expected_forecast = None
        expected_next = None
        for owner in AGENTS:
            with self.subTest(owner=owner):
                raw = ledger(BASE)
                for task in raw["tasks"]:
                    if task["owner"] == "claude":
                        task["owner"] = owner
                self.assertEqual(rules.validate_ledger(raw), [])
                parsed = roadmap().parse(json.dumps(raw).encode())
                self.assertTrue(parsed["valid"], parsed["error"])
                live, _ = overlay.overlay(parsed["tasks"], [])
                next_ids = [task["id"] for task in view._next(live, [], roadmap(), raw, {})]
                forecast = rules.forecast(raw)
                if expected_forecast is None:
                    expected_forecast, expected_next = forecast, next_ids
                self.assertEqual(forecast, expected_forecast)
                self.assertEqual(next_ids, expected_next)
                self.assertTrue(roadmap().agent_task(owner))

    def test_task_file_accepts_every_safe_agent_and_reserves_human_roles(self) -> None:
        adapter = ledgers.make("tasks", "tasks.json")
        for owner in (*AGENTS, "", "owner", "reviewer"):
            with self.subTest(owner=owner):
                item = {"id": "A-1", "status": "planned"}
                if owner:
                    item["owner"] = owner
                parsed = adapter.parse(json.dumps({"tasks": [item]}).encode())
                self.assertTrue(parsed["valid"])
                self.assertEqual(adapter.agent_task(owner), owner not in ("owner", "reviewer"))
        for owner in ("Agent", "two words", "a" * 32, "agent/other", "qwen\u202e"):
            with self.subTest(owner=owner):
                raw = ledger(BASE)
                raw["tasks"][0]["owner"] = owner
                self.assertTrue(rules.validate_ledger(raw))
                self.assertFalse(roadmap().agent_task(owner))

    def test_all_agents_share_capacity_while_human_reviewer_remains_distinct(self) -> None:
        raw = ledger(BASE)
        raw["tasks"] = [copy.deepcopy(raw["tasks"][0]) for _ in range(4)]
        for task, owner in zip(raw["tasks"], ("codex", "qwen", "reviewer", "owner")):
            task["owner"], task["size"] = owner, "L"
        raw["milestones"] = raw["milestones"][:1]
        raw["capacity"].update(agent_sessions_per_week=4, claude_sessions_per_week=4,
                               review_slots_per_week=6, owner_hours_per_week=6)
        [row] = rules.forecast(raw)
        self.assertEqual(row["load"], {"agent": 12, "reviewer": 6, "owner": 6})
        self.assertEqual(row["weeks"], 3)

    def test_neutral_and_legacy_capacity_keys_are_compatible(self) -> None:
        legacy = ledger(BASE)
        neutral = copy.deepcopy(legacy)
        neutral["capacity"]["agent_sessions_per_week"] = neutral["capacity"].pop("claude_sessions_per_week")
        both = copy.deepcopy(legacy)
        both["capacity"]["agent_sessions_per_week"] = both["capacity"]["claude_sessions_per_week"]
        for raw in (legacy, neutral, both):
            self.assertEqual(rules.validate_ledger(raw), [])
            self.assertEqual(rules.forecast(raw), rules.forecast(legacy))
        both["capacity"]["agent_sessions_per_week"] += 1
        self.assertTrue(any("must agree" in error for error in rules.validate_ledger(both)))
        with self.assertRaises(ValueError):
            rules.forecast(both)

    def test_both_capacity_aliases_must_be_positive_integers(self) -> None:
        for invalid in (True, False, 0, -1, "10", 1.5):
            for name in rules.AGENT_CAPACITY_FIELDS:
                with self.subTest(name=name, invalid=invalid):
                    raw = ledger(BASE)
                    raw["capacity"][name] = invalid
                    self.assertTrue(rules.validate_ledger(raw))
                    with self.assertRaises(ValueError):
                        rules.forecast(raw)
        raw = ledger(BASE)
        del raw["capacity"]["claude_sessions_per_week"]
        self.assertTrue(any("agent_sessions_per_week" in error for error in rules.validate_ledger(raw)))

    def test_external_dependencies_accept_safe_agent_owners(self) -> None:
        for owner in AGENTS:
            raw = ledger(BASE)
            raw["external_dependencies"] = [{"id": "Vendor:api", "title_fr": "API", "owner": owner,
                "needed_by": ["FB-001"], "status": "done", "observed_at": raw["updated_at"],
                "observed_ref": "commit:abcdef1", "observed_fr": "Available"}]
            raw["tasks"][0]["dependencies"] = ["Vendor:api"]
            self.assertEqual(rules.validate_ledger(raw), [], owner)

    def test_roadmap_identifiers_and_dates_use_ascii_digits(self) -> None:
        for pattern, good, bad in (
            (rules.MILESTONE_ID, "M1", "M\uff11"),
            (rules.TASK_ID, "FB-M1-02", "FB-M\uff11-02"),
            (rules.TASK_ID, "FB-123", "FB-\u0661\u0662\u0663"),
            (rules.DECISION_ID, "ADR-0001", "ADR-\uff10\uff10\uff10\uff11"),
            (rules.DATE, "2026-11-09", "2026-11-\uff10\uff19"),
            (rules.RECORD, "docs/decisions/0001-test.md", "docs/decisions/\uff10\uff10\uff10\uff11-test.md"),
            (rules.OWNER_DECISION_REF, "ADR-0001", "ADR-\u0660\u0660\u0660\u0661"),
        ):
            with self.subTest(good=good):
                self.assertIsNotNone(pattern.fullmatch(good))
                self.assertIsNone(pattern.fullmatch(bad))


if __name__ == "__main__":
    unittest.main()
