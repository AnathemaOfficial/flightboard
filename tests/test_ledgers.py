# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the ledger formats: the task file's small validator, and the pinned roadmap rules.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import re
import textwrap
import time
import unittest

from tests.fixtures import BASE, ROOT, encoded, ledger, load, roadmap

ledgers = load("ledgers")
tasks_module = load("ledgers.tasks")
rules = load("ledgers.roadmap_rules")


def task_file(*items: dict, **top) -> bytes:
    return json.dumps({"version": 1, **top, "tasks": list(items)}).encode("utf-8")


def parse(data: bytes, path: str = "tasks.json") -> dict | None:
    return ledgers.make("tasks", path).parse(data)


class TaskFileTest(unittest.TestCase):
    def test_a_plain_task_file(self) -> None:
        parsed = parse(task_file({"id": "T-1", "title": "One", "status": "done"},
                                 {"id": "T-2", "status": "planned", "depends_on": ["T-1"], "owner": "claude"}))
        self.assertTrue(parsed["valid"], parsed["error"])
        self.assertEqual(parsed["tasks"]["T-2"]["dependencies"], ["T-1"])
        self.assertEqual(parsed["tasks"]["T-1"]["title"], "One")

    def test_the_documented_samples_are_valid(self) -> None:
        """The task file the READMEs and the module show passes the validator as it is written."""
        samples = {name: re.search(r"```toml\n(.*?)```", (ROOT / name).read_text(encoding="utf-8"), re.S).group(1)
                   for name in ("README.md", "docs/fr/README.md")}
        indented = tasks_module.__doc__.split("\n\n", 1)[1].split("Its validator")[0]
        samples["ledgers/tasks.py"] = textwrap.dedent(indented)
        for name, sample in samples.items():
            with self.subTest(name=name):
                parsed = parse(sample.encode("utf-8"), "tasks.toml")
                self.assertTrue(parsed["valid"], parsed["error"])
                self.assertEqual(parsed["tasks"]["AUTH-1"]["dependencies"], ["AUTH-0"])

    def test_toml_and_status_words(self) -> None:
        data = b'[statuses]\ntodo = "planned"\n\n[[tasks]]\nid = "T-1"\nstatus = "todo"\n'
        parsed = parse(data, "tasks.toml")
        self.assertTrue(parsed["valid"], parsed["error"])
        self.assertEqual(parsed["tasks"]["T-1"]["status"], "planned")

    def test_what_the_small_validator_refuses(self) -> None:
        cases = {
            "duplicate id": task_file({"id": "T-1", "status": "done"}, {"id": "T-1", "status": "planned"}),
            "maps to none": task_file({"id": "T-1", "status": "almost"}, {"id": "T-2", "status": "done"}),
            "unknown dependency": task_file({"id": "T-1", "status": "done", "depends_on": ["T-9"]}),
            "itself": task_file({"id": "T-1", "status": "done", "depends_on": ["T-1"]}),
            "dependency cycle": task_file({"id": "T-1", "status": "done", "depends_on": ["T-2"]},
                                          {"id": "T-2", "status": "done", "depends_on": ["T-1"]}),
            "invalid id": task_file({"id": "has space", "status": "done"}, {"id": "T-2", "status": "done"}),
            "invalid owner": task_file({"id": "T-1", "status": "done", "owner": "Somebody Else"}),
            "unknown milestone": task_file({"id": "T-1", "status": "done", "milestone": "M9"},
                                           milestones=[{"id": "M1"}]),
            "not one of": task_file({"id": "T-1", "status": "done"}, statuses={"x": "finished"}),
            "cannot mean": task_file({"id": "T-1", "status": "done"}, statuses={"done": "planned"}),
            "version must be 1": task_file({"id": "T-1", "status": "done"}, version=2),
        }
        for expected, data in cases.items():
            with self.subTest(expected=expected):
                parsed = parse(data)
                self.assertIsNotNone(parsed)
                self.assertFalse(parsed["valid"])
                self.assertIn(expected, parsed["error"])

    def test_ids_stay_strict(self) -> None:
        parsed = parse(task_file({"id": "T-1", "status": "done"}, {"id": "12", "status": "done"},
                                 {"id": "<b>x</b>", "status": "done"}, {"id": "a" * 41, "status": "done"}))
        self.assertEqual(list(parsed["tasks"]), ["T-1"])  # a number alone, markup or a long word is no id
        self.assertFalse(parsed["valid"])

    def test_what_is_not_a_task_file_gives_none(self) -> None:
        for data, path in ((b"", "tasks.json"), (b"{", "tasks.json"), (b'{"tasks": 1}', "tasks.json"),
                           (b"tasks = [", "tasks.toml"), (b"\xff", "tasks.toml"),
                           (b'{"tasks": [{"id": "T-1", "status": "done"}], "x": NaN}', "tasks.json"),
                           (b"[" * 5000, "tasks.toml"), (b"x = [" + b"[" * 5000, "tasks.toml")):
            with self.subTest(data=data[:20], path=path):
                self.assertIsNone(parse(data, path))

    def test_a_task_file_without_usable_task_says_why(self) -> None:
        empty = parse(b'{"tasks": []}')
        self.assertEqual((empty["valid"], empty["tasks"]), (True, {}))  # a new project's task file: empty, valid
        unmapped = parse(b'tasks = [{id = "A-1", status = "todo"}]', "tasks.toml")
        self.assertEqual((unmapped["valid"], unmapped["tasks"]), (False, {}))
        self.assertIn("A-1: status 'todo' maps to none of flightboard's statuses", unmapped["error"])

    def test_a_long_chain_is_checked_without_recursion(self) -> None:
        count = tasks_module.MAX_TASKS
        items = [{"id": f"T-{index}", "status": "planned", "depends_on": [f"T-{index - 1}"] if index else []}
                 for index in range(count)]
        parsed = parse(task_file(*items))
        self.assertTrue(parsed["valid"], parsed["error"])
        items[0]["depends_on"] = [f"T-{count - 1}"]
        self.assertIn("dependency cycle", parse(task_file(*items))["error"])
        self.assertIsNone(parse(task_file(*items) + b" " * tasks_module.MAX_TASK_FILE_BYTES))

    def test_a_task_file_past_the_cap_is_read_in_part_and_never_valid(self) -> None:
        items = [{"id": f"T-{index}", "status": "done"} for index in range(tasks_module.MAX_TASKS * 5)]
        parsed = parse(task_file(*items))
        self.assertFalse(parsed["valid"])
        self.assertIn("too big", parsed["error"])
        self.assertEqual(len(parsed["tasks"]), tasks_module.MAX_TASKS)

    def test_text_is_cleaned(self) -> None:
        parsed = parse(task_file({"id": "T-1", "status": "done", "title": "a\u202eb\u0000c" + "x" * 500}))
        self.assertNotIn("\u202e", parsed["tasks"]["T-1"]["title"])
        self.assertLessEqual(len(parsed["tasks"]["T-1"]["title"]), 200)


