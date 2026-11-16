# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Chunked text and ref preflight preserve content and the shared reading bounds."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.fixtures import load

files = load("files")
text = load("text")


class ChunkedTextTest(unittest.TestCase):
    def test_a_word_crossing_the_chunk_boundary_has_no_new_space(self) -> None:
        for padding in (" ", "\u2800", "\u202e"):
            for offset in (4090, 4094, 8190):
                with self.subTest(padding=repr(padding), offset=offset):
                    self.assertEqual(text.clean(padding * offset + "ABCDEFGHI", 200), "ABCDEFGHI")

    def test_spaces_and_controls_at_a_boundary_still_separate_words(self) -> None:
        for separator in (" ", "\u2800", "\u202e", "\0", "\t"):
            for offset in (4095, 4096):
                with self.subTest(separator=repr(separator), offset=offset):
                    value = " " * (offset - 1) + "A" + separator + "B"
                    self.assertEqual(text.clean(value, 200), "A B")

    def test_an_output_limit_can_end_in_the_separator_between_words(self) -> None:
        self.assertEqual(text.clean(" " * 4094 + "AB CD", 3), "AB ")
        self.assertEqual(text.clean(" " * 4094 + "AB CD", 4), "AB C")
        self.assertEqual(text.clean(" " * 4094 + "AB CD", 0), "")


class RefPreflightBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.folder = self.root / ".git" / "refs" / "heads"
        self.folder.mkdir(parents=True)
        for index in range(10):
            (self.folder / f"r{index}").write_text("a" * 40 + "\n", encoding="ascii")

    def test_preinspection_does_not_charge_the_refs_again_before_the_walk(self) -> None:
        budget = files.Budget(entries=20)
        self.assertEqual(files.git_dir_problem(self.root, budget=budget), "")
        self.assertEqual(budget.left, 8)  # .git/refs, refs/heads and the ten loose refs

    def test_the_exact_walk_quota_is_accepted_and_the_next_entry_is_refused(self) -> None:
        accepted = files.Budget(entries=12)
        self.assertEqual(files.git_dir_problem(self.root, budget=accepted), "")
        self.assertEqual(accepted.left, 0)
        self.assertTrue(files.git_dir_problem(self.root, budget=files.Budget(entries=11)).startswith("many:"))

    def test_preinspection_refuses_a_folder_larger_than_the_remaining_quota(self) -> None:
        self.assertEqual(files._linked_entry(self.folder, self.root, budget=files.Budget(entries=2)), "many")

    def test_preinspection_stops_on_the_deadline_between_entries(self) -> None:
        budget = files.Budget(entries=20, deadline=10)
        with mock.patch.object(files.time, "monotonic", side_effect=(0, 0, 11)):
            with self.assertRaises(files.ReadingTooLong):
                files._linked_entry(self.folder, self.root, budget=budget)

    def test_an_expired_deadline_stops_before_listing_even_an_empty_folder(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        with mock.patch.object(files.time, "monotonic", return_value=11), \
                mock.patch.object(files.os, "scandir", side_effect=AssertionError("listing after deadline")):
            with self.assertRaises(files.ReadingTooLong):
                files._linked_entry(empty, self.root, budget=files.Budget(deadline=10))


if __name__ == "__main__":
    unittest.main()
