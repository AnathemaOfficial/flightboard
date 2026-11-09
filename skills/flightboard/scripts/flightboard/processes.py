# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Bounded subprocess pipes, including a Windows input pipe that nobody reads.

Only pipe threads touch or close their own streams. The caller waits for one deadline, then gives process cleanup
and all pipe threads one shared grace period. A child retaining a pipe cannot hold the reader forever.
"""
from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable

CHUNK = 65_536
ERROR_BYTES = 65_536


def _feed(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _drain(stream, chunks: list[bytes], limit: int, over: threading.Event, done: threading.Event) -> None:
    size = 0
    try:
        while chunk := stream.read1(CHUNK):
            size += len(chunk)
            if size > limit:
                over.set()
                return
            chunks.append(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass
        done.set()


def run(command: list[str], *, env: dict[str, str], cwd: str, stdin: bytes | None, timeout: float,
        limit: int, grace: float = 0.25, stop: Callable | None = None) -> tuple[int | None, bytes, bytes, bool]:
    """Return (code, stdout, stderr, oversized); code None means deadline or output limit, and git is stopped.

    Popen errors are left to the caller. The timeout covers feeding input and both outputs, unlike subprocess.run
    on Windows. Both output streams have a byte limit; oversized output is never returned as a complete result.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    proc = subprocess.Popen(command, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output: list[bytes] = []
    errors: list[bytes] = []
    over, out_done, err_done = threading.Event(), threading.Event(), threading.Event()
    threads = [threading.Thread(target=_drain, args=(proc.stdout, output, limit, over, out_done), daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, errors, ERROR_BYTES, over, err_done), daemon=True)]
    if stdin is not None:
        threads.append(threading.Thread(target=_feed, args=(proc.stdin, stdin), daemon=True))
    for thread in threads:
        thread.start()
    code = None
    try:
        while not over.is_set() and not (out_done.is_set() and err_done.is_set()):
            left = deadline - time.monotonic()
            if left <= 0:
                break
            over.wait(min(left, 0.01))
        if not over.is_set() and out_done.is_set() and err_done.is_set():
            code = proc.wait(max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        pass
    finally:
        until = time.monotonic() + max(0.0, grace)
        if code is None:
            try:
                (stop or (lambda child: child.kill()))(proc)
            except OSError:
                pass
            try:
                proc.wait(max(0.0, until - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for thread in threads:
            thread.join(max(0.0, until - time.monotonic()))
    return code, b"".join(output), b"".join(errors), over.is_set()
