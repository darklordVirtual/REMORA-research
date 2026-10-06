# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Strict JSON and exclusive publication for non-authoritative interop evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


class EvidenceError(RuntimeError):
    """Evidence is incomplete, ambiguous or cannot be published exclusively."""


#: Deepest array/object nesting decode_json accepts. Set explicitly because the
#: interpreter's recursion limit is not a stable bound: Python 3.14's decoder
#: parses 10,000 levels without raising RecursionError.
MAX_JSON_DEPTH = 512


def _nesting_exceeds(text: str, limit: int) -> bool:
    """True when brackets outside string literals nest deeper than ``limit``."""
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return True
        elif char in "]}":
            depth -= 1
    return False


def digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise EvidenceError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> Any:
        raise EvidenceError(f"non-finite JSON number: {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise EvidenceError(f"non-finite JSON number: {value}")
        return number

    if _nesting_exceeds(text, MAX_JSON_DEPTH):
        raise EvidenceError("JSON nesting exceeds parser limit")
    try:
        return json.loads(
            text, object_pairs_hook=pairs, parse_constant=invalid_constant, parse_float=finite_float,
        )
    except RecursionError as exc:
        raise EvidenceError("JSON nesting exceeds parser limit") from exc


def publish_new(output: Path, encoded: bytes) -> None:
    """Publish complete bytes atomically without replacing existing evidence."""
    if output.exists() or output.is_symlink():
        raise EvidenceError("existing output refused")
    # The temporary hard link is output publication, not an accepted input link.
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".remora-result-", delete=False) as staged:
        staged_path = Path(staged.name)
        try:
            staged.write(encoded)
            staged.flush()
            os.fsync(staged.fileno())
            os.link(staged_path, output)
        finally:
            staged_path.unlink()
