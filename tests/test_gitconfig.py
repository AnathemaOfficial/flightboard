# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests of the configuration reading: the installed git reads the configuration's bytes for the board, so it must
give what git reads from the file itself, and no spelling git accepts may hide an include, core.worktree or a partial
clone's remote from the board.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import os
import random
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import CONFIG_READ, GIT, NOW, git_starts, load
from tests.test_modes import Plain

gitconfig = load("gitconfig")
files = load("files")
gitreads = load("gitreads")
collector_module = load("collector")
Settings = load("config").Settings

BOM = "\ufeff"
# each one hides a key from a reader that cuts lines its own way; git reads the key (checked below against git)
HIDDEN = {
    BOM + "[include]\n\tpath = x\n": "include",
    BOM + '[includeIf "gitdir:**"]\n\tpath = x\n': "include",
    BOM + "[core]\n\tworktree = /x\n": "core_worktree",
    BOM + '[remote "origin"]\n\tpromisor = true\n': "promisor",
    BOM + "[extensions]\n\tpartialClone = o\n": "promisor",
    "[core][include]\n\tpath = x\n": "include",
    '[core] [includeIf "gitdir:**"]\n\tpath = x\n': "include",
    "[x][core]\n\tworktree = /x\n": "core_worktree",
    '[x] [remote "o"]\n\tpromisor = true\n': "promisor",
    "[core]\n\tnote = x \\\n[other]\n\tworktree = /x\n": "core_worktree",
    "[core]\r\n\tnote = x \\\r\n[other]\r\n\tworktree = /x\r\n": "core_worktree",
    '[core]\n\tnote = "x \\\n[other]"\n\tworktree = /x\n': "core_worktree",
    '[remote "origin"]\n\tnote = x\r[core]\n\tpromisor = true\n': "promisor",
    **{f"[core]\n\tnote = a{cut}[x]\n\tworktree = /x\n": "core_worktree"
       for cut in ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")},
    '[remote "o"]\n\tpartialclonefilter = blob:none\n': "promisor",
    '[remote "o"]\n\tpartialclonefilter =\n': "promisor",
    "[core] worktree = x\n": "core_worktree",
    "[Include]\npath = y\n": "include",
}
PLAIN = {
    '[core]\n\trepositoryformatversion = 0\n[remote "origin"]\n\turl = https://example.invalid/x.git\n'
    "\tfetch = +refs/heads/*:refs/remotes/origin/*\n": "",
    "[core]\r\n\tbare = false\r\n": "",
    BOM + "[core]\n\tbare = false\n": "",
    '[remote "o"]\n\tpromisor = off\n': "",
    '[remote "o"]\n\tpromisor = FALSE\n': "",
    "[core]\n\tnote = a ; [include]\n": "",
    '[core]\n\tnote = "[include]"\n': "",
    "[core\n": "config_unreadable",
    "[core]\n\tk = a\0b\n": "",  # git reads the value up to the NUL, as every later command reads it
    "[extensions]\n\tobjectFormat = sha1\n": "",
    "[extensions]\n\tobjectFormat = sha256\n": "object_format",
    "[extensions]\n\tobjectformat = SHA1\n": "object_format",  # a spelling git refuses: refused here too
}
# hand-written spellings git accepts or refuses, for the comparison with git
CORPUS = [
    b"key = v\n[core]\n\tx = 1\n", b'[ "sub"]\n\tk = v\n', b"[core]\n\tk\r= v\n", b"[core]\r\tk = v\n",
    b"[core]\n\x0b\tk = v\n", b'[core]\n\tk = "a\\\nb"\n', b'[sec "a\\"b"]\n\tk = v\n', b'[sec "a"  ]\n\tk = v\n',
    b"[sec.Sub]\n\tK = v\n", b"[core] [include] path = x\n", b"\xef\xbb[core]\n\tk = v\n", b"\xef\xbb\xbf",
    b"[core]\n\tk = a\rb\n", b"[core]\n\tk = a\x0bb\n\tz=1\n", b'[core]\n\tk = a ; c\n\tj = " a " # x\n',
    b'[core]\n\tk\n\tj =\n\tm = ""\n', b"[core]\n\tk = \\q\n", b"[core]\n\tk-1 = v\n\t1k = v\n", b"[co_re]\n\tk = v\n",
    b"[core]\n\tk = v", b"[core]\n\tk", b'[core]\n\tk = "open\n', b"[]\n\tk = v\n", b"[core\n\tk = v\n",
    b'[sec "x" ]\n', b'[sec\t"x"]\n\tk=v\n', b'[sec "x\\\ny"]\n\tk=v\n', b'[sec "\xc3\xa9"]\n\tk=\xff\xfe\n',
    b"# c\n; c\n[a]\n\tb = c # d\n\te = f\\\\\n", b'[a]\n\tb = x\\t\\n\\b\\"\n', b"[a]\r\n\tb = x\r\n\tc = y \r\n",
    b"[a] b\n", b"[a] b = c [d]\n", b"[a]\n\tb = c\n\t[d]\n\te = f\n", b"[a]\n  \t  \n\tb = c\n",
    b"[a]\n\tb\t=\tc\n", b"[a.b.c]\n\tk = v\n", b'[a "b.c"]\n\tk = v\n', b'[A "B"]\n\tK = V\n', b"[a]\n\tk # c\n",
    b"[a]\n\tk \\\n= v\n", b'[a]\n\tk = "x" "y"  z \n', b"[a]\n\tk = \\\n", b"[a]\n\tk = x\\", b"[a]#c\n\tk=v\n",
    b"[a];c\n\tk=v\n", b"[a]\n\tk=v\r", b"[a]\n\tk=\r\n", b"[a]\n\tk\t\r\n", b"[a]\n\tk\r", b"\r\n[a]\r\n",
    b'[a "\\\\"]\n\tk=v\n', b'[a ""]\n\tk=v\n', b"[a.]\n\tk=v\n", b"[.a]\n\tk=v\n", b"[-]\n\tk=v\n",
]
PIECES = [b"[core]", b"[include]", b'[includeIf "gitdir:x"]', b'[remote "o"]', b"[remote.o]", b"[Core]", b"[a.b]",
          b'[a "b\\"c"]', b'[ "s"]', b"[]", b"[x", b'[x "y" ]', b"worktree", b"path", b"promisor",
          b"partialclonefilter", b"k", b"K-1", b"1k", b"a_b", b"=", b" = ", b"\t=\t", b"v", b'"v"', b'" v "', b"a b",
          b"\\", b"\\\\", b"\\t", b"\\q", b'"', b"]", b"[", b"#", b";", b"[d]", b"\xc3\xa9", b"\xe2\x80\xa8",
          b"\xc2\x85", b" ", b"\t", b"\r", b"\x0b", b"\x0c", b"\n", b"\n", b"\n", b"\r\n", b"\\\n"]
RANDOM_CASES = 150


def _git_entries(data: bytes, folder: Path) -> list[tuple[bytes, bytes | None]] | None:
    """What git itself reads in this configuration, or None when git refuses it."""
    path = folder / "config"
    path.write_bytes(data)
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, HOME=str(folder), XDG_CONFIG_HOME=str(folder),
               GIT_CEILING_DIRECTORIES=str(folder.parent))
    proc = subprocess.run([GIT, "config", "--file", str(path), "--no-includes", "--null", "--list"], cwd=folder,
                          env=env, capture_output=True)
    if proc.returncode != 0:
        return None
    found = []
    for record in proc.stdout.split(b"\0")[:-1]:
        name, newline, value = record.partition(b"\n")
        found.append((name, value if newline else None))
    return found


