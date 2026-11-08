# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Everything the page shows, computed once here so that the page only draws, and the same few lines for --resume.

What waits for the owner comes first, in the words of the go they give (merge, review, check, decide). Branch ledgers
are claims: main's figures stay main's, and what the sessions declare is counted apart. Each waiting item carries a
short text made only of verbs, ids and names, for --resume: free text read in a branch (a quote, a title) never reaches
a session through it. Without a ledger, the view is git's alone: sessions, what waits, and main's moves. The page reads;
it never approves nor authorizes anything. Standard library only, safe under -I.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from . import messages as M
from . import overlay as OVERLAY
from .ledgers import SATISFIED, Ledger
from .text import clean, instant, iso, parse_time, safe_branch

ACTIVE_MINUTES = 15
RECENT_MINUTES = 120
REFRESH_SECONDS = 10
MAX_EVENTS = 60
MAX_WAITING = 30
MAX_NEXT = 5
MAX_CHANGES = 40
MAX_SESSION_TASKS = 40  # the tasks a session's card names; the rules read them all
MAX_LISTED = 5  # the ids a line of the summary or of what waits names: the rest is a count
MAX_DETAILS = 500  # the tasks whose detail the page holds
HISTORY_MAX = 300
STARTED = ("in_progress", "awaiting_review", "done")
PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
WAITING_ORDER = ("merge", "conflict", "check", "alert", "review", "session")
WORD = re.compile(r"[A-Za-z0-9]+(?:[._-]+[A-Za-z0-9]+)*")


# ---------------------------------------------------------------- small rules

def activity(last: datetime | None, now: datetime, active: int = ACTIVE_MINUTES, recent: int = RECENT_MINUTES) -> str:
    if last is None:
        return "unknown"
    age = (now - last).total_seconds()
    if age < active * 60:
        return "active"
    return "recent" if age < recent * 60 else "quiet"


def infer_tasks(texts: list[str], known: set[str] | dict) -> list[str]:
    """The known task ids named in texts (folder and branch names, own commit messages), in order of appearance, case
    ignored. An id is found as a whole word or as a run of a word's hyphen-separated parts, never inside a longer
    number: "fix-abc-12-login" names ABC-12, "abc-120" does not. An id without a digit is never inferred: a branch
    named auth-refactor does not work on a task called auth."""
    folded = {tid.casefold(): tid for tid in known if any(char.isdigit() for char in tid)}  # never a plain word
    found: list[str] = []
    for text in texts:
        for word in WORD.findall((text or "")[:400]):
            parts = word.split("-")
            for start in range(len(parts)):
                for end in range(start + 1, min(len(parts), start + 6) + 1):
                    tid = folded.get("-".join(parts[start:end]).casefold())
                    if tid is not None and tid not in found:
                        found.append(tid)
    return found


def _when(value: str) -> float:
    return instant(parse_time(value))


def _stage(session: dict) -> str:
    if session["conflicted"]:
        return "conflict"
    if session["operation"]:
        return "operation"
    if session["modified"] or session["untracked"]:
        return "uncommitted"
    if session["kind"] == "checkout" and not session["ahead"]:
        return "up_to_date"
    if session["kind"] != "checkout" and session["remote"] == "behind":
        return "behind_origin"  # the remote holds commits this copy lacks: never "merged", even when this copy is
    if not session["ahead"]:
        return "merged"
    return "pushed" if session["kind"] == "remote" or session["remote"] == "pushed" else "committed"


