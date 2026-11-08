# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for repositories at git's edges: a git too old for the board, a partial clone that never fetched its trees,
files whose names git reads in a setting or in another file, a sparse checkout, the object formats and ref stores the
board does not read, the commit-graph, a history too long to walk in time, and folders of .git that hold very many
entries.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, git_version, load
from tests.test_files import make_link
from tests.test_modes import Plain

cli = load("cli")
collector_module = load("collector")
files = load("files")
gitreads = load("gitreads")
Settings = load("config").Settings
CAP = 300  # above the 258 entries objects/ may hold (256 fan-out folders, info and pack)
TASKS = json.dumps({"tasks": [{"id": "T-1", "title": "One", "status": "planned"}]}) + "\n"


def read(root: Path, settings=None) -> dict:
    return collector_module.Collector(root, settings or Settings()).snapshot(NOW)


def clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}


def by_name(found: dict) -> dict[str, dict]:
    return {session["name"]: session for session in found["sessions"]}


@contextlib.contextmanager
def runs(trace: tuple[str, Path] | None = None):
    """Every git run of the board, as (command, completed process); with trace, each run also asks git for that trace
    (GIT_TRACE_REFS, GIT_TRACE2_PERF) in that file."""
    calls: list[tuple[list[str], subprocess.CompletedProcess]] = []
    real = subprocess.run

    def spy(command, *args, **kwargs):
        if trace:
            kwargs["env"] = {**(kwargs.get("env") or {}), trace[0]: str(trace[1])}
        proc = real(command, *args, **kwargs)
        calls.append((list(command), proc))
        return proc

    with mock.patch.object(gitreads.subprocess, "run", side_effect=spy):
        yield calls


