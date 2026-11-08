# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The git reads of flightboard, and nothing else.

A fixed list of commands, each run with an explicit --git-dir (and --work-tree inside a worktree); the one other git
run, gitconfig.py's reading of a configuration's bytes on git's standard input, has no repository at all (GIT_DIR names
the null device) and comes before any of these. Attributes come from git's empty tree, and neither a user attributes
file nor a user excludes file is read, so no filter, textconv or LFS program can start. No optional lock (a read never
rewrites a session's index), no fsmonitor, no signature check, and an environment cut down to a short allowlist (no API
key reaches a program git might start). git never walks untracked
content: a nested .git file there could send it to a network share. Every revision given to git is a full commit id
checked here (the reflogs are read by files.py, not by git), and "--" ends every list of revisions. Standard library
only, safe under -I.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .text import clean

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's built-in empty tree: no .gitattributes at all
MIN_VERSION = (2, 41)  # git --attr-source=<tree> <command> (RelNotes 2.41.0)
NO_LAZY_FETCH = (2, 45)  # GIT_NO_LAZY_FETCH: older git may fetch a missing object from a partial clone's remote
GIT_TIMEOUT = 8  # shorter than the page's refresh
MAX_HISTORY = 300
MAX_COMMITS = 8
MAX_ENTRIES = 2000
MAX_STAGED = 50_000  # index entries checked before git status; a bigger index is not read at all
MAX_FILTERS = 40  # filter drivers blanked on every command line; more, and the worktrees' files are not read
BATCH = 40
VERBS = ("version", "for-each-ref", "rev-list", "merge-base", "log", "cat-file", "status", "ls-files", "check-ignore",
         "config")
FILTER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,60}")
# git may run no program a repository's configuration names (fsmonitor hook, signature check), writes no untracked
# cache, reads no user attributes, excludes or mailmap file and no diff order file (a path there could name a network
# share), starts no LFS program and no external diff, follows no rename in a history walk, and reads the commits as
# they are (no replacement, whatever core.useReplaceRefs says). The multi-pack-index is not read: a pack name in it is
# a file name git opens as written, ".." included. The board's own arguments make git look up no other name: a full
# commit id is never checked for an ambiguous ref (.git/<id>, refs/tags/<id>), a reflog is read by the board itself
# (files.read_reflog), and git status counts no stash. git never turns a full index into a sparse one (index.sparse),
# which would write trees into .git/objects; a sparse or split index is never handed to git at all (files.index_state),
# and git reads every index with one thread (index.threads), entry after entry, as the board walks it: never from
# where an index's own offset tables point. On Windows git keeps to paths shorter than 260 characters
# (core.longpaths), as the board's own checks may have to: a longer path git reached alone could hold a .git the board
# never saw.
SETTINGS = ("-c", "core.fsmonitor=false", "-c", "log.showSignature=false", "-c", "color.ui=never",
            "-c", "core.untrackedCache=false", "-c", "core.attributesFile=", "-c", "core.excludesFile=",
            "-c", "log.mailmap=false", "-c", "core.useReplaceRefs=false", "-c", "advice.graftFileDeprecated=false",
            "-c", "filter.lfs.process=", "-c", "filter.lfs.clean=", "-c", "filter.lfs.smudge=",
            "-c", "filter.lfs.required=false", "-c", "diff.external=", "-c", f"diff.orderFile={os.devnull}",
            "-c", "log.follow=false", "-c", "core.multiPackIndex=false", "-c", "core.warnAmbiguousRefs=false",
            "-c", "status.showStash=false", "-c", "index.sparse=false", "-c", "index.threads=1",
            "-c", "core.longpaths=false")
# The commit-graph is read only when the board found its chain of graphs absent or plain (files.commit_graph_plain):
# a line of the chain is a file name git opens as written, ".." included.
GRAPH_OFF = ("-c", "core.commitGraph=false")
# Sparse checkout is off for the commands that read index names the board has not checked yet: git would look up on
# disk each skip-worktree name of the index, wherever it points (git checks none of them). git status runs only once
# every name has passed the board's checks: it keeps the repository's own sparse checkout, so a file a session wrote
# outside its sparse patterns still counts as modified, as git itself counts it.
SPARSE_OFF = ("-c", "core.sparseCheckout=false")
UNCHECKED_NAMES = ("ls-files", "check-ignore")
# The only variables git and anything it might start receive, besides the GIT_* settings of environment().
ENV_KEYS = frozenset({"PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
                      "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "LANG",
                      "LC_ALL", "LC_CTYPE"})
