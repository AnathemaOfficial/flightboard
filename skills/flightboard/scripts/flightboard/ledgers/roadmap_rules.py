# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The rules of the roadmap ledger (schema 2), pinned in flightboard.

This validator is part of flightboard and is never loaded from the repository flightboard observes: a branch could
otherwise change the code that judges it. Ids take any uppercase prefix (ABC-123, ABC-M1-02, ADR-0001, EXT:name), and
an epic is any short slug. Messages are English and name ids only, plus the odd value that broke a rule. Standard
library only, safe under -I.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from .base import OWNER

SCHEMA_VERSION = 2
STALE_DAYS = 14

PRIORITIES = ("P0", "P1", "P2", "P3")
SIZE_UNITS = {"S": 1, "M": 3, "L": 6}
STATUSES = ("planned", "ready", "in_progress", "awaiting_review", "done", "blocked", "dropped")
SATISFIED = ("done", "awaiting_review")
EVIDENCE = ("doc", "tests", "demo", "receipt", "measure", "owner_decision", "review", "release")
PRODUCT_EVIDENCE = ("tests", "doc", "demo", "measure")
TRACKS = {"principal": "principal", "main": "principal", "recherche": "research", "research": "research"}
RELEASES = ("1.0", "later")
EXTERNAL_STATUSES = ("proposed", "not_started", "in_progress", "done", "unknown")
DECISION_STATUSES = ("adopted", "open", "superseded")

TOP_REQUIRED = ("schema_version", "updated_at", "capacity", "launch_gate", "milestones", "tasks",
                "external_dependencies")
TOP_OPTIONAL = ("project", "decisions")
CAPACITY_FIELDS = ("start_date", "review_slots_per_week", "owner_hours_per_week")
AGENT_CAPACITY_FIELDS = ("agent_sessions_per_week", "claude_sessions_per_week")
MILESTONE_FIELDS = ("id", "title_fr", "track", "goal_fr", "value_fr", "timebox_weeks", "dogfood_min",
                    "cut_list", "exit_criteria")
CRITERION_FIELDS = ("text_fr", "tasks")
TASK_REQUIRED = (
    "id", "title_fr", "milestone", "epic", "owner", "priority", "size", "release",
    "dependencies", "acceptance_fr", "evidence_expected", "status", "notes_fr",
)
TASK_OPTIONAL = ("evidence", "start_early")
EVIDENCE_FIELDS = ("kind", "at", "ref", "note_fr")
EXTERNAL_FIELDS = ("id", "title_fr", "owner", "needed_by", "status", "observed_at", "observed_ref", "observed_fr")
DECISION_REQUIRED = ("id", "title_fr", "status", "date", "record", "task", "summary_fr")
DECISION_OPTIONAL = ("source", "default_fr")
SOURCE_FIELDS = ("date", "channel_fr", "quote_fr")

MILESTONE_ID = re.compile(r"M[0-9]{1,2}")
# Stable ids: PREFIX-M<n>-<nn> names the milestone of origin, PREFIX-<n> any later task; the "milestone" field is the
# only placement.
TASK_ID = re.compile(r"[A-Z][A-Z0-9]{0,9}-(?:M[0-9]{1,2}-[0-9]{2}|[0-9]{1,6})")
EXTERNAL_ID = re.compile(r"[A-Z][A-Za-z0-9]{0,15}:[A-Za-z0-9][A-Za-z0-9._-]{0,40}")
DECISION_ID = re.compile(r"[A-Z]{2,9}-[0-9]{4}")
EPIC = re.compile(r"[a-z][a-z0-9_-]{0,40}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
RECORD = re.compile(r"docs/decisions/[0-9]{4}-[a-z0-9-]+\.md")
OWNER_DECISION_REF = re.compile(r"([A-Z]{2,9}-[0-9]{4})|commit:[0-9a-f]{7,40}")
LOT_REF = re.compile(r"lot:[A-Za-z0-9._-]{1,64}")
SECRET = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|AIza[0-9A-Za-z_-]{35}|tskey-[A-Za-z0-9-]{16,}"
    # a token tried once per run of token characters, from its start (atomic): the same tokens as the unanchored
    # eyJ...{10,}\.eyJ... form, in linear time, where that form takes quadratic time on a long run of eyJ
    r"|(?<![A-Za-z0-9_-])(?>[A-Za-z0-9_-]*?eyJ[A-Za-z0-9_-]{10})[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]{10,}"
    r"\.[A-Za-z0-9_-]{10,}"
    r"|[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,40}"
)
# A host address of the 100.64.0.0/10 shared range that mesh VPNs hand out; a network written as a CIDR is allowed.
PRIVATE_HOST = re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.]|/\d)")
MACHINE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
FORBIDDEN_REF = re.compile(r"\.key\b|keys[\\/]")


