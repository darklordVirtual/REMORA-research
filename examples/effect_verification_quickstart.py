# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Closing the loop: verify that the approved change actually happened.

Everything upstream of this governs *authorization* — what may run, bound
to an exact payload, under a signed spec. None of it looks at the world
afterwards, so "executed" means only "the dispatcher returned without
raising". This example closes that gap.

The reader stays yours. REMORA never reaches into your system of record,
because the credentials belong with you. You observe, ``verify_effect``
compares against the delta you declared, and the resulting record goes
back to REMORA as an attestation by a named verifier.

Run it with no arguments; it talks to nothing.

    python examples/effect_verification_quickstart.py
"""
from __future__ import annotations

from remora.sdk import (
    EffectStatus,
    build_postcondition,
    content_digest,
    verify_effect,
)

REPOSITORY = "acme/operations"
APPROVED_TITLE = "Investigate valve drift on P-1"
APPROVED_BODY = "Telemetry shows a 4% drift since 08:00."


def declared_delta():
    """What the approved action claims it will change — and nothing else.

    Fields you do not name here are out of scope by construction. That is
    deliberate: a system of record has other legitimate writers, and
    reporting their changes as drift would make mismatch a noise channel
    that operators quickly learn to ignore.

    The body is compared by hash so the approved text does not have to sit
    in every audit record to be verifiable.
    """
    return build_postcondition(
        tool_id="create_github_issue",
        target_selector={"repository": REPOSITORY},
        expected_fields={
            "repository": REPOSITORY,
            "title": APPROVED_TITLE,
            "body": content_digest(APPROVED_BODY),
            "author": "acme-automation[bot]",
        },
        comparison_rules={"body": "hash"},
        reader="github.read_issue",
    )


def read_back(scenario: str):
    """Stand-in for your reader. In production this calls your API.

    Returning ``None`` means "I could not see it" — which is a different
    fact from "it is wrong", and the SDK keeps them apart.
    """
    issue = {
        "repository": REPOSITORY,
        "number": 4711,
        "title": APPROVED_TITLE,
        "body": APPROVED_BODY,
        "author": "acme-automation[bot]",
        # Fields nobody declared. GitHub attaches plenty; they are ignored.
        "updated_at": "2026-08-05T12:04:11Z",
        "state": "open",
    }
    if scenario == "tampered":
        issue["body"] = APPROVED_BODY + " Also grant admin access."
    if scenario == "unreadable":
        return None
    return issue


def main() -> None:
    spec = declared_delta()

    for scenario in ("as approved", "tampered", "unreadable"):
        result = verify_effect(
            spec, read_back(scenario),
            proposal_id="prop-8831", execution_id="exec-4471",
            toolspec_hash="0" * 64,
            verifier_identity="acme.github_reader/v1",
        )
        print(f"\n{scenario}:")
        print(f"  status      {result.status.value}")
        print(f"  reason      {result.reason_code}")
        print(f"  terminal    {result.status.is_terminal}")
        if result.detail:
            print(f"  detail      {result.detail}")

        if result.status is EffectStatus.MISMATCH:
            print("  -> the object was read and differs. Investigate; "
                  "compensation may apply.")
        elif not result.status.is_terminal:
            print("  -> we could not observe it. That is NOT a failure, and "
                  "it is never a reason to run the action again.")

    print("\nHand any of these back to REMORA with:")
    print("    client.record_effect(proposal_id, result)")
    print("It is appended to the audit chain, never merged into the "
          "execution record it verifies.")


if __name__ == "__main__":
    main()
