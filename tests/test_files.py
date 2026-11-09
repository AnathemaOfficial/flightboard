# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the file side of flightboard: which worktree folders may be read, and how.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.fixtures import load

files = load("files")
WINDOWS = os.name == "nt"
SLASHES = "/" * 2
BACKSLASHES = "\\" * 2
LEDGER = ("data", "roadmap.json")


def make_link(target: Path, link: Path) -> bool:
    """A link or junction to a folder; False when this system does not let the test make one."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if WINDOWS:
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except (ImportError, OSError):
            return False
    return False


class CheckWorktreeTest(unittest.TestCase):
    """Pure text: nothing on disk may be touched while a path is judged."""

    def setUp(self) -> None:
        self.root = Path(tempfile.gettempdir()).resolve() / "demo"
        guard = mock.patch.object(files.os, "lstat", side_effect=AssertionError("disk touched"))
        guard.start()
        self.addCleanup(guard.stop)
        opener = mock.patch("builtins.open", side_effect=AssertionError("file opened"))
        opener.start()
        self.addCleanup(opener.stop)

    def gitdir(self, *parts: str) -> str:
        return (self.root.joinpath(*parts) / ".git").as_posix()

    def test_the_main_checkout_and_its_session_folders(self) -> None:
        self.assertEqual(files.check_worktree(self.gitdir(), self.root), self.root)
        found = files.check_worktree(self.gitdir(".claude", "worktrees", "fb-210-export-0c4d9e"), self.root)
        self.assertEqual(found, self.root / ".claude" / "worktrees" / "fb-210-export-0c4d9e")
        windows_form = self.gitdir(".claude", "worktrees", "x").replace("/", "\\")
        expected = self.root / ".claude" / "worktrees" / "x" if WINDOWS else None
        self.assertEqual(files.check_worktree(windows_form, self.root), expected)

    def test_other_folders_only_when_named(self) -> None:
        text = self.gitdir(".worktrees", "x")
        self.assertIsNone(files.check_worktree(text, self.root))
        parents = (*files.WORKTREES, (".worktrees",))
        self.assertEqual(files.check_worktree(text, self.root, parents=parents), self.root / ".worktrees" / "x")
        self.assertIsNone(files.check_worktree(self.gitdir(".worktrees", "x", "y"), self.root, parents=parents))
        self.assertEqual(files.check_worktree(self.gitdir(".claude", "worktrees", "x"), self.root, parents=parents),
                         self.root / ".claude" / "worktrees" / "x")

    def test_the_relative_form_is_read_from_the_admin_folder(self) -> None:
        admin = self.root / ".git" / "worktrees" / "x"
        self.assertEqual(files.check_worktree("../../../.claude/worktrees/x/.git", self.root, admin),
                         self.root / ".claude" / "worktrees" / "x")
        self.assertIsNone(files.check_worktree("../../../../elsewhere/x/.git", self.root, admin))
        self.assertIsNone(files.check_worktree(".claude/worktrees/x/.git", self.root))

    def test_shares_devices_and_odd_paths_are_refused(self) -> None:
        drive = self.root.drive
        cases = [SLASHES + "host/share/x/.git", BACKSLASHES + "host" + "\\" + "share" + "\\" + "x" + "\\.git",
                 SLASHES + "?/" + self.gitdir(".claude", "worktrees", "x").lstrip("/"),
                 SLASHES + "./" + self.gitdir(".claude", "worktrees", "x").lstrip("/"),
                 self.gitdir(".claude", "worktrees", "..", "..", "x"), self.gitdir(".claude", "worktrees", "x:stream"),
                 self.gitdir(".claude", "worktrees", "aux"), self.gitdir(".claude", "worktrees", "com1.txt"),
                 self.gitdir("other", "x"), self.gitdir(".claude", "worktrees", "x", "y"),
                 self.gitdir(".claude", "worktrees", "x").replace("/.git", "/not-git"),
                 self.gitdir(".claude", "worktrees", "a b"), "", "relative/.git",
                 # Windows drops a final dot from the last part of a path only: x.. names x, x..\sub names nothing
                 self.gitdir(".claude", "worktrees", "x."), self.gitdir(".claude", "worktrees", "x..")]
        if WINDOWS and drive:
            other = ("Z" if drive[0].upper() != "Z" else "Y") + ":"
            cases.append(self.gitdir(".claude", "worktrees", "x").replace(drive, other, 1))
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(files.check_worktree(text, self.root, self.root / ".git" / "worktrees" / "x"))

    @unittest.skipUnless(WINDOWS, "drive letters and case: Windows only")
    def test_case_does_not_matter_on_windows(self) -> None:
        text = self.gitdir(".claude", "worktrees", "x").upper().replace("/.GIT", "/.git")
        self.assertIsNotNone(files.check_worktree(text, self.root))


class LinksTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "demo"
        self.tree = self.root / ".claude" / "worktrees" / "a"
        (self.tree / "data").mkdir(parents=True)
        (self.tree / "data" / "roadmap.json").write_text('{"tasks": []}', encoding="utf-8")
        self.elsewhere = Path(self._tmp.name).resolve() / "elsewhere"
        (self.elsewhere / "data").mkdir(parents=True)
        (self.elsewhere / "data" / "roadmap.json").write_text('{"secret": true}', encoding="utf-8")

    def test_plain_folders_pass(self) -> None:
        self.assertTrue(files.no_link(self.tree / "data" / "roadmap.json", self.root))
        self.assertFalse(files.no_link(self.elsewhere, self.root))
        self.assertFalse(files.no_link(self.tree / "absent", self.root))

    def test_a_link_or_junction_on_the_way_is_refused(self) -> None:
        link = self.root / ".claude" / "worktrees" / "link"
        if not make_link(self.elsewhere, link):
            self.skipTest("this system does not let the test make a link")
        self.assertFalse(files.no_link(link / "data" / "roadmap.json", self.root))
        self.assertEqual(files.read_ledger(link, self.root, LEDGER)[:2], (None, "unreadable"))
        data_link = self.tree / "data2"
        if make_link(self.elsewhere / "data", data_link):
            self.assertFalse(files.no_link(data_link, self.root))

    def test_reading_a_ledger(self) -> None:
        data, state, identity = files.read_ledger(self.tree, self.root, LEDGER)
        self.assertEqual((data, state), (b'{"tasks": []}', "ok"))
        self.assertIsNotNone(identity)
        with mock.patch.object(files, "MAX_LEDGER_BYTES", 3):
            self.assertEqual(files.read_ledger(self.tree, self.root, LEDGER)[1], "too_big")
        (self.tree / "data" / "roadmap.json").unlink()
        self.assertEqual(files.read_ledger(self.tree, self.root, LEDGER)[:2], (None, "absent"))

    def test_an_impossible_file_date_gives_no_date(self) -> None:
        broken = mock.Mock(fromtimestamp=mock.Mock(side_effect=OSError(22, "date out of range")))
        with mock.patch.object(files, "datetime", broken):
            self.assertIsNone(files.last_write(self.tree, self.root, ["data/roadmap.json"]))

    def test_last_write_reads_only_plain_relative_names(self) -> None:
        when = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)
        os.utime(self.tree / "data" / "roadmap.json", (when.timestamp(), when.timestamp()))
        (self.tree / "old.txt").write_text("x", encoding="utf-8")
        old = when - timedelta(days=2)
        os.utime(self.tree / "old.txt", (old.timestamp(), old.timestamp()))
        names = ["data/roadmap.json", "old.txt", "../elsewhere/data/roadmap.json", "C" + ":/x", "/etc/passwd",
                 "a\\b", "absent.txt"]
        self.assertEqual(files.last_write(self.tree, self.root, names), when)
        self.assertIsNone(files.last_write(self.tree, self.root, ["../x", "absent"]))


class DiscoverTest(unittest.TestCase):
    """The worktrees are found in the admin folders, without git, and a refused folder is never touched."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "demo"
        self.admins = self.root / ".git" / "worktrees"
        self.admins.mkdir(parents=True)
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.unc = BACKSLASHES + "host" + "\\" + "share" + "\\" + "x" + "\\.git"
        self.admin("a", (self.root / ".claude" / "worktrees" / "a" / ".git").as_posix(), "ref: refs/heads/claude/a")
        (self.root / ".claude" / "worktrees" / "a").mkdir(parents=True)
        (self.root / ".claude" / "worktrees" / "a" / ".git").write_text(
            "gitdir: " + (self.admins / "a").as_posix() + "\n", encoding="utf-8")
        self.admin("b", self.unc, "b" * 40)
        self.admin("c", (self.root / ".claude" / "worktrees" / "c" / ".git").as_posix(), "ref: refs/heads/claude/c")
        self.admin("d", "../../../.claude/worktrees/d/.git", "d" * 40)
        (self.root / ".claude" / "worktrees" / "d").mkdir(parents=True)
        (self.root / ".claude" / "worktrees" / "d" / ".git").write_text(
            "gitdir: " + (self.admins / "d").as_posix() + "\n", encoding="utf-8")
        (self.admins / "d" / "rebase-merge").mkdir()
        (self.admins / "d" / "rebase-merge" / "head-name").write_text("refs/heads/claude/d\n", encoding="utf-8")
        (self.admins / "not a name!").mkdir()

    def admin(self, name: str, gitdir: str, head: str) -> None:
        folder = self.admins / name
        folder.mkdir()
        (folder / "gitdir").write_text(gitdir + "\n", encoding="utf-8")
        (folder / "HEAD").write_text(head + "\n", encoding="utf-8")
        (folder / "commondir").write_text("../..\n", encoding="utf-8")

    def test_worktrees_from_the_admin_folders(self) -> None:
        found = {item["id"]: item for item in files.discover(self.root)}
        self.assertEqual(set(found), {"", "a", "b", "c", "d", "unknown:5"})
        self.assertTrue(found["unknown:5"]["unknown"])
        self.assertEqual((found[""]["path"], found[""]["head"], found[""]["main"]), (self.root, {"ref": "refs/heads/main"},
                                                                                     True))
        self.assertEqual((found["a"]["path"], found["a"]["head"]), (self.root / ".claude" / "worktrees" / "a",
                                                                     {"ref": "refs/heads/claude/a"}))
        self.assertEqual((found["b"]["path"], found["b"]["reason"]), (None, "outside"))
        self.assertEqual(found["c"]["path"], None)
        self.assertEqual(found["c"]["reason"], "gone")
        self.assertEqual(found["d"]["operation"], {"kind": "rebase", "branch": "refs/heads/claude/d"})
        self.assertIsNotNone(found["a"]["created"])

    def test_a_refused_folder_is_never_touched(self) -> None:
        seen: list[str] = []
        real = os.lstat

        def spy(path, *args, **kwargs):
            seen.append(str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=spy):
            files.discover(self.root)
        self.assertTrue(seen)
        self.assertFalse([path for path in seen if path.startswith((SLASHES, BACKSLASHES, "\\\\?"))])

    def test_no_repository(self) -> None:
        self.assertEqual(files.discover(Path(self._tmp.name).resolve() / "nothing"), [])

    def test_odd_admin_files_keep_git_away(self) -> None:
        self.assertTrue(files.plain_admin(self.admins / "a", self.root))
        (self.admins / "a" / "config.worktree").write_text("[core]\n\tlongpaths = true\n", encoding="utf-8")
        self.assertTrue(files.plain_admin(self.admins / "a", self.root))
        for name, text in (("config.worktree", "[core]\n\texcludesFile = " + SLASHES + "host/share/x\n"),
                           ("commondir", SLASHES + "host/share/x\n")):
            with self.subTest(name=name):
                (self.admins / "a" / "config.worktree").write_text("[core]\n\tlongpaths = true\n", encoding="utf-8")
                (self.admins / "a" / "commondir").write_text("../..\n", encoding="utf-8")
                (self.admins / "a" / name).write_text(text, encoding="utf-8")
                found = {item["id"]: item for item in files.discover(self.root)}
                self.assertEqual((found["a"]["path"], found["a"]["reason"]), (None, "odd_admin"))

    def test_a_commondir_is_read_as_git_reads_it(self) -> None:
        commondir = self.admins / "a" / "commondir"
        for data in (b"../..", b"../..\n", b"../..\r\n"):  # git drops only CR and LF at the end
            with self.subTest(data=data):
                commondir.write_bytes(data)
                self.assertTrue(files.plain_admin(self.admins / "a", self.root))
        # padded, git reads another folder (.git/worktrees/..<pad>, or one inside the admin folder): never read
        for data in ("../.. \n", " ../..\n", "../..\t\n", "　../..\n", "../..\x85\n", "../..\x1c\n",
                     "../.. \n", "../..\x0b\n", "../..\0\n"):
            with self.subTest(data=data):
                commondir.write_bytes(data.encode("utf-8"))
                self.assertFalse(files.plain_admin(self.admins / "a", self.root))
                found = {item["id"]: item for item in files.discover(self.root)}
                self.assertEqual((found["a"]["path"], found["a"]["reason"]), (None, "odd_admin"))

    def test_a_gone_folder_and_a_linked_one_are_told_apart(self) -> None:
        found = {item["id"]: item for item in files.discover(self.root)}
        self.assertEqual((found["c"]["path"], found["c"]["reason"]), (None, files.GONE))
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        self.admin("e", (self.root / ".claude" / "worktrees" / "e" / ".git").as_posix(), "ref: refs/heads/claude/e")
        if not make_link(outside, self.root / ".claude" / "worktrees" / "e"):
            self.skipTest("this system does not let the test make a link")
        found = {item["id"]: item for item in files.discover(self.root)}
        self.assertEqual((found["e"]["path"], found["e"]["reason"]), (None, "link"))

    def test_an_admin_index_that_is_a_link_is_refused(self) -> None:
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        if not make_link(outside, self.admins / "a" / "index"):
            self.skipTest("this system does not let the test make a link")
        self.assertFalse(files.plain_admin(self.admins / "a", self.root))

    def test_sparse_checkout_settings_are_plain(self) -> None:
        (self.admins / "a" / "config.worktree").write_text(
            "[core]\n\tsparseCheckout = true\n\tsparseCheckoutCone = true\n", encoding="utf-8")
        self.assertTrue(files.plain_admin(self.admins / "a", self.root))
        for text in ("[core]\n\tsparseCheckout = " + SLASHES + "host\n", "[extensions]\n\tworktreeConfig = true\n",
                     "[core]\n\thooksPath = x\n"):
            with self.subTest(text=text):
                self.assertFalse(files.plain_config(text))

    def test_a_worktree_leads_to_its_main_checkout(self) -> None:
        tree = self.root / ".claude" / "worktrees" / "a"
        (tree / ".git").write_text("gitdir: " + (self.admins / "a").as_posix() + "\n", encoding="utf-8")
        self.assertEqual(files.main_checkout(tree), self.root)
        self.assertEqual(files.main_checkout(self.root), self.root)
        for text in ("gitdir: " + SLASHES + "host/share/.git/worktrees/a", "gitdir: relative/without/sense",
                     "not a gitdir", "gitdir: " + (self.root / "other" / ".git" / "worktrees" / "a").as_posix()):
            with self.subTest(text=text):
                (tree / ".git").write_text(text + "\n", encoding="utf-8")
                self.assertEqual(files.main_checkout(tree), tree)
        elsewhere = Path(self._tmp.name).resolve() / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / ".git").write_text("gitdir: " + (self.admins / "a").as_posix() + "\n", encoding="utf-8")
        self.assertEqual(files.main_checkout(elsewhere), elsewhere)  # not one of main's own session folders


