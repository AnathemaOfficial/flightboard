# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Tests for the repository itself: licence headers, no secret and no machine path in any file, and a plugin layout
Claude Code, claude.ai and Cowork accept.

Run from the repository root:
    python -I -B -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.fixtures import ROOT, load

rules = load("ledgers.roadmap_rules")
HEADER = ("SPDX-License-Identifier: Apache-2.0", "SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.")
SKIP = {".git", "__pycache__"}
MACHINE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![\w.])/(?:Users|home)/[A-Za-z]")
RESERVED_NAME = re.compile(r"(?i)\b(?:claude|anthropic)\b|^cc-")
# the embeddings, overrides and isolates of bidirectional text, which can show code other than what runs
BIDI = frozenset(map(chr, (*range(0x202A, 0x202F), *range(0x2066, 0x206A))))


def files() -> list[Path]:
    """Every text file of the repository (an image, say, is no text and carries its licence in REUSE.toml)."""
    found = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not SKIP.intersection(path.relative_to(ROOT).parts):
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found.append(path)
    return found


def annotated() -> set[str]:
    text = (ROOT / "REUSE.toml").read_text(encoding="utf-8")
    return set(re.findall(r'"([^"]+)"', text.split("path = ", 1)[1].split("]", 1)[0]))


class HygieneTest(unittest.TestCase):
    def test_every_file_says_its_licence(self) -> None:
        exempt = annotated() | {"LICENSE", "LICENSES/Apache-2.0.txt"}
        for path in files():
            relative = path.relative_to(ROOT).as_posix()
            if relative in exempt:
                continue
            with self.subTest(path=relative):
                head = path.read_text(encoding="utf-8")[:400]
                for line in HEADER:
                    self.assertIn(line, head)

    def test_no_secret_and_no_machine_path(self) -> None:
        for path in files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIsNone(rules.SECRET.search(text))
                self.assertIsNone(rules.PRIVATE_HOST.search(text))
                self.assertIsNone(MACHINE.search(text))

    def test_the_plugin_layout(self) -> None:
        self.assertFalse((ROOT / "bin").exists(), "claude.ai and Cowork refuse a plugin with a bin/ folder")
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        portable = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        codex_market = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["name"], manifest["license"], manifest["version"]),
                         ("flightboard", "Apache-2.0", load().__version__))
        self.assertEqual({key: portable[key] for key in ("name", "license", "version")},
                         {key: manifest[key] for key in ("name", "license", "version")})
        self.assertTrue(portable["extensions"]["com.openai"]["requires_local_executor"])
        self.assertEqual(portable["extensions"]["com.openai"]["interface"]["capabilities"], ["Read"])
        self.assertEqual(codex_market["name"], market["name"])
        self.assertEqual([(entry["name"], entry["source"]) for entry in codex_market["plugins"]],
                         [("flightboard", {"source": "local", "path": "./"})])
        self.assertEqual([(entry["name"], entry["source"]) for entry in market["plugins"]], [("flightboard", "./")])
        skill = (ROOT / "skills" / "flightboard" / "SKILL.md").read_text(encoding="utf-8")
        front = skill.split("---", 2)[1]
        names = [market["name"], manifest["name"], re.search(r"^name: (.+)$", front, re.M).group(1)]
        self.assertFalse([name for name in names if RESERVED_NAME.search(name)])
        self.assertRegex(front, r"(?m)^description: .{80,}$")
        self.assertIn('"${CLAUDE_SKILL_DIR}/scripts/flightboard.py"', skill)
        self.assertTrue((ROOT / "skills" / "flightboard" / "scripts" / "flightboard.py").is_file())
        self.assertLess(len(skill.splitlines()), 500)

    def test_no_bidirectional_control_character(self) -> None:
        """A test that needs one writes it as an escape, so every file reads as it runs."""
        for path in files():
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertFalse(BIDI.intersection(path.read_text(encoding="utf-8")))

    def test_every_line_ending_is_plain(self) -> None:
        for path in files():
            if path.suffix in (".py", ".html", ".md", ".json", ".toml", ".yml"):
                with self.subTest(path=path.relative_to(ROOT).as_posix()):
                    self.assertNotIn(b"\r", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
