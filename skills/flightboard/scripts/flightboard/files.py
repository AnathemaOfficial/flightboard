# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The files flightboard reads: where the worktrees are, and the few files read there.

Worktrees are found in the repository's own admin folders (.git/worktrees/<id>), never through `git worktree list`,
which checks every path it prints. A worktree folder is checked as text before anything touches it: it must be the
main checkout, a direct child of one of the worktree folders (.claude/worktrees unless the owner names others), or
an explicitly authorized local external root itself or one or two plain components below it. It must be written
plainly (no network share, no device path, no "..", no stream, no reserved name). Then every
folder on the way is checked for links, junctions and other reparse points. A folder that cannot be read stays listed
with its reason, its branch read from the object database alone. Before git runs on the repository, its own .git is
checked for what would lead every git command elsewhere (git_dir_problem; the installed git reads only a byte copy of
its configuration, outside any repository). Reasons are codes: the view words them.
Standard library only, safe under -I.
"""
from __future__ import annotations

import os
import re
import stat
import struct
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import gitconfig as GITCONFIG
from . import readio
from .gitreads import GitFailed, ReadingTooLong
from .text import clean

# Windows device names: as the last part of a path they name the device (lstat of a folder named nul answers the NUL
# device), in the middle of one a real folder
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                      *(f"{kind}{n}" for kind in ("COM", "LPT") for n in "0123456789¹²³")})
WORKTREES = ((".claude", "worktrees"),)  # the default worktree folders, as parts relative to the main checkout
MAX_LEDGER_BYTES = 5_000_000
MAX_SMALL_BYTES = 4096
MAX_DATED = 200
MAX_WORKTREES = 100
MAX_LIST_ENTRIES = 50_000
MAX_KEPT_ENTRIES = 2000
MAX_KEPT_DEPTH = 8
OPEN_WAITS = (0.0, 0.01, 0.05)
REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: links, junctions, cloud placeholders
# a folder name as the board accepts one: never ending with a dot, which Windows drops from the last part of a path
# but keeps in the middle of one (x.. names the folder x, while x..\sub names nothing)
SAFE_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9_-])?")
FULL_SHA = re.compile(r"[0-9a-f]{40}")  # SHA-1 only: the board reads no SHA-256 repository
MAX_PATH = 260  # Windows: git (core.longpaths off) reaches no path this long, and the board may not see one either
# open for reading only: never through a link where the system can tell (the final part), never waiting on a pipe
OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
HEAD_REF = re.compile(r"refs/heads/[^\x00-\x20\x7f~^:?*\x5b\x5c]{1,250}")  # what git allows in a branch name
OPERATIONS = (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
              ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"))
GONE = "gone"  # the reason of a worktree whose folder is gone: its admin folder stays until git prunes it


def _pure(text: str):
    return PureWindowsPath(text) if os.name == "nt" else PurePosixPath(text)


def _key(pure) -> list[str]:
    return [part.lower() for part in pure.parts] if os.name == "nt" else list(pure.parts)


def _fold(part: str) -> str:
    return part.lower() if os.name == "nt" else part


def fold(part: str) -> str:
    """A path part as this system compares it: case is ignored on Windows."""
    return _fold(part)


def plain_parts(pure) -> bool:
    """No "." or "..", no stream or second drive, no reserved device name, in any component after the anchor."""
    for part in pure.parts[1:]:
        if part in (".", "..") or ":" in part or "\0" in part:
            return False
        if part.split(".")[0].strip().upper() in RESERVED:
            return False
        if os.name == "nt" and part.endswith((".", " ")):
            return False
    return True


def check_worktree(text: str, root: Path, admin: Path | None = None,
                   parents: tuple[tuple[str, ...], ...] = WORKTREES,
                   external_roots: tuple[Path, ...] = ()) -> Path | None:
    """The worktree folder a gitdir file names (its "<folder>/.git"), when it may be read; None otherwise.
    Text only: nothing on disk is touched here."""
    text = text.rstrip(" \t\r\n")
    if not text or text.startswith(("//", "\\\\")) or "\0" in text:
        return None
    pure = _pure(text)
    if not pure.is_absolute():
        if admin is None:
            return None
        pure = _pure(os.path.normpath(os.path.join(str(admin), text)))  # the relative form: from the admin folder
        if str(pure).startswith(("//", "\\\\")) or not pure.is_absolute():
            return None
    if pure.name.lower() != ".git" or not plain_parts(pure):
        return None
    folder, base = pure.parent, _pure(str(root))
    if _key(folder) == _key(base):
        return Path(root)
    if SAFE_NAME.fullmatch(folder.name):
        for parent in parents:
            if _key(folder.parent) == _key(base) + [_fold(part) for part in parent]:
                return Path(root).joinpath(*parent, folder.name)
    for allowed in external_roots:
        boundary = _pure(str(allowed))
        if not boundary.is_absolute() or str(boundary).startswith(("//", "\\\\")) or not plain_parts(boundary):
            continue
        key, prefix = _key(folder), _key(boundary)
        parts = folder.parts[len(prefix):]
        if key[:len(prefix)] == prefix and len(parts) in (0, 1, 2) and all(SAFE_NAME.fullmatch(part) for part in parts):
            return Path(allowed).joinpath(*parts)
    return None


def worktree_boundary(tree: Path, root: Path, external_roots: tuple[Path, ...] = ()) -> Path:
    """The already-authorized boundary for a discovered worktree; never infer a new root from repository text."""
    for boundary in (Path(root), *(Path(path) for path in external_roots)):
        try:
            Path(tree).relative_to(boundary)
            return boundary
        except ValueError:
            continue
    return Path(root)  # a caller that did not authorize it gets failing no_link checks


def local_root(path: Path) -> bool:
    """An explicit absolute local directory reached from its anchor without any reparse point."""
    text = os.fspath(path)
    pure = _pure(text)
    return pure.is_absolute() and not text.startswith(("//", "\\\\")) and plain_parts(pure) \
        and readio.local_volume(Path(path)) and no_link(Path(path), Path(pure.anchor)) \
        and _folder_state(Path(path), Path(pure.anchor)) == "plain"


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)


def is_link(info: os.stat_result) -> bool:
    """Whether an lstat result is a link, a junction or another reparse point."""
    return _is_link(info)


def no_link(path: Path, root: Path) -> bool:
    """True when root and every folder from root down to path exist as plain folders, none a link, a junction or
    another reparse point, and path itself is a plain folder or a regular file. Never a device: Windows answers the
    lstat of a last part named nul with the NUL device, whatever is on disk (a junction included), while the same
    name in the middle of a path walks through it."""
    try:
        relative = Path(path).relative_to(root)
    except ValueError:
        return False
    current = Path(root)
    try:
        info = os.lstat(current)
        for part in relative.parts:
            if _is_link(info) or not stat.S_ISDIR(info.st_mode):
                return False
            if os.name == "nt" and _windows_odd(part):
                return False
            current = current / part
            info = os.lstat(current)
    except (OSError, ValueError):
        return False
    return not _is_link(info) and (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))


def _open_regular(path: Path, info: os.stat_result):
    """The file lstat saw at path, opened for reading, or None. A pipe put there meanwhile is never waited on, a link
    never followed where the system can tell, and what opened must be that same regular file."""
    try:
        descriptor = readio.open_file(path)
    except (OSError, ValueError):
        return None
    try:
        opened = os.fstat(descriptor)
        if not _is_link(opened) and stat.S_ISREG(opened.st_mode) \
                and (opened.st_ino, opened.st_dev) == (info.st_ino, info.st_dev):
            return os.fdopen(descriptor, "rb")
    except OSError:
        pass
    os.close(descriptor)
    return None


def read_small(path: Path, root: Path) -> str | None:
    """A small admin file (HEAD, gitdir, head-name), read only through plain folders and only if it is a regular
    file: a pipe planted there would otherwise hold the reading for good."""
    data, state = _read_file(path, root, MAX_SMALL_BYTES)
    return data.decode("utf-8", errors="replace").rstrip(" \t\r\n") if state == "ok" else None


def _head(admin: Path, root: Path) -> dict:
    """What HEAD names: {ref} for a branch, {sha} when detached, {} when unreadable."""
    data, state = _read_file(admin / "HEAD", root, MAX_SMALL_BYTES)
    if state != "ok":
        return {}
    text = data.rstrip(b" \t\r\n")
    if text.startswith(b"ref:"):
        branch = text[4:].lstrip(b" \t\r\n").split(b"\0", 1)[0].decode("utf-8", errors="replace")
        return {"ref": branch} if HEAD_REF.fullmatch(branch) else {}
    match = re.match(rb"[0-9A-Fa-f]{40}", text)
    after = text[40:41] if match else b"x"
    return {"sha": match.group().decode("ascii").lower()} if after in (b"", b"\0", b" ", b"\t", b"\r", b"\n") else {}


def _operation(admin: Path, root: Path) -> dict:
    """A rebase, merge, cherry-pick, revert or bisect in progress in this worktree, with the branch a rebase works on."""
    for name, kind in OPERATIONS:
        if no_link(admin / name, root):
            branch = None
            if kind == "rebase":
                text = read_small(admin / name / "head-name", root) or ""
                branch = text if HEAD_REF.fullmatch(text) else None
            return {"kind": kind, "branch": branch}
    return {"kind": "", "branch": None}


def _created(admin: Path, root: Path) -> float | None:
    """When the worktree was added: its admin folder's commondir file is written once, at that moment."""
    path = admin / "commondir"
    if not no_link(path, root):
        return None
    try:
        return os.lstat(path).st_mtime
    except OSError:
        return None


