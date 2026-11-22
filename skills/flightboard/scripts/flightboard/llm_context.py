# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""A frozen, bounded dossier of explicitly selected local files and board observations.

The caller obtains separate reading and sharing consent. This reader never discovers
paths in board/model text, walks a directory, runs Git, or changes a selected file.
The conservative secret checks are a filter, not a guarantee; the owner still reviews
the exact frozen dossier before it is sent to a provider.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

from . import files as FILES
from . import readio

MAX_FILES = 12
MAX_FILE_BYTES = 32_768
MAX_CONTEXT_BYTES = 131_072
MAX_BOARD_BYTES = 65_536
MAX_BOARD_STRING_CHARS = 4096
MAX_PATH_CHARS = 1024
BOARD_FIELDS = ("generated_at", "tool", "repository", "main", "overview", "publication", "sessions",
                "waiting", "limits")
SENSITIVE_PARTS = frozenset({".git", ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker"})
SECRET_NAMES = frozenset({"credentials", "credentials.json", "secrets", "secrets.json", "secrets.yaml",
                          "secrets.yml", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_dsa", "id_ecdsa",
                          "id_ed25519", "known_hosts", "authorized_keys", ".envrc",
                          "application_default_credentials.json"})
SENSITIVE_PAIRS = frozenset({(".codex", "auth.json"), (".claude", ".credentials.json"),
                             (".gemini", "oauth_creds.json"), ("gh", "hosts.yml"),
                             ("github cli", "hosts.yml")})
SECRET_KEYS = frozenset({"api_key", "apikey", "password", "passwd", "authorization", "credential",
                         "credentials", "secret", "secrets", "access_token", "refresh_token", "private_key"})
SECRET_CONTENT = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"
    r"|\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"
    r"|(?i:(?:^|[\s{;,])[\"']?(?:[A-Z0-9_]*API[_-]?KEY|[A-Z0-9_]*SECRET|[A-Z0-9_]*TOKEN"
    r"|PASSWORD|PASSWD|AUTHORIZATION)[\"']?\s*[:=]\s*[\"']?[^\s\"'#]{8,})"
)


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _text(value: object) -> bool:
    return (type(value) is str and 0 < len(value) <= MAX_PATH_CHARS
            and not any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value))


def _plain_text(text: str, *, absolute: bool) -> bool:
    # Inspect the written spelling before Path can collapse a dot or repeated separator.
    if not _text(text) or text.startswith(("//", "\\\\")):
        return False
    if os.name != "nt" and "\\" in text:
        return False
    split = text.replace("\\", "/").split("/")
    if absolute:
        split = split[1:] if text.startswith("/") else split
        if os.name == "nt" and split and re.fullmatch(r"[A-Za-z]:", split[0]):
            split = split[1:]
    if not split or any(not part or part in (".", "..") or ":" in part
                        or part.endswith((".", " ")) or part.split(".")[0].upper() in FILES.RESERVED
                        for part in split):
        return False
    path = Path(text)
    return path.is_absolute() is absolute


def _secret_path(path: Path) -> bool:
    lowered = [part.casefold() for part in path.parts]
    parts = set(lowered)
    name = path.name.casefold()
    return bool(parts & SENSITIVE_PARTS or name in SECRET_NAMES or name == ".env" or name.startswith(".env.")
                or any(pair in SENSITIVE_PAIRS for pair in zip(lowered, lowered[1:]))
                or name.endswith((".pem", ".key", ".p12", ".pfx", ".keystore", ".kdbx")))


def _identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink


def _chain(path: Path) -> tuple[tuple, ...] | None:
    """Record every plain directory's identity and the final regular file's metadata."""
    if not readio.local_volume(path):
        return None
    current = Path(path.anchor)
    found = []
    try:
        info = current.lstat()
        if FILES.is_link(info) or not stat.S_ISDIR(info.st_mode):
            return None
        found.append((info.st_dev, info.st_ino, info.st_mode))
        for index, part in enumerate(path.parts[1:]):
            current /= part
            info = current.lstat()
            final = index == len(path.parts) - 2
            if FILES.is_link(info) or (not final and not stat.S_ISDIR(info.st_mode)):
                return None
            if final:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return None
                found.append(_identity(info))
            else:
                found.append((info.st_dev, info.st_ino, info.st_mode))
    except (OSError, ValueError):
        return None
    return tuple(found)


def _read(path: Path) -> tuple[bytes | None, str]:
    before = _chain(path)
    if before is None:
        return None, "unreadable_or_unsafe"
    raw, reason, seen = FILES._read_regular(path, Path(path.anchor), MAX_FILE_BYTES)
    if raw is None:
        return None, "file_too_large" if reason == "too_big" else "unreadable_or_unsafe"
    if seen is None or before[-1] != _identity(seen) or _chain(path) != before:
        return None, "changed_during_read"
    return raw, "ok"


