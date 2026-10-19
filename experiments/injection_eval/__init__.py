# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 Q6 harness: InjecAgent through REMORA's enforcing path (§13, PRF-042).

``pins`` holds the upstream commit and file hashes of §13.2, ``builder``
turns a verified InjecAgent checkout into attacked cases and benign
controls, ``upstream`` loads InjecAgent's own prompt and evaluator from that
checkout at run time, ``agent`` generates proposals through a budgeted model
client, and ``arms`` applies A0, B0, P and the REMORA arms to the logged
proposals. ``scripts/run_injection_eval.py`` is the runner.

Nothing here has been run on InjecAgent data. The runner refuses until the
study's manifest is locked (§15.1); no manifest exists.
"""
