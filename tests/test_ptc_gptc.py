# SPDX-License-Identifier: BUSL-1.1
"""Tests for remora.toolcall.ptc — Governed Programmatic Tool Calling (RF-11).

All tests are deterministic, offline, stdlib-only.  No network access; no API
keys; no exec/eval of untrusted code.

Coverage:
  - stub_generator: type annotation synthesis, forbidden-import guard,
    duplicate-tool_id detection, unsafe-identifier rejection.
  - call_graph: AST extraction of sequential calls, parallel gather patterns,
    unknown-call detection, 16 KiB safety cap, syntax-error handling.
  - governed_batch: ACCEPT dispatch, VERIFY pause, ESCALATE propagation,
    ABSTAIN abort, dependency ordering, parallel fan-out, dispatcher error.
"""
from __future__ import annotations

import asyncio
import textwrap
from typing import Any

import pytest

from remora.toolcall.ptc.stub_generator import (
    StubGenerationError,
    generate_stubs,
    render_stub_module,
)
from remora.toolcall.ptc.call_graph import (
    CallGraphError,
    ProposedCall,
    extract_call_graph,
)
from remora.toolcall.ptc.governed_batch import (
    BatchOutcome,
    GovernedBatchExecutor,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SPEC_READ = {
    "tool_id": "read_sensor",
    "version": 1,
    "callable_digest": "abc123",
    "implementation_identity": "test",
    "description": "Read a sensor value.",
    "argument_schema": {
        "type": "object",
        "properties": {
            "sensor": {"type": "string"},
            "unit": {"type": "string"},
        },
        "required": ["sensor"],
    },
    "risk_tier": "LOW",
    "action_type": "READ",
    "domain": "ot",
    "capabilities": ["read"],
    "semantic_contract": {},
    "credential_scope": [],
    "allowed_targets": [],
    "idempotency_contract": {},
    "postcondition_reader": None,
    "compensation_tool": None,
    "timeout_policy": {},
    "network_policy": {},
    "signing_identity": "test-key",
    "toolspec_hash": "deadbeef00",
}

SPEC_WRITE = {
    **SPEC_READ,
    "tool_id": "update_work_order",
    "description": "Update a work order status.",
    "argument_schema": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "status": {"type": "string"},
            "priority": {"type": "integer"},
        },
        "required": ["order_id", "status"],
    },
    "risk_tier": "HIGH",
    "action_type": "WRITE",
    "toolspec_hash": "cafebabe00",
}


# ── stub_generator tests ──────────────────────────────────────────────────────

class TestStubGenerator:
    def test_generates_typed_stubs(self):
        stubs = generate_stubs([SPEC_READ, SPEC_WRITE])
        assert len(stubs) == 2
        read_stub = stubs[0]
        assert read_stub.tool_id == "read_sensor"
        assert "sensor: str" in read_stub.source
        # Optional argument must have None default
        assert "unit: str | None = None" in read_stub.source

    def test_stub_returns_proposed_call_not_real_api(self):
        stubs = generate_stubs([SPEC_READ])
        # No network/process imports anywhere in the source
        assert "requests" not in stubs[0].source
        assert "subprocess" not in stubs[0].source
        assert "_remora_propose" in stubs[0].source

    def test_render_module_has_no_forbidden_imports(self):
        stubs = generate_stubs([SPEC_READ, SPEC_WRITE])
        module_src = render_stub_module(stubs)
        assert "import requests" not in module_src
        assert "ProposedCall" in module_src

    def test_duplicate_tool_id_raises(self):
        dup = {**SPEC_READ, "toolspec_hash": "other"}
        with pytest.raises(StubGenerationError, match="Duplicate"):
            generate_stubs([SPEC_READ, dup])

    def test_unsafe_identifier_raises(self):
        bad_spec = {**SPEC_READ, "tool_id": "import"}  # Python keyword
        with pytest.raises(StubGenerationError, match="Unsafe identifier"):
            generate_stubs([bad_spec])

    def test_hyphenated_tool_id_raises(self):
        bad = {**SPEC_READ, "tool_id": "read-sensor"}
        with pytest.raises(StubGenerationError, match="Unsafe identifier"):
            generate_stubs([bad])

    def test_required_params_have_no_default(self):
        stubs = generate_stubs([SPEC_WRITE])
        src = stubs[0].source
        # required args come first and have no default
        assert "order_id: str," in src or "order_id: str)" in src
        # optional int with None default
        assert "priority: int | None = None" in src

    def test_risk_tier_in_docstring(self):
        stubs = generate_stubs([SPEC_WRITE])
        assert "HIGH" in stubs[0].source
        assert "WRITE" in stubs[0].source


