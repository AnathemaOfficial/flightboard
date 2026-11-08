#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Technologies CoreXalt Inc.
"""flightboard: a read-only board of your parallel coding-agent sessions.

Run it from a git repository (or name one with --repo), with the Python standard library alone, isolated:

    python3 -I -B flightboard.py              serve the live page on http://127.0.0.1:8790/
    python3 -I -B flightboard.py --resume     print the summary and what waits for you
    python3 -I -B flightboard.py --snapshot   write the page once, in your cache folder

--help lists every option. Under -I the folder of this script is not on sys.path: the package next to it is loaded by
its path, and nothing else is.
"""
import importlib
import importlib.util
import sys
from pathlib import Path


def load():
    """The flightboard package next to this file, loaded by its path."""
    package = Path(__file__).resolve().parent / "flightboard"
    found = sys.modules.get("flightboard")
    if found is not None and list(getattr(found, "__path__", [])) == [str(package)]:
        return found
    spec = importlib.util.spec_from_file_location("flightboard", package / "__init__.py",
                                                  submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise ImportError("flightboard package not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules["flightboard"] = module
    spec.loader.exec_module(module)
    return module


def main():
    if sys.version_info < (3, 12):
        sys.stderr.write("flightboard needs Python 3.12 or newer\n")
        return 2
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    load()
    cli = importlib.import_module("flightboard.cli")
    return cli.main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