def _advice(session: dict, live: dict[str, dict], tracked: bool = True) -> str:
    """What the session's state allows to say, never more. Ready for a merge go: committed, quiet, its files read,
    and, with a ledger, every task it works on in review or done in its own ledger; without one, a local branch the
    session pushed as it is (a branch that lives only on the remote is pushed by nature, which says nothing).
    Ended: all in main, its files read, and every task done or dropped in main itself. Without a ledger nothing says a
    session is finished, so it is never called ended: in main and quiet may still mean waiting for a review."""
    stage = session["stage"]
    if session["kind"] == "checkout" or stage in ("conflict", "operation"):
        return ""
    if session.get("gone"):
        return "gone"
    read = session["files_read"]  # modified files not read: nothing says it is all committed
    if stage == "behind_origin" and not session["ahead"]:
        return "open"  # all of this copy is in main, but the remote holds more
    if session["ahead"]:
        settled = stage in ("committed", "pushed") and not session["reason"] and read \
            and session["activity"] != "active"
        if tracked:
            own = session.get("_head_tasks") or {}
            ready = settled and bool(session["tasks"]) \
                and all(own.get(tid, {}).get("status") in SATISFIED for tid in session["tasks"])
        else:
            ready = settled and stage == "pushed" and session["kind"] != "remote"
        return "ready_to_merge" if ready else "open"
    if stage != "merged" or session["kind"] != "worktree":
        return "merged"
    if session["kept"]:
        return "keep_files"
    if not tracked:
        return "merged"
    statuses = [live[tid]["status_main"] for tid in session["tasks"] if tid in live and live[tid]["status_main"]]
    if read and statuses and all(status in ("done", "dropped") for status in statuses):
        return "ended"
    return "keep_for_review" if "awaiting_review" in statuses else "merged"


def unreadable_session(item: dict, reason: str, detail: str = "") -> dict:
    """A session that could not be read at all: named, with why, and nothing else."""
    return {"id": item["id"], "name": item["name"], "kind": item["kind"], "branch": "", "head": item["tip"][:7],
            "head_date": "", "subject": "", "created": "", "ahead": item.get("ahead", 0),
            "behind": item.get("behind", 0), "modified": 0, "untracked": 0, "conflicted": 0, "kept": 0,
            "files_read": False, "files_issue": "unreadable", "stale": bool(item.get("stale")),
            "gone": bool(item.get("gone")),
            "last_write": "", "last_activity": "", "activity": "unknown",
            "operation": item["operation"], "remote": "", "pushed": False, "ledger": "unreadable", "error": "",
            "reason": reason, "reason_detail": detail, "overlay": False, "changes": [], "hidden_changes": 0,
            "decisions": [], "sections": [], "tasks": [], "inferred": [], "commits": [], "updated_at": "",
            "_changes": [], "_head_tasks": {}}


# ---------------------------------------------------------------- history

def _history(versions: list[dict], zone) -> list[dict]:
    series = []
    for version in versions:
        tasks = version["tasks"]
        series.append({"at": iso(version["at"], zone), "sha": version["sha"][:7], "via": version["via"],
                       "approx": version.get("approx", False), "counts": OVERLAY.counts(tasks),
                       "counts_10": OVERLAY.counts(tasks, "1.0"),
                       "active": sum(1 for task in tasks.values() if task["status"] != "dropped"),
                       "active_10": sum(1 for task in tasks.values()
                                        if task["status"] != "dropped" and task["release"] == "1.0")})
    return [entry for entry in series if entry["at"]]


def _moves(entries: list[dict], zone) -> list[dict]:
    """main's own moves, newest first: when it moved and why (its reflog), for the git-only view."""
    moves = [{"at": iso(entry["at"], zone), "sha": entry["sha"][:7], "via": entry["via"], "approx": entry["approx"]}
             for entry in reversed(entries)]
    return [move for move in moves if move["at"]][:MAX_EVENTS]


def _session_events(sessions: list[dict]) -> list[dict]:
    events = []
    for session in sessions:
        for change in session["_changes"]:
            if change["removed"]:
                continue
            events.append({"at": change.get("at") or session["last_activity"], "sha": change.get("sha", ""),
                           "subject": "" if change["uncommitted"] else session["subject"], "where": session["name"],
                           "uncommitted": change["uncommitted"], "approx": change.get("approx", False),
                           "task": change["task"], "title": change["title"], "milestone": change["milestone"],
                           "from": change["from"], "to": change["to"]})
    return events


