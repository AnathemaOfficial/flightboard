# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Work a session still holds: symbolic branches, stashes and detached commits.

The branch listing is shared, while HEAD and some symbolic refs are worktree-local. A tip is trusted only when its
whole symbolic chain stays in that listing. Stashed or uncommitted work also holds back another card that could own
it. These are pure functions: no git command or filesystem access happens here.
"""
from __future__ import annotations

import re
from collections.abc import Callable

HEADS = "refs/heads/"
TREES = ("checkout", "worktree")
BRANCHES = ("branch", "remote")
MAX_STASH = 1000
MAX_MOVES = 1000
MAX_DROPPED = 20
NO_BRANCH = "(no branch)"
BRANCH_NAME = r"[^\x00-\x20\x7f~^:?*\x5b\x5c]{1,250}"
STASH_LINE = re.compile(r"(?:WIP on|On) (\(no branch\)|" + BRANCH_NAME + r"): ")
MOVED = re.compile(r"checkout: moving from (" + BRANCH_NAME + r") to ")
FULL_ID = re.compile(r"[0-9a-f]{40}")


def fold(name: str) -> str:
    """Names Windows may open as one, including case variants and final dots or spaces."""
    return "/".join(part.upper().casefold().rstrip(". ") for part in name.split("/"))


def split_names(names) -> set[str]:
    seen: dict[str, str] = {}
    split: set[str] = set()
    for name in names:
        other = seen.setdefault(fold(name), name)
        if other != name:
            split.update((name, other))
    return split


def hidden_main(refs: dict, mains: tuple[str, ...], guess: str | None) -> bool:
    folded = {fold(name): name for name in refs}
    allowed = (guess,) if guess in refs else ()
    return any(folded.get(fold(name)) not in (None, name, *allowed) for name in (*mains, guess) if name)


def chain(name: str, refs: dict) -> list[str] | None:
    """Every symbolic hop must be listed: a worktree-local target is not the shared listing's commit."""
    found: list[str] = []
    while name:
        if name in found or name not in refs:
            return None
        found.append(name)
        name = refs[name].get("symref")
    return found


def held(tree: dict, refs: dict) -> set[str] | None:
    head, operation = tree["head"], tree["operation"]
    names = [head["ref"]] if head.get("ref") else []
    if not names and not head.get("sha"):
        return None
    if operation["kind"] in ("rebase", "bisect") and not names:
        if operation["kind"] == "bisect" or not operation.get("branch"):
            return None
        names.append(operation["branch"])
    elif operation.get("branch"):
        names.append(operation["branch"])
    found: set[str] = set()
    for name in names:
        walked = chain(name, refs)
        if walked is None:
            return None
        found.update(walked)
    return found


def tip(tree: dict, refs: dict) -> str | None:
    ref = tree["head"].get("ref")
    if not ref:
        return tree["head"].get("sha")
    if ref not in refs or (not tree["main"] and chain(ref, refs) is None):
        return None
    return refs[ref]["sha"]


def unread(tree: dict, refs: dict) -> str:
    if tree.get("unknown"):
        return tree["reason"] or "head_unreadable"
    ref = tree["head"].get("ref")
    if not ref:
        return "head_unreadable"
    return "head_symbolic" if ref in refs else "head_elsewhere"


def stashed(entries: list[dict] | None) -> dict:
    if entries is None:
        return {"refs": frozenset(), "detached": False, "other": False, "unknown": True}
    found = [STASH_LINE.match(entry["via"]) for entry in entries]
    names = [match.group(1) for match in found if match]
    return {"refs": frozenset(HEADS + name for name in names if name != NO_BRANCH),
            "detached": NO_BRANCH in names, "other": None in found, "unknown": False}


def head_moves(entries: list[dict] | None) -> dict | None:
    if entries is None:
        return None
    left: set[str] = set()
    dropped: list[str] = []
    for entry in entries:
        found = MOVED.match(entry["via"])
        if found is None:
            continue
        name = found.group(1)
        if FULL_ID.fullmatch(name):
            if name not in dropped:
                dropped.append(name)
        else:
            left.add(HEADS + name)
    return {"left": frozenset(left), "dropped": tuple(dropped)}


def left_behind(item: dict, existing: Callable[[list[str]], set[str]], contained: Callable[[str], bool]) -> int:
    dropped = (item.get("moves") or {}).get("dropped") or ()
    checked = list(dropped[:MAX_DROPPED])
    found = existing(checked) if checked else set()
    return len(dropped) - len(checked) + sum(1 for commit in checked if commit in found and not contained(commit))


def _ties(item: dict, remote_prefix: str) -> tuple[set[str], bool]:
    if item["kind"] in TREES:
        moves = item.get("moves") or {}
        return set(item.get("held") or ()) | set(moves.get("left", ())), \
            item.get("held") == set() or bool(moves.get("dropped"))
    if item["kind"] == "remote":
        return {HEADS + item["ref"][len(remote_prefix):]}, False
    return {item["ref"]}, False


def stash_states(items: list[dict], stash: dict, remote_prefix: str) -> list[str]:
    if stash["unknown"]:
        return ["unknown"] * len(items)
    ties = [_ties(item, remote_prefix) for item in items]
    named = set().union(*(names for names, _ in ties)) if ties else set()
    untied = stash["other"] or bool(stash["refs"] - named) \
        or (stash["detached"] and not any(detached for _, detached in ties))
    return ["stashed" if names & stash["refs"] or (detached and stash["detached"])
            else "unmatched" if untied else "" for names, detached in ties]


def settled(card: dict) -> bool:
    return bool(card["files_read"]) and not (card["modified"] or card["untracked"] or card["conflicted"]
                                             or card["operation"] or card.get("stash") or card.get("left_behind"))


def hold_back(items: list[dict], cards: list[dict], stash: dict, reaches: Callable[[str, str], bool],
              remote_prefix: str) -> list[dict]:
    cards = [{"left_behind": 0, **card, "held": card["reason"] if card["reason"].startswith("held_") else "",
              "stash": state}
             for card, state in zip(cards, stash_states(items, stash, remote_prefix))]
    loose = [item for item, card in zip(items, cards) if item["kind"] in TREES and not settled(card)]
    holding = {name for item in loose for name in item.get("held") or ()}
    detached = [item for item in loose if item.get("held") == set()]
    blind = any(not item.get("known") for item in detached)
    tips = sorted({item["tip"] for item in detached if item.get("known") and item.get("ahead") != 0})
    return [_held_card(item, card, holding, blind, tips, reaches, remote_prefix)
            for item, card in zip(items, cards)]


def _held_card(item: dict, card: dict, holding: set[str], blind: bool, tips: list[str],
               reaches: Callable[[str, str], bool], remote_prefix: str) -> dict:
    if item["kind"] not in BRANCHES or item.get("broken") or card["reason"]:
        return card
    if item["kind"] == "remote" and HEADS + item["ref"][len(remote_prefix):] in holding:
        why = "held_worktree"
    elif blind:
        why = "held_unknown"
    elif any(reaches(item["tip"], newer) for newer in tips):
        why = "held_detached"
    else:
        return card
    return {**card, "held": why, "reason": why, "overlay": False}
