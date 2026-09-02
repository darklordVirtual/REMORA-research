# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REMORA — Robust Entropy-Minimizing Oracle Reasoning Architecture.

Governance overlay for autonomous AI agents. Gate every agent action through
uncertainty-aware, evidence-backed, human-reviewable policy decisions.

Quick-start (zero API keys)::

    from remora import RemoraDecisionEngine, PolicyObservation, DecisionAction

    engine = RemoraDecisionEngine()
    obs = PolicyObservation(
        question="Deploy payment service to production",
        phase="critical", trust_score=0.62,
        final_H=0.88, final_D=0.44,
        risk_tier="high", domain="infrastructure",
        action_type="deploy", target_environment="prod",
    )
    report = engine.decide(obs)
    print(report.action)                 # DecisionAction.VERIFY
    print(report.human_review_required)  # True

Explain a decision::

    trace = engine.explain(obs)
    print(trace.decision_path)
    for r in trace.rule_evaluations:
        if r.triggered:
            print(r.rule, "->", r.outcome)

Tamper-evident audit chain::

    from remora import RemoraAuditChain
    chain = RemoraAuditChain(secret_key="my-hmac-key")
    envelope = chain.append(envelope)
    ok, errors = chain.verify()

Machine-verifiable safety invariants::

    from remora import assert_invariants, InvariantViolationError
    try:
        assert_invariants(obs, report)
    except InvariantViolationError as e:
        print("Safety invariant violated:", e)

What would it take for a call to be accepted::

    from remora import what_if_tool_call
    assessment, report = what_if_tool_call(
        "drop_database", {"db": "prod-main"},
        risk_tier="critical", action_type="destructive_write")
    print(report.confidence_can_lift)   # False: no model signal reaches ACCEPT
    print(report.summary())

Shadow-mode replay::

    from remora import replay_action_log
    result = replay_action_log("agent_log.jsonl")
    print(result.report.estimated_avoided_unsafe_executions)
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("remora-assurance")
except PackageNotFoundError:
    __version__ = "0.11.0-dev"

__author__ = "Stian Skogbrott"
__license__ = "BUSL-1.1"

# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# One-call tool-call assessment (the library form of `remora assess`)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Policy layer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Governance contract
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tamper-evident audit chain
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Machine-verifiable safety invariants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shadow-mode replay
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Evidence providers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# External integrations
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Framework adapters
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Lazy public surface (PEP 562)
# ---------------------------------------------------------------------------
#
# These were eager top-level imports until 2026-08-20, which meant that
# touching ANY part of remora — including `import remora.sdk`, the namespace
# documented as "a small, stable entry point" — pulled in 62 modules: the
# evidence providers, the GO-STAR bridge, the replay engine and the OTel
# wrapper, whether the caller wanted them or not. That defeated the
# embeddability the package otherwise earns by keeping every heavy dependency
# behind a function-local import.
#
# The public surface is unchanged: the same 90 names resolve to the same
# objects. They are now materialised on first attribute access.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AIGovernanceClassification": ("remora.evidence", "AIGovernanceClassification"),
    "AIGovernanceEvidenceProvider": ("remora.evidence", "AIGovernanceEvidenceProvider"),
    "AIGovernanceTriageResult": ("remora.evidence", "AIGovernanceTriageResult"),
    "AIGovernanceVerdict": ("remora.evidence", "AIGovernanceVerdict"),
    "ActionGateResult": ("remora.adapters.action_gate", "ActionGateResult"),
    "AllDomainsBenchmarkResult": ("remora.evidence", "AllDomainsBenchmarkResult"),
    "AssessmentBlock": ("remora.governance.envelope", "AssessmentBlock"),
    "AsyncActionGate": ("remora.adapters.action_gate", "AsyncActionGate"),
    "AsyncLocalGateway": ("remora.adapters.action_gate", "AsyncLocalGateway"),
    "AuditBlock": ("remora.governance.envelope", "AuditBlock"),
    "AutoGenActionAdapter": ("remora.adapters.action_gate", "AutoGenActionAdapter"),
    "BenchmarkCase": ("remora.evidence", "BenchmarkCase"),
    "CORE_INVARIANTS": ("remora.policy.invariants", "CORE_INVARIANTS"),
    "ChainEntry": ("remora.governance.audit_chain", "ChainEntry"),
    "CrewAIActionAdapter": ("remora.adapters.action_gate", "CrewAIActionAdapter"),
    "CyberEvidenceMatch": ("remora.evidence", "CyberEvidenceMatch"),
    "CyberEvidenceProvider": ("remora.evidence", "CyberEvidenceProvider"),
    "CyberEvidenceRecord": ("remora.evidence", "CyberEvidenceRecord"),
    "CyberFindingEnvelope": ("remora.evidence", "CyberFindingEnvelope"),
    "CyberTriageResult": ("remora.evidence", "CyberTriageResult"),
    "CyberTriageVerdict": ("remora.evidence", "CyberTriageVerdict"),
    "DOMAIN_REGISTRY": ("remora.evidence", "DOMAIN_REGISTRY"),
    "DecisionAction": ("remora.policy.report", "DecisionAction"),
    "DecisionEnvelope": ("remora.governance.envelope", "DecisionEnvelope"),
    "DecisionReason": ("remora.policy.report", "DecisionReason"),
    "DecisionReport": ("remora.policy.report", "DecisionReport"),
    "DefensivePoCPlan": ("remora.evidence", "DefensivePoCPlan"),
    "DisclosureLedger": ("remora.evidence", "DisclosureLedger"),
    "DisclosureStatus": ("remora.evidence", "DisclosureStatus"),
    "DomainBenchmarkResult": ("remora.evidence", "DomainBenchmarkResult"),
    "DomainBenchmarkRunner": ("remora.evidence", "DomainBenchmarkRunner"),
    "EvidenceProvider": ("remora.evidence", "EvidenceProvider"),
    "EvidenceProviderResult": ("remora.evidence", "EvidenceProviderResult"),
    "EvidenceSignal": ("remora.evidence", "EvidenceSignal"),
    "ExploitClassification": ("remora.evidence", "ExploitClassification"),
    "FinanceEvidenceProvider": ("remora.evidence", "FinanceEvidenceProvider"),
    "FinanceRiskClassification": ("remora.evidence", "FinanceRiskClassification"),
    "FinanceTriageResult": ("remora.evidence", "FinanceTriageResult"),
    "FinanceVerdict": ("remora.evidence", "FinanceVerdict"),
    "FindingVerdict": ("remora.integrations", "FindingVerdict"),
    "GateBlock": ("remora.governance.envelope", "GateBlock"),
    "GatewayResult": ("remora.adapters.gateway", "GatewayResult"),
    "Genome": ("remora.genome", "Genome"),
    "GoStarBridge": ("remora.integrations", "GoStarBridge"),
    "GoStarFinding": ("remora.integrations", "GoStarFinding"),
    "GoStarScanResult": ("remora.integrations", "GoStarScanResult"),
    "GovernanceDeltaReport": ("remora.shadow.replay", "GovernanceDeltaReport"),
    "HttpGateway": ("remora.adapters.gateway", "HttpGateway"),
    "InMemoryRetrievalBackend": ("remora.evidence", "InMemoryRetrievalBackend"),
    "InvariantResult": ("remora.policy.invariants", "InvariantResult"),
    "InvariantViolationError": ("remora.policy.invariants", "InvariantViolationError"),
    "JaccardNLIScorer": ("remora.evidence", "JaccardNLIScorer"),
    "LangGraphActionAdapter": ("remora.adapters.action_gate", "LangGraphActionAdapter"),
    "LocalGateway": ("remora.adapters.gateway", "LocalGateway"),
    "OpenAIToolCallingAdapter": ("remora.adapters.action_gate", "OpenAIToolCallingAdapter"),
    "Oracle": ("remora.core", "Oracle"),
    "OracleProxyEvidenceProvider": ("remora.evidence", "OracleProxyEvidenceProvider"),
    "OracleResponse": ("remora.core", "OracleResponse"),
    "OracleSignal": ("remora.integrations", "OracleSignal"),
    "PoCReadiness": ("remora.evidence", "PoCReadiness"),
    "PolicyInvariant": ("remora.policy.invariants", "PolicyInvariant"),
    "PolicyObservation": ("remora.policy", "PolicyObservation"),
    "PolicyRuleEvaluation": ("remora.policy.decision_engine", "PolicyRuleEvaluation"),
    "PolicyTrace": ("remora.policy.decision_engine", "PolicyTrace"),
    "RAGEvidenceProvider": ("remora.evidence", "RAGEvidenceProvider"),
    "RAGProviderResult": ("remora.evidence", "RAGProviderResult"),
    "Remora": ("remora.engine", "Remora"),
    "RemoraAuditChain": ("remora.governance.audit_chain", "RemoraAuditChain"),
    "RemoraDecisionEngine": ("remora.policy", "RemoraDecisionEngine"),
    "RemoraState": ("remora.engine", "RemoraState"),
    "RemoraTracer": ("remora.observability.otel", "RemoraTracer"),
    "ReplayResult": ("remora.shadow.replay", "ReplayResult"),
    "RequestBlock": ("remora.governance.envelope", "RequestBlock"),
    "ResearchArtifactRef": ("remora.evidence", "ResearchArtifactRef"),
    "RetrievedPassage": ("remora.evidence", "RetrievedPassage"),
    "SecurityGovernanceResult": ("remora.integrations", "SecurityGovernanceResult"),
    "Severity": ("remora.integrations", "Severity"),
    "StaticJsonlEvidenceProvider": ("remora.evidence", "StaticJsonlEvidenceProvider"),
    "TargetScanProfile": ("remora.evidence", "TargetScanProfile"),
    "ToolCallAssessment": ("remora.assess", "ToolCallAssessment"),
    "WhatIfReport": ("remora.policy.whatif", "WhatIfReport"),
    "assert_invariants": ("remora.policy.invariants", "assert_invariants"),
    "assess_tool_call": ("remora.assess", "assess_tool_call"),
    "check_all_invariants": ("remora.policy.invariants", "check_all_invariants"),
    "combine_results": ("remora.evidence", "combine_results"),
    "get_provider": ("remora.evidence", "get_provider"),
    "get_remora_tracer": ("remora.observability.otel", "get_remora_tracer"),
    "infer_risk_and_type": ("remora.assess", "infer_risk_and_type"),
    "invariant_summary": ("remora.policy.invariants", "invariant_summary"),
    "replay_action_log": ("remora.shadow.replay", "replay_action_log"),
    "what_if": ("remora.policy.whatif", "what_if"),
    "what_if_tool_call": ("remora.assess", "what_if_tool_call"),
}


