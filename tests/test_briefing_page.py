# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Run the actual agent-briefing UI and refresh code without an optional browser dependency."""
import shutil
import subprocess
import unittest

from tests.fixtures import PACKAGE, ROOT


class BriefingPageTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_briefing_updates_and_copies_the_same_snapshot_without_extra_requests(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/briefing_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("12 briefing-page checks passed", result.stdout)
