# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Fixtures of flightboard's tests: valid roadmap ledgers and a demo repository with worktrees and branches.

The repository follows a common flow: a branch merges main, then main fast-forwards to it. Every ledger it holds
passes the roadmap rules, except where a test wants an invalid one.
"""
from __future__ import annotations

import contextlib
import copy
import functools
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "skills" / "flightboard" / "scripts" / "flightboard"
ENTRY = PACKAGE.parent / "flightboard.py"
GIT = shutil.which("git")
NOW = datetime.fromisoformat("2026-11-07T12:00:00-05:00")
HOSTILE = "</script><script>alert(1)</script><img src=x onerror=alert(2)>\u202e"
# the one git command the board runs outside any repository: a configuration's bytes, read on git's standard input
CONFIG_READ = ["config", "--file", "-", "--no-includes", "--null", "--list"]


def reads_config_bytes(command: list[str], env: dict | None) -> bool:
    """Whether this git run is the board's reading of a configuration's bytes, with no repository around it."""
    return list(command[1:]) == CONFIG_READ and (env or {}).get("GIT_DIR") == os.devnull


class Starts(list):
    """(command, Popen's keyword arguments) of each process started; .processes holds the processes themselves."""

    def __init__(self) -> None:
        super().__init__()
        self.processes: list[subprocess.Popen] = []


@contextlib.contextmanager
def git_starts(code: str | None = None):
    """Every process the board starts while the block runs, whether through subprocess.run or straight through Popen
    (the configuration's bytes are read so). With code, each one runs that Python code instead (a git that never
    reads its input, or one that fails at everything), with the board's own pipes, environment and folder."""
    starts = Starts()
    real = subprocess.Popen

    def spy(args, *rest, **kwargs):
        proc = real(list(args) if code is None else [sys.executable, "-I", "-c", code], *rest, **kwargs)
        starts.append((list(args), kwargs))
        starts.processes.append(proc)
        return proc

    with mock.patch.object(subprocess, "Popen", side_effect=spy):
        yield starts


@functools.cache
def git_version() -> tuple[int, int]:
    """(major, minor) of the git that runs the tests; (0, 0) without git."""
    if GIT is None:
        return (0, 0)
    found = re.search(rb"git version (\d+)\.(\d+)", subprocess.run([GIT, "version"], capture_output=True,
                                                                    check=True).stdout)
    return (int(found.group(1)), int(found.group(2))) if found else (0, 0)


def load(name: str | None = None):
    """The flightboard package, loaded by its path as the entry script loads it, or one of its modules."""
    if "flightboard" not in sys.modules:
        spec = importlib.util.spec_from_file_location("flightboard", PACKAGE / "__init__.py",
                                                      submodule_search_locations=[str(PACKAGE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["flightboard"] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"flightboard.{name}") if name else sys.modules["flightboard"]


MILESTONES = [
    {"id": "M0", "title_fr": "Foundations", "track": "principal", "goal_fr": "A goal.", "value_fr": "A clean repo.",
     "timebox_weeks": 2, "dogfood_min": 0, "cut_list": [], "exit_criteria": [{"text_fr": "The ledger.",
                                                                               "tasks": ["FB-001"]}]},
    {"id": "M1", "title_fr": "Board", "track": "principal", "goal_fr": "A goal.", "value_fr": "A board.",
     "timebox_weeks": 2, "dogfood_min": 0, "cut_list": [], "exit_criteria": [{"text_fr": "The launch.",
                                                                               "tasks": ["FB-005"]}]},
]
BASE = {"FB-001": "planned", "FB-002": "in_progress", "FB-003": "ready", "FB-004": "planned",
        "FB-005": "planned", "FB-006": "planned", "FB-007": "ready"}
MILESTONE_OF = {"FB-005": "M1", "FB-006": "M1", "FB-007": "M1"}
OWNERS = {"FB-007": "owner"}


def proof(kind: str) -> dict:
    return {"kind": kind, "at": "2026-11-06", "ref": "commit:abcdef1", "note_fr": "test evidence"}


def task(tid: str, status: str, title: str | None = None) -> dict:
    """A task the roadmap rules accept in this status: its evidence follows its status."""
    owner = OWNERS.get(tid, "claude")
    evidence = []
    if owner != "owner" and status in ("awaiting_review", "done"):
        evidence.append(proof("tests"))
    if status == "done":
        evidence.append(proof("owner_decision" if owner == "owner" else "review"))
    return {"id": tid, "title_fr": title or f"Task {tid}", "milestone": MILESTONE_OF.get(tid, "M0"),
            "epic": "core", "owner": owner, "priority": "P0" if tid in ("FB-001", "FB-005") else "P2",
            "size": "S", "release": "1.0" if tid == "FB-005" else "later", "dependencies": [],
            "acceptance_fr": ["one criterion"], "evidence_expected": ["owner_decision"] if owner == "owner"
            else ["tests", "review"], "evidence": evidence, "status": status, "notes_fr": "a note"}


def decision(did: str = "ADR-0099", quote: str = "Yes, switch over") -> dict:
    return {"id": did, "title_fr": "A test switch", "status": "adopted", "date": "2026-11-07",
            "record": "docs/decisions/0099-test.md", "task": None, "summary_fr": "A summary.",
            "source": {"date": "2026-11-07", "channel_fr": "chat", "quote_fr": quote}}


def ledger(statuses: dict[str, str], updated: str = "2026-11-06", titles: dict | None = None,
           decisions: list | None = None) -> dict:
    return {"schema_version": 2, "updated_at": updated, "project": "Demo",
            "capacity": {"start_date": "2026-11-09", "claude_sessions_per_week": 10, "review_slots_per_week": 2,
                         "owner_hours_per_week": 4},
            "launch_gate": "FB-005", "milestones": copy.deepcopy(MILESTONES),
            "tasks": [task(tid, status, (titles or {}).get(tid)) for tid, status in statuses.items()],
            "external_dependencies": [], "decisions": decisions or []}


def encoded(statuses: dict[str, str], **options) -> bytes:
    return json.dumps(ledger(statuses, **options), ensure_ascii=False, indent=1).encode("utf-8")


def roadmap():
    return load("ledgers").make("roadmap")


def light(statuses: dict[str, str], **options) -> dict[str, dict]:
    """The tasks of a ledger as the roadmap adapter reads them."""
    return roadmap().parse(encoded(statuses, **options))["tasks"]


MAIN = {**BASE, "FB-002": "awaiting_review", "FB-006": "done"}


class Repository:
    """main: c1, c2, then a fast-forward to a branch that merged main. Worktrees a (committed then uncommitted work),
    b (behind main, ready for a merge go), m (all in main); branches without worktree c (ready), z (conflicts with a
    on FB-001), owner (claims the owner's task and records a decision), x and y (the same new id, two tasks), invalid
    (an invalid ledger); and an uncommitted change in the main checkout."""

    def __init__(self, extra: bool = True) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name).resolve() / "demo"
        self.root.mkdir()
        self.trees = self.root / ".claude" / "worktrees"
        self.git("init", "-q", "-b", "main")
        (self.root / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (self.root / ".git" / "info" / "exclude").write_text(".claude/worktrees/\nout/\n", encoding="utf-8")
        self.commit(BASE, "feat: first ledger", "2026-11-07T08:00:00-05:00")
        self.first = self.sha("HEAD")
        self.commit({**BASE, "FB-002": "awaiting_review"}, "docs: FB-002 in review", "2026-11-07T08:30:00-05:00")
        self.second = self.sha("HEAD")
        self.git("branch", "claude/fb-006-d", self.first)
        self.m = self.worktree("fb-006-d-7a8b9c", None, "claude/fb-006-d")
        self.commit({**BASE, "FB-006": "done"}, "feat: FB-006 done", "2026-11-07T08:45:00-05:00", where=self.m)
        self.git("merge", "-q", "--no-ff", "-m", "merge: main into the branch of FB-006", "main", where=self.m,
                 env=self.dated("2026-11-07T09:00:00-05:00"))
        self.git("merge", "-q", "--ff-only", "claude/fb-006-d", env=self.dated("2026-11-07T09:05:00-05:00"))
        self.main = self.sha("main")
        if extra:
            self._sessions()

    def _sessions(self) -> None:
        self.a = self.worktree("fb-001-a-1b2c3d", "claude/fb-001-a-1b2c3d", "main")
        self.commit({**MAIN, "FB-001": "in_progress"}, "feat: FB-001 started", "2026-11-07T11:00:00-05:00",
                    where=self.a)
        self.write({**MAIN, "FB-001": "awaiting_review"}, where=self.a)
        self.touch(self.a / "data" / "roadmap.json", NOW - timedelta(minutes=4))
        self.b = self.worktree("old-b-4e5f6a", "claude/old-b", self.first)
        self.commit({**BASE, "FB-003": "awaiting_review"}, "feat: FB-003 delivered", "2026-11-07T10:00:00-05:00",
                    where=self.b)
        self.branch("claude/fb-004-c", {**MAIN, "FB-004": "done"}, "feat: FB-004 done", "2026-11-07T11:30:00-05:00")
        self.branch("claude/fb-001-z", {**MAIN, "FB-001": "in_progress"}, "feat: FB-001 elsewhere",
                    "2026-11-07T07:00:00-05:00")
        self.branch("claude/owner", {**MAIN, "FB-007": "done"}, "docs: a test decision", "2026-11-07T06:00:00-05:00",
                    decisions=[decision()])
        self.branch("claude/fb-139-x", {**MAIN, "FB-139": "planned"}, "docs: FB-139", "2026-11-07T05:00:00-05:00",
                    titles={"FB-139": "One task"})
        self.branch("claude/fb-139-y", {**MAIN, "FB-139": "ready"}, "docs: FB-139 too",
                    "2026-11-07T05:30:00-05:00", titles={"FB-139": "Another task"})
        self.branch("claude/invalid", {**MAIN, "FB-003": "done"}, "docs: FB-003 done", "2026-11-07T04:00:00-05:00",
                    strip_evidence="FB-003")
        self.write({**MAIN, "FB-005": "ready"})
        self.touch(self.root / "data" / "roadmap.json", NOW - timedelta(hours=1))

    @staticmethod
    def dated(when: str) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        return env

    def git(self, *args: str, where: Path | None = None, env: dict | None = None) -> str:
        proc = subprocess.run([GIT, "-C", str(where or self.root), "-c", "user.name=Test",
                               "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                               "-c", "core.autocrlf=false", *args],
                              capture_output=True, check=True, env=env or self.dated("2026-11-07T07:30:00-05:00"))
        return proc.stdout.decode("utf-8").strip()

    def sha(self, rev: str, where: Path | None = None) -> str:
        return self.git("rev-parse", rev, where=where)

    def write(self, statuses: dict[str, str], where: Path | None = None, strip_evidence: str | None = None,
              **options) -> None:
        data = ledger(statuses, **options)
        for item in data["tasks"]:
            if item["id"] == strip_evidence:
                item["evidence"] = []
        path = (where or self.root) / "data" / "roadmap.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

    def commit(self, statuses: dict[str, str], message: str, when: str, where: Path | None = None, **options) -> None:
        self.write(statuses, where, **options)
        self.git("add", "-A", where=where)
        self.git("commit", "-q", "-m", message, where=where, env=self.dated(when))

    def worktree(self, name: str, branch: str | None, start: str) -> Path:
        path = self.trees / name
        self.git("worktree", "add", "-q", *(("-b", branch) if branch else ()), str(path), start)
        commondir = self.root / ".git" / "worktrees" / name / "commondir"
        if commondir.is_file():  # added at 07:00 of the test day, whatever the clock says
            self.touch(commondir, NOW - timedelta(hours=5))
        return path

    def branch(self, name: str, statuses: dict[str, str], message: str, when: str, **options) -> None:
        """A branch from main with one commit, and no worktree left."""
        self.git("branch", name, "main")
        tree = self.worktree("tmp-" + name.replace("/", "-"), None, name)
        self.commit(statuses, message, when, where=tree, **options)
        self.git("worktree", "remove", "--force", str(tree))

    @staticmethod
    def touch(path: Path, when: datetime) -> None:
        os.utime(path, (when.timestamp(), when.timestamp()))

    def close(self) -> None:
        self._tmp.cleanup()


def roadmap_settings(**values):
    """The settings of a board on the demo repository: its roadmap ledger, said explicitly."""
    return load("config").Settings(**{"ledger": "roadmap", **values})
