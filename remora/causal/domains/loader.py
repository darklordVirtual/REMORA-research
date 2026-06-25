"""Loader for YAML-based CausalDecisionModel domain profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from remora.causal.schema import (
    CausalDecisionModel,
    CausalEdge,
    CausalVariable,
    VariableProvenance,
    VariableType,
)

_DOMAINS_DIR = Path(__file__).parent


def load_domain(model_id: str) -> CausalDecisionModel:
    """Load a built-in domain profile by model_id.

    Parameters
    ----------
    model_id:
        The model_id field from the YAML file, which must also be the
        file stem (e.g. "network_change_management_v1" →
        "network_change_management_v1.yaml").

    Raises
    ------
    FileNotFoundError
        If no YAML file with that name exists in the domains directory.
    """
    path = _DOMAINS_DIR / f"{model_id}.yaml"
    if not path.exists():
        available = [p.stem for p in _DOMAINS_DIR.glob("*.yaml")]
        raise FileNotFoundError(
            f"Domain profile '{model_id}' not found. "
            f"Available domains: {available}"
        )
    return load_from_yaml(path)


def load_from_yaml(path: str | Path) -> CausalDecisionModel:
    """Parse a CausalDecisionModel from a YAML file."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return _parse(data)


def _parse(data: dict[str, Any]) -> CausalDecisionModel:
    variables = [_parse_variable(v) for v in data.get("variables", [])]
    edges = [_parse_edge(e) for e in data.get("edges", [])]
    return CausalDecisionModel(
        model_id=data["model_id"],
        version=str(data["version"]),
        domain=data["domain"],
        variables=variables,
        edges=edges,
        assumptions=list(data.get("assumptions", [])),
    )


def _parse_variable(v: dict[str, Any]) -> CausalVariable:
    return CausalVariable(
        name=v["name"],
        label=v["label"],
        type=VariableType(v["type"]),
        intervenable=bool(v["intervenable"]),
        actionable=bool(v["actionable"]),
        provenance=VariableProvenance(v["provenance"]),
        signal_mapping=dict(v.get("signal_mapping") or {}),
    )


def _parse_edge(e: dict[str, Any]) -> CausalEdge:
    return CausalEdge(
        source=str(e["source"]),
        target=str(e["target"]),
        relation=str(e["relation"]),
    )