FULL_SHA = re.compile(r"[0-9a-f]{40}")  # SHA-1 only: in a SHA-1 repository, 64 hex digits would be a ref name to git
REMOTE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")
VERSION = re.compile(r"git version (\d+)\.(\d+)")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitRefused(RuntimeError):
    """A git command or a revision outside what flightboard reads."""


class GitFailed(RuntimeError):
    """git is missing, timed out or failed."""


def git_env(base: Mapping[str, str]) -> dict[str, str]:
    """No inherited GIT_* variable (no other repository, index or config), no optional lock (git status could rewrite
    the index), no prompt and no pager. No lazy fetch: a partial clone's remote is never asked for a missing object, so
    no program its configuration names (an upload-pack, an ssh command) ever starts. No replacement object and no
    graft (the empty device stands for info/grafts): git reads the commits as they are, never as a refs/replace entry
    or a grafts line a session wrote would show them."""
    env = {key: value for key, value in base.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", PAGER="cat",
               GIT_LITERAL_PATHSPECS="1", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1",
               GIT_GRAFT_FILE=os.devnull, NO_COLOR="1")
    return env


def environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of git: a short allowlist, then the GIT_* settings of git_env."""
    source = os.environ if base is None else base
    return git_env({key: value for key, value in source.items() if key.upper() in ENV_KEYS})


def git_executable() -> str | None:
    """git found in an absolute local folder of PATH. Never in the current folder, where Windows would look first,
    and never on a network share."""
    names = ("git.exe",) if os.name == "nt" else ("git",)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or entry.startswith(("//", "\\\\")) or not Path(entry).is_absolute():
            continue
        for name in names:
            candidate = Path(entry) / name
            if candidate.is_file():
                return str(candidate)
    return None


def executable() -> str | None:
    """git by an absolute path. On Windows, the Git\\cmd launcher is replaced by the real git next to it, so that a
    timeout stops git itself and not only its launcher."""
    found = git_executable()
    if found is None or os.name != "nt":
        return found
    path = Path(found)
    if path.parent.name.lower() == "cmd":
        for candidate in (path.parent.parent / "mingw64" / "bin" / "git.exe", path.parent.parent / "bin" / "git.exe"):
            if candidate.is_file():
                return str(candidate)
    return found


def sha(value: object) -> str:
    if not isinstance(value, str) or not FULL_SHA.fullmatch(value):
        raise GitRefused("revision refused: only a full commit id passes")
    return value


def full_ref(remote: str) -> re.Pattern[str]:
    """The branch refs flightboard gives git: local branches and the branches of one remote."""
    return re.compile(r"refs/(?:heads|remotes/" + re.escape(remote) + r")/[A-Za-z0-9][A-Za-z0-9._/-]{0,200}")


PLAIN_PATH = re.compile(r"[A-Za-z0-9._-]{1,100}(?:/[A-Za-z0-9._-]{1,100}){0,9}")


def _path(value: object) -> str:
    """A repository path given to git after a commit id: plain relative parts only, never a newline or a ".."."""
    if not isinstance(value, str) or not PLAIN_PATH.fullmatch(value) or \
            any(part in (".", "..") for part in value.split("/")):
        raise GitRefused("path refused")
    return value


def is_ref(value: object, remote: str = "origin") -> bool:
    """Whether value is a full branch ref whose reflog the board may read: a local branch or one of the remote's,
    written plainly."""
    return isinstance(value, str) and full_ref(remote).fullmatch(value) is not None and ".." not in value \
        and not value.endswith((".", "/")) and "//" not in value


# ---------------------------------------------------------------- parsers

def parse_version(raw: bytes) -> tuple[int, int] | None:
    match = VERSION.search(raw.decode("ascii", errors="replace"))
    return (int(match.group(1)), int(match.group(2))) if match else None


def parse_refs(raw: bytes, remote: str = "origin") -> dict[str, dict]:
    """refs/heads and refs/remotes/<remote>: {full name: {sha, at (seconds since 1970)}}."""
    prefixes = ("refs/heads/", f"refs/remotes/{remote}/")
    refs = {}
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        parts = line.split("\0")
        if len(parts) == 3 and parts[0].startswith(prefixes) and FULL_SHA.fullmatch(parts[1]):
            refs[parts[0]] = {"sha": parts[1], "at": int(parts[2]) if parts[2].isdigit() else 0}
    return refs


def parse_log(raw: bytes) -> list[dict]:
    """Commits as "%H%x00%ct%x00%s" lines: {sha, at, subject}."""
    commits = []
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        parts = line.split("\0")
        if len(parts) == 3 and FULL_SHA.fullmatch(parts[0]) and parts[1].isdigit():
            commits.append({"sha": parts[0], "at": int(parts[1]), "subject": clean(parts[2], 160)})
    return commits


def parse_batch_check(raw: bytes, count: int, kind: str = "blob") -> list[int | None]:
    """The sizes `git cat-file --batch-check` gives, in the order asked; None for a missing object or another kind."""
    sizes = []
    lines = raw.decode("ascii", errors="replace").split("\n")
    for index in range(count):
        parts = lines[index].split(" ") if index < len(lines) else []
        sizes.append(int(parts[2]) if len(parts) == 3 and parts[1] == kind and parts[2].isdigit() else None)
    return sizes


def parse_batch(raw: bytes, count: int) -> list[bytes | None]:
    """The objects of `git cat-file --batch`, in the order asked; None for a missing one or a non-file."""
    objects, position = [], 0
    for _ in range(count):
        end = raw.find(b"\n", position)
        if end < 0:
            objects.append(None)
            continue
        parts = raw[position:end].decode("ascii", errors="replace").split(" ")
        position = end + 1
        size = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
        objects.append(raw[position:position + size] if size is not None and parts[1] == "blob" else None)
        if size is not None:
            position += size + 1
    return objects


def parse_status(raw: bytes) -> list[dict]:
    """`git status --porcelain=v2 -z --no-renames` on tracked files: {kind (modified, conflict), path, deleted}."""
    entries = []
    for field in raw.decode("utf-8", errors="replace").split("\0"):
        if field.startswith("1 "):
            parts = field.split(" ", 8)
            if len(parts) == 9:
                entries.append({"kind": "modified", "path": parts[8], "deleted": "D" in parts[1]})
        elif field.startswith("u "):
            parts = field.split(" ", 10)
            if len(parts) == 11:
                entries.append({"kind": "conflict", "path": parts[10], "deleted": False})
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def _names(raw: bytes) -> list[str]:
    return [name for name in raw.decode("utf-8", errors="replace").split("\0") if name]


def parse_filters(raw: bytes) -> tuple[set[str], bool]:
    """The filter drivers `git config --get-regexp` names, and whether one of them has a name we will not pass to
    git (it is then never blanked, and the files of the worktrees are not read)."""
    names, odd = set(), False
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        key = line.split(" ", 1)[0].strip()
        if not key.startswith("filter.") or key.count(".") < 2:
            continue
        name = key[len("filter."):key.rindex(".")]
        if FILTER_NAME.fullmatch(name):
            names.add(name)
        else:
            odd = True
    return names, odd


def parse_staged(raw: bytes, limit: int = MAX_STAGED) -> list[tuple[str, str]]:
    """`git ls-files -s -z`: (mode, path) of the index entries, one more than limit at most: the caller tells a cut
    list by its length, and never checks only part of the index. A name that is not UTF-8 keeps its bytes as lone
    surrogates, never a replacement character: the caller then refuses it rather than check another path than git's."""
    entries = []
    for field in raw.decode("utf-8", errors="surrogateescape").split("\0"):
        head, tab, path = field.partition("\t")
        parts = head.split(" ")
        if tab and len(parts) == 3 and parts[0].isdigit():
            entries.append((parts[0], path))
            if len(entries) > limit:
                break
    return entries


