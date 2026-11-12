# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Packaged CLI surface an external host (DCSIM) pins against.

Two subcommands remove the need to run REMORA code from an unpacked source
tree:

* ``remora sign-limits`` validates a cumulative-limit policy against the loader
  (refusing one REMORA would refuse to load) and signs it with an Ed25519 key,
  so a host authors a signed ``limits.json`` without importing
  ``remora.enforcement``.
* ``remora export-contract-files`` writes the contract files a host pins to
  (the OpenAPI document, the SDK public-API snapshot, the ToolSpec schemas)
  from the installed package.
"""
from __future__ import annotations

import json
from pathlib import Path

from remora.cli import main as cli_main

POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "deploy" / "ot-pilot" / "limits.json").read_text()
)["policy"]


def test_sign_limits_signs_a_valid_policy(tmp_path, monkeypatch):
    from remora.crypto import SignatureDomain, SigningKey
    from remora.enforcement.cumulative_limits import verify_signed_policy

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    monkeypatch.setenv("REMORA_LIMITS_SIGNING_SEED", key.seed.hex())
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(POLICY))
    out_path = tmp_path / "limits.json"

    rc = cli_main(["sign-limits", str(policy_path), "--out", str(out_path)])
    assert rc == 0

    document = json.loads(out_path.read_text())
    assert document["schema"] == "remora-cumulative-limits-signed/v1"
    policy, _kid = verify_signed_policy(document, [key.verification_key()])
    assert policy["schema"] == "remora-cumulative-limits/v1"


def test_sign_limits_refuses_a_policy_remora_would_not_load(tmp_path, monkeypatch):
    from remora.crypto import SignatureDomain, SigningKey

    key = SigningKey.generate({SignatureDomain.LIMIT_POLICY})
    monkeypatch.setenv("REMORA_LIMITS_SIGNING_SEED", key.seed.hex())
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "remora-cumulative-limits/v1"}))  # no meters
    out_path = tmp_path / "out.json"

    rc = cli_main(["sign-limits", str(bad), "--out", str(out_path)])
    assert rc != 0
    assert not out_path.exists()


def test_sign_limits_new_key_prints_seed_and_public_key(capsys):
    rc = cli_main(["sign-limits", "--new-key"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "seed" in payload and "public_key" in payload


def test_export_contract_files_writes_the_pinned_surface(tmp_path):
    import remora.sdk as sdk

    rc = cli_main(["export-contract-files", str(tmp_path)])
    assert rc == 0

    snap = json.loads((tmp_path / "public_api_v1.json").read_text())
    assert set(snap["symbols"]) == set(sdk.__all__)
    assert snap["module"] == "remora.sdk"

    openapi = json.loads((tmp_path / "openapi.json").read_text())
    assert "paths" in openapi
    assert any(p.name.startswith("tool_spec_v") for p in tmp_path.iterdir())


def test_export_contract_files_matches_the_committed_snapshot(tmp_path):
    # The exported snapshot is byte-identical to the committed one, so a host
    # pinning via the installed package gets the same PIN-005 artifact CI gates.
    committed = (
        Path(__file__).resolve().parents[1] / "artifacts" / "sdk" / "public_api_v1.json"
    ).read_text()
    cli_main(["export-contract-files", str(tmp_path)])
    assert (tmp_path / "public_api_v1.json").read_text() == committed
