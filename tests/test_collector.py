# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for flightboard on real git repositories: sessions, the live overlay, main's history through its reflog, and
the safety of every read.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from tests.fixtures import (GIT, HOSTILE, MAIN, NOW, Repository, git_starts, load, reads_config_bytes,
                            roadmap_settings)

collector_module = load("collector")
gitreads = load("gitreads")
files = load("files")
text = load("text")
rules = load("ledgers.roadmap_rules")
cli = load("cli")
Settings = load("config").Settings
SLASHES, BACKSLASHES = "/" * 2, "\\" * 2


def by_name(view: dict) -> dict[str, dict]:
    return {session["name"]: session for session in view["sessions"]}


def read(root: Path, **values) -> dict:
    return collector_module.Collector(root, roadmap_settings(**values)).snapshot(NOW)


def tree(folder: Path, skip: Path | None = None) -> dict[str, tuple[int, int]]:
    found = {}
    for path in folder.rglob("*"):
        if skip is not None and path.is_relative_to(skip):
            continue
        if path.is_file() and not path.is_symlink():
            info = path.stat()
            found[str(path)] = (info.st_size, info.st_mtime_ns)
    return found


@unittest.skipIf(GIT is None, "git absent")
class CollectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Repository()
        cls.view = read(cls.repo.root)
        cls.sessions = by_name(cls.view)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_main_is_read_at_its_tip(self) -> None:
        main = self.view["main"]
        self.assertEqual((main["state"], main["ref"], main["head"], main["valid"]), ("ok", "main", self.repo.main[:7],
                                                                                    True))
        self.assertEqual((self.view["repository"], self.view["ledger"]["kind"]), ("demo", "roadmap"))

    def test_every_worktree_and_branch_ahead_of_main_is_a_session(self) -> None:
        kinds = {name: session["kind"] for name, session in self.sessions.items()}
        self.assertEqual(kinds, {"demo": "checkout", "fb-001-a-1b2c3d": "worktree", "old-b-4e5f6a": "worktree",
                                 "fb-006-d-7a8b9c": "worktree", "claude/fb-004-c": "branch",
                                 "claude/fb-001-z": "branch", "claude/owner": "branch",
                                 "claude/fb-139-x": "branch", "claude/fb-139-y": "branch",
                                 "claude/invalid": "branch"})

    def test_a_session_shows_only_its_own_changes(self) -> None:
        moves = {name: [(c["task"], c["from"], c["to"], c["uncommitted"]) for c in session["changes"]]
                 for name, session in self.sessions.items()}
        self.assertEqual(moves, {
            "demo": [("FB-005", "planned", "ready", True)],
            "fb-001-a-1b2c3d": [("FB-001", "planned", "awaiting_review", True)],
            "old-b-4e5f6a": [("FB-003", "ready", "awaiting_review", False)],  # never FB-002 or FB-006 back
            "fb-006-d-7a8b9c": [],
            "claude/fb-004-c": [("FB-004", "planned", "done", False)],
            "claude/fb-001-z": [("FB-001", "planned", "in_progress", False)],
            "claude/owner": [("FB-007", "ready", "done", False)],
            "claude/fb-139-x": [("FB-139", None, "planned", False)],
            "claude/fb-139-y": [("FB-139", None, "ready", False)],
            "claude/invalid": [("FB-003", "ready", "done", False)],
        })

    def test_stages_and_what_may_be_said(self) -> None:
        states = {name: (session["stage"], session["advice"]) for name, session in self.sessions.items()}
        self.assertEqual(states, {
            "demo": ("uncommitted", ""), "fb-001-a-1b2c3d": ("uncommitted", "open"),
            "old-b-4e5f6a": ("committed", "ready_to_merge"), "fb-006-d-7a8b9c": ("merged", "ended"),
            "claude/fb-004-c": ("committed", "ready_to_merge"), "claude/fb-001-z": ("committed", "open"),
            "claude/owner": ("committed", "ready_to_merge"), "claude/fb-139-x": ("committed", "open"),
            "claude/fb-139-y": ("committed", "open"), "claude/invalid": ("committed", "open"),
        })
        self.assertEqual((self.sessions["old-b-4e5f6a"]["ahead"], self.sessions["old-b-4e5f6a"]["behind"]), (1, 3))
        self.assertEqual(self.sessions["claude/invalid"]["reason"], "invalid_ledger")
        self.assertTrue(self.sessions["claude/invalid"]["reason_text"].startswith("invalid ledger: FB-003"))
        self.assertFalse(self.sessions["claude/invalid"]["overlay"])

    def test_activity_and_names(self) -> None:
        a = self.sessions["fb-001-a-1b2c3d"]
        self.assertEqual((a["activity"], a["modified"], a["tasks"]), ("active", 1, ["FB-001"]))
        self.assertEqual(self.sessions["demo"]["activity"], "recent")
        self.assertEqual(self.sessions["fb-006-d-7a8b9c"]["tasks"], ["FB-006"])
        self.assertEqual(self.sessions["demo"]["tasks"], ["FB-005"])  # never main's last commit
        self.assertEqual(self.view["sessions"][0]["name"], "fb-001-a-1b2c3d")  # the most recently active first

    def test_the_live_overlay(self) -> None:
        tasks = self.view["tasks"]
        self.assertEqual({tid: tasks[tid]["status"] for tid in ("FB-001", "FB-002", "FB-003", "FB-004", "FB-005",
                                                                "FB-006", "FB-007")},
                         {"FB-001": "planned", "FB-002": "awaiting_review", "FB-003": "awaiting_review",
                          "FB-004": "done", "FB-005": "ready", "FB-006": "done", "FB-007": "ready"})
        kpis = self.view["kpis"]
        self.assertEqual((kpis["done_main"], kpis["done_live"], kpis["review_live"], kpis["conflicts"]), (1, 2, 2, 2))

    def test_what_waits_for_the_owner(self) -> None:
        waiting = self.view["waiting"]
        self.assertEqual([item["kind"] for item in waiting],
                         ["merge", "merge", "merge", "conflict", "conflict", "check", "check", "alert",
                          "review", "review", "session"])
        self.assertEqual(self.view["waiting_more"], 0)
        texts = " | ".join(item["text"] for item in waiting)
        for expected in ("old-b-4e5f6a", "claude/fb-004-c", "FB-001 Task FB-001, changed in several places",
                         "FB-139", "ADR-0099", "“Yes, switch over”", "claude/owner marks FB-007 (Task FB-007)",
                         "claude/invalid: invalid ledger", "demo: uncommitted changes"):
            with self.subTest(expected=expected):
                self.assertIn(expected, texts)
        safe = " | ".join(item["safe"] for item in waiting)
        self.assertNotIn("Yes, switch over", safe)
        self.assertNotIn("done without evidence", safe)
        self.assertEqual(self.view["yours"], {"decisions": 0, "tasks": 1})

    def test_main_history_follows_its_reflog(self) -> None:
        events = [(e["task"], e["from"], e["to"], e["sha"], e["subject"]) for e in self.view["events"]
                  if e["where"] == "main"]
        self.assertEqual(events, [("FB-006", "planned", "done", self.repo.main[:7],
                                   "merge claude/fb-006-d: Fast-forward"),
                                  ("FB-002", "in_progress", "awaiting_review", self.repo.second[:7],
                                   "commit: docs: FB-002 in review")])
        self.assertEqual([version["counts"].get("done", 0) for version in self.view["history"]], [0, 0, 1])

    def test_next_tasks_are_free(self) -> None:
        started = {change["task"] for session in self.view["sessions"] if session["advice"] != "ended"
                   for change in session["changes"] if change["to"] in ("in_progress", "awaiting_review", "done")}
        started |= {tid for session in self.view["sessions"] for tid in session["inferred"]}
        self.assertFalse({task["id"] for task in self.view["next"]} & started)
        self.assertIn("FB-005", [task["id"] for task in self.view["next"]])  # only made ready: nobody took it

    def test_resume_and_no_machine_path(self) -> None:
        self.assertIn("1 done in main out of 7", self.view["resume"])
        dumped = json.dumps(self.view, ensure_ascii=False)
        for path in (str(self.repo.root), self.repo.root.as_posix(), Path(self.repo._tmp.name).name):
            with self.subTest(path=path):
                self.assertNotIn(path, dumped)
        self.assertIsNone(rules.MACHINE_PATH.search(dumped))
        self.assertNotIn(SLASHES + "?", dumped)


