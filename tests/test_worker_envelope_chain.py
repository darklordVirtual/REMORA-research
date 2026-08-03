# SPDX-License-Identifier: BUSL-1.1
"""Cross-language contract between the agent-control Worker and Python.

The Worker writes the live DecisionEnvelope chain in TypeScript; auditors
verify it in Python. If the two disagree on canonical JSON or on the entry
hash, either an intact chain reads as tampered or a tampered one reads as
intact. Both failures are unacceptable, so the agreement is pinned here
rather than assumed.

The tests execute the real Worker module (bundled with the esbuild already
vendored in the worker directory) instead of a Python reimplementation of it
— a reimplementation would only prove that two copies of the same belief
agree. They skip when node or esbuild is unavailable, which keeps the
deterministic suite runnable without a JS toolchain.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from remora.governance.tenant_chain import (
    compute_entry_hash_from_canonical,
    verify_exported_chain,
)
from remora.policy.observation import canonical_tool_call_hash

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKER_DIR = _REPO_ROOT / "workers" / "agent-control"
_ENVELOPE_TS = _WORKER_DIR / "src" / "envelope.ts"

# Deliberately awkward payloads: Norwegian letters, an en dash, an emoji
# (surrogate pair), a tab, nested objects with unsorted keys, and null.
_CASES: list[dict] = [
    {"a": 1, "b": "x"},
    {"æøå": "Blåbærsyltetøy", "z": [1, 2, {"k": None}], "nested": {"b": True, "a": False}},
    {"claim": "GDPR art. 17 – retten til sletting", "top_k": 5},
    {"emoji": "🚀", "tab": "a\tb"},
]


def _python_canonical(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _skip_unless_js_toolchain() -> None:
    if not _ENVELOPE_TS.exists():
        pytest.skip("worker envelope module not present")
    if shutil.which("node") is None:
        pytest.skip("node not available")
    if not (_WORKER_DIR / "node_modules" / "esbuild").exists():
        pytest.skip("esbuild not installed in workers/agent-control")


def _run_worker_vectors(tmp_path: Path) -> list[str]:
    """Bundle the Worker envelope module and emit its own hash vectors."""
    bundle = tmp_path / "envelope.mjs"
    subprocess.run(
        [
            "npx", "esbuild", str(_ENVELOPE_TS),
            "--bundle", "--format=esm", "--platform=node",
            f"--outfile={bundle}",
        ],
        cwd=_WORKER_DIR,
        check=True,
        capture_output=True,
        shell=os.name == "nt",
    )

    driver = tmp_path / "vectors.mjs"
    driver.write_text(
        # ESM on Windows requires a file:// URL, not a bare absolute path.
        "import { canonicalJson, computeEntryHash, canonicalToolCallHash } "
        f"from {json.dumps(bundle.as_uri())};\n"
        f"const cases = {json.dumps(_CASES)};\n"
        "const out = cases.map(canonicalJson);\n"
        "out.push(await computeEntryHash('0'.repeat(64), canonicalJson(cases[1]), "
        "'tenant-a', 0, '2026-08-03T10:00:00Z'));\n"
        "out.push(await canonicalToolCallHash('store_artifact', cases[2], "
        "'tenant-a', 'cloudflare_worker'));\n"
        "console.log(JSON.stringify(out));\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["node", str(driver)],
        cwd=_WORKER_DIR,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_worker_and_python_agree_on_canonical_json_and_hashes(tmp_path: Path) -> None:
    _skip_unless_js_toolchain()
    worker = _run_worker_vectors(tmp_path)

    expected = [_python_canonical(case) for case in _CASES]
    expected.append(
        compute_entry_hash_from_canonical(
            "0" * 64,
            _python_canonical(_CASES[1]),
            "tenant-a",
            0,
            "2026-08-03T10:00:00Z",
        )
    )
    expected.append(
        canonical_tool_call_hash(
            name="store_artifact",
            arguments=_CASES[2],
            tenant="tenant-a",
            target="cloudflare_worker",
        )
    )

    assert worker == expected


# ── Off-platform verification of an exported Worker chain ─────────────────────


def _chain_rows(count: int = 3, tenant: str = "t1") -> list[dict]:
    """Build a chain the way the Worker does, using the shared hash contract."""
    rows: list[dict] = []
    previous = "0" * 64
    for seq in range(count):
        canonical = _python_canonical(
            {
                "audit": {"tenant_id": tenant, "hash": None, "previous_hash": previous},
                "gate": {"outcome": "accept"},
                "request": {"request_id": f"req-{seq}"},
            }
        )
        created_at = f"2026-08-03T10:0{seq}:00.000Z"
        entry_hash = compute_entry_hash_from_canonical(
            previous, canonical, tenant, seq, created_at
        )
        rows.append(
            {
                "sequence_no": seq,
                "created_at": created_at,
                "envelope_canonical": canonical,
                "previous_hash": previous,
                "entry_hash": entry_hash,
                "signature": "",
            }
        )
        previous = entry_hash
    return rows


def test_exported_worker_chain_verifies() -> None:
    ok, problems = verify_exported_chain(_chain_rows())
    assert ok is True, problems


def test_exported_chain_detects_an_edited_envelope() -> None:
    """Rewriting a stored decision must break the hash it committed to."""
    rows = _chain_rows()
    payload = json.loads(rows[1]["envelope_canonical"])
    payload["gate"]["outcome"] = "escalate"
    rows[1]["envelope_canonical"] = _python_canonical(payload)

    ok, problems = verify_exported_chain(rows)
    assert ok is False
    assert "hash_mismatch_at:1" in problems


def test_exported_chain_detects_a_deleted_entry() -> None:
    rows = _chain_rows()
    del rows[1]
    ok, problems = verify_exported_chain(rows)
    assert ok is False
    assert any(p.startswith("chain_break_at") or p.startswith("sequence_gap_at") for p in problems)


def test_exported_chain_reports_a_stripped_signature() -> None:
    """With a key configured, an unsigned row is evidence of stripping."""
    rows = _chain_rows()
    ok, problems = verify_exported_chain(rows, signing_key="test-key")
    assert ok is False
    assert all(p.startswith("signature_missing_at") for p in problems)


def test_exported_chain_reports_unreadable_payload() -> None:
    rows = _chain_rows()
    rows[1]["envelope_canonical"] = "{not json"
    ok, problems = verify_exported_chain(rows)
    assert ok is False
    assert any(p.startswith("unreadable_payload_at:1") for p in problems)
