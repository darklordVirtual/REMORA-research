"""Governance primitives for long-running REMORA agents.

The governance package tracks observable behavioral drift, memory-write risk,
and task-context pressure. It does not infer consciousness, feelings, or genuine
preferences.
"""

from remora.governance.continual_realigner import ContinualRealigner, RealignmentInput, RealignmentReport
from remora.governance.context_flow import (
    ContextFlow,
    ContextFlowDecision,
    ContextFlowRegistry,
    ContextFlowUpdate,
    default_context_flow_registry,
    default_context_flows,
)
from remora.governance.drift_monitor import AgentBehaviorSnapshot, DriftMonitor, DriftReport, DriftSignal
from remora.governance.governance_forgetting import (
    GovernanceForgettingAnalyzer,
    GovernanceForgettingAssessment,
    GovernanceForgettingMetrics,
    GovernanceForgettingThresholds,
)
from remora.governance.memory_gate import MemoryGate, MemoryGateDecision, MemoryGatePolicy, MemoryWriteRequest
from remora.governance.memory_layers import (
    DEFAULT_MEMORY_POLICIES,
    MemoryLayer,
    MemoryLayerDecision,
    MemoryLayerUpdate,
    MemoryPolicy,
    MemoryPolicyRegistry,
    default_memory_policy_registry,
)
from remora.governance.nested_governance import (
    GovernanceForgettingDetector,
    GovernanceForgettingEvent,
    GovernanceForgettingReport,
    GovernanceLayer,
    LayerUpdateDecision,
    LayerUpdateRequest,
    NestedGovernanceModel,
    default_nested_governance_model,
)
from remora.governance.policy_proposals import (
    ObservedGovernancePattern,
    PolicyProposal,
    PolicyProposalEngine,
)
from remora.governance.persona_baseline import PersonaBaseline
from remora.governance.work_context import WorkContext
from remora.governance.envelope import (
    AuditBlock,
    AssessmentBlock,
    DecisionEnvelope,
    FollowUpBlock,
    GateBlock,
    HistoryBlock,
    PolicyLearningBlock,
    RequestBlock,
    ReviewerContextBlock,
)

__all__ = [
    "AgentBehaviorSnapshot",
    "AuditBlock",
    "AssessmentBlock",
    "ContinualRealigner",
    "ContextFlow",
    "DecisionEnvelope",
    "FollowUpBlock",
    "GateBlock",
    "HistoryBlock",
    "PolicyLearningBlock",
    "RequestBlock",
    "ReviewerContextBlock",
    "ContextFlowDecision",
    "ContextFlowRegistry",
    "ContextFlowUpdate",
    "DriftMonitor",
    "DriftReport",
    "DriftSignal",
    "DEFAULT_MEMORY_POLICIES",
    "GovernanceForgettingAnalyzer",
    "GovernanceForgettingAssessment",
    "GovernanceForgettingDetector",
    "GovernanceForgettingEvent",
    "GovernanceForgettingMetrics",
    "GovernanceForgettingReport",
    "GovernanceForgettingThresholds",
    "GovernanceLayer",
    "LayerUpdateDecision",
    "LayerUpdateRequest",
    "MemoryGate",
    "MemoryGateDecision",
    "MemoryGatePolicy",
    "MemoryLayer",
    "MemoryLayerDecision",
    "MemoryLayerUpdate",
    "MemoryPolicy",
    "MemoryPolicyRegistry",
    "MemoryWriteRequest",
    "NestedGovernanceModel",
    "ObservedGovernancePattern",
    "PersonaBaseline",
    "PolicyProposal",
    "PolicyProposalEngine",
    "RealignmentInput",
    "RealignmentReport",
    "WorkContext",
    "default_context_flow_registry",
    "default_context_flows",
    "default_memory_policy_registry",
    "default_nested_governance_model",
]
