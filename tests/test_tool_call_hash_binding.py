"""Full-argument binding for tool-call decisions (security audit CLAIM 6).

A decision must be bound to the EXACT, full arguments — not the 120-char
question preview — so an approved decision cannot be reused for a different
tool call whose arguments differ only beyond the truncation boundary.
"""
from __future__ import annotations

from remora.policy.observation import PolicyObservation, canonical_tool_call_hash


def test_preview_collides_but_full_hash_distinguishes():
    """Two calls identical for the first >120 canonical chars collide on the
    question preview but MUST have different tool_call_hash."""
    common = {"a": "z" * 200}  # long leading field forces preview collision
    o1 = PolicyObservation.from_tool_call(
        name="run", arguments={**common, "tail": "ONE"}, risk_tier="high")
    o2 = PolicyObservation.from_tool_call(
        name="run", arguments={**common, "tail": "TWO"}, risk_tier="high")
    assert o1.question == o2.question, "preview should collide in this setup"
    assert o1.tool_call_hash != o2.tool_call_hash, "full-args hash must differ"


def test_hash_is_deterministic_and_order_independent():
    h1 = canonical_tool_call_hash(name="x", arguments={"a": 1, "b": 2}, tenant="t")
    h2 = canonical_tool_call_hash(name="x", arguments={"b": 2, "a": 1}, tenant="t")
    assert h1 == h2  # canonical (sorted keys)


def test_hash_covers_name_tenant_target():
    base = dict(arguments={"k": "v"})
    h = canonical_tool_call_hash(name="a", tenant="t1", target="prod", **base)
    assert h != canonical_tool_call_hash(name="b", tenant="t1", target="prod", **base)
    assert h != canonical_tool_call_hash(name="a", tenant="t2", target="prod", **base)
    assert h != canonical_tool_call_hash(name="a", tenant="t1", target="staging", **base)


def test_from_tool_call_populates_hash():
    o = PolicyObservation.from_tool_call(name="deploy", arguments={"svc": "api"},
                                         risk_tier="high")
    assert o.tool_call_hash is not None and len(o.tool_call_hash) == 64
