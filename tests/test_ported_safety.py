# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Regression coverage for bounded Git reads and work that must never disappear at a display limit."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, git_starts, load
from tests.test_files import make_link
from tests.test_modes import Plain

files = load("files")
gitreads = load("gitreads")
gitconfig = load("gitconfig")
readio = load("readio")
Collector = load("collector").Collector

# A separate process holds a real Windows oplock and deliberately does not acknowledge its break.
OPLOCK_HOLDER = r'''
import ctypes, sys, time
from ctypes import wintypes
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
class Overlapped(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]
kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
kernel.CreateFileW.restype = wintypes.HANDLE
kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(Overlapped)]
kernel.DeviceIoControl.restype = wintypes.BOOL
handle = kernel.CreateFileW(sys.argv[1], 0x80000000, 7, None, 3, 0x40000000, None)
overlapped = Overlapped(hEvent=kernel.CreateEventW(None, True, False, None))
done = kernel.DeviceIoControl(handle, int(sys.argv[2]), None, 0, None, 0, None, ctypes.byref(overlapped))
print("GRANTED" if not done and ctypes.get_last_error() == 997 else "REFUSED", flush=True)
time.sleep(10)
'''


class PipeBoundsTest(unittest.TestCase):
    def test_input_that_git_does_not_read_obeys_the_deadline(self) -> None:
        start = time.monotonic()
        with git_starts("import time; time.sleep(20)") as started, self.assertRaises(gitreads.GitFailed):
            gitreads._spawn([sys.executable], gitreads.environment(), str(Path.cwd()), b"x" * 2_000_000, 0.1)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertTrue(all(process.poll() is not None for process in started.processes))

    def test_both_output_streams_have_a_byte_limit(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), \
                    git_starts(f"import sys; sys.{stream}.buffer.write(b'x' * 200000); sys.{stream}.flush()"), \
                    self.assertRaisesRegex(gitreads.GitFailed, "byte limit"):
                gitreads._spawn([sys.executable], gitreads.environment(), str(Path.cwd()), None, 1, 1000)

    def test_a_descendant_retaining_pipes_cannot_hold_cleanup(self) -> None:
        code = ("import subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-I','-B','-c','import time; time.sleep(2)']); time.sleep(20)")
        start = time.monotonic()
        with git_starts(code) as started, self.assertRaises(gitreads.GitFailed):
            gitreads._spawn([sys.executable], gitreads.environment(), str(Path.cwd()), None, 0.1)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertTrue(all(process.poll() is not None for process in started.processes))

    def test_a_spent_reading_starts_no_git_or_configuration_parser(self) -> None:
        reader = gitreads.Git()
        reader.deadline = time.monotonic() - 1
        with mock.patch.object(subprocess, "Popen") as started, self.assertRaises(gitreads.ReadingTooLong):
            reader.version(Path.cwd())
        started.assert_not_called()
        with mock.patch.object(subprocess, "Popen") as started, self.assertRaises(gitreads.ReadingTooLong):
            gitconfig.entries(b"", reader.deadline)
        started.assert_not_called()

    def test_configuration_preflight_uses_the_shared_deadline(self) -> None:
        start = time.monotonic()
        with git_starts("import time; time.sleep(20)"), self.assertRaises(gitreads.GitFailed):
            gitconfig.entries(b"[core]\n\tbare=false\n", time.monotonic() + 0.1)
        self.assertLess(time.monotonic() - start, 1.5)


