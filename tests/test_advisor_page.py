# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Run consent and lifecycle checks against the actual optional adviser JavaScript."""
import shutil
import subprocess
import unittest

from tests.fixtures import PACKAGE, ROOT


class AdvisorPageTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_adviser_consent_and_jobs_are_independent_of_board_refresh(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/advisor_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("27 adviser-page checks passed", result.stdout)
