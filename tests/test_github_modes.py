# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Opt-in GitHub applies only to live mode and costs nothing while disabled."""
import contextlib
import io
from pathlib import Path
import unittest
from unittest import mock

from tests.fixtures import load

cli = load("cli")
config = load("config")


class GitHubModesTest(unittest.TestCase):
    def test_one_shot_modes_reject_github_instead_of_silently_ignoring_it(self):
        for mode in ("--snapshot", "--resume"):
            with self.subTest(mode=mode):
                options, error = cli.read_args([mode, "--github"])
                self.assertIsNone(options)
                self.assertIn("live", error)
        self.assertIsNotNone(cli.parse(["--github", "--port", "8792"]))

    def test_disabled_live_mode_never_constructs_an_observer(self):
        server = mock.Mock()
        with mock.patch.object(cli.GITHUB, "GitHubObserver") as observer, \
                mock.patch.object(cli, "Collector") as collector, \
                mock.patch.object(cli.SERVER, "Snapshots"), \
                mock.patch.object(cli.SERVER, "make_servers", return_value=[server]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._serve(Path.cwd(), config.Settings(), 8792), 0)
        observer.assert_not_called()
        self.assertIsNone(collector.call_args.kwargs["github"])
        server.server_close.assert_called_once()