@unittest.skipIf(GIT is None, "git absent")
class SafetyRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)

    def test_a_late_conflict_survives_two_thousand_modified_files(self) -> None:
        root = self.repo.root
        for index in range(2000):
            (root / f"a{index:04d}.txt").write_bytes(b"base\n")
        (root / "zconflict.txt").write_bytes(b"base\n")
        self.repo.git("add", "--all")
        self.repo.git("commit", "-qm", "files")
        blob = self.repo.git("rev-parse", "HEAD:a0000.txt")
        self.repo.git("update-index", "--force-remove", "zconflict.txt")
        index_info = "".join(f"100644 {blob} {stage}\tzconflict.txt\n" for stage in (1, 2, 3))
        subprocess.run([GIT, "-C", str(root), "update-index", "--index-info"], input=index_info.encode(),
                       check=True, capture_output=True)
        for index in range(2000):
            (root / f"a{index:04d}.txt").write_bytes(b"modified content\n")
        card = next(card for card in Collector(root).snapshot(NOW)["sessions"] if card["kind"] == "checkout")
        self.assertEqual((card["modified"], card["conflicted"], card["stage"]), (2000, 1, "conflict"))

    def test_ignored_candidates_cannot_hide_the_next_untracked_file(self) -> None:
        self.repo.commit(self.repo.root, "tasks.toml", '[[tasks]]\nid="T-1"\nstatus="done"\n', "tasks", "08:40")
        self.repo.commit(self.repo.root, ".gitignore", "*.generated\n", "ignore", "08:45")
        tree = self.repo.worktree("T-1", "T-1")
        for index in range(200):
            (tree / f"a{index:04d}.generated").write_bytes(b"generated\n")
        (tree / "zwork.py").write_bytes(b"work that must survive\n")
        self.assertIn("?? zwork.py", self.repo.git("status", "--porcelain", where=tree))
        card = next(card for card in Collector(self.repo.root).snapshot(NOW)["sessions"] if card["name"] == "T-1")
        self.assertFalse(card["files_read"])
        self.assertEqual(card["files_issue"], "folder_unlisted")
        self.assertNotEqual(card["advice"], "ended")

    def test_an_assume_unchanged_file_is_never_called_clean(self) -> None:
        self.repo.git("update-index", "--assume-unchanged", "app.py")
        (self.repo.root / "app.py").write_bytes(b"uncommitted work\n")
        self.assertEqual(self.repo.git("status", "--porcelain"), "")
        card = next(card for card in Collector(self.repo.root).snapshot(NOW)["sessions"] if card["kind"] == "checkout")
        self.assertEqual((card["files_read"], card["files_issue"]), (False, "assumed_tracked"))

    def test_symbolic_refs_keep_their_target_and_ref_overflow_is_explicit(self) -> None:
        self.repo.git("symbolic-ref", "refs/heads/context", "refs/heads/main")
        refs = gitreads.Git().refs(self.repo.root / ".git")
        self.assertEqual(refs["refs/heads/context"]["symref"], "refs/heads/main")
        with mock.patch.object(gitreads, "MAX_REFS", 1), self.assertRaisesRegex(gitreads.GitFailed, "too many"):
            gitreads.Git().refs(self.repo.root / ".git")

    def test_a_nested_admin_ref_link_is_refused(self) -> None:
        self.repo.worktree("work", "topic")
        admin = self.repo.root / ".git" / "worktrees" / "work"
        refs = admin / "refs" / "worktree"
        refs.mkdir(parents=True)
        target = self.repo.root / "app.py"
        if not make_link(target, refs / "trap"):
            self.skipTest("links unavailable")
        self.assertFalse(files.plain_admin(admin, self.repo.root))
        tree = next(tree for tree in files.discover(self.repo.root) if tree["id"] == "work")
        self.assertEqual((tree["path"], tree["reason"]), (None, "odd_admin"))

    def test_a_duplicate_registration_never_reads_one_folder_twice(self) -> None:
        self.repo.worktree("work", "topic")
        admins = self.repo.root / ".git" / "worktrees"
        shutil.copytree(admins / "work", admins / "duplicate")
        trees = {tree["id"]: tree for tree in files.discover(self.repo.root)}
        self.assertIsNone(trees["work"]["path"])
        self.assertEqual(trees["work"]["reason"], "duplicate_admin")
        self.assertIsNone(trees["duplicate"]["path"])

    def test_a_mismatching_worktree_marker_is_unreadable(self) -> None:
        tree = self.repo.worktree("work", "topic")
        (tree / ".git").unlink()  # Git for Windows marks this file hidden, which a truncating open refuses.
        (tree / ".git").write_text("gitdir: absent\n", encoding="utf-8")
        found = next(item for item in files.discover(self.repo.root) if item["id"] == "work")
        self.assertEqual((found["path"], found["reason"]), (None, "odd_admin"))

    def test_a_worktree_count_limit_refuses_instead_of_dropping_sessions(self) -> None:
        self.repo.worktree("one", "one")
        self.repo.worktree("two", "two")
        with mock.patch.object(files, "MAX_WORKTREES", 1), self.assertRaises(files.TooManyWorktrees):
            files.discover(self.repo.root)

    def test_preflight_and_admin_walks_share_an_entry_budget(self) -> None:
        self.repo.worktree("work", "topic")
        budget = files.Budget(entries=1)
        self.assertTrue(files.git_dir_problem(self.repo.root, budget=budget).startswith("many:"))
        self.assertFalse(files.plain_admin(self.repo.root / ".git" / "worktrees" / "work", self.repo.root, budget))

    def test_reflog_tail_keeps_a_whole_first_line_at_the_byte_boundary(self) -> None:
        tip = self.repo.git("rev-parse", "HEAD")
        path = self.repo.root / ".git" / "logs" / "refs" / "heads" / "main"
        line = f"{tip} {tip} T <test@example.invalid> 1794000000 +0000\tcommit: retained\n".encode()
        path.write_bytes(b"discarded\n" + line)
        with mock.patch.object(files, "MAX_REFLOG_BYTES", len(line)):
            entries = files.read_reflog(self.repo.root, "refs/heads/main", 10)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["via"], "commit: retained")
        self.assertIsNone(files.read_reflog(self.repo.root, "refs/heads/main", 0, whole=True))

    def test_a_full_reflog_with_an_incomplete_line_is_unknown(self) -> None:
        path = self.repo.root / ".git" / "logs" / "HEAD"
        path.write_bytes(path.read_bytes() + b"unfinished")
        self.assertIsNone(files.read_reflog(self.repo.root, "HEAD", 100, whole=True))


class ReadBoundsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_a_rename_during_open_is_retried_from_lstat(self) -> None:
        path = self.root / "ledger"
        path.write_bytes(b"old")
        original = files._open_regular
        attempts = []

        def renamed(candidate, info):
            attempts.append(info.st_ino)
            if len(attempts) == 1:
                replacement = self.root / "replacement"
                replacement.write_bytes(b"new")
                replacement.replace(path)
                return None
            return original(candidate, info)

        with mock.patch.object(files, "_open_regular", side_effect=renamed):
            self.assertEqual(files._read_file(path, self.root, 100), (b"new", "ok"))
        self.assertEqual(len(attempts), 2)

    def test_a_deep_or_crowded_kept_folder_is_never_empty(self) -> None:
        top = self.root / "notes"
        (top / "deep" / "deeper").mkdir(parents=True)
        with mock.patch.object(files, "MAX_KEPT_DEPTH", 0):
            self.assertGreater(files.kept_count(self.root, self.root, set(), ("notes",)), 0)
        with mock.patch.object(files, "MAX_KEPT_ENTRIES", 0):
            self.assertGreater(files.kept_count(self.root, self.root, set(), ("notes",)), 0)

    @unittest.skipUnless(os.name == "nt", "Windows filename normalization")
    def test_a_nested_trailing_dot_is_never_taken_for_an_empty_folder(self) -> None:
        new = self.root / "new"
        new.mkdir()
        unusual = "\\\\?\\" + str(new / "sub.")
        os.mkdir(unusual)
        Path(unusual, "work.txt").write_bytes(b"work\n")
        self.assertIsNone(files.children(self.root, self.root, "new/"))

    @unittest.skipUnless(os.name == "nt", "Windows native file handles")
    def test_an_oplock_break_handle_is_closed_without_reading(self) -> None:
        import _winapi
        path = self.root / "file"
        path.write_bytes(b"content")
        handle = _winapi.CreateFile(str(path), _winapi.GENERIC_READ, 7, _winapi.NULL, _winapi.OPEN_EXISTING, 0,
                                   _winapi.NULL)
        close = _winapi.CloseHandle
        with mock.patch.object(readio, "_nt_open", return_value=(readio.OPLOCK_BREAK, handle)), \
                mock.patch.object(readio._winapi, "CloseHandle", wraps=close) as closed, self.assertRaises(OSError):
            readio.open_file(path)
        closed.assert_called_once_with(handle)

    @unittest.skipUnless(os.name == "nt", "Windows opportunistic locks")
    def test_real_exclusive_oplocks_never_hold_file_or_reflog_reads(self) -> None:
        for kind in (0x00090008, 0x00090000):  # batch and level-one oplocks
            with self.subTest(kind=kind):
                path = self.root / f"locked-{kind}"
                path.write_bytes(b"content\n")
                holder = subprocess.Popen([sys.executable, "-I", "-B", "-c", OPLOCK_HOLDER, str(path), str(kind)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    granted = holder.stdout.readline().strip()
                    if granted == "REFUSED":
                        self.skipTest("the filesystem refused the requested oplock")
                    self.assertEqual(granted, "GRANTED")
                    start = time.monotonic()
                    self.assertEqual(files._read_file(path, self.root, 100), (None, "unreadable"))
                    self.assertEqual(files._read_tail(path, self.root, 100), (None, "unreadable"))
                    self.assertLess(time.monotonic() - start, 1.5)
                finally:
                    holder.kill()
                    holder.wait(2)
                    holder.stdout.close()
                    holder.stderr.close()
                self.assertEqual(files._read_file(path, self.root, 100), (b"content\n", "ok"))
