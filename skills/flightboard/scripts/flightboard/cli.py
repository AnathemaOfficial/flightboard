# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The command line of flightboard.

    flightboard.py [--port N]                    serve the live page on http://127.0.0.1:8790/
    flightboard.py --resume                      print the summary and what waits for you, as text
    flightboard.py --snapshot [--output FILE]    write the page once, outside the repository

and, for any of them: --repo DIR, --lang en|fr, --ledger auto|none|tasks|roadmap, --ledger-path PATH, --main BRANCH,
--remote NAME, --worktrees DIR, --worktrees-root DIR, --kept DIR (repeatable), --active-minutes N, --recent-minutes N,
--stale-days N, --max-branches N, --max-worktrees N, --read-seconds N. It prints one JSON line (except --resume); a
usage error exits with code 2, a busy port or a write error with code 1. It reads; it never approves nor authorizes
anything. Nothing is written but the snapshot, in the user's cache folder or the --output file, never inside the
observed repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from . import __version__
from . import config as CONFIG
from . import files as FILES
from . import messages as M
from . import page as PAGE
from . import server as SERVER
from .collector import Collector
from .config import Settings
from .ledgers import KINDS as LEDGER_KINDS

DEFAULT_PORT = 8790
PORT = re.compile(r"[0-9]{4,5}")
USAGE = ("usage: flightboard.py [--port N] | --resume | --snapshot [--output FILE]\n"
         "       [--repo DIR] [--lang en|fr] [--ledger auto|none|tasks|roadmap] [--ledger-path PATH]\n"
         "       [--main BRANCH] [--remote NAME] [--worktrees DIR]... [--kept DIR]...\n"
         "       [--worktrees-root DIR]... (explicit absolute local roots for external worktrees)\n"
         "       [--active-minutes N] [--recent-minutes N] [--stale-days N] [--max-branches N]\n"
         "       [--max-worktrees N] (1 to 1000 registered worktrees; default 100)\n"
         "       [--read-seconds N] (12 to 120 seconds; default 12 for one whole snapshot)")
SWITCHES = ("--resume", "--snapshot", "--help", "-h", "--version")
VALUES = ("--port", "--output", "--repo", "--lang", "--ledger", "--ledger-path", "--main", "--remote",
          "--active-minutes", "--recent-minutes", "--stale-days", "--max-branches", "--read-seconds", "--max-worktrees")
REPEATED = ("--worktrees", "--kept", "--worktrees-root")
NUMBERS = {"--active-minutes": "active_minutes", "--recent-minutes": "recent_minutes", "--stale-days": "stale_days",
           "--max-branches": "max_branches", "--read-seconds": "read_seconds", "--max-worktrees": "max_worktrees"}
RESUME_NOTES = ("guessed", "remote_ahead", "diverged", "remote_only")  # the notes on main --resume says, in fixed words


# ---------------------------------------------------------------- the command line

def read_args(argv: list[str]) -> tuple[dict | None, str]:
    """(options, "") or (None, why): each flag once (but --worktrees and --kept), each value present and not a flag,
    one mode at most, --output only with --snapshot."""
    options: dict = {flag: [] for flag in REPEATED}
    rest = list(argv)
    while rest:
        flag = rest.pop(0)
        if flag in SWITCHES:
            if flag in options:
                return None, f"{flag} is given twice"
            options[flag] = ""
        elif flag in VALUES or flag in REPEATED:
            if not rest or not rest[0] or rest[0].startswith("--"):
                return None, f"{flag} needs a value"
            if flag in VALUES and flag in options:
                return None, f"{flag} is given twice"
            value = rest.pop(0)
            if flag in REPEATED:
                options[flag].append(value)
            else:
                options[flag] = value
        else:
            return None, f"unknown option {flag[:40]!r} (an option takes its value as the next word, never after =)"
    modes = [flag for flag in ("--snapshot", "--resume", "--port") if flag in options]
    if len(modes) > 1:
        return None, f"{' and '.join(modes)} cannot go together"
    if "--output" in options and "--snapshot" not in options:
        return None, "--output goes with --snapshot"
    if "--port" in options and (not PORT.fullmatch(options["--port"]) or not 1024 <= int(options["--port"]) <= 65535):
        return None, "--port takes a number from 1024 to 65535"
    return options, ""


def parse(argv: list[str]) -> dict | None:
    """The options, or None for a usage error."""
    return read_args(argv)[0]


