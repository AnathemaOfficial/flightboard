# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Opt-in, per-user Windows startup of previously opened Flightboard dashboards.

Only process metadata and listeners are polled. This helper never reads Git, scans
repositories, stops a server, or infers a repository from an agent conversation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import cli

LOG = logging.getLogger("flightboard.startup")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Paths:
    root: Path
    source_scripts: Path
    startup_link: Path

    @property
    def engine(self) -> Path:
        return self.root / "engine" / "flightboard.py"

    @property
    def helper(self) -> Path:
        return self.root / "engine" / "flightboard_startup.py"

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def disabled(self) -> Path:
        return self.root / "disabled.flag"


def default_paths() -> Paths:
    local, roaming = os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")
    if not local or not roaming or not Path(local).is_absolute() or not Path(roaming).is_absolute():
        raise ValueError("LOCALAPPDATA and APPDATA must name absolute user folders")
    return Paths(Path(local) / "Flightboard" / "startup", Path(__file__).resolve().parent.parent,
                 Path(roaming) / "Microsoft/Windows/Start Menu/Programs/Startup/Flightboard.lnk")


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _absolute(value) -> bool:
    return isinstance(value, str) and bool(value) and "\0" not in value and Path(value).is_absolute()


def live_options(arguments: list[str]) -> dict:
    if not isinstance(arguments, list) or not all(isinstance(word, str) for word in arguments):
        raise ValueError("dashboard arguments must be strings")
    options, error = cli.read_args(arguments)
    if options is None or any(flag in options for flag in cli.SWITCHES):
        raise ValueError(error or "only live dashboard commands can be remembered")
    if not _absolute(options.get("--repo")):
        raise ValueError("a live dashboard needs --repo with an absolute path")
    if cli.CONFIG.external_root(Path(options["--repo"])) is None:
        raise ValueError("a dashboard repository must be an absolute plain local path")
    settings, error = cli.check_settings(options)
    if settings is None:
        raise ValueError(error)
    return options


def validate_config(value: dict) -> dict:
    """Reject executable commands outside the configured engine/runtime allowlists."""
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("unsupported startup configuration")
    interval = value.get("interval_seconds")
    if type(interval) is not int or not 10 <= interval <= 300:
        raise ValueError("interval_seconds must be an integer from 10 to 300")
    if type(value.get("discover_running_boards")) is not bool:
        raise ValueError("discover_running_boards must be a boolean")
    for name in ("python", "pythonw"):
        if not _absolute(value.get(name)):
            raise ValueError(f"{name} must be an absolute path")
    for name in ("trusted_engines", "trusted_python", "excluded_repos"):
        if not isinstance(value.get(name), list) or not all(_absolute(path) for path in value[name]):
            raise ValueError(f"{name} must contain absolute paths")
    engines = {_key(path) for path in value["trusted_engines"]}
    runtimes = {_key(path) for path in value["trusted_python"]}
    if _key(value["python"]) not in runtimes:
        raise ValueError("the restart interpreter must be trusted")
    if not isinstance(value.get("boards"), list):
        raise ValueError("boards must be a list")
    ports, repos = set(), set()
    for board in value["boards"]:
        if not isinstance(board, dict) or not isinstance(board.get("name"), str):
            raise ValueError("each board needs a name")
        command = board.get("command")
        if not isinstance(command, list) or len(command) < 6 or not all(isinstance(x, str) for x in command):
            raise ValueError("invalid dashboard command")
        if command[1:3] != ["-I", "-B"] or _key(command[0]) not in runtimes or _key(command[3]) not in engines:
            raise ValueError("a dashboard command must use a trusted isolated engine and interpreter")
        options = live_options(command[4:])
        port = board.get("port")
        repo = board.get("repo")
        if type(port) is not int or port != int(options.get("--port", cli.DEFAULT_PORT)):
            raise ValueError("board port and command do not match")
        if not _absolute(repo) or _key(repo) != _key(options["--repo"]):
            raise ValueError("board repository and command do not match")
        if port in ports or _key(repo) in repos:
            raise ValueError("duplicate repository or port")
        ports.add(port)
        repos.add(_key(repo))
        if "adopt_command_line" in board and not isinstance(board["adopt_command_line"], str):
            raise ValueError("invalid adopted command line")
        if "adopt_executable" in board and _key(board["adopt_executable"]) not in runtimes:
            raise ValueError("the adopted interpreter must be trusted")
    return value


def load_config(paths: Paths) -> dict:
    return validate_config(json.loads(paths.config.read_text(encoding="utf-8-sig")))


