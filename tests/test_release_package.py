# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Distribution archives are reproducible, commit-specific and contain no working-tree files."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from tests.fixtures import ROOT


def builder():
    spec = importlib.util.spec_from_file_location("release_builder", ROOT / "tools" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("git"), "git required for exact source archives")
class ReleasePackageTest(unittest.TestCase):
    def test_archive_paths_are_portable_and_cannot_create_git_metadata(self):
        module = builder()
        for name in ('docs/why?.md', 'docs/a*b.md', 'docs/a<b.md', 'docs/a>b.md',
                     'docs/a|b.md', 'docs/a"b.md', 'skills/flightboard/.GIT/config'):
            with self.subTest(name=name):
                self.assertFalse(module._safe_name(name))

    def test_casefold_file_directory_collisions_are_refused(self):
        module = builder()
        for names in (("skills/flightboard/A", "skills/flightboard/a/b"),
                      ("skills/flightboard/a/b", "skills/flightboard/A")):
            with self.subTest(names=names):
                listing = b"".join(b"100644 blob " + b"b" * 40 + b" 1\t" + name.encode() + b"\0"
                                   for name in names)
                with mock.patch.object(module, "_git", side_effect=[self.sha.encode() + b"\n", listing]):
                    with self.assertRaisesRegex(module.ReleaseError, "collision"):
                        module._source(self.repo, self.sha)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        files = {
            "plugin.json": json.dumps({"name": "flightboard", "version": "0.2.0"}) + "\n",
            ".claude-plugin/plugin.json": json.dumps({"name": "flightboard", "version": "0.2.0"}) + "\n",
            ".claude-plugin/marketplace.json": "{}\n",
            ".agents/plugins/marketplace.json": "{}\n",
            "skills/flightboard/SKILL.md": "---\nname: flightboard\nlicense: Apache-2.0\n---\nSkill\n",
            "skills/flightboard/scripts/flightboard.py": "print('fixture')\n",
            "skills/flightboard/scripts/flightboard/__init__.py": '__version__ = "0.2.0"\n',
            "skills/flightboard/agents/openai.yaml": "display_name: Flightboard\n",
            "README.md": "Install the skill.\n",
            "docs/install.md": "Installation instructions.\n",
            "LICENSE": "Fixture Apache license\n", "NOTICE": "Fixture attribution\n",
            "LICENSES/Apache-2.0.txt": "Fixture license\n",
            "tests/private-fixture.txt": "Test content is not shipped.\n",
            ".github/workflows/ci.yml": "name: fixture\n",
        }
        for name, value in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8", newline="\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.version = "0.2.0-rc.5.g" + self.sha[:12]

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run([shutil.which("git"), "-C", str(self.repo), "-c", "user.name=Test",
                                 "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
                                env=env, capture_output=True, check=True)
        return result.stdout.decode().strip()

    def test_packages_are_reproducible_and_exactly_from_the_committed_tree(self):
        mod = builder()
        (self.repo / "README.md").write_text("DIRTY CONTENT", encoding="utf-8")
        (self.repo / "skills/flightboard/secret.txt").write_text("UNTRACKED", encoding="utf-8")
        first = self.root / "first"
        second = self.root / "second"
        one = mod.build(self.repo, self.sha, self.version, first)
        two = mod.build(self.repo, self.sha, self.version, second)
        self.assertEqual(one, two)
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                         {p.name: p.read_bytes() for p in second.iterdir()})
        with zipfile.ZipFile(first / f"flightboard-plugin-{self.version}.zip") as archive:
            self.assertEqual(archive.read("README.md"), b"Install the skill.\n")
            self.assertNotIn("skills/flightboard/secret.txt", archive.namelist())
            self.assertFalse(any(name.startswith(("tests/", ".github/")) for name in archive.namelist()))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))

    def test_versions_provenance_licenses_and_hashes_are_coherent(self):
        output = self.root / "release"
        manifest = builder().build(self.repo, self.sha, self.version, output)
        self.assertEqual(manifest["source_sha"], self.sha)
        self.assertEqual(manifest["source_base_version"], "0.2.0")
        self.assertEqual(manifest["version"], self.version)
        self.assertEqual(len(manifest["assets"]), 2)
        for asset in manifest["assets"]:
            raw = (output / asset["name"]).read_bytes()
            self.assertEqual(asset["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(asset["size"], len(raw))
        with zipfile.ZipFile(output / f"flightboard-plugin-{self.version}.zip") as archive:
            for name in ("plugin.json", ".claude-plugin/plugin.json"):
                self.assertEqual(json.loads(archive.read(name))["version"], self.version)
            self.assertIn(self.version.encode(), archive.read("skills/flightboard/scripts/flightboard/__init__.py"))
        with zipfile.ZipFile(output / f"flightboard-skill-{self.version}.zip") as archive:
            for name in ("flightboard/SKILL.md", "flightboard/LICENSE", "flightboard/NOTICE",
                         "flightboard/LICENSES/Apache-2.0.txt", "flightboard/scripts/flightboard.py"):
                self.assertIn(name, archive.namelist())
        sums = (output / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(sums), 3)
        for line in sums:
            digest, filename = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((output / filename).read_bytes()).hexdigest())

    def test_output_within_a_repository_or_link_is_refused_without_writes(self):
        mod = builder()
        for output in (self.repo / "dist", self.repo / ".git" / "dist"):
            with self.subTest(output=output), self.assertRaises(mod.ReleaseError):
                mod.build(self.repo, self.sha, self.version, output)
            self.assertFalse(output.exists())
        link = self.root / "link"
        try:
            link.symlink_to(self.repo, target_is_directory=True)
        except OSError:
            return
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, self.sha, self.version, link / "dist")

    def test_unsafe_versions_short_refs_and_existing_output_are_refused(self):
        mod = builder()
        for version in ("../escape", "0.2.01", "0.2.0-01", "0.2", "v0.2.0"):
            with self.subTest(version=version), self.assertRaises(mod.ReleaseError):
                mod.build(self.repo, self.sha, version, self.root / "bad")
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, "main", self.version, self.root / "bad")
        output = self.root / "existing"
        output.mkdir()
        (output / "keep.txt").write_text("keep")
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, self.sha, self.version, output)
        self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_tracked_symlinks_and_case_collisions_are_refused(self):
        mod = builder()
        blob = self.git("rev-parse", "HEAD:README.md")
        self.git("update-index", "--add", "--cacheinfo", "120000", blob, "skills/flightboard/link")
        self.git("commit", "-qm", "link")
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, self.git("rev-parse", "HEAD"), self.version, self.root / "symlink")
        self.git("reset", "--hard", self.sha)
        self.git("update-index", "--add", "--cacheinfo", "100644", blob, "skills/flightboard/skill.md")
        self.git("commit", "-qm", "case collision")
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, self.git("rev-parse", "HEAD"), self.version, self.root / "collision")

    def test_inconsistent_source_versions_are_refused(self):
        mod = builder()
        path = self.repo / "plugin.json"
        value = json.loads(path.read_text())
        value["version"] = "0.1.0"
        path.write_text(json.dumps(value), encoding="utf-8")
        self.git("add", "plugin.json")
        self.git("commit", "-qm", "mismatch")
        with self.assertRaises(mod.ReleaseError):
            mod.build(self.repo, self.git("rev-parse", "HEAD"), self.version, self.root / "mismatch")

    def test_source_count_and_size_bounds_refuse_before_writing(self):
        mod = builder()
        for name, limit in (("MAX_FILES", 1), ("MAX_FILE_BYTES", 1), ("MAX_SOURCE_BYTES", 1)):
            output = self.root / name
            with self.subTest(bound=name), mock.patch.object(mod, name, limit):
                with self.assertRaises(mod.ReleaseError):
                    mod.build(self.repo, self.sha, self.version, output)
            self.assertFalse(output.exists())

    def test_unsafe_source_paths_cannot_reach_an_archive(self):
        mod = builder()
        for name in ("../escape", "skills/flightboard/trailing.", "skills/flightboard/CON.txt"):
            raw = ("100644 blob " + self.sha + "       1\t" + name + "\0").encode()
            with self.subTest(name=name), mock.patch.object(mod, "_git", side_effect=[self.sha.encode(), raw]):
                with self.assertRaises(mod.ReleaseError):
                    mod.build(self.repo, self.sha, self.version, self.root / "unsafe")
            self.assertFalse((self.root / "unsafe").exists())

    def test_git_timeout_terminates_the_actual_reader(self):
        mod = builder()
        real = subprocess.Popen
        children = []

        def start(command, **kwargs):
            child = real([sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"], **kwargs)
            children.append(child)
            return child

        with mock.patch.object(mod.subprocess, "Popen", side_effect=start), mock.patch.object(mod, "GIT_TIMEOUT", 0.05):
            with self.assertRaises(mod.ReleaseError):
                mod._git(self.repo, ["version"])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_windows_git_launchers_are_replaced_with_the_actual_executable(self):
        mod = builder()
        installation = self.root / "Git"
        direct = installation / "mingw64" / "bin" / "git.exe"
        direct.parent.mkdir(parents=True)
        direct.touch()
        for name in ("cmd", "bin"):
            launcher = installation / name / "git.exe"
            launcher.parent.mkdir(exist_ok=True)
            launcher.touch()
            with self.subTest(launcher=name), mock.patch.object(mod.shutil, "which", return_value=str(launcher)):
                self.assertEqual(mod._executable(windows=True), str(direct))