def _ours(data: bytes) -> list[tuple[bytes, bytes | None]] | None:
    try:
        return gitconfig.entries(data)
    except gitconfig.ConfigError:
        return None


class ReaderTest(unittest.TestCase):
    def test_no_spelling_hides_an_include_a_worktree_or_a_promisor(self) -> None:
        for text, expected in {**HIDDEN, **PLAIN}.items():
            with self.subTest(text=text):
                self.assertEqual(files.risky_config(text), expected)
                self.assertEqual(files.risky_config(text.encode("utf-8")), expected)

    def test_half_a_byte_order_mark_is_refused_as_git_refuses_it(self) -> None:
        self.assertEqual(files.risky_config(b"\xef\xbb[core]\n"), "config_unreadable")
        self.assertEqual(files.risky_config(b"\xef\xbb\xbf\xef\xbb\xbf[core]\n"), "config_unreadable")

    def test_a_worse_finding_is_never_hidden_by_a_promisor(self) -> None:
        self.assertEqual(files.risky_config('[remote "o"]\n\tpromisor = yes\n[core]\n\tworktree = /x\n'),
                         "core_worktree")
        self.assertEqual(files.risky_config("[extensions]\n\tpartialclone = o\n[include]\n\tpath = x\n"), "include")

    def test_entries_are_named_and_valued_as_git_gives_them(self) -> None:
        self.assertEqual(gitconfig.entries(b'[A "B.c"]\n\tK = " v "  ; c\n\tflag\n[d.E]\n\tx =\n'),
                         [(b"a.B.c.k", b" v "), (b"a.B.c.flag", None), (b"d.e.x", b"")])
        self.assertEqual(gitconfig.entries(b"[a]\n\tk = one \\\n  two\n"), [(b"a.k", b"one   two")])

    def test_a_worktree_configuration_holds_only_what_claude_code_writes(self) -> None:
        for text, plain in (("[core]\n\tsparseCheckout = true\n\tsparseCheckoutCone = TRUE\n", True),
                            (BOM + "[core]\n\tlongpaths = false\n", True), ("# nothing\n", True),
                            ('[core]\n\tlongpaths = "true" # c\n', True), ("[core]\n\tlongpaths\n", False),
                            ("[core]\n\tsparseCheckout = false\n\tsparseCheckoutCone = false\n"
                             "[index]\n\tsparse = false\n", True),  # what git sparse-checkout disable writes
                            ("[index]\n\tsparse = yes\n", False),
                            ("[core]\n\tlongpaths = yes\n", False), ("[core]\n\thooksPath = x\n", False),
                            ("[extensions]\n\tworktreeConfig = true\n", False),
                            ('[core "x"]\n\tlongpaths = true\n', False),
                            ("[core][include]\n\tpath = x\n", False), ("[core]\n\tlongpaths = true \\\n[x]\n", False),
                            ("[core\n", False)):
            with self.subTest(text=text):
                self.assertEqual(files.plain_config(text), plain)

    def test_codex_worktree_config_accepts_only_its_exact_no_environment_sentinel(self) -> None:
        for text in ("[codex]\n\tlocalEnvironmentConfigPath = __none__\n",
                     BOM + "[codex]\n\tlocalEnvironmentConfigPath = __none__\n",
                     '[CoDeX]\r\n\tLoCaLeNvIrOnMeNtCoNfIgPaTh = "__none__"\r\n',
                     "[core]\n\tlongpaths = true\n[codex]\n\tlocalEnvironmentConfigPath = __none__\n"
                     "[index]\n\tsparse = false\n"):
            with self.subTest(text=text):
                self.assertTrue(files.plain_config(text))
                self.assertTrue(files.plain_config(text.encode("utf-8")))

    def test_codex_worktree_config_refuses_other_values_and_keys(self) -> None:
        for text in ("[codex]\n\tlocalEnvironmentConfigPath = /local/environment.toml\n",
                     "[codex]\n\tlocalEnvironmentConfigPath = //server/share/environment.toml\n",
                     "[codex]\n\tlocalEnvironmentConfigPath = __NONE__\n",
                     '[codex]\n\tlocalEnvironmentConfigPath = " __none__ "\n',
                     "[codex]\n\tlocalEnvironmentConfigPath =\n",
                     "[codex]\n\tlocalEnvironmentConfigPath\n",
                     "[codex]\n\tother = __none__\n",
                     '[codex "other"]\n\tlocalEnvironmentConfigPath = __none__\n',
                     "[codex]\n\tlocalEnvironmentConfigPath = __none__\n"
                     "\tlocalEnvironmentConfigPath = /local/environment.toml\n"):
            with self.subTest(text=text):
                self.assertFalse(files.plain_config(text))

    def test_codex_sentinel_cannot_hide_an_include_or_hooks_configuration(self) -> None:
        sentinel = "[codex]\n\tlocalEnvironmentConfigPath = __none__\n"
        for dangerous in ("[include]\n\tpath = /local/other.cfg\n",
                          '[includeIf "gitdir:**"]\n\tpath = //server/share/other.cfg\n',
                          "[core]\n\thooksPath = /local/hooks\n",
                          "[codex]\n\tother = true\n"):
            for text in (sentinel + dangerous, dangerous + sentinel):
                with self.subTest(text=text):
                    self.assertFalse(files.plain_config(text))


