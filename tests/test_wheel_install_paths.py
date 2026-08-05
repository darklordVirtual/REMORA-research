# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Shipped artifacts must resolve from a wheel, not only from a checkout.

``pyproject.toml`` force-includes ``schemas/`` in the wheel at the same
top-level position it has in a repo checkout, specifically so path resolution
is identical in both install modes. That only holds if the code resolves those
paths against the *installed package root* — and one loader did not.

``_load_risk_profile_config`` used ``Path("schemas/risk-profiles.yaml")``,
which resolves against the working directory. An editable install run from the
repo root found the file by coincidence. A wheel install running from anywhere
else refused to start in production mode with "risk profile config file is
missing" while the file sat in site-packages, unreferenced.

It was found by installing the wheel into a container with ``WORKDIR /app``,
which is what any deployment does.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")


def test_the_risk_profile_resolves_from_the_package_not_the_cwd(
    monkeypatch, tmp_path
) -> None:
    """The regression itself: resolve from a directory with no schemas/."""
    import servers.api as api

    monkeypatch.delenv("REMORA_RISK_PROFILE_PATH", raising=False)
    monkeypatch.chdir(tmp_path)          # no schemas/ here, like a container
    assert not (tmp_path / "schemas").exists()

    config = api._load_risk_profile_config()
    assert config, (
        "the risk profile did not load from a working directory without a "
        "schemas/ subdirectory; a wheel install refuses to start in "
        "production mode with this"
    )


def test_an_explicit_override_still_wins(monkeypatch, tmp_path) -> None:
    """Operators who keep the config elsewhere must not be overridden."""
    import servers.api as api

    elsewhere = tmp_path / "custom-profiles.yaml"
    elsewhere.write_text("profiles:\n  demo: {}\n", encoding="utf-8")
    monkeypatch.setenv("REMORA_RISK_PROFILE_PATH", str(elsewhere))

    assert api._load_risk_profile_config() == {"profiles": {"demo": {}}}


def test_a_missing_file_names_where_it_looked(monkeypatch, tmp_path) -> None:
    """"missing" without a path is an error nobody can act on."""
    import servers.api as api

    monkeypatch.setenv("REMORA_RISK_PROFILE_PATH",
                       str(tmp_path / "nope.yaml"))
    monkeypatch.setattr(api, "_is_production_mode", lambda: True)

    with pytest.raises(RuntimeError, match="nope.yaml"):
        api._load_risk_profile_config()


def test_every_shipped_schema_is_reachable_from_the_package_root() -> None:
    """The force-include contract, checked against the files that rely on it.

    If a schema stops being shipped, or the package layout changes so
    ``_REPO_ROOT`` no longer contains ``schemas/``, this fails here rather
    than at some deployment's startup.
    """
    import servers.api as api

    for name in ("risk-profiles.yaml", "decision_envelope_schema.yaml",
                 "execution_lifecycle_v1.yaml", "tool_spec_v1.yaml",
                 "postcondition_contract_v1.yaml", "openapi.json"):
        assert (api._REPO_ROOT / "schemas" / name).is_file(), (
            f"schemas/{name} is not reachable from the installed package root "
            f"({api._REPO_ROOT}); a wheel install cannot find it"
        )


def test_repo_root_is_defined_before_anything_at_import_time_uses_it() -> None:
    """Ordering, not just correctness.

    ``_RISK_PROFILE_CONFIG`` is computed at import. ``_REPO_ROOT`` used to be
    assigned *after* it, so a package-relative fix would have raised NameError
    at import — which is how the CWD-relative version survived.
    """
    source = Path(__import__("servers.api", fromlist=["api"]).__file__)
    text = source.read_text(encoding="utf-8")
    definition = text.index("\n_REPO_ROOT = Path(__file__)")
    first_use = text.index("_RISK_PROFILE_CONFIG = _load_risk_profile_config()")
    assert definition < first_use, (
        "_REPO_ROOT is defined after the import-time code that needs it"
    )
