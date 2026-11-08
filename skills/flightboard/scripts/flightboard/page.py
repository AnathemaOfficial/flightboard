# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""The page: the view as JSON in the template's data block, and the security policy that lets only the page's own
script run, named by its SHA-256. "<" and the Unicode line separators are escaped, so no source text can close the
data block or start a comment in it; the data block is not a script. Standard library only, safe under -I.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().with_name("template.html")
PLACEHOLDER = "__FLIGHTBOARD_JSON__"
SCRIPT_HASH = "__SCRIPT_HASH__"
CODE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)
PAGE_POLICY = ("default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; connect-src 'self'; "
               "base-uri 'none'; form-action 'none'; require-trusted-types-for 'script'; trusted-types 'none'; "
               "frame-ancestors 'none'")
DATA_POLICY = "default-src 'none'; frame-ancestors 'none'; sandbox"


def script_digest(template: str) -> str:
    scripts = CODE_SCRIPT.findall(template)
    if len(scripts) != 1:
        raise ValueError("the template must hold exactly one code script")
    return base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode("ascii")


def embed(view: dict, template: str, placeholder: str = PLACEHOLDER) -> str:
    """The template with the view as JSON; a value JSON cannot hold (NaN, infinity) is an error, never sent."""
    for marker in (placeholder, SCRIPT_HASH):
        if template.count(marker) != 1:
            raise ValueError(f"the template must hold {marker} exactly once")
    digest = script_digest(template)
    data = json.dumps(view, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return template.replace(SCRIPT_HASH, f"sha256-{digest}").replace(placeholder, data)


def render(view: dict, template: str) -> str:
    """The page with the view as JSON: no source text can leave its block."""
    return embed(view, template)


def policy(template: str) -> str:
    """The security policy the server sends with the page: its own script, its own requests, no frame."""
    return PAGE_POLICY.format(digest=script_digest(template))


def state_json(view: dict) -> bytes:
    """The state as strict JSON: a value JSON cannot hold (NaN, infinity) is an error, never sent."""
    return json.dumps(view, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")
