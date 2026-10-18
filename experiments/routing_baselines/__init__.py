# SPDX-License-Identifier: BUSL-1.1
"""SAP v7 Q7 harness: external baselines on BFCL v4 multi-turn (§14, PRF-011).

``pins`` holds the gorilla commit and file hashes of §14.2, ``split`` draws
the development/test split of §14.3 and releases test-split content only
against a locked manifest, ``labels`` is the frozen label matcher of §14.4,
``trajectory`` drives the ungated agent K1/K2, and ``arms`` holds CONTROL,
ALLOW, N1, the LLM judge J (and J-τ, J2), the Invariant Guardrails arm IG
and the REMORA arms R and R-strict. ``scripts/run_routing_baselines.py`` is
the runner.

Nothing here has been run on BFCL data. The runner refuses until the
study's manifest is locked (§15.1); no manifest exists.
"""
