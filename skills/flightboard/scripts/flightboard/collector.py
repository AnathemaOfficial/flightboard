# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The state of the board: every session, the live overlay, main's history and what waits for the owner.

A session is a git working folder (the main checkout or one under the worktree folders, usually one Claude Code
session) or a branch holding commits that main lacks. Its changes are its ledger against its merge base with main; the
overlay rules live in overlay.py, the git reads in gitreads.py (git's reading of a configuration's bytes, outside any
repository, in gitconfig.py), the file reads in files.py, the ledger formats in ledgers/. Without a ledger, or when
main's ledger cannot be read, the view is git's alone. Whatever a commit id fixes is kept between readings, and only
while it is still used, so a steady refresh runs four git commands (one of them reads .git/config's bytes) plus two
per worktree, one more for each config.worktree, and check-ignore for a worktree holding new files. What a session can
change in place (its index, its ignore rules) is read again at every reading. One session that cannot be read never
stops the others, and a failed read is never cached. Standard library only, safe under -I.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import TOOL
from . import files as FILES
from . import gitreads as GIT
from . import ledgers as LEDGERS
from . import messages as M
from . import overlay as OVERLAY
from . import view as VIEW
from . import config as CONFIG
from .config import Settings
from .gitreads import GitFailed, GitRefused
from .ledgers import Ledger
from .ledgers.base import MAX_LEDGER_BYTES
from .text import iso, safe_branch

HEADS = "refs/heads/"
CHECKOUT_ID = "@checkout"  # no admin folder can take it: their names start with a letter or a digit
MAX_INFERRED = 3
UNREADABLE = "unreadable"  # a ledger that exists at a commit but cannot be read, unlike an absent one (None)
# why an index is never handed to git (files.index_state), as the issue a session shows
INDEX_ISSUES = {"sparse": "sparse_index", "split": "split_index", "too_big": "index_too_big"}


class Collector:
    """Reads the repository on demand, one reading at a time. Given a session's worktree, it reads the main checkout
    that worktree belongs to."""

    def __init__(self, root: Path, settings: Settings | None = None, git: GIT.Git | None = None) -> None:
        self.settings = settings or Settings()
        if not CONFIG.valid(self.settings):  # settings built by hand pass the same text checks as the command line
            raise ValueError("settings refused")
        self.lang = self.settings.lang
        # from a subfolder, the repository holding it; from a session's worktree, the main checkout
        self.root = FILES.main_checkout(FILES.top_folder(Path(root)), self.settings.worktrees)
        self.common = self.root / ".git"
        self.name = self.root.name if FILES.SAFE_NAME.fullmatch(self.root.name) else "repository"
        self.git = git or GIT.Git(self.settings.remote)
        self.remote = self.git.remote
        self.remote_prefix = f"refs/remotes/{self.remote}/"
        self._lock = threading.Lock()
        self._version_ok = False
        self._no_lazy_fetch = False  # whether this git honours GIT_NO_LAZY_FETCH (a partial clone is then read)
        self._adapter_key: tuple | None = None
        self._detected: tuple[str, Ledger | None] | None = None  # main's commit -> the ledger auto found there
        self._parsed: dict[str, dict | str | None] = {}  # commit -> its ledger, validated (or None, UNREADABLE)
        self._slim: dict[str, dict | str | None] = {}  # commit -> what history and dating need of its ledger
        self._pairs: dict[tuple[str, str], tuple[int, int, list[str]]] = {}
        self._ranges: dict[tuple[str, str], list[dict]] = {}
        self._branch_logs: dict[tuple[str, str], list[dict]] = {}
        self._heads: dict[str, dict] = {}
        self._commits: set[str] = set()  # ids known to name a commit
        self._ancestors: dict[tuple[str, str], bool] = {}
        self._history: tuple[tuple, list[dict], bool, bool] | None = None
        self._files: dict[str, tuple] = {}  # session -> (identity of its working ledger, parsed)
        self._tracked: dict[str, set] = {}  # session -> the names its index tracks, as this reading found them
        self._used: set = set()
        self._used_full: set = set()  # commits whose full ledger this reading needs (main, tips, bases)
        self._used_slim: set = set()  # commits whose slim ledger it needs (history, dating)
        self._remote_main: str | None = None

    def snapshot(self, now: datetime, mode: str = "live") -> dict:
        with self._lock:
            self._used, self._used_full, self._used_slim = set(), set(), set()
            self.git.blank = ()  # the filter drivers are read again by this reading: none carried over
            self.git.graph = False  # and the commit-graph stays off until this reading finds its chain plain
            try:
                view = self._snapshot(now, mode)
            except (GitFailed, GitRefused) as exc:
                return self._error(now, mode, "git_failed", str(exc))
            except Exception as exc:  # an odd repository must never take the page or the command down
                return self._error(now, mode, "read_failed", type(exc).__name__)
            self._prune()
            return view

    def _error(self, now: datetime, mode: str, reason: str, detail: str = "", git_ok: bool = False) -> dict:
        return VIEW.error_view(now, mode, reason, detail, self.lang, git_ok, TOOL, self.name)

    # -------- cached reads

    def _use(self, *keys) -> None:
        self._used.update(keys)

    def _prune(self) -> None:
        """Forget what this reading did not use: the caches never outgrow the repository's current state, and a full
        ledger is kept only for main, the tips and the bases, never for the whole history."""
        for cache, used in ((self._parsed, self._used_full), (self._slim, self._used_slim)):
            for key in [key for key in cache if key not in used]:
                del cache[key]
        for cache in (self._heads, self._pairs, self._ranges, self._branch_logs, self._ancestors, self._files,
                      self._tracked):
            for key in [key for key in cache if key not in self._used]:
                del cache[key]
        self._commits &= self._used

    def _ancestor(self, older: str, newer: str) -> bool:
        key = (older, newer)
        self._use(key)
        if key not in self._ancestors:
            self._ancestors[key] = self.git.is_ancestor(self.common, older, newer)
        return self._ancestors[key]

    def _pair(self, main: str, tip: str) -> tuple[int, int, list[str]]:
        key = (main, tip)
        self._use(key)
        if key not in self._pairs:
            if main == tip:
                self._pairs[key] = (0, 0, [main])
            else:
                behind, ahead = self.git.counts(self.common, main, tip)
                self._pairs[key] = (behind, ahead, self.git.merge_bases(self.common, main, tip))
        return self._pairs[key]

    def _range(self, base: str, tip: str) -> list[dict]:
        key = (base, tip)
        self._use(key)
        if key not in self._ranges:
            self._ranges[key] = self.git.commits(self.common, base, tip) if base != tip else []
        return self._ranges[key]

    def _branch_log(self, name: str, tip: str) -> list[dict]:
        """What a branch's own reflog says it committed, newest first ({sha, via}), even once it is all in main."""
        key = (name, tip)
        if not GIT.is_ref(name, self.remote):
            return []  # an unusual branch name: no reflog is looked for
        self._use(key)
        if key not in self._branch_logs:
            self._branch_logs[key] = [{"sha": entry["sha"], "via": entry["via"]} for entry in self._reflog(name)
                                      if entry["via"].startswith("commit")]
        return self._branch_logs[key]

    def _reflog(self, name: str) -> list[dict]:
        """A branch's reflog, newest first, read by the board itself (files.read_reflog). As git log -g would, it
        keeps only the moves to a commit the repository holds."""
        entries = FILES.read_reflog(self.root, name, GIT.MAX_HISTORY + 1)
        held = self._existing([entry["sha"] for entry in entries]) if entries else set()
        return [entry for entry in entries if entry["sha"] in held]

    def _existing(self, shas: list[str]) -> set[str]:
        """The ids among shas that name a commit, checked once each (a hand-written HEAD may name nothing)."""
        unknown = [sha for sha in dict.fromkeys(shas) if sha not in self._commits]
        if unknown:
            for sha, exists in zip(unknown, self.git.commits_exist(self.common, unknown)):
                if exists:
                    self._commits.add(sha)
        self._use(*shas)
        return {sha for sha in shas if sha in self._commits}

    def _read_heads(self, shas: list[str]) -> None:
        self._use(*shas)
        missing = [sha for sha in dict.fromkeys(shas) if sha and sha not in self._heads]
        if missing:
            for commit in self.git.heads(self.common, missing):
                self._heads[commit["sha"]] = commit

    def _read_ledgers(self, adapter: Ledger, shas: list[str], full: bool) -> None:
        """The ledger at each commit: sizes first, then only the ledgers within the cap, by one batch. The cache is
        written only once the batch is read, so a failed read is tried again at the next reading."""
        cache = self._parsed if full else self._slim
        wanted = [sha for sha in dict.fromkeys(shas) if sha]
        (self._used_full if full else self._used_slim).update(wanted)
        missing = [sha for sha in wanted if sha not in cache]
        if not full:
            for sha in [sha for sha in missing if isinstance(self._parsed.get(sha), dict)]:
                cache[sha] = adapter.slim(self._parsed[sha])
            missing = [sha for sha in missing if sha not in cache]
        if not missing:
            return
        sizes = self.git.sizes(self.common, missing, adapter.path)
        readable = [sha for sha, size in zip(missing, sizes)
                    if size is not None and size <= MAX_LEDGER_BYTES]
        found = {sha: (None if size is None else UNREADABLE) for sha, size in zip(missing, sizes) if sha not in readable}
        for sha, data in zip(readable, self.git.ledgers(self.common, readable, adapter.path) if readable else []):
            try:
                parsed = adapter.parse(data, validate=full)
            except Exception:  # one odd ledger is unreadable on its own, never for the others
                parsed = None
            found[sha] = (parsed if full else adapter.slim(parsed)) if parsed is not None else UNREADABLE
        cache.update(found)

    def _ledger(self, sha: str | None, full: bool = True) -> dict | None:
        value = (self._parsed if full else self._slim).get(sha) if sha else None
        return value if isinstance(value, dict) else None

    def _history_entries(self, main_ref: str, main: str, path: str | None) -> tuple[list[dict], bool, bool]:
        """main's moves, oldest first, whether older ones were cut, and whether its older history could not be read:
        its reflog (the truth on this PC: when it moved, and why), preceded by its first-parent line for what the
        reflog no longer holds, marked approximate. With a ledger, the first-parent line keeps only the commits that
        changed it. A branch name git may not be given (a guessed main named with "+", say) has no reflog read: its
        first-parent line alone, marked approximate."""
        key = (main_ref, main, path)
        if self._history is None or self._history[0] != key:
            reflog = self._reflog(main_ref) if GIT.is_ref(main_ref, self.remote) else []
            cut = len(reflog) > GIT.MAX_HISTORY  # a reflog read in part is followed by main's first-parent line
            reflog = list(reversed(reflog[:GIT.MAX_HISTORY]))
            older, unread = self._older(reflog[0]["sha"] if reflog else main, path) if not cut else ([], False)
            cut = cut or len(older) > GIT.MAX_HISTORY
            entries = [{"sha": commit["sha"], "at": commit["at"], "via": commit["subject"], "approx": True}
                       for commit in reversed(older[:GIT.MAX_HISTORY])
                       if not reflog or commit["sha"] != reflog[0]["sha"]]
            entries += [{**entry, "approx": False} for entry in reflog]
            if not entries or entries[-1]["sha"] != main:
                head = self._heads.get(main, {})
                entries.append({"sha": main, "at": head.get("at", 0), "via": head.get("subject", ""), "approx": True})
            history = (key, entries[-GIT.MAX_HISTORY:], cut or len(entries) > GIT.MAX_HISTORY, unread)
            if unread:  # never kept: the next reading walks again
                return history[1], history[2], True
            self._history = history
        return self._history[1], self._history[2], False

    def _older(self, tip: str, path: str | None) -> tuple[list[dict], bool]:
        """main's first-parent line from tip, and whether git failed to walk it. A partial clone that never fetched a
        tree (--filter=tree:0) stops a walk limited to the ledger's path, and git is kept from fetching it; a very
        long history may outlast git's time limit: main's older moves are then not read, and the page says so, rather
        than the whole reading failing."""
        try:
            return self.git.first_parent(self.common, tip, path), False
        except GitFailed:
            return [], True

    # -------- the ledger of this reading

    def _adapter(self, main: str) -> Ledger | None:
        """The ledger this reading uses: the one the settings name, or with auto, the first main holds."""
        settings = self.settings
        if settings.ledger != "auto":
            adapter = LEDGERS.make(settings.ledger, settings.ledger_path)
        else:
            if self._detected is None or self._detected[0] != main:
                candidates = [(kind, path) for kind, path in LEDGERS.AUTO]
                sizes = self.git.blob_sizes(self.common, [(main, path) for _, path in candidates])
                found = next(((kind, path) for (kind, path), size in zip(candidates, sizes) if size is not None),
                             None)
                self._detected = (main, LEDGERS.make(*found) if found else None)
            adapter = self._detected[1]
        key = (adapter.kind, adapter.path) if adapter is not None else None
        if key != self._adapter_key:  # another format: nothing parsed for the last one is reused
            self._adapter_key = key
            self._parsed, self._slim, self._files = {}, {}, {}
        return adapter

    # -------- the snapshot

    def _snapshot(self, now: datetime, mode: str) -> dict:
        state = FILES.folder_state(self.common, self.root)  # lstat only: a .git link is never followed
        if state != "plain":
            return self._error(now, mode, "no_repository" if state == "gone" else "git_dir_link")
        problem = FILES.git_dir_problem(self.root, self.remote)
        if problem and problem != FILES.PROMISOR:  # git would follow it at every command: none runs on the repository
            return self._error(now, mode, "git_trap", problem)
        if not self._version_ok:
            version = self.git.version(self.common)  # reads no object: nothing for a partial clone to fetch
            if version is None or version < GIT.MIN_VERSION:
                return self._error(now, mode, "git_too_old")
            self._version_ok, self._no_lazy_fetch = True, version >= GIT.NO_LAZY_FETCH
        if problem and not self._no_lazy_fetch:  # this git could fetch a missing object through the remote's program
            return self._error(now, mode, "git_trap", problem)
        self.git.graph = FILES.commit_graph_plain(self.root)  # a long history is then walked as fast as git can
        trees = FILES.discover(self.root, self.settings.worktrees)
        if not trees:
            return self._error(now, mode, "no_repository")
        refs = self.git.refs(self.common)
        main_ref, main, note = self._main(refs, trees[0])
        if main is None:
            return self._error(now, mode, "no_main", git_ok=True)
        adapter = self._adapter(main)
        candidates, limits = self._candidates(trees, refs, main_ref, main, now)
        readable = [item for item in candidates if not item.get("broken")]
        self._read_heads([main] + [item["tip"] for item in readable])
        main_ledger, missing = None, ""
        if adapter is not None:
            self._read_ledgers(adapter, [main] + [sha for item in readable
                                                  for sha in (item["tip"], *item["bases"][:1])], True)
            main_ledger = self._ledger(main)
            if main_ledger is None:  # main's ledger is unreadable: this reading is git's alone, and says so
                missing, adapter = adapter.path, None
        entries, cut, unread = self._history_entries(main_ref, main, adapter.path if adapter else None)
        ranges = {item["id"]: self._guarded_range(item["bases"][0], item["tip"]) for item in readable
                  if len(item["bases"]) == 1 and item["ahead"]}
        if adapter is not None:
            self._read_ledgers(adapter, [entry["sha"] for entry in entries]
                               + [commit["sha"] for commits in ranges.values() for commit in commits], False)
        # every filter driver is switched off for the reads to come, whatever attributes appear meanwhile; the
        # repository's own info/attributes stops the reads of modified files altogether
        planted = not self.git.disarm_filters(self.common) or FILES.attributes_planted(self.root)
        sessions = [self._guarded(item, adapter, main_ledger, main, ranges.get(item["id"], []), planted, now)
                    for item in candidates]
        versions = OVERLAY.history_versions(entries, {sha: self._ledger(sha, False) for sha in
                                                      {entry["sha"] for entry in entries}}) if adapter else []
        short = main_ref.split("/", 3)[-1] if main_ref.startswith("refs/remotes/") else main_ref[len(HEADS):]
        context = {"ref": main_ref, "sha": main, "note": list(note),
                   "note_text": " · ".join(M.say(self.lang, "note." + code, remote=self.remote,
                                                 main=safe_branch(short)) for code in note),
                   "ledger": main_ledger, "ledger_adapter": adapter, "ledger_missing": missing,
                   "head": self._heads.get(main, {}),
                   "limits": {**limits, "history_cut": cut, "history_unread": unread},
                   "planted": planted, "entries": entries, "lang": self.lang, "tool": TOOL,
                   "repository": self.name}
        return VIEW.build_view(now, mode, context, sessions, versions, self.settings.public())

    def _guarded_range(self, base: str, tip: str) -> list[dict]:
        try:
            return self._range(base, tip)
        except GitFailed:
            return []

    def _main(self, refs: dict, main_tree: dict) -> tuple[str | None, str | None, tuple[str, ...]]:
        """main, or the remote's main when it holds everything main holds and more (a merge pushed from elsewhere) or
        when there is no local main at all, with the notes the page and --resume both show: the remote's main
        followed, or diverged, and main guessed from the main checkout's branch when the repository has neither main
        nor master, locally or on the remote, and --main names none (a session that switches that checkout's branch
        moves the baseline: the note says so, and --main pins it)."""
        names = (self.settings.main,) if self.settings.main else ("main", "master")
        local = next((HEADS + name for name in names if HEADS + name in refs), None)
        notes: tuple[str, ...] = ()
        if local is None and not self.settings.main and main_tree["head"].get("ref") in refs \
                and not any(self.remote_prefix + name in refs for name in names):
            local, notes = main_tree["head"]["ref"], ("guessed",)
        shorts = [local[len(HEADS):]] if local else list(names)
        remote_ref = next((self.remote_prefix + name for name in shorts if self.remote_prefix + name in refs), None)
        self._remote_main = remote_ref
        remote = refs.get(remote_ref) if remote_ref else None
        if local is None:  # no local branch at all: the remote's is followed, and the notes say so
            return (remote_ref, remote["sha"], notes + ("remote_only",)) if remote else (None, None, notes)
        sha = refs[local]["sha"]
        if remote is None or remote["sha"] == sha or self._ancestor(remote["sha"], sha):
            return local, sha, notes
        if self._ancestor(sha, remote["sha"]):
            return remote_ref, remote["sha"], notes + ("remote_ahead",)
        return local, sha, notes + ("diverged",)

    def _candidate(self, base: dict, main: str) -> dict:
        """A candidate with its distance to main; a tip git cannot read marks it broken, never the whole page."""
        try:
            behind, ahead, bases = self._pair(main, base["tip"])
        except GitFailed:
            return {**base, "behind": 0, "ahead": 0, "bases": [], "broken": True}
        return {**base, "behind": behind, "ahead": ahead, "bases": bases, "broken": False}

    def _candidates(self, trees: list[dict], refs: dict, main_ref: str, main: str,
                    now: datetime) -> tuple[list[dict], dict]:
        tips = [refs[tree["head"]["ref"]]["sha"] if tree["head"].get("ref") in refs else tree["head"].get("sha")
                for tree in trees]
        existing = self._existing([tip for tip in tips if tip])
        items, used = [], {main_ref}
        for tree, tip in zip(trees, tips):
            branch = tree["head"].get("ref") or tree["operation"]["branch"]  # a rebase detaches HEAD: head-name names it
            if branch:
                used.add(branch)
            if not tip:
                continue
            # a folder that is not read (outside the read folders, gone, odd admin files) still shows, by its branch
            base = {"id": tree["id"] or CHECKOUT_ID, "kind": "checkout" if tree["main"] else "worktree",
                    "name": tree["name"], "ref": branch, "tip": tip, "path": tree["path"], "git_dir": tree["git_dir"],
                    "created": tree["created"], "operation": tree["operation"]["kind"], "reason": tree["reason"],
                    "stale": False, "gone": tree["reason"] == FILES.GONE, "remote": self._remote(refs, branch, tip)}
            items.append(self._candidate(base, main) if tip in existing else {**base, "behind": 0, "ahead": 0,
                                                                                "bases": [], "broken": True})
        try:
            unmerged, unread = self.git.refs(self.common, unmerged_from=main), False
        except GitFailed:  # git could not tell them in time (a very long history): the folders' sessions still show
            unmerged, unread = {}, True
        others = []
        for name, info in unmerged.items():
            if name in used or name in (self._remote_main, self.remote_prefix + "HEAD"):
                continue
            if name.startswith(self.remote_prefix) and HEADS + name[len(self.remote_prefix):] in unmerged:
                continue  # one session, one card: the local branch shows it, read at the remote's tip when behind
            kind = "branch" if name.startswith(HEADS) else "remote"
            short = name[len(HEADS):] if kind == "branch" else f"{self.remote}/" + name[len(self.remote_prefix):]
            remote = "pushed" if kind == "remote" else self._remote(refs, name, info["sha"])
            # a branch the remote has carried further is read, dated and sorted at the remote's tip
            front = refs[self.remote_prefix + short] if remote == "behind" else info
            others.append((front["at"], name, kind, short, "pushed" if remote == "behind" else remote, front["sha"]))
        others.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        cap = self.settings.max_branches
        for at, name, kind, short, remote, tip in others[:cap]:
            base = {"id": "ref:" + name, "kind": kind, "name": safe_branch(short), "ref": name, "tip": tip,
                    "path": None, "git_dir": None, "created": None, "operation": "", "reason": "",
                    "stale": now.timestamp() - at > self.settings.stale_days * 86400, "gone": False, "remote": remote}
            item = self._candidate(base, main)
            if item["broken"] or item["ahead"]:
                items.append(item)
        return items, {"branches_cut": max(0, len(others) - cap), "branches_unread": unread}

    def _remote(self, refs: dict, branch: str | None, tip: str | None) -> str:
        """Where the remote's copy of a local branch stands: pushed (same tip), ahead (local holds commits the remote
        lacks), behind (the remote holds commits local lacks: the session went on elsewhere), diverged (both), or ""
        without a remote copy. The remote's copy is a session of its own only once the local branch is all in main."""
        if not branch or not branch.startswith(HEADS) or not tip:
            return ""
        remote = refs.get(self.remote_prefix + branch[len(HEADS):])
        if remote is None:
            return ""
        if remote["sha"] == tip:
            return "pushed"
        if self._ancestor(remote["sha"], tip):
            return "ahead"
        return "behind" if self._ancestor(tip, remote["sha"]) else "diverged"

    def _guarded(self, item: dict, adapter: Ledger | None, main_ledger: dict | None, main: str,
                 commits: list[dict], planted: bool, now: datetime) -> dict:
        """One session; a failure shows it unreadable, as it stands now (its files not read: never called ready nor
        ended), and never stops the others. No earlier reading stands in for it: that one could hide the work done
        since."""
        self._use(item["id"])
        if item.get("broken"):
            return VIEW.unreadable_session(item, "unknown_commit")
        try:
            return self._session(item, adapter, main_ledger, main, commits, planted, now)
        except Exception as exc:  # one hostile or broken session must not take the page down
            return VIEW.unreadable_session(item, "read_failed", type(exc).__name__)

    def _working_ledger(self, item: dict, adapter: Ledger, tip_ledger: dict | None) -> tuple[dict | None, str,
                                                                                               float | None]:
        """The ledger a worktree shows now, its state and its file's time: the working copy, or its last commit when
        the copy cannot be read."""
        if item["operation"] == "merge":
            return tip_ledger, "merging", None  # a merge in progress holds main's changes too: read the last commit
        data, state, identity = FILES.read_ledger(item["path"], self.root, adapter.parts)
        if state == "absent":
            return None, "absent", None
        if state != "ok":
            return tip_ledger, state, None
        cached = self._files.get(item["id"])
        parsed = cached[1] if cached is not None and cached[0] == identity else adapter.parse(data)
        self._files[item["id"]] = (identity, parsed)
        written = identity[1] / 1e9 if identity else None
        return (parsed, "ok", written) if parsed is not None else (tip_ledger, "writing", None)

    def _files_of(self, item: dict, planted: bool) -> tuple[list[dict], list[str], str]:
        """A worktree's modified tracked files (git, without walking anything), its untracked candidates (listed
        here, never by git, the ignored ones left out), and why the modified files were not read (a code), if they
        were not. Before git status runs, every tracked path is checked: a .git where the index expects a file or a
        submodule, or a link where it expects a file or a folder, and git is not run there at all. The index is read
        again at every reading: a session can rewrite it and put its old size and time back. A sparse index is never
        handed to git, which would write its trees into .git/objects to read it: nothing of that worktree is asked."""
        state = FILES.index_state(item["git_dir"], self.root)
        if state:  # nothing of that worktree is asked of git: neither its modified files nor its new ones
            self._tracked[item["id"]] = set()
            return [], [], INDEX_ISSUES.get(state, "tracked_unreadable")
        staged = self.git.staged(item["git_dir"], item["path"])
        names = {name for _, name in staged if FILES.safe_relative(name)}
        self._tracked[item["id"]] = names
        if planted:
            issue = "planted"
        elif len(staged) > GIT.MAX_STAGED:
            issue = "too_many_tracked"
        else:
            issue = FILES.tracked_problem(item["path"], self.root, staged)
        entries = [] if issue else self.git.status(item["git_dir"], item["path"])
        candidates = FILES.untracked(item["path"], self.root, names)
        if candidates is None:  # a folder holding tracked files cannot be listed: its new files are unknown
            return entries, [], issue or "folder_unlisted"
        if item["kind"] == "checkout":  # the worktree folders, and the folders that hold them, are the sessions' own
            candidates = [name for name in candidates if not _sessions_folder(name, self.settings.worktrees)]
        nested = [name for name in candidates if name.endswith("/") and _holds_git(item["path"] / name)]
        inside = {name: FILES.children(item["path"], self.root, name) for name in candidates
                  if name.endswith("/") and name not in nested}
        asked = [name for name in candidates if name not in nested] \
            + [child for found in inside.values() if found for child in found["folders"] + found["leaves"]]
        # asked again at every reading: an ignore rule can change (a .gitignore rewritten, info/exclude) while the
        # names stay the same
        ignored: set[str] = set()
        if asked and not FILES.ignore_file_special(item["path"], self.root, asked):  # git would wait on a pipe
            try:
                ignored = self.git.ignored(item["git_dir"], item["path"], asked)
            except GitFailed:  # git cannot tell (a path inside a submodule, say): every candidate counts
                ignored = set()
        kept = []
        for name in candidates:
            found = inside.get(name)
            if name in ignored or (found is not None and FILES.all_ignored(found, ignored)):
                continue  # ignored, or a new folder whose whole content is ignored (or empty): git would not show it
            kept.append(name)
        return entries, kept, issue

    def _kept_count(self, item: dict, tracked: set[str]) -> int:
        """Ignored work an agent must not lose (in the kept folders the owner named), counted at every reading: a file
        added deep in a kept folder changes no top folder's time, and a stale count could let a worktree look safe to
        remove. The walk is bounded and opens no file."""
        folders = self.settings.kept
        return FILES.kept_count(item["path"], self.root, tracked, folders) if folders else 0

    def _dated(self, changes: list[dict], commits: list[dict], tip: str, ledger_time: float | None, zone,
               ahead: int) -> list[dict]:
        """Each change dated where it happened: an uncommitted one by its ledger file's time, a committed one by the
        first of its own commits whose ledger holds the new status. Approximate when that commit may lie beyond the
        commits read (the oldest one read already holds the status while older ones were not read)."""
        ordered = list(reversed(commits))  # oldest first
        cut = ahead > len(commits)
        dated = []
        for change in changes:
            if change["uncommitted"]:
                at, sha, approx = (iso(ledger_time, zone) if ledger_time else ""), "", False
            else:
                hit = next((commit for commit in ordered
                            if (self._ledger(commit["sha"], False) or {}).get("tasks", {}).get(change["task"], {})
                            .get("status") == change["to"]), None)
                commit = hit or (ordered[0] if ordered else self._heads.get(tip))
                at = iso(commit["at"], zone) if commit and commit.get("at") else ""
                sha = commit["sha"][:7] if commit else ""
                approx = hit is None or (cut and hit is ordered[0])
            dated.append({**change, "at": at, "sha": sha, "approx": approx})
        return dated

    def _ledger_side(self, item: dict, adapter: Ledger | None, tip_ledger: dict | None, head_ledger: dict | None,
                     reason: str, detail: str) -> tuple[list, list, list, str, str]:
        """(changes, decisions, sections, reason, detail): what the session changed against its merge base."""
        if adapter is None:
            return [], [], [], reason, detail
        base_sha = item["bases"][0] if len(item["bases"]) == 1 else None
        base_ledger = self._ledger(base_sha)
        if head_ledger is not None and not head_ledger["valid"] and not reason:
            reason, detail = "invalid_ledger", head_ledger["error"]
        if base_ledger is not None and head_ledger is not None:
            tip_tasks = (tip_ledger or {}).get("tasks", {}) if item["path"] is not None else None
            return (OVERLAY.task_changes(base_ledger["tasks"], head_ledger["tasks"], tip_tasks),
                    OVERLAY.decision_changes(base_ledger["decisions"], head_ledger["decisions"]),
                    adapter.section_changes(base_ledger["raw"], head_ledger["raw"]), reason, detail)
        if head_ledger is not None and not reason:
            reason = "base_unreadable" if base_sha else "no_base"
        return [], [], [], reason, detail

    def _session(self, item: dict, adapter: Ledger | None, main_ledger: dict | None, main: str,
                 commits: list[dict], planted: bool, now: datetime) -> dict:
        entries, candidates, written, kept, ledger_time = [], [], None, 0, None
        issue = (FILES.GONE if item.get("gone") else "not_read") \
            if item["path"] is None and item["kind"] in ("checkout", "worktree") else ""
        tip_ledger = self._ledger(item["tip"]) if adapter else None
        head_ledger = tip_ledger
        ledger_state = "none" if adapter is None else "ok" if tip_ledger else (
            "unreadable" if self._parsed.get(item["tip"]) == UNREADABLE else "absent")
        if item["path"] is not None:
            entries, candidates, issue = self._files_of(item, planted)
            written = FILES.last_write(item["path"], self.root, [entry["path"] for entry in entries
                                                                 if not entry["deleted"]] + candidates)
            if adapter is not None:
                head_ledger, ledger_state, ledger_time = self._working_ledger(item, adapter, tip_ledger)
            if not entries and not candidates and not issue and not item["ahead"] and item["kind"] == "worktree":
                kept = self._kept_count(item, self._tracked[item["id"]])
        reason, detail = item["reason"], ""
        if len(item["bases"]) > 1:
            reason = reason or "several_bases"
        if item["stale"]:
            reason, detail = (reason, detail) if reason else ("stale", str(self.settings.stale_days))
        changes, decisions, sections, reason, detail = self._ledger_side(item, adapter, tip_ledger, head_ledger,
                                                                         reason, detail)
        changes = self._dated(changes, commits, item["tip"], ledger_time, now.tzinfo, item["ahead"])
        short = item["ref"][len(HEADS):] if item["ref"] and item["ref"].startswith(HEADS) else ""
        log = self._branch_log(item["ref"], item["tip"]) if adapter and not commits and short \
            and item["kind"] == "worktree" else []
        own = [commit["subject"] for commit in commits] if commits else [entry["via"] for entry in log]
        known = set(main_ledger["tasks"] if main_ledger else {}) | set((head_ledger or {}).get("tasks", {}))
        moved = [change["task"] for change in changes if not change["removed"]]
        named = VIEW.infer_tasks([item["name"], short], known) if known else []
        written_by = VIEW.infer_tasks(own, known) if known else []
        inferred = [tid for tid in dict.fromkeys(named + written_by) if tid not in moved][:MAX_INFERRED]
        head = self._heads.get(item["tip"], {})
        times = [moment for moment in (head.get("at"), written.timestamp() if written else None, item["created"])
                 if moment]
        try:
            latest = datetime.fromtimestamp(max(times), timezone.utc).astimezone(now.tzinfo) if times else None
        except (OverflowError, OSError, ValueError):  # a commit dated beyond what the platform holds
            latest = None
        state = VIEW.activity(latest, now, self.settings.active_minutes, self.settings.recent_minutes)
        if issue and state != "active":
            state = "unknown"  # its modified files were not read: it may be writing right now
        return {
            "id": item["id"], "name": item["name"], "kind": item["kind"],
            "branch": safe_branch(short) if short else (M.say(self.lang, "detached") if item["kind"] != "remote"
                                                        else item["name"]),
            "head": item["tip"][:7], "head_date": iso(head["at"], now.tzinfo) if head.get("at") else "",
            "subject": head.get("subject", ""),
            "created": iso(item["created"], now.tzinfo) if item["created"] else "",
            "ahead": item["ahead"], "behind": item["behind"],
            "modified": sum(1 for entry in entries if entry["kind"] == "modified"), "untracked": len(candidates),
            "conflicted": sum(1 for entry in entries if entry["kind"] == "conflict"), "kept": kept,
            "files_read": not issue, "files_issue": issue, "stale": item["stale"], "gone": item.get("gone", False),
            "last_write": written.astimezone(now.tzinfo).isoformat(timespec="seconds") if written else "",
            "last_activity": latest.isoformat(timespec="seconds") if latest else "",
            "activity": state, "operation": item["operation"], "remote": item["remote"],
            "pushed": item["remote"] == "pushed",
            "ledger": ledger_state, "error": head_ledger["error"] if head_ledger and not head_ledger["valid"] else "",
            "reason": reason, "reason_detail": detail, "overlay": bool(changes) and not reason,
            "changes": changes[:VIEW.MAX_CHANGES], "hidden_changes": max(0, len(changes) - VIEW.MAX_CHANGES),
            "decisions": decisions[:VIEW.MAX_CHANGES], "sections": sections,
            "tasks": list(dict.fromkeys(moved + inferred)), "inferred": inferred,
            "commits": [{"sha": commit["sha"][:7], "at": iso(commit["at"], now.tzinfo),
                         "subject": commit["subject"]} for commit in commits],
            "updated_at": (head_ledger or {}).get("updated_at", ""),
            "_changes": changes, "_head_tasks": (head_ledger or {}).get("tasks", {}),
        }


def _sessions_folder(name: str, folders: tuple[tuple[str, ...], ...]) -> bool:
    """Whether an untracked entry of the main checkout is a worktree folder, one of the folders holding it, or inside
    one: compared part by part, never as a prefix of text (".claude/" holds ".claude/worktrees", "wt" is no prefix of
    "wtnotes.md")."""
    parts = [FILES.fold(part) for part in name.rstrip("/").split("/") if part]
    for folder in folders:
        own = [FILES.fold(part) for part in folder]
        if parts == own[:len(parts)] or own == parts[:len(own)]:
            return True
    return False


def _holds_git(folder: Path) -> bool:
    """Whether a new folder holds an entry named .git: such a folder is never handed to git, whose checks would read
    that entry (and follow it, a network share included)."""
    try:
        os.lstat(folder / ".git")
        return True
    except OSError:
        return False

