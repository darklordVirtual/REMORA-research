# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Research-profile tool registry for the governed execution API.

Deployment-configuration module for the ``REMORA_TOOL_REGISTRY_MODULE``
contract (see ``servers/execution_api.py``): the API process imports this
module once and calls ``register_tools(register)``. Tool callables — and any
credentials they would close over — live app-side; request payloads can
never add or replace them.

This registry wires ONLY side-effect-bounded tools that are useful for
shadow-mode research, so the full assess → approve → execute → dispatch
chain is demonstrable end to end with real (but sandboxed) side effects:

  store_artifact   — writes a JSON artifact inside the app-controlled
                     directory ``REMORA_EXECUTION_ARTIFACT_DIR``
                     (default ``artifacts/execution/``). Artifact ids are
                     sanitized to a strict charset; path traversal is
                     structurally impossible.
  read_telemetry   — read-only. Returns the JSON content of
                     ``REMORA_TELEMETRY_FILE`` when configured; otherwise an
                     explicitly labelled empty reading (``source: none``) —
                     never fabricated telemetry.

Deliberately NOT registered:
  delete_production_database — destructive/critical; never in this profile.
  update_work_order          — production write against external systems.
  dce_search_law             — requires network + external worker credentials.
  remora_verify_claim        — live consensus needs oracle API keys; use
                               ``/v1/assess`` for the decision path instead.

Enable with: ``REMORA_TOOL_REGISTRY_MODULE=servers.tool_registry_research``
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _artifact_dir() -> Path:
    configured = os.environ.get("REMORA_EXECUTION_ARTIFACT_DIR", "").strip()
    return Path(configured) if configured else Path("artifacts") / "execution"


def store_artifact(arguments: dict[str, Any]) -> dict[str, Any]:
    """Persist ``arguments['content']`` as JSON under the sandbox directory.

    The artifact id comes from ``arguments['artifact_id']`` and must match a
    strict charset (no separators, no leading dot), so the write can never
    escape the app-controlled directory.
    """
    artifact_id = str(arguments.get("artifact_id", "")).strip()
    if not _ARTIFACT_ID_RE.match(artifact_id):
        raise ValueError(
            "artifact_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,120} "
            f"(got {artifact_id!r})"
        )
    payload = {
        "artifact_id": artifact_id,
        "stored_at": datetime.now(UTC).isoformat(),
        "content": arguments.get("content"),
    }
    directory = _artifact_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{artifact_id}.json"
    body = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    path.write_text(body, encoding="utf-8", newline="\n")
    return {
        "stored": True,
        "path": str(path),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def read_telemetry(arguments: dict[str, Any]) -> dict[str, Any]:
    """Read-only telemetry access; explicit about having no source.

    With ``REMORA_TELEMETRY_FILE`` set, returns that file's JSON content.
    Without it, returns an empty reading labelled ``source: none`` — a
    missing source must never look like a measurement.
    """
    configured = os.environ.get("REMORA_TELEMETRY_FILE", "").strip()
    if not configured:
        return {"source": "none", "reading": None,
                "note": "REMORA_TELEMETRY_FILE not configured"}
    path = Path(configured)
    try:
        reading = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"source": str(path), "reading": None, "note": "file not found"}
    except (OSError, ValueError) as exc:
        return {"source": str(path), "reading": None, "note": f"unreadable: {exc}"}
    return {"source": str(path), "reading": reading}


def register_tools(register: Callable[[str, Callable[[Any], Any]], None]) -> None:
    register("store_artifact", store_artifact)
    register("read_telemetry", read_telemetry)