def _bytes(config: bytes | str) -> bytes:
    return config.encode("utf-8") if isinstance(config, str) else config


def plain_config(config: bytes | str, deadline: float | None = None) -> bool:
    """A config.worktree that only sets core.longpaths, core.sparseCheckout, core.sparseCheckoutCone or index.sparse
    to true or false, or codex.localenvironmentconfigpath to __none__, read as git reads it: nothing that could point
    git at a file, a program or a network share. The Codex marker is not opened as a path."""
    return GITCONFIG.plain_worktree(_bytes(config), deadline)


def plain_admin(admin: Path, root: Path, budget: Budget | None = None) -> bool:
    """An admin folder git may be pointed at: its commondir is "../..", none of the files git reads there in a worktree
    (its index and a split index's shared file, HEAD, the state of a merge or a rebase, its logs, a reftable store) is
    a link, and its config.worktree, if any, holds only the allowed booleans or Codex's exact no-environment marker.
    Other configuration remains refused."""
    common, state = _read_file(admin / "commondir", root, MAX_SMALL_BYTES)
    if state != "ok" or common.rstrip(b"\r\n") != b"../..":  # as git reads it: only CR and LF dropped at the end
        return False
    budget = budget or Budget()
    if _walk_problem(admin, ADMIN_SPOTS, root, budget)[0]:
        return False
    for name in ADMIN_ENTRIES:
        path = admin.joinpath(*name.split("/"))
        if _folder_state(path, root) == "link" or _special(path):
            return False
    if any(_linked_entry(admin / name, root, cap=MAX_GIT_FOLDER_ENTRIES) for name in ADMIN_FOLDERS) \
            or _linked_entry(admin, root, SHARED_INDEX, MAX_GIT_FOLDER_ENTRIES):
        return False
    data, state = _read_file(admin / "config.worktree", root, MAX_SMALL_BYTES)
    return state == "absent" or (data is not None and plain_config(data, budget.deadline))


def tracked_problem(tree: Path, root: Path, staged: list[tuple[str, str, str]]) -> str:
    """Why git status must not run in this worktree (a code), or "": git would read a .git it finds where the index
    expects a file (a tracked file turned into a folder) or a submodule (a gitlink), and follow it, a network share
    included; and a link or junction where the index expects a file or a folder would lead it outside the worktree."""
    checked: dict[str, str] = {}
    for item in staged:
        tag, mode, name = item if len(item) == 3 else ("H", *item)
        relative = PurePosixPath(name)
        if not safe_relative(name):
            return "odd_tracked_path"
        if tag.islower():
            return "assumed_tracked"
        path = Path(tree).joinpath(*relative.parts)
        if os.name == "nt" and len(str(path).encode("utf-16-le", "surrogatepass")) // 2 >= MAX_PATH:
            # git, kept to short paths (counted in UTF-16 units), cannot read it; nor may the board, which would take
            # it for a deleted file
            return "long_tracked_path"
        folder = str(relative.parent)
        if folder not in checked:
            checked[folder] = _folder_state(Path(tree).joinpath(*relative.parent.parts), root)
        if checked[folder] == "gone":
            continue  # its folder is gone: git sees deleted files, and looks for nothing in them
        if checked[folder] != "plain":
            return "tracked_link_folder"
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            return "tracked_unreadable"
        if mode == "160000":
            if _is_link(info):  # checked first: its .git is never looked for through a link
                return "submodule_link"
            if stat.S_ISDIR(info.st_mode) and _exists(path / ".git"):
                return "submodule_git"
        elif stat.S_ISDIR(info.st_mode) or (mode != "120000" and _is_link(info)):
            return "tracked_replaced"
        if tag == "S":
            return "skipped_tracked"
    return ""


def _exists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except OSError:
        return False


