# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Build deterministic skill/plugin archives from an exact committed tree, without modifying the source.

The distribution version is stamped into the runtime and both plugin manifests.
Only this documented transformation changes committed bytes; provenance and checksums accompany the archives.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import zipfile

SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
                     r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
                     r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")
VERSION_PATHS = ("plugin.json", ".claude-plugin/plugin.json",
                 "skills/flightboard/scripts/flightboard/__init__.py")
MAX_FILES = 4096
MAX_FILE_BYTES = 8_000_000
MAX_SOURCE_BYTES = 32_000_000
GIT_TIMEOUT = 20.0
ROOT_FILES = frozenset({"plugin.json", "README.md", "LICENSE", "NOTICE", "SECURITY.md", "REUSE.toml", "CHANGELOG.md"})
PLUGIN_PREFIXES = ("skills/flightboard/", ".claude-plugin/", ".agents/plugins/", "assets/", "docs/", "LICENSES/")
REQUIRED = frozenset({*VERSION_PATHS, "skills/flightboard/SKILL.md", "skills/flightboard/scripts/flightboard.py",
                      ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json", "LICENSE"})
ODD_WINDOWS = re.compile(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?")
_PROCESS = None


class ReleaseError(ValueError):
    """The requested source or destination does not satisfy the release contract."""


def valid_version(value: str) -> bool:
    match = VERSION.fullmatch(value) if isinstance(value, str) and len(value) <= 80 else None
    return bool(match and not any(part.isdigit() and len(part) > 1 and part[0] == "0"
                                  for part in (match[4] or "").split(".")))


def _plain(path: Path) -> None:
    for candidate in reversed((path, *path.parents)):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReleaseError("destination ancestor is unreadable") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ReleaseError("links and reparse points are not release destinations")
        if not stat.S_ISDIR(info.st_mode):
            raise ReleaseError("destination ancestor is not a directory")


def _destination(repo: Path, output: Path) -> Path:
    output = Path(output)
    if not output.is_absolute() or ".." in output.parts:
        raise ReleaseError("output must be an absolute directory outside repositories")
    _plain(output)
    if output == repo or repo in output.parents:
        raise ReleaseError("release output must remain outside the source repository")
    # A package build must not deposit artifacts into another observed project either.
    for ancestor in (output, *output.parents):
        try:
            (ancestor / ".git").lstat()
        except FileNotFoundError:
            continue
        raise ReleaseError("release output must remain outside Git repositories")
    if output.exists() and any(output.iterdir()):
        raise ReleaseError("output directory must be new or empty")
    return output


def _executable(*, windows: bool | None = None) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ReleaseError("Git is required to read the exact committed source")
    # Git for Windows' bin/cmd launchers can leave a child holding the pipes when
    # the launcher is stopped. Use the real executable so the timer stops the reader.
    selected = Path(executable)
    if (os.name == "nt" if windows is None else windows) and selected.parent.name.casefold() in ("cmd", "bin"):
        for directory in ("mingw64", "mingw32"):
            direct = selected.parent.parent / directory / "bin" / "git.exe"
            if direct.is_file():
                executable = str(direct)
                break
    return executable


def _runner():
    """Reuse the independently tested bounded pipe runner, without importing the board or observing a repo."""
    global _PROCESS
    if _PROCESS is None:
        path = Path(__file__).resolve().parents[1] / "skills/flightboard/scripts/flightboard/processes.py"
        spec = importlib.util.spec_from_file_location("_release_processes", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PROCESS = module
    return _PROCESS


def _git(repo: Path, args: list[str], *, feed: bytes = b"", limit: int = MAX_SOURCE_BYTES) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1",
               GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    command = [_executable(), "-C", str(repo), "-c", f"core.hooksPath={os.devnull}", *args]
    try:
        code, raw, _, over = _runner().run(command, env=env, cwd=str(repo), stdin=feed,
                                          timeout=GIT_TIMEOUT, limit=limit)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError("Git source reading failed or timed out") from exc
    if over or code is None:
        raise ReleaseError("Git source reading exceeded its output or time limit")
    if code != 0:
        raise ReleaseError("Git could not read the requested committed source")
    return raw


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name and len(name) <= 500 and not path.is_absolute() and str(path) == name
                and "\\" not in name and ":" not in name and not any(c in name for c in '<>"|?*')
                and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                and all(part not in (".", "..") and part.casefold() != ".git" and not part.endswith((" ", "."))
                        and not ODD_WINDOWS.fullmatch(part) for part in path.parts))


def _source(repo: Path, commit: str) -> dict[str, bytes]:
    if _git(repo, ["rev-parse", "--verify", commit + "^{commit}"], limit=200).strip().decode() != commit:
        raise ReleaseError("ref must identify the exact requested commit")
    listing = _git(repo, ["ls-tree", "-r", "-l", "-z", "--full-tree", commit], limit=2_000_000)
    entries, objects, total, names, directories = [], {}, 0, set(), set()
    for row in listing.split(b"\0"):
        if not row:
            continue
        try:
            metadata, encoded = row.split(b"\t", 1)
            mode, kind, object_id, size = metadata.split()
            name = encoded.decode("utf-8", errors="strict")
            count = int(size)
        except (ValueError, UnicodeError) as exc:
            raise ReleaseError("source tree entry is unreadable") from exc
        key = name.casefold()
        parents = {str(parent) for parent in PurePosixPath(key).parents if str(parent) != "."}
        if (mode not in (b"100644", b"100755") or kind != b"blob" or not SHA.fullmatch(object_id.decode())
                or not _safe_name(name) or key in names or key in directories or parents & names
                or not 0 <= count <= MAX_FILE_BYTES):
            raise ReleaseError("source tree contains an unsafe path, link, collision or oversized file")
        names.add(key)
        directories.update(parents)
        entries.append((name, object_id))
        objects[object_id] = count
        total += count
        if len(entries) > MAX_FILES or total > MAX_SOURCE_BYTES:
            raise ReleaseError("source tree exceeds the package bounds")
    if not REQUIRED.issubset(name for name, _ in entries):
        raise ReleaseError("required skill, plugin or license files are missing")
    feed = b"".join(object_id + b"\n" for object_id in objects)
    raw = _git(repo, ["cat-file", "--batch"], feed=feed,
               limit=sum(objects.values()) + len(objects) * 100)
    blobs, offset = {}, 0
    for object_id, count in objects.items():
        end = raw.find(b"\n", offset)
        expected = object_id + b" blob " + str(count).encode()
        if end < 0 or raw[offset:end] != expected or raw[end + count + 1:end + count + 2] != b"\n":
            raise ReleaseError("source object response is incomplete")
        blobs[object_id] = raw[end + 1:end + count + 1]
        offset = end + count + 2
    if offset != len(raw):
        raise ReleaseError("source object response contains unexpected bytes")
    return {name: blobs[object_id] for name, object_id in entries}


def _stamp(files: dict[str, bytes], version: str) -> tuple[dict[str, bytes], str]:
    files = dict(files)
    try:
        manifests = [json.loads(files[name]) for name in VERSION_PATHS[:2]]
        runtime = files[VERSION_PATHS[2]].decode("utf-8")
        matches = re.findall(r'^__version__ = "([^"]+)"$', runtime, flags=re.M)
        if len(matches) != 1:
            raise ReleaseError("runtime version marker is ambiguous")
        base = matches[0]
        if not valid_version(base) or any(value.get("version") != base for value in manifests):
            raise ReleaseError("source runtime and plugin versions disagree")
        for name, manifest in zip(VERSION_PATHS[:2], manifests):
            manifest["version"] = version
            files[name] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        files[VERSION_PATHS[2]] = re.sub(r'^__version__ = "[^"]+"$',
                                       '__version__ = "' + version + '"', runtime, flags=re.M).encode("utf-8")
    except (ValueError, UnicodeError, AttributeError, KeyError) as exc:
        raise ReleaseError("source version metadata is invalid") from exc
    return files, base


def _zip(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, raw)
    return stream.getvalue()


def _json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def build(repo: Path, commit: str, version: str, output: Path) -> dict:
    """Return provenance and write four new artifacts, never using dirty or untracked file bytes."""
    if not isinstance(commit, str) or SHA.fullmatch(commit) is None or not valid_version(version):
        raise ReleaseError("a full lowercase commit SHA and a valid SemVer version are required")
    repo = Path(repo).resolve(strict=True)
    output = _destination(repo, output)
    files, base = _stamp(_source(repo, commit), version)
    plugin = {name: value for name, value in files.items() if name in ROOT_FILES or name.startswith(PLUGIN_PREFIXES)}
    prefix = "skills/flightboard/"
    skill = {"flightboard/" + name[len(prefix):]: value for name, value in files.items() if name.startswith(prefix)}
    skill.update({"flightboard/" + name: value for name, value in files.items()
                  if name in ("LICENSE", "NOTICE") or name.startswith("LICENSES/")})
    for contract in ("docs/git-github-publication.md", "docs/agent-briefing.md"):
        if contract in files:
            skill["flightboard/" + contract] = files[contract]
    payload = {f"flightboard-skill-{version}.zip": _zip(skill), f"flightboard-plugin-{version}.zip": _zip(plugin)}
    manifest = {"schema_version": 1, "source_sha": commit, "source_base_version": base, "version": version,
                "transformations": list(VERSION_PATHS),
                "assets": [{"name": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
                           for name, raw in sorted(payload.items())]}
    payload["release-manifest.json"] = _json(manifest)
    payload["SHA256SUMS"] = "".join(hashlib.sha256(raw).hexdigest() + "  " + name + "\n"
                                    for name, raw in sorted(payload.items())).encode("ascii")
    _destination(repo, output)  # recheck before creating any path or writing bytes
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in payload.items():
        with (output / name).open("xb") as handle:
            handle.write(raw)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="full lowercase source commit SHA")
    parser.add_argument("--version", required=True, help="distribution SemVer version")
    parser.add_argument("--output", required=True, type=Path, help="new absolute directory outside repositories")
    options = parser.parse_args()
    try:
        manifest = build(Path(__file__).resolve().parents[1], options.ref, options.version, options.output)
    except (ReleaseError, OSError) as exc:
        parser.exit(1, f"release build refused: {exc}\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
