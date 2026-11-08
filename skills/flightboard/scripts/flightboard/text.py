# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Text read in the repository is data: cleaned before it is shown, matched against strict patterns before it is
trusted as a name, and never turned into markup. Standard library only."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
UNUSUAL_BRANCH = "(unusual branch name)"
_BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,100}")
# Characters that render as nothing (or a blank box) without being of Unicode category C.
_INVISIBLE_RANGES = ((0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180D), (0x180F, 0x180F),
                     (0x2800, 0x2800), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xFFFC, 0xFFFC),
                     (0xE0100, 0xE01EF))
_INVISIBLE = re.compile("[" + "".join(chr(low) if low == high else f"{chr(low)}-{chr(high)}"
                                      for low, high in _INVISIBLE_RANGES) + "]")


def clean(value: object, limit: int = 200) -> str:
    """Text safe to show: control, format (bidi, zero-width), private and unassigned characters become spaces,
    spaces collapse, and the text is cut at limit."""
    if value is None:
        return ""
    raw = _INVISIBLE.sub(" ", str(value)[:limit * 4 + 64])  # a huge text is cut before the slow pass
    visible = "".join(" " if unicodedata.category(char).startswith("C") else char for char in raw)
    return " ".join(visible.split())[:limit]


def safe_branch(value: object) -> str:
    """A branch name made of safe characters, or a fixed placeholder."""
    return value if isinstance(value, str) and _BRANCH.fullmatch(value) else UNUSUAL_BRANCH


def instant(when: datetime | None) -> float:
    """Seconds since 1970, to sort times given in different zones; a time without a zone counts as UTC, and a missing
    or unusable one sorts last. Never raises, even for the years 1 or 9999."""
    if when is None:
        return float("-inf")
    try:
        return ((when if when.tzinfo else when.replace(tzinfo=timezone.utc)) - EPOCH).total_seconds()
    except (OverflowError, ValueError):
        return float("-inf")


def parse_time(value: object) -> datetime | None:
    """An ISO date and time ("Z" accepted), or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso(seconds: int | float, zone) -> str:
    """An instant as ISO text; "" for a date the platform cannot hold (a hostile year 9999 commit, say)."""
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).astimezone(zone).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return ""
