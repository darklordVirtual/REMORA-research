# Author: Stian Skogbrott
# License: Apache-2.0
"""Policy bundle hash utility for REMORA audit chain population.

Computes a deterministic SHA-256 composite hash over the policy-critical Python
source files.  Integration layers use this to populate ``AuditBlock.policy_bundle_hash``
so that any change to the policy engine is reflected in the audit trail without
manual version-string bumps.

Files covered
-------------
The hash covers the files that together determine the governance outcome of any
decision: the engine itself, the invariants, the trap classifier, and the
observation schema.  Changing any one of these changes the composite hash.

Usage
-----
::

    from remora.policy.versioning import compute_policy_bundle_hash

    bundle_hash = compute_policy_bundle_hash()
    audit_block = AuditBlock(
        policy_version="RemoraDecisionEngine-v3",
        policy_bundle_hash=bundle_hash,
        ...
    )

The returned hash is stable within one process invocation (files do not change
at runtime).  It is deterministic across invocations as long as the source files
are identical (no randomness or timestamps in the hash input).
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

# Source files whose content determines the governance outcome.
# Paths are relative to the repository root (the parent of the ``remora`` package).
_POLICY_SOURCE_FILES: tuple[str, ...] = (
    "remora/policy/decision_engine.py",
    "remora/policy/invariants.py",
    "remora/policy/observation.py",
    "remora/policy/trap_classifier.py",
    "remora/policy/report.py",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def compute_policy_bundle_hash(
    source_files: Sequence[str] = _POLICY_SOURCE_FILES,
    *,
    repo_root: Path | None = None,
) -> str:
    """Return a hex SHA-256 hash over the content of all policy source files.

    Parameters
    ----------
    source_files:
        Paths relative to *repo_root* to include in the bundle hash.
        Defaults to the canonical set: ``decision_engine.py``,
        ``invariants.py``, ``observation.py``, ``trap_classifier.py``,
        ``report.py``.
    repo_root:
        Repository root path.  Defaults to the parent of the ``remora``
        package directory (auto-detected from ``__file__``).

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.

    Raises
    ------
    FileNotFoundError
        If any file in *source_files* does not exist relative to *repo_root*.

    Examples
    --------
    ::

        hash1 = compute_policy_bundle_hash()
        hash2 = compute_policy_bundle_hash()
        assert hash1 == hash2  # deterministic

        # Custom set of files
        hash3 = compute_policy_bundle_hash(["remora/policy/decision_engine.py"])
    """
    root = repo_root if repo_root is not None else _REPO_ROOT
    hasher = hashlib.sha256()

    for rel_path in sorted(source_files):  # sorted for determinism
        full_path = root / rel_path
        if not full_path.exists():
            raise FileNotFoundError(
                f"Policy source file not found: {full_path} "
                f"(root={root}, rel={rel_path})"
            )
        # Include the relative path in the hash so that renaming a file changes
        # the composite hash even if its content is identical to the old location.
        hasher.update(rel_path.encode("utf-8"))
        hasher.update(full_path.read_bytes())

    return hasher.hexdigest()


def policy_bundle_manifest(
    source_files: Sequence[str] = _POLICY_SOURCE_FILES,
    *,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Return a per-file SHA-256 manifest for audit inspection.

    Parameters
    ----------
    source_files, repo_root:
        Same as :func:`compute_policy_bundle_hash`.

    Returns
    -------
    dict[str, str]
        ``{relative_path: hex_sha256}`` mapping for each file.
        The composite bundle hash equals the SHA-256 of this manifest
        (via :func:`compute_policy_bundle_hash`).
    """
    root = repo_root if repo_root is not None else _REPO_ROOT
    manifest: dict[str, str] = {}
    for rel_path in sorted(source_files):
        full_path = root / rel_path
        if not full_path.exists():
            raise FileNotFoundError(
                f"Policy source file not found: {full_path}"
            )
        manifest[rel_path] = hashlib.sha256(full_path.read_bytes()).hexdigest()
    return manifest