def _applied_moves(sessions: list[dict], live: dict[str, dict], events: list[dict]) -> list[dict]:
    """The declared moves the live view applied, once per task: what the daily bars count for the sessions. A move
    main already holds is main's, counted once, by main."""
    applied = {(tid, source["session"]) for tid, entry in live.items() for source in entry["sources"]
               if source["applied"] and source["to"] != entry["status_main"]}
    seen, moves = set(), []
    for event in events:
        key = (event["task"], event["where"])
        if event["where"] != "main" and key in applied and event["task"] not in seen:
            seen.add(event["task"])
            moves.append(event)
    return moves


# ---------------------------------------------------------------- what waits for the owner

def _review_since(live: dict[str, dict], events: list[dict]) -> dict[str, str]:
    """When each task in review entered it: main's own move when main holds the review (a session saying the same
    later changes nothing), else the earliest move to review that a session declared and the live view applied."""
    moves: dict[str, list[dict]] = {}
    for event in events:  # newest first
        if event["to"] == "awaiting_review":
            moves.setdefault(event["task"], []).append(event)
    since = {}
    for tid, entry in live.items():
        if entry["status"] != "awaiting_review":
            continue
        if entry["status_main"] == "awaiting_review":
            found = [event["at"] for event in moves.get(tid, []) if event["where"] == "main"]
            since[tid] = found[0] if found else ""
        else:
            applied = {source["session"] for source in entry["sources"]
                       if source["applied"] and source["to"] == "awaiting_review"}
            found = [event["at"] for event in moves.get(tid, []) if event["where"] in applied]
            since[tid] = found[-1] if found else ""
    return since


def _named(session: dict) -> list[str]:
    """The tasks a waiting item links to: those the session's card names."""
    return session["tasks"][:MAX_SESSION_TASKS]


def _item(kind: str, verb: str, text: str, safe: str, tasks: list[str] | None = None, session: str = "",
          since: str = "") -> dict:
    return {"kind": kind, "verb": verb, "text": text, "safe": safe, "tasks": tasks or [], "session": session,
            "since": since}


