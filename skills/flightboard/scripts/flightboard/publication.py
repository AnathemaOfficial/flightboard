# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Pure publication summaries: bounded Git evidence, coverage and observation-based alerts."""
from __future__ import annotations

from datetime import datetime

from .text import clean, safe_branch

HEADS = "refs/heads/"
MAX_QUEUE = 100
MAX_ALIASES = 50
MAX_PULL_REQUESTS = 10


def _reachable(tip: str, parents: dict) -> set[str]:
    found, pending = set(), [tip]
    while pending:
        value = pending.pop()
        if value in found or value not in parents:
            continue
        found.add(value)
        pending.extend(parents[value])
    return found


def _coverage(worktrees: list[dict], sessions: list[dict]) -> dict:
    by_id = {row["id"]: row for row in sessions}
    present = [row for row in worktrees if not row.get("gone")]
    read, ledgers, reasons, details = 0, 0, {}, []
    for tree in worktrees:
        if tree.get("gone"):
            details.append({"id": clean(tree["id"], 160), "name": clean(tree.get("name", tree["id"]), 160),
                            "files_state": "gone",
                            "reason": "gone", "ledger_state": "unknown"})
    for tree in present:
        session = by_id.get(tree["id"], {})
        if session.get("files_read") and session.get("file_activity_complete"):
            read += 1
            file_state, reason = "read", ""
        else:
            reason = tree.get("reason") or session.get("files_issue") or "partial"
            reasons[reason] = reasons.get(reason, 0) + 1
            file_state = "partial" if session.get("files_read") else "unknown"
        if tree.get("working_directory_readable") and session.get("ledger") == "ok" and not session.get("error"):
            ledgers += 1
            ledger_state = "read"
        else:
            ledger_state = "unknown"
        details.append({"id": clean(tree["id"], 160), "name": clean(tree.get("name", tree["id"]), 160),
                        "files_state": file_state,
                        "reason": reason, "ledger_state": ledger_state})
    return {"worktrees_discovered": len(worktrees), "worktrees_gone": len(worktrees) - len(present),
            "worktree_files_total": len(present),
            "working_files_read": read, "working_files_unknown": len(present) - read,
            "working_ledgers_read": ledgers, "working_ledgers_unknown": len(present) - ledgers,
            "branch_sessions": sum(row.get("kind") in ("branch", "remote") for row in sessions),
            "reasons": reasons, "worktrees": details}


