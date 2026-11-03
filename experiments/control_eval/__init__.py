# SPDX-License-Identifier: BUSL-1.1
"""Control evaluation harness for SAP v7 (docs/assurance/statistical_analysis_plan_v7_control_eval.md).

The defences, the REMORA adapter and the statistics here do not import
AgentDojo, so they are tested in CI. ``agentdojo_glue`` holds the thin layer
that plugs a defence into an AgentDojo pipeline; it needs the pinned packages
in ``requirements.txt`` and runs only from ``scripts/run_control_eval.py``.

Gate G2 adds the paid-run harness, also tested without AgentDojo:
``spend_ledger`` (reserve-before-spend, append-only, one cap across pilot and
test), ``response_cache`` (shared responses across paired arms), ``gateway``
(the only path to a model, and arm D's monitor), ``claude_messages`` (the
agent's requests for the current Claude models), ``run_config``, ``arms``
(the arm registry), ``sealed_run`` and ``readiness`` (gates G0 to G6).
``study_runner`` imports AgentDojo and drives ``--pilot`` and ``--test``.
"""
