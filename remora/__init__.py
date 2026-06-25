# Author: Stian Skogbrott
# License: Apache-2.0
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

Shadow-mode replay::

    from remora import replay_action_log
    result = replay_action_log("agent_log.jsonl")
    print(result.report.estimated_avoided_unsafe_executions)
"""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("remora")
except PackageNotFoundError:
    __version__ = "0.9.0-dev"

__author__ = "Stian Skogbrott"
__license__ = "Apache-2.0"

# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
from remora.engine import Remora, RemoraState
from remora.genome import Genome
from remora.core import Oracle, OracleResponse

# ---------------------------------------------------------------------------
# Policy layer
# ---------------------------------------------------------------------------
from remora.policy import RemoraDecisionEngine, PolicyObservation
from remora.policy.report import DecisionAction, DecisionReason, DecisionReport
from remora.policy.decision_engine import PolicyTrace, PolicyRuleEvaluation

# ---------------------------------------------------------------------------
# Governance contract
# ---------------------------------------------------------------------------
from remora.governance.envelope import (
    DecisionEnvelope,
    RequestBlock,
    AssessmentBlock,
    GateBlock,
    AuditBlock,
)

# ---------------------------------------------------------------------------
# Tamper-evident audit chain
# ---------------------------------------------------------------------------
from remora.governance.audit_chain import RemoraAuditChain, ChainEntry

# ---------------------------------------------------------------------------
# Machine-verifiable safety invariants
# ---------------------------------------------------------------------------
from remora.policy.invariants import (
    CORE_INVARIANTS,
    PolicyInvariant,
    InvariantResult,
    InvariantViolationError,
    check_all_invariants,
    assert_invariants,
    invariant_summary,
)

# ---------------------------------------------------------------------------
# Shadow-mode replay
# ---------------------------------------------------------------------------
from remora.shadow.replay import replay_action_log, GovernanceDeltaReport, ReplayResult

# ---------------------------------------------------------------------------
# Evidence providers
# ---------------------------------------------------------------------------
from remora.evidence import (
    EvidenceProvider,
    EvidenceProviderResult,
    EvidenceSignal,
    InMemoryRetrievalBackend,
    JaccardNLIScorer,
    RAGEvidenceProvider,
    RAGProviderResult,
    OracleProxyEvidenceProvider,
    RetrievedPassage,
    StaticJsonlEvidenceProvider,
    CyberEvidenceMatch,
    CyberEvidenceProvider,
    CyberEvidenceRecord,
    CyberTriageResult,
    CyberTriageVerdict,
    DefensivePoCPlan,
    ExploitClassification,
    PoCReadiness,
    CyberFindingEnvelope,
    DisclosureLedger,
    DisclosureStatus,
    ResearchArtifactRef,
    TargetScanProfile,
    AllDomainsBenchmarkResult,
    BenchmarkCase,
    DomainBenchmarkResult,
    DomainBenchmarkRunner,
    combine_results,
    AIGovernanceClassification,
    AIGovernanceEvidenceProvider,
    AIGovernanceTriageResult,
    AIGovernanceVerdict,
    FinanceEvidenceProvider,
    FinanceRiskClassification,
    FinanceTriageResult,
    FinanceVerdict,
    DOMAIN_REGISTRY,
    get_provider,
)

# ---------------------------------------------------------------------------
# External integrations
# ---------------------------------------------------------------------------
from remora.integrations import (
    FindingVerdict,
    GoStarBridge,
    GoStarFinding,
    GoStarScanResult,
    OracleSignal,
    Severity,
    SecurityGovernanceResult,
)

# ---------------------------------------------------------------------------
# Framework adapters
# ---------------------------------------------------------------------------
from remora.adapters.gateway import LocalGateway, HttpGateway, GatewayResult
from remora.adapters.action_gate import (
    ActionGateResult,
    AsyncLocalGateway,
    AsyncActionGate,
    LangGraphActionAdapter,
    OpenAIToolCallingAdapter,
    CrewAIActionAdapter,
    AutoGenActionAdapter,
)

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
from remora.observability.otel import get_remora_tracer, RemoraTracer

__all__ = [
    "__version__",
    # Core engine
    "Remora", "RemoraState", "Genome", "Oracle", "OracleResponse",
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
