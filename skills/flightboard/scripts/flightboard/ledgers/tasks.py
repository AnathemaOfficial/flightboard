# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A simple task file (tasks.toml by default, or JSON): a list of tasks with an id, a status and, if you like, a
title, an owner, a milestone, dependencies, a priority and acceptance criteria.

    [statuses]          # optional: your words for flightboard's statuses
    todo = "planned"
    doing = "in_progress"

    [[tasks]]
    id = "AUTH-1"
    title = "Login page"
    status = "doing"
    owner = "claude"    # "owner" (you) and "reviewer" tasks never move from a branch
    depends_on = ["AUTH-0"]

    [[tasks]]
    id = "AUTH-0"
    status = "done"

Its validator is small and structural: unique ids, statuses that map to flightboard's, dependencies that resolve, no
cycle. It checks less than the roadmap ledger's rules, so what a branch declares passes more easily: main's figures
stay main's, and conflicts stay visible. Standard library only, safe under -I.
"""
from __future__ import annotations

import re
import tomllib
from typing import Any

from ..text import clean
from .base import OWNER, STATUSES, Ledger, NotALedger, dependencies, read_json, task_identity, texts

MAX_TASK_FILE_BYTES = 2_000_000
MAX_TASKS = 2000  # as the roadmap ledger's validator: a branch declaring more is read in part, never applied
TASK_ID = re.compile(r"(?=[0-9._-]*[A-Za-z])[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
MILESTONE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
PRIORITY = re.compile(r"P[0-9]")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _listed(value: object) -> list:
    return value if isinstance(value, list) else []


def _load(data: bytes, toml: bool) -> Any:
    if not toml:
        return read_json(data)
    try:
        return tomllib.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError, ValueError) as exc:
        raise NotALedger(type(exc).__name__) from exc


def _mapping(raw: dict, errors: list[str]) -> dict[str, str]:
    """Your status words, each mapped to one of flightboard's statuses; flightboard's own words always map."""
    words = {status: status for status in STATUSES}
    found = raw.get("statuses", {})
    if not isinstance(found, dict):
        errors.append("statuses must be a table of your words")
        return words
    for word, status in found.items():
        if not isinstance(status, str) or status not in STATUSES:
            errors.append(f"statuses: {clean(word, 40)!r} maps to {clean(status, 40)!r}, not one of "
                          f"{', '.join(STATUSES)}")
        elif word in STATUSES and word != status:
            errors.append(f"statuses: {word} is one of flightboard's statuses and cannot mean {status}")
        else:
            words[word] = status
    return words


def _milestones(raw: dict, errors: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    items = raw.get("milestones", [])
    if not isinstance(items, list):
        errors.append("milestones must be a list")
        return found
    for index, item in enumerate(items):
        mid = item.get("id") if isinstance(item, dict) else None
        if not (isinstance(mid, str) and MILESTONE.fullmatch(mid)):
            errors.append(f"milestone #{index + 1}: invalid id")
        elif mid in found:
            errors.append(f"milestone {mid}: duplicate id")
        else:
            found[mid] = clean(item.get("title"), 120)
    return found


def _check_task(item: Any, index: int, words: dict[str, str], milestones: dict[str, str],
                errors: list[str]) -> tuple[str, str] | None:
    """(id, canonical status) of a task, or None when it cannot be one; every problem is recorded in errors."""
    tid = item.get("id") if isinstance(item, dict) else None
    if not (isinstance(tid, str) and TASK_ID.fullmatch(tid)):
        errors.append(f"task #{index + 1}: invalid id (letters, digits and . _ - with at least one letter)")
        return None
    status = words.get(item.get("status")) if isinstance(item.get("status"), str) else None
    if status is None:
        errors.append(f"{tid}: status {clean(item.get('status'), 40)!r} maps to none of flightboard's statuses")
    for key, pattern in (("owner", OWNER), ("priority", PRIORITY)):
        if key in item and not (isinstance(item[key], str) and pattern.fullmatch(item[key])):
            errors.append(f"{tid}: invalid {key}")
    if "milestone" in item and not (isinstance(item["milestone"], str) and MILESTONE.fullmatch(item["milestone"])
                                    and (not milestones or item["milestone"] in milestones)):
        errors.append(f"{tid}: unknown milestone")
    for key in ("title",):
        if key in item and not isinstance(item[key], str):
            errors.append(f"{tid}: {key} must be a text")
    for key in ("depends_on", "acceptance"):
        if key in item and not (isinstance(item[key], list) and all(isinstance(v, str) for v in item[key])):
            errors.append(f"{tid}: {key} must be a list of texts")
    return (tid, status) if status is not None else None


def _check_graph(raw_tasks: dict[str, dict], errors: list[str]) -> None:
    """Every dependency names a task of the file, none names itself, and none loops back."""
    deps = {tid: [d for d in _listed(item.get("depends_on")) if isinstance(d, str)] for tid, item in raw_tasks.items()}
    for tid, names in deps.items():
        for dep in names:
            if dep == tid:
                errors.append(f"{tid}: a task cannot depend on itself")
            elif dep not in raw_tasks:
                errors.append(f"{tid}: unknown dependency {clean(dep, 40)!r}")
    state: dict[str, int] = {}
    for start in deps:
        if state.get(start):
            continue
        state[start], path, stack = 1, [start], [iter([d for d in deps[start] if d in deps])]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                state[path.pop()] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                errors.append("dependency cycle: " + " > ".join(path[path.index(nxt):] + [nxt]))
                return
            elif not state.get(nxt):
                state[nxt] = 1
                path.append(nxt)
                stack.append(iter([d for d in deps[nxt] if d in deps]))


def check(raw: dict) -> tuple[list[str], dict[str, tuple[dict, str]]]:
    """Every problem of a task file, and its tasks that can be read: {id: (item, canonical status)}."""
    errors: list[str] = []
    if "version" in raw and raw["version"] != 1:
        errors.append("version must be 1")
    if "updated_at" in raw and not (isinstance(raw["updated_at"], str) and DATE.fullmatch(raw["updated_at"])):
        errors.append("updated_at must be a YYYY-MM-DD date")
    words, milestones = _mapping(raw, errors), _milestones(raw, errors)
    found: dict[str, tuple[dict, str]] = {}
    for index, item in enumerate(raw["tasks"]):
        checked = _check_task(item, index, words, milestones, errors)
        if checked is None:
            continue
        if checked[0] in found:
            errors.append(f"{checked[0]}: duplicate id")
            continue
        found[checked[0]] = (item, checked[1])
    _check_graph({tid: item for tid, (item, _) in found.items()}, errors)
    return errors, found


def _task(item: dict, status: str) -> dict:
    return {"status": status, "title": clean(item.get("title"), 200), "milestone": clean(item.get("milestone"), 40),
            "owner": clean(item.get("owner"), 31), "size": "", "priority": clean(item.get("priority"), 2),
            "release": "", "dependencies": dependencies(item.get("depends_on")),
            "acceptance": texts(item.get("acceptance"), 5, 300),
            "_identity": task_identity({key: item.get(key, default) for key, default in
                                        (("title", ""), ("milestone", ""), ("owner", ""), ("priority", ""),
                                         ("depends_on", []), ("acceptance", []))})}


class TasksLedger(Ledger):
    kind = "tasks"
    sections = ("statuses", "milestones")

    def parse(self, data: bytes | None, validate: bool = True) -> dict | None:
        """A task file, cleaned: {valid, error, updated_at, tasks, decisions, raw}; None when it is not a task file at
        all (no table with a list of tasks). A task file whose tasks cannot be used is still one: it comes back with
        its validator's first error, so the owner learns why. Past MAX_TASKS tasks, only the first ones are read and
        the file is never valid: what a branch declares can never grow the page without bound."""
        if not data or len(data) > MAX_TASK_FILE_BYTES:
            return None
        try:
            raw = _load(data, self.path.lower().endswith(".toml"))
        except NotALedger:
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list):
            return None
        over = len(raw["tasks"]) > MAX_TASKS
        try:  # every check is linear in the tasks and their dependencies: a file within the cap is always checked
            errors, found = check({**raw, "tasks": raw["tasks"][:MAX_TASKS]})
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            return None
        if over:
            errors = [f"task file too big to be validated here (more than {MAX_TASKS} tasks)", *errors]
        tasks = {tid: _task(item, status) for tid, (item, status) in found.items()}
        updated = raw.get("updated_at")
        return {"valid": validate and not errors, "error": clean(errors[0], 240) if errors else "",
                "updated_at": updated if isinstance(updated, str) and DATE.fullmatch(updated) else "",
                "tasks": tasks, "decisions": {}, "raw": raw}

    def milestone_titles(self, raw: dict) -> list[tuple[str, str]]:
        items = raw.get("milestones") if isinstance(raw.get("milestones"), list) else []
        found: dict[str, str] = {}
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and MILESTONE.fullmatch(item["id"]):
                found.setdefault(item["id"], clean(item.get("title"), 120))
        return list(found.items())