class Waiting:
    """What waits for the owner, worded in one language: a text for the page and a safe text for --resume."""

    def __init__(self, lang: str) -> None:
        self.lang = lang

    def say(self, key: str, **params: object) -> str:
        return M.say(self.lang, key, **params)

    def status(self, status: str | None) -> str:
        return M.label(self.lang, "status", status) if status else M.say(self.lang, "status.removed")

    def _sides(self, entry: dict) -> str:
        """main's status, then each session's: MAX_LISTED sessions at most, then how many more. Each status a session
        claims is named before any repeat of it, those not applied first: cut short, a line still names what to
        arbitrate."""
        sources = entry["sources"]
        first: list[dict] = []
        for source in sorted(sources, key=lambda item: bool(item.get("applied"))):  # stable: name order kept
            if all(source["to"] != chosen["to"] for chosen in first):
                first.append(source)
        ordered = first + [source for source in sources if all(source is not chosen for chosen in first)]
        sides = [self.say("side", where="main", status=self.status(entry["status_main"]))] \
            if entry["status_main"] else []
        sides += [self.say("side", where=source["session"], status=self.status(source["to"]))
                  for source in ordered[:MAX_LISTED]]
        more = self.say("more_ids", n=len(sources) - MAX_LISTED) if len(sources) > MAX_LISTED else ""
        return " · ".join(sides) + more

    def merges(self, sessions: list[dict], tracked: bool) -> list[dict]:
        items = []
        for c in sessions:
            if c["advice"] != "ready_to_merge":
                continue
            commits = M.count(self.lang, "commits", c["ahead"])
            pushed = self.say("pushed" if c["stage"] == "pushed" else "not_pushed")
            text = self.say("wait.merge", tasks=listed(self.lang, c["tasks"]), name=c["name"], commits=commits,
                            pushed=pushed) if tracked else \
                self.say("wait.merge_git", name=c["name"], commits=commits, pushed=pushed)
            items.append(_item("merge", self.say("verb.merge"), text, text, _named(c), c["name"], c["last_activity"]))
        return items

    def conflicts(self, live: dict[str, dict], notes: list[dict]) -> list[dict]:
        items = []
        for tid, entry in sorted(live.items()):
            if entry["conflict"]:
                sides = self._sides(entry)
                items.append(_item("conflict", self.say("verb.conflict"),
                                   self.say("wait.conflict_titled", tid=tid, title=entry["title"], sides=sides),
                                   self.say("wait.conflict", tid=tid, sides=sides), [tid]))
            elif entry["collision"]:
                # a task main lacks: the session whose version the live view holds (its first declarer) first, then
                # those that collide with it; a task main holds: main is the other side, so those that collide come
                # first. Cut short, a line still names both sides.
                head = entry["sources"][:1] if entry.get("new") else []
                rest = sorted(entry["sources"][len(head):], key=lambda item: item.get("reason") != "collision")
                names = [item["session"] for item in head + rest]
                text = self.say("wait.collision", tid=tid, where=listed(self.lang, names))
                items.append(_item("conflict", self.say("verb.collision"), text, text, [tid]))
        for note in notes:
            if note["kind"] == "orphan":
                text = self.say("wait.orphan", tid=note["task"], name=note["session"], status=self.status(note["to"]))
                items.append(_item("conflict", self.say("verb.conflict"), text, text, [], note["session"]))
        return items

    def checks(self, sessions: list[dict], live: dict[str, dict], notes: list[dict]) -> list[dict]:
        items = []
        for c in sessions:
            for decision in c["decisions"]:
                known = M.label(self.lang, "decision", decision["status"], default="")
                status = known or decision["status"]
                quote = self.say("quote", quote=decision["quote"]) if decision["quote"] else ""
                safe = self.say("wait.decision_safe", did=decision["id"], status=known or self.say("unknown_status"),
                                name=c["name"])
                text = self.say("wait.decision", did=decision["id"], status=status, name=c["name"], quote=quote)
                items.append(_item("check", self.say("verb.check"), text, safe, [], c["name"]))
        for tid, entry in sorted(live.items()):
            for source in entry["sources"]:
                if source.get("governed"):
                    whose = self.say("whose.reviewer" if source["governed"] == "reviewer" else "whose.owner")
                    params = {"name": source["session"], "tid": tid, "status": self.status(source["to"]),
                              "whose": whose}
                    items.append(_item("check", self.say("verb.check"),
                                       self.say("wait.governed_titled", title=entry["title"], **params),
                                       self.say("wait.governed", **params), [tid], source["session"]))
        for note in notes:
            if note["kind"] == "governed":
                whose = self.say("whose.reviewer" if note.get("owner") == "reviewer" else "whose.owner")
                text = self.say("wait.governed_new", name=note["session"], tid=note["task"], whose=whose,
                                status=self.status(note["to"]))
                items.append(_item("check", self.say("verb.check"), text, text, [note["task"]], note["session"]))
        return items

    def alerts(self, sessions: list[dict]) -> list[dict]:
        items = []
        for c in sessions:
            if c["stage"] in ("conflict", "operation"):
                what = self.say("git_conflict") if c["stage"] == "conflict" else \
                    M.label(self.lang, "operation", c["operation"], default=self.say("git_operation"))
                text = self.say("wait.alert", name=c["name"], what=what)
                items.append(_item("alert", self.say("verb.alert"), text, text, _named(c), c["name"],
                                   c["last_activity"]))
            elif c["_changes"] and c["reason"] == "invalid_ledger":
                items.append(_item("alert", self.say("verb.alert"),
                                   self.say("wait.alert", name=c["name"], what=c["reason_text"]),
                                   self.say("wait.invalid_safe", name=c["name"]), _named(c), c["name"],
                                   c["last_activity"]))
        return items

    def reviews(self, live: dict[str, dict], events: list[dict], slots: int | None) -> list[dict]:
        entered = _review_since(live, events)
        note = self.say("slots", slots=M.count(self.lang, "review_slots", slots)) if isinstance(slots, int) else ""
        items = []
        for tid, entry in sorted(live.items(), key=lambda item: _when(entered.get(item[0], ""))):
            if entry["status"] == "awaiting_review":
                items.append(_item("review", self.say("verb.review"), f"{tid} {entry['title']}{note}", f"{tid}{note}",
                                   [tid], "", entered.get(tid, "")))
        return items

    def quiet(self, sessions: list[dict]) -> list[dict]:
        items = []
        for c in sessions:
            # a session whose modified files were not read may be writing: it is not called quiet
            if c["stage"] == "uncommitted" and c["activity"] != "active" and c["files_read"]:
                text = self.say("wait.session", name=c["name"])
                items.append(_item("session", self.say("verb.session"), text, text, _named(c), c["name"],
                                   c["last_activity"]))
        return items

    def all(self, sessions: list[dict], live: dict[str, dict], notes: list[dict], events: list[dict],
            slots: int | None, tracked: bool) -> list[dict]:
        items = self.merges(sessions, tracked) + self.conflicts(live, notes) + self.checks(sessions, live, notes) \
            + self.alerts(sessions) + self.reviews(live, events, slots) + self.quiet(sessions)
        return sorted(items, key=lambda item: WAITING_ORDER.index(item["kind"]))


