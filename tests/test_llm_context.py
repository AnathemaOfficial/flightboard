# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A selected LLM dossier reads only bounded, plain files and freezes their exact contents."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests.fixtures import load

context = load("llm_context")


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.board = {"repository": "demo", "generated_at": "2026-11-21T20:00:00-05:00",
                      "main": {"state": "ok", "valid": True}, "sessions": [{"id": "one", "tasks": []}],
                      "configuration": {"api_key": "never-copy"}}

    def build(self, repo_files=None, local_files=None, board=None):
        return context.build_context(self.board if board is None else board, self.repo,
                                     repo_files or [], local_files or [])

    def write(self, name, raw):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_no_selection_never_opens_or_scans_a_file(self):
        with mock.patch.object(context, "_read", side_effect=AssertionError("unexpected read")), \
                mock.patch.object(context.os, "scandir", side_effect=AssertionError("unexpected scan")), \
                mock.patch.object(Path, "lstat", side_effect=AssertionError("unexpected metadata")):
            found = self.build()
        self.assertEqual(found["files"], [])
        self.assertNotIn("configuration", found["board"])

    def test_repo_and_exact_external_file_are_frozen_with_hashes(self):
        raw = "Une preuve réelle.\r\n".encode()
        self.write("docs/proof.md", raw)
        local = self.root / "run.json"
        local.write_text('{"passed":true}', encoding="utf-8")
        found = self.build(["docs/proof.md"], [str(local)])
        self.assertEqual(found["files"][0], {"source": "repo:docs/proof.md", "sha256": hashlib.sha256(raw).hexdigest(),
                                             "bytes": len(raw), "text": raw.decode()})
        self.assertEqual(found["files"][1]["source"], "local:" + str(local))
        self.board["sessions"][0]["tasks"].append("changed")
        self.write("docs/proof.md", b"changed")
        self.assertEqual(found["board"]["sessions"][0]["tasks"], [])
        self.assertEqual(found["files"][0]["text"], raw.decode())

    def test_invalid_selection_types_excess_and_duplicate_paths(self):
        for names in (None, "proof.md", [1], ["a"] * 13, [""], ["nul\0file"], ["x\n"]):
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, "invalid_selection"):
                context.build_context(self.board, self.repo, names, [])
        with self.assertRaisesRegex(ValueError, "duplicate_selection"):
            self.build(["same", "same"])
        with self.assertRaisesRegex(ValueError, "duplicate_selection"):
            self.build(["same"], [str(self.repo / "same")])

    def test_unsafe_spelling_never_reaches_disk(self):
        repo_names = ["../outside.txt", "./proof.txt", "sub/../proof.txt", "sub//proof.txt", "/etc/passwd",
                       "C:" + "/Windows/win.ini", "file:stream", "NUL.txt", "sub/file."]
        local_names = ["relative.txt", str(self.root) + "/../outside.txt", "//server/share/file", "\\\\server\\x"]
        with mock.patch.object(context, "_read", side_effect=AssertionError("unsafe path reached disk")):
            for name in repo_names:
                with self.subTest(name=name):
                    self.assertEqual(self.build([name])["omitted"][0]["reason"], "unsafe_path")
            for name in local_names:
                with self.subTest(name=name):
                    self.assertEqual(self.build(local_files=[name])["omitted"][0]["reason"], "unsafe_path")

    def test_secret_names_and_git_admin_paths_never_reach_disk(self):
        with mock.patch.object(context, "_read", side_effect=AssertionError("secret path reached disk")):
            for name in (".env", ".env.production", "keys/private.pem", "id_ed25519", ".git/config",
                         ".aws/credentials", ".ssh/config", "secret.key", "vault.kdbx", ".envrc",
                         ".codex/auth.json", ".config/gh/hosts.yml", "application_default_credentials.json"):
                with self.subTest(name=name):
                    self.assertEqual(self.build([name])["omitted"][0]["reason"], "secret_path")

    def test_codex_worktree_path_is_not_blanket_refused(self):
        local = self.root / ".codex/worktrees/scout/repo/README.md"
        local.parent.mkdir(parents=True)
        local.write_text("Architecture and implementation evidence", encoding="utf-8")
        self.assertEqual(len(self.build(local_files=[str(local)])["files"]), 1)

    def test_obvious_secrets_binary_and_non_utf8_are_omitted(self):
        examples = [b'OPENAI_API_KEY="sk-proj-' + b"x" * 24 + b'"', b"-----BEGIN " + b"PRIVATE KEY-----\nabc",
                    b"PASSWORD=not-a-test-password", b'{"api_key":"some-provider-private-key"}',
                    b"x\0binary", b"\xff\xfe", b"x\x7fbinary"]
        for index, raw in enumerate(examples):
            name = f"proof{index}.txt"
            self.write(name, raw)
            found = self.build([name])
            self.assertEqual(found["files"], [])
            self.assertEqual(found["omitted"][0]["reason"], "secret_detected" if index < 4 else "not_utf8_text")

    def test_missing_directory_and_oversized_files_are_explicit(self):
        self.write("large.txt", b"a" * (context.MAX_FILE_BYTES + 1))
        (self.repo / "folder").mkdir()
        for name, expected in (("missing.txt", "unreadable_or_unsafe"), ("folder", "unreadable_or_unsafe"),
                               ("large.txt", "file_too_large")):
            with self.subTest(name=name):
                found = self.build([name])
                self.assertEqual(found["files"], [])
                self.assertEqual(found["omitted"][0]["reason"], expected)

    def test_symlink_or_linked_ancestor_is_refused(self):
        external = self.root / "external.txt"
        external.write_text("outside", encoding="utf-8")
        try:
            (self.repo / "link.txt").symlink_to(external)
            (self.repo / "linked").symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation not available")
        for name in ("link.txt", "linked/external.txt"):
            with self.subTest(name=name):
                self.assertEqual(self.build([name])["omitted"][0]["reason"], "unreadable_or_unsafe")

    def test_hardlink_is_refused(self):
        external = self.root / "external.txt"
        external.write_text("outside", encoding="utf-8")
        try:
            os.link(external, self.repo / "hard.txt")
        except OSError:
            self.skipTest("hardlink creation not available")
        self.assertEqual(self.build(["hard.txt"])["omitted"][0]["reason"], "unreadable_or_unsafe")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_fifo_is_never_opened(self):
        os.mkfifo(self.repo / "pipe")
        with mock.patch.object(context.FILES, "_read_regular", side_effect=AssertionError("opened FIFO")):
            self.assertEqual(self.build(["pipe"])["omitted"][0]["reason"], "unreadable_or_unsafe")

    def test_metadata_change_or_ancestor_swap_discards_the_read(self):
        path = self.write("proof.txt", b"before")
        reader = context.FILES._read_regular

        def changed(*args):
            result = reader(*args)
            path.write_bytes(b"changed during read")
            return result

        with mock.patch.object(context.FILES, "_read_regular", side_effect=changed):
            found = self.build(["proof.txt"])
        self.assertEqual(found["files"], [])
        self.assertEqual(found["omitted"][0]["reason"], "changed_during_read")

    def test_unreadable_or_network_drive_is_refused(self):
        self.write("proof.txt", b"normal")
        with mock.patch.object(context.readio, "local_volume", return_value=False):
            self.assertEqual(self.build(["proof.txt"])["omitted"][0]["reason"], "unreadable_or_unsafe")

    def test_context_total_includes_escaped_file_text_and_metadata(self):
        names = [f"proof{i}.txt" for i in range(12)]
        for name in names:
            self.write(name, b'"' * context.MAX_FILE_BYTES)
        found = self.build(names)
        encoded = json.dumps(found, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        self.assertLessEqual(len(encoded), context.MAX_CONTEXT_BYTES)
        self.assertTrue(found["files"])
        self.assertTrue(any(item["reason"] == "context_limit" for item in found["omitted"]))

    def test_large_or_recursive_board_is_bounded_and_marked_partial(self):
        recursive = {"self": None}
        recursive["self"] = recursive
        board = {**self.board, "sessions": [{"id": str(i), "description": "long" * 10_000} for i in range(10_000)],
                 "overview": recursive}
        found = self.build(board=board)
        self.assertTrue(found["limits"]["board_partial"])
        self.assertTrue(any(item["reason"] == "partial_snapshot" for item in found["omitted"]))
        self.assertLessEqual(len(context._json(found)), context.MAX_CONTEXT_BYTES)

    def test_board_embedded_credentials_do_not_enter_the_dossier(self):
        board = {**self.board, "main": {"state": "ok", "api_key": "sensitive"},
                 "waiting": ["sk-proj-" + "x" * 24]}
        found = self.build(board=board)
        self.assertNotIn("api_key", context._json(found).decode())
        self.assertNotIn("sk-proj-", context._json(found).decode())
        self.assertTrue(found["limits"]["board_partial"])


if __name__ == "__main__":
    unittest.main()
