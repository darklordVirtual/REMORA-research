# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The gate that should have caught the durability defect three times.

The consumed-jti ledger (#350), the lease nonce ledger and principal
revocation (#502) were the same defect: a durable backend the deployment
already ran, used by one component and not another. All three were found by
a reviewer or an audit. None was found by a gate, and the second
occurrence's own module docstring names the pattern.

The tests that matter here are in ``TestItWouldHaveCaughtTheThreeThatShipped``
and ``TestItCatchesAnUndeclaredStore``. A gate that passes on the current
tree proves nothing on its own; these show it fails on the shapes it exists
to reject.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "assurance" / "authority_state_topology.yaml"
SCRIPT = ROOT / "scripts" / "check_authority_state_durability.py"


@pytest.fixture()
def register() -> dict:
    return yaml.safe_load(REGISTER.read_text(encoding="utf-8"))


class TestTheCommittedTreePasses:
    def test_the_gate_passes(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_every_declared_module_exists(self, register):
        for entry in register["state"]:
            module = entry["symbol"].split("::")[0]
            assert (ROOT / module).exists(), entry["id"]

    def test_no_reauthorizing_store_lacks_a_durable_adapter(self, register):
        """The invariant, stated independently of the script."""

        for entry in register["state"]:
            if entry["on_loss"] == "reauthorizes":
                adapter = entry.get("durable_adapter")
                assert adapter and adapter != "none", entry["id"]

    def test_every_open_gap_names_a_tracking_item(self, register):
        for entry in register["state"]:
            adapter = entry.get("durable_adapter")
            if entry["on_loss"] == "loses_evidence" and (
                not adapter or adapter == "none"
            ):
                assert entry.get("tracking"), entry["id"]


class TestItWouldHaveCaughtTheThreeThatShipped:
    """Each past occurrence, reconstructed as the register entry it would
    have had at the time, must be rejected."""

    @pytest.mark.parametrize("symbol,what", [
        ("remora/enforcement/gate.py::EnforcementGate", "the consumed-jti ledger (#350)"),
        ("remora/enforcement/lease.py::NonceLedger", "the lease nonce ledger"),
        ("remora/governance/review_queue.py::ReviewQueue", "principal revocation (#502)"),
    ], ids=["jti-ledger", "nonce-ledger", "revocation"])
    def test_the_pre_fix_declaration_is_rejected(self, tmp_path, symbol, what):
        import importlib.util

        spec = importlib.util.spec_from_file_location("gate_mod", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # What the entry looked like before each fix: state whose loss
        # re-authorizes, with no durable adapter.
        broken = {
            "schema_version": "1",
            "state": [{
                "id": "AST-TEST",
                "symbol": symbol,
                "gates": what,
                "on_loss": "reauthorizes",
                "durable_adapter": "none",
            }],
        }
        path = tmp_path / "broken.yaml"
        path.write_text(yaml.safe_dump(broken), encoding="utf-8")

        original = module.REGISTER
        try:
            module.REGISTER = path
            errors = module.check()
        finally:
            module.REGISTER = original

        assert any("no durable adapter" in e for e in errors), errors

    def test_the_rejection_explains_why_rather_than_naming_a_rule(self, tmp_path):
        """A gate whose message is 'rule violated' teaches nobody."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("gate_mod2", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        path = tmp_path / "broken.yaml"
        path.write_text(yaml.safe_dump({
            "schema_version": "1",
            "state": [{
                "id": "AST-TEST",
                "symbol": "remora/enforcement/lease.py::NonceLedger",
                "gates": "x",
                "on_loss": "reauthorizes",
                "durable_adapter": "none",
            }],
        }), encoding="utf-8")

        original = module.REGISTER
        try:
            module.REGISTER = path
            errors = module.check()
        finally:
            module.REGISTER = original

        joined = " ".join(errors)
        assert "fail-open" in joined
        assert "executable" in joined or "execute" in joined


class TestItCatchesAnUndeclaredStore:
    """The discovery half. A hand-maintained list would have gone stale."""

    def test_a_store_missing_from_the_register_is_reported(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location("gate_mod3", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # An empty register against the real package: every discovered store
        # must be reported as undeclared.
        path = tmp_path / "empty.yaml"
        path.write_text(yaml.safe_dump({"schema_version": "1", "state": []}),
                        encoding="utf-8")
        original = module.REGISTER
        try:
            module.REGISTER = path
            errors = module.check()
        finally:
            module.REGISTER = original

        undeclared = [e for e in errors if e.startswith("UNDECLARED")]
        assert len(undeclared) >= 9, undeclared
        assert any("NonceLedger" in e for e in undeclared)

    def test_discovery_finds_the_three_that_shipped_broken(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("gate_mod4", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        found = module.discover()
        for symbol in (
            "remora/enforcement/gate.py::EnforcementGate",
            "remora/enforcement/lease.py::NonceLedger",
            "remora/governance/review_queue.py::ReviewQueue",
        ):
            assert symbol in found, f"{symbol} not discovered; the heuristic missed it"

    def test_a_stale_declaration_is_reported(self, tmp_path):
        """A symbol that moved must not sit in the register unnoticed."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("gate_mod5", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        entries = yaml.safe_load(REGISTER.read_text(encoding="utf-8"))
        entries["state"].append({
            "id": "AST-GONE",
            "symbol": "remora/enforcement/lease.py::ClassThatDoesNotExist",
            "gates": "x",
            "on_loss": "reauthorizes",
            "durable_adapter": "somewhere",
        })
        path = tmp_path / "stale.yaml"
        path.write_text(yaml.safe_dump(entries), encoding="utf-8")

        original = module.REGISTER
        try:
            module.REGISTER = path
            errors = module.check()
        finally:
            module.REGISTER = original

        assert any(e.startswith("STALE") for e in errors), errors


class TestTheRegisterIsHonest:
    def test_it_states_what_a_pass_does_not_establish(self, register):
        limits = register.get("limits") or []
        assert limits, "a gate with no stated limits reads as proving more than it does"
        joined = " ".join(limits).lower()
        assert "deployment" in joined

    def test_the_reference_implementations_are_marked(self, register):
        marked = [e["id"] for e in register["state"]
                  if e.get("reference_implementation")]
        assert "AST-005" in marked and "AST-006" in marked