def check_settings(options: dict) -> tuple[Settings | None, str]:
    """(settings, "") or (None, why): the settings the options name, each checked as text."""
    values: dict = {}
    if "--lang" in options:
        if options["--lang"] not in M.LANGS:
            return None, f"--lang takes {' or '.join(M.LANGS)}"
        values["lang"] = options["--lang"]
    if "--ledger" in options:
        if options["--ledger"] not in LEDGER_KINDS:
            return None, f"--ledger takes {', '.join(LEDGER_KINDS)}"
        values["ledger"] = options["--ledger"]
    if "--ledger-path" in options:
        if values.get("ledger", "auto") in ("auto", "none"):
            return None, "--ledger-path names the file of one format: add --ledger tasks or --ledger roadmap"
        if CONFIG.ledger_path(options["--ledger-path"]) is None:
            return None, "--ledger-path takes a plain path inside the repository (no .., drive, .git or device)"
        values["ledger_path"] = options["--ledger-path"]
    if "--main" in options:
        if CONFIG.branch(options["--main"]) is None:
            return None, "--main takes a branch name made of letters, digits and . _ / -"
        values["main"] = options["--main"]
    if "--remote" in options:
        if CONFIG.remote(options["--remote"]) is None:
            return None, "--remote takes a remote name made of letters, digits and . _ -"
        values["remote"] = options["--remote"]
    for flag in ("--worktrees", "--kept"):
        if any(CONFIG.folder(text) is None for text in options[flag]):
            return None, f"{flag} takes a plain folder inside the repository (no .., drive, .git or device)"
    folders = [CONFIG.folder(text) for text in options["--worktrees"]]
    values["worktrees"] = tuple(dict.fromkeys([*Settings().worktrees, *folders]))
    values["kept"] = tuple(dict.fromkeys("/".join(CONFIG.folder(text)) for text in options["--kept"]))
    roots = []
    for text in options.get("--worktrees-root", []):
        try:
            root = CONFIG.external_root(Path(text).expanduser())
        except (OSError, RuntimeError, ValueError):
            root = None
        if root is None:
            return None, "--worktrees-root takes an absolute local folder (no network, device, .. or .git)"
        roots.append(root)
    values["external_worktrees"] = tuple(dict.fromkeys(roots))
    for flag, name in NUMBERS.items():
        if flag in options:
            found = CONFIG.number(name, options[flag])
            if found is None:
                low, high = CONFIG.BOUNDS[name]
                return None, f"{flag} takes a number from {low} to {high}"
            values[name] = found
    settings = Settings(**values)
    if settings.recent_minutes <= settings.active_minutes:
        return None, "--recent-minutes must be more than --active-minutes"
    return settings, ""


def settings_of(options: dict) -> Settings | None:
    """The settings the options name, or None when one is refused."""
    return check_settings(options)[0]


# ---------------------------------------------------------------- the snapshot target