class UntrackedTest(unittest.TestCase):
    """Untracked content is listed here, never by git: no link followed, no .git entry opened, no new folder entered."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "demo"
        (self.root / "docs" / "sub").mkdir(parents=True)
        for name in ("README.md", "docs/a.md", "docs/sub/b.md"):
            (self.root / name).write_text("x", encoding="utf-8")
        self.tracked = {"README.md", "docs/a.md", "docs/sub/b.md"}

    def test_new_files_and_folders(self) -> None:
        (self.root / "new.py").write_text("x", encoding="utf-8")
        (self.root / "docs" / "c.md").write_text("x", encoding="utf-8")
        (self.root / "module" / "deep").mkdir(parents=True)
        (self.root / "module" / "deep" / "d.py").write_text("x", encoding="utf-8")
        nested = self.root / "docs" / "nested"
        nested.mkdir()
        (nested / ".git").write_text("gitdir: " + SLASHES + "host/share/x\n", encoding="utf-8")
        seen: list[str] = []
        real = os.scandir

        def spy(path):
            seen.append(str(path))
            return real(path)

        with mock.patch.object(files.os, "scandir", side_effect=spy):
            found = files.untracked(self.root, self.root, self.tracked)
        self.assertEqual(sorted(found), ["docs/c.md", "docs/nested/", "module/", "new.py"])
        self.assertFalse([path for path in seen if "nested" in path or "module" in path])
        self.assertIsNone(files.untracked(self.root, self.root, self.tracked, limit=2))

    def test_odd_tracked_names_never_lead_the_walk_outside(self) -> None:
        seen: list[str] = []
        real = os.scandir

        def spy(path):
            seen.append(str(path))
            return real(path)

        odd = self.tracked | {"../../neighbour/x.md", "/x", "C" + ":/y.md", "a\\..\\..\\z.md"}
        with mock.patch.object(files.os, "scandir", side_effect=spy):
            found = files.untracked(self.root, self.root, odd)  # "/x" once looped for ever
        self.assertEqual(found, files.untracked(self.root, self.root, self.tracked))
        self.assertFalse([path for path in seen if not Path(path).resolve().is_relative_to(self.root)])

    def test_a_submodule_folder_is_never_new(self) -> None:
        (self.root / "module").mkdir()
        (self.root / "module" / "lib.py").write_text("x", encoding="utf-8")
        self.assertIn("module/", files.untracked(self.root, self.root, self.tracked))
        self.assertNotIn("module/", files.untracked(self.root, self.root, self.tracked | {"module"}))

    def test_links_are_never_listed_nor_entered(self) -> None:
        outside = Path(self._tmp.name).resolve() / "elsewhere"
        outside.mkdir()
        (outside / "secret.txt").write_text("x", encoding="utf-8")
        if not make_link(outside, self.root / "docs" / "link"):
            self.skipTest("this system does not let the test make a link")
        self.assertNotIn("docs/link/", files.untracked(self.root, self.root, self.tracked))

    def test_a_new_folder_is_walked_a_few_levels_never_into_a_git(self) -> None:
        (self.root / "tools" / "a" / "b" / "c").mkdir(parents=True)
        (self.root / "tools" / "a" / "x.pyc").write_text("x", encoding="utf-8")
        (self.root / "tools" / "a" / "b" / "c" / "far.pyc").write_text("x", encoding="utf-8")
        sealed = self.root / "tools" / "repo"
        sealed.mkdir()
        (sealed / ".git").write_text("gitdir: " + SLASHES + "host/share/x\n", encoding="utf-8")
        seen: list[str] = []
        real = os.scandir

        def spy(path):
            seen.append(str(path))
            return real(path)

        with mock.patch.object(files.os, "scandir", side_effect=spy):
            found = files.children(self.root, self.root, "tools/")
        self.assertEqual({key: sorted(value) for key, value in found.items()},
                         {"leaves": ["tools/a/b/c/", "tools/a/x.pyc"], "folders": ["tools/a/", "tools/a/b/"],
                          "sealed": ["tools/repo/"]})
        self.assertFalse([path for path in seen if "repo" in Path(path).name])
        # all ignored only when each leaf is, itself or under an ignored folder; a sealed folder only under one
        self.assertFalse(files.all_ignored(found, {"tools/a/x.pyc", "tools/a/b/c/"}))
        self.assertTrue(files.all_ignored({**found, "sealed": []}, {"tools/a/x.pyc", "tools/a/b/c/"}))
        self.assertTrue(files.all_ignored({**found, "sealed": []}, {"tools/a/"}))
        self.assertTrue(files.all_ignored({"leaves": [], "folders": [], "sealed": []}, set()))  # empty: git hides it
        (self.root / "new").mkdir()
        (self.root / "new" / ".git").write_text("x", encoding="utf-8")
        self.assertIsNone(files.children(self.root, self.root, "new/"))

    def test_kept_work_and_planted_attributes(self) -> None:
        (self.root / "notes" / "sub").mkdir(parents=True)
        for name in ("notes/_template.md", "notes/2026-11-07-note.md", "notes/sub/other.md"):
            (self.root / name).write_text("x", encoding="utf-8")
        (self.root / "docs" / "research" / "raw").mkdir(parents=True)
        (self.root / "docs" / "research" / "raw" / "raw.json").write_text("{}", encoding="utf-8")
        folders = ("notes", "docs/research/raw")
        self.assertEqual(files.kept_count(self.root, self.root, self.tracked | {"notes/_template.md"}, folders), 3)
        self.assertEqual(files.kept_count(self.root, self.root, self.tracked, ()), 0)
        self.assertFalse(files.attributes_planted(self.root))
        (self.root / ".git" / "info").mkdir(parents=True)
        (self.root / ".git" / "info" / "attributes").write_text("", encoding="utf-8")
        self.assertFalse(files.attributes_planted(self.root))
        (self.root / ".git" / "info" / "attributes").write_text("* filter=probe\n", encoding="utf-8")
        self.assertTrue(files.attributes_planted(self.root))


class GitDirTest(unittest.TestCase):
    """What would lead every git command elsewhere is found before git runs on the repository, by lstat and small reads
    (and the installed git reading a byte copy of the configuration)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "demo"
        self.git = self.root / ".git"
        for folder in ("info", "objects/info", "objects/pack", "refs/heads", "logs"):
            (self.git / folder).mkdir(parents=True)
        (self.git / "config").write_text('[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n'
                                         '\turl = https://example.invalid/x.git\n[branch "claude/a-b"]\n'
                                         '\tremote = origin\n', encoding="utf-8")
        (self.git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.outside = Path(self._tmp.name).resolve() / "elsewhere"
        self.outside.mkdir()

    def test_a_plain_repository_passes(self) -> None:
        self.assertEqual(files.git_dir_problem(self.root), "")

    def test_what_git_would_follow_in_its_configuration_stops_it(self) -> None:
        cases = {"[include]\n\tpath = " + SLASHES + "host/share/x\n": "include",
                 '[includeIf "gitdir:x/"]\n\tpath = y\n': "include",
                 "[Include]\npath = y\n": "include",
                 "[core]\n\tworktree = " + SLASHES + "host/share\n": "core_worktree",
                 "[core] worktree = x\n": "core_worktree",
                 "[core\n": "config_unreadable:config"}
        for text, reason in cases.items():
            with self.subTest(text=text):
                (self.git / "config").write_text(text, encoding="utf-8")
                self.assertEqual(files.git_dir_problem(self.root), reason)
        (self.git / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
        (self.git / "config.worktree").write_text("[core]\n\thooksPath = x\n", encoding="utf-8")
        self.assertEqual(files.git_dir_problem(self.root), "main_worktree_config")

    def test_borrowed_objects_and_a_commondir_stop_it(self) -> None:
        alternates = self.git / "objects" / "info" / "alternates"
        alternates.write_text(SLASHES + "host/share/objects\n", encoding="utf-8")
        self.assertEqual(files.git_dir_problem(self.root), "alternates")
        alternates.write_text("", encoding="utf-8")
        self.assertEqual(files.git_dir_problem(self.root), "")
        (self.git / "commondir").write_text(SLASHES + "host/share\n", encoding="utf-8")
        self.assertEqual(files.git_dir_problem(self.root), "commondir")

    def test_a_link_in_git_stops_it_and_is_never_looked_through(self) -> None:
        (self.git / "info").rmdir()
        if not make_link(self.outside, self.git / "info"):
            self.skipTest("this system does not let the test make a link")
        (self.outside / "attributes").write_text("* filter=probe\n", encoding="utf-8")
        seen: list[str] = []
        real = os.lstat

        def spy(path, *args, **kwargs):
            seen.append(str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=spy):
            self.assertEqual(files.git_dir_problem(self.root), "link:info")
            self.assertTrue(files.attributes_planted(self.root))  # it cannot be told: no file read
        self.assertFalse([path for path in seen if Path(path).name in ("attributes", "exclude")])


class TrackedTest(unittest.TestCase):
    """Before git status runs, every tracked path is checked on disk, never through a link: git must never meet a .git
    it would follow where the index expects a file or a submodule."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "demo"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "module").mkdir()
        for name in ("README.md", "docs/a.md"):
            (self.root / name).write_text("x", encoding="utf-8")
        self.staged = [("100644", "README.md"), ("100644", "docs/a.md"), ("160000", "module"),
                       ("100644", "deleted.md"), ("100644", "gone/b.md")]
        self.outside = Path(self._tmp.name).resolve() / "elsewhere"
        self.outside.mkdir()

    def problem(self) -> str:
        return files.tracked_problem(self.root, self.root, self.staged)

    def test_a_plain_worktree_passes(self) -> None:
        self.assertEqual(self.problem(), "")  # deleted files and a gone folder are only deleted files

    def test_a_tracked_file_turned_into_a_folder(self) -> None:
        (self.root / "README.md").unlink()
        (self.root / "README.md").mkdir()
        (self.root / "README.md" / ".git").write_text("gitdir: " + SLASHES + "host/share/x\n", encoding="utf-8")
        self.assertEqual(self.problem(), "tracked_replaced")

    def test_a_submodule_holding_a_git(self) -> None:
        (self.root / "module" / ".git").write_text("gitdir: " + SLASHES + "host/share/x\n", encoding="utf-8")
        self.assertEqual(self.problem(), "submodule_git")

    def test_links_are_refused_without_looking_through_them(self) -> None:
        (self.outside / "a.md").write_text("x", encoding="utf-8")
        (self.root / "docs" / "a.md").unlink()
        (self.root / "docs").rmdir()
        if not make_link(self.outside, self.root / "docs"):
            self.skipTest("this system does not let the test make a link")
        seen: list[str] = []
        real = os.lstat

        def spy(path, *args, **kwargs):
            seen.append(str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=spy):
            self.assertEqual(self.problem(), "tracked_link_folder")
        self.assertFalse([path for path in seen if Path(path).name == "a.md" and "docs" in path])

    def test_a_link_in_place_of_a_submodule(self) -> None:
        (self.outside / ".git").write_text("gitdir: " + SLASHES + "host/share/x\n", encoding="utf-8")
        (self.root / "module").rmdir()
        if not make_link(self.outside, self.root / "module"):
            self.skipTest("this system does not let the test make a link")
        self.assertEqual(self.problem(), "submodule_link")

    def test_odd_tracked_names_stop_the_reads(self) -> None:
        for name in ("../outside.md", "C" + ":/x.md", "a\\b.md"):
            with self.subTest(name=name):
                self.assertEqual(files.tracked_problem(self.root, self.root, [("100644", name)]), "odd_tracked_path")

    def test_a_name_ending_with_a_dot_or_a_space_is_refused_on_windows(self) -> None:
        """Windows drops a final dot or space from the last part of a path, never from the others: the board would
        check another file than the one git meets on its way."""
        with mock.patch.object(files.os, "name", "nt"):
            for name in ("sub./x.md", "sub /x.md", "x.md.", "x.md ", "sub/nul/a/x", "nul", "con.txt", "a/COM1/b",
                         "lpt¹"):
                with self.subTest(name=name):
                    self.assertFalse(files.safe_relative(name))
            for name in ("v1.2/x.md", "null/x", "console.md", "com10"):
                with self.subTest(name=name):
                    self.assertTrue(files.safe_relative(name))

    def test_an_index_git_would_read_as_sparse_or_past_its_end_is_never_handed_to_it(self) -> None:
        """One entry that is a folder makes git take an index for a sparse one, extensions or not; an extension
        running past the trailing hash makes git's 32-bit walk (Windows) wrap round to bytes the board never read."""
        git_dir = self.root / ".git"
        git_dir.mkdir()
        entry = bytes(24) + struct.pack(">I", 0o040000) + bytes(12) + bytes(20) + struct.pack(">H", 1) + b"b\0"
        body = b"DIRC" + struct.pack(">II", 2, 1) + entry + bytes(8 - (len(entry) % 8 or 8))
        (git_dir / "index").write_bytes(body + hashlib.sha1(body).digest())
        self.assertEqual(files.index_state(git_dir, self.root), "sparse")
        entry = bytes(24) + struct.pack(">I", 0o100644) + bytes(12) + bytes(20) + struct.pack(">H", 1) + b"a\0"
        head = b"DIRC" + struct.pack(">II", 2, 1) + entry + bytes(8 - (len(entry) % 8 or 8))
        body = head + b"ZZZZ" + struct.pack(">I", 2 ** 32 + 12 - len(head) - 8)  # git on Windows lands on 12
        (git_dir / "index").write_bytes(body + hashlib.sha1(body).digest())
        self.assertEqual(files.index_state(git_dir, self.root), "unreadable")

    def test_a_long_varint_in_an_index_is_read_in_a_few_steps(self) -> None:
        """A run of continuation bytes in a version 4 name made the walk take quadratic time: every reading hung."""
        git_dir = self.root / ".git"
        git_dir.mkdir()
        head = bytes(40) + bytes(20) + struct.pack(">H", 1)
        body = b"DIRC" + struct.pack(">II", 4, 1) + head + b"\x80" * 1_000_000 + b"\x00x\0"
        (git_dir / "index").write_bytes(body + hashlib.sha1(body).digest())
        started = time.monotonic()
        self.assertEqual(files.index_state(git_dir, self.root), "unreadable")
        self.assertLess(time.monotonic() - started, 2)

    def test_a_folder_that_cannot_be_listed_is_never_taken_for_empty(self) -> None:
        (self.root / "docs" / "new").mkdir()
        (self.root / "docs" / "new" / "work.md").write_text("x", encoding="utf-8")
        real = os.scandir
        denied = {os.fspath(self.root / "docs"), os.fspath(self.root / "docs" / "new")}

        def scandir(path):
            if os.fspath(path) in denied:
                raise PermissionError(13, "Access is denied", os.fspath(path))
            return real(path)

        with mock.patch.object(files.os, "scandir", side_effect=scandir):
            self.assertIsNone(files.untracked(self.root, self.root, {"docs/a.md"}))
            self.assertIsNone(files.children(self.root, self.root, "docs/new/"))
            self.assertEqual(files.kept_count(self.root, self.root, set(), ("docs/new",)), 1)
        self.assertEqual(files.children(self.root, self.root, "docs/new/")["leaves"], ["docs/new/work.md"])

    def test_no_link_never_takes_a_device_for_a_folder_or_a_file(self) -> None:
        """Windows answers the lstat of a last part named nul with the NUL device, whatever is on disk."""
        real = os.lstat

        def device(path, *args, **kwargs):
            if Path(path).name == "docs":
                return SimpleNamespace(st_mode=stat.S_IFCHR | 0o666, st_file_attributes=0)
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=device):
            self.assertFalse(files.no_link(self.root / "docs", self.root))
            self.assertFalse(files.no_link(self.root / "docs" / "a.md", self.root))
        self.assertTrue(files.no_link(self.root / "docs" / "a.md", self.root))

    def test_index_entries_are_walked_by_the_length_their_flags_give(self) -> None:
        """git sizes an index entry by the name length its flags give, not by where a NUL falls: a name written
        longer than its flags say must not hide from the board the extension git finds after it (a sparse index's,
        which the board must never hand to git)."""
        git_dir = self.root / ".git"
        git_dir.mkdir()
        head = bytes(40) + bytes(20) + struct.pack(">H", 1)  # stat data, object id, flags: a name of 1 byte
        for version, name in ((2, b"xy"), (4, b"\x00xy")):  # version 4: a varint (nothing kept), then the name
            with self.subTest(version=version):
                body = b"DIRC" + struct.pack(">II", version, 1) + head + name + b"sdir" + struct.pack(">I", 0)
                (git_dir / "index").write_bytes(body + hashlib.sha1(body).digest())
                self.assertEqual(files.index_state(git_dir, self.root), "sparse")

    def test_a_name_this_system_cannot_write_is_refused_quietly(self) -> None:
        """On Linux or BSD under a locale that is not UTF-8, a name beyond ASCII may have no spelling at all: it is
        refused like a name written otherwise, never an error that fails the whole session."""
        cannot = UnicodeEncodeError("latin-1", "日本.txt", 0, 1, "ordinal not in range")
        with mock.patch.object(files.os, "name", "posix"), mock.patch.object(files.os, "fsencode", side_effect=cannot):
            self.assertFalse(files.safe_relative("日本.txt"))
            self.assertEqual(files.tracked_problem(self.root, self.root, [("100644", "日本.txt")]),
                             "odd_tracked_path")


if __name__ == "__main__":
    unittest.main()
