# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""flightboard: a read-only board of your parallel coding-agent sessions, what each one changed in your roadmap, and
what waits for you.

It reads one git repository, its worktrees and its unmerged branches, never runs a program the repository names, never
follows a link, and serves one page on this computer's loopback only. Standard library only, safe under -I; the entry
point is ../flightboard.py.
"""
from __future__ import annotations

__version__ = "0.1.1"
TOOL = {"name": "flightboard", "version": __version__}