class RoadmapRulesTest(unittest.TestCase):
    """The pinned rules take any project's prefixes, and every one of them holds."""

    def test_any_uppercase_prefix(self) -> None:
        for tid in ("APP-1", "XY-M3-07", "Q9-123456"):
            with self.subTest(tid=tid):
                self.assertIsNotNone(rules.TASK_ID.fullmatch(tid))
        for tid in ("app-1", "APP_1", "APP-", "-1", "APP-1234567", "TOOLONGPREFIX-1"):
            with self.subTest(tid=tid):
                self.assertIsNone(rules.TASK_ID.fullmatch(tid))
        self.assertIsNotNone(rules.DECISION_ID.fullmatch("ADR-0001"))
        self.assertIsNotNone(rules.EXTERNAL_ID.fullmatch("Vendor:api-v2"))

    def test_rules_still_bite(self) -> None:
        raw = ledger({**BASE, "FB-001": "done"})
        raw["tasks"][0]["evidence"] = []
        self.assertIn("FB-001: done without evidence", rules.validate_ledger(raw))
        cyclic = ledger(BASE)
        cyclic["tasks"][1]["dependencies"] = ["FB-003"]
        cyclic["tasks"][2]["dependencies"] = ["FB-002"]
        self.assertTrue([error for error in rules.validate_ledger(cyclic) if error.startswith("dependency cycle")])
        secret = ledger(BASE)
        secret["tasks"][0]["notes_fr"] = "token ghp_" + "a" * 30
        self.assertIn("ledger: a secret pattern was found; no secret in the repository", rules.validate_ledger(secret))

    def test_the_secret_check_takes_linear_time_and_finds_the_same_tokens(self) -> None:
        """A long run of eyJ made the unanchored token pattern take quadratic time: every reading hung."""
        started = time.monotonic()
        self.assertIsNone(rules.SECRET.search("eyJ" * 1_600_000))
        self.assertLess(time.monotonic() - started, 3)
        token = "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12
        for text in (token, "x" + token, "eyJeyJ" + token, "note: " + token + " end", "a-" + token):
            with self.subTest(text=text[:12]):
                self.assertIsNotNone(rules.SECRET.search(text))
        for text in ("eyJ" + "a" * 12 + ".eyJ" + "b" * 9 + "." + "c" * 12, "eyJ" + "a" * 9 + ".eyJ" + "b" * 12 + "."):
            with self.subTest(text=text[:12]):
                self.assertIsNone(rules.SECRET.search(text))

    def test_a_milestone_id_the_rules_refuse_never_reaches_the_page(self) -> None:
        raw = ledger(BASE)
        raw["milestones"].append({**raw["milestones"][0], "id": "M2\u202e"})
        raw["milestones"].append({**raw["milestones"][0], "id": "\ud800"})
        rows = roadmap().milestones(raw, {}, {})
        self.assertEqual([row["id"] for row in rows], ["M0", "M1"])

    def test_a_roadmap_past_the_cap_is_read_in_part_and_never_valid(self) -> None:
        cap = load("ledgers.roadmap").MAX_READ_TASKS
        raw = ledger(BASE)
        model = {key: value for key, value in raw["tasks"][0].items() if key != "dependencies"}
        raw["tasks"] = [{**model, "id": f"FB-{index}", "status": "planned"} for index in range(1, cap + 500)]
        parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
        self.assertFalse(parsed["valid"])
        self.assertIn("too big to be validated here", parsed["error"])
        self.assertEqual(len(parsed["tasks"]), cap)

    def test_english_tracks_mean_the_same(self) -> None:
        raw = ledger(BASE)
        raw["milestones"][0]["track"] = "main"
        self.assertEqual(rules.validate_ledger(raw), [])
        self.assertTrue(roadmap().parse(encoded(BASE))["valid"])

    def test_paths_of_ledgers_stay_plain(self) -> None:
        for path in ("../x.json", "/x.json", "C" + ":/x.json", "a/./b.json", "a\\b.json", "x.json\n", "a//b.json",
                     ".git/config", "sub/.GIT/x.json"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    ledgers.make("tasks", path)
        self.assertEqual(ledgers.make("tasks", ".board/tasks.toml").path, ".board/tasks.toml")


if __name__ == "__main__":
    unittest.main()
