#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Shadow measurement for surface binding (quality program Q3.2).

The design asks for a shadow period before enforcement: how often does the
observed tool surface change between assessment and dispatch on legitimate
runs? Enforcing a binding that fires on correct work would get it switched
off. This script runs the REMORA reference runtime in shadow mode:

* ``legitimate``: assess, lease with the assessed surface digest, dispatch,
  with nothing changed in between; repeated ``RUNS`` times.
* ``perturbed``: the same, with an extra tool registered between assessment
  and dispatch, which is the change the binding exists to catch.

It then repeats the perturbed case with the dispatcher enforcing the lease's
surface digest. The artifact records
counts only, never digests, so it is deterministic.

    python scripts/measure_surface_binding_shadow.py [--check]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ARTIFACT = ROOT / "artifacts" / "runtime_surface" / "surface_binding_shadow_v1.json"
RUNS = 200
PERTURBED = 20


def _cycle(enforce_lease: bool, perturb: bool) -> tuple[bool, str | None, int, int]:
    """One assess-lease-dispatch cycle. The runtime stays in shadow so that its
    own continuity check does not pre-empt the lease binding being measured;
    ``enforce_lease`` makes the dispatcher enforce the lease's surface digest,
    as an executor that trusts only the lease would."""
    from remora.toolcall.surface_evaluation import reference_lease, reference_runtime

    with TemporaryDirectory(prefix="remora-shadow-") as directory:
        runtime, _, _, spec = reference_runtime(Path(directory), mode="shadow")
        runtime.dispatcher.bind_surface_observer(
            lambda: runtime.snapshot().digest(), enforce=enforce_lease)
        assessment = runtime.assess("write", {"value": 1}, tenant="reference",
                                    principal="reference-agent", target="local-record")
        if perturb:
            runtime.dispatcher.register("shell", lambda args: args)
        outcome = runtime.dispatch(
            assessment.assessment_id,
            reference_lease(spec, surface_digest=assessment.surface.digest()),
            "write", {"value": 1}, tenant="reference", principal="reference-agent",
            target="local-record")
        dispatcher = runtime.dispatcher
        return (outcome.execution.executed, outcome.execution.refusal_reason,
                dispatcher.surface_checks, dispatcher.surface_changes)


def build() -> dict:
    os.environ.setdefault("REMORA_LEASE_SIGNING_KEY", "surface-shadow-key")
    for name in ("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE",
                 "REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC", "REMORA_RUNTIME_PROFILE"):
        os.environ.pop(name, None)
    legitimate = [_cycle(False, False) for _ in range(RUNS)]
    perturbed = [_cycle(False, True) for _ in range(PERTURBED)]
    enforced = [_cycle(True, True) for _ in range(PERTURBED)]
    return {
        "artifact": "surface_binding_shadow_v1",
        "generator": "scripts/measure_surface_binding_shadow.py",
        "question": "How often does the observed surface change between assessment and "
                    "dispatch on legitimate runs, and is a real change caught?",
        "legitimate_runs": {
            "runs": RUNS,
            "compared": sum(c[2] for c in legitimate),
            "surface_changed": sum(c[3] for c in legitimate),
            "executed": sum(1 for c in legitimate if c[0]),
        },
        "perturbed_runs_shadow": {
            "runs": PERTURBED,
            "surface_changed": sum(c[3] for c in perturbed),
            "refused_by_surface_binding": sum(1 for c in perturbed if c[1] == "surface_changed"),
        },
        "perturbed_runs_enforced": {
            "runs": PERTURBED,
            "surface_changed": sum(c[3] for c in enforced),
            "refused": sum(1 for c in enforced if not c[0]),
            "refusal_reasons": sorted({str(c[1]) for c in enforced}),
        },
        "scope": ("REMORA's own reference runtime only, one tool, one process. Says "
                  "nothing about how often an external agent host's surface changes "
                  "on legitimate runs; that needs Q3.1 on a named host."),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not ARTIFACT.exists() or ARTIFACT.read_text(encoding="utf-8") != text:
            print(f"[FAIL] {ARTIFACT.relative_to(ROOT)} is stale; regenerate it")
            return 1
        print(f"[PASS] {ARTIFACT.relative_to(ROOT)} reproduces")
        return 0
    ARTIFACT.write_text(text, encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