def __getattr__(name: str) -> object:
    """Resolve a public symbol on first use (PEP 562)."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'remora' has no attribute {name!r}")
    module_name, attribute = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value  # cache: one import per symbol per process
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "__version__",
    # Core engine
    "Remora", "RemoraState", "Genome", "Oracle", "OracleResponse",
    # One-call assessment
    "ToolCallAssessment", "assess_tool_call", "infer_risk_and_type",
    # What would it take: decision-boundary analysis
    "WhatIfReport", "what_if", "what_if_tool_call",
    # Policy
    "RemoraDecisionEngine", "PolicyObservation",
    "DecisionAction", "DecisionReason", "DecisionReport",
    "PolicyTrace", "PolicyRuleEvaluation",
    # Governance contract
    "DecisionEnvelope", "RequestBlock", "AssessmentBlock", "GateBlock", "AuditBlock",
    # Audit chain
    "RemoraAuditChain", "ChainEntry",
    # Safety invariants
    "CORE_INVARIANTS", "PolicyInvariant", "InvariantResult",
    "InvariantViolationError", "check_all_invariants", "assert_invariants",
    "invariant_summary",
    # Evidence providers
    "EvidenceProvider", "EvidenceProviderResult", "EvidenceSignal",
    "InMemoryRetrievalBackend", "JaccardNLIScorer", "RAGEvidenceProvider",
    "RAGProviderResult", "OracleProxyEvidenceProvider", "RetrievedPassage",
    "StaticJsonlEvidenceProvider",
    "CyberEvidenceMatch", "CyberEvidenceProvider", "CyberEvidenceRecord",
    "CyberTriageResult", "CyberTriageVerdict",
    "DefensivePoCPlan", "ExploitClassification", "PoCReadiness",
    # GO-STAR bridge types
    "CyberFindingEnvelope", "DisclosureLedger", "DisclosureStatus",
    "ResearchArtifactRef", "TargetScanProfile",
    # Cross-domain benchmark
    "AllDomainsBenchmarkResult", "BenchmarkCase", "DomainBenchmarkResult",
    "DomainBenchmarkRunner", "combine_results",
    # Domain providers
    "AIGovernanceClassification", "AIGovernanceEvidenceProvider",
    "AIGovernanceTriageResult", "AIGovernanceVerdict",
    "FinanceEvidenceProvider", "FinanceRiskClassification",
    "FinanceTriageResult", "FinanceVerdict",
    "DOMAIN_REGISTRY", "get_provider",
    # External integrations
    "FindingVerdict", "GoStarBridge", "GoStarFinding", "GoStarScanResult",
    "OracleSignal", "Severity",
    "SecurityGovernanceResult",
    # Shadow mode
    "replay_action_log", "GovernanceDeltaReport", "ReplayResult",
    # Adapters
    "LocalGateway", "HttpGateway", "GatewayResult",
    "ActionGateResult", "AsyncLocalGateway", "AsyncActionGate",
    "LangGraphActionAdapter", "OpenAIToolCallingAdapter",
    "CrewAIActionAdapter", "AutoGenActionAdapter",
    # Observability
    "get_remora_tracer", "RemoraTracer",
]
