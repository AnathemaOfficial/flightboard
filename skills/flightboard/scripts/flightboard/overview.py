# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""An observational overview and prepared-action contexts, derived only from an existing reading.

No file, Git, network, model or command access lives here. Statuses remain ledger declarations;
even well-formed evidence references do not establish that their tests or implementation were verified.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re

from .ledgers.base import countable, plain_date
from .text import clean

MAX_ACTIONS = 8
MAX_ACTION_TASKS = 10
MAX_REFERENCES = 12
MAX_EVIDENCE_TASKS = 2000
MAX_TASK_REFERENCES = 20
TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
SHA = re.compile(r"[0-9a-f]{7,40}")
EVIDENCE_KINDS = frozenset(("doc", "tests", "demo", "receipt", "measure", "owner_decision", "review", "release"))


def _number(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


def _counts(tasks: list[dict]) -> dict:
    counts = Counter(task.get("status") for task in tasks if task.get("status") != "dropped")
    return {"total": sum(counts.values()), "done": counts["done"], "review": counts["awaiting_review"],
            "in_progress": counts["in_progress"]}


def _progress(ledger: dict | None, live: dict[str, dict]) -> dict:
    counted = [entry for entry in live.values() if countable(entry)]
    applied = [entry for entry in counted if not entry.get("conflict") and not entry.get("collision")
               and entry.get("status") != entry.get("status_main")]
    return {"available": ledger is not None,
            "main": _counts(list((ledger or {}).get("tasks", {}).values())), "live": _counts(counted),
            "local_only_tasks": sum(entry.get("status_main") is None and entry.get("status") != "dropped"
                                    for entry in counted),
            "uncommitted_tasks": sum(any(source.get("applied") and source.get("uncommitted")
                                         and source.get("to") == entry.get("status")
                                         for source in entry.get("sources", [])) for entry in applied),
            "conflicts": sum(bool(entry.get("conflict") or entry.get("collision")) for entry in live.values())}


def _evidence(ledger: dict | None, adapter: object) -> dict:
    """References from main's own matching declarations, never attached to a different live status."""
    result = {"state": "unavailable" if ledger is None or not ledger.get("valid") else "unsupported", "scope": "main",
              "verification": "not_evaluated", "referenced_tasks": None, "reference_count": None,
              "references": [], "references_more": 0, "partial": False}
    if ledger is None or not ledger.get("valid") or getattr(adapter, "kind", "") != "roadmap":
        return result
    result["state"] = "references_only"
    raw = ledger.get("raw", {}).get("tasks", [])
    if not isinstance(raw, list):
        result["partial"] = True
        return result
    main, seen, tasks, shown, total = ledger.get("tasks", {}), set(), set(), [], 0
    partial = len(raw) > MAX_EVIDENCE_TASKS
    for item in raw[:MAX_EVIDENCE_TASKS]:
        if not isinstance(item, dict):
            partial = True
            continue
        tid = item.get("id")
        if not isinstance(tid, str) or not TASK_ID.fullmatch(tid) or tid not in main \
                or item.get("status") != main[tid].get("status"):
            continue
        refs = item.get("evidence", [])
        if not isinstance(refs, list):
            partial = True
            continue
        partial = partial or len(refs) > MAX_TASK_REFERENCES
        for reference in refs[:MAX_TASK_REFERENCES]:
            if not isinstance(reference, dict):
                partial = True
                continue
            kind, at, ref = reference.get("kind"), plain_date(reference.get("at")), clean(reference.get("ref"), 240)
            if not isinstance(kind, str) or kind not in EVIDENCE_KINDS or not at or not ref:
                partial = True
                continue
            key = (tid, kind, at, reference["ref"])
            if key in seen:
                continue
            seen.add(key)
            tasks.add(tid)
            total += 1
            if len(shown) < MAX_REFERENCES:
                shown.append({"task": tid, "status": item["status"], "kind": kind, "at": at, "ref": ref})
    return {**result, "referenced_tasks": None if partial else len(tasks),
            "reference_count": None if partial else total, "references": shown,
            "references_more": total - len(shown), "partial": partial}


def _reading_partial(context: dict, sessions: list[dict], publication: dict) -> bool:
    ledger, limits = context.get("ledger"), context.get("limits", {})
    coverage = publication.get("coverage", {})
    if context.get("planted") or context.get("ledger_missing") or (ledger is not None and not ledger.get("valid")):
        return True
    if any(limits.get(key) for key in ("branches_cut", "branches_unread", "history_cut", "history_unread")):
        return True
    if publication:
        required = ("worktree_files_total", "working_files_read", "working_files_unknown",
                    "working_ledgers_read", "working_ledgers_unknown")
        if any(type(coverage.get(key)) is not int or coverage[key] < 0 for key in required):
            return True
        if coverage["working_files_read"] + coverage["working_files_unknown"] != coverage["worktree_files_total"] \
                or coverage["working_ledgers_read"] + coverage["working_ledgers_unknown"] \
                != coverage["worktree_files_total"]:
            return True
    if _number(coverage.get("working_files_unknown")) or _number(coverage.get("working_ledgers_unknown")):
        return True
    if publication.get("unpublished", {}).get("state") == "partial" \
            and publication.get("remote", {}).get("state") == "fresh" \
            and publication.get("remote", {}).get("complete") is True:
        return True
    for session in sessions:
        if session.get("gone"):
            continue
        if session.get("reason") or session.get("error") or session.get("operation"):
            return True
        if session.get("kind") in ("checkout", "worktree") \
                and (not session.get("files_read") or not session.get("file_activity_complete")):
            return True
    return False


def _banner(context: dict, progress: dict, sessions: list[dict], publication: dict) -> dict:
    if _reading_partial(context, sessions, publication):
        state, code = "partial", "reading_partial"
    elif progress["conflicts"]:
        state, code = "attention", "status_conflict"
    elif any(_number(publication.get("unpublished", {}).get(key)) for key in ("unique_commits", "candidate_commits")) \
            or any(_dirty(session) for session in sessions):
        state, code = "attention", "local_work"
    elif publication.get("main", {}).get("state") in ("ahead", "behind", "diverged"):
        state, code = "attention", "main_drift"
    elif any(row.get("kind") == "review" for row in publication.get("queue", [])) \
            or any(alert.get("code") == "publication_review" for alert in publication.get("alerts", [])) \
            or any(_number(session.get("ahead")) for session in sessions):
        state, code = "attention", "review_pending"
    elif context.get("ledger") is None:
        state, code = "unverified", "ledger_unavailable"
    elif publication.get("remote", {}).get("state") != "fresh" \
            or publication.get("remote", {}).get("complete") is not True \
            or publication.get("unpublished", {}).get("state") != "exact" \
            or publication.get("main", {}).get("state") != "equal":
        state, code = "unverified", "remote_unverified"
    else:
        state, code = "clear", "no_gap_observed"
    return {"state": state, "code": code}


def _dirty(session: dict) -> bool:
    return session.get("kind") in ("checkout", "worktree") and not session.get("gone") \
        and any(_number(session.get(key)) for key in ("modified", "untracked", "conflicted"))


def _task_ids(values: list) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and TASK_ID.fullmatch(value)))


