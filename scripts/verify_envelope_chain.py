#!/usr/bin/env python3
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Verify a persisted REMORA DecisionEnvelope trail.

Shadow mode is only evidence if a third party can re-check the record after
the run. This script does exactly that: it reads a stored trail and
recomputes the hash chain from scratch, so a deleted, reordered, or edited
decision is detected rather than assumed absent.

Three sources are supported:

  * a replay envelope JSONL (``artifacts/shadow_mode/decision_envelopes.jsonl``)
  * a SQLite control-plane store written by the API or by
    ``shadow_replay.py --store-db`` (linkage check across a tenant)
  * an export from the agent-control Worker's ``GET /envelopes`` endpoint,
    re-derived here so an auditor never has to trust the Worker's own
    verify endpoint

Exit codes: 0 = chain intact, 1 = chain broken, 2 = usage/IO error.

Example — verify a live Worker chain off-platform::

    curl -sH "Authorization: Bearer $CONTROL_SECRET" \\
      "https://<worker>/envelopes?limit=200" > chain.json
    python scripts/verify_envelope_chain.py --worker-export chain.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from remora.adapters.storage import (  # noqa: E402
    SQLiteControlPlaneStore,
    verify_audit_record_chain,
)
from remora.governance.tenant_chain import verify_exported_chain  # noqa: E402
from remora.shadow.replay import verify_envelope_file  # noqa: E402


def _verify_jsonl(path: str) -> tuple[bool, list[str], int, str]:
    from remora.shadow.replay import load_envelopes_jsonl

    envelopes = load_envelopes_jsonl(path)
    ok, breaks = verify_envelope_file(path)
    return ok, breaks, len(envelopes), "full_payload_recompute"


def _verify_sqlite(db_path: str, tenant_id: str) -> tuple[bool, list[str], int, str]:
    store = SQLiteControlPlaneStore(db_path=db_path)
    records = store.list_audit_records_for_tenant(tenant_id=tenant_id)
    ok, breaks = verify_audit_record_chain(records)
    return ok, breaks, len(records), "chain_linkage"


def _verify_worker_export(path: str, signing_key: str | None) -> tuple[bool, list[str], int, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    # Accept either the raw endpoint response {"rows": [...]} or a bare list.
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list of chain rows or an object with 'rows'")
    rows = sorted(rows, key=lambda r: int(r.get("sequence_no", 0)))
    ok, problems = verify_exported_chain(rows, signing_key=signing_key)
    return ok, problems, len(rows), "worker_chain_recompute"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a persisted REMORA DecisionEnvelope trail",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--envelopes",
        help="Path to a DecisionEnvelope JSONL produced by shadow replay.",
    )
    source.add_argument(
        "--store-db",
        help="Path to a SQLite control-plane store.",
    )
    source.add_argument(
        "--worker-export",
        help="JSON saved from the agent-control Worker's GET /envelopes endpoint.",
    )
    parser.add_argument(
        "--signing-key",
        default=None,
        help=(
            "HMAC key for --worker-export signature checks. Falls back to "
            "REMORA_AUDIT_SIGNING_KEY. Omit to check linkage and payload "
            "hashes only."
        ),
    )
    parser.add_argument(
        "--tenant",
        default="shadow",
        help="Tenant id to verify when reading a SQLite store (default: shadow).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable result instead of human-readable text.",
    )
    args = parser.parse_args()

    try:
        if args.envelopes:
            source_label = args.envelopes
            ok, breaks, count, method = _verify_jsonl(args.envelopes)
        elif args.worker_export:
            source_label = args.worker_export
            ok, breaks, count, method = _verify_worker_export(
                args.worker_export, args.signing_key
            )
        else:
            source_label = f"{args.store_db}[tenant={args.tenant}]"
            ok, breaks, count, method = _verify_sqlite(args.store_db, args.tenant)
    except (OSError, ValueError) as exc:
        print(f"verify_envelope_chain: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(
            {
                "source": source_label,
                "method": method,
                "records_checked": count,
                "chain_valid": ok,
                "breaks": breaks,
            },
            indent=2,
        ))
    else:
        print(f"Source:          {source_label}")
        print(f"Method:          {method}")
        print(f"Records checked: {count}")
        print(f"Chain valid:     {'yes' if ok else 'NO'}")
        for line in breaks:
            print(f"  - {line}")
        if count == 0:
            # An empty trail trivially "verifies". Say so, rather than letting
            # a green result imply decisions were recorded.
            print(
                "Note: no records found — an empty trail proves nothing about "
                "what the system decided."
            )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
