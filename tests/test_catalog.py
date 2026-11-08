# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the message catalog: both languages say the same things, every word the page or the code asks for
exists, and every code the code decides with has its words.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import re
import string
import unittest

from tests.fixtures import PACKAGE, load

M = load("messages")
page = load("page")
CODES = {
    "reason": ("outside", "odd_admin", "admin_unchecked", "gone", "link", "unknown_commit", "read_failed",
               "several_bases", "stale", "invalid_ledger", "base_unreadable", "no_base"),
    "issue": ("not_read", "gone", "planted", "too_many_tracked", "odd_tracked_path", "tracked_link_folder",
              "tracked_unreadable", "submodule_link", "submodule_git", "tracked_replaced", "unreadable",
              "long_tracked_path", "sparse_index", "split_index", "index_too_big", "folder_unlisted"),
    "error": ("git_failed", "read_failed", "no_repository", "git_dir_link", "git_trap", "git_too_old", "no_main",
              "unavailable"),
    "trap": ("link", "special", "many", "commondir", "alternates", "alternates_unreadable", "config_unreadable",
             "include", "core_worktree", "main_worktree_config", "promisor", "ref_storage", "object_format"),
}
LABELLED = {
    "status": ("planned", "ready", "in_progress", "awaiting_review", "done", "blocked", "dropped"),
    "activity": ("active", "recent", "quiet", "unknown"),
    "stage": ("uncommitted", "committed", "pushed", "behind_origin", "merged", "up_to_date", "conflict", "operation"),
    "advice": ("ready_to_merge", "open", "ended", "keep_for_review", "keep_files", "merged", "gone"),
    "kind": ("checkout", "worktree", "branch", "remote"),
    "ledger": ("ok", "absent", "none", "writing", "too_big", "unreadable", "merging", "stale"),
    "operation": ("rebase", "merge", "cherry-pick", "revert", "bisect"),
    "source": ("ok", "partial", "unreadable", "absent"),
    "section": ("milestones", "capacity", "launch_gate", "external_dependencies", "statuses"),
}


def fields(template: object) -> set[str]:
    forms = template if isinstance(template, (tuple, list)) else (template,)
    return {name for form in forms for _, name, _, _ in string.Formatter().parse(str(form)) if name}


class CatalogTest(unittest.TestCase):
    def test_both_languages_say_the_same_things(self) -> None:
        for table in (M.TEXT, M.PAGE):
            with self.subTest(table=next(iter(table["en"]))):
                self.assertEqual(set(table["en"]), set(table["fr"]))
                for key, english in table["en"].items():
                    french = table["fr"][key]
                    self.assertEqual(type(english), type(french), key)
                    self.assertEqual(fields(english), fields(french), key)
        for group, labels in M.LABELS["en"].items():
            self.assertEqual(set(labels), set(M.LABELS["fr"][group]), group)

    def test_every_code_has_its_words(self) -> None:
        for lang in M.LANGS:
            for group, codes in CODES.items():
                for code in codes:
                    with self.subTest(lang=lang, group=group, code=code):
                        self.assertIn(f"{group}.{code}", M.TEXT[lang])
            for group, codes in LABELLED.items():
                for code in codes:
                    with self.subTest(lang=lang, group=group, code=code):
                        self.assertIn(code, M.LABELS[lang][group])
        self.assertEqual(M.error("en", "git_trap", "link:info"),
                         "git is not run on this repository: a link in .git (info) (see SECURITY.md)")
        self.assertEqual(M.reason("fr", "stale", "14"), "silencieuse depuis plus de 14 jours : listée seulement")

    def test_every_word_the_page_asks_for_exists(self) -> None:
        template = page.template()
        asked = set(re.findall(r"\btn?\('(page\.[\w.]+)'", template))
        asked |= set(re.findall(r'data-t="(page\.[\w.]+)"', template))
        asked |= set(re.findall(r"'(page\.[\w.]+)'", template))
        self.assertTrue(asked)
        self.assertFalse(sorted(asked - set(M.PAGE["en"])))
        groups = set(re.findall(r"\blabel\('(\w+)'", template))
        self.assertFalse(sorted(groups - set(M.LABELS["en"])))
        unused = set(M.PAGE["en"]) - asked
        self.assertFalse(sorted(unused), "words the page never shows")

    def test_every_word_the_code_asks_for_exists(self) -> None:
        asked: set[str] = set()
        for path in PACKAGE.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            asked |= set(re.findall(r"\b(?:say|count)\((?:self\.lang|lang), \"([\w.]+)\"", source))
            asked |= set(re.findall(r"self\.say\(\"([\w.]+)\"", source))
            asked |= set(re.findall(r"self\.say\(\"([\w.]+)\" if", source))
            asked |= set(re.findall(r"else \"([\w.]+)\"\)", source))
        self.assertGreater(len(asked), 40)
        self.assertFalse(sorted(key for key in asked if "." in key and not key.endswith(".")
                                and key not in M.TEXT["en"]))

    def test_plurals_follow_each_language(self) -> None:
        self.assertEqual(M.count("en", "commits", 0), "0 commits")
        self.assertEqual(M.count("en", "commits", 1), "1 commit")
        self.assertEqual(M.count("fr", "summary.sessions", 0), "0 session ouverte")
        self.assertEqual(M.count("fr", "summary.sessions", 2), "2 sessions ouvertes")
        self.assertEqual(M.page("fr")["locale"], "fr-CA")
        self.assertEqual(M.page("de")["lang"], "en")  # an unknown language reads English, never fails

    def test_placeholders_are_filled_with_text_only(self) -> None:
        hostile = "{name} </script> {0}"
        self.assertEqual(M.say("en", "wait.alert", name=hostile, what="x"), hostile + ": x")


if __name__ == "__main__":
    unittest.main()
