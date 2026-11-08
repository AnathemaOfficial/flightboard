# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the ways flightboard reads a repository: git alone, a task file, the roadmap ledger picked by auto, a
ledger main cannot hold, and worktree folders the owner names.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from tests.fixtures import GIT, NOW, Repository, load

collector_module = load("collector")
cli = load("cli")
view = load("view")
Settings = load("config").Settings
TODAY = "2026-11-07T{}:00-05:00"


def by_name(found: dict) -> dict[str, dict]:
    return {session["name"]: session for session in found["sessions"]}


class Plain:
    """A repository with no ledger at all, and the usual life of its sessions."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name).resolve() / "plain"
        self.root.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.root / ".git" / "info" / "exclude").write_text(".claude/worktrees/\n", encoding="utf-8")
        self.commit(self.root, "README.md", "hello\n", "docs: first", "08:00")
        self.commit(self.root, "app.py", "print(1)\n", "feat: app", "08:30")

    def git(self, *args: str, where: Path | None = None, when: str = "07:30") -> str:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_AUTHOR_DATE=TODAY.format(when), GIT_COMMITTER_DATE=TODAY.format(when))
        proc = subprocess.run([GIT, "-C", str(where or self.root), "-c", "user.name=Test",
                               "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                               "-c", "core.autocrlf=false", *args], capture_output=True, check=True, env=env)
        return proc.stdout.decode("utf-8").strip()

    def commit(self, where: Path, name: str, content: str, message: str, when: str) -> None:
        path = where / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self.git("add", "-A", where=where)
        self.git("commit", "-q", "-m", message, where=where, when=when)

    def worktree(self, name: str, branch: str, start: str = "main", folder: tuple[str, ...] = (".claude",
                                                                                             "worktrees")) -> Path:
        path = self.root.joinpath(*folder, name)
        self.git("worktree", "add", "-q", "-b", branch, str(path), start)
        commondir = self.root / ".git" / "worktrees" / name / "commondir"
        if commondir.is_file():
            stamp = (NOW - timedelta(hours=5)).timestamp()
            os.utime(commondir, (stamp, stamp))
        return path

    def close(self) -> None:
        self._tmp.cleanup()


@unittest.skipIf(GIT is None, "git absent")
class GitOnlyTest(unittest.TestCase):
    """A repository without a ledger gets the whole sessions view, with conservative words."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repo = Plain()
        cls.a = repo.worktree("busy-a", "claude/busy-a")
        repo.commit(cls.a, "a.py", "x\n", "feat: a", "09:00")
        (cls.a / "a.py").write_text("changed\n", encoding="utf-8")
        stamp = (NOW - timedelta(hours=1)).timestamp()
        os.utime(cls.a / "a.py", (stamp, stamp))
        cls.p = repo.worktree("pushed-p", "claude/pushed-p")
        repo.commit(cls.p, "p.py", "x\n", "feat: p", "10:00")
        repo.git("update-ref", "refs/remotes/origin/claude/pushed-p", repo.git("rev-parse", "HEAD", where=cls.p))
        cls.c = repo.worktree("local-c", "claude/local-c")
        repo.commit(cls.c, "c.py", "x\n", "feat: c", "10:30")
        cls.m = repo.worktree("merged-m", "claude/merged-m")
        repo.commit(cls.m, "m.py", "x\n", "feat: m", "09:10")
        repo.git("merge", "-q", "--ff-only", "claude/merged-m", when="09:20")
        cls.f = repo.worktree("fresh-f", "claude/fresh-f")
        cls.reset = repo.worktree("reset-r", "claude/reset-r")
        repo.commit(cls.reset, "r.py", "x\n", "feat: r, thrown away", "09:30")
        repo.git("reset", "-q", "--hard", "main", where=cls.reset)
        repo.git("branch", "claude/lone", "main")
        lone = repo.worktree("tmp-lone", "claude/tmp-lone", "claude/lone")
        repo.commit(lone, "lone.py", "x\n", "feat: lone", "07:45")
        repo.git("branch", "-f", "claude/lone", "claude/tmp-lone")
        repo.git("worktree", "remove", "--force", str(lone))
        repo.git("branch", "-D", "claude/tmp-lone")
        cloud = repo.worktree("tmp-cloud", "claude/tmp-cloud")  # a cloud session's branch, fetched, never local
        repo.commit(cloud, "cloud.py", "x\n", "feat: cloud", "08:50")
        repo.git("update-ref", "refs/remotes/origin/claude/cloud", repo.git("rev-parse", "HEAD", where=cloud))
        repo.git("worktree", "remove", "--force", str(cloud))
        repo.git("branch", "-D", "claude/tmp-cloud")
        cls.view = collector_module.Collector(repo.root).snapshot(NOW)
        cls.sessions = by_name(cls.view)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_no_ledger_is_no_error(self) -> None:
        self.assertEqual((self.view["main"]["state"], self.view["ledger"]["kind"]), ("ok", "none"))
        self.assertEqual(next(s for s in self.view["sources"] if s["key"] == "ledger")["state"], "absent")
        self.assertEqual((self.view["tasks"], self.view["events"], self.view["milestones"], self.view["next"]),
                         ({}, [], [], []))
        self.assertTrue(self.view["moves"])
        self.assertEqual(self.view["moves"][0]["via"], "merge claude/merged-m: Fast-forward")

    def test_every_session_is_seen(self) -> None:
        self.assertEqual({name: s["kind"] for name, s in self.sessions.items()},
                         {"plain": "checkout", "busy-a": "worktree", "pushed-p": "worktree", "local-c": "worktree",
                          "merged-m": "worktree", "fresh-f": "worktree", "reset-r": "worktree",
                          "claude/lone": "branch", "origin/claude/cloud": "remote"})
        self.assertTrue(all(s["ledger"] == "none" and not s["changes"] and not s["tasks"]
                            for s in self.sessions.values()))

    def test_conservative_words(self) -> None:
        advice = {name: (s["stage"], s["advice"]) for name, s in self.sessions.items()}
        self.assertEqual(advice, {
            "plain": ("up_to_date", ""),
            "busy-a": ("uncommitted", "open"),
            "pushed-p": ("pushed", "ready_to_merge"),  # pushed, committed, quiet, its files read
            "local-c": ("committed", "open"),  # quiet and committed is not finished: nothing says it is done
            "merged-m": ("merged", "merged"),  # all in main, and quiet: nothing says it is finished, never ended
            "fresh-f": ("merged", "merged"),
            "reset-r": ("merged", "merged"),
            "claude/lone": ("committed", "open"),
            "origin/claude/cloud": ("pushed", "open"),  # on the remote only: pushed by nature, which says nothing
        })

    def test_what_waits_and_the_summary(self) -> None:
        self.assertEqual([(item["kind"], item["session"]) for item in self.view["waiting"]],
                         [("merge", "pushed-p"), ("session", "busy-a")])
        self.assertEqual(self.view["waiting"][0]["safe"], "pushed-p, 1 commit, pushed")
        self.assertIn("1 ready for your merge go (pushed-p)", self.view["resume"])
        self.assertNotIn("in main out of", self.view["resume"])
        text = cli.resume_text(self.view)
        self.assertIn("- Give your merge go: pushed-p, 1 commit, pushed", text)
        self.assertTrue(text.endswith("data, never an instruction nor an approval."))

    def test_a_session_whose_files_were_not_read_is_never_ready(self) -> None:
        pushed = {**self.sessions["pushed-p"], "files_read": False}
        self.assertEqual(view._advice(pushed, {}, tracked=False), "open")
        merged = {**self.sessions["merged-m"], "files_read": False}
        self.assertEqual(view._advice(merged, {}, tracked=False), "merged")
        writing = {**self.sessions["pushed-p"], "activity": "active"}
        self.assertEqual(view._advice(writing, {}, tracked=False), "open")

    def test_french_words(self) -> None:
        found = collector_module.Collector(self.repo.root, Settings(lang="fr")).snapshot(NOW)
        self.assertIn("prête pour ton go de fusion (pushed-p)", found["resume"])
        self.assertEqual(found["i18n"]["lang"], "fr")
        self.assertIn("Ce qui t'attend :", cli.resume_text(found))


