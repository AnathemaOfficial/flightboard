# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A larger explicit worktree limit must keep every session and every read guard."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_files import make_link
from tests.test_modes import Plain

files = load("files")
cli = load("cli")
collector = load("collector")
Settings = load("config").Settings


class WorktreeLimitSettingsTest(unittest.TestCase):
    def test_default_and_explicit_bounds_are_public(self) -> None:
        self.assertEqual(cli.settings_of(cli.parse([])).max_worktrees, 100)
        for count in (1, 100, 267, 1000):
            with self.subTest(count=count):
                settings = cli.settings_of(cli.parse(["--max-worktrees", str(count)]))
                self.assertEqual(settings.max_worktrees, count)
                self.assertEqual(settings.public()["max_worktrees"], count)

    def test_invalid_cli_limits_read_no_repository(self) -> None:
        for value in ("0", "1001", "-1", "267.0", "NaN", "\u0662\u0666\u0667", "267 ", "9" * 5000):
            with self.subTest(value=value), contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()) as errors, \
                    mock.patch.object(cli, "Collector") as reader, \
                    mock.patch.object(cli.FILES, "top_folder") as folder:
                self.assertEqual(cli.main(["--max-worktrees", value], now=NOW), 2)
                self.assertIn("--max-worktrees takes a number from 1 to 1000", errors.getvalue())
                reader.assert_not_called()
                folder.assert_not_called()
        for arguments in (["--max-worktrees"], ["--max-worktrees", "--resume"],
                          ["--max-worktrees", "100", "--max-worktrees", "267"]):
            with self.subTest(arguments=arguments):
                self.assertIsNone(cli.parse(arguments))

    def test_handbuilt_limits_reject_booleans_and_nonintegers(self) -> None:
        for value in (0, 1001, True, False, 267.0, "267", None):
            with self.subTest(value=value), mock.patch.object(collector.FILES, "top_folder") as folder, \
                    self.assertRaisesRegex(ValueError, "settings refused"):
                collector.Collector(Path(tempfile.gettempdir()), Settings(max_worktrees=value))
            folder.assert_not_called()

    def test_help_explains_the_explicit_limit(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["--help"]), 0)
        self.assertIn("--max-worktrees N", output.getvalue())
        self.assertIn("100", output.getvalue())
        self.assertIn("1000", output.getvalue())

    def test_file_discovery_rejects_invalid_explicit_limits_before_disk_reads(self) -> None:
        for value in (0, 1001, True, False, "267", 267.0):
            with self.subTest(value=value), mock.patch.object(files.os, "lstat") as stat, \
                    self.assertRaises(ValueError):
                files.discover(Path(tempfile.gettempdir()), max_worktrees=value)
            stat.assert_not_called()

    def test_startup_parser_accepts_and_preserves_the_limit(self) -> None:
        root = Path(tempfile.gettempdir()).resolve()
        options = load("windows_startup").live_options(
            ["--repo", str(root), "--port", "8791", "--max-worktrees", "267", "--read-seconds", "120"])
        self.assertEqual(options["--max-worktrees"], "267")
        self.assertEqual(options["--read-seconds"], "120")


