# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Importing the package must not drag the whole product in.

`docs/sdk.md` calls `remora.sdk` "a small, stable entry point". Until
2026-08-20 that was false: `remora/__init__.py` held 16 eager cross-package
imports, so touching any part of the package pulled in 62 modules — the
evidence providers, the GO-STAR bridge, the replay engine, the OTel wrapper —
whether the caller wanted them or not.

These bounds are ceilings with headroom, not targets. They exist to fail when
someone reintroduces an eager top-level import, which is the regression that
is otherwise invisible until a downstream service's start-up time doubles.
"""
from __future__ import annotations

import subprocess
import sys

# Measured 2026-08-20: `import remora` = 0, `import remora.sdk` = 18.
MAX_MODULES_BARE = 5
MAX_MODULES_SDK = 25


def _module_count(statement: str) -> int:
    """Count remora.* modules loaded by `statement` in a fresh interpreter."""
    code = (
        f"{statement}\n"
        "import sys\n"
        "print(len([m for m in sys.modules if m.startswith('remora.')]))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip())


def test_bare_import_pulls_in_almost_nothing() -> None:
    count = _module_count("import remora")
    assert count <= MAX_MODULES_BARE, (
        f"`import remora` loaded {count} remora modules (ceiling "
        f"{MAX_MODULES_BARE}). An eager top-level import came back — add the "
        f"symbol to _LAZY_EXPORTS instead."
    )


def test_sdk_import_stays_small() -> None:
    count = _module_count("import remora.sdk")
    assert count <= MAX_MODULES_SDK, (
        f"`import remora.sdk` loaded {count} remora modules (ceiling "
        f"{MAX_MODULES_SDK}); docs/sdk.md promises a small entry point."
    )


def test_importing_the_engine_does_not_pull_the_servers_or_evidence_stack() -> None:
    """The embeddability claim: a decision engine, not a product."""
    code = (
        "from remora.policy.decision_engine import RemoraDecisionEngine\n"
        "import sys\n"
        "loaded = set(sys.modules)\n"
        "unwanted = [m for m in loaded if m.startswith((\n"
        "    'remora.evidence', 'remora.integrations', 'remora.shadow',\n"
        "    'remora.adapters', 'remora.oracles', 'servers',\n"
        "))]\n"
        "print(','.join(sorted(unwanted)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    unwanted = [m for m in out.stdout.strip().split(",") if m]
    assert unwanted == [], (
        f"importing the decision engine pulled in {unwanted}"
    )


def test_every_public_name_still_resolves() -> None:
    """Lazy loading must not silently drop a symbol from the surface."""
    import remora

    unresolved = [name for name in remora.__all__ if not hasattr(remora, name)]
    assert unresolved == [], unresolved


def test_unknown_attribute_still_raises_attribute_error() -> None:
    import remora

    try:
        remora.definitely_not_a_symbol  # noqa: B018
    except AttributeError as exc:
        assert "definitely_not_a_symbol" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected AttributeError")


def test_dir_lists_the_lazy_surface() -> None:
    """Tab-completion and introspection must still see the exports."""
    import remora

    listed = set(dir(remora))
    assert set(remora.__all__) <= listed
