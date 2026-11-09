# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests of the board's defences and edge cases: links in git's state files, kept files counted afresh, bounded task
lists and summary lines, the notes that say what "main" is, the sessions' own folder, empty task files, subfolders,
distinct session ids, inference, usage messages and snapshot files.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, git_version, load
from tests.test_files import make_link
from tests.test_modes import Plain

collector_module = load("collector")
cli = load("cli")
view = load("view")
files = load("files")
gitreads = load("gitreads")
Settings = load("config").Settings


def by_name(found: dict) -> dict[str, dict]:
    return {session["name"]: session for session in found["sessions"]}


def read(root: Path, settings=None) -> dict:
    return collector_module.Collector(root, settings or Settings()).snapshot(NOW)


def drop_link(path: Path) -> None:
    """Remove a link or a junction to a folder, never what it leads to."""
    try:
        os.rmdir(path)  # a junction, or a Windows link to a folder
    except OSError:
        os.unlink(path)


def tasks_json(count: int, status: str = "done", prefix: str = "T") -> str:
    return json.dumps({"tasks": [{"id": f"{prefix}-{index}", "title": f"Task {index}", "status": status}
                                 for index in range(1, count + 1)]}, indent=1) + "\n"


@unittest.skipIf(GIT is None, "git absent")
class GitStateLinksTest(unittest.TestCase):
    """A link on one of the files git reads for a worktree's state keeps git out of it."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.outside = Path(self.repo._tmp.name).resolve() / "elsewhere"
        self.outside.mkdir()

    def test_a_link_in_a_worktree_admin_folder_keeps_git_away(self) -> None:
        self.repo.worktree("w1", "claude/w1")
        if not make_link(self.outside, self.repo.root / ".git" / "worktrees" / "w1" / "rebase-merge"):
            self.skipTest("this system does not let the test make a link")
        session = by_name(read(self.repo.root))["w1"]
        self.assertEqual((session["reason"], session["files_read"]), ("odd_admin", False))

    def test_a_link_in_the_main_git_state_stops_git(self) -> None:
        if not make_link(self.outside, self.repo.root / ".git" / "rebase-apply"):
            self.skipTest("this system does not let the test make a link")
        found = read(self.repo.root)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("a link in .git (rebase-apply)", found["main"]["reason_text"])

    def test_links_on_the_files_a_walk_of_the_history_opens_stop_git(self) -> None:
        git = self.repo.root / ".git"
        (git / "rebase-merge").mkdir()
        (git / "objects" / "pack" / "multi-pack-index.d").mkdir()
        (git / "refs" / "remotes" / "origin").mkdir(parents=True)
        for place, said in ((git / "shallow", "shallow"), (git / "info" / "grafts", "info/grafts"),
                            (git / "REBASE_HEAD", "REBASE_HEAD"), (git / "FETCH_HEAD", "FETCH_HEAD"),
                            (git / "rebase-merge" / "head-name", "rebase-merge"), (git / "refs" / "stash", "refs"),
                            (git / "refs" / "heads" / "claude", "refs/heads"),
                            (git / "refs" / "remotes" / "origin" / "main", "refs/remotes/origin"),
                            (git / "logs" / "refs" / "heads" / "planted", "logs/refs/heads"),
                            (git / "objects" / "zz", "objects"),
                            (git / "objects" / "info" / "commit-graph", "objects/info"),
                            (git / "objects" / "pack" / "pack-1.idx", "objects/pack"),
                            (git / "objects" / "pack" / "multi-pack-index.d" / "chain",
                             "objects/pack/multi-pack-index.d"),
                            (git / "reftable", "reftable"), (git / ("sharedindex." + "0" * 40), "sharedindex"),
                            (git / ("SharedIndex." + "1" * 40), "sharedindex")):  # a volume may ignore case
            with self.subTest(place=said):
                if not make_link(self.outside, place):
                    self.skipTest("this system does not let the test make a link")
                try:  # refused before git starts, and the entry's own name never reaches the page
                    found = read(self.repo.root)
                    self.assertEqual(found["main"]["reason"], "git_trap")
                    self.assertIn(f"a link in .git ({said})", found["main"]["reason_text"])
                finally:
                    drop_link(place)
        for made in (git / "rebase-merge", git / "objects" / "pack" / "multi-pack-index.d",
                     git / "refs" / "remotes" / "origin"):
            made.rmdir()
        self.assertEqual(read(self.repo.root)["main"]["reason"], "")  # each link gone, the board reads again

    def test_a_folder_or_an_entry_git_removes_meanwhile_is_no_link(self) -> None:
        folder = self.repo.root / ".git" / "rebase-merge"
        folder.mkdir()

        class Listing:  # what os.scandir gives: one entry, removed by git before its own lstat
            def __enter__(self):
                return iter([Gone()])

            def __exit__(self, *exc) -> bool:
                return False

        class Gone:
            name = "head-name"

            def stat(self, follow_symlinks: bool = True):
                raise FileNotFoundError(self.name)

        with mock.patch.object(files.os, "scandir", return_value=Listing()):
            self.assertFalse(files._linked_entry(folder, self.repo.root))

        def ended(path):  # the rebase ends between the folder's lstat and its listing
            folder.rmdir()  # empty: no listing is needed to remove it
            raise FileNotFoundError(path)

        with mock.patch.object(files.os, "scandir", side_effect=ended):
            self.assertFalse(files._linked_entry(folder, self.repo.root))
        folder.mkdir()
        real, refusals = os.scandir, [PermissionError("denied"), PermissionError("denied")]

        def deleting(path):  # Windows refuses to list a folder git is deleting, for a few milliseconds
            if refusals:
                raise refusals.pop()
            return real(path)

        with mock.patch.object(files.os, "scandir", side_effect=deleting):
            self.assertEqual(files._linked_entry(folder, self.repo.root), "")
        with mock.patch.object(files.os, "scandir", side_effect=PermissionError("denied")):
            self.assertEqual(files._linked_entry(folder, self.repo.root), "link")  # a folder that never lists

    def test_the_admin_folder_of_a_worktree_keeps_its_shared_index_and_ref_store_plain(self) -> None:
        self.repo.worktree("w3", "claude/w3")
        admin = self.repo.root / ".git" / "worktrees" / "w3"
        for place in (admin / ("sharedindex." + "1" * 40), admin / ("SHAREDINDEX." + "2" * 40), admin / "reftable"):
            with self.subTest(place=place.name[:12]):
                if not make_link(self.outside, place):
                    self.skipTest("this system does not let the test make a link")
                try:
                    session = by_name(read(self.repo.root))["w3"]
                    self.assertEqual((session["reason"], session["files_read"]), ("odd_admin", False))
                finally:
                    drop_link(place)

    def test_a_grafts_line_is_never_read(self) -> None:
        tree = self.repo.worktree("w4", "claude/w4", "main~1")  # older than main: a graft can make it main's parent
        self.repo.commit(tree, "w.py", "w\n", "feat: the session's own work", "09:00")
        main, parent = self.repo.git("rev-parse", "main"), self.repo.git("rev-parse", "main~1")
        tip = self.repo.git("rev-parse", "HEAD", where=tree)
        (self.repo.root / ".git" / "info" / "grafts").write_text(f"{main} {parent} {tip}\n", encoding="ascii")
        self.assertIn(tip, self.repo.git("rev-list", "main"))  # git itself now counts the session's work in main
        session = by_name(read(self.repo.root))["w4"]
        self.assertEqual((session["ahead"], session["stage"]), (1, "committed"))  # the board does not

    def test_a_repository_that_turns_replacement_back_on_is_read_as_it_is(self) -> None:
        real = self.repo.git("rev-parse", "main")
        other = self.repo.worktree("tmp-again", "claude/tmp-again")
        self.repo.commit(other, "z.py", "z\n", "feat: a replacement written by a session", "09:00")
        self.repo.git("replace", real, self.repo.git("rev-parse", "HEAD", where=other))
        self.repo.git("config", "core.useReplaceRefs", "true")
        older = {key: value for key, value in gitreads.environment().items() if key != "GIT_NO_REPLACE_OBJECTS"}
        with mock.patch.object(gitreads, "environment", return_value=older):  # git 2.41: the config wins
            self.assertEqual(read(self.repo.root)["main"]["subject"], "feat: app")

    def test_a_replacement_object_is_never_read(self) -> None:
        real = self.repo.git("rev-parse", "main")
        other = self.repo.worktree("tmp-other", "claude/tmp-other")
        self.repo.commit(other, "z.py", "z\n", "feat: a replacement written by a session", "09:00")
        self.repo.git("replace", real, self.repo.git("rev-parse", "HEAD", where=other))
        self.assertEqual(self.repo.git("log", "-1", "--format=%s", "main"), "feat: a replacement written by a session")
        self.assertEqual(read(self.repo.root)["main"]["subject"], "feat: app")  # the board reads main as it is

    def test_a_link_in_a_worktree_state_folder_keeps_git_away(self) -> None:
        self.repo.worktree("w2", "claude/w2")
        state = self.repo.root / ".git" / "worktrees" / "w2" / "rebase-merge"
        state.mkdir()
        if not make_link(self.outside, state / "onto"):
            self.skipTest("this system does not let the test make a link")
        session = by_name(read(self.repo.root))["w2"]
        self.assertEqual((session["reason"], session["files_read"]), ("odd_admin", False))


@unittest.skipIf(GIT is None, "git absent")
class CommonDirTest(unittest.TestCase):
    """A worktree's commondir padded so that the board and git read two different folders: git would take its
    repository's configuration and attributes from a folder the board never checks."""

    def test_a_filter_planted_behind_a_padded_commondir_never_runs(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        tree = repo.worktree("w", "claude/w")
        base = Path(repo._tmp.name).resolve()
        marker = base / "PROGRAM-STARTED.txt"
        git = repo.root / ".git"
        planted = git / "worktrees" / ".. "  # where git goes with "../..<no-break space>"
        (planted / "objects" / "info").mkdir(parents=True)
        (planted / "objects" / "info" / "alternates").write_text((git / "objects").as_posix() + "\n", encoding="utf-8")
        (planted / "refs" / "heads" / "claude").mkdir(parents=True)
        (planted / "refs" / "heads" / "claude" / "w").write_text(repo.git("rev-parse", "main") + "\n", encoding="ascii")
        (planted / "info").mkdir()
        (planted / "info" / "attributes").write_text("* filter=probe\n", encoding="utf-8")
        (planted / "config").write_text("[core]\n\trepositoryformatversion = 0\n[filter \"probe\"]\n"
                                        f"\tclean = echo started > '{marker.as_posix()}'; cat\n", encoding="utf-8")
        (git / "worktrees" / "w" / "commondir").write_bytes("../.. \n".encode("utf-8"))
        (tree / "README.md").write_text("HELLO\n", encoding="utf-8")  # the same size: git hashes it again
        session = by_name(read(repo.root))["w"]
        self.assertFalse(marker.exists())
        self.assertEqual((session["reason"], session["files_read"]), ("odd_admin", False))


@unittest.skipIf(GIT is None, "git absent")
class LazyFetchTest(unittest.TestCase):
    """A partial clone's remote is never asked for a missing object: no program its configuration names starts."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.tree = self.repo.worktree("w1", "claude/w1")  # made before the remote: the test's own git fetches nothing
        base = Path(self.repo._tmp.name).resolve()
        self.marker = base / "PROGRAM-STARTED.txt"
        other = base / "other.git"
        subprocess.run([GIT, "init", "-q", "--bare", str(other)], check=True, capture_output=True)
        config = self.repo.root / ".git" / "config"
        config.write_text(config.read_text(encoding="utf-8") + (
            '[remote "origin"]\n'
            f"\turl = {other.as_posix()}\n"
            "\tpromisor = true\n"
            f"\tuploadpack = echo started > '{self.marker.as_posix()}'; git-upload-pack\n"), encoding="utf-8")

    def test_a_missing_commit_starts_no_program(self) -> None:
        missing = "1" * 40
        (self.repo.root / ".git" / "worktrees" / "w1" / "HEAD").write_text(missing + "\n", encoding="ascii")
        found = read(self.repo.root)  # a session's HEAD names a commit the store lacks: looked up, never fetched
        self.assertFalse(self.marker.exists())
        # a git that cannot be kept from fetching does not read a partial clone at all
        self.assertEqual(found["main"]["state"], "ok" if git_version() >= gitreads.NO_LAZY_FETCH else "unreadable")
        ghost = self.repo.root / ".git" / "refs" / "heads" / "claude" / "ghost"
        ghost.write_text(missing + "\n", encoding="ascii")
        read(self.repo.root)  # a branch on it: git cannot read the branches any more, and still fetches nothing
        self.assertFalse(self.marker.exists())

    def test_an_older_git_never_reads_a_partial_clone(self) -> None:
        collector = collector_module.Collector(self.repo.root, Settings())
        with mock.patch.object(collector.git, "version", return_value=(2, 44)):
            found = collector.snapshot(NOW)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("partial clone", found["main"]["reason_text"])
        self.assertFalse(self.marker.exists())

    def test_how_a_configuration_names_a_promisor(self) -> None:
        for text, expected in (('[remote "o"]\n\tpromisor = true\n', "promisor"),
                               ("[remote.o]\n\tpromisor\n", "promisor"),
                               ('[remote "o"]\n\tpromisor = off\n', ""),
                               ("[extensions]\n\tpartialClone = o\n", "promisor"),
                               ("[extensions]\n\tpartialclone = o\n[include]\n\tpath = x\n", "include"),
                               ('[remote "o"]\n\tpromisor = yes\n[core]\n\tworktree = /x\n', "core_worktree")):
            with self.subTest(text=text):
                self.assertEqual(files.risky_config(text), expected)


@unittest.skipIf(GIT is None, "git absent")
class KeptFilesTest(unittest.TestCase):
    def test_a_file_added_deep_in_a_kept_folder_is_counted_at_once(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        exclude = repo.root / ".git" / "info" / "exclude"
        exclude.write_text(exclude.read_text(encoding="utf-8") + "notes/\n", encoding="utf-8")
        tree = repo.worktree("done-d", "claude/done-d")
        (tree / "notes" / "2026").mkdir(parents=True)
        collector = collector_module.Collector(repo.root, Settings(kept=("notes",)))
        self.assertEqual((by_name(collector.snapshot(NOW))["done-d"]["kept"]), 0)
        (tree / "notes" / "2026" / "precious.md").write_text("x", encoding="utf-8")
        session = by_name(collector.snapshot(NOW))["done-d"]
        self.assertEqual((session["kept"], session["advice"]), (1, "keep_files"))


@unittest.skipIf(GIT is None, "git absent")
class BoundsTest(unittest.TestCase):
    """What a branch declares never grows the page, the summary or what waits without bound."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = repo = Plain()
        repo.commit(repo.root, "tasks.json", tasks_json(2, "planned"), "docs: tasks", "08:40")
        many = repo.worktree("many-m", "claude/many-m")
        repo.commit(many, "tasks.json", tasks_json(60), "feat: sixty tasks", "09:00")
        flood = repo.worktree("flood-f", "claude/flood-f")
        repo.commit(flood, "tasks.json", tasks_json(5000, prefix="X"), "feat: five thousand tasks", "09:10")
        cls.view = read(repo.root)
        cls.sessions = by_name(cls.view)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repo.close()

    def test_a_card_names_a_bounded_number_of_tasks(self) -> None:
        many = self.sessions["many-m"]
        self.assertEqual((len(many["tasks"]), many["hidden_tasks"]), (view.MAX_SESSION_TASKS, 20))
        self.assertLessEqual(len(self.view["tasks"]), view.MAX_DETAILS)
        self.assertLess(len(json.dumps(self.view)), 400_000)

    def test_a_branch_past_the_cap_is_never_applied(self) -> None:
        flood = self.sessions["flood-f"]
        self.assertEqual((flood["reason"], flood["overlay"], flood["advice"]), ("invalid_ledger", False, "open"))
        detail = self.view["tasks"].get("X-1", {})  # shown as the branch declares it, never as applied
        self.assertEqual((detail.get("declared_in"), detail.get("status_main")), ("flood-f", None))
        self.assertLessEqual(len(self.view["tasks"]), view.MAX_DETAILS)

    def test_the_lines_agents_read_list_five_ids_at_most(self) -> None:
        self.assertIn("1 ready for your merge go (T-1, T-10, T-11, T-12, T-13 and 55 more)", self.view["resume"])
        text = cli.resume_text(self.view)
        self.assertIn("- Give your merge go: T-1, T-10, T-11, T-12, T-13 and 55 more · many-m, 1 commit", text)
        self.assertLess(len(text), 2000)
        french = cli.resume_text(read(self.repo.root, Settings(lang="fr")))
        self.assertIn("T-1, T-10, T-11, T-12, T-13 et 55 de plus", french)

    def test_conflict_and_collision_lines_name_five_sessions_at_most(self) -> None:
        sources = [{"session": f"s-{index}", "to": "done"} for index in range(1, 9)]
        entry = {"conflict": True, "collision": False, "status_main": "planned", "title": "T", "sources": sources}
        [item] = view.Waiting("en").conflicts({"A-1": entry}, [])
        self.assertIn("· s-5: ", item["safe"])
        self.assertTrue(item["safe"].endswith(" and 3 more"), item["safe"])
        self.assertNotIn("s-6", item["text"])
        [item] = view.Waiting("fr").conflicts({"A-1": {**entry, "conflict": False, "collision": True}}, [])
        self.assertTrue(item["safe"].endswith(": s-1, s-2, s-3, s-4, s-5 et 3 de plus"), item["safe"])

    def test_a_capped_line_still_names_what_to_arbitrate(self) -> None:
        sources = [{"session": f"s-{index}", "to": "done", "applied": True, "reason": ""} for index in range(1, 6)]
        sources.append({"session": "s-6", "to": "blocked", "applied": False, "reason": "changed_elsewhere"})
        entry = {"conflict": True, "collision": False, "status_main": "planned", "title": "T", "sources": sources}
        [item] = view.Waiting("en").conflicts({"A-1": entry}, [])
        self.assertIn("· s-6: ", item["safe"])  # the dissent first, then the sessions that agree
        self.assertTrue(item["safe"].endswith(" and 1 more"), item["safe"])
        clash = [{"session": f"s-{index}", "to": "planned", "applied": False, "reason": ""} for index in range(1, 7)]
        clash.append({"session": "s-7", "to": "planned", "applied": False, "reason": "collision"})
        [item] = view.Waiting("en").conflicts({"A-1": {**entry, "conflict": False, "collision": True,
                                                       "sources": clash}}, [])
        self.assertTrue(item["safe"].endswith(": s-7, s-1, s-2, s-3, s-4 and 2 more"), item["safe"])
        holder = [{"session": "a-alpha", "to": "planned", "applied": True, "reason": ""}]  # its version is the live one
        holder += [{"session": f"b{index}-beta", "to": "planned", "applied": False, "reason": "collision"}
                   for index in range(1, 7)]
        [item] = view.Waiting("en").conflicts({"X-1": {"new": True, "status_main": None, "conflict": False,
                                                       "collision": True, "title": "Alpha", "sources": holder}}, [])
        self.assertTrue(item["safe"].endswith(": a-alpha, b1-beta, b2-beta, b3-beta, b4-beta and 2 more"),
                        item["safe"])


@unittest.skipIf(GIT is None, "git absent")
class MainNotesTest(unittest.TestCase):
    """What "main" means for a reading is said on the page, with checked names, and in --resume in fixed words only:
    no branch name read in the repository."""

    def test_a_remote_main_ahead_keeps_the_local_baseline_and_says_so(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        ahead = repo.worktree("tmp-ahead", "claude/tmp-ahead")
        repo.commit(ahead, "x.py", "x\n", "feat: pushed from elsewhere", "09:00")
        repo.git("update-ref", "refs/remotes/origin/main", repo.git("rev-parse", "HEAD", where=ahead))
        found = read(repo.root)
        self.assertEqual(found["main"]["head"], repo.git("rev-parse", "main")[:7])
        self.assertEqual(found["main"]["note_text"],
                         "origin/main is ahead of main (not pulled yet): the page follows local main")
        self.assertIn("Note: the remote's main is ahead (not pulled yet): this summary follows local main.",
                      cli.resume_text(found))
        french = read(repo.root, Settings(lang="fr"))
        self.assertIn("À noter : le main du remote a de l'avance (pas encore tirée) : ce résumé suit main local.",
                      cli.resume_text(french))

    def test_a_diverged_main_is_said(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        apart = repo.worktree("tmp-apart", "claude/tmp-apart", "main~1")
        repo.commit(apart, "y.py", "y\n", "feat: pushed from elsewhere, apart", "09:00")
        repo.git("update-ref", "refs/remotes/origin/main", repo.git("rev-parse", "HEAD", where=apart))
        found = read(repo.root)
        self.assertEqual((found["main"]["note"], found["main"]["ref"]), (["diverged"], "main"))
        self.assertEqual(found["main"]["note_text"], "main and origin/main have diverged")
        self.assertIn("Note: main and the remote's main have diverged.", cli.resume_text(found))
        self.assertIn("À noter : main et le main du remote ont divergé.",
                      cli.resume_text(read(repo.root, Settings(lang="fr"))))

    def test_a_main_read_only_on_the_remote_is_said(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.git("update-ref", "refs/remotes/origin/main", repo.git("rev-parse", "main"))
        repo.git("checkout", "-q", "--detach")
        repo.git("branch", "-D", "main")
        found = read(repo.root)
        self.assertEqual((found["main"]["ref"], found["main"]["note"]), ("origin/main", ["remote_only"]))
        self.assertEqual(found["main"]["note_text"], "there is no local main: the page follows origin/main")
        self.assertIn("Note: there is no local main: this summary follows the remote's.", cli.resume_text(found))
        self.assertIn("À noter : il n'y a pas de main local : ce résumé suit celui du remote.",
                      cli.resume_text(read(repo.root, Settings(lang="fr"))))

    def test_a_main_kept_only_on_the_remote_is_followed_rather_than_guessed(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.git("update-ref", "refs/remotes/origin/main", repo.git("rev-parse", "main"))
        repo.git("branch", "-m", "main", "work")  # the main checkout stays on its own branch
        found = read(repo.root)
        self.assertEqual((found["main"]["ref"], found["main"]["note"]), ("origin/main", ["remote_only"]))

    def test_a_guessed_main_with_an_unusual_name_is_still_read(self) -> None:
        for name in ("dev+x", "dév"):  # git takes these names; the board never gives them to git
            with self.subTest(name=name):
                repo = Plain()
                self.addCleanup(repo.close)
                repo.git("branch", "-m", "main", name)
                found = read(repo.root)
                self.assertEqual((found["main"]["state"], found["main"]["note"]), ("ok", ["guessed"]))
                self.assertEqual(found["main"]["ref"], "(unusual branch name)")

    def test_a_guessed_main_is_said_and_pinned_by_the_flag(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.git("branch", "-m", "main", "develop")
        found = read(repo.root)
        self.assertIn("develop", found["main"]["note_text"])  # the page names it
        notes = [line for line in cli.resume_text(found).splitlines() if line.startswith("Note:")]
        self.assertEqual(notes, ["Note: main is guessed from the main checkout's branch, as the repository has "
                                 "neither main nor master: name it with --main."])  # --resume never does
        self.assertNotIn("Note:", cli.resume_text(read(repo.root, Settings(main="develop"))))


@unittest.skipIf(GIT is None, "git absent")
class SessionsFolderTest(unittest.TestCase):
    def test_the_folder_holding_the_worktrees_is_no_untracked_work(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        (repo.root / ".git" / "info" / "exclude").write_text("", encoding="utf-8")  # .claude neither tracked nor ignored
        repo.worktree("wt1", "claude/wt1")
        checkout = by_name(read(repo.root))["plain"]
        self.assertEqual((checkout["untracked"], checkout["stage"]), (0, "up_to_date"))

    def test_a_folder_named_wt_hides_no_file_named_wtnotes(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("x", "claude/x", folder=("wt",))
        (repo.root / "wtnotes.md").write_text("x", encoding="utf-8")
        named = Settings(worktrees=(*Settings().worktrees, ("wt",)))
        checkout = by_name(read(repo.root, named))["plain"]
        self.assertEqual(checkout["untracked"], 1)  # wtnotes.md, and never wt/


@unittest.skipIf(GIT is None, "git absent")
class TaskFileShapesTest(unittest.TestCase):
    def test_an_empty_task_file_is_a_ledger(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.commit(repo.root, "tasks.toml", "tasks = []\n", "docs: no task yet", "09:00")
        found = read(repo.root)
        self.assertEqual((found["ledger"]["kind"], found["ledger"]["missing"], found["main"]["valid"]),
                         ("tasks", "", True))

    def test_an_unusable_task_file_says_why(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.commit(repo.root, "tasks.toml", 'tasks = [{id = "A-1", status = "todo"}]\n', "docs: a task", "09:00")
        found = read(repo.root)
        self.assertEqual((found["ledger"]["kind"], found["main"]["valid"]), ("tasks", False))
        self.assertIn("maps to none of flightboard's statuses", found["main"]["error"])
        text = cli.resume_text(found)  # --resume says it too, in fixed words: the validator's stay on the page
        self.assertIn("Note: main's ledger (tasks.toml) does not pass its validator (the reason is on the page).", text)
        self.assertNotIn("todo", text)
        self.assertIn("À noter : le registre de main (tasks.toml) ne passe pas son validateur (la raison est sur la "
                      "page).", cli.resume_text(read(repo.root, Settings(lang="fr"))))

    def test_a_version_without_one_usable_task_never_empties_the_history(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        for status, message, when in (("planned", "docs: A-1", "09:00"), ("in_progress", "feat: A-1 started", "09:10"),
                                      ("oops", "docs: a typo", "09:20"),
                                      ("awaiting_review", "feat: A-1 in review", "09:30")):
            repo.commit(repo.root, "tasks.json", tasks_json(1, status, "A"), message, when)
        moves = [(event["task"], event["from"], event["to"]) for event in read(repo.root)["events"]]
        self.assertEqual(moves, [("A-1", "in_progress", "awaiting_review"), ("A-1", "planned", "in_progress")])
        repo.commit(repo.root, "tasks.json", tasks_json(1, "oops", "A"), "docs: the typo again", "09:40")
        found = read(repo.root)  # main's tip itself cannot be used: it removes no task from the history either
        self.assertEqual(found["main"]["valid"], False)
        self.assertEqual([(event["task"], event["to"]) for event in found["events"]],
                         [("A-1", "awaiting_review"), ("A-1", "in_progress")])


@unittest.skipIf(GIT is None, "git absent")
class PlacesTest(unittest.TestCase):
    def test_a_subfolder_reads_its_repository(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        (repo.root / "sub" / "deeper").mkdir(parents=True)
        found = read(repo.root / "sub" / "deeper")
        self.assertEqual((found["main"]["state"], found["repository"]), ("ok", "plain"))

    def test_a_worktree_named_like_the_checkout_keeps_its_own_id(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("checkout", "claude/checkout")
        ids = [session["id"] for session in read(repo.root)["sessions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("@checkout", ids)  # no folder name can be it: a worktree's id is its folder's name
        self.assertEqual(collector_module.CHECKOUT_ID, "@checkout")


class InferenceTest(unittest.TestCase):
    def test_a_word_is_never_inferred_an_id_with_a_digit_is(self) -> None:
        known = {"auth", "login", "AUTH-1"}
        self.assertEqual(view.infer_tasks(["auth-refactor", "feature/login-page"], known), [])
        self.assertEqual(view.infer_tasks(["claude/auth-1-refactor"], known), ["AUTH-1"])


class UsageTest(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main(argv, root=Path(tempfile.gettempdir()), now=NOW)
        return code, err.getvalue()

    def test_a_usage_error_names_what_was_wrong(self) -> None:
        for argv, said in ((["--lang", "de"], "--lang takes en or fr"),
                           (["--lang=fr"], "unknown option '--lang=fr'"),
                           (["--active-minutes", "200"], "--recent-minutes must be more than --active-minutes"),
                           (["--port", "80"], "--port takes a number from 1024 to 65535"),
                           (["--main", "a+b"], "--main takes a branch name"),
                           (["--worktrees", "../x"], "--worktrees takes a plain folder"),
                           (["--ledger-path", "x.toml"], "add --ledger tasks or --ledger roadmap"),
                           (["--resume", "--snapshot"], "--snapshot and --resume cannot go together"),
                           (["--stale-days", "0"], "--stale-days takes a number from 1 to 3650")):
            with self.subTest(argv=argv):
                code, err = self.run_main(argv)
                self.assertEqual(code, 2)
                self.assertIn(said, err)


class SnapshotFileTest(unittest.TestCase):
    def test_snapshots_at_once_never_meet_and_leave_nothing_behind(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "board.html"
            failures: list[BaseException] = []

            def write(text: str) -> None:
                try:
                    for _ in range(20):
                        cli.write_once(output, text)
                except OSError as exc:  # Windows may refuse a replace while another one holds the target
                    if os.name != "nt":
                        failures.append(exc)

            threads = [threading.Thread(target=write, args=(str(index) * 200_000,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
            self.assertEqual(failures, [])
            self.assertEqual(sorted(path.name for path in Path(folder).iterdir()), ["board.html"])
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode) & 0o077, 0)  # its owner alone reads it


if __name__ == "__main__":
    unittest.main()