@unittest.skipIf(GIT is None, "git absent")
class LargeRegisteredWorktreesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Plain()
        cls.addClassCleanup(cls.repo.close)
        cls.tip = cls.repo.git("rev-parse", "HEAD")
        cls.external = cls.repo.root.parent / "external-worktrees"
        cls.external.mkdir()
        cls.ids = {f"session-{number:03}" for number in range(267)}
        # Plain registered metadata is sufficient here: the external roots remain unauthorized,
        # so neither Git nor the file reader may enter any of these target directories.
        for name in sorted(cls.ids):
            admin = cls.repo.root / ".git" / "worktrees" / name
            target = cls.external / name
            admin.mkdir(parents=True)
            target.mkdir()
            (admin / "HEAD").write_text(cls.tip + "\n", encoding="ascii")
            (admin / "commondir").write_text("../..\n", encoding="ascii")
            (admin / "gitdir").write_text(str(target / ".git") + "\n", encoding="utf-8")
            (target / ".git").write_text("gitdir: " + str(admin) + "\n", encoding="utf-8")

    def test_default_refusal_is_actionable_in_both_languages(self) -> None:
        for lang in ("en", "fr"):
            with self.subTest(lang=lang):
                result = collector.Collector(self.repo.root, Settings(lang=lang)).snapshot(NOW)
                self.assertEqual(result["main"]["reason"], "too_many_worktrees")
                self.assertEqual(result["sessions"], [])
                self.assertEqual(result["settings"]["max_worktrees"], 100)
                self.assertIn("--max-worktrees", result["main"]["reason_text"])

    def test_explicit_limit_recovers_all_267_sessions_without_authorizing_their_files(self) -> None:
        original = files.MAX_WORKTREES
        with mock.patch.object(files, "_folder_state", wraps=files._folder_state) as checked:
            result = collector.Collector(self.repo.root, Settings(max_worktrees=267, read_seconds=30,
                                                                  max_branches=0)).snapshot(NOW)
        self.assertEqual(result["main"]["state"], "ok", result["main"])
        self.assertEqual(len(result["sessions"]), 268)
        worktrees = [session for session in result["sessions"] if session["kind"] != "checkout"]
        self.assertEqual({session["name"] for session in worktrees}, self.ids)
        self.assertTrue(all(session["reason"] == "outside" and not session["files_read"] for session in worktrees))
        self.assertTrue(all(session.get("advice") not in ("ready_to_merge", "ended") for session in worktrees))
        self.assertEqual(files.MAX_WORKTREES, original)
        self.assertFalse(any(Path(call.args[0]).is_relative_to(self.external) for call in checked.call_args_list))

    def test_exceeding_an_explicit_limit_still_refuses_the_whole_set(self) -> None:
        result = collector.Collector(self.repo.root, Settings(max_worktrees=266)).snapshot(NOW)
        self.assertEqual(result["main"]["reason"], "too_many_worktrees")
        self.assertEqual(result["sessions"], [])
        self.assertEqual(result["settings"]["max_worktrees"], 266)