@unittest.skipIf(GIT is None, "git absent")
class SameAsGitTest(unittest.TestCase):
    """The board's reading against git reading the same bytes from a file: the same keys, the same values, the same
    refusals."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name).resolve() / "probe"
        self.folder.mkdir()

    def compare(self, data: bytes) -> None:
        with self.subTest(data=data):
            self.assertEqual(_ours(data), _git_entries(data, self.folder))

    def test_every_hidden_key_is_one_git_reads(self) -> None:
        for text, expected in HIDDEN.items():
            data = text.encode("utf-8")
            self.compare(data)
            with self.subTest(text=text):  # what git itself reads there is the trap
                self.assertEqual(gitconfig.weigh(_git_entries(data, self.folder) or []), expected)

    def test_hand_written_spellings(self) -> None:
        for data in CORPUS + [text.encode("utf-8") for text in PLAIN]:
            self.compare(data)

    def test_codex_sentinel_uses_gits_case_bom_and_line_ending_rules(self) -> None:
        for data in (b"[codex]\n\tlocalEnvironmentConfigPath = __none__\n",
                     b'\xef\xbb\xbf[CoDeX]\r\n\tLoCaLeNvIrOnMeNtCoNfIgPaTh = "__none__"\r\n'):
            with self.subTest(data=data):
                expected = [(b"codex.localenvironmentconfigpath", b"__none__")]
                self.assertEqual(_git_entries(data, self.folder), expected)
                self.assertEqual(gitconfig.entries(data), expected)
                self.assertTrue(files.plain_config(data))

    def test_random_spellings(self) -> None:
        chance = random.Random(2026)  # the same cases at every run
        for _ in range(RANDOM_CASES):
            data = (b"\xef\xbb\xbf" if chance.random() < 0.1 else b"") + b"".join(
                chance.choice(PIECES) for _ in range(chance.randint(1, 14)))
            self.compare(data)


@unittest.skipIf(GIT is None, "git absent")
class SparseCheckoutTest(unittest.TestCase):
    """What git sparse-checkout writes in a config.worktree keeps a checkout readable."""

    def test_a_sparse_checkout_set_then_disabled_is_read(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.git("sparse-checkout", "set", "--cone", "docs")
        repo.git("sparse-checkout", "disable")  # leaves sparseCheckout, sparseCheckoutCone and index.sparse
        self.assertIn("[index]", (repo.root / ".git" / "config.worktree").read_text(encoding="utf-8"))
        self.assertEqual(files.git_dir_problem(repo.root), "")
        tree = repo.worktree("w", "claude/w")
        repo.git("sparse-checkout", "set", "--sparse-index", "--cone", "docs", where=tree)
        found = collector_module.Collector(repo.root, Settings()).snapshot(NOW)
        self.assertEqual(found["main"]["state"], "ok")
        session = {item["name"]: item for item in found["sessions"]}["w"]
        self.assertEqual(session["reason"], "")  # what sparse-checkout writes in its config.worktree is nothing odd
        # its files are read, unless git made its index a sparse one (as git 2.43 does here): never handed to git
        self.assertIn((session["files_issue"], session["files_read"]), (("", True), ("sparse_index", False)))


@unittest.skipIf(GIT is None, "git absent")
class HiddenTrapTest(unittest.TestCase):
    """End to end: a trap spelled so a line reader misses it stops the board before any git command on the
    repository: git only reads the configuration's bytes on its standard input, with no repository around it."""

    def setUp(self) -> None:
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        self.config = self.repo.root / ".git" / "config"
        self.original = self.config.read_bytes()

    def read_with_git_off_the_repository(self) -> dict:
        with git_starts() as starts:
            found = collector_module.Collector(self.repo.root, Settings()).snapshot(NOW)
        self.assertTrue(starts)
        for command, kwargs in starts:  # refused before the first git command on the repository
            self.assertEqual((command[1:], (kwargs.get("env") or {}).get("GIT_DIR")), (CONFIG_READ, os.devnull))
        return found

    def test_a_byte_order_mark_or_a_second_header_hides_nothing(self) -> None:
        elsewhere = (Path(self.repo._tmp.name).resolve() / "elsewhere.cfg").as_posix()
        for head in (b"\xef\xbb\xbf[include]\n", b"[core][include]\n", b"[core]\n\tnote = x \\\n[other]\n[include]\n"):
            with self.subTest(head=head):
                self.config.write_bytes(head + b"\tpath = " + elsewhere.encode() + b"\n" + self.original)
                self.assertEqual(files.git_dir_problem(self.repo.root), "include")
                found = self.read_with_git_off_the_repository()
                self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
                self.assertIn("a configuration include", found["main"]["reason_text"])

    def test_a_partial_clone_filter_is_a_promisor_for_an_older_git(self) -> None:
        self.config.write_bytes(self.original + b'[remote "origin"]\n\turl = x\n\tpartialclonefilter = blob:none\n')
        collector = collector_module.Collector(self.repo.root, Settings())
        with mock.patch.object(collector.git, "version", return_value=(2, 44)):
            found = collector.snapshot(NOW)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_trap"))
        self.assertIn("partial clone", found["main"]["reason_text"])

    def test_a_configuration_git_cannot_parse_is_named(self) -> None:
        self.config.write_bytes(self.original + b"[core\n")
        self.assertEqual(files.git_dir_problem(self.repo.root), "config_unreadable:config")
        found = self.read_with_git_off_the_repository()
        self.assertIn("an unreadable git configuration (config)", found["main"]["reason_text"])


