# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The task an authorization was granted under.

The property that carries the whole design is the last class here: an
absent identity must leave a signable payload byte-identical to what it was
before this module existed, or every signature REMORA has already issued
stops verifying.
"""
from __future__ import annotations

import pytest

from remora.governance.task_identity import (
    TaskIdentity,
    TaskIdentityMismatch,
    merge_task_fields,
    task_fields,
)


class TestConstruction:
    def test_both_halves_are_required(self):
        identity = TaskIdentity(context_id="ctx-1", task_id="task-1")
        assert identity.context_id == "ctx-1"
        assert identity.task_id == "task-1"

    @pytest.mark.parametrize("context_id,task_id", [
        ("", "task-1"), ("   ", "task-1"), ("ctx-1", ""), ("ctx-1", "  "),
    ])
    def test_a_blank_half_is_refused(self, context_id, task_id):
        with pytest.raises(ValueError, match="must not be blank"):
            TaskIdentity(context_id=context_id, task_id=task_id)

    @pytest.mark.parametrize("context_id,task_id", [
        (" ctx-1", "task-1"), ("ctx-1", "task-1 "), ("ctx-1\t", "task-1"),
    ])
    def test_padding_is_refused_rather_than_trimmed(self, context_id, task_id):
        """A padded id compares unequal to its own trimmed form.

        Trimming silently would make two spellings of one task compare
        equal in some paths and not others; refusing keeps the comparison
        total.
        """
        with pytest.raises(ValueError, match="leading or trailing space"):
            TaskIdentity(context_id=context_id, task_id=task_id)

    @pytest.mark.parametrize("value", [1, None, b"ctx", ["ctx"]])
    def test_a_non_string_half_is_refused(self, value):
        with pytest.raises(TypeError, match="must be a string"):
            TaskIdentity(context_id=value, task_id="task-1")

    def test_it_is_frozen(self):
        identity = TaskIdentity(context_id="ctx-1", task_id="task-1")
        with pytest.raises(Exception):
            identity.task_id = "task-2"


class TestFromFields:
    def test_neither_half_present_is_no_identity(self):
        assert TaskIdentity.from_fields({}) is None
        assert TaskIdentity.from_fields({"tenant": "acme"}) is None

    def test_both_halves_present_is_an_identity(self):
        identity = TaskIdentity.from_fields(
            {"context_id": "ctx-1", "task_id": "task-1"}
        )
        assert identity == TaskIdentity(context_id="ctx-1", task_id="task-1")

    @pytest.mark.parametrize("data", [
        {"context_id": "ctx-1"}, {"task_id": "task-1"},
    ])
    def test_exactly_one_half_is_an_error_not_a_partial_identity(self, data):
        """Dropping the supplied half would turn a binding attempt into none."""

        with pytest.raises(ValueError, match="needs both"):
            TaskIdentity.from_fields(data)

    def test_a_non_mapping_is_no_identity(self):
        assert TaskIdentity.from_fields(None) is None
        assert TaskIdentity.from_fields("ctx-1") is None


class TestComparison:
    def test_an_identity_matches_itself(self):
        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        assert a.matches(TaskIdentity(context_id="ctx-1", task_id="task-1"))

    def test_a_different_task_in_the_same_context_does_not_match(self):
        """The defect this module closes, at its smallest.

        Same context, same everything REMORA already binds, different task.
        """
        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        b = TaskIdentity(context_id="ctx-1", task_id="task-2")
        assert a.matches(b) is False
        assert a.differences(b) == ("task_id",)

    def test_the_same_task_id_in_another_context_does_not_match(self):
        """Task ids are only unique within a context."""

        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        b = TaskIdentity(context_id="ctx-2", task_id="task-1")
        assert a.matches(b) is False
        assert a.differences(b) == ("context_id",)

    def test_nothing_matches_none(self):
        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        assert a.matches(None) is False

    def test_unbound_is_reported_distinctly_from_mismatched(self):
        """A caller must tell "you bound no task" from "you bound another"."""

        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        assert a.differences(None) == ("task_unbound",)
        assert "task_unbound" not in a.differences(
            TaskIdentity(context_id="ctx-2", task_id="task-2")
        )

    def test_both_halves_differing_are_both_reported(self):
        a = TaskIdentity(context_id="ctx-1", task_id="task-1")
        b = TaskIdentity(context_id="ctx-2", task_id="task-2")
        assert set(a.differences(b)) == {"context_id", "task_id"}


class TestSignaturesIssuedBeforeThisModuleStillVerify:
    """The regression guard for the entire change.

    Every signed structure this feeds already has signatures in the field
    that a verifier recomputes from a payload. If an absent identity adds
    anything at all to that payload, every one of them stops verifying.
    """

    def test_an_absent_identity_contributes_no_fields(self):
        assert task_fields(None) == {}

    def test_an_absent_identity_leaves_the_payload_unchanged(self):
        payload = {"tenant": "acme", "tool": "read_telemetry"}
        assert merge_task_fields(payload, None) == payload

    def test_an_absent_identity_leaves_the_canonical_bytes_unchanged(self):
        """Stated in bytes, because bytes are what the verifier recomputes."""
        import json

        payload = {"tenant": "acme", "tool": "read_telemetry"}
        before = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        after = json.dumps(
            merge_task_fields(payload, None), sort_keys=True, separators=(",", ":")
        )
        assert before == after

    def test_a_null_valued_field_would_have_broken_it(self):
        """Pins why the rule is omission and not a null.

        This is the implementation that looks equivalent and is not: a
        null-valued key changes the preimage exactly as much as a populated
        one does.
        """
        import json

        payload = {"tenant": "acme"}
        naive = {**payload, "context_id": None, "task_id": None}
        assert json.dumps(naive, sort_keys=True) != json.dumps(payload, sort_keys=True)
        assert json.dumps(
            merge_task_fields(payload, None), sort_keys=True
        ) == json.dumps(payload, sort_keys=True)

    def test_a_present_identity_does_change_the_payload(self):
        """It must: the envelope now asserts something more than it did."""

        payload = {"tenant": "acme"}
        merged = merge_task_fields(
            payload, TaskIdentity(context_id="ctx-1", task_id="task-1")
        )
        assert merged == {
            "tenant": "acme", "context_id": "ctx-1", "task_id": "task-1"
        }


class TestRebindingIsRefused:
    def test_an_identity_already_in_the_payload_cannot_be_overwritten(self):
        """A silent overwrite would let a later layer rebind the task."""

        payload = {"context_id": "ctx-1", "task_id": "task-1"}
        with pytest.raises(TaskIdentityMismatch, match="refusing to rebind"):
            merge_task_fields(
                payload, TaskIdentity(context_id="ctx-1", task_id="task-2")
            )

    def test_folding_the_same_identity_twice_is_allowed(self):
        payload = {"context_id": "ctx-1", "task_id": "task-1"}
        identity = TaskIdentity(context_id="ctx-1", task_id="task-1")
        assert merge_task_fields(payload, identity) == payload

    def test_the_error_carries_the_taxonomy_code(self):
        assert TaskIdentityMismatch.code == "task_mismatch"
        assert TaskIdentityMismatch.category == "enforcement"
