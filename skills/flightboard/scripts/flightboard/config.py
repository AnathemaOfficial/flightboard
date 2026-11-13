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
from pathlib import Path

from .files import MAX_WORKTREES, RESERVED, WORKTREES
from .gitreads import READING_BUDGET, REMOTE_NAME, is_ref
from .ledgers import KINDS, safe_path
from .messages import LANGS

PART = re.compile(r"[A-Za-z0-9._-]{1,100}")
BOUNDS = {"active_minutes": (1, 1440), "recent_minutes": (2, 10080), "stale_days": (1, 3650),
          "max_branches": (0, 500), "read_seconds": (12, 120), "max_worktrees": (1, 1000)}


@dataclass(frozen=True)
class Settings:
    """What one board reads, and how it words it."""

    lang: str = "en"
    ledger: str = "auto"  # auto, none, tasks or roadmap
    ledger_path: str | None = None  # relative to the repository; the kind's default when None
    main: str | None = None  # the main branch; main, then master, then the main checkout's branch when None
    remote: str = "origin"
    worktrees: tuple[tuple[str, ...], ...] = WORKTREES  # .claude/worktrees always, then the folders named
    external_worktrees: tuple[Path, ...] = ()  # explicit local roots only; never discovered from repository content
    kept: tuple[str, ...] = ()  # folders whose ignored files a merged session must not lose (say, notes)
    active_minutes: int = 15
    recent_minutes: int = 120
    stale_days: int = 14
    max_branches: int = 30
    read_seconds: int = int(READING_BUDGET)  # shared snapshot; each git run still has its own cap
    max_worktrees: int = MAX_WORKTREES  # registered admins, including those whose working files cannot be read

    def public(self) -> dict:
        """What the page may say about these settings: relative folders, names and numbers, never a machine path."""
        return {"worktrees": ["/".join(parts) for parts in self.worktrees], "remote": self.remote,
                "external_worktree_roots": len(self.external_worktrees),
                "main": self.main or "", "active_minutes": self.active_minutes, "stale_days": self.stale_days,
                "kept": list(self.kept), "read_seconds": self.read_seconds, "max_worktrees": self.max_worktrees}


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


def external_root(value: object) -> Path | None:
    """An explicit absolute local root, checked as text only; the file reader later checks every folder for links.

    Spaces in an owner-supplied root are allowed. Only the one or two plain components below it come from git.
    A network/device path, traversal, or a git admin folder is never an authorization to read worktree content.
    """
    if not isinstance(value, (str, Path)) or not str(value) or "\0" in str(value):
        return None
    text = str(value)
    if text.startswith(("//", "\\\\")):
        return None
    path = Path(text)
    if not path.is_absolute() or path == Path(path.anchor):
        return None
    for part in path.parts[1:]:
        if part in (".", "..") or part.lower() == ".git" or ":" in part \
                or part.split(".")[0].strip().upper() in RESERVED or part.endswith((".", " ")):
            return None
    return path


def remote(text: str) -> str | None:
    return text if isinstance(text, str) and REMOTE_NAME.fullmatch(text) and ".." not in text else None


def ledger_path(text: str) -> str | None:
    found = safe_path(text)
    if found is None or any(part.split(".")[0].strip().upper() in RESERVED for part in found.split("/")):
        return None
    return found


def number(name: str, text: str) -> int | None:
    low, high = BOUNDS[name]
    if not isinstance(text, str) or not text.isascii() or not text.isdigit():
        return None
    try:
        value = int(text)
    except ValueError:  # Python refuses excessively long digit strings too
        return None
    return value if low <= value <= high else None


def valid(settings: Settings) -> bool:
    """Whether settings built by hand hold only what the command line would accept."""
    return settings.lang in LANGS and settings.ledger in KINDS \
        and (settings.ledger_path is None or ledger_path(settings.ledger_path) == settings.ledger_path) \
        and (settings.main is None or branch(settings.main) == settings.main) \
        and remote(settings.remote) == settings.remote \
        and all(folder("/".join(parts)) == parts for parts in settings.worktrees) \
        and all(isinstance(path, Path) and external_root(path) == path for path in settings.external_worktrees) \
        and all(folder(name) is not None for name in settings.kept) \
        and type(settings.read_seconds) is int and BOUNDS["read_seconds"][0] <= settings.read_seconds \
        <= BOUNDS["read_seconds"][1] \
        and type(settings.max_worktrees) is int and BOUNDS["max_worktrees"][0] <= settings.max_worktrees \
        <= BOUNDS["max_worktrees"][1]
