# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Publication evidence fails closed on incomplete tests or changed bytes."""
import json
from pathlib import Path

import pytest

from scripts.reproduce_federation_readiness import check_junit, seal, verify


@pytest.mark.parametrize("xml", [
    '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>',
    '<testsuites><testsuite tests="2" failures="0" errors="0" skipped="1"/></testsuites>',
    '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/></testsuites>',
    '<testsuites/>',
])
def test_incomplete_or_failed_evidence_is_refused(tmp_path: Path, xml: str) -> None:
    report = tmp_path / "tests.xml"
    report.write_text(xml, encoding="utf-8")
    with pytest.raises(ValueError):
        check_junit(report)


def test_external_manifest_pin_detects_resealed_tampering(tmp_path: Path) -> None:
    record = tmp_path / "result.json"
    record.write_text('{"status":"NOT_ESTABLISHED"}', encoding="utf-8")
    pin = seal(tmp_path)
    assert verify(tmp_path, pin)
    record.write_text('{"status":"ESTABLISHED"}', encoding="utf-8")
    assert not verify(tmp_path, pin)
    new_pin = seal(tmp_path)
    assert new_pin != pin
    assert not verify(tmp_path, pin)


def test_added_and_missing_evidence_are_refused(tmp_path: Path) -> None:
    record = tmp_path / "result.json"
    record.write_text("{}", encoding="utf-8")
    pin = seal(tmp_path)
    extra = tmp_path / "unlisted.json"
    extra.write_text("{}", encoding="utf-8")
    assert not verify(tmp_path, pin)
    extra.unlink()
    record.unlink()
    assert not verify(tmp_path, pin)


def test_manifest_paths_cannot_escape_bundle(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    seal(tmp_path)
    manifest = tmp_path / "hashes.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"]["../outside.json"] = "0" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    from hashlib import sha256
    assert not verify(tmp_path, sha256(manifest.read_bytes()).hexdigest())