MARKER = """import pathlib, sys
pathlib.Path(sys.argv[1]).write_text("launched", encoding="utf-8")
if len(sys.argv) > 2:
    sys.stdout.write(sys.stdin.read())
"""


@unittest.skipIf(GIT is None, "git absent")
class LiveReadingTest(unittest.TestCase):
    """The live board reads the same collector again and again: nothing an earlier reading saw may stand in for what
    a session holds now."""

    def setUp(self) -> None:
        self.repo = Repository()
        self.addCleanup(self.repo.close)
        self.collector = collector_module.Collector(self.repo.root, roadmap_settings())
        self.tree = self.repo.trees / "fb-006-d-7a8b9c"
        self.later = NOW

    def session(self) -> dict:
        self.later += timedelta(seconds=10)
        return by_name(self.collector.snapshot(self.later))["fb-006-d-7a8b9c"]

    def test_a_failed_reading_never_stands_for_the_last_good_one(self) -> None:
        self.assertEqual(self.session()["advice"], "ended")
        (self.tree / "notes-not-committed.md").write_text("new work\n", encoding="utf-8")
        index = self.repo.root / ".git" / "worktrees" / "fb-006-d-7a8b9c" / "index"
        data = index.read_bytes()[:-20] + b"abcd" + bytes(4)  # an extension git does not know: it refuses the index
        index.write_bytes(data + hashlib.sha1(data).digest())
        session = self.session()
        self.assertEqual((session["reason"], session["files_read"]), ("read_failed", False))
        self.assertNotEqual(session["advice"], "ended")

    def test_ignore_rules_are_asked_again_at_every_reading(self) -> None:
        (self.tree / "work").mkdir()
        (self.tree / "work" / "notes.md").write_text("notes\n", encoding="utf-8")
        (self.tree / "work" / ".gitignore").write_text("*\n", encoding="utf-8")
        self.assertEqual((self.session()["untracked"], self.session()["advice"]), (0, "ended"))
        (self.tree / "work" / ".gitignore").write_text("# nothing ignored\n", encoding="utf-8")
        session = self.session()
        self.assertEqual(session["untracked"], 1)
        self.assertNotEqual(session["advice"], "ended")

    def test_a_folder_that_cannot_be_listed_keeps_a_session_from_ending(self) -> None:
        self.assertEqual(self.session()["advice"], "ended")
        real = os.scandir

        def scandir(path):
            if Path(os.fspath(path)) == self.tree:
                raise PermissionError(13, "Access is denied", os.fspath(path))
            return real(path)

        with mock.patch.object(files.os, "scandir", side_effect=scandir):
            session = self.session()
        self.assertEqual((session["files_issue"], session["files_read"]), ("folder_unlisted", False))
        self.assertNotEqual(session["advice"], "ended")

    def test_an_index_too_big_to_check_lists_nothing_and_says_so(self) -> None:
        (self.tree / "notes-not-committed.md").write_text("new work\n", encoding="utf-8")
        with mock.patch.object(files, "MAX_INDEX_BYTES", 100):
            session = self.session()
        self.assertEqual((session["files_issue"], session["files_read"], session["untracked"]),
                         ("index_too_big", False, 0))
        self.assertIn("new files are not listed either", session["files_issue_text"])


