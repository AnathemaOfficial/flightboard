#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""Opt-in Windows startup of Flightboard dashboards; run with -I -B."""
import importlib
import importlib.util
from pathlib import Path
import sys


def main() -> int:
    if sys.version_info < (3, 12):
        if sys.stderr:
            sys.stderr.write("flightboard needs Python 3.12 or newer\n")
        return 2
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    package = Path(__file__).resolve().parent / "flightboard"
    spec = importlib.util.spec_from_file_location("flightboard", package / "__init__.py",
                                                 submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise ImportError("flightboard package not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules["flightboard"] = module
    spec.loader.exec_module(module)
    return importlib.import_module("flightboard.windows_startup").main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
