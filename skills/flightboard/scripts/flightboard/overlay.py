# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""What a session changed in the ledger, the live overlay, and main's history. Pure functions: no git, no file.

A ledger in a branch or a worktree is an agent's claim, not a fact. The live overlay therefore takes only task status
changes and new tasks, only from a ledger its adapter's validator accepts, and never for a task owned by the owner or a
reviewer; decisions, milestones and capacity come from main only. A change applies when main still holds the value the
session started from, or already holds the same value; any other case is a conflict, and main's value stays.
Standard library only, safe under -I.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from .ledgers import GOVERNED, PROGRESS
from .text import iso, parse_time

DAYS = 14


# ---------------------------------------------------------------- what a session changed

def task_changes(base: dict[str, dict] | None, head: dict[str, dict], tip: dict[str, dict] | None = None) -> list[dict]:
    """The status changes of a session: its tasks (head) against its merge base with main (base), never against main
    itself. With tip, the tasks of its last commit when head is a working copy, a change the last commit does not
    hold is uncommitted. A move back along planned → done is marked."""
    base = base or {}
    changes = []
    for tid in sorted(set(base) | set(head)):
        before, after = base.get(tid), head.get(tid)
        old, new = (before or {}).get("status"), (after or {}).get("status")
        if old == new:
            continue
        info = after or before or {}
        committed = (tip.get(tid) or {}).get("status") if tip is not None else new
        changes.append({"task": tid, "title": info.get("title", ""), "milestone": info.get("milestone", ""),
                        "owner": info.get("owner", ""), "from": old, "to": new, "new": before is None,
                        "removed": after is None, "uncommitted": tip is not None and committed != new,
                        "back": old in PROGRESS and new in PROGRESS and PROGRESS[new] < PROGRESS[old]})
    return changes


def decision_changes(base: dict[str, dict] | None, head: dict[str, dict]) -> list[dict]:
    """Decisions a session added or changed: never applied here, only shown, for the owner to check them."""
    base = base or {}
    return [{"id": did, "new": did not in base, **decision} for did, decision in sorted(head.items())
            if base.get(did) != decision]


# ---------------------------------------------------------------- the live overlay

def _entry(task: dict, status_main: str | None, new: bool) -> dict:
    return {"status": task["status"], "status_main": status_main, "title": task["title"],
            "milestone": task["milestone"], "owner": task["owner"], "priority": task["priority"],
            "release": task["release"], "size": task["size"], "dependencies": task["dependencies"],
            "acceptance": task["acceptance"], "new": new, "conflict": False, "collision": False, "sources": []}


def _new_task(live: dict, notes: list, moved_by: dict, session: dict, change: dict, source: dict) -> None:
    """A change to a task main does not hold: a new task the overlay adds, or a note when it cannot."""
    tid, head = change["task"], session.get("_head_tasks") or {}
    if change["removed"]:
        return  # gone on both sides: nothing to say
    if not change["new"] or tid not in head:
        notes.append({"kind": "orphan", "task": tid, "title": change["title"], "session": session["name"],
                      "to": change["to"]})
    elif head[tid]["owner"] in GOVERNED:
        notes.append({"kind": "governed", "task": tid, "title": change["title"], "session": session["name"],
                      "to": change["to"], "owner": head[tid]["owner"]})
    else:
        live[tid] = _entry(head[tid], None, True)
        source["applied"] = True
        moved_by[tid] = session["name"]
        live[tid]["sources"].append(source)