@unittest.skipIf(GIT is None, "git absent")
class SafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repository(extra=False)
        self.addCleanup(self.repo.close)
        self.a = self.repo.worktree("fb-001-a-1b2c3d", "claude/fb-001-a-1b2c3d", "main")
        (self.a / ".gitattributes").write_text("*.txt filter=probe diff=probe\n", encoding="utf-8")
        (self.a / "note.txt").write_text("a note\n", encoding="utf-8")
        self.repo.commit({**MAIN, "FB-001": "in_progress"}, "feat: FB-001", "2026-11-07T11:00:00-05:00", where=self.a)
        self._marks = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._marks.cleanup)
        self.marks = Path(self._marks.name).resolve()

    def arm(self) -> None:
        """Programs a careless read would start: a clean filter, an fsmonitor hook, an index hook, a textconv and an
        external diff, all named by the repository's own configuration."""
        script = self.marks / "probe.py"
        script.write_text(MARKER, encoding="utf-8")
        run = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
        hooks = self.marks / "hooks"
        hooks.mkdir()
        for name in ("post-index-change", "fsmonitor", "gpg"):
            hook = hooks / name
            hook.write_text(f"#!/bin/sh\n{run} \"{(self.marks / name).as_posix()}\"\n", encoding="utf-8", newline="\n")
            hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
        attributes = hooks / "attributes"
        attributes.write_text("*.md filter=other\n", encoding="utf-8")
        for key, value in (("filter.probe.clean", f'{run} "{(self.marks / "clean").as_posix()}" pass'),
                           ("filter.other.clean", f'{run} "{(self.marks / "attributesfile").as_posix()}" pass'),
                           ("core.attributesFile", attributes.as_posix()),
                           ("diff.probe.textconv", f'{run} "{(self.marks / "textconv").as_posix()}"'),
                           ("diff.external", f'{run} "{(self.marks / "external").as_posix()}"'),
                           ("core.fsmonitor", (hooks / "fsmonitor").as_posix()),
                           ("core.hooksPath", hooks.as_posix()), ("gpg.program", (hooks / "gpg").as_posix()),
                           ("log.showSignature", "true")):
            self.repo.git("config", key, value)
        (self.a / "note.md").write_text("another note\n", encoding="utf-8")
        self.repo.git("add", "-A", where=self.a)
        self.repo.git("-c", "core.attributesFile=", "commit", "-q", "-m", "docs: a note", where=self.a)
        self.sign("claude/fb-001-a-1b2c3d")
        self.clear()
        self.touch()

    def sign(self, branch: str) -> None:
        """A signature header on the branch's tip: git log checks it with gpg.program when log.showSignature is
        true."""
        tip = self.repo.sha(branch)
        raw = subprocess.run([GIT, "-C", str(self.repo.root), "cat-file", "commit", tip], capture_output=True,
                             check=True).stdout
        head, blank, body = raw.partition(b"\n\n")
        signature = b"\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n =abcd\n -----END PGP SIGNATURE-----"
        signed = head + signature + blank + body
        new = subprocess.run([GIT, "-C", str(self.repo.root), "hash-object", "-t", "commit", "-w", "--stdin"],
                             input=signed, capture_output=True, check=True).stdout.decode("ascii").strip()
        self.repo.git("update-ref", f"refs/heads/{branch}", new, tip)

    def clear(self) -> None:
        for path in self.marks.iterdir():
            if path.is_file() and path.suffix != ".py":
                path.unlink()

    def touch(self) -> None:
        later = NOW + timedelta(seconds=int.from_bytes(os.urandom(2), "big") % 500 + 10)
        for name in ("note.txt", "note.md"):
            if (self.a / name).exists():
                os.utime(self.a / name, (later.timestamp(), later.timestamp()))

    def fired(self) -> list[str]:
        return sorted(path.name for path in self.marks.iterdir() if path.is_file() and path.suffix != ".py")

    def test_no_program_starts_and_nothing_is_written(self) -> None:
        self.arm()
        subprocess.run([GIT, "-C", str(self.a), "status", "--porcelain"], capture_output=True, check=False)
        self.assertIn("clean", self.fired(), "the trap must fire with an ordinary git")
        self.assertIn("attributesfile", self.fired(), "the attributes file too")
        subprocess.run([GIT, "-C", str(self.a), "log", "-n1", "--format=%H"], capture_output=True, check=False)
        self.assertIn("gpg", self.fired(), "and the signature program")
        self.clear()
        self.touch()  # the ordinary git refreshed the index: the file must look changed again
        before = tree(self.repo.root)
        view = read(self.repo.root)
        self.assertEqual(self.fired(), [])
        self.assertEqual(tree(self.repo.root), before)
        self.assertFalse(list(self.repo.root.rglob("index.lock")))
        self.assertEqual(by_name(view)["fb-001-a-1b2c3d"]["changes"][0]["task"], "FB-001")

    def test_planted_repository_attributes_stop_the_file_reads(self) -> None:
        self.arm()
        info = self.repo.root / ".git" / "info"
        (info / "attributes").write_text("*.txt filter=probe\n", encoding="utf-8")
        self.touch()
        view = read(self.repo.root)
        self.assertEqual(self.fired(), [])
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertFalse(session["files_read"])
        self.assertIn(session["activity"], ("active", "unknown"))  # never called quiet: it may be writing
        self.assertIn("files", [source["key"] for source in view["sources"]])
        self.assertIn("some modified files are not read", cli.resume_text(view))

    def test_every_configured_filter_is_switched_off(self) -> None:
        self.arm()
        (self.repo.root / ".git" / "info" / "attributes").write_text("*.txt filter=probe\n", encoding="utf-8")
        self.touch()
        with mock.patch.object(files, "attributes_planted", return_value=False):  # a race the check missed
            view = read(self.repo.root)
        self.assertEqual(self.fired(), [])
        self.assertTrue(by_name(view)["fb-001-a-1b2c3d"]["files_read"])

    def test_a_filter_with_an_odd_name_stops_the_file_reads(self) -> None:
        self.repo.git("config", "filter.a.b.clean", "nothing")
        view = read(self.repo.root)
        self.assertFalse(by_name(view)["fb-001-a-1b2c3d"]["files_read"])
        self.assertIn("files", [source["key"] for source in view["sources"]])

    def worktree_status(self) -> tuple[dict, list[str]]:
        """A reading, and the worktrees git status ran in."""
        trees: list[str] = []
        real = subprocess.run

        def spy(command, *args, **kwargs):
            if "status" in command:
                trees.append(next(part for part in command if part.startswith("--work-tree=")))
            return real(command, *args, **kwargs)

        with mock.patch.object(gitreads.subprocess, "run", side_effect=spy):
            view = read(self.repo.root)
        return view, trees

    def test_a_tracked_file_turned_folder_keeps_git_status_away(self) -> None:
        (self.a / "note.txt").unlink()
        (self.a / "note.txt").mkdir()
        (self.a / "note.txt" / ".git").write_text("gitdir: " + SLASHES + "host.invalid/share/x\n", encoding="utf-8")
        view, trees = self.worktree_status()
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertEqual((session["files_read"], session["files_issue"]), (False, "tracked_replaced"))
        self.assertFalse([path for path in trees if path.endswith("fb-001-a-1b2c3d")])
        self.assertEqual(len(trees), 2)  # the main checkout and the other worktree are read as usual
        self.assertIn("files", [source["key"] for source in view["sources"]])

    def test_a_staged_gitlink_holding_a_git_keeps_git_status_away(self) -> None:
        self.repo.git("update-index", "--add", "--cacheinfo", f"160000,{self.repo.main},sub", where=self.a)
        (self.a / "sub").mkdir()
        (self.a / "sub" / ".git").write_text("gitdir: " + SLASHES + "host.invalid/share/x\n", encoding="utf-8")
        view, trees = self.worktree_status()
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertEqual((session["files_read"], session["files_issue"]), (False, "submodule_git"))
        self.assertFalse([path for path in trees if path.endswith("fb-001-a-1b2c3d")])

    def test_a_nested_git_file_is_never_followed(self) -> None:
        nested = self.a / "sub-repo"
        nested.mkdir()
        (nested / ".git").write_text("gitdir: " + SLASHES + "host.invalid/share/x\n", encoding="utf-8")
        (self.a / "new.py").write_text("x", encoding="utf-8")
        seen: list[str] = []
        calls: list[tuple[list[str], bytes]] = []
        real_lstat, real_open, real_scandir, real_run = os.lstat, open, os.scandir, subprocess.run

        def spy_path(real):
            def spy(path, *args, **kwargs):
                seen.append(str(path))
                return real(path, *args, **kwargs)
            return spy

        def spy_run(command, *args, **kwargs):
            calls.append((list(command), kwargs.get("input") or b""))
            return real_run(command, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=spy_path(real_lstat)), \
                mock.patch.object(files.os, "scandir", side_effect=spy_path(real_scandir)), \
                mock.patch("builtins.open", side_effect=spy_path(real_open)), \
                mock.patch.object(gitreads.subprocess, "run", side_effect=spy_run):
            session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertFalse([path for path in seen if path.startswith((SLASHES, BACKSLASHES))])
        self.assertFalse([path for path in seen if Path(path).name == ".git" and "sub-repo" in path
                          and not path.endswith(".git")])
        self.assertFalse([command for command, _ in calls if "--untracked-files=all" in command])
        self.assertFalse([stdin for command, stdin in calls if b"sub-repo" in stdin])
        self.assertEqual(session["untracked"], 2)  # sub-repo/ and new.py, counted, never handed to git

    def test_an_ignored_new_file_is_not_counted(self) -> None:
        (self.a / "out").mkdir()
        (self.a / "out" / "page.html").write_text("x", encoding="utf-8")
        (self.a / "new.py").write_text("x", encoding="utf-8")
        session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertEqual((session["untracked"], session["stage"]), (1, "uncommitted"))

    def test_a_new_folder_ignored_deep_down_is_not_counted(self) -> None:
        exclude = self.repo.root / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "*.pyc\ncaches/\n", encoding="utf-8")
        (self.a / "tools" / "a").mkdir(parents=True)
        (self.a / "tools" / "a" / "x.pyc").write_text("x", encoding="utf-8")
        (self.a / "package" / "sub" / "__pycache__").mkdir(parents=True)
        (self.a / "package" / "sub" / "__pycache__" / "m.pyc").write_text("x", encoding="utf-8")
        (self.a / "box" / "caches" / "sealed").mkdir(parents=True)
        (self.a / "box" / "caches" / "sealed" / ".git").write_text("gitdir: " + SLASHES + "host.invalid/x\n",
                                                                    encoding="utf-8")
        feeds: list[bytes] = []
        real = subprocess.run

        def spy(command, *args, **kwargs):
            feeds.append(kwargs.get("input") or b"")
            return real(command, *args, **kwargs)

        with mock.patch.object(gitreads.subprocess, "run", side_effect=spy):
            session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertEqual(session["untracked"], 0)
        self.assertFalse([feed for feed in feeds if b"sealed" in feed])  # the sealed folder is never named to git

    def test_odd_admin_files_keep_git_away(self) -> None:
        admin = self.repo.root / ".git" / "worktrees" / "fb-001-a-1b2c3d"
        (admin / "commondir").write_text(SLASHES + "host.invalid/share/x\n", encoding="utf-8")
        calls = []
        real = subprocess.run

        def spy(command, *args, **kwargs):
            calls.append(list(command))
            return real(command, *args, **kwargs)

        with mock.patch.object(gitreads.subprocess, "run", side_effect=spy):
            view = read(self.repo.root)
        self.assertFalse([command for command in calls if any(str(admin) in part for part in command)])
        sessions = by_name(view)
        session = sessions["fb-001-a-1b2c3d"]  # still shown, by its folder's name, and never read
        self.assertEqual((session["kind"], session["reason"], session["files_read"], session["overlay"]),
                         ("worktree", "odd_admin", False, False))
        self.assertNotIn("claude/fb-001-a-1b2c3d", sessions)  # one session, one card
        self.assertIn("files", [source["key"] for source in view["sources"]])

    def test_an_unknown_head_breaks_only_its_worktree(self) -> None:
        admin = self.repo.root / ".git" / "worktrees" / "fb-001-a-1b2c3d"
        (admin / "HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        view = read(self.repo.root)
        self.assertEqual(view["main"]["state"], "ok")
        sessions = by_name(view)
        self.assertEqual(sessions["fb-001-a-1b2c3d"]["reason"], "unknown_commit")
        self.assertEqual(sessions["fb-006-d-7a8b9c"]["advice"], "ended")

    def test_a_failed_read_is_tried_again(self) -> None:
        collector = collector_module.Collector(self.repo.root, roadmap_settings())
        real = collector.git.ledgers
        with mock.patch.object(collector.git, "ledgers", side_effect=gitreads.GitFailed("TimeoutExpired")):
            self.assertEqual(collector.snapshot(NOW)["main"]["state"], "unreadable")
        with mock.patch.object(collector.git, "ledgers", side_effect=real):
            view = collector.snapshot(NOW + timedelta(seconds=20))
        self.assertEqual(view["main"]["state"], "ok")
        self.assertEqual(len(view["history"]), 3)

    def test_a_branch_with_odd_sections_stops_only_itself(self) -> None:
        self.repo.branch("claude/broken", {**MAIN, "FB-004": "in_progress"}, "docs: broken", "2026-11-07T11:40:00-05:00")
        tree_ = self.repo.worktree("tmp-broken", None, "claude/broken")
        raw = json.loads((tree_ / "data" / "roadmap.json").read_text(encoding="utf-8"))
        raw["decisions"] = 1
        (tree_ / "data" / "roadmap.json").write_text(json.dumps(raw), encoding="utf-8")
        self.repo.git("add", "-A", where=tree_)
        self.repo.git("commit", "-q", "-m", "docs: broken decisions", where=tree_)
        self.repo.git("worktree", "remove", "--force", str(tree_))
        self.repo.branch("claude/fb-004-good", {**MAIN, "FB-004": "awaiting_review"}, "feat: FB-004 delivered",
                         "2026-11-07T11:00:00-05:00")
        sessions = by_name(read(self.repo.root))
        self.assertEqual(sessions["claude/broken"]["ledger"], "unreadable")
        self.assertEqual([c["task"] for c in sessions["claude/fb-004-good"]["changes"]], ["FB-004"])

    def test_merged_branches_never_hide_unmerged_ones(self) -> None:
        self.repo.branch("claude/fb-004-c", {**MAIN, "FB-004": "awaiting_review"}, "feat: FB-004",
                         "2026-11-07T06:00:00-05:00")
        for index in range(Settings().max_branches + 2):
            self.repo.git("branch", f"claude/done-{index:02d}", "main")
        view = read(self.repo.root)
        self.assertIn("claude/fb-004-c", by_name(view))
        self.assertEqual(view["limits"]["branches_cut"], 0)

    def test_a_session_folder_reads_the_main_checkout(self) -> None:
        view = read(self.a)
        self.assertEqual(view["main"]["state"], "ok")
        self.assertIn("demo", by_name(view))
        self.assertEqual(view["repository"], "demo")

    def test_a_committed_change_is_dated_by_its_own_commit(self) -> None:
        self.repo.git("branch", "claude/fb-004-e", "main")
        tree_ = self.repo.worktree("tmp-e", None, "claude/fb-004-e")
        self.repo.commit({**MAIN, "FB-004": "in_progress"}, "feat: FB-004 started", "2026-11-07T07:00:00-05:00",
                         where=tree_)
        first = self.repo.sha("HEAD", where=tree_)
        (tree_ / "code.py").write_text("x", encoding="utf-8")
        self.repo.git("add", "-A", where=tree_)
        self.repo.git("commit", "-q", "-m", "feat: some code", where=tree_,
                      env=self.repo.dated("2026-11-07T11:00:00-05:00"))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        change = by_name(read(self.repo.root))["claude/fb-004-e"]["changes"][0]
        self.assertEqual((change["sha"], change["at"], change["approx"]),
                         (first[:7], "2026-11-07T07:00:00-05:00", False))

    def test_a_move_beyond_the_commits_read_is_approximate(self) -> None:
        self.repo.git("branch", "claude/fb-004-f", "main")
        tree_ = self.repo.worktree("tmp-f", None, "claude/fb-004-f")
        self.repo.commit({**MAIN, "FB-004": "in_progress"}, "feat: FB-004 started", "2026-11-06T08:00:00-05:00",
                         where=tree_)
        for index in range(gitreads.MAX_COMMITS + 1):
            (tree_ / f"code{index}.py").write_text("x", encoding="utf-8")
            self.repo.git("add", "-A", where=tree_)
            self.repo.git("commit", "-q", "-m", f"feat: code {index}", where=tree_,
                          env=self.repo.dated(f"2026-11-07T0{index}:30:00-05:00"))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        change = by_name(read(self.repo.root))["claude/fb-004-f"]["changes"][0]
        self.assertEqual((change["task"], change["approx"]), ("FB-004", True))

    def test_a_branch_carried_further_on_origin_is_one_session(self) -> None:
        self.repo.branch("claude/fb-004-c", {**MAIN, "FB-004": "in_progress"}, "feat: FB-004",
                         "2026-11-07T09:00:00-05:00")
        local = self.repo.sha("claude/fb-004-c")
        tree_ = self.repo.worktree("tmp-c", None, "claude/fb-004-c")
        self.repo.commit({**MAIN, "FB-004": "awaiting_review"}, "feat: FB-004 delivered", "2026-11-07T10:00:00-05:00",
                         where=tree_)
        self.repo.git("update-ref", "refs/remotes/origin/claude/fb-004-c", self.repo.sha("HEAD", where=tree_))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        self.repo.git("update-ref", "refs/heads/claude/fb-004-c", local)  # the session went on in the cloud
        view = read(self.repo.root)
        self.assertEqual([c["name"] for c in view["sessions"] if "fb-004-c" in c["name"]], ["claude/fb-004-c"])
        session = by_name(view)["claude/fb-004-c"]
        self.assertEqual([(c["task"], c["to"]) for c in session["changes"]], [("FB-004", "awaiting_review")])
        self.assertEqual((view["tasks"]["FB-004"]["status"], view["kpis"]["conflicts"]), ("awaiting_review", 0))

    def test_a_worktree_git_file_neither_redirects_nor_hides_it(self) -> None:
        (self.a / ".git").unlink()
        (self.a / "data" / "roadmap.json").write_text(json.dumps({"tasks": "nothing"}), encoding="utf-8")
        session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertEqual(session["branch"], "claude/fb-001-a-1b2c3d")
        self.assertEqual(session["ledger"], "writing")
        self.assertEqual([c["task"] for c in session["changes"]], ["FB-001"])

    def test_a_worktree_outside_the_read_folders_is_never_touched(self) -> None:
        outside = Path(self._marks.name).resolve() / "outside-tree"
        self.repo.git("worktree", "add", "-q", "-b", "claude/outside", str(outside), "main")
        self.repo.commit({**MAIN, "FB-004": "in_progress"}, "feat: outside", "2026-11-07T11:10:00-05:00",
                         where=outside)
        seen: list[str] = []
        real_lstat, real_open = os.lstat, open

        def spy_lstat(path, *args, **kwargs):
            seen.append(str(path))
            return real_lstat(path, *args, **kwargs)

        def spy_open(path, *args, **kwargs):
            seen.append(str(path))
            return real_open(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=spy_lstat), \
                mock.patch("builtins.open", side_effect=spy_open):
            view = read(self.repo.root)
        self.assertFalse([path for path in seen if path.startswith(str(outside))])
        session = by_name(view)["outside-tree"]
        self.assertEqual((session["kind"], session["branch"], session["reason"]),
                         ("worktree", "claude/outside", "outside"))
        self.assertFalse(session["overlay"])

    def test_hostile_names_and_subjects_stay_data(self) -> None:
        self.repo.branch("claude/x'y&z", {**MAIN, "FB-004": "in_progress"}, HOSTILE, "2026-11-07T11:20:00-05:00")
        view = read(self.repo.root)
        session = by_name(view)[text.UNUSUAL_BRANCH]
        self.assertNotIn("\u202e", session["subject"])
        self.assertIn("</script>", session["subject"])  # kept as text: the page escapes it

    def test_a_ledger_mid_write_is_read_at_the_last_commit(self) -> None:
        (self.a / "data" / "roadmap.json").write_text('{"tasks": [', encoding="utf-8")
        session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertEqual((session["ledger"], [c["task"] for c in session["changes"]]), ("writing", ["FB-001"]))

    def test_one_broken_session_never_stops_the_others(self) -> None:
        real = files.read_ledger

        def broken(path, root, parts):
            if Path(path).name == "fb-001-a-1b2c3d":
                raise RuntimeError("failure")
            return real(path, root, parts)

        with mock.patch.object(files, "read_ledger", side_effect=broken):
            view = read(self.repo.root)
        sessions = by_name(view)
        self.assertEqual((sessions["fb-001-a-1b2c3d"]["reason"], sessions["fb-001-a-1b2c3d"]["reason_text"]),
                         ("read_failed", "reading failed (RuntimeError)"))
        self.assertEqual(sessions["fb-006-d-7a8b9c"]["advice"], "ended")

    def test_git_runs_fixed_reads_with_a_small_environment(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), git_starts() as starts:
            read(self.repo.root)
        calls = [(command, kwargs.get("env") or {}, kwargs) for command, kwargs in starts]
        outside = [(command, env, kwargs) for command, env, kwargs in calls if reads_config_bytes(command, env)]
        self.assertTrue(outside)  # the configuration, read by git from its bytes
        for command, env, kwargs in outside:
            with self.subTest(command=command[1:4]):
                self.assertTrue(Path(command[0]).is_absolute())
                self.assertEqual(kwargs.get("stdin"), subprocess.PIPE)  # its bytes, never its path ("-")
                self.assertEqual(Path(kwargs.get("cwd")), Path(command[0]).parent)  # git's own folder, no repository
                self.assertEqual((env.get("GIT_CONFIG_NOSYSTEM"), env.get("GIT_CONFIG_GLOBAL")), ("1", os.devnull))
                self.assertNotIn("ANTHROPIC_API_KEY", env)
        inside = [(command, env) for command, env, _ in calls if not reads_config_bytes(command, env)]
        self.assertTrue(inside)
        for command, env in inside:
            with self.subTest(command=command[1:4]):
                self.assertTrue(Path(command[0]).is_absolute())
                self.assertTrue(command[1].startswith("--git-dir="))
                verb = next(part for part in command if part in gitreads.VERBS)
                if verb != "version":  # git version reads no attribute: an older git can then say how old it is
                    self.assertIn("--attr-source=" + gitreads.EMPTY_TREE, command)
                self.assertIn("core.fsmonitor=false", command)
                self.assertNotIn("-C", command)
                self.assertEqual(env.get("GIT_OPTIONAL_LOCKS"), "0")
                self.assertEqual(env.get("GIT_NO_REPLACE_OBJECTS"), "1")
                self.assertEqual(env.get("GIT_NO_LAZY_FETCH"), "1")
                self.assertEqual(env.get("GIT_GRAFT_FILE"), os.devnull)
                for setting in ("log.mailmap=false", "core.useReplaceRefs=false", "core.attributesFile=",
                                "core.excludesFile=", f"diff.orderFile={os.devnull}", "log.follow=false",
                                "core.multiPackIndex=false", "core.warnAmbiguousRefs=false", "status.showStash=false",
                                "index.sparse=false", "index.threads=1", "core.longpaths=false",
                                "log.showSignature=false"):
                    self.assertIn(setting, command)
                if verb != "version":  # no chain of commit-graphs here: git reads the commit-graph
                    self.assertNotIn("core.commitGraph=false", command)
                # the commands that read index names the board has not checked yet never look them up on disk
                self.assertEqual("core.sparseCheckout=false" in command, verb in ("ls-files", "check-ignore"))
                self.assertNotIn("-g", command)  # the reflogs are read by the board, never by git
                self.assertNotIn("ANTHROPIC_API_KEY", env)
                self.assertNotEqual(verb, "diff")

    def test_cached_reads_are_reused(self) -> None:
        collector = collector_module.Collector(self.repo.root, roadmap_settings())
        collector.snapshot(NOW)
        with git_starts() as starts:
            collector.snapshot(NOW + timedelta(seconds=20))
        verbs = [next(part for part in command if part in gitreads.VERBS) for command, _ in starts]
        self.assertEqual(sorted(set(verbs)), ["config", "for-each-ref", "ls-files", "status"])
        # the configuration's bytes and the filter drivers, two listings of refs, and per worktree its index (read
        # again: a session can rewrite it in place and put its size and time back) and its status
        self.assertEqual(len(verbs), 2 + 2 + 2 * 3)

    def test_a_reading_never_inherits_the_last_one_filters(self) -> None:
        collector = collector_module.Collector(self.repo.root, roadmap_settings())
        collector.git.blank = ("-c", "x.y=" + "z" * 40_000)  # what a huge configuration left behind
        self.assertEqual(collector.snapshot(NOW)["main"]["state"], "ok")

    def test_too_many_filter_drivers_stop_the_file_reads(self) -> None:
        self.repo.git("config", "filter.probe.clean", "nothing")
        with mock.patch.object(gitreads, "MAX_FILTERS", 0):
            view = read(self.repo.root)
        self.assertFalse(by_name(view)["fb-001-a-1b2c3d"]["files_read"])
        self.assertIn("files", [source["key"] for source in view["sources"]])

    def test_an_index_past_the_cap_keeps_git_status_away(self) -> None:
        with mock.patch.object(gitreads, "MAX_STAGED", 2):
            view, trees = self.worktree_status()
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertEqual((session["files_read"], session["files_issue"], session["files_issue_text"]),
                         (False, "too_many_tracked", "more than 2 tracked files: too many to check"))
        self.assertFalse([path for path in trees if path.endswith("fb-001-a-1b2c3d")])

    def test_odd_names_in_an_index_never_lead_outside(self) -> None:
        seen: list[str] = []
        real = os.scandir

        def spy(path):
            seen.append(str(path))
            return real(path)

        odd = [("100644", "../../../../neighbour/x.md"), ("100644", "/x"), ("100644", "note.txt")]
        with mock.patch.object(gitreads.Git, "staged", return_value=odd), \
                mock.patch.object(files.os, "scandir", side_effect=spy):
            view = read(self.repo.root)  # "/x" once looped for ever
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertEqual((session["files_read"], session["files_issue"]), (False, "odd_tracked_path"))
        root = os.path.normcase(str(self.repo.root))
        self.assertFalse([path for path in seen if not os.path.normcase(os.path.abspath(path)).startswith(root)])

    def test_a_trap_in_git_stops_every_git_command_on_the_repository(self) -> None:
        config = self.repo.root / ".git" / "config"
        config.write_text(config.read_text(encoding="utf-8") + "[include]\n\tpath = " + SLASHES
                          + "host.invalid/share/x\n", encoding="utf-8")
        with git_starts() as starts:
            view = read(self.repo.root)
        self.assertTrue(starts)  # git read the configuration's bytes, and ran nothing on the repository
        self.assertEqual([command for command, kwargs in starts if not reads_config_bytes(command, kwargs.get("env"))],
                         [])
        self.assertEqual((view["main"]["state"], view["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("a configuration include", view["main"]["reason_text"])

    def test_a_submodule_folder_without_git_keeps_its_session_readable(self) -> None:
        self.repo.git("update-index", "--add", "--cacheinfo", f"160000,{self.repo.main},vendor", where=self.a)
        (self.a / "vendor").mkdir()
        (self.a / "vendor" / "lib.py").write_text("x", encoding="utf-8")
        session = by_name(read(self.repo.root))["fb-001-a-1b2c3d"]
        self.assertNotEqual(session["reason"], "read_failed")
        self.assertEqual([change["task"] for change in session["changes"]], ["FB-001"])

    def test_a_gone_folder_is_said_gone_and_not_counted(self) -> None:
        before = read(self.repo.root)["kpis"]["sessions"]
        shutil.rmtree(self.a)
        view = read(self.repo.root)
        session = by_name(view)["fb-001-a-1b2c3d"]
        self.assertEqual((session["reason"], session["advice"], session["gone"]), ("gone", "gone", True))
        self.assertEqual(view["kpis"]["sessions"], before - 1)
        self.assertNotIn("files", [source["key"] for source in view["sources"]])

    def test_a_refused_session_folder_still_reads_its_repository(self) -> None:
        admin = self.repo.root / ".git" / "worktrees" / "fb-001-a-1b2c3d"
        (admin / "config.worktree").write_text("[core]\n\thooksPath = x\n", encoding="utf-8")
        view = read(self.a)
        self.assertEqual(by_name(view)["fb-001-a-1b2c3d"]["reason"], "odd_admin")
        self.assertEqual(view["main"]["state"], "ok")

    def test_a_merged_branch_carried_further_on_origin_shows_origin(self) -> None:
        self.repo.branch("claude/fb-004-c", {**MAIN, "FB-004": "in_progress"}, "feat: FB-004",
                         "2026-11-07T09:00:00-05:00")
        tree_ = self.repo.worktree("tmp-c", None, "claude/fb-004-c")
        self.repo.commit({**MAIN, "FB-004": "awaiting_review"}, "feat: FB-004 delivered", "2026-11-07T10:00:00-05:00",
                         where=tree_)
        self.repo.git("update-ref", "refs/remotes/origin/claude/fb-004-c", self.repo.sha("HEAD", where=tree_))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        self.repo.git("update-ref", "refs/heads/claude/fb-004-c", self.repo.main)  # the local copy: all in main
        view = read(self.repo.root)
        self.assertIn("origin/claude/fb-004-c", by_name(view))
        self.assertEqual(view["tasks"]["FB-004"]["status"], "awaiting_review")

    def test_a_worktree_on_a_merged_branch_origin_carried_further(self) -> None:
        self.repo.git("branch", "claude/tmp-x", "claude/fb-006-d")
        tree_ = self.repo.worktree("tmp-x", None, "claude/tmp-x")
        self.repo.commit({**MAIN, "FB-004": "in_progress"}, "feat: FB-004", "2026-11-07T10:00:00-05:00", where=tree_)
        self.repo.git("update-ref", "refs/remotes/origin/claude/fb-006-d", self.repo.sha("HEAD", where=tree_))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        self.repo.git("branch", "-D", "claude/tmp-x")
        sessions = by_name(read(self.repo.root))
        self.assertEqual((sessions["fb-006-d-7a8b9c"]["stage"], sessions["fb-006-d-7a8b9c"]["advice"]),
                         ("behind_origin", "open"))  # never "merged" nor "ended" while origin holds more
        self.assertIn("origin/claude/fb-006-d", sessions)

    def test_a_branch_read_at_origin_is_dated_by_origin(self) -> None:
        self.repo.branch("claude/fb-004-v", {**MAIN, "FB-004": "in_progress"}, "feat: FB-004",
                         "2026-10-10T09:00:00-05:00")
        local = self.repo.sha("claude/fb-004-v")
        tree_ = self.repo.worktree("tmp-v", None, "claude/fb-004-v")
        self.repo.commit({**MAIN, "FB-004": "awaiting_review"}, "feat: FB-004 delivered", "2026-11-07T10:00:00-05:00",
                         where=tree_)
        self.repo.git("update-ref", "refs/remotes/origin/claude/fb-004-v", self.repo.sha("HEAD", where=tree_))
        self.repo.git("worktree", "remove", "--force", str(tree_))
        self.repo.git("update-ref", "refs/heads/claude/fb-004-v", local)  # quiet here for weeks, busy on origin
        session = by_name(read(self.repo.root))["claude/fb-004-v"]
        self.assertEqual((session["stale"], session["reason"]), (False, ""))

    def test_missing_git_or_no_repository(self) -> None:
        with mock.patch.object(gitreads, "git_executable", return_value=None):
            view = read(self.repo.root)
        self.assertEqual((view["main"]["state"], view["sessions"]), ("unreadable", []))
        self.assertEqual(next(s for s in view["sources"] if s["key"] == "git")["state"], "unreadable")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(read(Path(folder))["main"]["state"], "unreadable")


if __name__ == "__main__":
    unittest.main()
