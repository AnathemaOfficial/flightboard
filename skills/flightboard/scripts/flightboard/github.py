# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Opt-in, bounded GitHub observations independent of the local Git reading budget.

Only an explicit live-board option enables this worker. It uses existing gh authentication,
issues fixed GET requests and never fetches objects or writes anything in an observed repo.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import processes
from .gitreads import ENV_KEYS, FULL_SHA, is_ref
from .text import clean

TTL = 300.0
REQUEST_TIMEOUT = 8.0
CHAIN_TIMEOUT = 20.0
MAX_PAGES = 5
MAX_RESPONSE_BYTES = 4_000_000
MAX_TOTAL_BYTES = 8_000_000
PAGE_SIZE = 100
OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
REPOSITORY = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
IDENTITY = re.compile(rf"({OWNER})/({REPOSITORY})")
REMOTE = re.compile(rf"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                    rf"({OWNER})/({REPOSITORY})")
AUTH_ENV = frozenset({"GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "XDG_CONFIG_HOME", "HTTPS_PROXY",
                      "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR"})


class ObservationError(ValueError):
    """A bounded observation did not establish complete, valid remote facts."""


def _identity(value: object) -> str:
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        return ""
    owner, repository = value.split("/")
    return value if not repository.endswith(".") and ".." not in repository else ""


def repository_identity(remote_url: object) -> str:
    """A plain GitHub owner/repository from common HTTPS/SSH URLs, or an empty string.

    No URL parser normalization, credential-bearing HTTPS, query, helper, port, encoded
    separator, trailing slash or alternate host can become an authorized API endpoint.
    """
    if not isinstance(remote_url, str) or len(remote_url) > 250:
        return ""
    match = REMOTE.fullmatch(remote_url)
    if match is None:
        return ""
    owner, repository = match.groups()
    if repository.endswith(".git"):
        repository = repository[:-4]
    return _identity(f"{owner}/{repository}")


def _executable() -> str | None:
    """Use only an executable in an absolute local PATH entry, never the current folder."""
    name = "gh.exe" if os.name == "nt" else "gh"
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or entry.startswith(("//", "\\\\")) or not Path(entry).is_absolute():
            continue
        candidate = Path(entry) / name
        try:
            if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                resolved = candidate.resolve(strict=True)
                if not str(resolved).startswith(("//", "\\\\")):
                    return str(resolved)
        except (OSError, RuntimeError):
            continue
    return None


class GhClient:
    """Fixed-host GET client; subprocess output, time and environment are bounded."""

    def __init__(self, *, runner=None, executable: str | None = None) -> None:
        self._runner = processes.run if runner is None else runner
        self._executable = executable

    def get(self, endpoint: str, *, timeout: float, limit: int) -> bytes:
        if not re.fullmatch(rf"repos/{OWNER}/{REPOSITORY}(?:/(?:branches|pulls)\?"
                            rf"(?:state=open&)?per_page=100&page=[1-9][0-9]*)?", endpoint):
            raise ObservationError("endpoint_refused")
        program = self._executable or _executable()
        if program is None:
            raise ObservationError("gh_unavailable")
        env = {key: value for key, value in os.environ.items() if key.upper() in ENV_KEYS | AUTH_ENV}
        env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="", PAGER="",
                   GH_NO_UPDATE_NOTIFIER="1", GH_NO_EXTENSION_UPDATE_NOTIFIER="1", NO_COLOR="1")
        command = [program, "api", "--hostname", "github.com", "--method", "GET",
                   "-H", "Accept: application/vnd.github+json", endpoint]
        try:
            code, output, _, over = self._runner(command, env=env, cwd=str(Path(program).parent), stdin=None,
                                                timeout=min(REQUEST_TIMEOUT, timeout), limit=limit, grace=0.25)
        except (OSError, ValueError) as exc:
            raise ObservationError("request_failed") from exc
        if over or len(output) > limit:
            raise ObservationError("output_limit")
        if code is None:
            raise ObservationError("request_timeout")
        if code != 0:
            raise ObservationError("request_failed")
        return output


def _empty(state: str, identity: str = "", error: str = "") -> dict:
    return {"source": "github", "state": state, "repository": identity, "checked_at": None, "last_success_at": None,
            "complete": False, "heads": {}, "pull_requests": [], "error": error}


