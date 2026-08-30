# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""An approval granted under one task must not authorise another.

REMORA binds an authorization to the exact call it was granted for and
recomputes that binding before dispatch. It did not bind it to the task the
call was made under, so an approval for task A authorised the identical call
under task B with every existing binding still holding.

The class that carries the change is
``TestContextsWithoutATaskHashExactlyAsBefore``. If it fails, tokens already
issued stop verifying and the change is unshippable regardless of the rest.

Design: docs/superpowers/specs/2026-08-30-task-bound-execution-authority-design.md
"""
from __future__ import annotations

import pytest

from remora.enforcement.token import AuthorizationContext
from remora.governance.task_identity import TaskIdentity


def _ctx(**kwargs) -> AuthorizationContext:
    base = dict(
        tenant="acme",
        principal="alice",
        target_environment="production",
        policy_bundle_hash="p" * 64,
        toolspec_hash="t" * 64,
        intent_authority_hash="i" * 64,
    )
    base.update(kwargs)
    return AuthorizationContext(**base)


class TestContextsWithoutATaskHashExactlyAsBefore:
    """The regression guard. Nothing else matters if this fails.

    ``context_hash`` is signed into every token issued since RMR-001 and is
    recomputed at redemption. A context carrying no task identity must
    produce the identical hash it produced before these fields existed.
    """

    #: Computed from the pre-change implementation, which built a fixed
    #: six-key mapping. Hard-coded rather than recomputed, so this test
    #: fails if the preimage ever changes for any reason at all.
    PRE_CHANGE_PREIMAGE = (
        '{"intent_authority_hash":"%s","policy_bundle_hash":"%s",'
        '"principal":"alice","target_environment":"production",'
        '"tenant":"acme","toolspec_hash":"%s"}'
    ) % ("i" * 64, "p" * 64, "t" * 64)

    def test_the_preimage_is_unchanged_for_an_unbound_context(self):
        import hashlib

        expected = hashlib.sha256(self.PRE_CHANGE_PREIMAGE.encode()).hexdigest()
        assert _ctx().hash() == expected

    def test_empty_task_fields_are_omitted_not_defaulted(self):
        """The implementation that looks equivalent and is not.

        Defaulting to "" would put the keys in the preimage and rewrite the
        hash of every context that never had a task.
        """
        assert _ctx(context_id="", task_id="").hash() == _ctx().hash()

    def test_a_bound_context_does_hash_differently(self):
        """It must: the context now asserts something more than it did."""

        assert _ctx(context_id="ctx-1", task_id="task-1").hash() != _ctx().hash()


class TestAnApprovalDoesNotCrossTasks:
    """The defect, stated at the level the refusal happens."""

    def test_the_same_call_under_another_task_is_a_different_context(self):
        granted = _ctx(context_id="ctx-1", task_id="task-1")
        replayed = _ctx(context_id="ctx-1", task_id="task-2")

        assert granted.hash() != replayed.hash()
        assert granted.differences(replayed) == ["task_id"]

    def test_everything_remora_already_bound_is_identical(self):
        """Pins that no pre-existing binding would have caught this.

        Same tool contract, same policy bundle, same principal, same tenant,
        same target, same intent authority. Only the task differs.
        """
        granted = _ctx(context_id="ctx-1", task_id="task-1")
        replayed = _ctx(context_id="ctx-1", task_id="task-2")

        for field in (
            "tenant", "principal", "target_environment",
            "policy_bundle_hash", "toolspec_hash", "intent_authority_hash",
        ):
            assert getattr(granted, field) == getattr(replayed, field)

    def test_the_same_task_id_in_another_context_is_a_different_context(self):
        granted = _ctx(context_id="ctx-1", task_id="task-1")
        other = _ctx(context_id="ctx-2", task_id="task-1")

        assert granted.hash() != other.hash()
        assert granted.differences(other) == ["context_id"]

    def test_an_unbound_context_differs_from_a_bound_one(self):
        assert _ctx().differences(_ctx(context_id="c", task_id="t")) == [
            "context_id", "task_id"
        ]


class TestTaskIdentityReadBack:
    def test_a_bound_context_yields_its_identity(self):
        ctx = _ctx(context_id="ctx-1", task_id="task-1")
        assert ctx.task_identity() == TaskIdentity(
            context_id="ctx-1", task_id="task-1"
        )

    def test_an_unbound_context_yields_none(self):
        assert _ctx().task_identity() is None

    @pytest.mark.parametrize("kwargs", [
        {"context_id": "ctx-1"}, {"task_id": "task-1"},
    ])
    def test_half_a_binding_is_refused_rather_than_silently_dropped(self, kwargs):
        """Dropping the supplied half turns a binding attempt into none."""

        with pytest.raises(ValueError, match="needs both"):
            _ctx(**kwargs).task_identity()

    def test_the_identity_round_trips_through_the_context(self):
        identity = TaskIdentity(context_id="ctx-9", task_id="task-9")
        ctx = _ctx(context_id=identity.context_id, task_id=identity.task_id)
        assert identity.matches(ctx.task_identity())


class TestTheCommittedArtifactReproduces:
    """The backward-compatibility guarantee as a committed reference.

    A replicator who does not trust the test suite can recompute the
    preimages from the artifact and check them against the code.
    """

    def test_the_artifact_is_current(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/generate_authorization_context_vectors.py",
             "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_every_committed_vector_reports_an_unchanged_hash(self):
        import json
        import pathlib

        doc = json.loads(
            pathlib.Path(
                "artifacts/task_authority/authorization_context_preimage_v1.json"
            ).read_text(encoding="utf-8")
        )
        assert doc["vectors"], "the artifact carries no vectors"
        for vector in doc["vectors"]:
            assert vector["identical"], vector["name"]
            assert vector["pre_change_sha256"] == vector["post_change_sha256"]

    def test_the_artifact_records_that_a_bound_context_differs(self):
        import json
        import pathlib

        doc = json.loads(
            pathlib.Path(
                "artifacts/task_authority/authorization_context_preimage_v1.json"
            ).read_text(encoding="utf-8")
        )
        assert doc["a_bound_context_differs"]["differs"] is True
