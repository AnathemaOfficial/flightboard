# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Whether a repository's git configuration would lead git elsewhere, as the installed git itself reads it.

Before git runs on a repository, flightboard must know whether its configuration would lead git elsewhere: an include,
core.worktree, a partial clone's remote, a reftable or SHA-256 store. A reader that cuts lines its own way can be fooled
where git is not (a byte order mark, two headers on one line, a value carried on to the next line, a carriage return
alone), so no such reader is written here: the installed git, the one that runs every later command, reads the
configuration's bytes on its standard input (git config --file - --list), with no include followed, no system or
global configuration, and no repository around it. Its listing is read within GIT_TIMEOUT and up to
MAX_LISTING_BYTES: it repeats each key's whole section name, so a few kilobytes can list as gigabytes. What the board
weighs is what git reads; what git refuses to parse, or lists past that size, is refused, since the board cannot weigh
it. Standard library only, safe under -I.
"""
from __future__ import annotations

import os
import subprocess
import time

from . import gitreads as GIT
from . import processes

PROMISOR = "promisor"  # a partial clone's remote: git older than gitreads.NO_LAZY_FETCH may fetch from it
FALSE_WORDS = (b"false", b"no", b"off", b"0", b"")  # git reads these as false; any other spelling counts as true
# what Claude Code and git sparse-checkout (set, init, disable) write in a config.worktree: booleans only
WORKTREE_KEYS = frozenset({b"core.longpaths", b"core.sparsecheckout", b"core.sparsecheckoutcone", b"index.sparse"})
COMMAND = ("config", "--file", "-", "--no-includes", "--null", "--list")
# git's listing of a configuration of files.MAX_CONFIG_BYTES, with room to spare: past it, nothing is weighed
MAX_LISTING_BYTES = 4_000_000
CHUNK = 65_536
GRACE = 2.0  # seconds left to the pipes' threads once git is stopped: no second deadline is spent on them


class ConfigError(ValueError):
    """A configuration git itself refuses to read ("bad config line"), or one it lists past MAX_LISTING_BYTES."""


def _stop(proc: subprocess.Popen) -> None:
    """Request termination; the pipe runner owns the shared cleanup deadline."""
    try:
        proc.kill()
    except OSError:
        pass


def _listing(program: str, data: bytes, deadline: float | None = None) -> tuple[int, bytes]:
    """(exit code, listing) of git reading these bytes. One thread writes them and another reads git's output, so the
    deadline holds whatever git does with its pipes (subprocess.run, on Windows, writes all of its input before it
    counts time), and no more than MAX_LISTING_BYTES is ever kept. GitFailed when git cannot start or misses
    GIT_TIMEOUT, ConfigError when its listing passes MAX_LISTING_BYTES; git is stopped in both cases. GIT_DIR names the
    null device, so no repository is looked for anywhere, and the system and global configurations are left out."""
    env = {**GIT.environment(), "GIT_DIR": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    timeout = GIT.GIT_TIMEOUT if deadline is None else min(GIT.GIT_TIMEOUT, deadline - time.monotonic())
    if timeout <= 0:
        raise GIT.ReadingTooLong("the whole reading exceeded its time budget")
    try:
        code, output, _, over = processes.run([program, *COMMAND], env=env, cwd=os.path.dirname(program), stdin=data,
                                              timeout=timeout, limit=MAX_LISTING_BYTES, grace=GRACE, stop=_stop)
    except (OSError, ValueError) as exc:
        raise GIT.GitFailed(type(exc).__name__) from exc
    if over:
        raise ConfigError("its listing is too long")
    if code is None:
        raise GIT.GitFailed("TimeoutExpired")
    return code, output


def entries(data: bytes, deadline: float | None = None) -> list[tuple[bytes, bytes | None]]:
    """Every key git reads in this configuration, in order: (name, value), name being section[.subsection].key with
    the section and the key in lower case, as git gives them, and value None for a key with no "=". ConfigError where
    git refuses it (or lists it past MAX_LISTING_BYTES); GitFailed when git cannot be run, misses GIT_TIMEOUT, or
    cannot list even an empty configuration (a git too old to read one on its input, a broken install): then git is
    at fault, not the repository. The bytes go to git on its standard input, so nothing is written."""
    program = GIT.executable()
    if program is None:
        raise GIT.GitFailed("git not found")
    code, listing = _listing(program, data, deadline)
    if code != 0:
        if _listing(program, b"", deadline)[0] != 0:
            raise GIT.GitFailed(f"git config failed ({code})")
        raise ConfigError("git refuses it")
    if listing and not listing.endswith(b"\0"):
        raise ConfigError("its listing is incomplete")
    found = []
    for record in listing.split(b"\0")[:-1]:
        name, newline, value = record.partition(b"\n")  # with --null, a value follows its name after a line end
        found.append((name, value if newline else None))
    return found


def _parts(name: bytes) -> tuple[bytes, bytes]:
    """(section, key) of an entry's name; the subsection, which may hold dots, is left out."""
    stem, _, key = name.rpartition(b".")
    return stem.split(b".", 1)[0], key


def _false(value: bytes | None) -> bool:
    """Whether git reads this boolean as false. A key with no "=" is true, and an odd spelling counts as true."""
    return value is not None and value.lower() in FALSE_WORDS


def risky(data: bytes, deadline: float | None = None) -> str:
    """What in a repository configuration makes every git command read elsewhere (a code), or "": an include
    (include, includeIf), or core.worktree, which git resolves at each command on the repository folder; a reftable
    ref store (ref_storage), whose tables.list names the files git opens; a SHA-256 object store (object_format);
    config_unreadable where git itself would stop, or where its listing is too long to weigh. A partial clone's remote
    (PROMISOR: a promisor remote, a remote with a partial clone filter, extensions.partialClone) comes last, only when
    nothing worse is found: git may fetch a missing object from it through a program the configuration names, which
    the board allows only where git can be kept from fetching at all."""
    try:
        found = entries(data, deadline)
    except ConfigError:
        return "config_unreadable"
    return weigh(found)


def weigh(found: list[tuple[bytes, bytes | None]]) -> str:
    """The code risky gives for these entries, whoever read them."""
    promisor = False
    for name, value in found:
        section, key = _parts(name)
        if section in (b"include", b"includeif"):
            return "include"
        if section == b"core" and key == b"worktree":
            return "core_worktree"
        if section == b"extensions" and key == b"refstorage" and value != b"files":
            return "ref_storage"  # reftable: git opens every name its tables.list holds, ".." included
        if section == b"extensions" and key == b"objectformat" and value != b"sha1":
            # SHA-256 (or a value git refuses): the board's empty tree, a SHA-1 id, would be a ref name there, and the
            # .gitattributes of whatever commit a session named so would apply to every read
            return "object_format"
        if (section == b"remote" and (key == b"partialclonefilter" or (key == b"promisor" and not _false(value)))) \
                or (section == b"extensions" and key == b"partialclone"):
            promisor = True
    return PROMISOR if promisor else ""


def plain_worktree(data: bytes, deadline: float | None = None) -> bool:
    """A config.worktree that only sets core.longpaths, core.sparseCheckout, core.sparseCheckoutCone or index.sparse
    to true or false: nothing that could point git at a file, a program or a network share. GitFailed when git cannot
    tell (the caller decides what is left unread)."""
    try:
        found = entries(data, deadline)
    except ConfigError:
        return False
    return all(name in WORKTREE_KEYS and value is not None and value.lower() in (b"true", b"false")
               for name, value in found)