def _branch(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1000 or not is_ref("refs/heads/" + value):
        raise ObservationError("invalid_branch")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or FULL_SHA.fullmatch(value) is None:
        raise ObservationError("invalid_commit")
    return value


class GitHubObserver:
    """One worker and one active request chain; current() never waits for network or Git.

    The injected client only needs get(endpoint, timeout=..., limit=...) -> bytes.
    Monotonic time controls expiration; wall-clock values are descriptive timestamps.
    """

    def __init__(self, enabled: bool = True, *, client=None, clock=time.monotonic,
                 now=None, ttl: float = TTL) -> None:
        if type(enabled) is not bool or type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("invalid observer settings")
        self._enabled = enabled
        self._client = GhClient() if client is None else client
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._ttl = ttl
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._identity = ""
        self._generation = 0
        self._next_at = 0.0
        self._success_at: float | None = None
        self._value = _empty("pending" if enabled else "disabled")
        self._worker = None
        if enabled:
            self._worker = threading.Thread(target=self._run, name="flightboard-github", daemon=True)
            self._worker.start()

    def current(self, identity: str) -> dict:
        with self._lock:
            if not self._enabled or self._closed:
                return _empty("disabled")
            checked = _identity(identity)
            if checked != self._identity:
                self._identity = checked
                self._generation += 1
                self._success_at = None
                self._next_at = 0.0
                self._value = _empty("pending", checked)
                self._wake.set()
            if not checked:
                return _empty("error", error="repository_identity_unavailable")
            value = copy.deepcopy(self._value)
            if self._success_at is not None and self._clock() - self._success_at >= self._ttl:
                value["state"] = "stale"
            if self._clock() >= self._next_at:
                self._wake.set()
            return value

    def close(self) -> None:
        """Stop scheduling and allow at most one bounded active subprocess to finish."""
        with self._lock:
            self._closed = True
            self._generation += 1
            self._wake.set()
        if self._worker is not None and self._worker is not threading.current_thread():
            self._worker.join(REQUEST_TIMEOUT + 1.0)

    def _read(self, identity: str, generation: int) -> dict:
        deadline, spent = self._clock() + CHAIN_TIMEOUT, 0

        def get(endpoint: str):
            nonlocal spent
            with self._lock:
                if self._closed or generation != self._generation or identity != self._identity:
                    raise ObservationError("observation_cancelled")
            remaining = deadline - self._clock()
            if remaining <= 0 or spent >= MAX_TOTAL_BYTES:
                raise ObservationError("observation_limit")
            limit = min(MAX_RESPONSE_BYTES, MAX_TOTAL_BYTES - spent)
            raw = self._client.get(endpoint, timeout=min(REQUEST_TIMEOUT, remaining), limit=limit)
            if not isinstance(raw, bytes) or len(raw) > limit:
                raise ObservationError("output_limit")
            spent += len(raw)
            if self._clock() > deadline:
                raise ObservationError("observation_timeout")
            try:
                return json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise ObservationError("invalid_response") from exc

        metadata = get(f"repos/{identity}")
        if not isinstance(metadata, dict) or not _identity(metadata.get("full_name")) \
                or metadata["full_name"].casefold() != identity.casefold() \
                or type(metadata.get("id")) is not int or metadata["id"] <= 0:
            raise ObservationError("repository_identity_mismatch")

        def pages(resource: str) -> tuple[list, bool]:
            result = []
            query = "state=open&" if resource == "pulls" else ""
            for page in range(1, MAX_PAGES + 1):
                entries = get(f"repos/{identity}/{resource}?{query}per_page={PAGE_SIZE}&page={page}")
                if not isinstance(entries, list) or len(entries) > PAGE_SIZE:
                    raise ObservationError("invalid_response")
                result.extend(entries)
                if len(entries) < PAGE_SIZE:
                    return result, True
            return result, False

        branches, heads_complete = pages("branches")
        heads = {}
        for item in branches:
            if not isinstance(item, dict) or not isinstance(item.get("commit"), dict):
                raise ObservationError("invalid_branch")
            branch, sha = _branch(item.get("name")), _sha(item["commit"].get("sha"))
            if branch in heads:
                raise ObservationError("remote_changed_during_read")
            heads[branch] = sha
        pulls, pulls_complete = pages("pulls")
        requests = []
        seen = set()
        for item in pulls:
            if not isinstance(item, dict) or type(item.get("number")) is not int \
                    or not 0 < item["number"] <= 2_147_483_647 or item.get("state") != "open" \
                    or not isinstance(item.get("head"), dict) or not isinstance(item.get("base"), dict) \
                    or not isinstance(item.get("title"), str):
                raise ObservationError("invalid_pull_request")
            number, head, base = item["number"], item["head"], item["base"]
            url = f"https://github.com/{metadata['full_name']}/pull/{number}"
            base_repo = base.get("repo")
            if item.get("html_url") != url or not isinstance(base_repo, dict) \
                    or not isinstance(base_repo.get("full_name"), str) \
                    or base_repo["full_name"].casefold() != identity.casefold() or number in seen:
                raise ObservationError("invalid_pull_request")
            seen.add(number)
            requests.append({"number": number, "title": clean(item["title"]), "url": url,
                             "head": _branch(head.get("ref")), "base": _branch(base.get("ref")),
                             "head_sha": _sha(head.get("sha"))})
        complete = heads_complete and pulls_complete
        return {"heads": heads, "pull_requests": requests, "complete": complete,
                "repository_id": metadata["id"], "default_branch": _branch(metadata["default_branch"])
                if metadata.get("default_branch") is not None else "",
                "state": "fresh" if complete else "partial", "error": "" if complete else "pagination_limit"}

    def _run(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return
                identity, generation = self._identity, self._generation
                delay = max(0.0, self._next_at - self._clock()) if identity else None
                self._wake.clear()
            if not identity or delay:
                self._wake.wait(delay)
                continue
            try:
                result, failure = self._read(identity, generation), ""
            except Exception as exc:  # remote/process errors never terminate the worker or reach local reads
                result = None
                failure = str(exc) if isinstance(exc, ObservationError) else "observation_failed"
            observed = self._now().isoformat(timespec="seconds")
            with self._lock:
                if self._closed:
                    return
                if generation != self._generation or identity != self._identity:
                    continue
                self._next_at = self._clock() + self._ttl
                if result is not None:
                    self._success_at = self._clock()
                    self._value = {**_empty(result["state"], identity), **result,
                                   "checked_at": observed, "last_success_at": observed}
                else:
                    self._value = {**self._value, "checked_at": observed, "error": failure,
                                   "state": "stale" if self._success_at is not None else "error"}
