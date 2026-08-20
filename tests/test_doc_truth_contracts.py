# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Machine-checked contract claims for the documentation surface.

Born from the 2026-08-03 repository truth-sync: several governed documents
carried statements the code contradicted (a rate limiter described as absent,
env vars and symbols that do not exist, audit snapshots presented as current
state). Each check here pins a fact that was verified against source during
that sync, so the same drift cannot return silently.

Scope: live documentation only, as classified by the document register —
``historical`` and ``superseded`` entries are exempt by design (history is
allowed to be wrong about the present, and forcing a snapshot to rewrite its
original findings to pass CI would defeat its purpose). A doc missing from
the register is treated as live: unclassified must not mean unchecked.
"""
from __future__ import annotations

import pytest

import importlib.util
import re
from pathlib import Path

import yaml

#: Documentation/register consistency gate, not a behaviour test.
#: Split out so a documentation drift and a governance regression do
#: not fail the same way (self-review 2026-08-20).
pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parents[1]


def _load_governance_module():
    module_path = ROOT / "scripts" / "check_document_governance.py"
    spec = importlib.util.spec_from_file_location(
        "check_document_governance", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_cdg = _load_governance_module()
#: Single source of truth: the banner contract the governance validator
#: enforces on historical register entries is the same one commit-pinned
#: live docs must satisfy. Defined in scripts/check_document_governance.py.
VINTAGE_BANNER_RE = _cdg.VINTAGE_BANNER_RE
DOCS = ROOT / "docs"
REGISTER = DOCS / "assurance" / "document_register_v1.yaml"

ROOT_DOCS = ("README.md", "ARCHITECTURE.md", "NEGATIVE_RESULTS.md",
             "SECURITY.md", "EVIDENCE_OF_CAPABILITY.md")

#: Register statuses whose documents speak about the present.
LIVE_STATUSES = {"canonical", "generated", "supporting", "proposal"}

#: Claims verified FALSE against source on 2026-08-03. Each tuple is
#: (regex, why it is false). A hit in a live doc is a regression, not a style
#: issue: every one of these shipped in a document marked verified/current.
KNOWN_FALSE_CLAIMS: tuple[tuple[str, str], ...] = (
    (r"REMORA_API_DEFAULT_ROLE",
     "env var does not exist anywhere in the codebase; roles come from "
     "servers/api.py:_authenticate()"),
    (r"_auth_token_data",
     "function does not exist; the bearer-token path is "
     "servers/api.py:_authenticate() / _load_token_table()"),
    (r"_require_capability\b(?!\w)",
     "symbol does not exist; the real check is _require_tenant_capability()"),
    (r"no rate limiting (?:is )?(?:currently )?implemented",
     "servers/api.py:_InMemoryRateLimiter gates /v1/assess per tenant "
     "(default 120/min); the true residual gap is edge/cross-replica scope"),
    (r"legacy no-expiry tokens are still accepted",
     "remora/enforcement/token.py:verify() rejects a token without "
     "expires_at outright (missing_expiry)"),
)

#: A commit pin is a vintage statement. A live doc that says it was verified
#: against a specific commit must open with a structured vintage banner —
#: otherwise it reads as a statement about the present.
COMMIT_PIN_RE = re.compile(
    r"(verified against commit|commit audited)[:\s]+\**`?[0-9a-f]{6,}", re.I
)
#: Structured banner contract, not a substring: a block-quote line carrying
#: a bold span with a vintage keyword (HTML assets use a comment banner).
#: "This is not a historical document." must NOT satisfy it — a loose token
#: is exactly the weakness the old `effect` substring check had.


def _register_status_by_path() -> dict[str, str]:
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    return {e.get("path", ""): e.get("status", "")
            for e in register["documents"]}


def _live_docs() -> list[Path]:
    """Docs classified live by the register, plus any unregistered doc."""
    status_by_path = _register_status_by_path()
    docs = []
    candidates = [p for p in DOCS.rglob("*.md")
                  if "archive" not in p.relative_to(DOCS).parts]
    candidates += [ROOT / name for name in ROOT_DOCS if (ROOT / name).exists()]
    for path in candidates:
        rel = path.relative_to(ROOT).as_posix()
        status = status_by_path.get(rel)
        if status is not None and status not in LIVE_STATUSES:
            continue  # historical/superseded: history may disagree with today
        docs.append(path)
    return docs


def test_no_known_false_contract_claims_in_live_docs() -> None:
    offenders: list[str] = []
    for doc in _live_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for pattern, why in KNOWN_FALSE_CLAIMS:
            for m in re.finditer(pattern, text, re.I):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(
                    f"{doc.relative_to(ROOT)}:{line}: matches {pattern!r} — {why}"
                )
    assert not offenders, (
        "documents restate claims verified false against source:\n  "
        + "\n  ".join(offenders)
    )


def test_commit_pinned_docs_declare_their_vintage() -> None:
    offenders: list[str] = []
    for doc in _live_docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        if not COMMIT_PIN_RE.search(text):
            continue
        head = "\n".join(text.splitlines()[:20])
        if not VINTAGE_BANNER_RE.search(head):
            offenders.append(
                f"{doc.relative_to(ROOT)}: pins a verification commit but its "
                f"first 20 lines have no structured vintage banner "
                f"(a block-quote line with a bold vintage span, e.g. "
                f"'> **Historical ...**'); a loose mention of the word "
                f"does not count"
            )
    assert not offenders, "\n".join(offenders)


def test_vintage_banner_contract_rejects_loose_tokens() -> None:
    """Negative control: the banner regex must be structural.

    The old `effect` drift check accepted a bare token anywhere in the file;
    this pins that the vintage contract does not repeat that mistake.
    """
    assert not VINTAGE_BANNER_RE.search("This is not a historical document.")
    assert not VINTAGE_BANNER_RE.search(
        "the archive keeps every snapshot and historical record"
    )
    assert not VINTAGE_BANNER_RE.search(
        "An archived snapshot of the proof is kept for reference."
    )
    assert VINTAGE_BANNER_RE.search(
        "> **Historical audit snapshot — do not cite as current state.**"
    )
    assert VINTAGE_BANNER_RE.search("> **Verification-vintage notice.**")
    assert VINTAGE_BANNER_RE.search(
        "> **ARCHIVED — historical document.** Superseded; preserved as record."
    )
    assert VINTAGE_BANNER_RE.search(
        "> **NOTICE:** This document is **HISTORICAL** and has been archived."
    )
    assert VINTAGE_BANNER_RE.search(
        "<!-- ARCHIVED - historical asset. Superseded; do not cite. -->"
    )


def test_audit_snapshots_stay_reclassified() -> None:
    """The two dated audit reports must not silently return to canonical.

    They audited commits 2cd573d (2026-06-30) and the 2026-07-03 tree; their
    findings are false as statements about current code. Promoting them back
    to canonical/current requires an actual revalidation — in which case this
    pin is updated deliberately, in the same commit, with that evidence.
    """
    register = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
    by_path = {e.get("path"): e for e in register["documents"]}
    for path in (
        "docs/assurance/policy_engine_audit_v1.md",
        "docs/assurance/ai_assisted_adversarial_security_review_v1.md",
    ):
        entry = by_path[path]
        assert entry["status"] == "historical", (
            f"{path}: expected status 'historical', found {entry['status']!r}"
        )
        assert entry["verdict"] != "current", (
            f"{path}: a dated audit snapshot must not carry verdict 'current'"
        )
        assert entry["code_synced"] == "mismatch", (
            f"{path}: a snapshot whose findings are false about current code "
            f"must record code_synced 'mismatch', found "
            f"{entry['code_synced']!r} — 'verified' would tell a machine "
            f"reader the opposite of the truth"
        )
