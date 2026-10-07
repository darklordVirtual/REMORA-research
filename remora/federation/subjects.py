# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Subjects, report selection and native results (report-specific binding).

A claim result is always about one subject: an operation, or one report,
attempt or effect observation of that operation. Several reports for one
operation are not interchangeable. The same claim id evaluated on two reports
can legitimately give two different native results, so a result that does
not say which report it describes is ambiguous, and a consumer that picks the
first, the last or any established report can return the wrong answer while
looking conformant. Rul1an showed this on aeoess/agent-governance-vocabulary#177
with the synthetic LATE and LATE-CONFLICT fixtures.

This module makes the subject explicit and integrity-bound:

- ``Report`` digests its identity (kind, operation, report id, sequence) and
  its opaque native body together, so a report id cannot be moved to other
  bytes without changing the digest;
- ``select_report`` selects by a declared rule (explicit id, explicit digest,
  the single available report, or a named profile) and refuses rather than
  choosing when several reports are eligible and nothing selects one;
- ``NativeResult`` carries the native status and a bounded reason code in a
  declared vocabulary, separate from any projection strength.

Claim ids stay claim ids: the report a result is about is in its subject,
never in the claim name.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from remora.policy.observation import _canonical_json

__all__ = ["NATIVE_VOCABULARIES", "OBSERVATION_KINDS", "SELECTION_RULES", "SUBJECT_KINDS",
           "EvidenceSelection", "NativeResult", "Report", "SelectionProfile", "SelectionRefused",
           "SubjectRef", "select_report"]

SUBJECT_KINDS = ("operation", "operation_report", "execution_attempt", "effect_observation")
#: Kinds where several instances can exist for one operation. Each must be
#: integrity-bound by a digest, not named by an id alone.
OBSERVATION_KINDS = ("operation_report", "execution_attempt", "effect_observation")
SELECTION_RULES = ("explicit_report_id", "explicit_digest", "single_available", "declared_profile")

#: The vocabularies a native result may use. Each is an existing one: claim
#: results as REMORA's interop checks report them, effect statuses from
#: remora.governance.effect_verification, and federation-port/v0 outcomes.
NATIVE_VOCABULARIES: dict[str, frozenset[str]] = {
    "remora-claim-result-v1": frozenset({"ESTABLISHED", "CONTRADICTED", "NOT_ESTABLISHED"}),
    "remora-effect-status-v1": frozenset({"EFFECT_VERIFIED", "EFFECT_MISMATCH",
                                          "EFFECT_UNOBSERVABLE", "EFFECT_VERIFIER_FAILED",
                                          "EFFECT_UNSUPPORTED"}),
    "federation-port-v0-outcome": frozenset({"provider_confirmed", "failed", "unknown"}),
}
_REASON = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SubjectRef:
    """What one result is about."""

    kind: str
    operation_id: str
    report_id: str | None = None
    report_digest: str | None = None
    sequence: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in SUBJECT_KINDS:
            raise ValueError(f"subject kind {self.kind!r} is not one of {SUBJECT_KINDS}")
        if not self.operation_id:
            raise ValueError("a subject names its operation")
        if self.kind in OBSERVATION_KINDS and not (self.report_id and self.report_digest):
            raise ValueError(f"a {self.kind} subject is bound by report_id and report_digest")
        if self.report_digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}",
                                                              self.report_digest):
            raise ValueError("report_digest must be sha256:<64 hex>")

    @property
    def report_specific(self) -> bool:
        return self.kind in OBSERVATION_KINDS

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "operation_id": self.operation_id}
        for name in ("report_id", "report_digest", "sequence"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        return out


@dataclass(frozen=True)
class Report:
    """One native observation of an operation. ``body`` is opaque to the bridge."""

    operation_id: str
    report_id: str
    body: Any
    sequence: int | None = None
    kind: str = "operation_report"

    def __post_init__(self) -> None:
        if self.kind not in OBSERVATION_KINDS:
            raise ValueError(f"a report is one of {OBSERVATION_KINDS}")

    @property
    def digest(self) -> str:
        """Identity and body together: relabelling the report changes it."""
        return _digest({"kind": self.kind, "operation_id": self.operation_id,
                        "report_id": self.report_id, "sequence": self.sequence,
                        "body": self.body})

    def subject(self) -> SubjectRef:
        return SubjectRef(kind=self.kind, operation_id=self.operation_id,
                          report_id=self.report_id, report_digest=self.digest,
                          sequence=self.sequence)


@dataclass(frozen=True)
class EvidenceSelection:
    selected_ref: str
    selected_digest: str
    selection_rule: str
    eligible: int
    profile_id: str | None = None

    def __post_init__(self) -> None:
        if self.selection_rule not in SELECTION_RULES:
            raise ValueError(f"selection_rule {self.selection_rule!r} is not one of "
                             f"{SELECTION_RULES}")
        if (self.selection_rule == "declared_profile") != bool(self.profile_id):
            raise ValueError("declared_profile names its profile_id, and only it does")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"selected_ref": self.selected_ref,
                               "selected_digest": self.selected_digest,
                               "selection_rule": self.selection_rule, "eligible": self.eligible}
        if self.profile_id:
            out["profile_id"] = self.profile_id
        return out


