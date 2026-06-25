# Author: Stian Skogbrott
# License: Apache-2.0
"""Check import hygiene for REMORA scripts and modules used in CI and local validation."""
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

for mod, cls in checks:
    try:
        m = __import__(mod, fromlist=[cls])
        getattr(m, cls)
        print(f"OK   {mod}.{cls}")
    except Exception as e:
        print(f"FAIL {mod}.{cls} -- {e}")