@unittest.skipIf(GIT is None, "git absent")
class ListingTest(unittest.TestCase):
    """git's listing of a configuration is read within GIT_TIMEOUT and up to MAX_LISTING_BYTES, whatever git does with
    its pipes, and a git that cannot list any configuration is git's fault, never the repository's."""

    def test_a_listing_past_the_cap_is_refused_at_once(self) -> None:
        section = b'[a "' + b"x" * 4000 + b'"]\n'  # git repeats the section's name, 4 KB here, for each of its keys
        self.assertEqual(len(gitconfig.entries(section + b"\tk\n" * 900)), 900)  # a listing of 3.6 MB: read
        start = time.monotonic()
        with git_starts() as starts, self.assertRaises(gitconfig.ConfigError):  # 20 MB listed from 19 KB: refused
            gitconfig.entries(section + b"\tk\n" * 5000)
        self.assertLess(time.monotonic() - start, gitreads.GIT_TIMEOUT)
        self.assertEqual([proc.poll() is None for proc in starts.processes], [False])  # git was stopped
        self.assertEqual(files.risky_config(section + b"\tk\n" * 5000), "config_unreadable")

    @unittest.skipUnless(os.name == "nt", "Git for Windows' launchers")
    def test_a_git_started_through_a_launcher_is_refused_at_once_too(self) -> None:
        launcher = Path(gitreads.executable()).parents[2] / "bin" / "git.exe"  # Git\mingw64\bin\git.exe: Git\bin
        if not launcher.is_file():
            self.skipTest("no Git for Windows launcher next to this git")
        section = b'[a "' + b"x" * 4000 + b'"]\n'
        start = time.monotonic()
        with mock.patch.object(gitreads, "executable", return_value=str(launcher)), \
                mock.patch.object(gitconfig, "GRACE", 30, create=True), \
                self.assertRaises(gitconfig.ConfigError):  # killing the launcher leaves its git running
            gitconfig.entries(section + b"\tk\n" * 5000)
        self.assertLess(time.monotonic() - start, gitreads.GIT_TIMEOUT / 2)  # its output closed, that git ends too

    def test_no_second_deadline_is_spent_once_git_is_stopped(self) -> None:
        start = time.monotonic()
        with mock.patch.object(gitreads, "GIT_TIMEOUT", 3), mock.patch.object(gitconfig, "GRACE", 0.5, create=True), \
                mock.patch.object(gitconfig, "_stop", lambda proc: None), \
                git_starts("import time; time.sleep(30)") as starts:  # a stop that left both pipes open
            self.addCleanup(lambda: [proc.kill() for proc in starts.processes])
            with self.assertRaises(gitreads.GitFailed):
                gitconfig.entries(b"[core]\n" + b"\tk = v\n" * 150_000)  # more than a pipe holds
        self.assertLess(time.monotonic() - start, 3 + 2)  # the deadline and two short waits, not three deadlines

    def test_the_deadline_holds_while_git_reads_nothing(self) -> None:
        start = time.monotonic()
        with mock.patch.object(gitreads, "GIT_TIMEOUT", 1), git_starts("import time; time.sleep(20)") as starts:
            with self.assertRaises(gitreads.GitFailed):  # about 1 MB: more than a pipe holds, so writing it waits
                gitconfig.entries(b"[core]\n" + b"\tk = v\n" * 150_000)
        self.assertLess(time.monotonic() - start, 8)
        self.assertEqual([proc.poll() is None for proc in starts.processes], [False])  # git was stopped

    def test_a_git_that_lists_no_configuration_is_no_trap(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        with git_starts("import sys; sys.exit(1)"):  # a git too old to read its input, or a broken install
            with self.assertRaises(gitreads.GitFailed):
                files.risky_config(b"[core]\n\tbare = false\n")
            found = collector_module.Collector(repo.root, Settings()).snapshot(NOW)
        self.assertEqual((found["main"]["state"], found["main"]["reason"]), ("unreadable", "git_failed"))


@unittest.skipIf(GIT is None, "git absent")
class WorktreeConfigTest(unittest.TestCase):
    def test_a_worktree_whose_configuration_git_cannot_read_is_alone_left_unread(self) -> None:
        repo = Plain()
        self.addCleanup(repo.close)
        repo.worktree("w1", "claude/w1")
        repo.worktree("w2", "claude/w2")
        odd = b"[core]\n\tsparseCheckout = false\n"
        (repo.root / ".git" / "worktrees" / "w2" / "config.worktree").write_bytes(odd)
        real = gitconfig.entries

        def slow(data: bytes, deadline=None) -> list:
            if data == odd:
                raise gitreads.GitFailed("TimeoutExpired")  # git did not answer in time for that one
            return real(data, deadline)

        with mock.patch.object(gitconfig, "entries", side_effect=slow):
            found = collector_module.Collector(repo.root, Settings()).snapshot(NOW)
        self.assertEqual(found["main"]["state"], "ok")
        sessions = {item["name"]: item for item in found["sessions"]}
        self.assertEqual((sessions["w2"]["reason"], sessions["w1"]["reason"]), ("admin_unchecked", ""))


if __name__ == "__main__":
    unittest.main()