def _board(board: dict, omitted: list[dict]) -> tuple[dict, bool]:
    """Copy only observation fields, bounding every container and string before serialization."""
    partial = False
    nodes = 0
    secret = oversized = False

    def copy(value, depth=0):
        nonlocal partial, nodes, secret, oversized
        if secret or oversized:
            return None
        nodes += 1
        if depth > 10 or nodes > 3000:
            partial = True
            return None
        if value is None or type(value) is bool:
            return value
        if type(value) is int:
            if value.bit_length() <= 64:
                return value
            partial = True
            return None
        if type(value) is float:
            if math.isfinite(value):
                return value
            partial = True
            return None
        if type(value) is str:
            # Never scan an unbounded string or share a prefix that could end midway through a credential.
            if len(value) > MAX_BOARD_STRING_CHARS:
                partial = oversized = True
                return None
            if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
                partial = True
                return None
            if SECRET_CONTENT.search(value):
                partial = secret = True
                return None
            return value
        if type(value) is list:
            if len(value) > 100:
                partial = True
            return [copy(item, depth + 1) for item in value[:100]]
        if type(value) is dict:
            result = {}
            if len(value) > 100:
                partial = True
            for index, (key, item) in enumerate(value.items()):
                if index >= 100:
                    break
                if type(key) is not str or len(key) > 200 or any(0xD800 <= ord(c) <= 0xDFFF for c in key):
                    partial = True
                    continue
                if key.startswith("_"):
                    continue  # implementation caches/expiry counters are neither evidence nor provider context
                if key.casefold() in SECRET_KEYS:
                    partial = True
                    continue
                result[key] = copy(item, depth + 1)
            return result
        partial = True
        return None

    result = {}
    for field in BOARD_FIELDS:
        if field not in board:
            continue
        secret = oversized = False
        candidate = copy(board[field])
        if secret or SECRET_CONTENT.search(_json(candidate).decode("utf-8")):
            partial = True
            omitted.append({"source": "board:" + field, "reason": "secret_detected"})
            continue
        if oversized or len(_json({**result, field: candidate})) > MAX_BOARD_BYTES:
            partial = True
            omitted.append({"source": "board:" + field, "reason": "board_limit"})
            continue
        result[field] = candidate
    if partial:
        omitted.append({"source": "board", "reason": "partial_snapshot"})
    return result, partial


def build_context(board: dict, repo: Path, repo_files: list[str], local_files: list[str]) -> dict:
    """Return exact accepted UTF-8 bytes as text, or an explicit omission; never discover more files."""
    if type(board) is not dict or not isinstance(repo, Path):
        raise ValueError("invalid_context")
    if (type(repo_files) is not list or type(local_files) is not list
            or len(repo_files) + len(local_files) > MAX_FILES
            or any(not _text(name) for name in (*repo_files, *local_files))):
        raise ValueError("invalid_selection")
    selections, seen = [], set()
    for kind, names in (("repo", repo_files), ("local", local_files)):
        for name in names:
            valid = _plain_text(name, absolute=kind == "local")
            valid = valid and (kind == "local" or _plain_text(str(repo), absolute=True))
            path = Path(name) if kind == "local" else repo / name
            key = str(path).casefold() if os.name == "nt" else str(path)
            if key in seen:
                raise ValueError("duplicate_selection")
            seen.add(key)
            selections.append((kind + ":" + name, path, valid))
    omitted = []
    frozen, partial = _board(board, omitted)
    context = {"board": frozen, "files": [], "omitted": omitted,
               "limits": {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
                          "max_context_bytes": MAX_CONTEXT_BYTES, "board_partial": partial}}
    for source, path, valid in selections:
        reason = "unsafe_path" if not valid else "secret_path" if _secret_path(path) else ""
        raw = None
        if not reason:
            raw, reason = _read(path)
        if raw is not None:
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeError:
                reason = "not_utf8_text"
            else:
                if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in text):
                    reason = "not_utf8_text"
                elif SECRET_CONTENT.search(text):
                    reason = "secret_detected"
                else:
                    item = {"source": source, "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "text": text}
                    context["files"].append(item)
                    if len(_json(context)) <= MAX_CONTEXT_BYTES:
                        continue
                    context["files"].pop()
                    reason = "context_limit"
        omitted.append({"source": source, "reason": reason})
    # Later omission labels can be longer than an accepted empty file's metadata.
    while len(_json(context)) > MAX_CONTEXT_BYTES and context["files"]:
        item = context["files"].pop()
        omitted.append({"source": item["source"], "reason": "context_limit"})
    if len(_json(context)) > MAX_CONTEXT_BYTES:
        raise ValueError("context_limit")
    return context
