# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Check import hygiene for REMORA scripts and modules used in CI and local validation.

Exits non-zero on any failed import — self-review 2026-07-28 found this gate
printed FAIL lines but always exited 0, making the `make audit` line
decorative.
"""
import sys

checks = [
    ("remora.cascade", "CascadeEngine"),
    ("remora.oracles.groq", "GroqOracle"),
    ("remora.oracles.openrouter", "OpenRouterOracle"),
    ("remora.genome", "Genome"),
    ("remora.selective.guardrail", "ConformalPhaseGuardrail"),
    ("remora.policy.decision_engine", "RemoraDecisionEngine"),
    ("remora.thermodynamics", "ThermodynamicState"),
    ("remora.engine", "Remora"),
    ("remora.agent_hook.lyapunov_tracker", "LyapunovTracker"),
    ("remora.cascade.stages", "FastGate"),
    ("remora.cascade.stages", "ConsensusGate"),
    ("remora.cascade.stages", "VerifierGate"),
]

failures = 0
for mod, cls in checks:
    try:
        m = __import__(mod, fromlist=[cls])
        getattr(m, cls)
        print(f"OK   {mod}.{cls}")
    except Exception as e:
        failures += 1
        print(f"FAIL {mod}.{cls} -- {e}")

if failures:
    print(f"[FAIL] {failures} import check(s) failed")
    sys.exit(1)
print("[PASS] All core module imports resolve")