def _special(path: Path) -> bool:
    """Whether path is a pipe, a socket or a device: where git expects a file, it would wait on it or misread it."""
    try:
        info = os.lstat(path)
    except (OSError, ValueError):
        return False
    return not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or _is_link(info))


def ignore_file_special(tree: Path, root: Path, names: list[str]) -> bool:
    """Whether git check-ignore, asked about these names, would open a .gitignore that is a pipe, a socket or a device
    (it waits on a pipe until its time limit), or one past a link: the worktree's own, the one of every folder on the
    way to each name, and an asked folder's own."""
    folders: set[tuple[str, ...]] = {()}
    for name in names:
        parts = tuple(part for part in name.split("/") if part)
        upto = parts if name.endswith("/") else parts[:-1]
        folders.update(upto[:end] for end in range(1, len(upto) + 1))
    for parts in folders:
        folder = Path(tree).joinpath(*parts)
        state = _folder_state(folder, root)
        if state == "link" or (state == "plain" and not _regular_or_absent(folder / ".gitignore")):
            return True
    return False


def _regular_or_absent(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(info.st_mode) and not _is_link(info)


def _folder_state(path: Path, root: Path) -> str:
    """plain: root and every folder down to path exist, none a link; gone: one is missing or is now a file, so what
    it held is deleted; link: a link, a junction or an unreadable entry on the way. Each step is an lstat of the
    entry itself: nothing is ever looked at through a link."""
    try:
        relative = Path(path).relative_to(root)
    except ValueError:
        return "link"
    current = Path(root)
    for part in ("", *relative.parts):
        if part and os.name == "nt" and _windows_odd(part):
            return "link"
        current = current / part if part else current
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return "gone"
        except OSError:
            return "link"
        if _is_link(info):
            return "link"
        if not stat.S_ISDIR(info.st_mode):
            return "gone" if stat.S_ISREG(info.st_mode) else "link"
    return "plain"


def folder_state(path: Path, root: Path) -> str:
    """plain, gone or link (see _folder_state)."""
    return _folder_state(path, root)


def _linked_entry(folder: Path, root: Path, prefix: str = "", cap: int | None = None) -> str:
    """"link" when one direct entry of folder (whose name starts with prefix, in any case: a volume may ignore case)
    is a link, a junction or cannot be told, "special" when one is a pipe, a socket or a device (git would wait on
    it), "many" when the folder holds more than cap entries; "" when it holds none of these, or is absent. A link on
    the folder itself is for its caller to refuse: here it reads as absent, so that nothing is ever listed through it.
    git removes some of these folders and entries as it works (a rebase ending, a lock renamed, packs repacked): an
    entry gone since the listing is skipped, and a folder that fails to list is looked at again a little later
    (Windows denies a folder git is deleting), refused only when every look fails."""
    for wait in LIST_WAITS:
        if wait:
            time.sleep(wait)
        if _folder_state(folder, root) != "plain":
            return ""
        try:
            with os.scandir(folder) as found:
                for count, entry in enumerate(found):
                    if cap is not None and count >= cap:
                        return "many"
                    if not entry.name.casefold().startswith(prefix):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # removed since the listing: nothing is left there to follow
                    if _is_link(info):
                        return "link"
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                        return "special"
            return ""
        except OSError:
            continue  # gone or being removed meanwhile: looked at again
    return "link"


def _admin_of(root: Path):
    """The admin folder a worktree's .git file names, checked as text (an absolute, plain .git/worktrees/<id>), or
    None: root is then no worktree, or an odd one."""
    marker = Path(root) / ".git"
    try:
        info = os.lstat(marker)
    except OSError:
        return None
    if _is_link(info) or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SMALL_BYTES:
        return None
    handle = _open_regular(marker, info)
    if handle is None:
        return None
    try:
        with handle:
            text = handle.read(MAX_SMALL_BYTES).decode("utf-8", errors="replace").rstrip(" \t\r\n")
    except OSError:
        return None
    if not text.startswith("gitdir: "):
        return None
    admin_text = text[len("gitdir: "):].rstrip(" \t\r\n")
    if not admin_text or admin_text.startswith(("//", "\\\\")):
        return None
    if not _pure(admin_text).is_absolute():
        admin_text = os.path.normpath(os.path.join(str(root), admin_text))
    admin = _pure(admin_text)
    parts = [_fold(part) for part in admin.parts]
    if not admin.is_absolute() or str(admin).startswith(("//", "\\\\")) or not plain_parts(admin) \
            or len(parts) < 4 or parts[-3:-1] != [".git", "worktrees"] or not SAFE_NAME.fullmatch(admin.name):
        return None
    return admin


HEAD_TEXT = re.compile(rb"ref:[ \t\n\r]*refs/|[0-9a-fA-F]{40}")  # how a HEAD starts: a symbolic ref, or an object id


def git_folder(root: Path) -> bool:
    """Whether root holds its own git folder, a HEAD, an objects folder and a refs folder, as gitrepository-layout(5)
    describes one, told by lstat and one small read, never through a link: .git a plain folder whose HEAD is a plain
    file naming refs/ or holding an object id, with plain objects and refs folders, and no commondir. git's search for
    a repository then stops at root, as the board's does: the repository is root, and nothing else. Anything else (a
    .git file, a link, an empty or odd .git folder, none at all) is a repository the board cannot read, nor tell the
    extent of."""
    common = Path(root) / ".git"
    if any(_folder_state(common / name, root) != "plain" for name in ("objects", "refs")) \
            or _exists(common / "commondir"):
        return False
    head, state = _read_file(common / "HEAD", root, MAX_SMALL_BYTES)
    return state == "ok" and HEAD_TEXT.match(head) is not None


def top_folder(start: Path) -> Path:
    """The folder of start's repository, as git finds it: start, or its nearest parent that holds a .git entry, by
    lstat only (a .git that is a link is found, then refused like any other). start itself when none does."""
    start = Path(start)
    for folder in (start, *start.parents):
        try:
            os.lstat(folder / ".git")
            return folder
        except FileNotFoundError:
            continue
        except OSError:
            return folder  # something is there that cannot be told: the checks to come refuse it
    return start


def main_checkout(root: Path, parents: tuple[tuple[str, ...], ...] = WORKTREES,
                  external_roots: tuple[Path, ...] = ()) -> Path:
    """The main checkout root belongs to: root itself, or, when root is a worktree (its .git is a file), the checkout
    its admin folder names. Text checks first, as for any worktree; root when anything is odd."""
    root = Path(root)
    admin = _admin_of(root)
    if admin is None:
        return root
    named = Path(str(admin.parent.parent.parent))
    if check_worktree((root / ".git").as_posix(), named, parents=parents, external_roots=external_roots) != root:
        return root  # root must be one of main's own session folders, as written
    # root's own parent at that depth, never the folder the text names: case folding may match two folders the disk
    # keeps apart (str.lower turns the Kelvin sign into k, NTFS does not), and root's parents are resolved
    external = worktree_boundary(root, named, external_roots) != named
    if external:
        boundary = worktree_boundary(root, named, external_roots)
        if not local_root(boundary) or not no_link(root, boundary) or not local_root(named):
            return root
        main = named
        actual_admin = main / ".git" / "worktrees" / admin.name
        target = check_worktree(read_small(actual_admin / "gitdir", main) or "", main, actual_admin, parents,
                                external_roots)
        if target != root or not _worktree_marker(root, actual_admin, boundary):
            return root
    else:
        main = Path(*root.parts[:len(named.parts)])
    return main if no_link(main / ".git", main) and (main / ".git").is_dir() else root


def _worktree_marker(tree: Path, admin: Path, boundary: Path) -> bool:
    """The worktree's own plain .git file must point back to the admin folder that registered it."""
    text = read_small(Path(tree) / ".git", boundary)
    if text is None or not text.startswith("gitdir:"):
        return False
    value = text[len("gitdir:"):].lstrip(" \t")
    if not value or value.startswith(("//", "\\\\")) or "\0" in value:
        return False
    pure = _pure(value)
    if not pure.is_absolute():
        pure = _pure(os.path.normpath(os.path.join(str(tree), value)))
    return pure.is_absolute() and plain_parts(pure) and _key(pure) == _key(_pure(str(admin)))


def attributes_planted(root: Path) -> bool:
    """True when the repository's own info/attributes holds anything, or cannot be told: it could name a filter
    program that git status would start, so modified files are then not read at all. Never looked at through a
    link."""
    path = Path(root) / ".git" / "info" / "attributes"
    folder = _folder_state(path.parent, root)
    if folder != "plain":
        return folder != "gone"
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return _is_link(info) or info.st_size > 0


# what git opens on the repository at the commands flightboard runs: a link there leads git elsewhere. The state of a
# merge, a cherry-pick, a revert, a bisect or a rebase is read by git status; shallow by any walk of the history (a
# grafts file is never read: GIT_GRAFT_FILE names the empty device). A link on another file git opens by name stays
# possible (see SECURITY.md): one loose object, one ref or reflog file inside a folder of branches, or any entry of
# .git or of an admin folder that a symbolic ref ("ref: <name>") or a reflog line names (git status, in a detached
# worktree, looks up the name its last checkout moved to). It is the finer trap no reader of .git can rule out without
# opening everything.
STATE_ENTRIES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "AUTO_MERGE", "ORIG_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                 "REBASE_HEAD", "SQUASH_MSG", "FETCH_HEAD", "BISECT_LOG", "BISECT_START", "BISECT_HEAD", "BISECT_TERMS",
                 "BISECT_EXPECTED_REV", "rebase-merge", "rebase-apply", "sequencer", "logs/HEAD")
