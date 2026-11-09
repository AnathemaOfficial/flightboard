# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Execute the actual page refresh and task rendering code when Node is available; Python/Git remain sufficient."""
import shutil
import subprocess
import unittest

from tests.fixtures import PACKAGE, ROOT


class LivePageTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_refresh_and_open_task_use_current_data(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "live_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("9 live-page checks passed", result.stdout)