def cache_folder() -> Path:
    """The user's own cache folder for flightboard: never inside a repository the board reads."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
        root = Path(base) if base and Path(base).is_absolute() else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME", "")
        root = Path(base) if base and Path(base).is_absolute() else Path.home() / ".cache"
    return root / "flightboard"


def default_output(root: Path) -> Path:
    """<cache>/flightboard/<repository>-<8 hex>.html: one file per repository, the hash telling apart two folders of
    the same name."""
    name = root.name if FILES.SAFE_NAME.fullmatch(root.name) else "repository"
    digest = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:8]
    return cache_folder() / f"{name}-{digest}.html"


def _existing(path: Path) -> Path:
    """The deepest part of path that exists already."""
    current = path
    while not os.path.lexists(current) and current.parent != current:
        current = current.parent
    return current


def _key(path: Path) -> str:
    """A folder as text to compare: case folded where the system ignores it, a \\\\?\\ prefix dropped (resolve may
    keep one), no separator at the end."""
    key = os.path.normcase(str(path))
    if key.startswith("\\\\?\\") and not key.startswith("\\\\?\\unc\\"):
        key = key[4:]
    return key.rstrip("\\/")


def _inside(path: Path, root: Path) -> bool:
    """Whether the existing folder path is root or lies inside it: by text, then by identity, so that the same folder
    written another way (a \\\\?\\ prefix, a share or a mapped drive of it) is told too. A folder that cannot be looked
    at counts as inside: the safe side."""
    key, base = _key(path), _key(root)
    if key == base or key.startswith(base + os.sep):
        return True
    try:
        same = os.stat(root)
        return any(os.path.samestat(os.stat(part), same) for part in (path, *path.parents))
    except OSError:
        return True


def guarded_roots(checkout: Path, external_roots: tuple[Path, ...] = ()) -> tuple[Path, ...] | None:
    """The folders the snapshot never goes into: the checkout the page reads (resolved: looking at it follows
    nothing), when it holds its own git folder, so that the repository is that checkout and nothing else. None
    otherwise (a worktree the board does not read, a submodule, a checkout whose git folder lives elsewhere, an odd or
    empty .git, none at all): the board then reads nothing, cannot tell where the repository ends, and the page, an
    error page, may go only to the cache folder. Whatever a .git file names is never looked at."""
    return (checkout, *external_roots) if FILES.git_folder(checkout) else None


def target(wanted: Path, roots: tuple[Path, ...], create: bool) -> Path | None:
    """The file the snapshot is written to, its folder resolved: an .html file that is no device and no stream, in a
    folder outside the observed repository (each of roots) once every link on its way is resolved. With create, the
    folder is the cache folder: it is made only when what exists of its way lies outside the repository, and it may
    not itself be a link (one planted there could aim the snapshot anywhere). Otherwise the folder is the one the
    owner named with --output, and must exist. None when the file may not be written."""
    name = wanted.name
    if not name.lower().endswith(".html") or ":" in name or "\0" in str(wanted) \
            or name.split(".")[0].strip().upper() in FILES.RESERVED or name.startswith("."):
        return None
    folder = wanted.parent
    try:
        if create:
            if any(_inside(_existing(folder).resolve(), root) for root in roots):
                return None  # checked before anything is made: nothing is ever created inside the repository
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)  # its own folder: readable by its owner only
            if FILES.is_link(os.lstat(folder)):
                return None
        resolved = folder.resolve(strict=True)
    except (OSError, RuntimeError):  # Python 3.12 raises RuntimeError for a loop of links
        return None
    if not resolved.is_dir() or any(_inside(resolved, root) for root in roots):
        return None
    final = resolved / name
    try:
        if stat.S_ISDIR(os.lstat(final).st_mode):
            return None
    except FileNotFoundError:
        pass
    except OSError:
        return None
    return final


def write_once(output: Path, page: str) -> None:
    """Write the page whole or not at all, through a new file of its own: mkstemp makes a fresh one (never an
    existing file or link written through, and two snapshots at once never meet), readable by its owner only; then
    os.replace swaps it in, replacing a link at the target rather than writing through it."""
    handle, name = tempfile.mkstemp(dir=output.parent, prefix=output.name + ".", suffix=".partial")
    partial = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(page)
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)


# ---------------------------------------------------------------- the three modes

def resume_text(view: dict) -> str:
    """What waits for the owner, as a few lines: the page's first sentence and its list. Each line keeps only verbs,
    ids, names and counts: a quote or a title read in a branch stays on the page, never in a session's context."""
    lang = view.get("i18n", {}).get("lang", "en")
    lines = [view["resume"]]
    notes = [code for code in view["main"].get("note") or [] if code in RESUME_NOTES]
    if notes:  # what "main" means for this reading, in fixed words: no branch name read in the repository
        lines.append(M.say(lang, "resume.note", note=" · ".join(M.say(lang, "resume_note." + code) for code in notes)))
    if view["waiting"]:
        lines.append(M.say(lang, "resume.waiting"))
        lines += [M.say(lang, "resume.item", verb=item["verb"], safe=item["safe"]) for item in view["waiting"]]
        if view["waiting_more"]:
            lines.append(M.say(lang, "resume.more", n=view["waiting_more"]))
    if any(source["key"] == "files" for source in view["sources"]):  # fixed texts only: what the summary cannot see
        lines.append(M.say(lang, "resume.files"))
    if view.get("limits", {}).get("branches_unread"):  # a branch that waits for a merge go may be missing
        lines.append(M.say(lang, "resume.branches_unread"))
    if view["ledger"]["missing"]:
        lines.append(M.say(lang, "resume.missing", path=view["ledger"]["missing"]))
    elif view["ledger"]["kind"] != "none" and not view["main"]["valid"]:  # the validator's words stay on the page
        lines.append(M.say(lang, "resume.invalid", path=view["ledger"]["path"]))
    yours = view["yours"]
    if yours["decisions"] or yours["tasks"]:
        lines.append(M.say(lang, "resume.yours", decisions=M.count(lang, "resume.decisions", yours["decisions"]),
                           tasks=M.count(lang, "resume.tasks", yours["tasks"])))
    lines.append(M.say(lang, "resume.data"))
    return "\n".join(lines)