def overlay(main: dict[str, dict], sessions: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """main's tasks plus what every session allowed to overlay changed, and the notes for what could not apply.
    Each entry keeps main's status, the live one, and its sources: {session, from, to, uncommitted, applied, reason
    (a code), other (the session that moved it first), governed (the owner or reviewer a change could not move for)}.
    A note is a change to a task main no longer holds, or a new task given to the owner or a reviewer: shown, never
    applied. Sessions are taken by name, so their order never matters."""
    live = {tid: _entry(task, task["status"], False) for tid, task in main.items()}
    notes: list[dict] = []
    moved_by: dict[str, str] = {}
    for session in sorted(sessions, key=lambda item: item["name"]):
        if not session.get("overlay"):
            continue
        head = session.get("_head_tasks") or {}
        for change in session.get("_changes", session["changes"]):
            tid, before, after = change["task"], change["from"], change["to"]
            source = {"session": session["name"], "from": before, "to": after,
                      "uncommitted": change["uncommitted"], "applied": False, "reason": "", "other": "",
                      "governed": ""}
            entry = live.get(tid)
            if entry is None:
                _new_task(live, notes, moved_by, session, change, source)
                continue
            if change["removed"]:
                source["reason"] = "removed"
            elif change["owner"] in GOVERNED or entry["owner"] in GOVERNED:
                source["governed"] = entry["owner"] if entry["owner"] in GOVERNED else change["owner"]
                source["reason"] = "governed"
            elif change["new"] and (head.get(tid, {}).get("title"), head.get(tid, {}).get("milestone")) != (
                    entry["title"], entry["milestone"]):
                entry["collision"] = True
                source["reason"] = "collision"
            elif tid in moved_by and entry["status"] != after:
                entry["status"], entry["conflict"] = entry["status_main"] or entry["status"], True
                source["reason"], source["other"] = "changed_elsewhere", moved_by[tid]
            elif entry["status_main"] in (before, after) or (tid in moved_by and entry["status"] == after):
                entry["status"], source["applied"] = after, True
                moved_by.setdefault(tid, session["name"])
            else:
                entry["conflict"] = True
                source["reason"] = "main_changed"
            entry["sources"].append(source)
    return live, notes


# ---------------------------------------------------------------- main's history

def history_versions(entries: list[dict], ledgers: dict[str, dict | None]) -> list[dict]:
    """The versions of main's ledger, oldest first: one per move of main that changed a task (status or presence).
    entries: {sha, at, via, approx}, oldest first; a version that cannot be read, or holds no task that can (a task
    file whose every status is unknown, say), is skipped and diffed across: it never reads as every task removed."""
    versions, previous = [], None
    for entry in entries:
        ledger = ledgers.get(entry["sha"])
        if not ledger or not ledger["tasks"]:
            continue
        statuses = {tid: task["status"] for tid, task in ledger["tasks"].items()}
        if statuses == previous:
            continue
        previous = statuses
        versions.append({**entry, "tasks": ledger["tasks"]})
    return versions


def history_events(versions: list[dict], zone) -> list[dict]:
    """The status moves between consecutive versions of main, newest first, each dated by the move of main."""
    batches = []
    for previous, current in zip(versions, versions[1:]):
        batches.append([{"at": iso(current["at"], zone), "sha": current["sha"][:7], "subject": current["via"],
                         "where": "main", "uncommitted": False, "approx": current.get("approx", False),
                         "task": change["task"], "title": change["title"], "milestone": change["milestone"],
                         "from": change["from"], "to": change["to"]}
                        for change in task_changes(previous["tasks"], current["tasks"])])
    return [event for batch in reversed(batches) for event in batch]


def counts(tasks: dict[str, dict], release: str | None = None) -> dict[str, int]:
    return dict(sorted(Counter(task["status"] for task in tasks.values()
                               if release is None or task["release"] == release).items()))


def daily(events: list[dict], now: datetime, days: int = DAYS, zone=None) -> list[dict]:
    """Tasks moved to done or to review each day, in main and in the sessions, for the last days. Each instant is
    placed by the zone's own rules (this PC's by default), so a move near midnight stays on its day across a change of
    time."""
    today = now.astimezone(zone).date()
    buckets = {today - timedelta(days=offset): Counter() for offset in range(days)}
    for event in events:
        moment = parse_time(event["at"])
        if moment is None or moment.tzinfo is None or event["to"] not in ("done", "awaiting_review"):
            continue
        try:
            local = moment.astimezone(zone).date()
        except (OverflowError, OSError, ValueError):
            continue
        if local in buckets:
            kind = "done" if event["to"] == "done" else "review"
            buckets[local][kind + ("_main" if event["where"] == "main" else "_live")] += 1
    return [{"day": day.isoformat(), **{key: buckets[day][key] for key in
                                        ("done_main", "review_main", "done_live", "review_live")}}
            for day in sorted(buckets)]