# ── call_graph tests ──────────────────────────────────────────────────────────

class TestCallGraph:
    def test_extracts_simple_sequential_call(self):
        source = textwrap.dedent("""\
            x = read_sensor(sensor="PT-101")
        """)
        calls, unknowns = extract_call_graph(source, ["read_sensor", "update_work_order"])
        assert len(calls) == 1
        assert calls[0].tool_id == "read_sensor"
        assert calls[0].arguments == {"sensor": "PT-101"}
        assert unknowns == []

    def test_extracts_parallel_gather(self):
        source = textwrap.dedent("""\
            import asyncio
            results = asyncio.gather(
                read_sensor(sensor="R1"),
                read_sensor(sensor="R2"),
                read_sensor(sensor="R3"),
            )
        """)
        calls, unknowns = extract_call_graph(source, ["read_sensor"])
        assert len(calls) == 3
        sensors = {c.arguments.get("sensor") for c in calls}
        assert sensors == {"R1", "R2", "R3"}
        # Parallel calls have no dependencies on each other
        for c in calls:
            assert c.dependencies == []

    def test_unknown_call_reported(self):
        source = "hallucinated_tool(x=1)\nread_sensor(sensor='A')"
        calls, unknowns = extract_call_graph(source, ["read_sensor"])
        assert "hallucinated_tool" in unknowns
        assert len(calls) >= 1

    def test_syntax_error_raises(self):
        with pytest.raises(CallGraphError, match="syntax error"):
            extract_call_graph("def (broken syntax", ["read_sensor"])

    def test_source_size_cap(self):
        huge = "x = 1\n" * 3000  # > 16 KiB
        with pytest.raises(CallGraphError, match="16 KiB"):
            extract_call_graph(huge, ["read_sensor"])

    def test_plan_source_hash_stable(self):
        source = "read_sensor(sensor='X')"
        calls, _ = extract_call_graph(source, ["read_sensor"])
        assert calls[0].plan_source_hash
        # Re-run produces same hash
        calls2, _ = extract_call_graph(source, ["read_sensor"])
        assert calls[0].plan_source_hash == calls2[0].plan_source_hash

    def test_unknown_builtins_not_reported(self):
        source = "vals = list(range(10))\nread_sensor(sensor='Z')"
        _, unknowns = extract_call_graph(source, ["read_sensor"])
        assert "list" not in unknowns
        assert "range" not in unknowns

    def test_dynamic_args_sentinel(self):
        source = "read_sensor(sensor=some_variable)"
        calls, _ = extract_call_graph(source, ["read_sensor"])
        assert calls[0].arguments["sensor"] == "<dynamic>"


# ── governed_batch tests ──────────────────────────────────────────────────────

def _make_call(tool_id: str, deps: list[str] | None = None) -> ProposedCall:
    return ProposedCall(
        call_id=f"{tool_id}-id",
        tool_id=tool_id,
        arguments={"x": 1},
        toolspec_hash="abc",
        dependencies=deps or [],
        plan_source_hash="planhash",
    )


def _make_assessor(decision_map: dict[str, str]):
    async def _assess(call: ProposedCall) -> dict[str, Any]:
        return {"decision": decision_map.get(call.tool_id, "ACCEPT")}
    return _assess


def _make_dispatcher(results_map: dict[str, Any] | None = None):
    results_map = results_map or {}
    async def _dispatch(call: ProposedCall, _meta: dict) -> Any:
        if call.tool_id in results_map:
            return results_map[call.tool_id]
        return f"result:{call.tool_id}"
    return _dispatch


