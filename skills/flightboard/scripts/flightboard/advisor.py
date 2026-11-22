# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Optional, in-memory LLM advice. No collector, Git, shell, repository writes or implicit provider calls.

A local preview freezes the dossier. A separate consent sends those exact bytes. Optional monitoring authorizes
future versions of the same selected files for at most 24 hours and a fixed total number of attempted calls.
One worker may run, including after revocation until its bounded transport returns; its result is then discarded.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import threading
import time

from . import llm_context, llm_providers

AUTH_SECONDS = 24 * 60 * 60
PREVIEW_SECONDS = 10 * 60
MAX_ENVELOPE_BYTES = 196_608
VOLATILE = frozenset({"generated_at", "observed_at", "checked_at", "last_success_at"})


class AdvisorError(ValueError):
    """Fixed public error code; never a provider response, path exception or credential."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(context) -> str:
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in VOLATILE and not k.startswith("_")}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value
    return hashlib.sha256(_json(stable(context))).hexdigest()


class Advisor:
    def __init__(self, repo: Path | None, snapshot, *, provider=None, clock=time.monotonic, schedule=True,
                 refresh_snapshot=None):
        self.token = secrets.token_urlsafe(32)
        self._repo, self._snapshot = repo, snapshot
        self._refresh_snapshot = refresh_snapshot
        self._provider = provider or llm_providers.call_provider
        self._clock, self._schedule = clock, schedule
        self._condition = threading.Condition()
        self._state, self._generation = "disabled", 0
        self._preview = self._envelope = self._selection = self._result = None
        self._error = ""
        self._consumed = self._active = self._preparing = self._closed = False
        self._preview_until = self._result_until = 0.0
        self._auto = self._auto_key = self._last_fingerprint = None
        self._thread = self._scheduler = None

    def _available(self):
        if self._closed:
            raise AdvisorError("closed", 409)
        if self._active or self._preparing:
            raise AdvisorError("busy", 409)
        if self._auto and self._auto["enabled"]:
            raise AdvisorError("automatic_active", 409)

    def _expire(self):
        now = self._clock()
        if self._auto and self._auto["enabled"] and now >= self._auto["deadline"]:
            self._auto["enabled"] = False
            self._auto_key = None
        if not self._active and not (self._auto and self._auto["enabled"]):
            if self._preview is not None and now >= self._preview_until:
                self._preview = self._envelope = self._selection = None
                if self._state == "prepared":
                    self._state = "expired"
            if self._result is not None and now >= self._result_until:
                self._result = None
                self._state = "expired"

    def _context(self, repo_files, local_files, *, automatic=False):
        # Preview only captures. Explicit automatic consent may refresh once per interval, never overlap a scan.
        capture = self._refresh_snapshot if automatic and self._refresh_snapshot else self._snapshot
        board = capture()
        if (not isinstance(board, dict) or board.get("main", {}).get("state") != "ok"
                or board.get("main", {}).get("valid") is not True):
            raise AdvisorError("board_unavailable", 409)
        if self._repo is None and (repo_files or local_files):
            raise AdvisorError("repository_unavailable", 409)
        try:
            return llm_context.build_context(board, self._repo, repo_files, local_files)
        except (ValueError, OSError):
            raise AdvisorError("context_invalid") from None

    @staticmethod
    def _preflight(envelope):
        """Check the final provider encoding locally, before accepting consent or spending an attempt."""
        try:
            llm_providers.prepare_request(envelope["config"], envelope["question"], envelope["context"])
        except llm_providers.ProviderError as exc:
            raise AdvisorError("context_too_large" if exc.code == "context_too_large" else "context_invalid") from None

    def preview(self, request: dict) -> dict:
        if request.get("consent_board") is not True:
            raise AdvisorError("reading_consent_required")
        repo_files, local_files = request.get("repo_files", []), request.get("local_files", [])
        if (repo_files and request.get("consent_repo") is not True
                or local_files and request.get("consent_local") is not True):
            raise AdvisorError("reading_consent_required")
        question = request.get("question")
        if not isinstance(question, str) or not question.strip() or len(question) > 4000 or "\0" in question:
            raise AdvisorError("question_invalid")
        try:
            config = llm_providers.validate_config(request.get("config"))
        except (ValueError, TypeError):
            raise AdvisorError("configuration_invalid") from None
        with self._condition:
            self._expire()
            self._available()
            self._generation += 1
            generation = self._generation
            self._preparing = True
            self._preview = self._envelope = self._selection = self._result = None
            self._state, self._error = "disabled", ""
        try:
            context = self._context(repo_files, local_files)
            envelope = _json({"config": config, "question": question, "context": context})
            if len(envelope) > MAX_ENVELOPE_BYTES:
                raise AdvisorError("context_too_large")
            self._preflight({"config": config, "question": question, "context": context})
            at = datetime.now(timezone.utc)
            preview = {"id": secrets.token_urlsafe(24), "sha256": hashlib.sha256(envelope).hexdigest(),
                       "config": config, "question": question, "context": context, "bytes": len(envelope),
                       "created_at": at.isoformat(), "expires_at": (at + timedelta(seconds=PREVIEW_SECONDS)).isoformat()}
            with self._condition:
                if generation != self._generation or self._closed:
                    raise AdvisorError("revoked", 409)
                self._preview, self._envelope = preview, envelope
                self._selection = (tuple(repo_files), tuple(local_files))
                self._preview_until = self._clock() + PREVIEW_SECONDS
                self._consumed, self._state = False, "prepared"
                return {"state": "prepared", "preview": copy.deepcopy(preview)}
        finally:
            with self._condition:
                self._preparing = False
                self._condition.notify_all()

    def _approved(self, request):
        self._expire()
        self._available()
        if request.get("consent_send") is not True:
            raise AdvisorError("sharing_consent_required")
        if self._preview is None or self._consumed:
            raise AdvisorError("preview_required", 409)
        for key, expected in (("preview_id", self._preview["id"]), ("sha256", self._preview["sha256"])):
            value = request.get(key)
            if not isinstance(value, str) or not hmac.compare_digest(value, expected):
                raise AdvisorError("preview_changed", 409)
        key = request.get("api_key", "")
        if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise AdvisorError("key_invalid")
        if not key and not self._preview["config"]["endpoint"].startswith("http://"):
            raise AdvisorError("key_required")
        return key, json.loads(self._envelope)

    def analyze(self, request: dict) -> dict:
        with self._condition:
            key, envelope = self._approved(request)
            self._consumed = True
            self._dispatch(key, envelope)
            return {"state": self._state, "job_id": self._job_id}

    def automate(self, request: dict) -> dict:
        if request.get("consent_automatic") is not True:
            raise AdvisorError("automatic_consent_required")
        interval, maximum = request.get("interval_minutes"), request.get("max_calls")
        if type(interval) is not int or not 15 <= interval <= 1440 or type(maximum) is not int or not 1 <= maximum <= 20:
            raise AdvisorError("automatic_limit_invalid")
        with self._condition:
            key, envelope = self._approved(request)
            now, at = self._clock(), datetime.now(timezone.utc)
            self._auto = {"enabled": True, "used": 0, "max_calls": maximum, "interval_minutes": interval,
                          "deadline": now + AUTH_SECONDS, "next_check": now + interval * 60,
                          "expires_at": (at + timedelta(seconds=AUTH_SECONDS)).isoformat(),
                          "next_check_at": (at + timedelta(minutes=interval)).isoformat(),
                          "config": envelope["config"], "question": envelope["question"],
                          "selection": self._selection}
            self._auto_key, self._consumed = key, True
            self._last_fingerprint = _fingerprint(envelope["context"])
            if self._schedule and self._scheduler is None:
                self._scheduler = threading.Thread(target=self._schedule_loop, name="flightboard-advisor-schedule",
                                                   daemon=True)
                try:
                    self._scheduler.start()
                except RuntimeError:
                    self._scheduler = self._auto_key = None
                    self._auto = {**self._auto_status(), "enabled": False}
                    self._state, self._error = "error", "automatic_schedule_failed"
                    raise AdvisorError("automatic_schedule_failed", 503) from None
            self._dispatch(key, envelope)
            self._condition.notify_all()
            return {"state": self._state, "job_id": self._job_id, "automatic": self._auto_status()}

    def _auto_status(self):
        if self._auto is None:
            return {"enabled": False}
        return {**{k: self._auto[k] for k in ("enabled", "used", "max_calls", "interval_minutes", "expires_at",
                                             "next_check_at")},
                "remaining": max(0, self._auto["max_calls"] - self._auto["used"])}

    def _dispatch(self, key, envelope):
        # Caller owns the condition; marking active precedes thread creation, so concurrent requests cannot queue work.
        automatic_deadline = None
        if self._auto and self._auto["enabled"]:
            automatic_deadline = self._auto["deadline"]
            self._auto["used"] += 1  # attempts, including provider errors, consume the agreed total cap
            if self._auto["used"] >= self._auto["max_calls"]:
                self._auto["enabled"], self._auto_key = False, None
        self._active, self._state, self._error, self._result = True, "running", "", None
        self._job_id = secrets.token_urlsafe(18)
        self._thread = threading.Thread(target=self._run, args=(self._generation, key, envelope, automatic_deadline),
                                        name="flightboard-advisor", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None  # an unstarted Thread retains its secret args until this reference is dropped
            self._auto_key = None
            if self._auto:
                self._auto = {**self._auto_status(), "enabled": False}
            self._active, self._state, self._error = False, "error", "provider_failed"
            self._condition.notify_all()

    def _run(self, generation, key, envelope, automatic_deadline=None):
        with self._condition:
            expired = automatic_deadline is not None and self._clock() >= automatic_deadline
            if generation != self._generation or self._closed or expired:
                key = None
                self._active = False
                if expired and generation == self._generation and not self._closed:
                    self._expire()
                    self._auto_key = None
                    self._state, self._error = "expired", ""
                self._condition.notify_all()
                return  # revocation before worker entry is not an already-started provider call
        started, result, error = time.monotonic(), None, ""
        try:
            response = self._provider(envelope["config"], key, envelope["question"], envelope["context"])
            text = response.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > 131072:
                raise ValueError("invalid provider response")
            usage = response.get("usage", {})
            usage = {k: v for k, v in usage.items() if k in ("input_tokens", "output_tokens")
                     and type(v) is int and v >= 0}
            result = {"text": text, "usage": usage, "elapsed_seconds": round(time.monotonic() - started, 3),
                      "config": envelope["config"], "observed_at": envelope["context"].get("board", {}).get("generated_at", ""),
                      "context_sha256": _fingerprint(envelope["context"]),
                      "completed_at": datetime.now(timezone.utc).isoformat(), "job_id": self._job_id}
        except Exception:
            error = "provider_failed"  # neither request headers nor provider error bodies are reflected
        finally:
            key = None
            with self._condition:
                self._active = False
                if generation == self._generation and not self._closed:
                    self._result, self._error = result, error
                    self._result_until = self._clock() + AUTH_SECONDS
                    self._state = "error" if error else "complete"
                self._condition.notify_all()

    def check_automatic(self):
        with self._condition:
            self._expire()
            auto = self._auto
            if self._closed or not auto or not auto["enabled"] or self._active or self._preparing:
                return
            if self._clock() < auto["next_check"]:
                return
            auto["next_check"] = self._clock() + auto["interval_minutes"] * 60
            auto["next_check_at"] = (datetime.now(timezone.utc) + timedelta(minutes=auto["interval_minutes"])).isoformat()
            generation, key = self._generation, self._auto_key
            repo_files, local_files = auto["selection"]
            config, question = copy.deepcopy(auto["config"]), auto["question"]
            self._preparing = True
        try:
            context = self._context(list(repo_files), list(local_files), automatic=True)
            fingerprint = _fingerprint(context)
            with self._condition:
                self._expire()
                if generation != self._generation or not self._auto or not self._auto["enabled"] or self._closed:
                    return
                if self._error == "automatic_context_unavailable":
                    self._error = ""
                if fingerprint != self._last_fingerprint:
                    envelope = {"config": config, "question": question, "context": context}
                    if len(_json(envelope)) > MAX_ENVELOPE_BYTES:
                        raise AdvisorError("context_too_large")
                    self._preflight(envelope)
                    self._last_fingerprint = fingerprint
                    self._dispatch(key, envelope)
        except (AdvisorError, OSError, ValueError):
            # A missed/unavailable reading is not a provider call and is not retried before the next full interval.
            with self._condition:
                if generation == self._generation:
                    self._error = "automatic_context_unavailable"
        finally:
            key = None
            with self._condition:
                self._preparing = False
                self._condition.notify_all()

    def _schedule_loop(self):
        while True:
            with self._condition:
                if self._closed:
                    return
                self._expire()
                if not self._auto or not self._auto["enabled"]:
                    self._condition.wait()
                    continue
                delay = self._auto["next_check"] - self._clock()
                if delay > 0 or self._active or self._preparing:
                    self._condition.wait(timeout=max(0.1, min(60.0, delay)) if delay > 0 else 1.0)
                    continue
            self.check_automatic()

    def status(self):
        with self._condition:
            self._expire()
            value = {"state": self._state, "automatic": self._auto_status()}
            if self._auto and self._auto["enabled"]:
                repo_files, local_files = self._auto["selection"]
                value["authorization"] = {"config": copy.deepcopy(self._auto["config"]),
                                          "question": self._auto["question"],
                                          "repo_files": list(repo_files), "local_files": list(local_files)}
            if self._error:
                value["error"] = self._error
            if self._result is not None:
                value["result"] = copy.deepcopy(self._result)
            if self._preview is not None:
                value["preview"] = {k: copy.deepcopy(v) for k, v in self._preview.items() if k != "context"}
            return value

    def revoke(self):
        with self._condition:
            self._generation += 1
            self._preview = self._envelope = self._selection = self._result = self._auto_key = None
            if self._auto:
                # Keep only non-sensitive counters for the UI, not the question or file selection.
                self._auto = {**self._auto_status(), "enabled": False}
            self._state, self._error = "revoked", ""
            self._condition.notify_all()
            return {"state": "revoked", "automatic": self._auto_status()}

    def wait_idle(self, timeout=1.0):
        """Bounded test/close observation; never used by state.json or page refresh."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._active and not self._preparing, timeout=timeout)

    def close(self):
        self.revoke()
        with self._condition:
            self._closed = True
            self._condition.notify_all()
