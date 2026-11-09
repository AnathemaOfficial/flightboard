# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""What every ledger adapter shares: the canonical statuses, a strict JSON reader, and the default answers of a ledger
that knows no milestone, capacity, decision or release.

A ledger in a branch or a worktree is an agent's claim, not a fact. An adapter turns a file into the same shape for
every format: {valid, error, updated_at, tasks, decisions, raw}, each task {status, title, milestone, owner, size,
priority, release, dependencies, acceptance}, every text cleaned and every id matched against a strict pattern.
Standard library only, safe under -I.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from collections import Counter
from typing import Any

from ..text import clean

MAX_LEDGER_BYTES = 5_000_000
STATUSES = ("planned", "ready", "in_progress", "awaiting_review", "done", "blocked", "dropped")
SATISFIED = ("done", "awaiting_review")
PROGRESS = {"planned": 0, "ready": 1, "in_progress": 2, "awaiting_review": 3, "done": 4}
GOVERNED = ("owner", "reviewer")  # their tasks move only in main: a branch never decides for them
OWNER = re.compile(r"[a-z][a-z0-9_-]{0,30}")
PATH = re.compile(r"[A-Za-z0-9._-]{1,100}(?:/[A-Za-z0-9._-]{1,100}){0,9}")


class NotALedger(ValueError):
    """The data is no ledger at all: absent, oversized, cut mid-write, duplicate keys, NaN, odd sections."""


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(name: str) -> float:
    raise ValueError(f"no JSON value: {name}")


def read_json(data: bytes) -> Any:
    """Strict JSON: no duplicate key, no NaN or infinity; NotALedger for anything else."""
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise NotALedger(type(exc).__name__) from exc


def texts(value: object, count: int, limit: int) -> list[str]:
    return [clean(item, limit) for item in value[:count] if isinstance(item, str)] if isinstance(value, list) else []


def dependencies(value: object) -> list[str]:
    """Dependency ids are decision inputs: preserve every id, without display truncation."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def task_identity(values: dict) -> str:
    """The complete declaration behind a task's displayed metadata, independent of its status."""
    encoded = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("ascii")).hexdigest()


def countable(task: dict) -> bool:
    """Keep main's own task, but never count an unresolved task introduced only by sessions."""
    return task.get("status_main") is not None or not (task.get("conflict") or task.get("collision"))


def safe_path(text: object) -> str | None:
    """A ledger path relative to the repository, "/"-separated and plain (no "..", no drive, no stream), or None."""
    if not isinstance(text, str) or not PATH.fullmatch(text):
        return None
    if any(part in (".", "..") or part.lower() == ".git" for part in text.split("/")):
        return None  # a ledger is a file of the work tree, never one of git's own
    return text


class Ledger:
    """A ledger format, read from path in every commit and working copy. The defaults suit a format with tasks only."""

    kind = ""
    releases = False  # whether tasks carry a release ("1.0" or "later") the page can filter on
    sections: tuple[str, ...] = ()  # the other parts a branch may change: named on the page, never applied

    def __init__(self, path: str) -> None:
        checked = safe_path(path)
        if checked is None:
            raise ValueError("ledger path refused")
        self.path = checked
        self.parts = tuple(checked.split("/"))

    def parse(self, data: bytes | None, validate: bool = True) -> dict | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def slim(self, ledger: dict | None) -> dict | None:
        """What main's history needs of a version: statuses, titles, milestones, releases and owners."""
        if ledger is None:
            return None
        return {"tasks": {tid: {key: task[key] for key in ("status", "title", "milestone", "release", "owner")}
                          for tid, task in ledger["tasks"].items()}}

    def section_changes(self, base: dict | None, head: dict) -> list[str]:
        """The other parts of the ledger a branch changed: named, never applied here."""
        base = base or {}
        return [key for key in self.sections if base.get(key) != head.get(key)]

    def agent_task(self, owner: str) -> bool:
        """Whether a task with this owner is one a coding-agent session could pick up."""
        return owner not in GOVERNED and (owner == "" or bool(OWNER.fullmatch(owner)))

    def milestones(self, raw: dict, live: dict[str, dict], main: dict[str, dict]) -> list[dict]:
        """One row per milestone: counts in the live view and in main; no forecast unless the format has one."""
        rows = []
        for mid, title in self.milestone_titles(raw):
            own = [entry for entry in live.values() if entry["milestone"] == mid
                   and countable(entry)]
            rows.append(milestone_row(mid, title, "", own, [t for t in main.values() if t["milestone"] == mid]))
        return rows

    def milestone_titles(self, raw: dict) -> list[tuple[str, str]]:
        return []

    def plan(self, raw: dict, milestones: list[dict], main: dict[str, dict]) -> list[dict]:
        return []

    def launch(self, raw: dict, live: dict[str, dict], milestones: list[dict]) -> dict | None:
        return None

    def review_slots(self, raw: dict) -> int | None:
        return None

    def open_decisions(self, raw: dict) -> int:
        return 0

    def externals(self, raw: dict) -> dict[str, object]:
        return {}


def milestone_row(mid: str, title: str, track: str, own: list[dict], own_main: list[dict], row: dict | None = None,
                  starts: tuple[str, str] = ("", "")) -> dict:
    """A milestone as the page draws it: the live view's counts, main's counts, what is declared and not yet in main,
    and the forecast when the format has one."""
    own = [entry for entry in own if countable(entry)]
    return {
        "id": mid, "title": title, "track": track,
        "total": len(own), "active": sum(1 for entry in own if entry["status"] != "dropped"),
        "counts": dict(sorted(Counter(entry["status"] for entry in own).items())),
        "counts_main": dict(sorted(Counter(task["status"] for task in own_main).items())),
        "unmerged": dict(sorted(Counter(entry["status"] for entry in own
                                        if entry["status"] != entry["status_main"]).items())),
        "planned_start": starts[0], "planned": row["planned"].isoformat() if row else "",
        "forecast_start": starts[1], "forecast": row["forecast"].isoformat() if row else "",
        "gap": row["gap"] if row else None,
    }