def build(now: datetime, refs: dict, worktrees: list[dict], sessions: list[dict], remote: dict,
          graph: dict, main: dict, first_seen: dict[str, str]) -> dict:
    """No IO. A local tracking ref establishes candidates, never a fresh GitHub publication proof."""
    source = graph.get("comparison_source", "local_tracking_refs")
    exact = bool(graph.get("complete") and source == "github" and remote.get("state") == "fresh"
                 and remote.get("complete"))
    parents = graph.get("parents", {})
    tips: dict[str, dict] = {}
    for name, info in refs.items():
        if not name.startswith(HEADS):
            continue
        value = tips.setdefault(info["sha"], {"branches": [], "worktrees": [], "upstreams": []})
        value["branches"].append(safe_branch(name[len(HEADS):]))
        if info.get("upstream"):
            value["upstreams"].append(clean(info["upstream"], 250))
    for tree in worktrees:
        if tree.get("tip"):
            tips.setdefault(tree["tip"], {"branches": [], "worktrees": [], "upstreams": []})[
                "worktrees"].append(clean(tree["id"], 160))
    # Every tip present in the walked union has candidate commits; wholly excluded tips have none.
    published = set(graph.get("published_tips", ()))
    if source == "github":
        published.update(remote.get("heads", {}).values())
    else:
        published.update(info["sha"] for name, info in refs.items() if name.startswith("refs/remotes/"))
    selected = [tip for tip in tips if tip in parents or (not graph.get("complete") and tip not in published)]
    # Walk each selected tip once. Repeating every member's walk for each overlapping stack is cubic on a fan-out.
    reachable = {tip: _reachable(tip, parents) for tip in selected}
    selected_set, ancestors = set(selected), set()
    for tip in selected:
        ancestors.update((reachable[tip] & selected_set) - {tip})
    # A shared ancestor may belong to two divergent publication paths. It cannot fuse their independent tips.
    stacks = {tip: sorted((reachable[tip] & selected_set) | {tip})
              for tip in selected if tip not in ancestors}
    queue = []
    prs = remote.get("pull_requests", [])
    for head, members in stacks.items():
        commits = reachable[head]
        branches = sorted({name for tip in members for name in tips[tip]["branches"]})
        worktree_ids = sorted({name for tip in members for name in tips[tip]["worktrees"]})
        attached = [pr for pr in prs if pr.get("head_sha") in members]
        queue.append({"id": "commits:" + head, "kind": "commits", "branches": branches,
                      "worktrees": worktree_ids, "head": head, "commit_count": len(commits) if exact else None,
                      "candidate_count": len(commits), "files": None,
                      "state": "unknown" if head not in parents else "unpublished" if exact else "candidate",
                      "comparison_source": source,
                      "upstreams": sorted({name for tip in members for name in tips[tip]["upstreams"]}),
                      "pull_requests": attached})
    attached_heads = {pr.get("head_sha") for row in queue for pr in row["pull_requests"]}
    review = {}
    for pr in prs:
        head = pr.get("head_sha")
        if head in tips and head not in attached_heads:
            review.setdefault(head, []).append(pr)
    for head, attached in review.items():
        value = tips[head]
        queue.append({"id": "review:" + head, "kind": "review", "branches": sorted(set(value["branches"])),
                      "worktrees": sorted(set(value["worktrees"])), "head": head, "commit_count": 0,
                      "candidate_count": 0, "files": None, "state": "pr_open", "comparison_source": "github",
                      "upstreams": sorted(set(value["upstreams"])), "pull_requests": attached})
    session_by_id = {row["id"]: row for row in sessions}
    for tree in worktrees:
        session = session_by_id.get(tree["id"], {})
        files = session.get("modified", 0) + session.get("untracked", 0) + session.get("conflicted", 0)
        if not files:
            continue
        ref = tree.get("ref") or ""
        branch = safe_branch(ref[len(HEADS):]) if ref.startswith(HEADS) else ""
        queue.append({"id": "dirty:" + tree["id"], "kind": "dirty", "branches": [branch] if branch else [],
                      "worktrees": [clean(tree["id"], 160)], "head": tree.get("tip", ""),
                      "commit_count": None, "candidate_count": 0, "files": files, "state": "uncommitted",
                      "comparison_source": "working_files", "upstreams": [], "pull_requests": []})
    queue.sort(key=lambda row: (row["kind"], row["branches"], row["id"]))
    coverage = _coverage(worktrees, sessions)
    alerts = []

    def alert(code, severity, detail):
        alerts.append({"code": code, "severity": severity, "message_key": "publication.alert." + code,
                       "detail": str(detail), "first_seen_at": first_seen.get(code)})

    candidates = len(parents)
    if candidates or selected:
        alert("publication_pending", "warning", candidates)
    dirty = sum(row["kind"] == "dirty" for row in queue)
    if dirty:
        alert("uncommitted_work", "warning", dirty)
    if review:
        alert("publication_review", "info", len(review))
    if coverage["working_files_unknown"]:
        alert("worktree_coverage", "warning", coverage["working_files_unknown"])
    if remote.get("state") not in ("fresh", "disabled"):
        alert("github_unavailable", "warning", remote.get("state", "unknown"))
    if not exact:
        alert("publication_unknown", "info", graph.get("reason") or source)
    if main.get("state") in ("ahead", "behind", "diverged"):
        alert("main_" + main["state"], "warning", main.get("ahead") if main["state"] == "ahead"
              else main.get("behind"))
    if candidates and first_seen.get("publication_pending"):
        try:
            age = (now - datetime.fromisoformat(first_seen["publication_pending"])).total_seconds()
        except (ValueError, TypeError):
            age = 0
        if age >= 86400:
            alert("publication_overdue", "warning", int(age // 3600))
    queue_total = len(queue)
    queue = queue[:MAX_QUEUE]
    for row in queue:
        for key in ("branches", "worktrees", "upstreams"):
            row[key + "_more"] = max(0, len(row[key]) - MAX_ALIASES)
            row[key] = row[key][:MAX_ALIASES]
        row["pull_requests_more"] = max(0, len(row["pull_requests"]) - MAX_PULL_REQUESTS)
        row["pull_requests"] = row["pull_requests"][:MAX_PULL_REQUESTS]
    return {"remote": {key: value for key, value in remote.items() if key not in ("heads", "pull_requests")},
            "main": main, "coverage": coverage,
            "unpublished": {"state": "exact" if exact else "partial" if source == "github" else "unknown",
                            "unique_commits": candidates if exact else None, "candidate_commits": candidates,
                            "comparison_source": source},
            "queue": queue, "queue_total": queue_total, "queue_more": queue_total - len(queue), "alerts": alerts}
