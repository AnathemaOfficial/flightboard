# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The settings of one board, all from the command line: nothing is read from the observed repository's own files to
decide what to read, so an agent working there cannot widen what the board reads.

Every folder and name is checked as text here, before anything touches the disk: a worktree folder is a plain relative
path (no "..", no drive, no stream, no device name), a branch and a remote are names git allows and the board can pass
safely. Standard library only, safe under -I.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .files import RESERVED, WORKTREES
from .gitreads import REMOTE_NAME, is_ref
from .ledgers import KINDS, safe_path
from .messages import LANGS

PART = re.compile(r"[A-Za-z0-9._-]{1,100}")
BOUNDS = {"active_minutes": (1, 1440), "recent_minutes": (2, 10080), "stale_days": (1, 3650),
          "max_branches": (0, 500)}


@dataclass(frozen=True)
class Settings:
    """What one board reads, and how it words it."""

    lang: str = "en"
    ledger: str = "auto"  # auto, none, tasks or roadmap
    ledger_path: str | None = None  # relative to the repository; the kind's default when None
    main: str | None = None  # the main branch; main, then master, then the main checkout's branch when None
    remote: str = "origin"
    worktrees: tuple[tuple[str, ...], ...] = WORKTREES  # .claude/worktrees always, then the folders named
    kept: tuple[str, ...] = ()  # folders whose ignored files a merged session must not lose (say, notes)
    active_minutes: int = 15
    recent_minutes: int = 120
    stale_days: int = 14
    max_branches: int = 30

    def public(self) -> dict:
        """What the page may say about these settings: relative folders, names and numbers, never a machine path."""
        return {"worktrees": ["/".join(parts) for parts in self.worktrees], "remote": self.remote,
                "main": self.main or "", "active_minutes": self.active_minutes, "stale_days": self.stale_days,
                "kept": list(self.kept)}


def folder(text: str) -> tuple[str, ...] | None:
    """A folder relative to the repository, as its parts, when it is written plainly; None otherwise."""
    if not isinstance(text, str) or not text or "\0" in text or text.startswith(("/", "\\")):
        return None
    parts = tuple(part for part in text.replace("\\", "/").split("/") if part)
    if not parts or len(parts) > 6:
        return None
    for part in parts:
        if not PART.fullmatch(part) or part in (".", "..") or part.split(".")[0].strip().upper() in RESERVED \
                or part.endswith((".", " ")) or part.lower() == ".git":
            return None
    return parts


def branch(text: str) -> str | None:
    """A main branch name the board may give git, or None."""
    if not isinstance(text, str) or text.endswith((".lock", "/")) or text.startswith("-"):
        return None
    return text if is_ref("refs/heads/" + text) else None


def remote(text: str) -> str | None:
    return text if isinstance(text, str) and REMOTE_NAME.fullmatch(text) and ".." not in text else None


def ledger_path(text: str) -> str | None:
    found = safe_path(text)
    if found is None or any(part.split(".")[0].strip().upper() in RESERVED for part in found.split("/")):
        return None
    return found


def number(name: str, text: str) -> int | None:
    low, high = BOUNDS[name]
    return int(text) if isinstance(text, str) and text.isascii() and text.isdigit() and low <= int(text) <= high \
        else None


def valid(settings: Settings) -> bool:
    """Whether settings built by hand hold only what the command line would accept."""
    return settings.lang in LANGS and settings.ledger in KINDS \
        and (settings.ledger_path is None or ledger_path(settings.ledger_path) == settings.ledger_path) \
        and (settings.main is None or branch(settings.main) == settings.main) \
        and remote(settings.remote) == settings.remote \
        and all(folder("/".join(parts)) == parts for parts in settings.worktrees) \
        and all(folder(name) is not None for name in settings.kept)