def _write(path: Path, value: dict) -> None:
    """Replace a complete JSON document; concurrent readers never see a half-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_config(settings: dict, paths: Paths) -> None:
    _write(paths.config, validate_config(settings))


def powershell(script: str, *, env=None) -> subprocess.CompletedProcess:
    executable = Path(os.environ.get("SystemRoot", "")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    return subprocess.run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, timeout=25, check=True, creationflags=NO_WINDOW, env=env)


def inventory() -> dict:
    script = (
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        "$p=@(Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%.exe'\" "
        "| Select-Object ProcessId,ExecutablePath,CommandLine,CreationDate); "
        "$l=@(Get-NetTCPConnection -State Listen -ErrorAction Stop "
        "| Select-Object LocalAddress,LocalPort,OwningProcess); "
        "@{processes=$p;listeners=$l} | ConvertTo-Json -Compress -Depth 5"
    )
    return json.loads(powershell(script).stdout.decode("utf-8-sig"))


def command_words(command: str) -> list[str]:
    split = ctypes.windll.shell32.CommandLineToArgvW
    split.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    split.restype = ctypes.POINTER(ctypes.c_wchar_p)
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    count = ctypes.c_int()
    pointer = split(command, ctypes.byref(count))
    if not pointer:
        return []
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        free(pointer)


def discover(settings: dict, current: dict, paths: Paths) -> bool:
    if not settings["discover_running_boards"]:
        return False
    ports = {board["port"] for board in settings["boards"]}
    repos = {_key(board["repo"]) for board in settings["boards"]} | {_key(p) for p in settings["excluded_repos"]}
    engines = {_key(path) for path in settings["trusted_engines"]}
    runtimes = {_key(path) for path in settings["trusted_python"]}
    changed = False
    for process in current["processes"]:
        text = process.get("CommandLine") or ""
        if "flightboard.py" not in text.casefold() or _key(process.get("ExecutablePath") or "") not in runtimes:
            continue
        words = command_words(text)
        switches, index = set(), 1
        while index < len(words) and words[index] in ("-I", "-B", "-u"):
            switches.add(words[index])
            index += 1
        if not {"-I", "-B"}.issubset(switches) or index >= len(words) or _key(words[index]) not in engines:
            continue
        arguments = words[index + 1:]
        try:
            options = live_options(arguments)
        except (ValueError, OSError):
            continue
        repo, port = options["--repo"], int(options.get("--port", cli.DEFAULT_PORT))
        if not Path(repo).is_dir():
            continue
        listeners = [item for item in current["listeners"] if item["LocalPort"] == port]
        if port in ports or _key(repo) in repos or not listeners:
            continue
        if any(item["OwningProcess"] != process["ProcessId"] or item["LocalAddress"] not in ("127.0.0.1", "::1")
               for item in listeners):
            continue
        settings["boards"].append({"name": Path(repo).name, "repo": repo, "port": port,
                                   "command": [settings["python"], "-I", "-B", str(paths.engine), *arguments],
                                   "adopt_command_line": text, "adopt_executable": process["ExecutablePath"]})
        ports.add(port)
        repos.add(_key(repo))
        changed = True
        LOG.info("Remembered dashboard %s port=%s", repo, port)
    if changed:
        save_config(settings, paths)
    return changed


def matches(process: dict, board: dict) -> bool:
    actual, executable = (process.get("CommandLine") or "").strip(), _key(process.get("ExecutablePath") or "")
    canonical = actual == subprocess.list2cmdline(board["command"]) and executable == _key(board["command"][0])
    adopted = bool(actual) and actual == board.get("adopt_command_line") and executable == _key(
        board.get("adopt_executable", board["command"][0]))
    return canonical or adopted


def _capture(stream, name: str) -> None:
    try:
        with stream:
            while chunk := stream.read1(4096):
                LOG.info("%s output: %s", name, chunk.decode("utf-8", errors="replace").rstrip())
    except Exception:
        LOG.exception("Could not capture %s output", name)


def launch(board: dict, paths: Paths, *, capture_output: bool = True) -> dict:
    for needed in (board["command"][0], board["command"][3], board["repo"]):
        if not Path(needed).exists():
            return {"name": board["name"], "state": "waiting_for_path", "path": needed}
    process = subprocess.Popen(board["command"], cwd=paths.root, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                               stderr=subprocess.STDOUT, creationflags=NO_WINDOW, close_fds=True)
    if capture_output:
        threading.Thread(target=_capture, args=(process.stdout, board["name"]), daemon=True).start()
    LOG.info("Started %s pid=%s port=%s", board["name"], process.pid, board["port"])
    return {"name": board["name"], "state": "starting", "pid": process.pid, "port": board["port"]}


def cycle(settings: dict, paths: Paths, current: dict | None = None, *, detached: bool = False) -> list[dict]:
    current = inventory() if current is None else current
    discover(settings, current, paths)
    states = []
    for board in settings["boards"]:
        processes = [p for p in current["processes"] if matches(p, board)]
        listeners = [p for p in current["listeners"] if p["LocalPort"] == board["port"]]
        owners = {p["ProcessId"] for p in processes}
        foreign = [p for p in listeners if p["OwningProcess"] not in owners]
        if foreign:
            state = {"name": board["name"], "state": "port_conflict", "port": board["port"],
                     "owners": sorted({p["OwningProcess"] for p in foreign})}
        elif processes:
            state = {"name": board["name"], "state": "listening" if listeners else "process_without_listener",
                     "port": board["port"], "processes": [
                         {"pid": p["ProcessId"], "created": p.get("CreationDate")} for p in processes]}
        else:
            state = launch(board, paths, capture_output=False) if detached else launch(board, paths)
        states.append(state)
    return states


def forget(settings: dict, repo: str, paths: Paths) -> None:
    if not _absolute(repo):
        raise ValueError("forget requires an absolute --repo path")
    settings["boards"] = [board for board in settings["boards"] if _key(board["repo"]) != _key(repo)]
    if _key(repo) not in {_key(path) for path in settings["excluded_repos"]}:
        settings["excluded_repos"].append(repo)
    save_config(settings, paths)


@contextmanager
def singleton(paths: Paths):
    import msvcrt
    paths.root.mkdir(parents=True, exist_ok=True)
    with (paths.root / "supervisor.lock").open("a+b") as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        acquired = False
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _shortcut(paths: Paths, settings: dict) -> None:
    """Paths travel as JSON via an environment variable, never as PowerShell code."""
    data = {"link": str(paths.startup_link), "target": settings["pythonw"], "cwd": str(paths.root),
            "arguments": subprocess.list2cmdline(["-I", "-B", str(paths.helper), "run"])}
    environment = dict(os.environ)
    environment["FLIGHTBOARD_SHORTCUT_DATA"] = json.dumps(data, ensure_ascii=True)
    script = (
        "$ErrorActionPreference='Stop'; $d=$env:FLIGHTBOARD_SHORTCUT_DATA | ConvertFrom-Json; "
        "$s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut($d.link); "
        "$l.TargetPath=$d.target; $l.Arguments=$d.arguments; $l.WorkingDirectory=$d.cwd; "
        "$l.WindowStyle=7; $l.Description='Flightboard multi-repository startup'; $l.Save()"
    )
    powershell(script, env=environment)


def enable(paths: Paths) -> None:
    settings = load_config(paths)
    if not paths.helper.is_file() or not Path(settings["pythonw"]).is_file():
        raise ValueError("the installed helper and pythonw must exist; run install again")
    paths.disabled.unlink(missing_ok=True)
    _shortcut(paths, settings)
    subprocess.Popen([settings["pythonw"], "-I", "-B", str(paths.helper), "run"], cwd=paths.root,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=NO_WINDOW, close_fds=True)


def disable(paths: Paths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.disabled.touch()
    paths.startup_link.unlink(missing_ok=True)


def install(paths: Paths, trust_engines=(), trust_python=()) -> dict:
    runtime = Path(sys.executable).resolve()
    if runtime.name.lower() == "pythonw.exe":
        runtime = runtime.with_name("python.exe")
    windowless = runtime.with_name("pythonw.exe")
    if not runtime.is_file() or not windowless.is_file():
        raise ValueError("install needs a Python installation with python.exe and pythonw.exe")
    engines = [paths.source_scripts / "flightboard.py", *(Path(p) for p in trust_engines)]
    runtimes = [runtime, *(Path(p) for p in trust_python)]
    for path in [*engines, *runtimes]:
        if not path.is_absolute() or not path.is_file():
            raise ValueError("trusted engines and interpreters must be existing absolute files")
    initial = {
        "version": 1, "interval_seconds": 60, "discover_running_boards": True, "boards": [],
        "excluded_repos": [], "trusted_engines": [], "trusted_python": [],
        "python": str(runtime), "pythonw": str(windowless),
    }
    paths.root.mkdir(parents=True, exist_ok=True)
    # Stop only this helper through its flag. Servers stay alive and will be adopted.
    paths.disabled.touch()
    limit = time.monotonic() + 10
    while True:
        with singleton(paths) as acquired:
            if acquired:
                # A last discovery may have completed while the stop flag was pending.
                settings = load_config(paths) if paths.config.exists() else initial
                for source in paths.source_scripts.rglob("*"):
                    relative = source.relative_to(paths.source_scripts)
                    if "__pycache__" in relative.parts or source.suffix not in (".py", ".html") or not source.is_file():
                        continue
                    destination = paths.root / "engine" / relative
                    if source.resolve() == destination.resolve():
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                for name, additions in (("trusted_engines", [*engines, paths.engine]), ("trusted_python", runtimes)):
                    settings[name] = list(dict.fromkeys([*settings[name], *(str(p.resolve()) for p in additions)]))
                settings["python"], settings["pythonw"] = str(runtime), str(windowless)
                for board in settings["boards"]:
                    board["command"][0], board["command"][3] = str(runtime), str(paths.engine)
                save_config(settings, paths)
                break
        if time.monotonic() >= limit:
            raise ValueError("the supervisor is still running; disable it and retry install")
        time.sleep(0.2)
    enable(paths)
    return settings


def run(paths: Paths, once: bool = False) -> dict:
    if paths.disabled.exists():
        return {"status": "disabled"}
    with singleton(paths) as acquired:
        if not acquired:
            return {"status": "already_running"}
        handler = RotatingFileHandler(paths.root / "startup.log", maxBytes=1_048_576, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)
        LOG.info("Supervisor started pid=%s", os.getpid())
        previous, status = None, {"status": "starting"}
        try:
            while not paths.disabled.exists():
                interval = 60
                try:
                    settings = load_config(paths)
                    interval = settings["interval_seconds"]
                    states = cycle(settings, paths, detached=True) if once else cycle(settings, paths)
                    if states != previous:
                        LOG.info("State: %s", json.dumps(states, ensure_ascii=False))
                        previous = states
                    status = {"status": "running", "supervisor_pid": os.getpid(),
                              "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "boards": states}
                    _write(paths.root / "status.json", status)
                except Exception as error:
                    LOG.exception("Supervision failed; will retry")
                    status = {"status": "error", "error": str(error)}
                    _write(paths.root / "status.json", status)
                    if once:
                        raise
                if once:
                    return status
                for _ in range(interval):
                    if paths.disabled.exists():
                        break
                    time.sleep(1)
            LOG.info("Supervisor disabled; existing servers left running")
            return {"status": "disabled"}
        finally:
            LOG.removeHandler(handler)
            handler.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    installer = commands.add_parser("install", help="install, enable and start for this Windows user")
    installer.add_argument("--trust-engine", action="append", default=[], metavar="FILE")
    installer.add_argument("--trust-python", action="append", default=[], metavar="FILE")
    for name in ("enable", "disable", "status", "run", "once"):
        commands.add_parser(name)
    forgetting = commands.add_parser("forget", help="stop remembering a repository; leave its server running")
    forgetting.add_argument("--repo", required=True)
    options = parser.parse_args(argv)
    if os.name != "nt":
        print("flightboard startup is available on Windows only", file=sys.stderr)
        return 2
    try:
        paths = default_paths()
        if options.command == "install":
            settings = install(paths, options.trust_engine, options.trust_python)
            result = {"status": "enabled", "folder": str(paths.root), "boards": len(settings["boards"])}
        elif options.command == "enable":
            enable(paths)
            result = {"status": "enabled"}
        elif options.command == "disable":
            disable(paths)
            result = {"status": "disabled", "servers_left_running": True}
        elif options.command == "status":
            result = {"enabled": paths.startup_link.exists() and not paths.disabled.exists(),
                      "folder": str(paths.root), "config": load_config(paths) if paths.config.exists() else None,
                      "last_check": json.loads((paths.root / "status.json").read_text(encoding="utf-8"))
                      if (paths.root / "status.json").exists() else None}
        elif options.command == "forget":
            # Pause supervision so a discovery write cannot race this edit.
            if not _absolute(options.repo):
                raise ValueError("forget requires an absolute --repo path")
            was_disabled = paths.disabled.exists()
            enabled = paths.startup_link.exists() and not was_disabled
            paths.root.mkdir(parents=True, exist_ok=True)
            paths.disabled.touch()
            try:
                limit = time.monotonic() + 10
                while True:
                    with singleton(paths) as acquired:
                        if acquired:
                            settings = load_config(paths)
                            forget(settings, options.repo, paths)
                            break
                    if time.monotonic() >= limit:
                        raise ValueError("supervisor is busy; retry forget")
                    time.sleep(0.2)
            finally:
                if enabled:
                    enable(paths)
                elif not was_disabled:
                    paths.disabled.unlink(missing_ok=True)
            result = {"status": "forgotten", "repo": options.repo, "servers_left_running": True}
        else:
            result = run(paths, options.command == "once")
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        if sys.stderr:
            print(f"flightboard startup: {error}", file=sys.stderr)
        return 1