class TestGovernedBatch:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_all_accept(self):
        calls = [_make_call("read_sensor"), _make_call("update_work_order")]
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({}),
            dispatcher=_make_dispatcher(),
        )
        results, outcome = self._run(executor.execute(calls))
        assert outcome == BatchOutcome.ALL_ACCEPTED
        assert all(r.decision == "ACCEPT" for r in results)
        assert all(r.executed for r in results)

    def test_verify_produces_requires_verify_outcome(self):
        calls = [_make_call("read_sensor"), _make_call("update_work_order")]
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({"update_work_order": "VERIFY"}),
            dispatcher=_make_dispatcher(),
        )
        results, outcome = self._run(executor.execute(calls))
        assert outcome == BatchOutcome.REQUIRES_VERIFY
        verify_result = next(r for r in results if r.tool_id == "update_work_order")
        assert verify_result.decision == "VERIFY"
        assert not verify_result.executed

    def test_escalate_outcome(self):
        calls = [_make_call("update_work_order")]
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({"update_work_order": "ESCALATE"}),
            dispatcher=_make_dispatcher(),
        )
        results, outcome = self._run(executor.execute(calls))
        assert outcome == BatchOutcome.ESCALATED

    def test_abstain_aborts_batch(self):
        calls = [_make_call("read_sensor")]
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({"read_sensor": "ABSTAIN"}),
            dispatcher=_make_dispatcher(),
        )
        results, outcome = self._run(executor.execute(calls))
        assert outcome == BatchOutcome.ABSTAINED
        assert not results[0].executed

    def test_dependency_ordering_blocks_child_on_non_accept(self):
        parent = _make_call("read_sensor")
        child = ProposedCall(
            call_id="child-id",
            tool_id="update_work_order",
            arguments={},
            toolspec_hash="",
            dependencies=[parent.call_id],
        )
        # Parent returns VERIFY — child should be blocked (ABSTAIN)
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({"read_sensor": "VERIFY"}),
            dispatcher=_make_dispatcher(),
        )
        results, outcome = self._run(executor.execute([parent, child]))
        child_result = next(r for r in results if r.tool_id == "update_work_order")
        assert child_result.decision == "ABSTAIN"
        assert "Blocked" in (child_result.execution_error or "")

    def test_parallel_fan_out_all_dispatched(self):
        """Independent calls (no deps) are all dispatched concurrently."""
        calls = [_make_call(f"read_sensor_{i}") for i in range(5)]
        dispatched = []

        async def _dispatch(call, _meta):
            dispatched.append(call.tool_id)
            return "ok"

        executor = GovernedBatchExecutor(
            assessor=_make_assessor({}),
            dispatcher=_dispatch,
            max_concurrent=5,
        )
        results, outcome = self._run(executor.execute(calls))
        assert outcome == BatchOutcome.ALL_ACCEPTED
        assert len(dispatched) == 5

    def test_dispatcher_error_recorded(self):
        async def _fail(call, _meta):
            raise RuntimeError("Simulated execution failure")

        executor = GovernedBatchExecutor(
            assessor=_make_assessor({}),
            dispatcher=_fail,
        )
        results, _ = self._run(executor.execute([_make_call("read_sensor")]))
        r = results[0]
        assert r.execution_error == "Simulated execution failure"
        assert not r.executed

    def test_call_result_envelope_block_keys(self):
        calls = [_make_call("read_sensor")]
        executor = GovernedBatchExecutor(
            assessor=_make_assessor({}),
            dispatcher=_make_dispatcher(),
        )
        results, _ = self._run(executor.execute(calls))
        block = results[0].to_envelope_block()
        for key in ("check", "call_id", "tool_id", "decision",
                    "arguments_hash", "toolspec_hash", "plan_source_hash",
                    "executed", "duration_ms"):
            assert key in block, f"Missing envelope key: {key}"

    def test_no_bypass_on_repeated_accept(self):
        """Each call is independently assessed — ACCEPT is not cached."""
        assess_counts: dict[str, int] = {}

        async def _counting_assessor(call: ProposedCall) -> dict:
            assess_counts[call.tool_id] = assess_counts.get(call.tool_id, 0) + 1
            return {"decision": "ACCEPT"}

        calls = [_make_call("read_sensor")] * 3  # same tool, 3 calls
        # Build proper unique call_ids
        import uuid
        calls = [
            ProposedCall(
                call_id=str(uuid.uuid4()),
                tool_id="read_sensor",
                arguments={"x": i},
                toolspec_hash="abc",
                plan_source_hash="h",
            )
            for i in range(3)
        ]
        executor = GovernedBatchExecutor(
            assessor=_counting_assessor,
            dispatcher=_make_dispatcher(),
        )
        self._run(executor.execute(calls))
        # 3 separate assessments, not 1 cached
        assert sum(assess_counts.values()) == 3
