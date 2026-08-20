# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""A document may not claim a sealed run is pending after it has been run.

On 2026-08-19 the C-ext3 track was sealed, evaluated once, and published as
CLAIM-019. Its own pre-registration kept saying **"sealed run NOT yet
executed"** for a full day, and so did the documentation index. Nothing
caught it: the documentation-governance gate checks register bookkeeping —
status enums, canonical uniqueness, ID uniqueness — not whether a document's
factual claim still matches the repository.

This closes that specific hole. A sealed holdout has exactly one
irreversible state transition (`sealed_never_run` → `locked_never_run` →
`evaluated`), the manifest records it, and a live document that contradicts
it is stating something false about the strongest evidence the project has.

The check is deliberately narrow: it does not try to validate prose in
general, only the one claim whose truth value flips at a known moment and
whose ground truth is machine-readable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.docgate

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

#: Phrases that ASSERT, in the present tense, that a run has not happened.
#: Deliberately excludes the state names `sealed_never_run` and
#: `locked_never_run`: a document that describes the sealing protocol names
#: those states legitimately, and flagging that would train people to write
#: around the gate instead of keeping the protocol documented.
_PENDING_PHRASES: tuple[str, ...] = (
    "not yet executed",
    "sealed run pending",
    "run pending",
    "awaiting the sealed run",
)

#: A document that records its execution has already answered the question.
#: Only text ABOVE that record is the document's current status claim; below
#: it sits the frozen pre-registration, which must not be rewritten.
_EXECUTION_RECORD = re.compile(r"EXECUTED\s+20\d\d-\d\d-\d\d")

#: Documents that are historical records by construction: they describe what
#: was true at a past moment and must not be rewritten to match today.
_HISTORICAL_PREFIXES: tuple[str, ...] = ("archive/",)


def _tracks() -> dict[str, dict]:
    """Directory name → manifest, for every sealed holdout that has a status."""
    out: dict[str, dict] = {}
    for manifest_path in sorted(DATA.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status"):
            out[manifest_path.parent.name] = manifest
    return out


def _live_documents() -> list[Path]:
    return [
        p for p in sorted(DOCS.rglob("*.md"))
        if not str(p.relative_to(DOCS)).replace("\\", "/").startswith(
            _HISTORICAL_PREFIXES
        )
    ]


def test_there_are_sealed_tracks_to_check() -> None:
    """A silently empty scan would make this test a no-op."""
    assert _tracks(), "no sealed-track manifests found under data/"


def test_evaluated_tracks_are_not_described_as_pending() -> None:
    """The failure this test exists for, stated plainly.

    If a track's manifest says `evaluated`, no live document may say its run
    has not happened. Documents naming the track by its directory name or by
    its short track label are both checked.
    """
    problems: list[str] = []
    for name, manifest in _tracks().items():
        if manifest["status"] != "evaluated":
            continue
        # e.g. "C-ext3" from "C-ext3 — BFCL v4 semantic-authority ..."
        label = str(manifest.get("track", "")).split("—")[0].split("-")[0:2]
        short = "-".join(part.strip() for part in label if part.strip())
        needles = {name}
        if short and len(short) > 2:
            needles.add(short)

        for doc in _live_documents():
            text = doc.read_text(encoding="utf-8", errors="replace")
            if not any(needle in text for needle in needles):
                continue
            record = _EXECUTION_RECORD.search(text)
            # Everything below an execution record is the frozen
            # pre-registration; the status claim is what stands above it.
            scope = text[: record.start()] if record else text
            lowered = scope.lower()
            for phrase in _PENDING_PHRASES:
                for match in re.finditer(re.escape(phrase), lowered):
                    line_no = text[: match.start()].count("\n") + 1
                    line = scope.splitlines()[line_no - 1].strip()
                    # A document may legitimately QUOTE the protocol, e.g.
                    # describing the sealed_never_run -> evaluated lifecycle.
                    if "->" in line or "→" in line or "lifecycle" in line.lower():
                        continue
                    problems.append(
                        f"{doc.relative_to(ROOT)}:{line_no} says {phrase!r} "
                        f"about track {name!r}, whose manifest is 'evaluated': "
                        f"{line[:110]}"
                    )
    assert problems == [], (
        "documents claim a sealed run is pending after it was run:\n  "
        + "\n  ".join(problems)
    )


def test_the_cext3_pre_registration_records_its_execution() -> None:
    """The pre-registration must carry the outcome, without being rewritten.

    Both halves matter. A pre-registration that never says what happened
    leaves the reader to find out elsewhere; one that is edited in hindsight
    stops being a pre-registration at all. The document therefore appends an
    execution record and keeps the original text below it.
    """
    sap = DOCS / "assurance" / "statistical_analysis_plan_v5_bfcl_semantic.md"
    text = sap.read_text(encoding="utf-8")
    assert "EXECUTED 2026-08-19" in text, (
        "SAP v5 does not record that its sealed run happened"
    )
    assert "CLAIM-019" in text, "SAP v5 does not name the resulting claim"
    # The pre-registered content must still be there, unedited.
    assert "## 2. Co-primary targets" in text
    assert "## 12. Deviations" in text