GIT_ENTRIES = ("config", "config.worktree", "HEAD", "index", "packed-refs", "shallow", "info", "info/exclude",
               "info/attributes", "info/sparse-checkout", "info/grafts", "objects", "objects/info",
               "objects/info/commit-graphs", "objects/pack", "objects/pack/multi-pack-index.d", "refs", "refs/heads",
               "refs/remotes", "reftable", "logs", "logs/refs", "logs/refs/heads", "logs/refs/remotes", "worktrees",
               *STATE_ENTRIES)
# the same for a worktree's own admin folder (.git/worktrees/<id>)
ADMIN_ENTRIES = ("HEAD", "index", "gitdir", "commondir", "config.worktree", "info", "info/sparse-checkout", "logs",
                 "reftable", *STATE_ENTRIES)
# folders git opens what they hold: none of their direct entries may be a link either (each folder is itself one of
# the entries above, or a direct entry of one of these). Their entries are many only in an odd repository: past
# MAX_GIT_FOLDER_ENTRIES, it is refused ("many"). The folders of branches and of their reflogs are the exception: a
# big repository may hold that many, and they are listed in full, as git itself opens them. The remote's own folders
# are added for the remote the board reads.
STATE_FOLDERS = ("rebase-merge", "rebase-apply", "sequencer")
ADMIN_FOLDERS = (*STATE_FOLDERS, "reftable")
GIT_FOLDERS = ("refs", "refs/remotes", "objects", "objects/info", "objects/info/commit-graphs", "objects/pack",
               "objects/pack/multi-pack-index.d", "reftable", "logs/refs", "logs/refs/remotes", *STATE_FOLDERS)
BRANCH_FOLDERS = ("refs/heads", "logs/refs/heads")
SHARED_INDEX = "sharedindex."  # the shared part of a split index, next to the index that names it
MAX_GIT_FOLDER_ENTRIES = 50_000
MAX_GIT_ENTRIES = 50_000  # one shared preflight budget, including all worktree admin folders
LIST_WAITS = (0.0, 0.02, 0.05, 0.1)  # seconds before each look at a folder that fails to list (Windows: ~20 ms)
PROMISOR = GITCONFIG.PROMISOR  # a partial clone's remote: git older than gitreads.NO_LAZY_FETCH may fetch from it
MAX_CONFIG_BYTES = 1_000_000
GRAPH_CHAIN = re.compile(rb"(?:[0-9a-f]{40}\n)+")  # what git writes in a commit-graph chain: one id per line
MAX_CHAIN_BYTES = 41 * 1000
SPARSE_MARK = b"sdir"  # the index extension of a sparse index (sparse directories)
SPLIT_MARK = b"link"  # the index extension of a split index, naming its shared part
MAX_INDEX_BYTES = 64_000_000
# one reflog line as git reads it: old id, new id, who, when, then the reason after a tab (or whatever follows)
REFLOG_LINE = re.compile(rb"([0-9a-f]{40}) ([0-9a-f]{40}) [^\n>]*> ([1-9][0-9]{0,11}) [+-][0-9]{4}"
                         rb"(?:\t([^\n]*)|([^\n]*))")
NULL_SHA = b"0" * 40
MAX_REFLOG_BYTES = 2_000_000  # the newest part of a long reflog
GIT_SPOTS = (("", False), ("refs", True), ("logs", True),
             *((name, False) for name in (*STATE_FOLDERS, "objects", "objects/info", "objects/info/commit-graphs",
                                          "objects/pack", "objects/pack/multi-pack-index.d", "reftable")))
ADMIN_SPOTS = (("", False), ("refs", True), ("logs", True),
               *((name, False) for name in (*STATE_FOLDERS, "info", "reftable")))