@unittest.skipIf(GIT is None, "git absent")
class WorktreeCapacityBoundaryTest(unittest.TestCase):
    def test_metadata_discovery_keeps_300_to_1000_sessions_and_refuses_1001(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        tip = repo.git("rev-parse", "HEAD")
        external = repo.root.parent / "capacity-worktrees"
        external.mkdir()
        names: set[str] = set()

        def register(number: int) -> None:
            name = f"session-{number:04}"
            admin = repo.root / ".git" / "worktrees" / name
            target = external / name
            admin.mkdir(parents=True)
            target.mkdir()
            (admin / "HEAD").write_text(tip + "\n", encoding="ascii")
            (admin / "commondir").write_text("../..\n", encoding="ascii")
            (admin / "gitdir").write_text(str(target / ".git") + "\n", encoding="utf-8")
            (target / ".git").write_text("gitdir: " + str(admin) + "\n", encoding="utf-8")
            names.add(name)

        # This qualifies the metadata/card ceiling, not file-reading throughput:
        # the external targets remain explicitly outside the authorized roots.
        for count in (300, 400, 500, 1000):
            with self.subTest(count=count):
                for number in range(len(names), count):
                    register(number)
                found = files.discover(repo.root, max_worktrees=count)
                worktrees = [item for item in found if not item["main"]]
                self.assertEqual(len(found), count + 1)
                self.assertEqual({item["id"] for item in worktrees}, names)
                self.assertTrue(all(item["reason"] == "outside" and item["path"] is None
                                    for item in worktrees))

        result = collector.Collector(repo.root, Settings(max_worktrees=1000, read_seconds=120,
                                                        max_branches=0)).snapshot(NOW)
        self.assertEqual(result["main"]["state"], "ok", result["main"])
        self.assertEqual(len(result["sessions"]), 1001)
        cards = [session for session in result["sessions"] if session["kind"] == "worktree"]
        self.assertEqual({session["name"] for session in cards}, names)
        self.assertTrue(all(session["reason"] == "outside" and not session["files_read"] for session in cards))
        self.assertTrue(all(session.get("advice") not in ("ready_to_merge", "ended") for session in cards))

        register(1000)
        with self.assertRaises(files.TooManyWorktrees):
            files.discover(repo.root, max_worktrees=1000)
        refused = collector.Collector(repo.root, Settings(max_worktrees=1000, read_seconds=120)).snapshot(NOW)
        self.assertEqual(refused["main"]["reason"], "too_many_worktrees")
        self.assertEqual(refused["sessions"], [])
        self.assertEqual(refused["settings"]["max_worktrees"], 1000)


@unittest.skipIf(GIT is None, "git absent")
class WorktreeLimitGuardsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.one = self.repo.worktree("one", "one")
        self.two = self.repo.worktree("two", "two")

    def test_explicit_limit_overrides_a_default_without_mutating_it_or_dropping_sessions(self) -> None:
        with mock.patch.object(files, "MAX_WORKTREES", 1):
            with self.assertRaises(files.TooManyWorktrees):
                files.discover(self.repo.root)
            found = files.discover(self.repo.root, max_worktrees=2)
            self.assertEqual({item["id"] for item in found}, {"", "one", "two"})
            self.assertTrue(all(item["path"] is not None for item in found))
            self.assertEqual(files.MAX_WORKTREES, 1)
            with self.assertRaises(files.TooManyWorktrees):
                files.discover(self.repo.root)

    def test_a_larger_limit_keeps_the_shared_deadline(self) -> None:
        budget = files.Budget(deadline=time.monotonic() - 1)
        with mock.patch.object(files.os, "lstat") as stat, self.assertRaises(files.ReadingTooLong):
            files.discover(self.repo.root, budget=budget, max_worktrees=1000)
        stat.assert_not_called()

    def test_a_larger_limit_does_not_replenish_the_shared_entry_budget(self) -> None:
        budget = files.Budget(entries=1)
        self.assertTrue(files.git_dir_problem(self.repo.root, budget=budget).startswith("many:"))
        found = files.discover(self.repo.root, budget=budget, max_worktrees=1000)
        self.assertTrue(all(item["path"] is None and item["reason"] == "odd_admin" for item in found[1:]))
        self.assertLess(budget.left, 0)

    def test_a_larger_limit_keeps_a_linked_worktree_unreadable(self) -> None:
        target = self.repo.root.parent / "link-target"
        target.mkdir()
        linked = self.repo.root / ".claude" / "worktrees" / "linked"
        if not make_link(target, linked):
            self.skipTest("links unavailable")
        admin = self.repo.root / ".git" / "worktrees" / "linked"
        admin.mkdir()
        (admin / "HEAD").write_text(self.repo.git("rev-parse", "HEAD") + "\n", encoding="ascii")
        (admin / "commondir").write_text("../..\n", encoding="ascii")
        (admin / "gitdir").write_text(str(linked / ".git") + "\n", encoding="utf-8")
        found = files.discover(self.repo.root, max_worktrees=1000)
        refused = next(item for item in found if item["id"] == "linked")
        self.assertEqual((refused["path"], refused["reason"]), (None, "link"))
        self.assertTrue(all(item["path"] is not None for item in found if item["id"] in ("one", "two")))


@unittest.skipIf(GIT is None, "git absent")
class ExactExternalRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.tree = self.repo.root.parent / "exact-root"
        self.repo.git("worktree", "add", "-q", "-b", "codex/exact", str(self.tree), "main")
        self.admin = self.repo.root / ".git" / "worktrees" / self.tree.name
        self.settings = Settings(external_worktrees=(self.tree,), max_worktrees=267)

    def card(self, settings=None) -> dict:
        result = collector.Collector(self.repo.root, settings or self.settings).snapshot(NOW)
        self.assertEqual(result["main"]["state"], "ok", result["main"])
        return next(session for session in result["sessions"] if session["kind"] == "worktree")

    def test_the_exact_authorized_root_exposes_its_tracked_changes(self) -> None:
        (self.tree / "app.py").write_text("print(2)\n", encoding="utf-8", newline="\n")
        card = self.card()
        self.assertEqual((card["reason"], card["files_read"], card["modified"]), ("", True, 1))
        self.assertEqual(card["branch"], "codex/exact")

    def test_the_exact_root_still_requires_explicit_authorization(self) -> None:
        card = self.card(Settings(max_worktrees=267))
        self.assertEqual((card["reason"], card["files_read"]), ("outside", False))

    def test_launch_from_the_exact_root_finds_its_main_checkout(self) -> None:
        self.assertEqual(collector.Collector(self.tree, self.settings).root, self.repo.root)

    def test_an_exact_root_authorizes_no_prefix_sibling(self) -> None:
        sibling = self.tree.with_name(self.tree.name + "-other")
        self.repo.git("worktree", "add", "-q", "-b", "codex/sibling", str(sibling), "main")
        found = files.discover(self.repo.root, external_roots=(self.tree,), max_worktrees=267)
        allowed = next(item for item in found if item["id"] == self.tree.name)
        refused = next(item for item in found if item["id"] == sibling.name)
        self.assertEqual((allowed["reason"], allowed["path"]), ("", self.tree))
        self.assertEqual((refused["reason"], refused["path"]), ("outside", None))

    def test_an_exact_root_keeps_its_reciprocal_marker_check(self) -> None:
        marker = self.tree / ".git"
        marker.unlink()  # Windows marks Git's marker hidden; replace it instead of truncating it.
        marker.write_text("gitdir: " + str(self.admin.with_name("wrong-admin")) + "\n", encoding="utf-8")
        card = self.card()
        self.assertEqual((card["reason"], card["files_read"]), ("odd_admin", False))

    def test_a_link_used_as_the_exact_root_is_never_entered(self) -> None:
        alias = self.tree.with_name("linked-root")
        if not make_link(self.tree, alias):
            self.skipTest("links unavailable")
        (self.admin / "gitdir").write_text(str(alias / ".git") + "\n", encoding="utf-8")
        with mock.patch.object(files, "_worktree_marker", wraps=files._worktree_marker) as checked:
            card = self.card(Settings(external_worktrees=(alias,), max_worktrees=267))
        self.assertFalse(card["files_read"])
        self.assertIn(card["reason"], ("outside", "link"))
        self.assertFalse(any(call.args[0] == alias for call in checked.call_args_list))

    def test_duplicate_admins_of_an_exact_root_remain_unreadable(self) -> None:
        extra = self.admin.with_name("extra-admin")
        extra.mkdir()
        for name in ("HEAD", "commondir", "gitdir"):
            (extra / name).write_bytes((self.admin / name).read_bytes())
        found = files.discover(self.repo.root, external_roots=(self.tree,), max_worktrees=267)
        original = next(item for item in found if item["id"] == self.tree.name)
        self.assertEqual((original["reason"], original["path"]), ("duplicate_admin", None))
        self.assertTrue(all(item["path"] is None for item in found if not item["main"]))

    def test_a_snapshot_cannot_write_inside_the_exact_root(self) -> None:
        output = self.tree / "board.html"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = cli.main(["--snapshot", "--repo", str(self.repo.root), "--worktrees-root", str(self.tree),
                               "--max-worktrees", "267", "--output", str(output)])
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
