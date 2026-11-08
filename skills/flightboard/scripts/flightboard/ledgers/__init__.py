# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Ledger adapters: none (git only), a simple task file (tasks.toml or JSON), and the roadmap ledger (schema 2).

auto picks the first of AUTO that main holds; a repository without any gets the git-only view. Every adapter is code of
flightboard: nothing is ever loaded or run from the observed repository. Standard library only, safe under -I.
"""
from __future__ import annotations

from .base import GOVERNED, PROGRESS, SATISFIED, STATUSES, Ledger, safe_path
from .roadmap import RoadmapLedger
from .tasks import TasksLedger

KINDS = ("auto", "none", "tasks", "roadmap")
DEFAULT_PATHS = {"roadmap": "data/roadmap.json", "tasks": "tasks.toml"}
AUTO = (("roadmap", "data/roadmap.json"), ("tasks", "tasks.toml"), ("tasks", "tasks.json"))

__all__ = ["AUTO", "DEFAULT_PATHS", "GOVERNED", "KINDS", "PROGRESS", "SATISFIED", "STATUSES", "Ledger", "make",
           "safe_path"]


def make(kind: str, path: str | None = None) -> Ledger | None:
    """The adapter of a kind, reading path (or the kind's default path); None for the git-only view."""
    if kind == "none":
        return None
    if kind == "roadmap":
        return RoadmapLedger(path or DEFAULT_PATHS["roadmap"])
    if kind == "tasks":
        return TasksLedger(path or DEFAULT_PATHS["tasks"])
    raise ValueError(f"unknown ledger kind: {kind}")
