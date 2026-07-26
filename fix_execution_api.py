import re

with open("servers/execution_api.py", "r") as f:
    content = f.read()

prefix = """\
PEP_AUDIENCE = "pep://remora-execution"
EXECUTION_TOKEN_TTL_SECONDS = 300

_ENGINE = RemoraDecisionEngine()
_IDEMPOTENCY: dict[str, dict[str, Any]] = {}

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "delete_production_database": {
        "risk_tier": "critical",
        "domain": "infrastructure",
        "action_type": "destructive_write"
    },
    "dce_search_law": {
        "risk_tier": "low",
        "domain": "law",
        "action_type": "read"
    },
    "remora_verify_claim": {
        "risk_tier": "low",
        "domain": "general",
        "action_type": "read"
    },
    "store_artifact": {
        "risk_tier": "medium",
        "domain": "general",
        "action_type": "write"
    }
}
"""

content = content.replace("PEP_AUDIENCE = \"pep://remora-execution\"\nEXECUTION_TOKEN_TTL_SECONDS = 300\n\n_ENGINE = RemoraDecisionEngine()", prefix)

observation_fn = """\
def _observation(req: ToolCallRequest, tenant: str) -> PolicyObservation:
    registry_entry = TOOL_REGISTRY.get(req.tool_name, {
        "risk_tier": "critical",
        "domain": "unknown",
        "action_type": "unknown"
    })
    return PolicyObservation.from_tool_call(
        name=req.tool_name,
        arguments=req.arguments,
        risk_tier=registry_entry.get("risk_tier", "critical"),
        domain=registry_entry.get("domain", "unknown"),
        action_type=registry_entry.get("action_type", "unknown"),
        target_environment=registry_entry.get("target_environment", req.target_environment),
        trust_score=req.trust_score,
        phase=req.phase,
        evidence_action=req.evidence_action,
        evidence_confidence=req.evidence_confidence,
        schema_valid=req.schema_valid,
        rollback_available=registry_entry.get("rollback_available", req.rollback_available),
        session_id=tenant,
    )
"""

content = re.sub(r'def _observation\(req: ToolCallRequest, tenant: str\) -> PolicyObservation:\n    return PolicyObservation\.from_tool_call\([\s\S]*?session_id=tenant,\n    \)', observation_fn, content)

with open("servers/execution_api.py", "w") as f:
    f.write(content)
