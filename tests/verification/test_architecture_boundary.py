# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""WS1-01/05: the WS1 layer and its monitor adapter hold no authority exports (A28).

Since WP5 the server wires the gate in through ``Ws1GatePort``; the import
rule below pins that it is the only way in.

Same pattern as tests/test_advisory_assessment_cannot_authorize.py: the
library imports nothing that mints a token, lease, grant or approval, and its
outputs carry no such field.
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

from remora.decision_providers.composition_adapter import MonitorAssessment
from remora.verification.check import CheckedPreconditions, PreconditionResult, ResolverEvidence
from remora.verification.records import CompositionRecord

ROOT = Path(__file__).resolve().parents[2]
WS1 = [ROOT / "remora" / "verification", ROOT / "remora" / "decision_providers" / "composition_adapter.py"]
ENFORCING = ("remora/enforcement", "remora/execution", "servers")
AUTHORITY_MODULES = ("remora.enforcement", "remora.execution", "servers", "remora.governance",
                     "remora.evidence.obligations")
GRANT_FIELDS = {"token", "execution_token", "grant", "lease", "signature", "jti", "approval",
                "issuer_key", "declassification_grant"}


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _files() -> list[Path]:
    return [f for p in WS1 for f in ([p] if p.is_file() else sorted(p.rglob("*.py")))]


def test_monitors_and_ws1_records_have_no_authority_exports():
    for cls in (MonitorAssessment, CheckedPreconditions, PreconditionResult, ResolverEvidence,
                CompositionRecord):
        assert not {f.name for f in dataclasses.fields(cls)} & GRANT_FIELDS, cls.__name__


def test_ws1_imports_no_issuer_or_settlement_machinery():
    offenders = [f"{f.name}: {n}" for f in _files() for n in _imports(f)
                 if n.startswith(AUTHORITY_MODULES)]
    assert offenders == []


def test_the_execution_core_reaches_ws1_only_through_its_port():
    """WP5: ``remora/execution`` and ``remora/enforcement`` see a
    ``Ws1GatePort`` and a ``Ws1AdmissionPort``; the one importer of the
    library is the server, and it imports only the gate and the WS1-M4
    admission checks it wires in."""
    importers = {}
    for package in ENFORCING + ("remora/enforcement",):
        for source in (ROOT / package).rglob("*.py"):
            names = [n for n in _imports(source)
                     if n.startswith("remora.verification")
                     or n == "remora.decision_providers.composition_adapter"]
            if names:
                importers[str(source.relative_to(ROOT))] = sorted(set(names))
    assert importers == {"servers/execution_api.py": ["remora.verification.admission",
                                                      "remora.verification.execution_gate"]}


def test_ws1_reads_no_clock_or_environment():
    offenders = []
    for f in _files():
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "time",
                                                                  "monotonic", "environ", "getenv"}:
                offenders.append(f"{f.name}:{node.lineno}:{node.attr}")
    assert offenders == []
