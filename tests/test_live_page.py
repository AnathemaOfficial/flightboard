# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Execute the actual page refresh and task rendering code when Node is available; Python/Git remain sufficient."""
import shutil
import subprocess
import unittest

from tests.fixtures import PACKAGE, ROOT


class LivePageTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_overview_separates_declarations_and_prepares_safe_copyable_actions(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "overview_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("8 overview-page checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_publication_queue_refresh_preserves_uncertainty_and_safe_links(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "publication_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("5 publication-page checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_daily_chart_includes_new_tasks_and_starts(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "daily_chart_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("6 daily-chart checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "optional Node runtime for JavaScript regression checks")
    def test_refresh_and_open_task_use_current_data(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "live_page_checks.cjs"),
                                 str(PACKAGE / "template.html")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("15 live-page checks passed", result.stdout)