# ---------------------------------------------------------------- next tasks and details

def _next(live: dict[str, dict], sessions: list[dict], ledger: Ledger, raw: dict, order: dict[str, int]) -> list[dict]:
    """The next tasks an agent session could start: dependencies met, nobody started or works on them."""
    taken = set()
    for c in sessions:
        if c["advice"] == "ended" or c["stale"]:  # a branch quiet for weeks takes nothing, whatever else it says
            continue
        taken |= {change["task"] for change in c["_changes"] if change["to"] in STARTED}
        taken |= set(c["inferred"])
    externals = ledger.externals(raw)

    def met(dep: str) -> bool:
        return live[dep]["status"] in SATISFIED if dep in live else externals.get(dep) == "done"

    ready = [(tid, entry) for tid, entry in live.items()
             if ledger.agent_task(entry["owner"]) and entry["status"] in ("planned", "ready") and tid not in taken
             and not entry["collision"] and all(met(dep) for dep in entry["dependencies"])]
    ready.sort(key=lambda item: (order.get(item[1]["milestone"], len(order)), PRIORITY.get(item[1]["priority"], 9),
                                 item[0]))
    return [{"id": tid, "title": entry["title"], "milestone": entry["milestone"], "priority": entry["priority"],
             "status": entry["status"]} for tid, entry in ready[:MAX_NEXT]]


DETAIL_KEYS = ("title", "milestone", "status", "owner", "priority", "release", "acceptance", "dependencies")


def _details(ids: set[str], live: dict[str, dict], sessions: list[dict]) -> dict[str, dict]:
    """What a click on a task id shows: title, milestone, acceptance criteria, dependencies still awaited. A task the
    live view does not hold (a session's new task it did not apply) is shown as that session declares it."""
    declared: dict[str, tuple[dict, str]] = {}
    for c in sorted(sessions, key=lambda item: item["name"]):
        for tid, task in (c.get("_head_tasks") or {}).items():
            declared.setdefault(tid, (task, c["name"]))
    details = {}
    for tid in sorted(ids):
        entry = live.get(tid)
        where = ""
        if entry is None:
            if tid not in declared:
                continue
            entry, where = declared[tid]
        waiting = [dep for dep in entry["dependencies"] if dep in live and live[dep]["status"] not in SATISFIED]
        details[tid] = {**{key: entry[key] for key in DETAIL_KEYS}, "status_main": entry.get("status_main"),
                        "declared_in": where, "waiting_on": waiting}
    return details


# ---------------------------------------------------------------- the summary sentence

