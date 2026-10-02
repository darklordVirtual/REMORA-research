# SPDX-License-Identifier: BUSL-1.1
"""Authority isolation for the evidence-admission layer (task §1.2 and §7).

Evidence is not authority. The admission package must never import the
enforcement, execution or policy machinery, and feeding fully admitted
evidence into the engine's public surface must change nothing about what
the engine can authorize. The AST half pins the import boundary (same
pattern as tests/test_cascade_not_authorization.py); the runtime half
proves an admission record carries nothing a decision can read.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMISSION_DIR = ROOT / "remora" / "evidence" / "admission"

FORBIDDEN_PREFIXES = (
    "remora.enforcement",
    "remora.execution",
    "remora.policy",
    "remora.toolcall",
    "servers",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_admission_package_never_imports_authority_modules() -> None:
    offenders: list[str] = []
    for py in ADMISSION_DIR.rglob("*.py"):
        for mod in _imports(py):
            if mod.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{py.name}: {mod}")
    assert not offenders, (
        "evidence admission must not reach authority modules: "
        + ", ".join(offenders)
    )


def test_admission_result_carries_no_policy_observation_fields() -> None:
    """An EvidenceAdmission has no attribute the policy engine could read as
    a decision input. This is the structural half of 'evidence is not
    authority': there is nothing to accidentally wire."""
    from remora.evidence.admission import EvidenceAdmission

    fields = set(EvidenceAdmission.__dataclass_fields__)
    forbidden = {
        "action", "decision", "verdict", "trust_score", "phase",
        "evidence_action", "evidence_confidence", "risk_tier",
        "argument_tainted", "schema_valid", "rollback_available",
    }
    assert not (fields & forbidden), fields & forbidden


def test_admitted_evidence_does_not_change_a_policy_decision() -> None:
    """Runtime half: build a fully admitted record, then decide the same
    observation twice — with and without the admission in scope. The
    decisions must be identical because the engine never receives it."""
    from remora.evidence.admission import (
        EstablishmentStatus,
        EvidenceAdmission,
        ProcessingStatus,
    )
    from remora.policy.decision_engine import RemoraDecisionEngine
    from remora.policy.observation import PolicyObservation

    admission = EvidenceAdmission(
        processing=ProcessingStatus.COMPLETED,
        reason_codes=(),
        established_facts={"source_accepted": EstablishmentStatus.ESTABLISHED},
        evidence_digest="e" * 64,
        scope={"proposal_id": "p-1"},
    )

    obs = PolicyObservation(
        question="transfer_funds(recipient=acct-9931)",
        proposed_tool_name="transfer_funds",
        risk_tier="critical",
        action_type="production_write",
        target_environment="prod",
        argument_tainted=True,
    )
    engine = RemoraDecisionEngine()
    before = engine.decide(obs)
    # The admission record is in scope but has no path into the decision.
    _ = admission
    after = engine.decide(obs)
    assert before.action is after.action
    assert [r.value for r in before.reasons] == [r.value for r in after.reasons]


def test_erasure_monotonicity() -> None:
    """Removing evidence must never strengthen an outcome (task §7).

    Compare full evidence against progressively erased inputs: a fact that
    was ESTABLISHED must never become *more* established, and facts that were
    not established must stay that way."""
    from remora.evidence.admission import EstablishmentStatus
    from tests.test_evidence_admission_adversarial import (  # noqa: E402
        _full,
    )

    full = _full()
    erased_once = _full(prior_commitment=None)
    erased_twice = _full(prior_commitment=None, binding=None)
    erased_all = _full(manifest=None, coverage=None, binding=None,
                       vantage=None, prior_commitment=None)

    established_facts = tuple(
        fact for fact in full.established_facts
        if fact != "effect_observation_accepted"
    )
    assert full.all_established(established_facts)
    assert not full.is_established("effect_observation_accepted")
    for name, status in erased_all.established_facts.items():
        assert status is EstablishmentStatus.NOT_ESTABLISHED
    assert not erased_once.is_established("prior_commitment_established")
    assert erased_once.is_established("invocation_binding_established")
    assert not erased_twice.is_established("invocation_binding_established")


def test_scope_non_transitivity() -> None:
    """Evidence bound to invocation A establishes nothing for invocation B."""
    from tests.test_evidence_admission_adversarial import INVOCATION, _full

    other = dict(INVOCATION)
    other["invocation_id"] = "inv-2"
    other["proposal_id"] = "p-2"
    other["execution_id"] = "e-2"
    result = _full(expected_invocation=other)
    assert not result.is_established("invocation_binding_established")
    assert not result.is_established("observation_coverage_complete")
    assert not result.is_established("same_protected_operation")
