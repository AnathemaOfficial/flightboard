# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Malformed reference values produce field diagnostics, rather than aborting validation."""
from __future__ import annotations

import json
import unittest

from tests.fixtures import ledger, load, roadmap

rules = load("ledgers.roadmap_rules")


class ReferenceTypeTest(unittest.TestCase):
    def test_an_unhashable_track_keeps_the_field_diagnostic(self) -> None:
        for value in ([], {}):
            with self.subTest(value=value):
                raw = ledger({"FB-001": "planned"})
                raw["milestones"][0]["track"] = value
                errors = rules.validate_ledger(raw)
                self.assertTrue(any("unknown track" in error for error in errors))
                milestones = {"M0": {"data": raw["milestones"][0]}}
                self.assertIsNone(rules._track(milestones, "M0"))
                parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
                self.assertFalse(parsed["valid"])
                self.assertIn("track", parsed["error"])

    def test_an_unhashable_evidence_kind_keeps_the_field_diagnostic(self) -> None:
        for value in ([], {}):
            with self.subTest(value=value):
                raw = ledger({"FB-001": "done"})
                raw["tasks"][0]["evidence"][0]["kind"] = value
                errors = rules.validate_ledger(raw)
                self.assertTrue(any("unknown evidence kind" in error for error in errors))
                parsed = roadmap().parse(json.dumps(raw).encode("utf-8"))
                self.assertFalse(parsed["valid"])
                self.assertIn("evidence", parsed["error"])


if __name__ == "__main__":
    unittest.main()