def summary(lang: str, kpis: dict, sessions: list[dict], tracked: bool) -> str:
    """One sentence: the same text the page leads with and --resume prints."""
    ready = [tid for c in sessions if c["advice"] == "ready_to_merge" for tid in c["tasks"]] if tracked \
        else [c["name"] for c in sessions if c["advice"] == "ready_to_merge"]
    parts = [M.say(lang, "summary.open", sessions=M.count(lang, "summary.sessions", kpis["sessions"]),
                   writing=M.count(lang, "summary.writing", kpis["writing"]))]
    if kpis["ready"]:
        parts.append(M.count(lang, "summary.ready", kpis["ready"], names=listed(lang, ready)))
    if tracked:
        if kpis["review_live"]:
            parts.append(M.count(lang, "summary.review", kpis["review_live"]))
        extra = kpis["done_live"] - kpis["done_main"]
        parts.append(M.say(lang, "summary.done", done=M.count(lang, "summary.done_count", kpis["done_main"]),
                           active=kpis["active"])
                     + (M.count(lang, "summary.extra", extra) if extra > 0 else ""))
    return M.say(lang, "summary.join").join(parts) + "."


# ---------------------------------------------------------------- the whole view

def _public(session: dict, lang: str) -> dict:
    """A session as the page receives it: no private key, its file issue worded, and its tasks cut to what a card
    names, with the count of the others."""
    found = {key: value for key, value in session.items() if not key.startswith("_")}
    return {**found, "tasks": session["tasks"][:MAX_SESSION_TASKS],
            "hidden_tasks": max(0, len(session["tasks"]) - MAX_SESSION_TASKS),
            "files_issue_text": M.issue(lang, session["files_issue"]) if session["files_issue"] else ""}


def listed(lang: str, ids: list[str]) -> str:
    """At most MAX_LISTED ids, then how many more: a line an agent reads never grows with what a branch declares."""
    shown = ", ".join(ids[:MAX_LISTED])
    return shown + (M.say(lang, "more_ids", n=len(ids) - MAX_LISTED) if len(ids) > MAX_LISTED else "")


def _kpis(main: dict[str, dict], live: dict[str, dict], sessions: list[dict]) -> dict:
    """main's figures from main alone; what the sessions declare, counted apart."""
    counted = [entry for entry in live.values() if not entry["collision"] or entry["status_main"]]
    status = Counter(entry["status"] for entry in counted)
    status_10 = Counter(entry["status"] for entry in counted if entry["release"] == "1.0")
    in_main = [task for task in main.values() if task["status"] != "dropped"]
    open_ = [c for c in sessions if c["advice"] not in ("ended", "gone")
             and not (c["kind"] == "checkout" and c["stage"] == "up_to_date")]
    return {"active": len(in_main), "active_10": sum(1 for task in in_main if task["release"] == "1.0"),
            "done_main": sum(1 for task in in_main if task["status"] == "done"),
            "done_main_10": sum(1 for task in in_main if task["status"] == "done" and task["release"] == "1.0"),
            "review_main": sum(1 for task in in_main if task["status"] == "awaiting_review"),
            "active_live": sum(n for key, n in status.items() if key != "dropped"),
            "active_live_10": sum(n for key, n in status_10.items() if key != "dropped"),
            "done_live": status["done"], "done_live_10": status_10["done"],
            "review_live": status["awaiting_review"], "review_live_10": status_10["awaiting_review"],
            "progress_live": status["in_progress"], "blocked_live": status["blocked"],
            "conflicts": sum(1 for entry in live.values() if entry["conflict"] or entry["collision"]),
            "sessions_read": len(sessions), "sessions": len(open_),
            "writing": sum(1 for c in open_ if c["activity"] == "active"),
            "ready": sum(1 for c in sessions if c["advice"] == "ready_to_merge")}