# ---------------------------------------------------------------- helpers

def _is_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_text_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0 and all(_is_text(v) for v in value)


def _str_list(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _is_date(value: Any) -> bool:
    if not (isinstance(value, str) and DATE.fullmatch(value)):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_count(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _shown(value: Any) -> str:
    """A value that broke a rule, short and quoted."""
    return repr(value)[:60]


def _check_keys(obj: dict, required: tuple, optional: tuple, where: str, errors: list[str]) -> None:
    missing = [key for key in required if key not in obj]
    unknown = sorted(str(key) for key in set(obj) - set(required) - set(optional))
    if missing:
        errors.append(f"{where}: missing field(s) {', '.join(missing)}")
    if unknown:
        errors.append(f"{where}: unknown field(s) {', '.join(name[:40] for name in unknown[:5])}")


def _task_deps(tasks: dict, tid: str) -> list[str]:
    return [d for d in _str_list(tasks[tid].get("dependencies")) if d in tasks]


def _closure(tasks: dict, start: str) -> set[str]:
    """Every task that start depends on, directly or not."""
    seen: set[str] = set()
    stack = _task_deps(tasks, start) if start in tasks else []
    while stack:
        tid = stack.pop()
        if tid not in seen:
            seen.add(tid)
            stack.extend(_task_deps(tasks, tid))
    return seen


def _downstream(tasks: dict, start: str) -> set[str]:
    """Every task that depends on start, directly or not."""
    return {tid for tid in tasks if start in _closure(tasks, tid)}


def _track(milestones: dict, mid: Any) -> str | None:
    return TRACKS.get(milestones[mid]["data"].get("track")) if mid in milestones else None


# ---------------------------------------------------------------- validation

def validate_ledger(ledger: Any) -> list[str]:
    """Every rule violation; an empty list means the ledger is valid."""
    if not isinstance(ledger, dict):
        return ["the ledger must be a JSON object"]
    errors: list[str] = []
    _check_top(ledger, errors)
    milestones = _check_milestones(_as_list(ledger.get("milestones")), errors)
    externals = _check_externals(_as_list(ledger.get("external_dependencies")), ledger.get("updated_at"), errors)
    tasks = _check_tasks(_as_list(ledger.get("tasks")), milestones, errors)
    _check_dependencies(tasks, externals, milestones, errors)
    _check_cycles(tasks, errors)
    _check_statuses(tasks, externals, errors)
    _check_exits(milestones, tasks, errors)
    _check_priorities(tasks, errors)
    _check_release(tasks, ledger.get("launch_gate"), errors)
    _check_external_links(externals, tasks, errors)
    decisions = _check_decisions(_as_list(ledger.get("decisions", [])), tasks, errors)
    _check_owner_evidence(tasks, decisions, errors)
    _check_hygiene(ledger, errors)
    return errors


def _check_top(ledger: dict, errors: list[str]) -> None:
    _check_keys(ledger, TOP_REQUIRED, TOP_OPTIONAL, "ledger", errors)
    if ledger.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"ledger: schema_version must be {SCHEMA_VERSION}")
    if not _is_date(ledger.get("updated_at")):
        errors.append("ledger: updated_at must be a YYYY-MM-DD date")
    for key in ("milestones", "tasks", "external_dependencies", "decisions"):
        if key in ledger and not isinstance(ledger[key], list):
            errors.append(f"ledger: {key} must be a list")
    if "project" in ledger and not _is_text(ledger["project"]):
        errors.append("ledger: project must be a text")
    capacity = ledger.get("capacity")
    if not isinstance(capacity, dict):
        errors.append("ledger: capacity must be an object")
        return
    _check_keys(capacity, CAPACITY_FIELDS, AGENT_CAPACITY_FIELDS, "capacity", errors)
    if not _is_date(capacity.get("start_date")):
        errors.append("capacity: start_date must be a YYYY-MM-DD date")
    for key in CAPACITY_FIELDS[1:]:
        if not _is_count(capacity.get(key), 1):
            errors.append(f"capacity: {key} must be a positive integer")
    present = [key for key in AGENT_CAPACITY_FIELDS if key in capacity]
    if not present:
        errors.append("capacity: missing field(s) agent_sessions_per_week")
    for key in present:
        if not _is_count(capacity[key], 1):
            errors.append(f"capacity: {key} must be a positive integer")
    if len(present) == 2 and capacity[present[0]] != capacity[present[1]]:
        errors.append("capacity: agent_sessions_per_week and claude_sessions_per_week must agree")


def _check_milestones(items: list, errors: list[str]) -> dict[str, dict]:
    milestones: dict[str, dict] = {}
    previous = -1
    for index, milestone in enumerate(items):
        where = f"milestone #{index + 1}"
        mid = milestone.get("id") if isinstance(milestone, dict) else None
        if not (isinstance(mid, str) and MILESTONE_ID.fullmatch(mid)):
            errors.append(f"{where}: invalid id {_shown(mid)} (expected M0, M1, ...)")
            continue
        where = f"milestone {mid}"
        _check_keys(milestone, MILESTONE_FIELDS, (), where, errors)
        if mid in milestones:
            errors.append(f"{where}: duplicate id")
            continue
        number = int(mid[1:])
        if number <= previous:
            errors.append(f"{where}: milestones must come in increasing order")
        previous = max(previous, number)
        milestones[mid] = {"rank": len(milestones), "data": milestone}
        for key in ("title_fr", "goal_fr", "value_fr"):
            if not _is_text(milestone.get(key)):
                errors.append(f"{where}: empty {key}")
        if milestone.get("track") not in TRACKS:
            errors.append(f"{where}: unknown track {_shown(milestone.get('track'))}")
        if not _is_count(milestone.get("timebox_weeks"), 1):
            errors.append(f"{where}: timebox_weeks must be a positive integer")
        if not _is_count(milestone.get("dogfood_min"), 0):
            errors.append(f"{where}: dogfood_min must be a positive integer or zero")
        if not isinstance(milestone.get("cut_list"), list):
            errors.append(f"{where}: cut_list must be a list of task ids")
        _check_criteria(milestone.get("exit_criteria"), where, errors)
    if not milestones:
        errors.append("ledger: no milestone")
    return milestones


def _check_criteria(criteria: Any, where: str, errors: list[str]) -> None:
    if not (isinstance(criteria, list) and criteria):
        errors.append(f"{where}: exit criteria missing")
        return
    for number, criterion in enumerate(criteria, start=1):
        here = f"{where} criterion {number}"
        if not isinstance(criterion, dict):
            errors.append(f"{here}: must be an object {{text_fr, tasks}}")
            continue
        _check_keys(criterion, CRITERION_FIELDS, (), here, errors)
        if not _is_text(criterion.get("text_fr")):
            errors.append(f"{here}: empty text_fr")
        if not (_str_list(criterion.get("tasks")) and len(_str_list(criterion["tasks"])) == len(criterion["tasks"])):
            errors.append(f"{here}: must cite at least one task")


def _check_externals(items: list, updated: Any, errors: list[str]) -> dict[str, dict]:
    externals: dict[str, dict] = {}
    today = date.fromisoformat(updated) if _is_date(updated) else None
    for index, ext in enumerate(items):
        eid = ext.get("id") if isinstance(ext, dict) else None
        if not (isinstance(eid, str) and EXTERNAL_ID.fullmatch(eid)):
            errors.append(f"external dependency #{index + 1}: invalid id {_shown(eid)} (expected NAME:item)")
            continue
        _check_keys(ext, EXTERNAL_FIELDS, (), eid, errors)
        if eid in externals:
            errors.append(f"{eid}: duplicate id")
            continue
        externals[eid] = ext
        if not _is_text(ext.get("title_fr")):
            errors.append(f"{eid}: empty title_fr")
        if not (isinstance(ext.get("owner"), str) and OWNER.fullmatch(ext["owner"])):
            errors.append(f"{eid}: invalid owner {_shown(ext.get('owner'))}")
        if ext.get("status") not in EXTERNAL_STATUSES:
            errors.append(f"{eid}: unknown status {_shown(ext.get('status'))}")
        if not isinstance(ext.get("observed_fr"), str):
            errors.append(f"{eid}: observed_fr must be a text")
        if not _is_text(ext.get("observed_ref")):
            errors.append(f"{eid}: observed_ref must name what was observed (a commit, say)")
        if not _is_text_list(ext.get("needed_by")):
            errors.append(f"{eid}: needed_by must list at least one task")
        _check_observed(ext, eid, today, errors)
    return externals


def _check_observed(ext: dict, eid: str, today: date | None, errors: list[str]) -> None:
    observed = ext.get("observed_at")
    if not _is_date(observed):
        errors.append(f"{eid}: observed_at must be a YYYY-MM-DD date")
    elif today is not None:
        age = (today - date.fromisoformat(observed)).days
        if age < 0:
            errors.append(f"{eid}: observed_at is later than updated_at")
        elif age > STALE_DAYS and ext.get("status") != "done":
            errors.append(f"{eid}: stale observation ({age} days); refresh it")


def _check_tasks(items: list, milestones: dict, errors: list[str]) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    for index, task in enumerate(items):
        tid = task.get("id") if isinstance(task, dict) else None
        if not (isinstance(tid, str) and TASK_ID.fullmatch(tid)):
            errors.append(f"task #{index + 1}: invalid id {_shown(tid)} (expected ABC-M1-03 or ABC-123)")
            continue
        if tid in tasks:
            errors.append(f"{tid}: duplicate id")
            continue
        tasks[tid] = task
        _check_keys(task, TASK_REQUIRED, TASK_OPTIONAL, tid, errors)
        if task.get("milestone") not in milestones:
            errors.append(f"{tid}: unknown milestone {_shown(task.get('milestone'))}")
        _check_task_enums(task, tid, errors)
        _check_task_lists(task, tid, errors)
        if "evidence" in task:
            _check_evidence_entries(task["evidence"], tid, errors)
    return tasks


def _check_task_enums(task: dict, tid: str, errors: list[str]) -> None:
    if not _is_text(task.get("title_fr")):
        errors.append(f"{tid}: empty title_fr")
    if not isinstance(task.get("notes_fr"), str):
        errors.append(f"{tid}: notes_fr must be a text")
    if not (isinstance(task.get("epic"), str) and EPIC.fullmatch(task["epic"])):
        errors.append(f"{tid}: invalid epic {_shown(task.get('epic'))}")
    if not (isinstance(task.get("owner"), str) and OWNER.fullmatch(task["owner"])):
        errors.append(f"{tid}: invalid owner {_shown(task.get('owner'))}")
    for key, allowed in (("priority", PRIORITIES), ("size", tuple(SIZE_UNITS)),
                         ("status", STATUSES), ("release", RELEASES)):
        if task.get(key) not in allowed:
            errors.append(f"{tid}: unknown {key} {_shown(task.get(key))}")


def _check_task_lists(task: dict, tid: str, errors: list[str]) -> None:
    deps = task.get("dependencies")
    if not (isinstance(deps, list) and all(isinstance(d, str) for d in deps)):
        errors.append(f"{tid}: dependencies must be a list of texts")
    elif len(set(deps)) != len(deps):
        errors.append(f"{tid}: duplicate dependency")
    elif tid in deps:
        errors.append(f"{tid}: a task cannot depend on itself")
    if not _is_text_list(task.get("acceptance_fr")):
        errors.append(f"{tid}: empty acceptance criteria")
    expected = task.get("evidence_expected")
    if not (isinstance(expected, list) and expected and all(e in EVIDENCE for e in expected)):
        errors.append(f"{tid}: evidence_expected must list known evidence kinds")
    elif len(set(expected)) != len(expected):
        errors.append(f"{tid}: duplicate expected evidence")


def _check_evidence_entries(entries: Any, tid: str, errors: list[str]) -> None:
    if not isinstance(entries, list):
        errors.append(f"{tid}: evidence must be a list")
        return
    for index, entry in enumerate(entries):
        where = f"{tid} evidence #{index + 1}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        _check_keys(entry, EVIDENCE_FIELDS, (), where, errors)
        if entry.get("kind") not in EVIDENCE:
            errors.append(f"{where}: unknown evidence kind {_shown(entry.get('kind'))}")
        if not _is_date(entry.get("at")):
            errors.append(f"{where}: YYYY-MM-DD date missing")
        for key in ("ref", "note_fr"):
            if not _is_text(entry.get(key)):
                errors.append(f"{where}: empty {key}")
        if isinstance(entry.get("ref"), str) and FORBIDDEN_REF.search(entry["ref"]):
            errors.append(f"{where}: evidence never points to keys")


def _rank(milestones: dict, mid: Any) -> int | None:
    return milestones[mid]["rank"] if mid in milestones else None


def _start_rank(task: dict, milestones: dict) -> int | None:
    early = task.get("start_early")
    return _rank(milestones, early) if early in milestones else _rank(milestones, task.get("milestone"))


def _check_dependencies(tasks: dict, externals: dict, milestones: dict, errors: list[str]) -> None:
    for tid, task in tasks.items():
        here = _rank(milestones, task.get("milestone"))
        principal = _track(milestones, task.get("milestone")) == "principal"
        for dep in _str_list(task.get("dependencies")):
            if dep in tasks:
                there = _rank(milestones, tasks[dep].get("milestone"))
                if here is not None and there is not None and there > here:
                    errors.append(f"{tid}: depends on {dep}, of a later milestone")
                if principal and _track(milestones, tasks[dep].get("milestone")) == "research":
                    errors.append(f"{tid}: depends on {dep}, of the research track, which must block nothing")
            elif EXTERNAL_ID.fullmatch(dep):
                if dep not in externals:
                    errors.append(f"{tid}: undeclared external dependency {dep}")
            else:
                errors.append(f"{tid}: unknown dependency {_shown(dep)}")
        if "start_early" in task:
            _check_start_early(tid, task, tasks, milestones, errors)


def _check_start_early(tid: str, task: dict, tasks: dict, milestones: dict, errors: list[str]) -> None:
    early, here = task["start_early"], _rank(milestones, task.get("milestone"))
    if early not in milestones or here is None or milestones[early]["rank"] >= here:
        errors.append(f"{tid}: start_early must name a milestone before its own")
        return
    for dep in _task_deps(tasks, tid):
        start = _start_rank(tasks[dep], milestones)
        if start is not None and start > milestones[early]["rank"]:
            errors.append(f"{tid}: starts early ({early}) but depends on {dep}, which starts later")


def _check_cycles(tasks: dict, errors: list[str]) -> None:
    state: dict[str, int] = {}
    for start in tasks:
        if state.get(start):
            continue
        state[start] = 1
        path = [start]
        stack = [iter(_task_deps(tasks, start))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                state[path.pop()] = 2
                stack.pop()
                continue
            if state.get(nxt) == 1:
                cycle = path[path.index(nxt):] + [nxt]
                errors.append("dependency cycle: " + " > ".join(cycle))
                return
            if not state.get(nxt):
                state[nxt] = 1
                path.append(nxt)
                stack.append(iter(_task_deps(tasks, nxt)))


def _dep_ok(dep: str, tasks: dict, externals: dict, strict: bool) -> bool:
    if dep in tasks:
        status = tasks[dep].get("status")
        return status == "done" if strict else status in SATISFIED
    return dep in externals and externals[dep].get("status") == "done"


def _evidence_kinds(task: dict) -> set:
    return {e.get("kind") for e in _as_list(task.get("evidence")) if isinstance(e, dict)}


def _check_statuses(tasks: dict, externals: dict, errors: list[str]) -> None:
    for tid, task in tasks.items():
        status = task.get("status")
        deps = _str_list(task.get("dependencies"))
        if status in ("ready", "in_progress", "awaiting_review", "done"):
            unmet = [d for d in deps if not _dep_ok(d, tasks, externals, strict=status == "done")]
            if unmet:
                errors.append(f"{tid}: status {status} while {', '.join(unmet)} is not done")
        if status == "in_progress" and task.get("size") == "L":
            errors.append(f"{tid}: a size L task must be split before it starts")
        if status in ("blocked", "dropped") and not _is_text(task.get("notes_fr")):
            errors.append(f"{tid}: the status {status} needs a reason in notes_fr")
        _check_evidence(tid, task, status, errors)
        if status != "dropped":
            dropped = [d for d in deps if d in tasks and tasks[d].get("status") == "dropped"]
            if dropped:
                errors.append(f"{tid}: depends on {', '.join(dropped)}, dropped; point it elsewhere first")


def _check_evidence(tid: str, task: dict, status: Any, errors: list[str]) -> None:
    expected = _str_list(task.get("evidence_expected"))
    if status == "done":
        if not _evidence_kinds(task):
            errors.append(f"{tid}: done without evidence")
        elif missing := [k for k in expected if k not in _evidence_kinds(task)]:
            errors.append(f"{tid}: expected evidence missing {', '.join(missing)}")
    if status == "awaiting_review":
        if "review" not in expected or not any(k in PRODUCT_EVIDENCE for k in expected):
            errors.append(f"{tid}: awaiting review is for a task that delivers a product and expects a review")
        elif missing := [k for k in expected if k != "review" and k not in _evidence_kinds(task)]:
            errors.append(f"{tid}: awaiting review without the evidence {', '.join(missing)}")


def _cited(milestone: dict) -> list[str]:
    cited: list[str] = []
    for criterion in _as_list(milestone.get("exit_criteria")):
        if isinstance(criterion, dict):
            cited += _str_list(criterion.get("tasks"))
    return cited


def _check_exits(milestones: dict, tasks: dict, errors: list[str]) -> None:
    for mid, info in milestones.items():
        own = [tid for tid, t in tasks.items() if t.get("milestone") == mid]
        if not own:
            errors.append(f"milestone {mid}: no task")
            continue
        milestone, cited = info["data"], _cited(info["data"])
        for tid in cited:
            if tid not in tasks:
                errors.append(f"milestone {mid}: an exit criterion cites an unknown task {_shown(tid)}")
            elif tasks[tid].get("milestone") != mid:
                errors.append(f"milestone {mid}: an exit criterion cites {tid}, of another milestone")
            elif tasks[tid].get("priority") != "P0" or tasks[tid].get("status") == "dropped":
                errors.append(f"milestone {mid}: {tid} is cited by an exit criterion; it must be P0 and active")
        covered = {tid for tid in cited if tid in tasks}
        for tid in list(covered):
            covered |= {d for d in _closure(tasks, tid) if tasks[d].get("milestone") == mid}
        for tid in own:
            if tasks[tid].get("priority") == "P0" and tasks[tid].get("status") != "dropped" and tid not in covered:
                errors.append(f"{tid}: a P0 no exit criterion of {mid} serves; cite it or lower its priority")
        _check_cut_list(mid, milestone, tasks, errors)
        _check_dogfood(mid, milestone, own, cited, tasks, errors)


def _check_cut_list(mid: str, milestone: dict, tasks: dict, errors: list[str]) -> None:
    cut = _as_list(milestone.get("cut_list"))
    if len(set(map(repr, cut))) != len(cut):
        errors.append(f"milestone {mid}: cut_list holds a duplicate")
    for tid in cut:
        if not (isinstance(tid, str) and tid in tasks and tasks[tid].get("milestone") == mid):
            errors.append(f"milestone {mid}: cut_list cites {_shown(tid)}, which is no task of the milestone")
        elif tasks[tid].get("priority") == "P0":
            errors.append(f"milestone {mid}: cut_list cannot cite {tid}, which is P0")


def _check_dogfood(mid: str, milestone: dict, own: list[str], cited: list[str], tasks: dict, errors: list[str]) -> None:
    need = milestone.get("dogfood_min")
    if not (_is_count(need, 1) and cited and all(tasks.get(t, {}).get("status") == "done" for t in cited)):
        return
    lots = sum(1 for tid in own if any(isinstance(e, dict) and isinstance(e.get("ref"), str)
                                       and LOT_REF.fullmatch(e["ref"]) for e in _as_list(tasks[tid].get("evidence"))))
    if lots < need:
        errors.append(f"milestone {mid}: exit reached with {lots} task(s) done as a lot; {need} needed"
                      f" (evidence ref lot:...)")


def _check_priorities(tasks: dict, errors: list[str]) -> None:
    for tid, task in tasks.items():
        if task.get("priority") != "P0" or task.get("status") == "dropped":
            continue
        lower = [d for d in _task_deps(tasks, tid) if tasks[d].get("priority") != "P0"]
        if lower:
            errors.append(f"{tid}: a P0 task that depends on {', '.join(lower)}, of a lower priority")


def _check_release(tasks: dict, gate: Any, errors: list[str]) -> None:
    for tid, task in tasks.items():
        if task.get("release") == "1.0":
            later = [d for d in _task_deps(tasks, tid) if tasks[d].get("release") != "1.0"]
            if later:
                errors.append(f"{tid}: a 1.0 task that depends on {', '.join(later)}, after 1.0")
    if not (isinstance(gate, str) and gate in tasks):
        errors.append("ledger: launch_gate must name the task of the launch go")
        return
    if tasks[gate].get("release") != "1.0":
        errors.append(f"{gate}: the launch go must be a 1.0 task")
    scope = _closure(tasks, gate) | _downstream(tasks, gate) | {gate}
    stray = sorted(tid for tid, t in tasks.items()
                   if t.get("release") == "1.0" and t.get("status") != "dropped" and tid not in scope)
    if stray:
        errors.append("ledger: 1.0 task(s) off the launch path: " + ", ".join(stray[:10]))


def _check_external_links(externals: dict, tasks: dict, errors: list[str]) -> None:
    for eid, ext in externals.items():
        needed = set(_str_list(ext.get("needed_by")))
        users = {tid for tid, task in tasks.items() if eid in _str_list(task.get("dependencies"))}
        unknown = sorted(n for n in needed if n not in tasks)
        if unknown:
            errors.append(f"{eid}: needed_by cites unknown tasks {', '.join(_shown(n) for n in unknown[:5])}")
        strangers = sorted(n for n in needed if n in tasks and n not in users)
        if strangers:
            errors.append(f"{eid}: needed_by cites {', '.join(strangers)}, which do not depend on it")
        missing = sorted(users - needed)
        if missing:
            errors.append(f"{eid}: needed_by must also cite {', '.join(missing)}")


def _check_decisions(items: list, tasks: dict, errors: list[str]) -> dict[str, dict]:
    decisions: dict[str, dict] = {}
    for index, dec in enumerate(items):
        did = dec.get("id") if isinstance(dec, dict) else None
        if not (isinstance(did, str) and DECISION_ID.fullmatch(did)):
            errors.append(f"decision #{index + 1}: invalid id {_shown(did)} (expected ADR-0001)")
            continue
        _check_keys(dec, DECISION_REQUIRED, DECISION_OPTIONAL, did, errors)
        if did in decisions:
            errors.append(f"{did}: duplicate id")
            continue
        decisions[did] = dec
        _check_decision(dec, did, tasks, errors)
    return decisions


def _check_decision(dec: dict, did: str, tasks: dict, errors: list[str]) -> None:
    for key in ("title_fr", "summary_fr"):
        if not _is_text(dec.get(key)):
            errors.append(f"{did}: empty {key}")
    status, record, task = dec.get("status"), dec.get("record"), dec.get("task")
    if status not in DECISION_STATUSES:
        errors.append(f"{did}: unknown status {_shown(status)}")
    if task is not None and task not in tasks:
        errors.append(f"{did}: unknown task {_shown(task)}")
    if status in ("adopted", "superseded"):
        if not _is_date(dec.get("date")):
            errors.append(f"{did}: an adopted decision needs a date")
        if not (isinstance(record, str) and RECORD.fullmatch(record)):
            errors.append(f"{did}: an adopted decision needs its record docs/decisions/NNNN-title.md")
        _check_source(dec.get("source"), did, errors)
        if status == "adopted" and task in tasks and tasks[task].get("status") != "done":
            errors.append(f"{did}: adopted while its task {task} is not done")
    if status == "open":
        if task not in tasks:
            errors.append(f"{did}: an open decision must cite the owner's task that settles it")
        elif tasks[task].get("owner") != "owner":
            errors.append(f"{did}: the task {task} that settles it must belong to owner")
        elif tasks[task].get("status") == "done":
            errors.append(f"{did}: its task {task} is done; record the decision (adopted or superseded)")
        if not _is_text(dec.get("default_fr")):
            errors.append(f"{did}: an open decision proposes a recommended default (default_fr)")


def _check_source(source: Any, did: str, errors: list[str]) -> None:
    if not isinstance(source, dict):
        errors.append(f"{did}: an adopted decision cites its source (date, channel, quote)")
        return
    _check_keys(source, SOURCE_FIELDS, (), f"{did} source", errors)
    if not _is_date(source.get("date")):
        errors.append(f"{did}: source without a YYYY-MM-DD date")
    for key in ("channel_fr", "quote_fr"):
        if not _is_text(source.get(key)):
            errors.append(f"{did}: source without {key}")


def _check_owner_evidence(tasks: dict, decisions: dict, errors: list[str]) -> None:
    for tid, task in tasks.items():
        for index, entry in enumerate(_as_list(task.get("evidence"))):
            if not (isinstance(entry, dict) and entry.get("kind") == "owner_decision"):
                continue
            ref = entry.get("ref")
            match = OWNER_DECISION_REF.fullmatch(ref) if isinstance(ref, str) else None
            where = f"{tid} evidence #{index + 1}"
            if match is None:
                errors.append(f"{where}: an owner's decision cites an adopted decision id or commit:<sha>")
            elif match.group(1) and decisions.get(match.group(1), {}).get("status") not in ("adopted", "superseded"):
                errors.append(f"{where}: {match.group(1)} is no adopted decision of the ledger")


def _check_hygiene(ledger: dict, errors: list[str]) -> None:
    text = json.dumps(ledger, ensure_ascii=False)
    if SECRET.search(text):
        errors.append("ledger: a secret pattern was found; no secret in the repository")
    if PRIVATE_HOST.search(text):
        errors.append("ledger: a private network host address was found; no private infrastructure detail")
    if MACHINE_PATH.search(text):
        errors.append("ledger: an absolute machine path was found; use a relative path")


# ---------------------------------------------------------------- forecast

def forecast(ledger: dict) -> list[dict]:
    """Sequential forecast from the remaining work and the declared capacity (deterministic)."""
    cap = ledger["capacity"]
    start = date.fromisoformat(cap["start_date"])
    cursor = max(start, date.fromisoformat(ledger["updated_at"]))
    planned, rows = start, []
    agent_rate = cap.get("agent_sessions_per_week", cap.get("claude_sessions_per_week"))
    if not _is_count(agent_rate, 1) or any(not _is_count(cap[key], 1) for key in AGENT_CAPACITY_FIELDS if key in cap) \
            or (all(key in cap for key in AGENT_CAPACITY_FIELDS)
                and cap[AGENT_CAPACITY_FIELDS[0]] != cap[AGENT_CAPACITY_FIELDS[1]]):
        raise ValueError("invalid agent capacity")
    rates = {"agent": agent_rate, "reviewer": cap["review_slots_per_week"],
             "owner": cap["owner_hours_per_week"]}
    for m in ledger["milestones"]:
        load: Counter = Counter()
        for t in ledger["tasks"]:
            if t["milestone"] == m["id"] and t["status"] not in ("done", "dropped"):
                load[t["owner"] if t["owner"] in ("owner", "reviewer") else "agent"] += SIZE_UNITS[t["size"]]
        weeks = max(math.ceil(load[k] / rate) for k, rate in rates.items())
        planned += timedelta(weeks=m["timebox_weeks"])
        cursor += timedelta(weeks=weeks)
        rows.append({"id": m["id"], "planned": planned, "forecast": cursor, "weeks": weeks,
                     "gap": (cursor - planned).days, "load": dict(load)})
    return rows