# ---------------------------------------------------------------- the runner

class Git:
    """The reads of flightboard, and nothing else. remote names the one remote whose branches are read."""

    def __init__(self, remote: str = "origin") -> None:
        if not REMOTE_NAME.fullmatch(remote) or ".." in remote:
            raise GitRefused("remote name refused")
        self.remote = remote
        self.blank: tuple[str, ...] = ()  # every filter driver the configuration defines, switched off
        self.graph = False  # whether git may read the commit-graph: only once a reading found its chain plain

    def execute(self, git_dir: Path, args: tuple[str, ...], work_tree: Path | None = None,
                stdin: bytes | None = None, codes: tuple[int, ...] = (0,), literal: bool = True) -> tuple[int, bytes]:
        """(exit code, output) of one of the reads; a command outside VERBS is refused before git starts."""
        if not args or args[0] not in VERBS:
            raise GitRefused(f"git command refused: {list(args[:1])}")
        program = executable()
        if program is None:
            raise GitFailed("git not found")
        # git version reads no attribute, and a git too old for --attr-source can still say how old it is
        attributes = () if args[0] == "version" else (f"--attr-source={EMPTY_TREE}",)
        command = [program, f"--git-dir={git_dir}", *([f"--work-tree={work_tree}"] if work_tree else []),
                   *attributes, *SETTINGS, *(() if self.graph else GRAPH_OFF),
                   *(SPARSE_OFF if args[0] in UNCHECKED_NAMES else ()), *self.blank, *args]
        feed = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        env = environment() if literal else {**environment(), "GIT_LITERAL_PATHSPECS": "0"}
        try:
            proc = subprocess.run(command, env=env, cwd=str(work_tree or git_dir), capture_output=True,
                                  timeout=GIT_TIMEOUT, creationflags=_NO_WINDOW, check=False, **feed)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitFailed(type(exc).__name__) from exc
        if proc.returncode not in codes:
            raise GitFailed(f"git {args[0]} failed ({proc.returncode})")
        return proc.returncode, proc.stdout

    def run(self, git_dir: Path, args: tuple[str, ...], work_tree: Path | None = None, stdin: bytes | None = None,
            codes: tuple[int, ...] = (0,)) -> bytes:
        return self.execute(git_dir, args, work_tree, stdin, codes)[1]

    def version(self, common: Path) -> tuple[int, int] | None:
        return parse_version(self.run(common, ("version",)))

    def disarm_filters(self, common: Path) -> bool:
        """Switch off, for every later read, each filter driver the configuration defines (system, user and this
        repository), whatever attributes may name it in between. False when a driver has a name we will not pass to
        git, or when there are more drivers than a command line holds: the files of the worktrees must then not be
        read, and nothing is blanked."""
        self.blank = ()
        names, odd = parse_filters(self.run(common, ("config", "--get-regexp", r"^filter\."), codes=(0, 1)))
        if odd or len(names) > MAX_FILTERS:
            return False
        self.blank = tuple(part for name in sorted(names) for part in (
            "-c", f"filter.{name}.clean=", "-c", f"filter.{name}.smudge=", "-c", f"filter.{name}.process=",
            "-c", f"filter.{name}.required=false"))
        return True

    def staged(self, git_dir: Path, work_tree: Path) -> list[tuple[str, str]]:
        """The index entries with their modes, read from the index alone (nothing on disk is walked); one more than
        MAX_STAGED when the index holds more."""
        return parse_staged(self.run(git_dir, ("ls-files", "-s", "-z"), work_tree=work_tree), MAX_STAGED)

    def refs(self, common: Path, unmerged_from: str | None = None) -> dict[str, dict]:
        """Every branch and every branch of the remote; with unmerged_from, only those holding a commit it lacks."""
        only = (f"--no-merged={sha(unmerged_from)}",) if unmerged_from else ()
        return parse_refs(self.run(common, ("for-each-ref", *only,
                                            "--format=%(refname)%00%(objectname)%00%(committerdate:unix)",
                                            "refs/heads/", f"refs/remotes/{self.remote}/")), self.remote)

    def commits_exist(self, common: Path, shas: list[str]) -> list[bool]:
        """Whether each id names a commit of the repository (a hand-written HEAD may name nothing)."""
        feed = "".join(f"{sha(value)}\n" for value in shas).encode("ascii")
        sizes = parse_batch_check(self.run(common, ("cat-file", "--batch-check"), stdin=feed), len(shas), "commit")
        return [size is not None for size in sizes]

    def counts(self, common: Path, main: str, tip: str) -> tuple[int, int]:
        """(behind, ahead): the commits of main the tip lacks, and the tip's own commits main lacks."""
        parts = self.run(common, ("rev-list", "--left-right", "--count", f"{sha(main)}...{sha(tip)}", "--")).split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise GitFailed("rev-list unreadable")
        return int(parts[0]), int(parts[1])

    def merge_bases(self, common: Path, main: str, tip: str) -> list[str]:
        found = self.run(common, ("merge-base", "--all", sha(main), sha(tip)), codes=(0, 1))
        return [line for line in found.decode("ascii", errors="replace").split() if FULL_SHA.fullmatch(line)]

    def is_ancestor(self, common: Path, older: str, newer: str) -> bool:
        code, _ = self.execute(common, ("merge-base", "--is-ancestor", sha(older), sha(newer)), codes=(0, 1))
        return code == 0

    def commits(self, common: Path, base: str, tip: str) -> list[dict]:
        return parse_log(self.run(common, ("log", "--no-color", f"-n{MAX_COMMITS}", "--format=%H%x00%ct%x00%s",
                                           f"{sha(base)}..{sha(tip)}", "--")))

    def heads(self, common: Path, shas: list[str]) -> list[dict]:
        return parse_log(self.run(common, ("log", "--no-walk=unsorted", "--no-color", "--format=%H%x00%ct%x00%s",
                                           *(sha(value) for value in shas), "--")))

    def first_parent(self, common: Path, tip: str, path: str | None = None) -> list[dict]:
        """The commits of the first-parent line of tip, newest first: those that changed the ledger at path, or every
        one of them without a ledger."""
        return parse_log(self.run(common, ("log", "--first-parent", "--no-color", f"-n{MAX_HISTORY + 1}",
                                           "--format=%H%x00%ct%x00%s", sha(tip), "--",
                                           *([_path(path)] if path else []))))

    def sizes(self, common: Path, shas: list[str], path: str) -> list[int | None]:
        """The size of the ledger at path in each commit, without reading it."""
        return self.blob_sizes(common, [(value, path) for value in shas])

    def blob_sizes(self, common: Path, pairs: list[tuple[str, str]]) -> list[int | None]:
        """The size of each (commit, path) file, without reading it; None when absent or not a file. Each path is one
        the caller checked as a plain relative path."""
        sizes: list[int | None] = []
        for start in range(0, len(pairs), BATCH):
            group = [(sha(value), _path(path)) for value, path in pairs[start:start + BATCH]]
            feed = "".join(f"{value}:{path}\n" for value, path in group).encode("utf-8")
            sizes += parse_batch_check(self.run(common, ("cat-file", "--batch-check"), stdin=feed), len(group))
        return sizes

    def ledgers(self, common: Path, shas: list[str], path: str) -> list[bytes | None]:
        """The ledger at path in each commit, by one `git cat-file --batch` per group (sizes checked first by the
        caller)."""
        found: list[bytes | None] = []
        path = _path(path)
        for start in range(0, len(shas), BATCH):
            group = [sha(value) for value in shas[start:start + BATCH]]
            feed = "".join(f"{value}:{path}\n" for value in group).encode("utf-8")
            found += parse_batch(self.run(common, ("cat-file", "--batch"), stdin=feed), len(group))
        return found

    def status(self, git_dir: Path, work_tree: Path) -> list[dict]:
        """The tracked files that changed. Untracked content is never walked by git (files.py lists it)."""
        return parse_status(self.run(git_dir, ("status", "--porcelain=v2", "-z", "--untracked-files=no",
                                               "--ignore-submodules=all", "--no-renames"), work_tree=work_tree))

    def ignored(self, git_dir: Path, work_tree: Path, paths: list[str]) -> set[str]:
        """Which of these paths, relative to the worktree (a folder ends with "/"), its ignore rules cover.
        check-ignore refuses literal pathspecs, so a name pathspec magic could read (":" first, or one of *?[ and
        backslash) is never asked: it simply counts as untracked."""
        asked = [path for path in paths if path and not path.startswith(":") and not any(c in path for c in "*?[\\")
                 and not any("\ud800" <= c <= "\udfff" for c in path)]  # a name that is not UTF-8 counts as untracked
        if not asked:
            return set()
        feed = "".join(f"{path}\0" for path in asked).encode("utf-8")
        return set(_names(self.execute(git_dir, ("check-ignore", "-z", "--stdin"), work_tree=work_tree, stdin=feed,
                                       codes=(0, 1), literal=False)[1]))