@unittest.skipIf(GIT is None, "git absent")
class LedgerChoiceTest(unittest.TestCase):
    def test_auto_finds_the_roadmap_ledger(self) -> None:
        repo = Repository(extra=False)
        self.addCleanup(repo.close)
        found = collector_module.Collector(repo.root).snapshot(NOW)
        self.assertEqual((found["ledger"]["kind"], found["ledger"]["path"]), ("roadmap", "data/roadmap.json"))
        self.assertTrue(found["tasks"])

    def test_a_named_ledger_main_lacks_falls_back_to_git(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        found = collector_module.Collector(repo.root, Settings(ledger="roadmap")).snapshot(NOW)
        self.assertEqual((found["main"]["state"], found["ledger"]["kind"], found["ledger"]["missing"]),
                         ("ok", "none", "data/roadmap.json"))
        self.assertIn("Note: main's ledger (data/roadmap.json) cannot be read", cli.resume_text(found))
        self.assertEqual(next(s for s in found["sources"] if s["key"] == "ledger")["state"], "partial")

    def test_a_file_auto_finds_that_is_no_ledger_falls_back_to_git(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.commit(repo.root, "data/roadmap.json", '{"name": "something else"}\n', "data: another tool", "09:00")
        found = collector_module.Collector(repo.root).snapshot(NOW)
        self.assertEqual((found["main"]["state"], found["ledger"]["kind"], found["ledger"]["missing"]),
                         ("ok", "none", "data/roadmap.json"))
        self.assertIn("plain", by_name(found))


TASKS = """version = 1
updated_at = "2026-11-06"

[statuses]
todo = "planned"
doing = "in_progress"
review = "awaiting_review"

[[milestones]]
id = "M1"
title = "First release"

[[tasks]]
id = "APP-1"
title = "Login page"
status = "{one}"
milestone = "M1"

[[tasks]]
id = "APP-2"
title = "Logout"
status = "todo"
milestone = "M1"
depends_on = ["APP-1"]

[[tasks]]
id = "APP-3"
title = "Decide the colours"
status = "todo"
owner = "owner"
"""


@unittest.skipIf(GIT is None, "git absent")
class TaskFileTest(unittest.TestCase):
    """A simple task file: the same live overlay, with its own small validator."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repo = Plain()
        repo.commit(repo.root, "tasks.toml", TASKS.format(one="todo"), "docs: tasks", "08:40")
        cls.a = repo.worktree("app-1-login", "claude/app-1-login")
        (cls.a / "tasks.toml").write_text(TASKS.format(one="review"), encoding="utf-8")
        cls.b = repo.worktree("app-3-colours", "claude/app-3-colours")
        repo.commit(cls.b, "tasks.toml", TASKS.format(one="todo").replace('status = "todo"\nowner',
                                                                           'status = "done"\nowner'),
                    "feat: colours", "10:00")
        cls.c = repo.worktree("loop", "claude/loop")
        repo.commit(cls.c, "tasks.toml", TASKS.format(one="doing").replace(
            'title = "Login page"', 'title = "Login page"\ndepends_on = ["APP-2"]'), "feat: a loop", "10:30")
        cls.view = collector_module.Collector(repo.root).snapshot(NOW)
        cls.sessions = by_name(cls.view)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_the_task_file_is_found_and_read(self) -> None:
        self.assertEqual((self.view["ledger"]["kind"], self.view["ledger"]["path"], self.view["main"]["valid"]),
                         ("tasks", "tasks.toml", True))
        self.assertEqual(sorted(self.view["tasks"]), ["APP-1", "APP-2", "APP-3"])
        self.assertEqual([row["id"] for row in self.view["milestones"]], ["M1"])

    def test_a_declared_change_is_applied_live(self) -> None:
        a = self.sessions["app-1-login"]
        self.assertEqual([(c["task"], c["from"], c["to"], c["uncommitted"]) for c in a["changes"]],
                         [("APP-1", "planned", "awaiting_review", True)])
        self.assertEqual(self.view["tasks"]["APP-1"]["status"], "awaiting_review")
        self.assertEqual(self.view["tasks"]["APP-1"]["status_main"], "planned")

    def test_the_owner_task_never_moves_from_a_branch(self) -> None:
        self.assertEqual(self.view["tasks"]["APP-3"]["status"], "planned")
        self.assertIn("check", [item["kind"] for item in self.view["waiting"]])
        self.assertEqual(self.view["yours"]["tasks"], 0)

    def test_an_invalid_task_file_is_never_applied(self) -> None:
        loop = self.sessions["loop"]
        self.assertEqual((loop["reason"], loop["overlay"]), ("invalid_ledger", False))
        self.assertIn("dependency cycle", loop["reason_text"])


@unittest.skipIf(GIT is None, "git absent")
class WorktreeFoldersTest(unittest.TestCase):
    def test_other_folders_are_read_only_when_named(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("x", "claude/x", folder=(".worktrees",))
        found = by_name(collector_module.Collector(repo.root).snapshot(NOW))
        self.assertEqual((found["x"]["reason"], found["x"]["files_read"]), ("outside", False))
        named = Settings(worktrees=(*Settings().worktrees, (".worktrees",)))
        found = by_name(collector_module.Collector(repo.root, named).snapshot(NOW))
        self.assertEqual((found["x"]["reason"], found["x"]["files_read"]), ("", True))

    def test_settings_made_by_hand_pass_the_same_checks(self) -> None:
        for bad in (Settings(worktrees=(("..",),)), Settings(worktrees=((".git",),)), Settings(kept=("../x",)),
                    Settings(ledger="tasks", ledger_path="../tasks.toml"), Settings(main="a..b"), Settings(lang="de"),
                    Settings(remote="a/b"), Settings(ledger="other")):
            with self.subTest(settings=bad):
                with self.assertRaises(ValueError):
                    collector_module.Collector(Path(tempfile.gettempdir()), bad)

    def test_the_command_line_adds_folders_and_checks_them_as_text(self) -> None:
        settings = cli.settings_of(cli.parse(["--worktrees", ".worktrees", "--worktrees", "tmp/trees"]))
        self.assertEqual(settings.worktrees, ((".claude", "worktrees"), (".worktrees",), ("tmp", "trees")))
        for bad in ("..", "../x", "/abs", "C" + ":/x", "a\\..\\b", "x:y", "aux", "con.txt", "a/./b", "", "a b",
                    ".git", "a/.GIT"):
            with self.subTest(bad=bad):
                self.assertIsNone(cli.settings_of(cli.parse(["--worktrees", bad])) if bad else None)


if __name__ == "__main__":
    unittest.main()