def _actions(context: dict, live: dict, sessions: list[dict], waiting: list[dict], nexts: list[dict],
             banner: dict, progress: dict) -> list[dict]:
    publication = context.get("publication") or {}
    adapter = context.get("ledger_adapter")
    limits = ["evidence_not_evaluated"]
    if banner["state"] == "partial":
        limits.append("reading_partial")
    remote = publication.get("remote", {})
    if remote.get("state") != "fresh" or remote.get("complete") is not True:
        limits.append("github_unverified")
    if publication.get("unpublished", {}).get("state") != "exact":
        limits.append("publication_unknown")
    if publication.get("queue_more"):
        limits.append("queue_capped")
    if progress["conflicts"]:
        limits.append("task_conflicts")
    base = {"repository": clean(context.get("repository"), 100), "ledger": clean(getattr(adapter, "path", ""), 1000),
            # The page uses generated_at at copy time; a changing duplicate timestamp would break poll deduplication.
            "observed_at": "", "main_head": clean(context.get("sha"), 40), "limits": limits}

    def action(kind, stable, *, target="", branch="", head="", worktree="", tasks=(), more=0):
        chosen = _task_ids(list(tasks))
        identity = sha256(str(stable).encode("utf-8", errors="replace")).hexdigest()[:12]
        return {**base, "id": kind + ":" + identity, "kind": kind, "target": clean(target, 200),
                "branch": clean(branch, 200), "head": head if isinstance(head, str) and SHA.fullmatch(head) else "",
                "worktree": clean(worktree, 160), "tasks": chosen[:MAX_ACTION_TASKS],
                "more": _number(more), "tasks_more": max(0, len(chosen) - MAX_ACTION_TASKS)}

    prepared = []
    if banner["state"] == "partial":
        prepared.append(action("repair_reading", "reading", target=context.get("repository", "")))
    queue = [row for row in publication.get("queue", []) if row.get("kind") in ("commits", "review")]
    queue.sort(key=lambda row: (row.get("kind") != "commits", row.get("id", "")))

    def publication_action(row):
        branches, worktrees = row.get("branches", []), row.get("worktrees", [])
        return action("review_publication", row.get("id", row.get("head", "")),
                      target=branches[0] if branches else row.get("id", ""),
                      branch=branches[0] if branches else "", head=row.get("head", ""),
                      worktree=worktrees[0] if worktrees else "", more=publication.get("queue_more", 0))

    if queue:
        prepared.append(publication_action(queue[0]))
    elif any(_number(publication.get("unpublished", {}).get(key)) for key in ("unique_commits", "candidate_commits")):
        prepared.append(action("review_publication", "publication", target=context.get("repository", ""),
                               more=publication.get("queue_more", 0)))
    else:
        unmerged = sorted((session for session in sessions if _number(session.get("ahead"))),
                          key=lambda session: session.get("id", session.get("name", "")))
        if unmerged:
            session = unmerged[0]
            key = session.get("id", session.get("name", ""))
            prepared.append(action("review_publication", key, target=session.get("name", key),
                                   branch=session.get("branch", ""), head=session.get("head", ""),
                                   tasks=session.get("tasks", []), more=len(unmerged) - 1))
    dirty = {session.get("id", session.get("name", "")): session for session in sessions if _dirty(session)}
    if dirty:
        key = sorted(dirty)[0]
        session = dirty[key]
        prepared.append(action("inspect_worktree", key, target=session.get("name", key),
                               worktree=key, branch=session.get("branch", ""), head=session.get("head", ""),
                               tasks=session.get("tasks", []), more=len(dirty) - 1))
    tracked = sorted((session for session in sessions if session.get("tracking", {}).get("state") == "check"),
                     key=lambda session: session.get("id", session.get("name", "")))
    if tracked:
        session = tracked[0]
        key = session.get("id", session.get("name", ""))
        prepared.append(action("reconcile_tracking", key, target=session.get("name", key),
                               worktree=key, branch=session.get("branch", ""), head=session.get("head", ""),
                               tasks=session.get("tasks", []), more=len(tracked) - 1))
    conflicted = sorted(tid for tid, entry in live.items() if entry.get("conflict") or entry.get("collision"))
    if conflicted:
        prepared.append(action("reconcile_status", "status", tasks=conflicted))
    elif any(item.get("kind") == "conflict" for item in waiting):
        ids = [tid for item in waiting if item.get("kind") == "conflict" for tid in item.get("tasks", [])]
        prepared.append(action("reconcile_status", "status", tasks=ids))
    if nexts and banner["state"] != "partial":
        prepared.append(action("prepare_next", nexts[0]["id"], tasks=[nexts[0]["id"]]))
    for row in queue[1:MAX_ACTIONS]:
        if len(prepared) >= MAX_ACTIONS:
            break
        prepared.append(publication_action(row))
    return prepared[:MAX_ACTIONS]


def build(context: dict, live: dict[str, dict], sessions: list[dict], waiting: list[dict], nexts: list[dict]) -> dict:
    """Use complete pre-presentation aggregates; a bounded queue provides representative action targets only."""
    progress = _progress(context.get("ledger"), live)
    banner = _banner(context, progress, sessions, context.get("publication") or {})
    return {"schema_version": 1, "banner": banner, "progress": progress,
            "evidence": _evidence(context.get("ledger"), context.get("ledger_adapter")),
            "actions": _actions(context, live, sessions, waiting, nexts, banner, progress)}


def unavailable(state: str = "unavailable") -> dict:
    """No old progress or prepared action survives a loading or failed reading."""
    state = "loading" if state == "loading" else "unavailable"
    return {"schema_version": 1, "banner": {"state": state, "code": state},
            "progress": _progress(None, {}), "evidence": _evidence(None, None), "actions": []}