class Budget:
    """Entries and time shared by the repository preflight and every admin folder of one snapshot."""

    def __init__(self, entries: int | None = None, deadline: float | None = None) -> None:
        self.left = MAX_GIT_ENTRIES if entries is None else entries
        self.deadline = deadline

    def check(self) -> None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise ReadingTooLong("the whole reading exceeded its time budget")


class TooManyWorktrees(GitFailed):
    """The admin entry count is past the limit; no session may silently disappear."""


def _entry_kind(entry: os.DirEntry) -> str:
    if os.name == "nt" and _windows_odd(entry.name):
        return "name"
    try:
        info = entry.stat(follow_symlinks=False)
    except FileNotFoundError:
        return "gone"
    except OSError:
        return "unreadable"
    if _is_link(info):
        return "link"
    if stat.S_ISDIR(info.st_mode):
        return "folder"
    return "file" if stat.S_ISREG(info.st_mode) else "special"


def _walk_problem(base: Path, spots: tuple[tuple[str, bool], ...], root: Path,
                  budget: Budget) -> tuple[str, str]:
    """Check direct admin entries and recursively every ref/log, charging every listed entry to one budget."""
    for spot, deep in spots:
        stack = [base / spot if spot else base]
        while stack:
            budget.check()
            folder = stack.pop()
            state = _folder_state(folder, root)
            if state == "gone":
                continue
            if state != "plain":
                return "link", spot
            listed = _entries(folder)
            if listed is None:
                return "link", spot
            for entry in listed:
                budget.check()
                budget.left -= 1
                if budget.left < 0:
                    return "many", spot
                kind = _entry_kind(entry)
                if kind in ("link", "special", "name", "unreadable"):
                    return ("link" if kind == "unreadable" else kind), spot
                if kind == "folder" and deep:
                    stack.append(Path(entry.path))
    return "", ""


def risky_config(config: bytes | str, deadline: float | None = None) -> str:
    """What in a repository configuration makes every git command read elsewhere (a code), or "": see
    gitconfig.risky, which reads it as git does. PROMISOR comes last, only when nothing worse is found."""
    return GITCONFIG.risky(_bytes(config), deadline)


def _read_file(path: Path, root: Path, limit: int) -> tuple[bytes | None, str]:
    """A file read through plain folders only: (data, state), state being ok, absent, too_big or unreadable."""
    data, state, _ = _read_regular(path, root, limit)
    return data, state


def _read_regular(path: Path, root: Path, limit: int) -> tuple[bytes | None, str, os.stat_result | None]:
    """Retry a rename race from lstat, never reusing an identity from a previous open."""
    info = None
    for wait in OPEN_WAITS:
        if wait:
            time.sleep(wait)
        data, state, info = _read_once(path, root, limit)
        if state != "retry":
            return data, state, info
    return None, "unreadable", info


def _read_once(path: Path, root: Path, limit: int) -> tuple[bytes | None, str, os.stat_result | None]:
    if not no_link(Path(path).parent, root):
        return None, "unreadable", None
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, "absent", None
    except OSError:
        return None, "unreadable", None
    if _is_link(info) or not stat.S_ISREG(info.st_mode):
        return None, "unreadable", None
    if info.st_size > limit:
        return None, "too_big", info
    handle = _open_regular(path, info)
    if handle is None:
        return None, "retry", info
    try:
        with handle:
            data = handle.read(limit + 1)
    except OSError:
        return None, "retry", info
    return (None, "too_big", info) if len(data) > limit else (data, "ok", info)


def git_dir_problem(root: Path, remote: str = "origin", budget: Budget | None = None) -> str:
    """Why git must not run on this repository at all (a code; "link:<entry>", "special:<entry>", "many:<folder>" and
    "config_unreadable:<name>" name what), or "". At every command git follows a link planted on one of its own
    entries, an included configuration file, core.worktree, a commondir file and a borrowed object store
    (objects/info/alternates), a network share included, and waits on a pipe planted where it expects a file. Checked
    with lstat and small reads, never through a link; the bytes of config and config.worktree are then read by the
    installed git itself, outside any repository (gitconfig.py). GitFailed when git cannot read them.
    Finer traps inside .git stay possible: any git run on this repository meets them too (see SECURITY.md). PROMISOR,
    the last code, is for the caller to weigh against git's version. remote is the remote the board reads, a name
    checked as text."""
    common = Path(root) / ".git"
    budget = budget or Budget()
    budget.check()
    for name in GIT_ENTRIES:
        path = common.joinpath(*name.split("/"))
        if _folder_state(path.parent, root) == "plain" and _special(path):
            return f"special:{name}"
        if _folder_state(path, root) == "link":
            return f"link:{name}"
    # the folder is named, never the entry: an entry's name is the repository's own text
    folders = [*((name, MAX_GIT_FOLDER_ENTRIES) for name in GIT_FOLDERS),
               *((name, None) for name in (*BRANCH_FOLDERS, f"refs/remotes/{remote}", f"logs/refs/remotes/{remote}"))]
    for name, cap in folders:
        budget.check()
        found = _linked_entry(common.joinpath(*name.split("/")), root, cap=cap)
        if found:
            return f"{found}:{name}"
    found = _linked_entry(common, root, SHARED_INDEX, MAX_GIT_FOLDER_ENTRIES)
    if found:
        return "link:sharedindex" if found == "link" else f"{found}:.git"
    found, spot = _walk_problem(common, GIT_SPOTS, root, budget)
    if found:
        return f"{found}:{spot or '.git'}"
    if _exists(common / "commondir"):
        return "commondir"
    try:
        info = os.lstat(common / "objects" / "info" / "alternates")
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            return "alternates_unreadable"
        if info.st_size > 0:
            return "alternates"
    except FileNotFoundError:
        pass
    except OSError:
        return "alternates_unreadable"
    weighed = ""
    for name in ("config", "config.worktree"):
        data, state = _read_file(common / name, root, MAX_CONFIG_BYTES)
        if state in ("too_big", "unreadable"):
            return f"config_unreadable:{name}"
        if data is None:
            continue
        found = risky_config(data, budget.deadline) if name == "config" \
            else ("" if plain_config(data, budget.deadline) else "main_worktree_config")
        if found == "config_unreadable":  # git itself would stop on it
            return f"config_unreadable:{name}"
        if found == PROMISOR:
            weighed = found  # never hides a worse problem found later
        elif found:
            return found
    return weighed


