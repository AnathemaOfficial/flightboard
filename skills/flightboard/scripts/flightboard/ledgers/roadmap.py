# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The roadmap ledger (schema 2, data/roadmap.json by default): milestones with exit criteria, capacity, a launch gate,
decisions and external dependencies, judged by the pinned rules of roadmap_rules.py.

The live overlay takes only task status changes and new tasks, only from a ledger these rules accept; decisions,
milestones, capacity, the launch gate and external dependencies come from main only, and a branch that changes them is
only named. Standard library only, safe under -I.
"""
from __future__ import annotations

from datetime import timedelta

from ..text import clean
from . import roadmap_rules as RULES
from .base import MAX_LEDGER_BYTES, Ledger, NotALedger, countable, dependencies, milestone_row, read_json, task_identity, texts

# What the validator iterates over: its time grows with tasks times dependencies, exit-criteria citations times
# dependencies and external dependencies times tasks. A ledger past any of these is read but not validated, so never
# applied; at these sizes validation stays near a second.
MAX_VALIDATED = {"tasks": 2000, "dependencies": 5000, "exit_citations": 300, "milestones": 60,
                 "external_dependencies": 200, "decisions": 2000}
MAX_READ_TASKS = 2 * MAX_VALIDATED["tasks"]  # an oversized ledger is read in part: never applied, never unbounded


def _task(item: dict) -> dict:
    return {"status": item["status"], "title": clean(item.get("title_fr"), 200),
            "milestone": clean(item.get("milestone"), 12), "owner": clean(item.get("owner"), 31),
            "size": clean(item.get("size"), 4), "priority": clean(item.get("priority"), 4),
            "release": clean(item.get("release"), 10), "dependencies": dependencies(item.get("dependencies")),
            "acceptance": texts(item.get("acceptance_fr"), 5, 300),
            "_identity": task_identity({key: item.get(key, default) for key, default in
                                        (("title_fr", ""), ("milestone", ""), ("owner", ""), ("size", ""),
                                         ("priority", ""), ("release", ""), ("dependencies", []),
                                         ("acceptance_fr", []), ("epic", ""), ("evidence_expected", []),
                                         ("start_early", ""), ("notes_fr", ""))})}


def _decision(item: dict) -> dict:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return {"status": clean(item.get("status"), 20), "title": clean(item.get("title_fr"), 200),
            "date": clean(item.get("date"), 12), "task": clean(item.get("task"), 20),
            "quote": clean(source.get("quote_fr"), 300), "channel": clean(source.get("channel_fr"), 200)}


def _listed(value: object) -> list:
    return value if isinstance(value, list) else []


def sizes(raw: dict) -> dict[str, int]:
    """What the validator iterates over, counted as MAX_VALIDATED names it."""
    tasks = [item for item in raw["tasks"] if isinstance(item, dict)]
    milestones = [item for item in _listed(raw.get("milestones")) if isinstance(item, dict)]
    return {"tasks": len(raw["tasks"]),
            "dependencies": sum(len(_listed(item.get("dependencies"))) for item in tasks),
            "exit_citations": sum(len(_listed(criterion.get("tasks"))) for item in milestones
                                  for criterion in _listed(item.get("exit_criteria")) if isinstance(criterion, dict)),
            "milestones": len(_listed(raw.get("milestones"))),
            "external_dependencies": len(_listed(raw.get("external_dependencies"))),
            "decisions": len(_listed(raw.get("decisions")))}


class RoadmapLedger(Ledger):
    kind = "roadmap"
    releases = True
    sections = ("milestones", "capacity", "launch_gate", "external_dependencies")

    def parse(self, data: bytes | None, validate: bool = True) -> dict | None:
        """A ledger, cleaned: {valid, error, updated_at, tasks, decisions, raw}; None when it is not a ledger at all.
        valid says whether the pinned rules accept it."""
        if not data or len(data) > MAX_LEDGER_BYTES:
            return None
        try:
            raw = read_json(data)
        except NotALedger:
            return None
        keys = ("decisions", "milestones", "external_dependencies")
        if not isinstance(raw, dict) or not isinstance(raw.get("tasks"), list) \
                or not all(isinstance(raw.get(key) or [], list) for key in keys):
            return None
        try:
            return self._read(raw, validate)
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            return None

    def _read(self, raw: dict, validate: bool) -> dict | None:
        tasks: dict[str, dict] = {}
        for item in raw["tasks"][:MAX_READ_TASKS]:  # past the validator's own cap the ledger is never valid anyway
            if isinstance(item, dict) and isinstance(item.get("id"), str) and RULES.TASK_ID.fullmatch(item["id"]) \
                    and isinstance(item.get("status"), str) and item["status"] in RULES.STATUSES \
                    and item["id"] not in tasks:
                tasks[item["id"]] = _task(item)
        if not tasks:
            return None
        decisions = {item["id"]: _decision(item) for item in (raw.get("decisions") or [])[:MAX_READ_TASKS]
                     if isinstance(item, dict) and isinstance(item.get("id"), str)
                     and RULES.DECISION_ID.fullmatch(item["id"])}
        errors: list[str] = []
        over = [name for name, count in sizes(raw).items() if count > MAX_VALIDATED[name]]
        if validate and over:
            errors = [f"ledger too big to be validated here (too many {', '.join(over)})"]
        elif validate:
            try:
                errors = RULES.validate_ledger(raw)
            except Exception:  # an odd ledger may break a check: it is then simply not valid
                errors = ["the validator could not read it"]
        updated = raw.get("updated_at")
        return {"valid": validate and not errors, "error": clean(errors[0], 240) if errors else "",
                "updated_at": updated if isinstance(updated, str) and RULES.DATE.fullmatch(updated) else "",
                "tasks": tasks, "decisions": decisions, "raw": raw}

    def _forecast(self, raw: dict) -> dict[str, dict]:
        """main's forecast; empty when it cannot be computed (an odd ledger never breaks the page)."""
        try:
            return {row["id"]: row for row in RULES.forecast(raw)}
        except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError, OverflowError):
            return {}

    def milestones(self, raw: dict, live: dict[str, dict], main: dict[str, dict]) -> list[dict]:
        rows, result = self._forecast(raw), []
        for milestone in _listed(raw.get("milestones")):
            # an id the rules allow (M0 to M99) and nothing else: it reaches the page as written
            if not isinstance(milestone, dict) or not isinstance(milestone.get("id"), str) \
                    or not RULES.MILESTONE_ID.fullmatch(milestone["id"]):
                continue
            mid, row = milestone["id"], rows.get(milestone["id"])
            # A contested new declaration has no baseline to count; main's own task remains main's.
            own = [entry for entry in live.values() if entry["milestone"] == mid
                   and countable(entry)]
            own_main = [task for task in main.values() if task["milestone"] == mid]
            weeks = milestone.get("timebox_weeks") if isinstance(milestone.get("timebox_weeks"), int) else 0
            try:
                planned_start = (row["planned"] - timedelta(weeks=weeks)).isoformat() if row else ""
                forecast_start = (row["forecast"] - timedelta(weeks=row["weeks"])).isoformat() if row else ""
            except (OverflowError, TypeError):
                planned_start = forecast_start = ""
            result.append(milestone_row(mid, clean(milestone.get("title_fr"), 120), clean(milestone.get("track"), 20),
                                        own, own_main, row, (planned_start, forecast_start)))
        return result

    def plan(self, raw: dict, milestones: list[dict], main: dict[str, dict]) -> list[dict]:
        """The plan as a step line: the active tasks of every milestone, due at its planned end."""
        capacity = raw.get("capacity") if isinstance(raw.get("capacity"), dict) else {}
        start = capacity.get("start_date")
        if not isinstance(start, str) or not RULES.DATE.fullmatch(start):
            return []
        points, total, total_10 = [{"at": start, "all": 0, "v10": 0}], 0, 0
        for milestone in milestones:
            if not milestone["planned"]:
                continue
            own = [task for task in main.values() if task["milestone"] == milestone["id"]
                   and task["status"] != "dropped"]
            total += len(own)
            total_10 += sum(1 for task in own if task["release"] == "1.0")
            points.append({"at": milestone["planned"], "all": total, "v10": total_10})
        return points

    def launch(self, raw: dict, live: dict[str, dict], milestones: list[dict]) -> dict | None:
        gate = live.get(raw.get("launch_gate"), {}) if isinstance(raw.get("launch_gate"), str) else {}
        if not countable(gate):
            return None
        found = next((m for m in milestones if m["id"] == gate.get("milestone") and m["forecast"]), None)
        return {key: found[key] for key in ("id", "planned", "forecast", "gap")} if found else None

    def review_slots(self, raw: dict) -> int | None:
        capacity = raw.get("capacity") if isinstance(raw.get("capacity"), dict) else {}
        slots = capacity.get("review_slots_per_week")
        return slots if isinstance(slots, int) and not isinstance(slots, bool) else None

    def open_decisions(self, raw: dict) -> int:
        return sum(1 for item in raw.get("decisions") or [] if isinstance(item, dict) and item.get("status") == "open")

    def externals(self, raw: dict) -> dict[str, object]:
        return {item.get("id"): item.get("status") for item in raw.get("external_dependencies") or []
                if isinstance(item, dict) and isinstance(item.get("id"), str)}