def _sources(lang: str, context: dict, ledger: dict | None, sessions: list[dict]) -> list[dict]:
    sources = [{"key": "git", "label": M.say(lang, "source.git"), "state": "ok",
                "detail": M.count(lang, "source.read", len(sessions))}]
    adapter = context["ledger_adapter"]
    if ledger is not None:
        note = M.say(lang, "source.note", note=context["note_text"]) if context["note_text"] else ""
        sources.append({"key": "main", "label": M.say(lang, "source.main"),
                        "state": "ok" if ledger["valid"] else "partial",
                        "detail": M.say(lang, "source.main_detail", sha=context["sha"][:7], path=adapter.path,
                                        note=note, dated=M.say(lang, "source.dated", date=ledger["updated_at"])
                                        if ledger["updated_at"] else "")})
        unreadable = sum(1 for c in sessions if c["ledger"] not in ("ok", "absent"))
        sources.append({"key": "sessions", "label": M.say(lang, "source.sessions"),
                        "state": "partial" if unreadable else "ok",
                        "detail": M.count(lang, "source.unreadable", unreadable) if unreadable
                        else M.say(lang, "source.all_read")})
    else:
        missing = context.get("ledger_missing")
        sources.append({"key": "ledger", "label": M.say(lang, "source.ledger"),
                        "state": "partial" if missing else "absent",
                        "detail": M.say(lang, "source.ledger_unreadable", path=missing) if missing
                        else M.say(lang, "source.no_ledger")})
    unread = sum(1 for c in sessions if not c["files_read"] and c["kind"] in ("checkout", "worktree")
                 and not c.get("gone"))  # a folder that is gone holds nothing left to read
    if context.get("planted"):
        sources.append({"key": "files", "label": M.say(lang, "source.files"), "state": "partial",
                        "detail": M.say(lang, "source.planted")})
    elif unread:
        sources.append({"key": "files", "label": M.say(lang, "source.files"), "state": "partial",
                        "detail": M.count(lang, "source.unread", unread)})
    return sources


def _ledger_info(adapter: Ledger | None, context: dict, ledger: dict | None) -> dict:
    return {"kind": adapter.kind if adapter is not None and ledger is not None else "none",
            "path": adapter.path if adapter is not None else "",
            "releases": bool(adapter is not None and ledger is not None and adapter.releases),
            "missing": context.get("ledger_missing") or ""}


def build_view(now: datetime, mode: str, context: dict, sessions: list[dict], versions: list[dict],
               settings: dict | None = None) -> dict:
    """The whole view. context: {ref, sha, note, note_text, ledger (main's, or None for git only), ledger_adapter,
    ledger_missing, head, limits, planted, entries, lang, tool}."""
    lang, ledger, adapter = context["lang"], context["ledger"], context["ledger_adapter"]
    settings = settings or {}
    tracked = ledger is not None and adapter is not None
    raw, main_tasks = (ledger["raw"], ledger["tasks"]) if tracked else ({}, {})
    live, notes = OVERLAY.overlay(main_tasks, sessions)
    milestones = adapter.milestones(raw, live, main_tasks) if tracked else []
    order = {item["id"]: index for index, item in enumerate(milestones)}
    staged = []
    for session in sessions:
        stage = _stage(session)
        staged.append({**session, "stage": stage})
    sessions = [{**session, "advice": _advice(session, live, tracked)} for session in staged]
    sessions = [{**session, "reason_text": M.reason(lang, session["reason"], session.get("reason_detail", ""))
                 if session["reason"] else ""} for session in sessions]
    sessions = sorted(sessions, key=lambda c: (-_when(c["last_activity"]), c["name"]))
    main_events = OVERLAY.history_events(versions, now.tzinfo)
    events = main_events + _session_events(sessions)
    events.sort(key=lambda event: _when(event["at"]), reverse=True)
    kpis = _kpis(main_tasks, live, sessions)
    slots = adapter.review_slots(raw) if tracked else None
    waiting = Waiting(lang).all(sessions, live, notes, events, slots, tracked)
    nexts = _next(live, sessions, adapter, raw, order) if tracked else []
    shown = events[:MAX_EVENTS]
    # the tasks the page can open, those it shows first, at most MAX_DETAILS
    wanted = [tid for item in waiting for tid in item["tasks"]] + [item["id"] for item in nexts]
    wanted += [tid for c in sessions for tid in c["tasks"][:MAX_SESSION_TASKS]] + [event["task"] for event in shown]
    wanted += sorted(tid for tid, e in live.items() if e["sources"])
    ids = set(list(dict.fromkeys(wanted))[:MAX_DETAILS])
    head = context["head"]
    owner_tasks = sum(1 for task in main_tasks.values() if task["owner"] == "owner"
                      and task["status"] in ("ready", "in_progress"))
    return {
        "generated_at": now.isoformat(timespec="seconds"), "mode": mode, "refresh_seconds": REFRESH_SECONDS,
        "tool": context["tool"], "repository": context.get("repository", ""),
        "main": {"state": "ok", "reason": "", "reason_text": "",
                 "ref": safe_branch(context["ref"].split("/", 2)[-1]), "head": context["sha"][:7],
                 "date": iso(head["at"], now.tzinfo) if head.get("at") else "", "subject": head.get("subject", ""),
                 "updated_at": ledger["updated_at"] if tracked else "", "note": context["note"],
                 "note_text": context["note_text"], "valid": ledger["valid"] if tracked else True,
                 "error": ledger["error"] if tracked else ""},
        "ledger": _ledger_info(adapter, context, ledger),
        "resume": summary(lang, kpis, sessions, tracked),
        "waiting": waiting[:MAX_WAITING], "waiting_more": max(0, len(waiting) - MAX_WAITING),
        "yours": {"decisions": adapter.open_decisions(raw) if tracked else 0, "tasks": owner_tasks},
        "kpis": kpis,
        "launch": adapter.launch(raw, live, milestones) if tracked else None,
        "milestones": milestones,
        "sessions": [_public(session, lang) for session in sessions],
        "next": nexts,
        "tasks": _details(ids, live, sessions),
        "history": _history(versions, now.tzinfo),
        "plan": adapter.plan(raw, milestones, main_tasks) if tracked else [],
        "events": shown,
        "moves": _moves(context.get("entries", []), now.tzinfo),
        "daily": OVERLAY.daily(main_events + _applied_moves(sessions, live, events), now),
        "sources": _sources(lang, context, ledger if tracked else None, sessions),
        "limits": {**context["limits"], "history": len(versions), "history_max": HISTORY_MAX},
        "settings": settings,
        "i18n": M.page(lang),
    }