def commit_graph_plain(root: Path) -> bool:
    """Whether git may read the repository's commit-graph: it holds no chain of graphs, or a chain whose every line is
    a full object id, read through plain folders. git opens "graph-<line>.graph" for each line as written, ".."
    included; the graphs themselves name no other file. Anything else, and the reading leaves the commit-graph off
    (slower on a very long history, never elsewhere)."""
    chain = Path(root) / ".git" / "objects" / "info" / "commit-graphs" / "commit-graph-chain"
    folder = _folder_state(chain.parent, root)
    if folder != "plain":
        return folder == "gone"  # no folder of graphs: no chain to read
    data, state = _read_file(chain, root, MAX_CHAIN_BYTES)
    return state == "absent" or (state == "ok" and GRAPH_CHAIN.fullmatch(data) is not None)


def _varint(data: bytes, position: int, end: int, most: int) -> tuple[int | None, int]:
    """The variable-width integer at position, in the offset encoding gitformat-pack(5) describes, which an index of
    version 4 uses for the part of the previous name to drop (gitformat-index(5)): (value, the position after it);
    None when it is cut, or once it passes most, which no longer byte can bring back (and a run of continuation bytes
    is read in a few steps, never in quadratic time)."""
    value = None
    while position < end:
        byte = data[position]
        position += 1
        value = (byte & 127) if value is None else ((value + 1) << 7) + (byte & 127)
        if value > most:
            return None, position
        if not byte & 128:
            return value, position
    return None, position


def _entries_end(data: bytes, end: int) -> tuple[int, bool] | None:
    """Where the entries of an index file (version 2, 3 or 4) end, walked one after the other as gitformat-index(5)
    lays them out (a name's length is the one its flags give below 0xFFF, not where a NUL falls), and whether one of
    them is a folder: git takes an index holding one for a sparse index, whatever its extensions say. None when they
    do not lie so."""
    version, count = struct.unpack_from(">II", data, 4)
    if version not in (2, 3, 4):
        return None
    position, previous, folder = 12, 0, False
    for _ in range(count):
        if position + 62 > end:
            return None
        folder = folder or struct.unpack_from(">I", data, position + 24)[0] & 0o170000 == 0o040000
        flags = struct.unpack_from(">H", data, position + 60)[0]
        name = position + 62 + (2 if flags & 0x4000 else 0)  # the extended flags git reads whatever the version
        length = flags & 0xFFF
        if version == 4:  # the name is cut from the previous one: a varint, then the rest of it and a NUL
            strip, name = _varint(data, name, end, previous)
            if strip is None:
                return None
            kept = previous - strip
            if length == 0xFFF:
                nul = data.find(b"\0", name, end)
                if nul < 0:
                    return None
                length = nul - name + kept
            if length < kept:
                return None
            position, previous = name + length - kept + 1, length
        else:
            if length == 0xFFF:
                nul = data.find(b"\0", name, end)
                if nul < 0:
                    return None
                length = nul - name
            position = (name - position + length + 8 & ~7) + position
    return (position, folder) if position <= end else None


def _extensions(data: bytes, start: int, end: int) -> dict[bytes, list[int]] | None:
    """The extensions from start, each a 4-byte signature, a 32-bit size, then its data (gitformat-index(5)):
    {signature: where each one's data starts}. None unless they lie back to back up to the trailing hash, as git
    writes them: a size that runs past it could send git's reading somewhere the board never looked."""
    found: dict[bytes, list[int]] = {}
    while start <= end - 8:
        size = struct.unpack_from(">I", data, start + 4)[0]
        found.setdefault(bytes(data[start:start + 4]), []).append(start + 8)
        start += 8 + size
    return found if start == end else None


def index_state(git_dir: Path, root: Path) -> str:
    """"" when git may read the index of this git folder; "sparse" for a sparse index (the sdir extension, or one entry
    that is a folder), which git expands at every read, writing its trees into .git/objects and touching the objects
    already there, a link planted on one included; "split" for a split index, whose shared part git touches at every
    read; "too_big" past MAX_INDEX_BYTES; "unreadable" when the board cannot tell. Only "" lets git read it. The
    board walks the whole index as git does with one thread (gitreads.SETTINGS: index.threads=1), never through a
    link."""
    data, state = _read_file(Path(git_dir) / "index", root, MAX_INDEX_BYTES)
    if state == "absent":
        return ""
    if state != "ok":
        return state if state == "too_big" else "unreadable"
    end = len(data) - 20  # the trailing SHA-1: the board reads no SHA-256 repository
    walked = _entries_end(data, end) if end >= 12 and data[:4] == b"DIRC" else None
    found = _extensions(data, walked[0], end) if walked is not None else None
    if found is None:
        return "unreadable"
    if walked[1] or SPARSE_MARK in found:
        return "sparse"
    places = found.get(SPLIT_MARK, [])
    if any(data[place:place + 20].strip(b"\0") for place in places):
        return "split"  # a split index with a shared part: git reads that part, and resets its time
    return ""


def read_reflog(root: Path, ref: str, limit: int, whole: bool = False) -> list[dict] | None:
    """A branch's reflog, read here rather than by git (finding no entry it can read, git would look up other names,
    refs/tags/<name> and the like, and follow a link planted there): its newest entries first, {sha, at, via}, at most
    limit of them, from its newest MAX_REFLOG_BYTES. Read through plain folders only; a line REFLOG_LINE does not
    match is skipped, and so may be an odd one git would take."""
    parts = ref.split("/")
    if any(part in ("", ".", "..") or (os.name == "nt" and _windows_odd(part)) for part in parts):
        return []
    path = Path(root).joinpath(".git", "logs", *parts)
    return _read_log(path, root, limit, whole)


def read_head_log(git_dir: Path, root: Path, limit: int) -> list[dict] | None:
    # Discarding an old or incomplete checkout can hide a detached commit: the whole bounded log is needed.
    return _read_log(Path(git_dir) / "logs" / "HEAD", root, limit, True)


def _read_log(path: Path, root: Path, limit: int, whole: bool) -> list[dict] | None:
    if _folder_state(path.parent, root) == "gone":
        return []
    if whole:
        data, state = _read_file(path, root, MAX_REFLOG_BYTES)
    else:
        data, state = _read_tail(path, root, MAX_REFLOG_BYTES)
    if data is None:
        return [] if state == "absent" else None
    lines = data.split(b"\n")
    if whole and lines[-1]:
        return None
    entries = []
    for line in reversed(lines[:-1]):
        match = REFLOG_LINE.fullmatch(line)
        if match is None:
            if whole and line:
                return None
            continue
        if match.group(2) == NULL_SHA:
            continue
        if len(entries) >= limit:
            if whole:
                return None
            break
        reason = match.group(4) if match.group(4) is not None else match.group(5)
        entries.append({"sha": match.group(2).decode("ascii"), "at": int(match.group(3)),
                        "via": reason.decode("utf-8", errors="replace")})
    return entries


