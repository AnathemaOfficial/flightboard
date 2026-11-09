# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Real Git coverage for explicit external worktrees, including Codex's group/project layout."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import GIT, NOW, load
from tests.test_modes import Plain, by_name

config = load("config")
collector = load("collector")
cli = load("cli")


class ExternalSettingsTest(unittest.TestCase):
    def test_a_mapped_network_drive_is_rejected_before_filesystem_lookup(self):
        root = Path(tempfile.gettempdir()).resolve() / "external"
        files = load("files")
        with mock.patch.object(load("readio"), "local_volume", return_value=False), \
                mock.patch.object(files, "no_link", side_effect=AssertionError("filesystem lookup")):
            self.assertFalse(files.local_root(root))

    def test_cache_cannot_write_under_external_root_even_without_a_readable_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            outside, external = root / "not-a-repository", root / "external"
            outside.mkdir()
            external.mkdir()
            cache = external / "cache"
            with mock.patch.object(cli, "cache_folder", return_value=cache), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = cli.main(["--snapshot", "--repo", str(outside), "--worktrees-root", str(external)])
            self.assertEqual(code, 2)
            self.assertFalse(cache.exists())

    def test_roots_are_explicit_local_absolute_paths_and_not_public(self):
        root = Path(tempfile.gettempdir()).resolve() / "agent worktrees"
        settings = cli.settings_of(cli.parse(["--worktrees-root", str(root), "--worktrees-root", str(root)]))
        self.assertEqual(settings.external_worktrees, (root,))
        self.assertEqual(settings.public()["external_worktree_roots"], 1)
        self.assertNotIn(str(root), json.dumps(settings.public()))
        for value in ("relative", "../outside", "//server/share", r"\\server\share", str(root / ".." / "x"), str(root / ".git")):
            with self.subTest(value=value):
                self.assertIsNone(cli.settings_of(cli.parse(["--worktrees-root", value])))


@unittest.skipIf(GIT is None, "git absent")
class ExternalWorktreeTest(unittest.TestCase):
    def setUp(self):
        self.repo = Plain()
        self.addCleanup(self.repo.close)
        tasks = {"tasks": [{"id": "APP-1", "status": "planned", "owner": "codex"},
                           {"id": "APP-2", "status": "planned", "owner": "qwen"}]}
        self.repo.commit(self.repo.root, "tasks.json", json.dumps(tasks), "docs: tasks for coding agents", "08:40")
        self.external = self.repo.root.parent / "external agent roots"
        self.tree = self.external / "group-1" / "project"
        self.repo.git("worktree", "add", "-q", "-b", "codex/app-1", str(self.tree), "main")
        self.settings = config.Settings(external_worktrees=(self.external,))

    def test_external_content_is_read_only_after_explicit_authorization(self):
        path = self.tree / "tasks.json"
        tasks = json.loads(path.read_text(encoding="utf-8"))
        tasks["tasks"][0]["status"] = "awaiting_review"
        path.write_text(json.dumps(tasks), encoding="utf-8")
        refused = by_name(collector.Collector(self.repo.root).snapshot(NOW))["project"]
        self.assertEqual((refused["reason"], refused["files_read"]), ("outside", False))
        found = collector.Collector(self.repo.root, self.settings).snapshot(NOW)
        card = by_name(found)["project"]
        self.assertEqual((card["files_read"], card["branch"], card["overlay"]), (True, "codex/app-1", True))
        self.assertEqual(found["tasks"]["APP-1"]["status"], "awaiting_review")
        self.assertIn("APP-2", [task["id"] for task in found["next"]])
        self.assertNotIn(str(self.external), json.dumps(found))

    def test_launch_from_authorized_external_tree_reads_its_main_checkout(self):
        self.assertEqual(collector.Collector(self.tree, self.settings).root, self.repo.root)

    def test_codex_sentinel_keeps_tracked_changes_visible_and_is_rechecked(self):
        self.repo.git("config", "extensions.worktreeConfig", "true")
        worktree_config = self.repo.root / ".git" / "worktrees" / "project" / "config.worktree"
        sentinel = b"[codex]\n\tlocalEnvironmentConfigPath = __none__\n"
        worktree_config.write_bytes(sentinel)
        (self.tree / "app.py").write_text("print(2)\n", encoding="utf-8", newline="\n")
        reader = collector.Collector(self.repo.root, self.settings)
        card = by_name(reader.snapshot(NOW))["project"]
        self.assertEqual((card["reason"], card["files_read"], card["modified"]), ("", True, 1))

        for dangerous in (b"[codex]\n\tlocalEnvironmentConfigPath = /local/environment.toml\n",
                          sentinel + b"[include]\n\tpath = //server/share/other.cfg\n",
                          sentinel + b"[core]\n\thooksPath = /local/hooks\n"):
            with self.subTest(config=dangerous):
                worktree_config.write_bytes(dangerous)
                refused = by_name(reader.snapshot(NOW))["project"]
                self.assertEqual((refused["reason"], refused["files_read"]), ("odd_admin", False))
                worktree_config.write_bytes(sentinel)
                restored = by_name(reader.snapshot(NOW))["project"]
                self.assertEqual((restored["reason"], restored["files_read"], restored["modified"]), ("", True, 1))

    def test_prefix_lookalike_is_not_an_authorized_root(self):
        wrong = config.Settings(external_worktrees=(self.external.with_name(self.external.name + "-other"),))
        card = by_name(collector.Collector(self.repo.root, wrong).snapshot(NOW))["project"]
        self.assertEqual((card["reason"], card["files_read"]), ("outside", False))

    def test_snapshot_never_writes_inside_an_authorized_external_root(self):
        output = self.tree / "board.html"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--snapshot", "--repo", str(self.repo.root), "--worktrees-root", str(self.external),
                             "--output", str(output)])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_link_in_external_path_is_not_followed(self):
        alias = self.repo.root.parent / "alias"
        try:
            os.symlink(self.external, alias, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create directory links")
        self.addCleanup(alias.unlink)
        settings = config.Settings(external_worktrees=(alias,))
        card = by_name(collector.Collector(self.repo.root, settings).snapshot(NOW))["project"]
        self.assertFalse(card["files_read"])


if __name__ == "__main__":
    unittest.main()