def error_view(now: datetime, mode: str, reason: str, detail: str = "", lang: str = "en", git_ok: bool = False,
               tool: dict | None = None, repository: str = "") -> dict:
    """A view that says why nothing could be read; the page draws it like any other."""
    text = clean(M.error(lang, reason, detail), 200)
    return {
        "generated_at": now.isoformat(timespec="seconds"), "mode": mode, "refresh_seconds": REFRESH_SECONDS,
        "tool": tool or {"name": "flightboard", "version": ""}, "repository": repository,
        "main": {"state": "unreadable", "reason": reason, "reason_text": text, "ref": "", "head": "", "date": "",
                 "subject": "", "updated_at": "", "note": "", "note_text": "", "valid": False, "error": ""},
        "ledger": {"kind": "none", "path": "", "releases": False, "missing": ""},
        "resume": M.say(lang, "summary.error", reason=text), "waiting": [], "waiting_more": 0,
        "yours": {"decisions": 0, "tasks": 0},
        "kpis": {key: 0 for key in ("active", "active_10", "done_main", "done_main_10", "review_main", "active_live",
                                    "active_live_10", "done_live", "done_live_10", "review_live", "review_live_10",
                                    "progress_live", "blocked_live", "conflicts", "sessions_read", "sessions",
                                    "writing", "ready")},
        "launch": None, "milestones": [], "sessions": [], "next": [], "tasks": {}, "history": [], "plan": [],
        "events": [], "moves": [], "daily": [],
        "sources": [{"key": "git", "label": M.say(lang, "source.git"), "state": "ok" if git_ok else "unreadable",
                     "detail": M.say(lang, "source.git_read") if git_ok else text}],
        "limits": {"branches_cut": 0, "branches_unread": False, "history_cut": False, "history_unread": False,
                   "history": 0, "history_max": HISTORY_MAX},
        "settings": {},
        "i18n": M.page(lang),
    }