def _read_tail(path: Path, root: Path, limit: int) -> tuple[bytes | None, str]:
    for wait in OPEN_WAITS:
        if wait:
            time.sleep(wait)
        if not no_link(path.parent, root):
            return None, "unreadable"
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None, "absent"
        except (OSError, ValueError):
            return None, "unreadable"
        if _is_link(info) or not stat.S_ISREG(info.st_mode):
            return None, "unreadable"
        handle = _open_regular(path, info)
        if handle is None:
            continue
        try:
            with handle:
                start = max(0, os.fstat(handle.fileno()).st_size - limit)
                handle.seek(max(0, start - 1))
                data = handle.read(limit + (1 if start else 0))
        except OSError:
            continue
        if start:
            end = data.find(b"\n")
            data = data[end + 1:] if end >= 0 else b""
        return data, "ok"
    return None, "unreadable"


def _entries(folder: Path) -> list[os.DirEntry] | None:
    """The entries of a folder: [] when it is gone (or is now a file), None when it is there but cannot be listed
    (never taken for an empty folder: what it holds is unknown). A folder git is deleting is looked at again a little
    later (Windows denies it for a moment)."""
    for wait in LIST_WAITS:
        if wait:
            time.sleep(wait)
        try:
            with os.scandir(folder) as found:
                entries = []
                for entry in found:
                    if len(entries) >= MAX_LIST_ENTRIES:
                        return None
                    entries.append(entry)
                return entries
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError:
            continue
    return None


def _plain_entry(entry: os.DirEntry) -> bool:
    try:
        return not _is_link(entry.stat(follow_symlinks=False))
    except OSError:
        return False


def untracked(tree: Path, root: Path, tracked: set[str], limit: int = MAX_DATED) -> list[str] | None:
    """Untracked candidates, relative to the worktree: files beside tracked ones, and new folders as one entry ending
    with "/". Only folders that hold tracked files are listed, never through a link; an entry named .git is never
    opened, and a new folder is never entered (so a nested .git file there is never read). A tracked name that is not
    a plain relative path (an index written by hand) is left out: it never leads the walk outside the worktree. A
    tracked folder (a submodule) is never a new folder. None when one of those folders cannot be listed: what it holds
    is unknown, never nothing."""
    tracked = {name for name in tracked if safe_relative(name)}
    known_folders: set[str] = set()
    for name in tracked:
        parent = PurePosixPath(name).parent
        while str(parent) not in ("", "."):
            known_folders.add(str(parent))
            parent = parent.parent
    found: list[str] = []
    for folder in sorted({""} | known_folders):
        path = Path(tree).joinpath(*folder.split("/")) if folder else Path(tree)
        if folder and not no_link(path, root):
            continue
        listed = _entries(path)
        if listed is None:
            return None
        for entry in listed:
            if entry.name == ".git":
                continue
            relative = f"{folder}/{entry.name}" if folder else entry.name
            kind = _entry_kind(entry)
            if kind == "gone":
                continue
            if kind == "folder" and relative not in known_folders and relative not in tracked:
                found.append(relative + "/")
            elif kind != "folder" and relative not in tracked:
                found.append(relative)
            if len(found) > limit:
                return None  # ignored candidates must never hide unknown untracked work after this boundary
    return found


def children(tree: Path, root: Path, folder: str, limit: int = MAX_DATED, depth: int = 3) -> dict | None:
    """The content of a new folder, a few levels deep, to learn whether all of it is ignored: its leaves ("folder/name",
    and "folder/sub/" past the last level), the folders walked through ("folder/sub/"), and the sealed folders, those
    holding a .git: never entered nor handed to git, they count as ignored only under an ignored folder. None when it
    cannot be told: too many entries, a link, a folder that cannot be listed, or a .git right in the folder."""
    found: dict = {"leaves": [], "folders": [], "sealed": []}
    stack = [(folder.rstrip("/"), 1)]
    while stack:
        current, level = stack.pop()
        path = Path(tree).joinpath(*current.split("/"))
        if not no_link(path, root):
            return None
        listed = _entries(path)
        if listed is None:
            return None
        for entry in listed:
            kind = "" if entry.name == ".git" else _entry_kind(entry)
            if kind not in ("folder", "file", "special"):
                return None
            relative = f"{current}/{entry.name}"
            if kind != "folder":
                found["leaves"].append(relative)
            elif _exists(Path(entry.path) / ".git"):
                found["sealed"].append(relative + "/")
            elif level < depth:
                found["folders"].append(relative + "/")
                stack.append((relative, level + 1))
            else:
                found["leaves"].append(relative + "/")
            if sum(len(names) for names in found.values()) > limit:
                return None
    return found


def all_ignored(found: dict, ignored: set[str]) -> bool:
    """Whether everything children() found is ignored: each leaf itself or by an ignored folder above it, each sealed
    folder by an ignored folder above it (it is never asked about). An empty folder is ignored too: git never shows
    it."""
    above = [name for name in found["folders"] if name in ignored]

    def covered(name: str) -> bool:
        return any(name.startswith(folder) for folder in above)

    return all(name in ignored or covered(name) for name in found["leaves"]) \
        and all(covered(name) for name in found["sealed"])


def kept_count(tree: Path, root: Path, tracked: set[str], folders: tuple[str, ...], limit: int = 500) -> int:
    """Files under the kept folders (say, an ignored notes folder) that the index does not hold: work an agent must
    not lose, counted without following a link and without opening any file."""
    total, seen = 0, 0
    for top in folders:
        stack = [(Path(tree).joinpath(*top.split("/")), 0)]
        while stack and total < limit:
            folder, depth = stack.pop()
            if not no_link(folder, root):
                if _folder_state(folder, root) != "gone":
                    total = max(total, 1)
                continue
            listed = _entries(folder)
            seen += len(listed or ())
            if listed is None or seen > MAX_KEPT_ENTRIES:
                return max(total, 1)
            for entry in listed:
                if entry.name == ".git":
                    continue
                kind = _entry_kind(entry)
                if kind in ("name", "unreadable") or (kind == "folder" and depth >= MAX_KEPT_DEPTH):
                    return max(total, 1)
                relative = Path(entry.path).relative_to(tree).as_posix()
                if kind == "folder":
                    stack.append((Path(entry.path), depth + 1))
                elif kind not in ("gone", "link") and relative not in tracked:
                    total += 1
                    if total >= limit:
                        return limit
    return total


def _admin_state(admin: Path, root: Path, budget: Budget | None = None) -> str:
    """"plain" for an admin folder git may be pointed at (plain_admin), "odd_admin" for any other, and
    "admin_unchecked" when git could not read its config.worktree (it timed out, say): that worktree alone is left
    unread, never the others."""
    try:
        return "plain" if plain_admin(admin, root, budget) else "odd_admin"
    except GitFailed:
        return "admin_unchecked"


