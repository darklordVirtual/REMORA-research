#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Regenerate the AuthorizationContext preimage vectors.

``AuthorizationContext.hash()`` is signed into every ``PolicyDecisionToken``
issued since RMR-001 and is recomputed at redemption. Task-bound execution
authority adds ``context_id`` and ``task_id`` to that structure, so the
backward-compatibility guarantee needs to be checkable by someone who does
not trust the test suite: these vectors record the preimage the pre-change
implementation produced and assert the current one still matches it.

The pre-change form is reproduced here deliberately rather than imported.
Importing it would make the reference track the implementation, which is
exactly what the reference exists to detect.

    python scripts/generate_authorization_context_vectors.py [--check]

``--check`` regenerates in memory and fails if the committed artifact
differs, which is what CI runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "task_authority" / "authorization_context_preimage_v1.json"

#: The exact fields the six-key pre-change mapping carried, in the order
#: ``json.dumps(sort_keys=True)`` emits them.
_PRE_CHANGE_FIELDS = (
    "intent_authority_hash",
    "policy_bundle_hash",
    "principal",
    "target_environment",
    "tenant",
    "toolspec_hash",
)

CASES: tuple[dict, ...] = (
    {"name": "empty_context", "fields": {}},
    {
        "name": "fully_populated_context",
        "fields": {
            "tenant": "acme",
            "principal": "alice",
            "target_environment": "production",
            "policy_bundle_hash": "p" * 64,
            "toolspec_hash": "t" * 64,
            "intent_authority_hash": "i" * 64,
        },
    },
    {"name": "tenant_only", "fields": {"tenant": "acme"}},
)


def pre_change_preimage(fields: dict) -> str:
    """The canonical JSON the implementation produced before task binding."""
    return json.dumps(
        {name: fields.get(name, "") for name in _PRE_CHANGE_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
    )


def build() -> dict:
    from remora.enforcement.token import AuthorizationContext

    vectors = []
    for case in CASES:
        preimage = pre_change_preimage(case["fields"])
        expected = hashlib.sha256(preimage.encode()).hexdigest()
        actual = AuthorizationContext(**case["fields"]).hash()
        vectors.append(
            {
                "name": case["name"],
                "fields": case["fields"],
                "pre_change_preimage": preimage,
                "pre_change_sha256": expected,
                "post_change_sha256": actual,
                "identical": actual == expected,
            }
        )

    bound = AuthorizationContext(tenant="acme", context_id="ctx-1", task_id="task-1")
    unbound = AuthorizationContext(tenant="acme")
    return {
        "artifact": "authorization_context_preimage_v1",
        "purpose": (
            "AuthorizationContext.hash() is signed into every "
            "PolicyDecisionToken issued since RMR-001 and is recomputed at "
            "redemption. Task-bound execution authority adds context_id and "
            "task_id to that structure. These vectors record that a context "
            "carrying no task identity produces a byte-identical preimage, "
            "and therefore an identical hash, to what it produced before "
            "those fields existed."
        ),
        "rule": (
            "Absent task fields are OMITTED from the preimage, never "
            "defaulted to the empty string. A key present with an empty "
            "value changes the preimage exactly as much as a populated one "
            "would."
        ),
        "vectors": vectors,
        "a_bound_context_differs": {
            "unbound_sha256": unbound.hash(),
            "bound_sha256": bound.hash(),
            "differs": unbound.hash() != bound.hash(),
            "note": "It must differ: the bound context asserts something more.",
        },
        "regenerate": "python scripts/generate_authorization_context_vectors.py",
        "design": (
            "docs/design/task-bound-execution-authority-v1.md"
        ),
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed artifact is out of date")
    args = parser.parse_args()

    doc = build()
    stale = [v["name"] for v in doc["vectors"] if not v["identical"]]
    if stale:
        print(
            "FAIL: the hash of a context with no task identity changed for: "
            + ", ".join(stale)
            + "\nEvery PolicyDecisionToken issued since RMR-001 would stop "
              "verifying. This is not a vector to regenerate; it is a bug.",
            file=sys.stderr,
        )
        return 1

    rendered = render(doc)
    if args.check:
        if not ARTIFACT.exists():
            print(f"FAIL: {ARTIFACT} does not exist", file=sys.stderr)
            return 1
        if ARTIFACT.read_text(encoding="utf-8") != rendered:
            print(
                f"FAIL: {ARTIFACT} is out of date; regenerate it with\n"
                f"  python {Path(__file__).relative_to(ROOT).as_posix()}",
                file=sys.stderr,
            )
            return 1
        print(f"[OK  ] {ARTIFACT.relative_to(ROOT).as_posix()} reproduces exactly")
        return 0

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(rendered, encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(ROOT).as_posix()} ({len(doc['vectors'])} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
