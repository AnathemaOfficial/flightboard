# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Windows startup remembers only explicitly launched, local Flightboard servers.

The process/discovery cases run on every platform; real Windows helpers use temporary paths.
"""
from __future__ import annotations

import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.fixtures import ENTRY, load

startup = load("windows_startup")


class StartupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.paths = startup.Paths(self.root / "appdata", ENTRY.parent, self.root / "Startup" / "Flightboard.lnk")
        self.paths.root.mkdir()
        self.paths.engine.parent.mkdir(parents=True)
        self.paths.engine.write_text("# fixture\n", encoding="utf-8")
        self.python = self.root / "python.exe"
        self.pythonw = self.root / "pythonw.exe"
        self.python.touch()
        self.pythonw.touch()
        self.repo = self.root / "project one"
        self.repo.mkdir()
        self.other = self.root / "project two"
        self.other.mkdir()
        self.settings = {
            "version": 1, "interval_seconds": 60, "python": str(self.python), "pythonw": str(self.pythonw),
            "trusted_engines": [str(self.paths.engine), str(ENTRY)], "trusted_python": [str(self.python)],
            "discover_running_boards": True, "excluded_repos": [], "boards": [],
        }
        self.words: dict[str, list[str]] = {}
        split = mock.patch.object(startup, "command_words", side_effect=lambda text: self.words[text])
        split.start()
        self.addCleanup(split.stop)

    def process(self, repo: Path | str | None = None, port: int = 8791, pid: int = 101,
                extra: list[str] | None = None, python: Path | None = None, engine: Path | None = None,
                switches: list[str] | None = None) -> tuple[dict, list[dict]]:
        arguments = [str(python or self.python), *(switches if switches is not None else ["-I", "-B"]),
                     str(engine or ENTRY)]
        if repo is not None:
            arguments.extend(["--repo", str(repo)])
        arguments.extend(["--port", str(port), *(extra or [])])
        text = subprocess.list2cmdline(arguments)
        self.words[text] = arguments
        process = {"ProcessId": pid, "ExecutablePath": str(python or self.python), "CommandLine": text,
                   "CreationDate": "2026-11-09T12:00:00Z"}
        listeners = [{"LocalPort": port, "LocalAddress": address, "OwningProcess": pid}
                     for address in ("127.0.0.1", "::1")]
        return process, listeners

    def discover(self, process: dict, listeners: list[dict]) -> bool:
        return startup.discover(self.settings, {"processes": [process], "listeners": listeners}, self.paths)

    def remember(self, **options) -> dict:
        process, listeners = self.process(self.repo, **options)
        self.assertTrue(self.discover(process, listeners))
        return self.settings["boards"][0]

    def test_two_repositories_are_remembered_with_their_authorized_options(self) -> None:
        external = self.root / "authorized worktrees"
        external.mkdir()
        one, listeners = self.process(self.repo, extra=["--lang", "fr", "--read-seconds", "30",
                                                       "--worktrees-root", str(external), "--max-branches", "0"])
        two, others = self.process(self.other, port=8792, pid=102)
        current = {"processes": [one, two], "listeners": [*listeners, *others]}
        self.assertTrue(startup.discover(self.settings, current, self.paths))
        saved = json.loads(self.paths.config.read_text(encoding="utf-8"))
        self.assertEqual({board["repo"] for board in saved["boards"]}, {str(self.repo), str(self.other)})
        command = saved["boards"][0]["command"]
        self.assertEqual(command[:4], [str(self.python), "-I", "-B", str(self.paths.engine)])
        self.assertIn(str(external), command)
        self.assertEqual(command[command.index("--read-seconds") + 1], "30")
        self.assertFalse(list(self.paths.root.glob("*.tmp")))

    def test_repeat_discovery_does_not_duplicate_a_repository(self) -> None:
        process, listeners = self.process(self.repo)
        self.assertTrue(self.discover(process, listeners))
        self.assertFalse(self.discover(process, listeners))
        other_port, other_listeners = self.process(self.repo, port=8792, pid=102)
        self.assertFalse(self.discover(other_port, other_listeners))
        self.assertEqual(len(self.settings["boards"]), 1)

    def test_unknown_runtime_or_engine_is_not_remembered(self) -> None:
        foreign_python = self.root / "untrusted-python.exe"
        foreign_python.touch()
        foreign_engine = self.root / "untrusted" / "flightboard.py"
        foreign_engine.parent.mkdir()
        foreign_engine.touch()
        for change in ({"python": foreign_python}, {"engine": foreign_engine}):
            with self.subTest(change=change):
                process, listeners = self.process(self.repo, **change)
                self.assertFalse(self.discover(process, listeners))
                self.assertEqual(self.settings["boards"], [])

    def test_isolation_switches_are_required(self) -> None:
        for switches in ([], ["-I"], ["-B"], ["-u"]):
            with self.subTest(switches=switches):
                process, listeners = self.process(self.repo, switches=switches)
                self.assertFalse(self.discover(process, listeners))

    def test_an_optional_unbuffered_switch_is_accepted(self) -> None:
        process, listeners = self.process(self.repo, switches=["-I", "-B", "-u"])
        self.assertTrue(self.discover(process, listeners))

    def test_a_repository_must_be_explicit_absolute_and_existing(self) -> None:
        for repo in (None, "relative-project", self.root / "missing-project"):
            with self.subTest(repo=repo):
                process, listeners = self.process(repo)
                self.assertFalse(self.discover(process, listeners))

    def test_text_and_snapshot_modes_are_never_remembered(self) -> None:
        for flag in ("--snapshot", "--resume", "--help", "-h", "--version"):
            with self.subTest(flag=flag):
                process, listeners = self.process(self.repo, extra=[flag])
                self.assertFalse(self.discover(process, listeners))

    def test_invalid_cli_options_are_not_persisted(self) -> None:
        for extra in (["--unknown", "x"], ["--read-seconds", "121"], ["--lang", "invalid"],
                      ["--worktrees", "../escape"]):
            with self.subTest(extra=extra):
                process, listeners = self.process(self.repo, extra=extra)
                self.assertFalse(self.discover(process, listeners))

    def test_listeners_must_belong_to_the_process_and_remain_loopback(self) -> None:
        process, listeners = self.process(self.repo)
        cases = [[], [{**listeners[0], "OwningProcess": 999}],
                 [{**listeners[0], "LocalAddress": "0.0.0.0"}],
                 [{**listeners[0], "LocalAddress": "::"}],
                 [listeners[0], {**listeners[1], "OwningProcess": 999}],
                 [{**listeners[0], "LocalPort": 8792}]]
        for candidate in cases:
            with self.subTest(listeners=candidate):
                self.assertFalse(self.discover(process, candidate))
                self.assertEqual(self.settings["boards"], [])

    def test_discovery_can_be_disabled_without_changing_running_boards(self) -> None:
        self.settings["discover_running_boards"] = False
        process, listeners = self.process(self.repo)
        self.assertFalse(self.discover(process, listeners))
        self.assertEqual(self.settings["boards"], [])

    def test_forgetting_a_repository_prevents_its_running_server_being_added_again(self) -> None:
        process, listeners = self.process(self.repo)
        self.assertTrue(self.discover(process, listeners))
        startup.forget(self.settings, str(self.repo), self.paths)
        self.assertEqual(self.settings["boards"], [])
        self.assertFalse(self.discover(process, listeners))
        self.assertIn(os.path.normcase(str(self.repo)),
                      [os.path.normcase(path) for path in self.settings["excluded_repos"]])

    def test_an_adopted_runtime_can_differ_from_the_stable_runtime(self) -> None:
        alternate = self.root / "alternate-python.exe"
        alternate.touch()
        self.settings["trusted_python"].append(str(alternate))
        process, listeners = self.process(self.repo, python=alternate)
        self.assertTrue(self.discover(process, listeners))
        board = self.settings["boards"][0]
        self.assertTrue(startup.matches(process, board))
        self.assertEqual(board["command"][0], str(self.python))
        changed = {**process, "ExecutablePath": str(self.python)}
        self.assertFalse(startup.matches(changed, board))

    def test_existing_servers_are_reused_without_launches_or_repository_reads(self) -> None:
        process, listeners = self.process(self.repo)
        self.assertTrue(self.discover(process, listeners))
        with mock.patch.object(startup, "launch") as launch, mock.patch.object(startup, "inventory") as inventory, \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("unexpected subprocess")), \
                mock.patch("socket.create_connection", side_effect=AssertionError("unexpected HTTP probe")):
            states = startup.cycle(self.settings, self.paths, {"processes": [process], "listeners": listeners})
        self.assertEqual(states[0]["state"], "listening")
        launch.assert_not_called()
        inventory.assert_not_called()

    def test_a_foreign_port_owner_is_preserved(self) -> None:
        self.remember()
        listeners = [{"LocalPort": 8791, "LocalAddress": "127.0.0.1", "OwningProcess": 999}]
        with mock.patch.object(startup, "launch") as launch, \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("unexpected process operation")):
            states = startup.cycle(self.settings, self.paths, {"processes": [], "listeners": listeners})
        self.assertEqual(states[0]["state"], "port_conflict")
        launch.assert_not_called()

    def test_an_existing_process_without_a_listener_is_not_duplicated(self) -> None:
        process, listeners = self.process(self.repo)
        self.assertTrue(self.discover(process, listeners))
        with mock.patch.object(startup, "launch") as launch:
            states = startup.cycle(self.settings, self.paths, {"processes": [process], "listeners": []})
        self.assertEqual(states[0]["state"], "process_without_listener")
        launch.assert_not_called()

    def test_a_missing_server_is_launched_only_for_its_registered_board(self) -> None:
        board = self.remember()
        replacement = {"name": board["name"], "state": "starting", "pid": 202, "port": 8791}
        with mock.patch.object(startup, "launch", return_value=replacement) as launch:
            states = startup.cycle(self.settings, self.paths, {"processes": [], "listeners": []})
        self.assertEqual(states, [replacement])
        self.assertEqual(launch.call_count, 1)
        self.assertEqual(launch.call_args.args[0], board)

    def test_valid_configuration_round_trips_without_machine_defaults(self) -> None:
        self.remember()
        startup.save_config(self.settings, self.paths)
        self.assertEqual(startup.load_config(self.paths), self.settings)

    def test_malformed_configuration_is_rejected_explicitly(self) -> None:
        changes = [{"version": 0}, {"interval_seconds": True}, {"interval_seconds": 0},
                   {"interval_seconds": 301}, {"boards": {}}, {"trusted_python": "python.exe"},
                   {"python": "relative-python.exe"}, {"discover_running_boards": "yes"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                startup.validate_config({**copy.deepcopy(self.settings), **change})

    def test_duplicate_ports_in_saved_configuration_are_rejected(self) -> None:
        board = self.remember()
        self.settings["boards"].append({**copy.deepcopy(board), "repo": str(self.other), "name": self.other.name})
        with self.assertRaises(ValueError):
            startup.validate_config(self.settings)

    def test_saved_commands_cannot_escape_the_trusted_live_engine(self) -> None:
        self.remember()
        for location, replacement in ((0, str(self.root / "other.exe")), (1, "-c"),
                                      (3, str(self.root / "untrusted.py")), (5, str(self.other)), (7, "8792")):
            changed = copy.deepcopy(self.settings)
            changed["boards"][0]["command"][location] = replacement
            with self.subTest(location=location), self.assertRaises(ValueError):
                startup.validate_config(changed)

    def test_failed_atomic_replace_leaves_the_previous_configuration_intact(self) -> None:
        self.remember()
        before = self.paths.config.read_bytes()
        self.settings["interval_seconds"] = 30
        with mock.patch.object(startup.os, "replace", side_effect=OSError("disk unavailable")), \
                self.assertRaises(OSError):
            startup.save_config(self.settings, self.paths)
        self.assertEqual(self.paths.config.read_bytes(), before)
        self.assertFalse(list(self.paths.root.glob("*.tmp")))

    def test_a_temporarily_missing_repository_is_retained_and_retried_later(self) -> None:
        board = self.remember()
        self.repo.rmdir()
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected launch")):
            states = startup.cycle(self.settings, self.paths, {"processes": [], "listeners": []})
        self.assertEqual(states[0]["state"], "waiting_for_path")
        self.assertEqual(states[0]["path"], str(self.repo))
        self.assertEqual(self.settings["boards"], [board])

    def test_once_child_can_write_after_its_supervisor_process_has_exited(self) -> None:
        gate, receipt = self.root / "caller-has-exited", self.root / "child-survived"
        child = self.root / "delayed-child.py"
        child.write_text(
            "from pathlib import Path\nimport time\n"
            f"gate = Path({str(gate)!r})\nreceipt = Path({str(receipt)!r})\n"
            "limit = time.monotonic() + 5\n"
            "while not gate.exists() and time.monotonic() < limit:\n    time.sleep(0.02)\n"
            "if gate.exists():\n    print('SERVING after caller exit', flush=True)\n"
            "    receipt.write_text('survived', encoding='utf-8')\n", encoding="utf-8")
        settings = copy.deepcopy(self.settings)
        settings["python"] = sys.executable
        settings["trusted_python"].append(sys.executable)
        settings["trusted_engines"].append(str(child))
        settings["boards"] = [{"name": "delayed child", "repo": str(self.repo), "port": 8791,
                               "command": [sys.executable, "-I", "-B", str(child), "--repo", str(self.repo),
                                           "--port", "8791"]}]
        startup.save_config(settings, self.paths)
        code = (
            "import contextlib, importlib, runpy\nfrom pathlib import Path\n"
            f"runpy.run_path({str(ENTRY)!r})['load']()\n"
            "m = importlib.import_module('flightboard.windows_startup')\n"
            "m.singleton = lambda paths: contextlib.nullcontext(True)\n"
            "m.inventory = lambda: {'processes': [], 'listeners': []}\n"
            f"paths = m.Paths(Path({str(self.paths.root)!r}), Path({str(ENTRY.parent)!r}), "
            f"Path({str(self.paths.startup_link)!r}))\n"
            "assert m.run(paths, once=True)['status'] == 'running'\n"
        )
        caller = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True,
                                timeout=10, creationflags=startup.NO_WINDOW)
        self.assertEqual(caller.returncode, 0, caller.stderr.decode("utf-8", errors="replace"))
        gate.touch()  # the child cannot print until its caller and pipe readers have exited
        deadline = time.monotonic() + 6
        while not receipt.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(receipt.is_file(), "once left the child with a pipe whose reader exited")
        self.assertEqual(receipt.read_text(encoding="utf-8"), "survived")

    def test_disabled_run_does_not_inspect_or_restart_anything(self) -> None:
        self.paths.disabled.touch()
        with mock.patch.object(startup, "inventory") as inventory, mock.patch.object(startup, "launch") as launch:
            self.assertEqual(startup.run(self.paths, once=True), {"status": "disabled"})
        inventory.assert_not_called()
        launch.assert_not_called()

    def test_disable_removes_only_its_shortcut_and_leaves_servers_alone(self) -> None:
        self.paths.startup_link.parent.mkdir()
        self.paths.startup_link.touch()
        unrelated = self.paths.startup_link.parent / "Another application.lnk"
        unrelated.touch()
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("unexpected process operation")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("unexpected launch")):
            startup.disable(self.paths)
        self.assertTrue(self.paths.disabled.exists())
        self.assertFalse(self.paths.startup_link.exists())
        self.assertTrue(unrelated.exists())

    def test_shortcut_data_is_passed_as_json_instead_of_executable_code(self) -> None:
        hostile = self.root / "owner $name 'quoted'" / "Startup" / "Flightboard.lnk"
        paths = startup.Paths(self.paths.root, self.paths.source_scripts, hostile)
        with mock.patch.object(startup, "powershell") as powershell:
            startup._shortcut(paths, self.settings)
        script = powershell.call_args.args[0]
        data = json.loads(powershell.call_args.kwargs["env"]["FLIGHTBOARD_SHORTCUT_DATA"])
        self.assertNotIn(str(hostile), script)
        self.assertEqual(data["link"], str(hostile))
        self.assertEqual(data["target"], str(self.pythonw))
        self.assertIn(str(paths.helper), data["arguments"])

    @unittest.skipUnless(os.name == "nt", "Windows file locks")
    def test_windows_singleton_rejects_a_second_supervisor_and_releases_its_lock(self) -> None:
        with startup.singleton(self.paths) as first:
            self.assertTrue(first)
            with startup.singleton(self.paths) as second:
                self.assertFalse(second)
        with startup.singleton(self.paths) as after_exit:
            self.assertTrue(after_exit)

    @unittest.skipUnless(os.name == "nt", "Windows shortcuts")
    def test_native_shortcut_preserves_spaces_and_shell_metacharacters_in_paths(self) -> None:
        shortcut_path = self.root / "owner $name 'quoted'" / "Startup" / "Flightboard.lnk"
        shortcut_path.parent.mkdir(parents=True)
        paths = startup.Paths(self.paths.root, self.paths.source_scripts, shortcut_path)
        startup._shortcut(paths, self.settings)
        environment = dict(os.environ)
        environment["FLIGHTBOARD_TEST_SHORTCUT"] = str(shortcut_path)
        result = startup.powershell(
            "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
            "$s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut($env:FLIGHTBOARD_TEST_SHORTCUT); "
            "@{target=$l.TargetPath; arguments=$l.Arguments; cwd=$l.WorkingDirectory; window=$l.WindowStyle} "
            "| ConvertTo-Json -Compress", env=environment)
        saved = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(os.path.normcase(saved["target"]), os.path.normcase(str(self.pythonw)))
        self.assertEqual(saved["arguments"], subprocess.list2cmdline(["-I", "-B", str(paths.helper), "run"]))
        self.assertEqual(os.path.normcase(saved["cwd"]), os.path.normcase(str(paths.root)))
        self.assertEqual(saved["window"], 7)

    @unittest.skipUnless(os.name == "nt", "Windows startup install uses a native singleton")
    def test_install_copies_a_stable_engine_and_preserves_multiple_repositories(self) -> None:
        one, listeners = self.process(self.repo)
        two, others = self.process(self.other, port=8792, pid=102)
        self.assertTrue(startup.discover(self.settings, {"processes": [one, two], "listeners": [*listeners, *others]},
                                         self.paths))
        with mock.patch.object(startup.sys, "executable", str(self.python)), \
                mock.patch.object(startup, "enable") as enable:
            installed = startup.install(self.paths)
        enable.assert_called_once_with(self.paths)
        self.assertTrue(self.paths.engine.is_file())
        self.assertTrue(self.paths.helper.is_file())
        self.assertTrue((self.paths.engine.parent / "flightboard" / "cli.py").is_file())
        self.assertFalse(list(self.paths.engine.parent.rglob("__pycache__")))
        self.assertEqual({board["repo"] for board in installed["boards"]}, {str(self.repo), str(self.other)})
        self.assertIn(str(ENTRY.resolve()), installed["trusted_engines"])
        self.assertIn(str(self.paths.engine.resolve()), installed["trusted_engines"])

    @unittest.skipUnless(os.name == "nt", "Windows startup install uses a native singleton")
    def test_reinstall_can_move_registered_dashboards_to_a_new_python_installation(self) -> None:
        self.remember()
        replacement = self.root / "replacement runtime" / "python.exe"
        replacement.parent.mkdir()
        replacement.touch()
        replacement.with_name("pythonw.exe").touch()
        with mock.patch.object(startup.sys, "executable", str(replacement)), mock.patch.object(startup, "enable"):
            installed = startup.install(self.paths)
        self.assertEqual(installed["python"], str(replacement))
        self.assertEqual(installed["pythonw"], str(replacement.with_name("pythonw.exe")))
        self.assertEqual(installed["boards"][0]["command"][0], str(replacement))
        self.assertEqual(installed["boards"][0]["repo"], str(self.repo))
        self.assertIn(str(self.python), installed["trusted_python"])

    @unittest.skipUnless(os.name == "nt", "Windows startup CLI")
    def test_invalid_forget_does_not_disable_a_running_installation(self) -> None:
        with mock.patch.object(startup, "default_paths", return_value=self.paths), \
                mock.patch.object(startup, "enable") as enable, contextlib.redirect_stderr(io.StringIO()):
            result = startup.main(["forget", "--repo", "relative-project"])
        self.assertNotEqual(result, 0)
        self.assertFalse(self.paths.disabled.exists())
        enable.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows startup CLI")
    def test_failed_forget_restores_the_previously_enabled_installation(self) -> None:
        self.remember()
        self.paths.startup_link.parent.mkdir()
        self.paths.startup_link.touch()
        with mock.patch.object(startup, "default_paths", return_value=self.paths), \
                mock.patch.object(startup, "forget", side_effect=OSError("configuration busy")), \
                mock.patch.object(startup, "enable", side_effect=lambda paths: paths.disabled.unlink()) as enable, \
                contextlib.redirect_stderr(io.StringIO()):
            result = startup.main(["forget", "--repo", str(self.repo)])
        self.assertNotEqual(result, 0)
        self.assertFalse(self.paths.disabled.exists())
        enable.assert_called_once_with(self.paths)
        self.assertEqual(len(startup.load_config(self.paths)["boards"]), 1)


if __name__ == "__main__":
    unittest.main()
