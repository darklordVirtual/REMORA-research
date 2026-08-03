# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Machine-checked contract claims for the documentation surface.

Born from the 2026-08-03 repository truth-sync: several governed documents
carried statements the code contradicted (a rate limiter described as absent,
env vars and symbols that do not exist, audit snapshots presented as current
state). Each check here pins a fact that was verified against source during
that sync, so the same drift cannot return silently.

Scope: live documentation only. ``docs/archive/`` is exempt by design —
history is allowed to be wrong about the present.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REGISTER = DOCS / "assurance" / "document_register_v1.yaml"

ROOT_DOCS = ("README.md", "ARCHITECTURE.md", "NEGATIVE_RESULTS.md",
             "SECURITY.md", "EVIDENCE_OF_CAPABILITY.md")

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
#: against a specific commit must say, near the top, that it is a snapshot —
#: otherwise it reads as a statement about the present.
COMMIT_PIN_RE = re.compile(
    r"(verified against commit|commit audited)[:\s]+\**`?[0-9a-f]{6,}", re.I
)
VINTAGE_MARKERS = ("historical", "snapshot", "superseded", "archived",
                   "do not cite", "vintage")


def _live_docs() -> list[Path]:
    docs = [p for p in DOCS.rglob("*.md")
            if "archive" not in p.relative_to(DOCS).parts]
    docs += [ROOT / name for name in ROOT_DOCS if (ROOT / name).exists()]
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
        head = "\n".join(text.splitlines()[:20]).lower()
        if not any(marker in head for marker in VINTAGE_MARKERS):
            offenders.append(
                f"{doc.relative_to(ROOT)}: pins a verification commit but has "
                f"no vintage marker in its first 20 lines "
                f"(one of {sorted(VINTAGE_MARKERS)})"
            )
    assert not offenders, "\n".join(offenders)


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
