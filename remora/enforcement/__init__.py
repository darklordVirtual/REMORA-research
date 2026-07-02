# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA Policy Enforcement Point (PEP) package.

ARCHITECTURAL BOUNDARY (REM-013):
  PDP = remora.policy.decision_engine.RemoraDecisionEngine (produces signed tokens)
  PEP = remora.enforcement.gate.EnforcementGate (verifies tokens, blocks execution)

The PEP must NEVER call the PDP directly. It receives a signed PolicyDecisionToken
from the API or orchestrator layer and verifies the HMAC signature before
allowing action execution. Without a valid signed token (in strict mode),
the PEP fails closed.

Deployment pattern:
    1. API/orchestrator calls PDP: report = engine.decide(obs)
    2. API/orchestrator issues token: token = PolicyDecisionToken.issue(
           action=report.action.value,
           observation_hash=_hash_observation(obs),
           request_id=req_id,
           issued_at=utc_now_str,
       )
    3. Token passed to PEP layer (may cross process/network boundary)
    4. PEP verifies and enforces: gate.enforce(token, execute_fn)

INTEGRATION STATUS: this package is a library plus its test suite
(tests/test_rem013_pdp_pep_boundary.py); no runtime component in this repo
issues or verifies tokens yet. The deployment pattern above is prescriptive,
not a description of current wiring — actual runtime blocking happens in
remora/adapters/action_gate.py, which calls the PDP directly. This is
consistent with deployment_status=SHADOW_ONLY (ARCHITECTURE.md §10); do not
cite this package as evidence of integrated enforcement.

See docs/assurance/remediation_register.yaml REM-013.
"""
from remora.enforcement.gate import EnforcementGate, EnforcementResult
from remora.enforcement.token import (
    PolicyDecisionToken,
    TokenVerificationResult,
    _hash_observation,
)

__all__ = [
    "EnforcementGate",
    "EnforcementResult",
    "PolicyDecisionToken",
    "TokenVerificationResult",
    "_hash_observation",
]
