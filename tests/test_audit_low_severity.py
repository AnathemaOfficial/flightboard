# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Non-regression tests for the low-severity findings (B1-B10) of the Flightboard audit."""
from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

from tests.fixtures import decision, ledger, load, roadmap

base = load("ledgers.base")
files = load("files")
ledgers = load("ledgers")
page = load("page")
processes = load("processes")
roadmap_ledger = load("ledgers.roadmap")
rules = load("ledgers.roadmap_rules")
server = load("server")
startup = load("windows_startup")
tasks = load("ledgers.tasks")
text = load("text")


class PipeReadErrorTest(unittest.TestCase):
    """B1: an output the reader could not read is never handed back as a complete result."""

    def test_a_pipe_read_error_raises_instead_of_truncating(self) -> None:
        class Broken:
            def read1(self, size: int) -> bytes:
                raise OSError("the pipe broke")

            def close(self) -> None:
                pass

        proc = mock.Mock()
        proc.stdout, proc.stderr, proc.stdin = Broken(), Broken(), None
        proc.wait.return_value = 0
        with mock.patch.object(processes.subprocess, "Popen", return_value=proc):
            with self.assertRaises(OSError):
                processes.run(["git"], env={}, cwd=".", stdin=None, timeout=1, limit=100)


class ValidatorGuardTest(unittest.TestCase):
    """B2: an unhashable value names its field instead of breaking the validator."""

    def test_a_list_where_a_milestone_belongs_names_the_field(self) -> None:
        raw = ledger({"FB-001": "planned"})
        raw["tasks"][0]["milestone"] = []
        errors = rules.validate_ledger(raw)
        self.assertTrue(any("unknown milestone" in error for error in errors))

    def test_a_list_where_a_decision_task_belongs_names_the_field(self) -> None:
        raw = ledger({"FB-001": "planned"})
        entry = decision()
        entry.update(task=[], status="open", default_fr="the default")
        raw["decisions"] = [entry]
        errors = rules.validate_ledger(raw)
        self.assertTrue(any("must cite the owner's task" in error for error in errors))


class CleanTest(unittest.TestCase):
    """B3: padding does not hide the text that follows it."""

    def test_padding_does_not_hide_the_text_after_it(self) -> None:
        self.assertEqual(text.clean("A" + " " * 4000 + "B", 200), "A B")
        self.assertEqual(text.clean("A" + "\u2800" * 4000 + "B", 200), "A B")

    def test_the_limit_still_cuts_and_control_characters_still_vanish(self) -> None:
        self.assertEqual(text.clean("x" * 500, 40), "x" * 40)
        self.assertEqual(text.clean("a\u202eb", 200), "a b")


class LedgerPathTest(unittest.TestCase):
    """B4: a git admin folder spelled as Windows reads it is refused."""

    def test_a_git_folder_with_a_trailing_dot_is_refused(self) -> None:
        for path in (".git./config", ".GIT./x.json", "sub/.git./x.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ledgers.make("tasks", path)


class EmptyLedgerTest(unittest.TestCase):
    """B5: a well-formed ledger with no task is invalid, never silently absent."""

    def test_a_ledger_with_no_task_is_invalid(self) -> None:
        parsed = roadmap().parse(json.dumps(ledger({})).encode("utf-8"))
        self.assertIsNotNone(parsed)
        self.assertFalse(parsed["valid"])
        self.assertIn("no task", parsed["error"])


class ImpossibleDateTest(unittest.TestCase):
    """B6: a date that does not exist is refused and never shown as a fact."""

    def test_a_date_the_calendar_lacks_is_refused(self) -> None:
        parsed = roadmap().parse(json.dumps(ledger({"FB-001": "planned"}, updated="2024-02-31")).encode("utf-8"))
        self.assertFalse(parsed["valid"])
        self.assertEqual(parsed["updated_at"], "")

    def test_a_task_file_with_such_a_date_is_invalid(self) -> None:
        data = json.dumps({"version": 1, "updated_at": "2024-02-31",
                           "tasks": [{"id": "T-1", "status": "done"}]}).encode("utf-8")
        parsed = ledgers.make("tasks", "tasks.json").parse(data)
        self.assertFalse(parsed["valid"])
        self.assertIn("updated_at", parsed["error"])


class DependencyListTest(unittest.TestCase):
    """B7: a dependency declared twice is refused, and the declared list stays bounded."""

    def test_a_duplicate_dependency_is_refused(self) -> None:
        data = json.dumps({"version": 1, "tasks": [
            {"id": "T-1", "status": "done", "depends_on": ["T-2", "T-2"]},
            {"id": "T-2", "status": "done"}]}).encode("utf-8")
        parsed = ledgers.make("tasks", "tasks.json").parse(data)
        self.assertFalse(parsed["valid"])
        self.assertIn("declared twice", parsed["error"])

    def test_the_list_is_deduplicated_and_bounded(self) -> None:
        self.assertEqual(base.dependencies(["a", "a", "b"]), ["a", "b"])
        self.assertEqual(len(base.dependencies([f"t{index}" for index in range(500)])), base.MAX_DEPENDENCIES)


class RefFolderBudgetTest(unittest.TestCase):
    """B8: a folder of loose refs costs the shared budget, never unbounded time."""

    def test_a_large_names_folder_stops_at_the_budget(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            folder = root / "refs"
            folder.mkdir()
            for index in range(5):
                (folder / f"r{index}").write_text("x", encoding="utf-8")
            self.assertEqual(files._linked_entry(folder, root, budget=files.Budget(entries=2)), "many")


class ConnectionCapTest(unittest.TestCase):
    """B9: an idle flood never spawns threads without end."""

    def test_a_flood_of_idle_connections_is_bounded(self) -> None:
        board = None
        sockets: list[socket.socket] = []
        with mock.patch.object(server.Server, "capacity", threading.BoundedSemaphore(2)):
            board = server.make_server(server.Snapshots(object()), page.template(), 0)
            thread = threading.Thread(target=board.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
            thread.start()
            try:
                for _ in range(3):
                    sockets.append(socket.create_connection(("127.0.0.1", board.server_address[1]), timeout=10))
                received = b""
                for raw in sockets:
                    raw.settimeout(0.5)
                    try:
                        received += raw.recv(128)
                    except OSError:
                        pass
                self.assertIn(b"503", received)
            finally:
                for raw in sockets:
                    raw.close()
                board.shutdown()
                board.server_close()


class CycleDisabledTest(unittest.TestCase):
    """B10: a disable that lands during a cycle does not launch a board."""

    def test_a_disabled_cycle_launches_nothing(self) -> None:
        settings = {"discover_running_boards": False,
                    "boards": [{"name": "board", "repo": str(Path.cwd()), "port": 8791, "command": ["python"]}]}
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            paths = startup.Paths(root, root, root / "Flightboard.lnk")
            paths.disabled.touch()
            with mock.patch.object(startup, "launch", side_effect=AssertionError("no launch")) as launch:
                states = startup.cycle(settings, paths, {"processes": [], "listeners": []})
            self.assertEqual(states[0]["state"], "disabled")
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