def discover(root: Path, parents: tuple[tuple[str, ...], ...] = WORKTREES,
             external_roots: tuple[Path, ...] = (), budget: Budget | None = None, *,
             max_worktrees: int | None = None) -> list[dict] | None:
    """The worktrees of the repository, main checkout first: {id, name, path (None when not read), git_dir, head,
    operation, created, main, reason}. The explicit entry limit remains bounded; no excess session is dropped."""
    if max_worktrees is not None and (type(max_worktrees) is not int or not 1 <= max_worktrees <= 1000):
        raise ValueError("max_worktrees must be an integer from 1 to 1000")
    limit = MAX_WORKTREES if max_worktrees is None else max_worktrees
    root = Path(root)
    budget = budget or Budget()
    budget.check()
    common = root / ".git"
    if not no_link(common, root) or not common.is_dir():
        return []
    found = [{"id": "", "name": root.name if SAFE_NAME.fullmatch(root.name) else "repository", "path": root,
              "git_dir": common, "head": _head(common, root), "operation": _operation(common, root), "created": None,
              "main": True, "reason": "", "unknown": False, "boundary": root, "target": None}]
    admins = common / "worktrees"
    state = _folder_state(admins, root)
    if state == "gone":
        return found
    listed = _entries(admins) if state == "plain" else None
    if listed is None:
        return None
    if len(listed) > limit:
        raise TooManyWorktrees("too many entries in .git/worktrees")
    external_roots = tuple(path for path in external_roots if local_root(path))
    for number, entry in enumerate(sorted(listed, key=lambda item: item.name), 1):
        budget.check()
        name = entry.name
        admin = admins / name
        kind = _entry_kind(entry)
        if kind in ("file", "special", "gone"):
            continue
        safe_name = bool(SAFE_NAME.fullmatch(name)) and not (os.name == "nt" and _windows_odd(name))
        if not safe_name or kind != "folder" or not no_link(admin, root):
            found.append({"id": name if safe_name else f"unknown:{number}", "name": name if safe_name else "worktree",
                          "path": None, "git_dir": admin, "head": {}, "operation": {"kind": "", "branch": None},
                          "created": None, "main": False, "reason": "unknown_admin", "unknown": True,
                          "boundary": root, "target": None})
            continue
        target = check_worktree(read_small(admin / "gitdir", root) or "", root, admin, parents, external_roots)
        boundary = worktree_boundary(target, root, external_roots) if target is not None else root
        reason = ""
        if target is None:
            reason = "outside"
        elif (checked := _admin_state(admin, root, budget)) != "plain":
            reason = checked
        elif (state := _folder_state(target, boundary)) != "plain":
            reason = GONE if state == "gone" else "link"
        elif not _worktree_marker(target, admin, boundary):
            reason = "odd_admin"
        found.append({"id": name, "name": target.name if target is not None and not reason else name,
                      "path": None if reason else target, "target": target, "boundary": boundary,
                      "git_dir": admin, "head": _head(admin, root), "operation": _operation(admin, root),
                      "created": _created(admin, root), "main": False, "reason": reason, "unknown": False})
    keys = [tuple(_key(_pure(str(tree["target"])))) if tree["target"] is not None else None for tree in found]
    counts: dict[tuple, int] = {}
    for key in keys:
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    main_key = tuple(_key(_pure(str(root))))
    for tree, key in zip(found, keys):
        if key is not None and (counts[key] > 1 or key == main_key) and not tree["reason"]:
            tree.update(path=None, reason="duplicate_admin", name=tree["git_dir"].name)
        tree.pop("target", None)
    return found


def read_ledger(tree: Path, root: Path, parts: tuple[str, ...]) -> tuple[bytes | None, str, tuple | None]:
    """The working copy of a worktree's ledger (at parts, relative to the worktree): (content, state, identity). The
    identity (size, time, file id) lets the caller skip a file that did not change; the file is opened only through
    plain folders, checked once open."""
    data, state, info = _read_regular(Path(tree).joinpath(*parts), root, MAX_LEDGER_BYTES)
    identity = (info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev) \
        if info is not None and state in ("ok", "too_big") else None
    return data, state, identity


def safe_relative(name: str) -> bool:
    """A plain relative path, as git names a file: no "..", no drive or stream, no backslash, and nothing but UTF-8
    (a name git read as other bytes would be looked up here as another path), written as this system writes it. On
    Windows no part may end with a dot or a space, nor be a device name (nul, con, com1...): Windows reads them one
    way as the last part of a path and another in the middle of one, so the board's checks and git would look at two
    different files."""
    relative = PurePosixPath(name)
    return bool(name) and not relative.is_absolute() and ".." not in relative.parts and ":" not in name \
        and "\\" not in name and "\0" not in name and not any("\ud800" <= c <= "\udfff" for c in name) \
        and (_written_as_utf8(name) if os.name != "nt" else not any(_windows_odd(part) for part in relative.parts))


def _windows_odd(part: str) -> bool:
    """A path part Windows reads differently by its place in a path: a final dot or space, or a device name."""
    return part.endswith((".", " ")) or part.split(".")[0].strip().upper() in RESERVED


def _written_as_utf8(name: str) -> bool:
    """Whether this system writes the name with the same bytes as git (UTF-8). Under a locale that is not UTF-8 (on
    Linux or BSD, with Python older than 3.15 and not in UTF-8 mode), a name beyond ASCII is written otherwise, or not
    at all: never an error, the name is simply not one the board looks up."""
    try:
        return os.fsencode(name) == name.encode("utf-8")
    except UnicodeEncodeError:
        return False


def last_write(tree: Path, root: Path, names: list[str]) -> datetime | None:
    """The latest modification time among the files git status names, each reached through plain folders only."""
    latest, checked = None, {}
    for name in names[:MAX_DATED]:
        if not safe_relative(name):
            continue
        relative = PurePosixPath(name.rstrip("/"))
        folder = relative.parent
        if folder not in checked:
            checked[folder] = no_link(Path(tree).joinpath(*folder.parts), root)
        if not checked[folder]:
            continue
        try:
            info = os.lstat(Path(tree).joinpath(*relative.parts))
        except (OSError, ValueError):
            continue
        latest = info.st_mtime if latest is None else max(latest, info.st_mtime)
    try:
        return datetime.fromtimestamp(latest, timezone.utc) if latest is not None else None
    except (OverflowError, OSError, ValueError):  # a file dated before 1970 or past what the platform holds
        return None


def admin_name(root: Path) -> str | None:
    """The id of the admin folder of the worktree root, or None (the main checkout, or an odd .git file)."""
    admin = _admin_of(root)
    return admin.name if admin is not None else None
