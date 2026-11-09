# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Open the final file entry itself without waiting on a pipe, lease or Windows oplock."""
from __future__ import annotations

import os
from pathlib import Path

if os.name == "nt":
    import _winapi
    import ctypes
    import msvcrt
    from ctypes import wintypes

OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
SHARE_ALL = 0x1 | 0x2 | 0x4
NT_ACCESS = 0x80000000 | 0x00100000  # GENERIC_READ | SYNCHRONIZE
NT_OPEN = 1
# SYNCHRONOUS_IO_NONALERT | NON_DIRECTORY_FILE | COMPLETE_IF_OPLOCKED | OPEN_REPARSE_POINT
NT_OPTIONS = 0x20 | 0x40 | 0x100 | 0x00200000
CASE_INSENSITIVE = 0x40
OPLOCK_BREAK = 0x108

if os.name == "nt":
    class _Name(ctypes.Structure):
        _fields_ = (("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p))

    class _Attributes(ctypes.Structure):
        _fields_ = (("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(_Name)), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", ctypes.c_void_p), ("SecurityQualityOfService", ctypes.c_void_p))

    class _IoStatus(ctypes.Structure):
        _fields_ = (("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t))

    _NTDLL = ctypes.WinDLL("ntdll")
    _NTDLL.RtlDosPathNameToNtPathName_U_WithStatus.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(_Name),
                                                            ctypes.c_void_p, ctypes.c_void_p)
    _NTDLL.RtlDosPathNameToNtPathName_U_WithStatus.restype = wintypes.LONG
    _NTDLL.RtlFreeUnicodeString.argtypes = (ctypes.POINTER(_Name),)
    _NTDLL.RtlFreeUnicodeString.restype = None
    _NTDLL.NtCreateFile.argtypes = (ctypes.POINTER(wintypes.HANDLE), wintypes.ULONG, ctypes.POINTER(_Attributes),
                                  ctypes.POINTER(_IoStatus), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
                                  wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG)
    _NTDLL.NtCreateFile.restype = wintypes.LONG
    _DRIVE_TYPE = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    _DRIVE_TYPE.argtypes = (wintypes.LPCWSTR,)
    _DRIVE_TYPE.restype = wintypes.UINT


def local_volume(path: Path) -> bool:
    """Reject Windows mapped network drives before any file lookup, as well as unknown drive roots."""
    if os.name != "nt":
        return True
    return _DRIVE_TYPE(Path(path).anchor) in (2, 3, 5, 6)  # removable, fixed, optical or RAM; never DRIVE_REMOTE


def _nt_open(path: Path) -> tuple[int, int]:
    text = os.fspath(path)
    if "\0" in text:
        raise ValueError("path contains a null byte")
    name = _Name()
    status = _NTDLL.RtlDosPathNameToNtPathName_U_WithStatus(text, ctypes.byref(name), None, None)
    if status < 0:
        return status, 0
    try:
        attributes = _Attributes(ctypes.sizeof(_Attributes), None, ctypes.pointer(name), CASE_INSENSITIVE, None, None)
        handle, block = wintypes.HANDLE(), _IoStatus()
        status = _NTDLL.NtCreateFile(ctypes.byref(handle), NT_ACCESS, ctypes.byref(attributes), ctypes.byref(block),
                                   None, 0, SHARE_ALL, NT_OPEN, NT_OPTIONS, None, 0)
        return status, (handle.value or 0) if status >= 0 else 0
    finally:
        _NTDLL.RtlFreeUnicodeString(ctypes.byref(name))


def open_file(path: Path) -> int:
    """Return a read-only descriptor, sharing rename/delete on Windows and refusing an oplock break in progress."""
    if os.name != "nt":
        return os.open(path, OPEN_FLAGS)
    status, handle = _nt_open(path)
    if status != 0:
        if handle:
            _winapi.CloseHandle(handle)
        raise OSError(f"file cannot be opened ({status & 0xFFFFFFFF:#010x})")
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        _winapi.CloseHandle(handle)
        raise


def read_count(handle: int, count: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size < count:
        chunk = os.read(handle, count - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)