def _snapshot(root: Path, settings: Settings, options: dict, now: datetime) -> int:
    try:  # the collector finds the checkout once: every check of the target uses the very folder the page reads
        collector = Collector(root, settings)
    except Exception as exc:  # the last guard of the command
        print(f"snapshot impossible: {type(exc).__name__}", file=sys.stderr)
        return 1
    roots = guarded_roots(collector.root, settings.external_worktrees)
    wanted = Path(options["--output"]).expanduser() if "--output" in options else default_output(collector.root)
    if "--output" in options and not wanted.is_absolute():
        wanted = Path.cwd() / wanted
    if roots is None and "--output" in options:
        print("flightboard: --output needs a repository the board can read (its main checkout, or a worktree it "
              "reads); from here the snapshot goes only to the cache folder\n" + USAGE, file=sys.stderr)
        return 2
    roots = roots or (collector.root, *settings.external_worktrees)
    output = target(wanted, roots, create="--output" not in options)
    if output is None:
        print("flightboard: the snapshot is an .html file in an existing folder outside the repository (the cache "
              "folder may not be a link)\n" + USAGE, file=sys.stderr)
        return 2
    try:
        view = collector.snapshot(now, "snapshot")
        page = PAGE.render(view, PAGE.template())
        if target(output, roots, create=False) != output:
            raise OSError("the target changed while the page was made")
        write_once(output, page)
    except Exception as exc:  # the collector degrades on its own; this is the last guard of the command
        print(f"snapshot impossible: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "RENDERED", "page": str(output), "sessions": len(view["sessions"]),
                      "main": view["main"]["state"]}, ensure_ascii=True))
    return 0


def _resume(root: Path, settings: Settings, now: datetime) -> int:
    try:
        view = Collector(root, settings).snapshot(now, "snapshot")
    except Exception as exc:  # the collector degrades on its own; this is the last guard of the command
        print(f"summary impossible: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(resume_text(view))
    return 0


def _serve(root: Path, settings: Settings, port: int) -> int:
    try:
        servers = SERVER.make_servers(SERVER.Snapshots(Collector(root, settings)), PAGE.template(), port,
                                      settings.lang)
    except OSError:
        print(f"port {port} is busy or unavailable (127.0.0.1 or ::1): start again with --port N", file=sys.stderr)
        return 1
    print(json.dumps({"status": "SERVING", "url": f"http://{SERVER.HOST}:{port}/"}, ensure_ascii=True), flush=True)
    for extra in servers[1:]:
        threading.Thread(target=extra.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
    try:
        servers[0].serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.server_close()
    return 0


def main(argv: list[str], root: Path | None = None, now: datetime | None = None) -> int:
    options, problem = read_args(argv)
    settings, problem = check_settings(options) if options is not None else (None, problem)
    if options is None or settings is None:
        print(f"flightboard: {problem}\n{USAGE}", file=sys.stderr)
        return 2
    if "--help" in options or "-h" in options:
        print(USAGE + "\n\n" + (__doc__ or "").strip())
        return 0
    if "--version" in options:
        print(f"flightboard {__version__}")
        return 0
    if any(not FILES.local_root(path) for path in settings.external_worktrees):
        print("flightboard: --worktrees-root needs an existing plain local folder, without links or junctions\n"
              + USAGE, file=sys.stderr)
        return 2
    folder = Path(options["--repo"]).expanduser() if "--repo" in options else (root or Path.cwd())
    try:  # a folder inside the repository stands for the repository, for every check to come
        repo = FILES.top_folder(folder.resolve(strict=True))
    except (OSError, RuntimeError):  # Python 3.12 raises RuntimeError for a loop of links
        print(USAGE + "\n(--repo names no folder)", file=sys.stderr)
        return 2
    now = now or SERVER.now_local()
    if "--snapshot" in options:
        return _snapshot(repo, settings, options, now)
    if "--resume" in options:
        return _resume(repo, settings, now)
    return _serve(repo, settings, int(options.get("--port", DEFAULT_PORT)))
