# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A successful child result requires complete input and output streams."""
from __future__ import annotations

import io
import threading
import time
import unittest
from unittest import mock

from tests.fixtures import load

processes = load("processes")


class Writer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = threading.Event()

    def write(self, data) -> int:
        self.data.extend(data)
        return len(data)

    def close(self) -> None:
        self.closed.set()


class ProcessStreamsTest(unittest.TestCase):
    def run_child(self, writer=None, output=None, **options):
        child = mock.Mock()
        child.stdin = writer
        child.stdout = io.BytesIO(b"result") if output is None else output
        child.stderr = io.BytesIO()
        child.wait.return_value = 0
        with mock.patch.object(processes.subprocess, "Popen", return_value=child):
            return processes.run(["child"], env={}, cwd=".", stdin=b"input" if writer is not None else None,
                                 timeout=options.get("timeout", 1), grace=options.get("grace", 0.1), limit=100,
                                 stop=options.get("stop"))

    def test_an_input_write_error_invalidates_a_zero_exit(self) -> None:
        class Broken(Writer):
            def write(self, data) -> int:
                raise OSError("input write failed")

        writer = Broken()
        with self.assertRaises(OSError):
            self.run_child(writer)
        self.assertTrue(writer.closed.is_set())

    def test_an_input_flush_error_on_close_invalidates_a_zero_exit(self) -> None:
        class Broken(Writer):
            def close(self) -> None:
                self.closed.set()
                raise OSError("buffered input could not be flushed")

        with self.assertRaises(OSError):
            self.run_child(Broken())

    def test_prematurely_closed_output_is_not_an_empty_success(self) -> None:
        class Closed(io.BytesIO):
            def read1(self, size=-1):
                raise ValueError("the output was closed before EOF")

        with self.assertRaises(OSError):
            self.run_child(output=Closed())

    def test_overflow_remains_explicit_when_stopping_the_child_breaks_input(self) -> None:
        for failure in ("write", "close"):
            with self.subTest(failure=failure):
                stopped = threading.Event()

                class Interrupted(Writer):
                    def write(self, data) -> int:
                        stopped.wait()
                        if failure == "write":
                            raise BrokenPipeError("child stopped after overflowing its output")
                        return super().write(data)

                    def close(self) -> None:
                        super().close()
                        if failure == "close":
                            raise OSError("input flush failed after the child was stopped")

                writer = Interrupted()
                try:
                    result = self.run_child(writer, output=io.BytesIO(b"x" * 101),
                                            stop=lambda child: stopped.set())
                    self.assertIsNone(result[0])
                    self.assertTrue(result[3])
                finally:
                    stopped.set()
                    self.assertTrue(writer.closed.wait(1), "the test must not leave its feeder blocked")

    def test_partial_input_writes_are_completed_before_success(self) -> None:
        class Partial(Writer):
            def write(self, data) -> int:
                return super().write(data[:2])

        writer = Partial()
        self.assertEqual(self.run_child(writer), (0, b"result", b"", False))
        self.assertEqual(writer.data, b"input")
        self.assertTrue(writer.closed.is_set())

    def test_an_input_write_without_progress_is_not_a_success(self) -> None:
        class Stalled(Writer):
            def write(self, data) -> int:
                return 0

        with self.assertRaises(OSError):
            self.run_child(Stalled())

    def test_unfinished_input_uses_the_same_deadline_and_cleanup_grace(self) -> None:
        gate = threading.Event()

        class Blocked(Writer):
            def write(self, data) -> int:
                gate.wait(2)
                return super().write(data)

        writer = Blocked()
        started = time.monotonic()
        try:
            result = self.run_child(writer, timeout=0.05, grace=0.05)
            self.assertIsNone(result[0])
            self.assertLess(time.monotonic() - started, 1)
        finally:
            gate.set()
            self.assertTrue(writer.closed.wait(1), "the test must not leave its feeder blocked")

    def test_complete_input_and_outputs_keep_the_success_result(self) -> None:
        writer = Writer()
        self.assertEqual(self.run_child(writer), (0, b"result", b"", False))
        self.assertEqual(writer.data, b"input")


if __name__ == "__main__":
    unittest.main()