@dataclass(frozen=True)
class NativeResult:
    """What the native verifier concluded about the selected subject, and why."""

    status: str
    reason_code: str
    vocabulary: str = "remora-claim-result-v1"
    detail: str = ""
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        allowed = NATIVE_VOCABULARIES.get(self.vocabulary)
        if allowed is None:
            raise ValueError(f"unknown native result vocabulary {self.vocabulary!r}")
        if self.status not in allowed:
            raise ValueError(f"{self.status!r} is not in {self.vocabulary}")
        if not _REASON.match(self.reason_code):
            raise ValueError(f"reason_code {self.reason_code!r} is not a bounded code")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "reason_code": self.reason_code,
                               "vocabulary": self.vocabulary}
        if self.detail:
            out["detail"] = self.detail
        if self.evidence_digest:
            out["evidence_digest"] = self.evidence_digest
        return out


class SelectionRefused(ValueError):
    """No report is selected. ``reason`` is the bounded code a result carries."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class SelectionProfile:
    """A named, declared selection rule. Its semantics are the profile's, stated once."""

    profile_id: str
    select: Callable[[Sequence[Report]], Report | None] = field(compare=False)


def select_report(reports: Sequence[Report], *, report_id: str | None = None,
                  report_digest: str | None = None,
                  profile: SelectionProfile | None = None) -> tuple[Report, EvidenceSelection]:
    """The one report a result will describe, and how it was selected.

    Refuses, never guesses: reports for different operations, a report id that
    names two different reports, a selector that matches nothing, or several
    eligible reports with no selector all raise ``SelectionRefused``.
    """
    if not reports:
        raise SelectionRefused("no_report_available")
    if len({r.operation_id for r in reports}) != 1:
        raise SelectionRefused("reports_for_different_operations")
    by_id: dict[str, set[str]] = {}
    for r in reports:
        by_id.setdefault(r.report_id, set()).add(r.digest)
    if any(len(digests) > 1 for digests in by_id.values()):
        raise SelectionRefused("report_id_not_unique",
                               "one report id names reports with different digests")
    if sum(x is not None for x in (report_id, report_digest, profile)) > 1:
        raise SelectionRefused("selector_overdetermined", "name one selection rule")
    eligible = len(reports)
    if report_id is not None:
        chosen = [r for r in reports if r.report_id == report_id]
        rule, profile_id = "explicit_report_id", None
    elif report_digest is not None:
        chosen = [r for r in reports if r.digest == report_digest]
        rule, profile_id = "explicit_digest", None
    elif profile is not None:
        picked = profile.select(list(reports))
        chosen = [picked] if picked is not None and picked in reports else []
        rule, profile_id = "declared_profile", profile.profile_id
    elif eligible == 1:
        chosen, rule, profile_id = list(reports), "single_available", None
    else:
        raise SelectionRefused("report_selection_ambiguous",
                               f"{eligible} eligible reports and no declared selector")
    if not chosen:
        raise SelectionRefused("selected_report_absent")
    report = chosen[0]
    return report, EvidenceSelection(selected_ref=report.report_id,
                                     selected_digest=report.digest, selection_rule=rule,
                                     eligible=eligible, profile_id=profile_id)
