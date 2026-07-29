# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The built distribution must fulfil the documented CLI/API promise.

REM-045 / external review F-01: a wheel that ships only remora/ passes the
whole unit suite from an editable checkout while `remora serve` is broken
for every wheel install. These tests pin the packaging *declaration*; the
`wheel-contract` CI job proves the built artifact behaves (installs the
wheel in a clean venv, imports servers.api, resolves schemas/, serves
/v1/health from an empty directory).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_wheel_ships_servers_package():
    cfg = _pyproject()
    packages = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "remora" in packages
    assert "servers" in packages, (
        "the wheel must ship servers/ — `remora serve` and the documented "
        "'uvicorn servers.api:app' deployment depend on it (REM-045)"
    )
    # A PEP-420 namespace dir silently drops out of some packaging paths;
    # servers/ must stay a real package.
    assert (ROOT / "servers" / "__init__.py").is_file()


def test_wheel_ships_schemas_at_repo_root_position():
    cfg = _pyproject()
    force = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force.get("schemas") == "schemas", (
        "schemas/ must ship at the same top-level position as in a checkout — "
        "remora/governance/envelope.py resolves it relative to the package root"
    )
    assert (ROOT / "schemas" / "decision_envelope_schema.yaml").is_file()


def test_postgres_drivers_are_declared_in_an_extra():
    extras = _pyproject()["project"]["optional-dependencies"]
    postgres = extras.get("postgres", [])
    joined = " ".join(postgres)
    assert "psycopg[binary]" in joined, "tenant chain / enforcement gate import psycopg (v3)"
    assert "psycopg2" in joined, "control-plane storage / audit adapter import psycopg2"


def test_schema_path_resolves_in_this_environment():
    """The runtime loader the wheel depends on must work here too."""
    from remora.governance.envelope import load_decision_envelope_schema
    schema = load_decision_envelope_schema()
    assert schema.get("additionalProperties") is False