@unittest.skipIf(GIT is None, "git absent")
class OldGitTest(unittest.TestCase):
    def test_a_git_too_old_for_the_board_is_told_so(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        real = subprocess.run

        def older(command, *args, **kwargs):  # what git 2.40 does: --attr-source is an unknown option to it
            if any(str(part).startswith("--attr-source") for part in command):
                return subprocess.CompletedProcess(command, 129, b"", b"unknown option: --attr-source")
            if command[-1] == "version":
                return subprocess.CompletedProcess(command, 0, b"git version 2.40.4\n", b"")
            return real(command, *args, **kwargs)

        with mock.patch.object(gitreads.subprocess, "run", side_effect=older):
            found = read(repo.root)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_too_old"))
        self.assertIn("git 2.41 or newer", found["main"]["reason_text"])


@unittest.skipIf(git_version() < gitreads.NO_LAZY_FETCH, "a partial clone is read with git 2.45 or newer")
class TreelessCloneTest(unittest.TestCase):
    """A clone that fetched its commits but not their trees: the board reads it without ever fetching one."""

    def test_main_is_read_and_its_older_history_cut(self) -> None:
        source = Plain()
        self.addCleanup(source.close)
        for index, when in enumerate(("09:00", "09:10", "09:20", "09:30"), start=1):
            tasks = {"tasks": [{"id": f"T-{n}", "title": f"Task {n}", "status": "planned"}
                               for n in range(1, index + 1)]}
            source.commit(source.root, "tasks.json", json.dumps(tasks) + "\n", f"docs: {index} tasks", when)
        source.git("config", "uploadpack.allowFilter", "true")
        base = Path(source._tmp.name).resolve()
        clone, marker = base / "clone", base / "PROGRAM-STARTED.txt"
        subprocess.run([GIT, "clone", "-q", "--filter=tree:0", "--no-local", source.root.as_uri(), str(clone)],
                       check=True, capture_output=True, env=clean_env())
        subprocess.run([GIT, "-C", str(clone), "config", "remote.origin.uploadpack",
                        f"echo started > '{marker.as_posix()}'; git-upload-pack"], check=True, capture_output=True,
                       env=clean_env())
        self.assertEqual(files.git_dir_problem(clone), files.PROMISOR)
        found = read(clone)
        self.assertFalse(marker.exists())  # no tree was ever fetched for the board
        self.assertEqual((found["main"]["state"], found["ledger"]["kind"]), ("ok", "tasks"))
        # said as such, never as main's last 300 moves
        self.assertEqual((found["limits"]["history_unread"], found["limits"]["history_cut"]), (True, False))
        self.assertIn("could not be read", found["i18n"]["messages"]["page.history_unread"])
        self.assertFalse(marker.exists())


@unittest.skipIf(GIT is None, "git absent")
class NamedFilesTest(unittest.TestCase):
    """Files whose name git reads in a setting or in another file's content: none outside the repository is opened,
    and a name the board would look up as another path than git's is refused."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.base = Path(self.repo._tmp.name).resolve()
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def test_a_diff_order_file_and_a_follow_walk_open_nothing(self) -> None:
        self.repo.commit(self.repo.root, "tasks.json", TASKS, "docs: tasks", "08:40")
        tree = self.repo.worktree("w", "claude/w")
        (tree / "README.md").write_text("changed\n", encoding="utf-8")  # a modified tracked file: status diffs it
        config = self.repo.root / ".git" / "config"
        missing = (self.outside / "order.txt").as_posix()  # git stops when it cannot read the file it is told to
        config.write_text(config.read_text(encoding="utf-8") + f"[diff]\n\torderFile = {missing}\n"
                          "[log]\n\tfollow = true\n", encoding="utf-8")
        # without main's reflog, its history is walked from main itself, through the commit that wrote the ledger
        (self.repo.root / ".git" / "logs" / "refs" / "heads" / "main").unlink()
        found = read(self.repo.root)
        self.assertFalse(found["limits"]["history_unread"])
        session = by_name(found)["w"]
        self.assertEqual((session["reason"], session["files_read"], session["modified"]), ("", True, 1))

    def test_an_index_name_that_is_not_utf8_is_refused(self) -> None:
        tree = self.repo.worktree("w", "claude/w")
        blob = subprocess.run([GIT, "-C", str(tree), "hash-object", "-w", "--stdin"], input=b"x\n",
                              capture_output=True, check=True, env=clean_env()).stdout.strip()
        tip = self.repo.git("rev-parse", "main").encode("ascii")
        for line in (b"100644 " + blob + b"\td\x81x\n", b"160000 " + tip + b"\ts\x81\n"):
            with self.subTest(line=line[:6]):
                subprocess.run([GIT, "-C", str(tree), "update-index", "--index-info"], input=line,
                               capture_output=True, check=True, env=clean_env())
                session = by_name(read(self.repo.root))["w"]
                self.assertEqual((session["files_issue"], session["files_read"]), ("odd_tracked_path", False))
                gone = b"0 " + b"0" * 40 + b"\t" + line.split(b"\t")[1]  # mode 0: the entry leaves the index
                subprocess.run([GIT, "-C", str(tree), "update-index", "--index-info"], input=gone,
                               capture_output=True, check=True, env=clean_env())

    def test_an_untracked_name_that_is_not_utf8_is_never_asked(self) -> None:
        with mock.patch.object(gitreads.subprocess, "run", side_effect=AssertionError("git started")):
            found = gitreads.Git().ignored(self.repo.root / ".git", self.repo.root, ["d\udc81x.txt"])
        self.assertEqual(found, set())

    def test_a_pack_named_outside_the_repository_is_never_read(self) -> None:
        self.repo.git("repack", "-adq")
        self.repo.git("multi-pack-index", "write")
        pack = self.repo.root / ".git" / "objects" / "pack"
        [index] = pack.glob("pack-*.idx")
        stem = index.name[:-len(".idx")]
        named = b"../../../../outside/" + b"a" * (len(index.name) - len("../../../../outside/.idx")) + b".idx"
        midx = pack / "multi-pack-index"
        os.chmod(midx, 0o644)
        data = midx.read_bytes()
        self.assertEqual(data.count(index.name.encode("ascii")), 1)
        midx.write_bytes(data.replace(index.name.encode("ascii"), named))  # the same length: git reads it as written
        for old in pack.glob(stem + ".*"):  # the objects now live only outside the repository
            old.replace(self.outside / (named.decode("ascii").split("/")[-1][:-len(".idx")] + old.suffix))
        found = read(self.repo.root)  # git looks for packs in the repository alone: main cannot be read
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_failed"))

    def test_git_looks_up_no_other_name_than_it_is_given(self) -> None:
        """No ambiguity check of a full id or a full ref name and no shortened reflog selector: git never looks for
        .git/<id>, refs/tags/<name> or another spelling a session could plant a link on."""
        self.repo.commit(self.repo.root, "tasks.json", TASKS, "docs: tasks", "08:40")
        tree = self.repo.worktree("w", "claude/w")
        (tree / "README.md").write_text("changed\n", encoding="utf-8")
        trace = self.base / "refs-trace.txt"
        with runs(("GIT_TRACE_REFS", trace)):
            found = read(self.repo.root)
        self.assertEqual((found["main"]["state"], by_name(found)["w"]["files_read"]), ("ok", True))
        names = set(re.findall(r"read_raw_ref: (\S+?): ", trace.read_text(encoding="utf-8", errors="replace")))
        self.assertIn("refs/heads/main", names)
        self.assertEqual({name for name in names if not re.fullmatch(r"[A-Z_]+|refs/heads/(?:main|claude/w)", name)},
                         set())

    def test_a_reflog_git_could_not_read_makes_it_look_up_nothing_else(self) -> None:
        """git, finding no entry it can read in a reflog, would look up refs/tags/<name> and the like: the board
        reads the reflogs itself, and git none."""
        self.repo.commit(self.repo.root, "tasks.json", TASKS, "docs: tasks", "08:40")
        self.repo.worktree("w", "claude/w")
        reflog = self.repo.root / ".git" / "logs" / "refs" / "heads" / "main"
        tip = self.repo.git("rev-parse", "main")
        line = f"{'0' * 40} {tip} Test <test@example.com> 1794000000 +0000\tcommit: x"
        for label, content in (("empty", b""), ("no line end", line.encode("ascii")),
                               ("time zero", line.replace("1794000000", "0").encode("ascii") + b"\n"),
                               ("deleted", None)):
            with self.subTest(reflog=label):
                if content is None:
                    reflog.unlink()
                else:
                    reflog.write_bytes(content)
                trace = self.base / f"refs-{label}.txt"
                with runs(("GIT_TRACE_REFS", trace)) as calls:
                    found = read(self.repo.root)
                self.assertEqual(found["main"]["state"], "ok")
                text = trace.read_text(encoding="utf-8", errors="replace")
                names = set(re.findall(r"read_raw_ref: (\S+?): ", text))
                self.assertEqual({name for name in names
                                  if not re.fullmatch(r"[A-Z_]+|refs/heads/(?:main|claude/w)", name)}, set())
                self.assertNotIn("reflog", text)
                self.assertEqual([command for command, _ in calls if "-g" in command], [])

    def test_a_reflog_is_read_through_plain_folders_only(self) -> None:
        tip = self.repo.git("rev-parse", "main")
        elsewhere = self.outside / "logs"
        elsewhere.mkdir()
        (elsewhere / "x").write_text(f"{'0' * 40} {tip} Test <test@example.com> 1794000000 +0000\tcommit: outside\n",
                                     encoding="ascii")
        heads = self.repo.root / ".git" / "logs" / "refs" / "heads" / "claude"
        heads.mkdir(parents=True)
        if not make_link(elsewhere, heads / "sub"):
            self.skipTest("this system does not let the test make a link")
        self.assertEqual(files.read_reflog(self.repo.root, "refs/heads/claude/sub/x", 10), [])
        entries = files.read_reflog(self.repo.root, "refs/heads/main", 10)
        self.assertEqual(entries[0]["sha"], tip)
        self.assertTrue(entries[0]["via"].startswith("commit"))

    def test_a_reflog_is_read_as_git_reads_it(self) -> None:
        """A line with no tab before its reason counts, as git counts it; a long reflog is read from its end, and
        main's older moves then come from its first-parent line, never said to be its last 300."""
        tip = self.repo.git("rev-parse", "main")
        reflog = self.repo.root / ".git" / "logs" / "refs" / "heads" / "main"
        reflog.write_bytes(reflog.read_bytes() + f"{tip} {tip} T <t@example.com> 1794000100 +0000\r\n".encode("ascii"))
        self.assertEqual(files.read_reflog(self.repo.root, "refs/heads/main", 10)[0]["at"], 1794000100)
        first, rest = reflog.read_bytes().split(b"\n", 1)
        reflog.write_bytes(first + b"\n" + b"x" * 5000 + b"\n" + rest)  # main's first move, far from the end
        with mock.patch.object(files, "MAX_REFLOG_BYTES", 1000):
            found = read(self.repo.root)
        self.assertFalse(found["limits"]["history_cut"])
        self.assertIn(("docs: first", True), [(move["via"], move["approx"]) for move in found["moves"]])

    def test_a_head_of_64_digits_is_never_given_to_git(self) -> None:
        """64 hex digits are a ref name to git in a SHA-1 repository: such a HEAD is no commit the board asks git."""
        self.repo.worktree("w", "claude/w")
        (self.repo.root / ".git" / "worktrees" / "w" / "HEAD").write_text("ab" * 32 + "\n", encoding="ascii")
        trace = self.base / "refs-64.txt"
        with runs(("GIT_TRACE_REFS", trace)) as calls:
            found = read(self.repo.root)
        self.assertEqual(found["main"]["state"], "ok")
        self.assertNotIn("ab" * 32, trace.read_text(encoding="utf-8", errors="replace"))
        self.assertEqual([command for command, _ in calls if any("ab" * 32 in part for part in command)], [])

    def test_git_status_counts_no_stash(self) -> None:
        tip = self.repo.git("rev-parse", "main")
        stash = self.repo.root / ".git" / "logs" / "refs" / "stash"
        stash.write_text("".join(f"{'0' * 40} {tip} Test <test@example.com> 1794000000 +0000\tWIP {n}\n"
                                 for n in range(3)), encoding="ascii")
        config = self.repo.root / ".git" / "config"
        config.write_text(config.read_text(encoding="utf-8") + "[status]\n\tshowStash = true\n", encoding="utf-8")
        with runs() as calls:
            self.assertEqual(read(self.repo.root)["main"]["state"], "ok")
        statuses = [proc.stdout for command, proc in calls if "status" in command]
        self.assertTrue(statuses)
        self.assertEqual([out for out in statuses if b"# stash" in out], [])

    def test_a_link_among_the_reflogs_stops_git(self) -> None:
        if not make_link(self.outside, self.repo.root / ".git" / "logs" / "refs" / "stash"):
            self.skipTest("this system does not let the test make a link")
        self.assertEqual(files.git_dir_problem(self.repo.root), "link:logs/refs")


@unittest.skipIf(GIT is None, "git absent")
class SparseCheckoutTest(unittest.TestCase):
    """A sparse worktree: git looks up no index name on disk before the board has checked it (a skip-worktree name
    could point anywhere, and git checks none), counts a file a session wrote outside its sparse patterns as git
    itself counts it, and never gets a sparse index, which it would write into .git/objects to read."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        for folder in ("a", "b", "c"):
            self.repo.commit(self.repo.root, f"{folder}/f.txt", f"{folder}\n", f"feat: {folder}", "08:40")
        self.tree = self.repo.worktree("w", "claude/w")
        self.admin = self.repo.root / ".git" / "worktrees" / "w"
        self.base = Path(self.repo._tmp.name).resolve()

    def sparse(self, *options: str) -> None:
        """Sparse checkout of a/ alone, whatever the user's own settings say of split indexes."""
        self.repo.git("-c", "core.splitIndex=false", "sparse-checkout", "set", *options, "a", where=self.tree)

    def test_git_looks_up_no_index_name_the_board_has_not_checked(self) -> None:
        self.sparse("--cone")
        (self.tree / "a" / "new.txt").write_text("new\n", encoding="utf-8")  # an untracked file: check-ignore runs
        real = subprocess.run
        calls: list[tuple[str, Path]] = []

        def spy(command, *args, **kwargs):
            trace = self.base / f"trace2-{len(calls)}.txt"
            kwargs["env"] = {**(kwargs.get("env") or {}), "GIT_TRACE2_PERF": str(trace)}
            calls.append((next(part for part in command if part in gitreads.VERBS), trace))
            return real(command, *args, **kwargs)

        with mock.patch.object(gitreads.subprocess, "run", side_effect=spy):
            session = by_name(read(self.repo.root))["w"]
        self.assertEqual((session["reason"], session["files_read"], session["untracked"]), ("", True, 1))
        verbs = {verb for verb, _ in calls}
        self.assertLessEqual({"ls-files", "check-ignore", "status"}, verbs)
        looked = {verb for verb, trace in calls if trace.exists() and "clear_skip_worktree_from_present_files"
                  in trace.read_text(encoding="utf-8", errors="replace")}
        self.assertEqual(looked - {"status"}, set())  # git status alone, once every name has passed the checks

    def test_a_file_written_outside_the_sparse_patterns_counts_as_modified(self) -> None:
        self.sparse("--cone")
        (self.tree / "c").mkdir()
        (self.tree / "c" / "f.txt").write_text("written outside the patterns\n", encoding="utf-8")
        session = by_name(read(self.repo.root))["w"]
        self.assertEqual((session["reason"], session["files_read"], session["modified"]), ("", True, 1))

    def test_a_sparse_index_is_never_handed_to_git(self) -> None:
        self.sparse("--cone", "--sparse-index")
        (self.tree / "a" / "f.txt").write_text("staged\n", encoding="utf-8")
        self.repo.git("-c", "core.splitIndex=false", "add", "a/f.txt", where=self.tree)  # git would write new trees
        self.assertEqual(files.index_state(self.admin, self.repo.root), "sparse")
        objects = self.repo.root / ".git" / "objects"
        before = {path: path.stat().st_mtime_ns for path in objects.rglob("*") if path.is_file()}
        (self.tree / "a" / "new.txt").write_text("new\n", encoding="utf-8")
        with runs() as calls:
            session = by_name(read(self.repo.root))["w"]
        self.assertEqual((session["files_issue"], session["files_read"], session["untracked"]),
                         ("sparse_index", False, 0))
        self.assertIn("new files are not listed either", session["files_issue_text"])
        trees = [Path(part.split("=", 1)[1]).resolve() for command, _ in calls for part in command
                 if part.startswith("--work-tree=")]
        self.assertNotIn(self.tree.resolve(), trees)
        self.assertEqual({path: path.stat().st_mtime_ns for path in objects.rglob("*") if path.is_file()}, before)

    def test_a_split_index_is_never_handed_to_git(self) -> None:
        """git resets the time of a split index's shared part at every read, through a hard link too."""
        self.repo.git("update-index", "--split-index", where=self.tree)
        [shared] = self.admin.glob("sharedindex.*")
        os.utime(shared, (1_000_000_000, 1_000_000_000))
        self.assertEqual(files.index_state(self.admin, self.repo.root), "split")
        with runs() as calls:
            session = by_name(read(self.repo.root))["w"]
        self.assertEqual((session["files_issue"], session["files_read"]), ("split_index", False))
        self.assertEqual(shared.stat().st_mtime, 1_000_000_000)
        trees = [Path(part.split("=", 1)[1]).resolve() for command, _ in calls for part in command
                 if part.startswith("--work-tree=")]
        self.assertNotIn(self.tree.resolve(), trees)

    def test_a_full_index_is_never_made_sparse(self) -> None:
        """A worktree set for a sparse index whose index is full for now: git status, which keeps the sparse checkout,
        would make it sparse in memory, writing its trees into .git/objects."""
        self.sparse("--cone", "--sparse-index")
        (self.tree / "a" / "f.txt").write_text("staged\n", encoding="utf-8")
        self.repo.git("-c", "core.splitIndex=false", "add", "a/f.txt", where=self.tree)
        self.repo.git("-c", "core.splitIndex=false", "-c", "index.sparse=false", "update-index", "--index-version",
                      "3", where=self.tree)
        self.assertEqual(files.index_state(self.admin, self.repo.root), "")
        objects = self.repo.root / ".git" / "objects"
        before = {path: path.stat().st_mtime_ns for path in objects.rglob("*") if path.is_file()}
        session = by_name(read(self.repo.root))["w"]
        self.assertEqual((session["files_issue"], session["files_read"]), ("", True))
        self.assertEqual({path: path.stat().st_mtime_ns for path in objects.rglob("*") if path.is_file()}, before)

    def test_every_index_git_writes_is_told_apart(self) -> None:
        (self.tree / "a" / "linksdir").write_text("x\n", encoding="utf-8")  # a name holding both signatures
        self.repo.git("-c", "core.splitIndex=false", "add", "-A", where=self.tree)
        for version in ("2", "3", "4"):
            with self.subTest(version=version):
                self.repo.git("-c", "core.splitIndex=false", "-c", "index.recordEndOfIndexEntries=true",
                              "update-index", "--no-split-index", "--index-version", version, where=self.tree)
                self.assertEqual(files.index_state(self.admin, self.repo.root), "")
        self.repo.git("update-index", "--split-index", where=self.tree)
        self.assertTrue(list(self.admin.glob("sharedindex.*")))
        self.assertEqual(files.index_state(self.admin, self.repo.root), "split")
        self.repo.git("-c", "core.splitIndex=false", "update-index", "--no-split-index", where=self.tree)
        self.assertEqual(files.index_state(self.admin, self.repo.root), "")
        self.sparse("--cone", "--sparse-index")
        for version in ("3", "4"):
            with self.subTest(sparse=version):
                self.repo.git("-c", "core.splitIndex=false", "-c", "index.recordEndOfIndexEntries=true",
                              "update-index", "--index-version", version, where=self.tree)
                self.assertEqual(files.index_state(self.admin, self.repo.root), "sparse")
        # an index naming a sparse directory but cut short: the board cannot tell, and hands it to no git
        (self.admin / "index").write_bytes(b"DIRC" + struct.pack(">II", 3, 5) + b"sdir" * 20)
        self.assertEqual(files.index_state(self.admin, self.repo.root), "unreadable")


@unittest.skipIf(GIT is None, "git absent")
class ObjectFormatTest(unittest.TestCase):
    def test_a_sha256_repository_is_not_read(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        other = Path(repo._tmp.name).resolve() / "sha256"
        subprocess.run([GIT, "init", "-q", "-b", "main", "--object-format=sha256", str(other)], check=True,
                       capture_output=True, env=clean_env())
        subprocess.run([GIT, "-C", str(other), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-q", "--allow-empty", "-m", "first"], check=True, capture_output=True,
                       env=clean_env())
        # the board's empty tree is a SHA-1 id: in this repository it would be a ref name a session could write
        self.assertEqual(files.git_dir_problem(other), "object_format")
        found = read(other)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("a SHA-256 object store", found["main"]["reason_text"])


@unittest.skipIf(git_version() < (2, 45), "git init --ref-format arrived in git 2.45")
class ReftableTest(unittest.TestCase):
    def test_a_reftable_repository_is_not_read(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        other = Path(repo._tmp.name).resolve() / "reftable"
        subprocess.run([GIT, "init", "-q", "-b", "main", "--ref-format=reftable", str(other)], check=True,
                       capture_output=True, env=clean_env())
        subprocess.run([GIT, "-C", str(other), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                        "commit", "-q", "--allow-empty", "-m", "first"], check=True, capture_output=True,
                       env=clean_env())
        self.assertEqual(files.git_dir_problem(other), "ref_storage")
        found = read(other)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("a reftable ref store", found["main"]["reason_text"])


@unittest.skipIf(GIT is None, "git absent")
class CommitGraphTest(unittest.TestCase):
    """The commit-graph keeps a long history fast; it is read only while its chain names no file elsewhere."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.base = Path(self.repo._tmp.name).resolve()
        self.graphs = self.repo.root / ".git" / "objects" / "info" / "commit-graphs"

    def test_a_plain_commit_graph_is_read(self) -> None:
        self.assertTrue(files.commit_graph_plain(self.repo.root))  # no graph at all
        self.repo.git("commit-graph", "write", "--reachable", "--split")
        self.assertTrue((self.graphs / "commit-graph-chain").is_file())
        self.assertTrue(files.commit_graph_plain(self.repo.root))
        with runs() as calls:
            self.assertEqual(read(self.repo.root)["main"]["state"], "ok")
        reads = [command for command, _ in calls if "version" not in command]
        self.assertTrue(reads)
        self.assertEqual([command for command in reads if "core.commitGraph=false" in command], [])

    def test_a_chain_written_otherwise_leaves_the_graph_off(self) -> None:
        self.graphs.mkdir(parents=True)
        name = "ab" * 20
        for data in (f"{name}\r\n", name.upper() + "\n", name, "", f"{name}\n../x\n"):
            with self.subTest(data=data):
                (self.graphs / "commit-graph-chain").write_bytes(data.encode("ascii"))
                self.assertFalse(files.commit_graph_plain(self.repo.root))

    def test_a_commit_graph_named_outside_the_repository_is_never_read(self) -> None:
        self.graphs.mkdir(parents=True)
        name = "ab" * 20
        (self.graphs / f"graph-{name}").mkdir()  # the folder a POSIX path walks through
        # graph-<name>, commit-graphs, info, objects, .git and the repository folder: six steps up
        (self.graphs / "commit-graph-chain").write_bytes(f"{name}{'/..' * 6}/outside/x\n".encode("ascii"))
        (self.base / "outside").mkdir()
        (self.base / "outside" / "x.graph").write_bytes(b"tiny\n")  # git would say it is too small
        self.assertFalse(files.commit_graph_plain(self.repo.root))
        with mock.patch.dict(os.environ, {"LC_ALL": "C", "LANG": "C"}), runs() as calls:
            self.assertEqual(read(self.repo.root)["main"]["state"], "ok")
        self.assertTrue(calls)
        for command, proc in calls:
            with self.subTest(command=command[-3:]):
                self.assertIn("core.commitGraph=false", command)
                self.assertNotIn(b"commit-graph", proc.stderr)


@unittest.skipIf(GIT is None, "git absent")
class LongHistoryTest(unittest.TestCase):
    def test_branches_that_cannot_be_listed_in_time_leave_the_worktrees(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("w", "claude/w")
        self.assertFalse(read(repo.root)["limits"]["branches_unread"])
        real = gitreads.Git.refs

        def slow(git, common, unmerged_from=None):  # what a walk of millions of commits does past git's time limit
            if unmerged_from:
                raise gitreads.GitFailed("TimeoutExpired")
            return real(git, common)

        with mock.patch.object(gitreads.Git, "refs", slow):
            found = read(repo.root)
        self.assertEqual(found["main"]["state"], "ok")
        self.assertIn("w", by_name(found))
        self.assertTrue(found["limits"]["branches_unread"])
        self.assertIn("in time", found["i18n"]["messages"]["page.branches_unread"])
        self.assertIn("could not be listed in time", cli.resume_text(found))  # a branch may wait for a merge go


@unittest.skipUnless(GIT is not None and os.name == "nt", "Windows' 260-character paths")
class LongPathTest(unittest.TestCase):
    """A tracked path of 260 characters or more: a board that cannot reach it (Windows' default) must not take it for
    a deleted file, while git, told core.longpaths by the repository, would reach a .git planted there."""

    def test_a_long_tracked_path_keeps_git_status_out(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        tree = repo.worktree("w", "claude/w")
        repo.git("config", "extensions.worktreeConfig", "true")
        (repo.root / ".git" / "worktrees" / "w" / "config.worktree").write_text("[core]\n\tlongpaths = true\n",
                                                                                 encoding="utf-8")
        base = Path(repo._tmp.name).resolve()
        outside = base / "outside-gitdir"
        subprocess.run([GIT, "init", "-q", "--bare", str(outside)], check=True, capture_output=True, env=clean_env())
        (outside / "config").write_text("[[[\n", encoding="utf-8")  # git says so when it reads it
        name = "/".join(["p" * 50] * 5) + "/sub"
        deep = tree.joinpath(*name.split("/"))
        try:
            deep.mkdir(parents=True)
            (deep / ".git").write_text(f"gitdir: {outside.as_posix()}\n", encoding="utf-8")
        except OSError:
            self.skipTest("this system does not let the test make a long path")
        main = repo.git("rev-parse", "main")
        repo.git("-c", "core.longpaths=true", "update-index", "--add", "--cacheinfo", f"160000,{main},{name}",
                 where=tree)
        self.assertGreaterEqual(len(str(deep)), files.MAX_PATH)
        real = os.lstat

        def short_paths(path, *args, **kwargs):  # what a process not opted into long paths meets: Windows' default
            if units(os.fspath(path)) >= files.MAX_PATH:
                raise FileNotFoundError(3, "The system cannot find the path specified", os.fspath(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "lstat", side_effect=short_paths), runs() as calls:
            session = by_name(read(repo.root))["w"]
        self.assertEqual((session["files_issue"], session["files_read"]), ("long_tracked_path", False))
        self.assertEqual([proc.stderr for _, proc in calls if b"outside-gitdir" in proc.stderr], [])

    def test_a_path_is_as_long_as_windows_counts_it(self) -> None:
        """Windows and git count UTF-16 units: a character beyond the basic plane counts twice."""
        repo = Plain()
        self.addCleanup(repo.close)
        tree = repo.worktree("w", "claude/w")
        name = "q" * (255 - len(str(tree)) - 1 - 10) + "\U0001F4C4" * 10  # 255 characters, 265 units
        self.assertEqual((len(str(tree / name)), units(str(tree / name))), (255, 265))
        blob = subprocess.run([GIT, "-C", str(tree), "hash-object", "-w", "--stdin"], input=b"x\n",
                              capture_output=True, check=True, env=clean_env()).stdout.decode("ascii").strip()
        repo.git("-c", "core.longpaths=true", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}",
                 where=tree)
        session = by_name(read(repo.root))["w"]
        self.assertEqual((session["files_issue"], session["files_read"]), ("long_tracked_path", False))


def units(path: str) -> int:
    """A path's length as Windows counts it: in UTF-16 units."""
    return len(path.encode("utf-16-le", "surrogatepass")) // 2


@unittest.skipUnless(GIT is not None and os.name == "nt", "Windows' own path rules")
class WindowsNamesTest(unittest.TestCase):
    def test_a_worktree_named_with_a_final_dot_is_not_read(self) -> None:
        """x.. names the folder x as the last part of a path, while x..\\sub names nothing: the board would check
        no tracked path there, and git, working in x, would follow a submodule's .git outside the repository."""
        repo = Plain()
        self.addCleanup(repo.close)
        tree = repo.worktree("x", "claude/x")
        outside = Path(repo._tmp.name).resolve() / "outside-gitdir"
        subprocess.run([GIT, "init", "-q", "--bare", str(outside)], check=True, capture_output=True, env=clean_env())
        (outside / "config").write_text("[[[\n", encoding="utf-8")  # git says so when it reads it
        (tree / "sub").mkdir()
        (tree / "sub" / ".git").write_text(f"gitdir: {outside.as_posix()}\n", encoding="utf-8")
        main = repo.git("rev-parse", "main")
        repo.git("update-index", "--add", "--cacheinfo", f"160000,{main},sub", where=tree)
        self.assertEqual(by_name(read(repo.root))["x"]["files_issue"], "submodule_git")
        gitdir = repo.root / ".git" / "worktrees" / "x" / "gitdir"
        text = gitdir.read_text(encoding="utf-8").strip()
        self.assertTrue(text.endswith("/x/.git"))
        gitdir.write_text(text[:-len("/x/.git")] + "/x../.git\n", encoding="utf-8")
        with runs() as calls:
            found = read(repo.root)
        self.assertEqual([proc.stderr for _, proc in calls if b"outside-gitdir" in proc.stderr], [])
        session = {session["id"]: session for session in found["sessions"]}["x"]
        self.assertEqual((session["reason"], session["files_read"]), ("outside", False))

    def test_a_tracked_path_through_a_device_name_is_refused(self) -> None:
        """A folder named nul is the NUL device as the last part of a path, a real folder in the middle of one: the
        board's checks would find nothing where git, walking sub/nul/a/x, follows a .git outside the repository."""
        repo = Plain()
        self.addCleanup(repo.close)
        tree = repo.worktree("w", "claude/w")
        # a folder named nul goes only through \\?\ paths, removal included
        self.addCleanup(shutil.rmtree, "\\\\?\\" + str(tree), True)
        outside = Path(repo._tmp.name).resolve() / "outside-gitdir"
        subprocess.run([GIT, "init", "-q", "--bare", str(outside)], check=True, capture_output=True, env=clean_env())
        (outside / "config").write_text("[[[\n", encoding="utf-8")  # git says so when it reads it
        repo.git("config", "core.protectNTFS", "false")
        blob = subprocess.run([GIT, "-C", str(tree), "hash-object", "-w", "--stdin"], input=b"x\n",
                              capture_output=True, check=True, env=clean_env()).stdout.decode("ascii").strip()
        for name in ("sub/nul/a/x", "nul"):
            with self.subTest(name=name):
                folder = "\\\\?\\" + str(tree.joinpath(*name.split("/")))
                os.makedirs(folder, exist_ok=True)
                with open(folder + "\\.git", "w", encoding="utf-8") as handle:
                    handle.write(f"gitdir: {outside.as_posix()}\n")
                repo.git("-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo",
                         f"100644,{blob},{name}", where=tree)
                with runs() as calls:
                    session = by_name(read(repo.root))["w"]
                self.assertEqual([proc.stderr for _, proc in calls if b"outside-gitdir" in proc.stderr], [])
                self.assertEqual((session["files_issue"], session["files_read"]), ("odd_tracked_path", False))
                repo.git("-c", "core.protectNTFS=false", "update-index", "--force-remove", name, where=tree)

    def test_no_read_goes_through_a_link_named_nul(self) -> None:
        """lstat of a last part named nul answers the NUL device, whatever is there (a junction included)."""
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("w", "claude/w")
        outside = Path(repo._tmp.name).resolve() / "outside"
        outside.mkdir()
        for name in ("gitdir", "HEAD", "commondir"):
            (outside / name).write_text("x\n", encoding="utf-8")
        import _winapi
        junction = "\\\\?\\" + str(repo.root / ".git" / "worktrees" / "nul")
        try:
            _winapi.CreateJunction(str(outside), junction)
        except OSError:
            self.skipTest("this system does not let the test make a junction")
        self.addCleanup(os.rmdir, junction)  # the junction alone, never what it leads to
        self.assertFalse(files.no_link(repo.root / ".git" / "worktrees" / "nul", repo.root))
        opened: list[str] = []
        real = os.open

        def spy(path, *args, **kwargs):
            opened.append(os.fspath(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(files.os, "open", side_effect=spy):
            found = read(repo.root)
        self.assertNotIn("nul", [session["id"] for session in found["sessions"]])
        self.assertEqual([path for path in opened if "\\nul\\" in path.lower()], [])


@unittest.skipUnless(GIT is not None and hasattr(os, "mkfifo"), "pipes in the file system")
class SpecialFilesTest(unittest.TestCase):
    """A pipe planted where the board or git reads a small file never holds the reading."""

    def test_a_pipe_never_holds_the_reading(self) -> None:
        for place in ("worktrees/w/HEAD", "worktrees/w/gitdir", "worktrees/w/rebase-merge/head-name", "HEAD"):
            with self.subTest(place=place):
                repo = Plain()
                self.addCleanup(repo.close)
                repo.worktree("w", "claude/w")
                repo.worktree("other", "claude/other")
                path = repo.root / ".git" / place
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    path.unlink()
                os.mkfifo(path)
                self.assertTrue(stat.S_ISFIFO(os.lstat(path).st_mode))
                found = within_git_time(lambda: read(repo.root))
                self.assertIsNotNone(found, "the reading waits on the pipe")
                if place == "HEAD":  # git is not run at all: it would wait on it at every command
                    self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
                    self.assertIn("a pipe, a socket or a device in .git (HEAD)", found["main"]["reason_text"])
                else:
                    self.assertEqual(found["main"]["state"], "ok")
                    self.assertIn("other", by_name(found))

    def test_a_pipe_for_a_gitignore_never_holds_the_reading(self) -> None:
        """git check-ignore opens the .gitignore of every folder on the way to a name it is asked about, and of an
        asked folder itself: a pipe there would hold it until its time limit, at every reading."""
        for place in (".gitignore", "deep/a/b/c/.gitignore"):
            with self.subTest(place=place):
                repo = Plain()
                self.addCleanup(repo.close)
                tree = repo.worktree("w", "claude/w")
                path = tree / place
                path.parent.mkdir(parents=True, exist_ok=True)
                (path.parent / "new.txt").write_text("new\n", encoding="utf-8")  # a new file: check-ignore is asked
                os.mkfifo(path)
                with runs() as calls:
                    found = within_git_time(lambda: read(repo.root))
                self.assertIsNotNone(found, "the reading waits on the pipe")
                self.assertGreaterEqual(by_name(found)["w"]["untracked"], 1)
                asked = [command for command, _ in calls if "check-ignore" in command
                         and f"--work-tree={tree}" in command]
                self.assertEqual(asked, [])


def within_git_time(reading):
    """What reading() returns, if it returns well within git's time limit; None if it is still waiting."""
    found: list = []
    thread = threading.Thread(target=lambda: found.append(reading()), daemon=True)
    thread.start()
    thread.join(gitreads.GIT_TIMEOUT - 2)
    return found[0] if found and not thread.is_alive() else None


@unittest.skipIf(GIT is None, "git absent")
class ManyEntriesTest(unittest.TestCase):
    """The folders of branches are listed in full, however many they hold; another folder of .git past the cap is
    refused, and said to be crowded, never to hold a link."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        patcher = mock.patch.object(files, "MAX_GIT_FOLDER_ENTRIES", CAP)  # a small cap stands for 50,000
        patcher.start()
        self.addCleanup(patcher.stop)
        self.git = self.repo.root / ".git"

    def test_many_branches_and_reflogs_are_read(self) -> None:
        tip = self.repo.git("rev-parse", "main") + "\n"
        for folder in (self.git / "refs" / "remotes" / "origin", self.git / "logs" / "refs" / "remotes" / "origin",
                       self.git / "refs" / "heads"):
            folder.mkdir(parents=True, exist_ok=True)
            for index in range(CAP + 1):
                (folder / f"pr-{index}").write_text(tip, encoding="ascii")
        self.assertEqual(files.git_dir_problem(self.repo.root), "")
        self.assertEqual(read(self.repo.root)["main"]["state"], "ok")

    def test_another_crowded_folder_is_said_to_be_crowded(self) -> None:
        pack = self.git / "objects" / "pack"
        pack.mkdir(parents=True, exist_ok=True)
        for index in range(CAP + 1):
            (pack / f"tmp_{index}").write_bytes(b"")
        self.assertEqual(files.git_dir_problem(self.repo.root), "many:objects/pack")
        found = read(self.repo.root)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn(f"more than {CAP} entries in a folder of .git (objects/pack)", found["main"]["reason_text"])
        self.assertNotIn("link", found["main"]["reason_text"])
        french = read(self.repo.root, Settings(lang="fr"))
        self.assertIn(f"plus de {CAP} entrées dans un dossier de .git (objects/pack)", french["main"]["reason_text"])


if __name__ == "__main__":
    unittest.main()
