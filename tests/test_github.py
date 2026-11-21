# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Hermetic GitHub observations: bounded reads never hold the local board's refresh."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tests.fixtures import load

github = load("github")
cli = load("cli")
config = load("config")
startup = load("windows_startup")
SHA = "a" * 40
OTHER = "b" * 40
IDENTITY = "Owner/project"


def encoded(value):
    return json.dumps(value).encode("utf-8")


class FixtureClient:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.branches = [{"name": "main", "commit": {"sha": SHA}}]
        self.pulls = []

    def get(self, endpoint, *, timeout, limit):
        self.calls.append((endpoint, timeout, limit))
        if self.failure:
            raise self.failure
        if "/branches?" in endpoint:
            return encoded(self.branches)
        if "/pulls?" in endpoint:
            return encoded(self.pulls)
        identity = endpoint.removeprefix("repos/")
        return encoded({"id": 123, "full_name": identity, "default_branch": "main"})


class GitHubTest(unittest.TestCase):
    def observer(self, client=None, clock=None, **kwargs):
        value = github.GitHubObserver(client=client or FixtureClient(), clock=clock or time.monotonic,
                                      now=lambda: datetime(2026, 11, 21, tzinfo=timezone.utc), **kwargs)
        self.addCleanup(value.close)
        return value

    def completed(self, observer, identity=IDENTITY):
        until = time.monotonic() + 3
        while time.monotonic() < until:
            value = observer.current(identity)
            if value["state"] not in ("pending", "stale"):
                return value
            threading.Event().wait(0.005)
        self.fail("observer did not finish its hermetic request")

    def test_strict_repository_identity(self):
        for value in ("https://github.com/Owner/project.git", "https://github.com/Owner/project",
                      "git@github.com:Owner/project.git", "ssh://git@github.com/Owner/project.git"):
            with self.subTest(value=value):
                self.assertEqual(github.repository_identity(value), IDENTITY)
        for value in (None, "", "https://github.com/Owner/project/", "http://github.com/Owner/project",
                      "https://token@github.com/Owner/project", "https://github.com.evil.test/Owner/project",
                      "https://github.com:443/Owner/project", "https://github.com/Owner/../project",
                      "https://github.com/Owner/project?token=secret", "https://github.com/Owner/project#x",
                      "https://github.com/Owner/project%2Fother", "ext::anything", "../Owner/project",
                      "ssh://bob@github.com/Owner/project", "git@github.com:Owner/project\n",
                      "git@github.com:Owner/project.git/", "https://github.com/Owner/.git"):
            with self.subTest(value=value):
                self.assertEqual(github.repository_identity(value), "")

    def test_disabled_and_invalid_identity_never_call_client(self):
        client = FixtureClient()
        observer = self.observer(client, enabled=False)
        self.assertEqual(observer.current(IDENTITY)["state"], "disabled")
        self.assertEqual(client.calls, [])
        observer = self.observer(client)
        self.assertEqual(observer.current("../../escape")["state"], "error")
        self.assertEqual(client.calls, [])

    def test_nonblocking_single_chain_and_defensive_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        client = FixtureClient()
        original = client.get

        def blocked(*args, **kwargs):
            entered.set()
            release.wait(2)
            return original(*args, **kwargs)

        client.get = blocked
        observer = self.observer(client)
        self.addCleanup(release.set)
        self.assertEqual(observer.current(IDENTITY)["state"], "pending")
        self.assertTrue(entered.wait(1))
        for _ in range(30):
            self.assertEqual(observer.current(IDENTITY)["state"], "pending")
        release.set()
        value = self.completed(observer)
        self.assertEqual(value["heads"], {"main": SHA})
        self.assertTrue(value["complete"])
        self.assertEqual(len(client.calls), 3)
        value["heads"].clear()
        self.assertEqual(observer.current(IDENTITY)["heads"], {"main": SHA})

    def test_ttl_expiration_and_failed_refresh_retain_stale_evidence(self):
        clock = [10.0]
        client = FixtureClient()
        observer = self.observer(client, clock=lambda: clock[0])
        initial = self.completed(observer)
        clock[0] = 309.0
        self.assertEqual(observer.current(IDENTITY)["state"], "fresh")
        self.assertEqual(len(client.calls), 3)
        client.failure = OSError("secret must not be exposed")
        clock[0] = 311.0
        value = observer.current(IDENTITY)
        self.assertEqual(value["state"], "stale")
        until = time.monotonic() + 2
        while not observer.current(IDENTITY)["error"] and time.monotonic() < until:
            threading.Event().wait(0.005)
        value = observer.current(IDENTITY)
        self.assertEqual(value["state"], "stale")
        self.assertEqual(value["heads"], {"main": SHA})
        self.assertEqual(value["last_success_at"], initial["last_success_at"])
        self.assertNotIn("secret", value["error"])
        self.assertEqual(len(client.calls), 4)
        observer.current(IDENTITY)
        self.assertEqual(len(client.calls), 4)

    def test_old_identity_result_cannot_replace_new_repository(self):
        entered, release = threading.Event(), threading.Event()
        client = FixtureClient()
        original = client.get

        def blocked(endpoint, **kwargs):
            if endpoint == "repos/Owner/project":
                entered.set()
                release.wait(2)
            return original(endpoint, **kwargs)

        client.get = blocked
        observer = self.observer(client)
        self.addCleanup(release.set)
        observer.current(IDENTITY)
        self.assertTrue(entered.wait(1))
        self.assertEqual(observer.current("Owner/other")["repository"], "Owner/other")
        release.set()
        value = self.completed(observer, "Owner/other")
        self.assertEqual(value["repository"], "Owner/other")
        self.assertEqual(value["state"], "fresh")

    def test_head_pagination_is_explicit_and_bounded(self):
        client = FixtureClient()
        original = client.get

        def paginated(endpoint, **kwargs):
            if "/branches?" in endpoint:
                client.calls.append((endpoint, kwargs["timeout"], kwargs["limit"]))
                page = int(endpoint.rsplit("=", 1)[-1])
                return encoded([{"name": f"branch-{page}-{i}", "commit": {"sha": SHA}} for i in range(100)])
            return original(endpoint, **kwargs)

        client.get = paginated
        observer = self.observer(client)
        value = self.completed(observer)
        self.assertEqual(value["state"], "partial")
        self.assertFalse(value["complete"])
        branches = [call[0] for call in client.calls if "/branches?" in call[0]]
        self.assertEqual(len(branches), github.MAX_PAGES)
        self.assertTrue(all("per_page=100&page=" in endpoint for endpoint in branches))

    def test_invalid_data_and_repository_mismatch_are_errors(self):
        for payload in (b"not JSON", encoded({"full_name": "Other/project", "id": 1}),
                        encoded({"full_name": IDENTITY, "id": True})):
            with self.subTest(payload=payload):
                client = FixtureClient()
                client.get = lambda *args, **kwargs: payload
                value = self.completed(self.observer(client))
                self.assertEqual(value["state"], "error")
                self.assertEqual(value["heads"], {})
                self.assertFalse(value["complete"])

    def test_output_and_whole_chain_deadlines_are_enforced(self):
        client = FixtureClient()
        client.get = lambda *args, **kwargs: b" " * (github.MAX_RESPONSE_BYTES + 1)
        self.assertEqual(self.completed(self.observer(client))["state"], "error")
        clock = [0.0]
        client = FixtureClient()
        original = client.get

        def elapsed(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] += github.CHAIN_TIMEOUT + 1
            return result

        client.get = elapsed
        value = self.completed(self.observer(client, clock=lambda: clock[0]))
        self.assertEqual(value["state"], "error")
        self.assertEqual(len(client.calls), 1)

    def test_pull_requests_are_reduced_to_validated_public_fields(self):
        client = FixtureClient()
        client.pulls = [{"number": 7, "title": "Review\x00 title", "state": "open",
                         "html_url": "https://github.com/Owner/project/pull/7", "body": "private body",
                         "head": {"ref": "topic", "sha": OTHER},
                         "base": {"ref": "main", "repo": {"full_name": IDENTITY}}}]
        value = self.completed(self.observer(client))
        pull = value["pull_requests"][0]
        self.assertEqual(pull["number"], 7)
        self.assertEqual(pull["head_sha"], OTHER)
        self.assertNotIn("body", pull)
        self.assertNotIn("\x00", pull["title"])
        client.pulls[0]["html_url"] = "https://evil.test/steal"
        value = self.completed(self.observer(client))
        self.assertEqual(value["state"], "error")

    def test_gh_process_uses_fixed_get_host_trusted_cwd_and_bounded_runner(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / ("gh.exe" if os.name == "nt" else "gh")
            executable.touch()

            def runner(command, **kwargs):
                calls.append((command, kwargs))
                return 0, b"[]", b"", False

            client = github.GhClient(runner=runner, executable=str(executable))
            with mock.patch.dict(os.environ, {"GH_DEBUG": "api", "GH_HOST": "evil.test", "PAGER": "danger"}):
                self.assertEqual(client.get("repos/Owner/project/branches?per_page=100&page=1",
                                            timeout=2.5, limit=100), b"[]")
            command, options = calls[0]
            self.assertEqual(command[1:6], ["api", "--hostname", "github.com", "--method", "GET"])
            self.assertEqual(options["cwd"], str(executable.parent))
            self.assertEqual(options["timeout"], 2.5)
            self.assertEqual(options["limit"], 100)
            self.assertNotIn("GH_DEBUG", options["env"])
            self.assertEqual(options["env"]["GH_HOST"], "github.com")
            self.assertEqual(options["env"]["GH_PROMPT_DISABLED"], "1")
            self.assertNotIn("shell", options)
            for result in ((None, b"", b"secret", False), (0, b"[]", b"", True), (1, b"", b"secret", False)):
                client = github.GhClient(runner=lambda *args, **kwargs: result, executable=str(executable))
                with self.assertRaises(github.ObservationError):
                    client.get("repos/Owner/project", timeout=1, limit=100)

    def test_github_option_is_explicit_boolean_and_startup_round_trips(self):
        self.assertFalse(config.Settings().github)
        self.assertTrue(cli.settings_of(cli.parse(["--github"])).github)
        self.assertIsNone(cli.parse(["--github", "--github"]))
        self.assertFalse(config.valid(config.Settings(github="yes")))
        with tempfile.TemporaryDirectory() as directory:
            arguments = ["--repo", str(Path(directory).resolve()), "--port", "8792", "--github"]
            self.assertIn("--github", startup.live_options(arguments))
            self.assertNotIn("--github", startup.live_options(arguments[:-1]))


if __name__ == "__main__":
    unittest.main()
