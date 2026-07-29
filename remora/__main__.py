# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""PATH-free CLI entry point: ``python -m remora <command>``.

The console script ``remora`` (declared in ``[project.scripts]``) is installed
into a ``Scripts`` directory that is frequently absent from ``PATH`` — notably
on Windows, where ``pip`` prints a "script remora.exe … is not on PATH"
warning. ``python -m remora`` needs no PATH changes and dispatches to the same
``remora.cli:main`` as the console script.
"""
from remora.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
