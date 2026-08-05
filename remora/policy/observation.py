# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""PolicyObservation — the governance observation fed to the policy engine.

All fields are optional except ``question``. The engine makes conservative
decisions when fields are absent: missing phase → treats as critical;
missing trust_score → no conformal path; missing adversarial_detected →
defaults to False (but see Remora._detect_adversarial_input for live detection).

Factory methods
---------------
Use the factory methods for clean integration with agent frameworks:

    # From an OpenAI-style tool call
    obs = PolicyObservation.from_tool_call(
        name="delete_account",
        arguments={"user_id": "u-882"},
        risk_tier="critical",
        domain="user_mgmt",
        action_type="destructive_write",
        trust_score=0.24,
        phase="disordered",
        final_H=1.59,
        final_D=0.84,
    )

    # From a JSONL action log record
    obs = PolicyObservation.from_json_record(record_dict)

    # Minimal — let the engine apply conservative defaults
    obs = PolicyObservation.minimal("Deploy to prod", risk_tier="high")
"""
from __future__ import annotations

import hashlib
import json as _json
from dataclasses import dataclass
from typing import Any


def _canonical_json(data: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) for hashing."""
    return _json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def canonical_tool_call_hash(
    *,
    name: str,
    arguments: Any,
    tenant: str = "",
    target: str | None = None,
) -> str:
    """SHA-256 binding a tool call to its exact, full arguments (security audit
    CLAIM 6). Covers (name, full canonical arguments, tenant, target) — never a
    truncated preview. An enforcement point recomputes this immediately before
    execution and refuses on mismatch, preventing an approved decision from
    being reused for different arguments.
    """
    preimage = _canonical_json({
        "name": name,
        "arguments": arguments,
        "tenant": tenant or "",
        "target": target or "",
    })
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolicyObservation:
    """Immutable snapshot of one agent action and its governance context.

    Parameters
    ----------
    question:
        Human-readable description of the proposed action. Used for
        adversarial detection heuristics and audit logging.
    phase:
        Thermodynamic consensus phase: ``"ordered"``, ``"critical"``,
        or ``"disordered"``. None → conservative handling.
    trust_score:
        Aggregate trust signal in [0, 1]. Higher is more trusted.
    temperature:
        Helmholtz temperature T derived from thermodynamic state.
    final_H:
        Shannon entropy H of oracle vote distribution (nats or bits).
    final_D:
        Dissensus D = mean pairwise disagreement in [0, 1].
    risk_tier:
        Operational risk tier: ``"low"``, ``"medium"``, ``"high"``, or ``"critical"``.
    domain:
        Functional domain (e.g. ``"finance"``, ``"infrastructure"``).
    action_type:
        Action category (e.g. ``"read"``, ``"write"``, ``"destructive_write"``).
    target_environment:
        Deployment target (e.g. ``"prod"``, ``"staging"``).
    adversarial_detected:
        True when a prompt-injection or exfiltration pattern was detected.
        Hard ESCALATE — no override.
    evidence_action:
        Evidence pipeline verdict: ``"answer"``, ``"verify"``, ``None``.
    evidence_confidence:
        Confidence score from the evidence pipeline in [0, 1].
    evidence_contradictions:
        Number of contradicting evidence items. > 0 → blocks ACCEPT.
    evidence_signal_source:
        ``"oracle_proxy"`` (derived from oracle distributions) or
        ``"retrieval"`` (live RAG/document retrieval). Surfaces in audit.
    """

    question: str

    # Thermodynamic state
    phase: str | None = None
    trust_score: float | None = None
    temperature: float | None = None
    order_parameter: float | None = None
    susceptibility: float | None = None
    hallucination_bound: float | None = None
    weighted_support: float | None = None
    # OFFLINE-ANALYSIS ONLY (verified 2026-08-05): the live engine producer
    # (remora/reporting.py) always leaves majority_support and
    # rho_response_agreement None, and no live decision path reads them —
    # they are populated only by offline experiment tooling.
    majority_support: float | None = None
    rho_response_agreement: float | None = None
    final_V: float | None = None
    final_H: float | None = None
    final_D: float | None = None

    # Policy flags
    require_rag: bool = False
    refuse_parametric_verdict: bool = False
    evidence_request_reason: str | None = None
    distribution_shift_detected: bool = False
    # OFFLINE-ANALYSIS ONLY (verified 2026-08-05): always None from the live
    # producer; gainability feeds only experiments/gainability_routing.py and
    # DecisionReason.GAINABILITY_ROUTE has never been emitted by the engine.
    conformal_score: float | None = None
    gainability_score: float | None = None

    # Evidence pipeline
    evidence_action: str | None = None
    evidence_confidence: float | None = None
    evidence_supporters: int | None = None
    evidence_contradictions: int | None = None

    # Claim-graph topology
    claim_graph_betti_0: int | None = None
    claim_graph_betti_1: int | None = None
    contradiction_cycles: int | None = None

    # Counterfactual gate
    counterfactual_passed: bool | None = None

    # Assurance trace
    assurance_root: str | None = None

    # Operational context
    risk_tier: str | None = None
    domain: str | None = None
    action_type: str | None = None
    target_environment: str | None = None

    # Oracle health
    oracle_failures: int = 0
    valid_oracle_count: int = 0

    # Security
    adversarial_detected: bool = False
    # Structural validity of the proposed tool call against its schema.
    # False → malformed call, hard ESCALATE.
    # None → validator was not run; engine treats as UNVERIFIED (conservative).
    # True → explicitly validated against schema.
    # Default is None (unknown) — True is only appropriate when a real schema
    # validator has been executed against the tool call's arguments.
    schema_valid: bool | None = None
    # The proposed tool is on the task's own forbidden-tool list → hard ESCALATE.
    tool_forbidden: bool = False
    # The call's arguments derive from untrusted input → never auto-accept (VERIFY).
    argument_tainted: bool = False

    # Misspecification context (v0.9)
    # All fields are None-safe: omitting them produces no change in behaviour.
    environment_confidence: float | None = None
    environment_mismatch_detected: bool = False
    rollback_available: bool | None = None
    state_transition_uncertain: bool = False
    classification_confidence: float | None = None
    classification_alternatives: list[str] | None = None
    model_misspecification_risk: float | None = None

    # Coercion signals (v0.9)
    coercion_detected: bool = False
    blackmail_pattern_detected: bool = False

    # Can every required parameter of the proposed call be sourced — from the
    # task, from prior results, or from another available tool? Supplied by the
    # caller's tool registry (see remora/toolcall/routing/tool_registry.py for a
    # reference extractor). False means confirmed unsatisfiable: an agent making
    # this call would have to fabricate arguments. None means the registry does
    # not cover the tool, which is unknown, not a negative.
    arguments_satisfiable: bool | None = None

    # Do the proposed call's identifier-shaped argument values exist in the
    # authoritative state? Caller-supplied; see
    # remora/toolcall/routing/compatibility.py for a reference implementation.
    # False means confirmed absent from the system of record — acting on it
    # would operate on a record that does not exist. None means no system of
    # record was consulted.
    argument_values_supported: bool | None = None

    # Are the call's judgeable argument values traceable to this context —
    # named in the task text or confirmed by the system of record? A
    # well-formed call whose values came from another context gives structural
    # signals nothing to distrust (NEGATIVE_RESULTS.md §34 measured 86.8% of
    # such calls accepted); ungrounded values withdraw autonomy. None means
    # nothing was judgeable, which must never behave like a negative.
    # Caller-supplied; see remora/toolcall/routing/compatibility.py.
    argument_values_grounded: bool | None = None

    # Does this call serve the task's goal — right resource, right effect?
    # True  → established: the declared tool contract matches an intent quoted
    #         from the task text, and the call fills the targeted role.
    # False → established contradiction: right form, wrong resource or wrong
    #         effect. This is §34's residue — the 30 of 258 foreign calls that
    #         survived value grounding because their values coincidentally
    #         occurred in the task.
    # None  → nothing establishes it: no declared contract, no intent, or an
    #         intent whose spans are not in the task text.
    # Caller-supplied from remora/toolcall/routing/goal_match.py. A model may
    # propose the intent; it may not set this field to True by assertion, and
    # the matcher only returns True when every clause is re-derivable from the
    # task text, the contract and the call.
    tool_matches_goal: bool | None = None

    # Does the tool's declared post-state match the effect the task requested?
    # True  → established: the declared state_delta acts on the resource the
    #         task named, in the direction (read vs change) it asked for.
    # False → established contradiction: a read task served by a tool declared
    #         to mutate, a change task served by a read-only tool, or a
    #         declared post-state that writes a different resource entirely.
    # None  → nothing establishes it: no contract, no intent, an unverified
    #         intent, or a mutating tool whose state_delta is undeclared.
    # Caller-supplied from remora/toolcall/routing/effect_prediction.py. This
    # is a *declaration* check, never a simulation: no model-predicted state
    # may set it to True.
    expected_effect_matches: bool | None = None

    # Required parameters of the proposed call that are absent from it, and the
    # authoritative tools that could supply them. Both caller-populated from a
    # tool registry. A non-empty missing list with resolver tools available is
    # the VERIFY-with-a-plan case; without them it is ABSTAIN, because
    # promising a verification that cannot happen is worse than stopping.
    missing_required_arguments: tuple[str, ...] = ()
    argument_resolver_tools: tuple[str, ...] = ()
    # Name of the tool being proposed, when known. Used to bind a resolution
    # plan to the call it was issued for.
    proposed_tool_name: str | None = None

    # Is the proposed tool absent from the caller-declared available_tools set?
    # True  → the tool is confirmed not in the set (VERIFY floor).
    # False → the tool is in the set (nominal path).
    # None  → available_tools was not supplied; absence is unknown, not confirmed.
    # Populated by build_full_observation; never inferred by the engine itself.
    tool_not_in_available_set: bool | None = None

    # Argument names whose value derives from untrusted content. Meaningful
    # only together with argument_tainted. When one of them occupies a
    # sensitive role (recipient, command, credential, egress target) the
    # untrusted content is authorising rather than informing, and the call
    # escalates regardless of the declared risk tier.
    untrusted_controlled_arguments: tuple[str, ...] = ()

    # Arguments that policy requires validated against an authoritative source
    # and that are not confirmed — either contradicted or simply unknown. The
    # requirement is a property of what the argument steers, decided
    # independently of whether an index happens to cover it; see
    # remora/toolcall/routing/validation.py. Non-empty means autonomy is not
    # available until the value is confirmed.
    unvalidated_required_arguments: tuple[str, ...] = ()

    # Policy generalization / fleet-level risk (v0.9)
    # All fields are caller-populated — REMORA is stateless.
    similar_action_seen_count: int | None = None
    policy_generalization_risk: float | None = None
    fleet_level_effect: str | None = None             # "local" | "systemic" | "critical_mass"

    # Session context for sequential attack detection (v0.9)
    session_id: str | None = None                     # audit correlation only — not used in gate logic
    session_action_count: int | None = None
    session_cumulative_risk: float | None = None

    # Provenance
    # "oracle_proxy"  — evidence derived from oracle response distributions
    # "retrieval"     — evidence from a live RAG / document-retrieval pipeline
    evidence_signal_source: str = "oracle_proxy"
    evidence_provenance: dict[str, Any] | None = None
    evidence_timestamp: str | None = None

    # Canonical binding of the FULL tool call to this decision (security audit
    # CLAIM 6). SHA-256 over canonical (name, full arguments, tenant, target) —
    # NOT the truncated question preview. A downstream enforcement point must
    # recompute this immediately before execution and refuse on mismatch, so an
    # approved decision cannot be reused for different arguments (TOCTOU).
    tool_call_hash: str | None = None

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_tool_call(
        cls,
        name: str,
        arguments: dict[str, Any],
        *,
        risk_tier: str | None = None,
        domain: str | None = None,
        action_type: str | None = None,
        target_environment: str = "prod",
        trust_score: float | None = None,
        phase: str | None = None,
        final_H: float | None = None,
        final_D: float | None = None,
        adversarial_detected: bool = False,
        **kwargs: Any,
    ) -> PolicyObservation:
        """Construct from an agent framework tool call.

        Compatible with OpenAI function-calling, LangGraph ToolNode, and
        any framework that expresses tool calls as ``(name, arguments)`` pairs.

        Parameters
        ----------
        name:
            Tool / function name (e.g. ``"delete_account"``).
        arguments:
            Tool arguments dict.
        **kwargs:
            Any additional ``PolicyObservation`` field overrides.

        Examples
        --------
        OpenAI::

            for call in response.choices[0].message.tool_calls:
                obs = PolicyObservation.from_tool_call(
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments),
                    risk_tier=classify_risk(call.function.name),
                    domain="customer-support",
                    trust_score=0.85,
                    phase="ordered",
                )

        LangGraph::

            for call in state["messages"][-1].tool_calls:
                obs = PolicyObservation.from_tool_call(
                    name=call["name"],
                    arguments=call["args"],
                    risk_tier=risk_policy[call["name"]],
                )
        """
        args_preview = _canonical_json(arguments)[:120]
        question = f"{name}({args_preview})"
        # Bind the decision to the FULL tool call, not the 120-char preview.
        tenant = str(kwargs.get("session_id") or "")
        tool_call_hash = canonical_tool_call_hash(
            name=name,
            arguments=arguments,
            tenant=tenant,
            target=target_environment,
        )
        return cls(
            question=question,
            risk_tier=risk_tier,
            domain=domain,
            action_type=action_type or "tool_call",
            target_environment=target_environment,
            trust_score=trust_score,
            phase=phase,
            final_H=final_H,
            final_D=final_D,
            adversarial_detected=adversarial_detected,
            tool_call_hash=tool_call_hash,
            **kwargs,
        )

    @classmethod
    def from_json_record(cls, record: dict[str, Any]) -> PolicyObservation:
        """Construct from a JSONL action log record.

        Accepts the same field names used by the shadow-mode replay pipeline
        (``trust_score``, ``phase``, ``risk_tier``, ``unsafe``, etc.).
        Unknown keys are silently ignored.

        Parameters
        ----------
        record:
            Dictionary parsed from one line of an agent action log.

        Examples
        --------
        ::

            with open("agent_log.jsonl") as f:
                for line in f:
                    obs = PolicyObservation.from_json_record(json.loads(line))
                    report = engine.decide(obs)
        """
        def _f(key: str) -> float | None:
            v = record.get(key)
            return float(v) if v is not None else None

        def _i(key: str) -> int | None:
            v = record.get(key)
            return int(v) if v is not None else None

        def _b(key: str, default: bool = False) -> bool:
            v = record.get(key, default)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return bool(v)

        question = (
            record.get("question")
            or record.get("proposed_action")
            or record.get("action")
            or record.get("tool_call")
            or "unspecified_action"
        )
        return cls(
            question=question,
            phase=record.get("phase"),
            trust_score=_f("trust_score"),
            temperature=_f("temperature"),
            order_parameter=_f("order_parameter"),
            susceptibility=_f("susceptibility"),
            hallucination_bound=_f("hallucination_bound"),
            weighted_support=_f("weighted_support"),
            majority_support=_f("majority_support"),
            final_V=_f("final_V"),
            final_H=_f("final_H"),
            final_D=_f("final_D"),
            require_rag=_b("require_rag"),
            refuse_parametric_verdict=_b("refuse_parametric_verdict"),
            distribution_shift_detected=_b("distribution_shift_detected"),
            evidence_action=record.get("evidence_action"),
            evidence_confidence=_f("evidence_confidence"),
            evidence_supporters=_i("evidence_supporters"),
            evidence_contradictions=_i("evidence_contradictions"),
            claim_graph_betti_0=_i("claim_graph_betti_0"),
            claim_graph_betti_1=_i("claim_graph_betti_1"),
            contradiction_cycles=_i("contradiction_cycles"),
            counterfactual_passed=(
                None if record.get("counterfactual_passed") is None
                else _b("counterfactual_passed")
            ),
            assurance_root=record.get("assurance_root"),
            risk_tier=record.get("risk_tier"),
            domain=record.get("domain"),
            action_type=record.get("action_type"),
            target_environment=record.get("target_environment"),
            oracle_failures=_i("oracle_failures") or 0,
            valid_oracle_count=_i("valid_oracle_count") or 0,
            adversarial_detected=_b("adversarial_detected"),
            environment_confidence=_f("environment_confidence"),
            environment_mismatch_detected=_b("environment_mismatch_detected"),
            rollback_available=(
                None if record.get("rollback_available") is None
                else _b("rollback_available")
            ),
            state_transition_uncertain=_b("state_transition_uncertain"),
            classification_confidence=_f("classification_confidence"),
            classification_alternatives=record.get("classification_alternatives"),
            model_misspecification_risk=_f("model_misspecification_risk"),
            coercion_detected=_b("coercion_detected"),
            blackmail_pattern_detected=_b("blackmail_pattern_detected"),
            similar_action_seen_count=_i("similar_action_seen_count"),
            policy_generalization_risk=_f("policy_generalization_risk"),
            fleet_level_effect=record.get("fleet_level_effect"),
            session_id=record.get("session_id"),
            session_action_count=_i("session_action_count"),
            session_cumulative_risk=_f("session_cumulative_risk"),
            evidence_signal_source=record.get("evidence_signal_source") or "oracle_proxy",
            evidence_provenance=record.get("evidence_provenance"),
            evidence_timestamp=record.get("evidence_timestamp"),
        )

    @classmethod
    def minimal(
        cls,
        question: str,
        *,
        risk_tier: str | None = None,
        domain: str | None = None,
        target_environment: str = "prod",
    ) -> PolicyObservation:
        """Construct a minimal observation — the engine applies conservative defaults.

        Use when thermodynamic parameters are not yet available and you want
        the engine to err on the side of caution.

        Examples
        --------
        ::

            obs = PolicyObservation.minimal(
                "Send password-reset email to user@example.com",
                risk_tier="medium",
                domain="email",
            )
        """
        return cls(
            question=question,
            risk_tier=risk_tier,
            domain=domain,
            target_environment=target_environment,
        )
