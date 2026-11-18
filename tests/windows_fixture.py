# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Own only the Windows processes a fixture places in its non-inheritable job."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time


def fixture_python() -> str:
    """A Windows venv's redirector must not create an interpreter before job assignment."""
    return str(Path(sys._base_executable).resolve(strict=True))


class _Limits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _Limits), ("io", _IO), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("user", "kernel", "period_user", "period_kernel")]
    _fields_ += [(name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]


class WindowsJob:
    """No name, inherited handle, breakaway permission, or process discovery outside this job."""

    def __init__(self) -> None:
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                                        wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.c_void_p], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            operation = getattr(self.api, name)
            operation.argtypes, operation.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            self._check(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits),
                                                        ctypes.sizeof(limits)))
        except BaseException as primary:
            try:
                self.close()
            except BaseException as error:
                primary.add_note(f"fixture job setup cleanup also failed: {error!r}")
            raise

    @staticmethod
    def _check(result) -> None:
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process_handle: int) -> None:
        self._check(self.api.AssignProcessToJobObject(self.handle, process_handle))

    def contains(self, process_handle: int) -> bool:
        member = wintypes.BOOL()
        self._check(self.api.IsProcessInJob(process_handle, self.handle, ctypes.byref(member)))
        return bool(member.value)

    def active(self) -> int:
        accounting = _Accounting()
        self._check(self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                      ctypes.sizeof(accounting), None))
        return accounting.active

    def stop(self) -> None:
        self._check(self.api.TerminateJobObject(self.handle, 1))
        deadline = time.monotonic() + 5
        while self.active():
            if time.monotonic() >= deadline:
                raise TimeoutError("fixture job still has active processes after termination")
            time.sleep(0.01)

    def close(self) -> None:
        if self.handle is not None:
            self._check(self.api.CloseHandle(self.handle))
            self.handle = None
