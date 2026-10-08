# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The federation-port/v0 contract coverage map resolves inside this repository.

``artifacts/interop/federation-port-v0/contract-coverage.json`` maps each rule of
federation-port's CONTRACT.md to the tests that exercise it. Upstream test names
can only be checked in a federation-port checkout, so the probe file's last test
does that (it runs in reproduce.sh). This file checks what lives here: every
REMORA test the map names exists, every probe it names is a probe in
contract-probes.test.ts and every probe there is mapped, the findings name
their clauses, and nothing claims a status the map does not define.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "artifacts/interop/federation-port-v0/contract-coverage.json"
PROBES = ROOT / "integrations/federation-port/contract-probes/contract-probes.test.ts"
REMORA_TESTS = [
    ROOT / "integrations/federation-port/remora-adapter/tests/remora-adapter.test.ts",
    ROOT / "integrations/federation-port/remora-report-result/tests/remora-report-result.test.ts",
]


def _load() -> dict:
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def _probe_ids() -> list[str]:
    return re.findall(r"^test\('(CP-[0-9F]+[a-z0-9]*) ", PROBES.read_text(encoding="utf-8"), re.M)


def _remora_ref_exists(ref: str) -> bool:
    """A REMORA reference is ``path::test_name`` (Python) or a title fragment of a TS test;
    ``a | b`` means both fragments occur (a generated title and its case label)."""
    if "::" in ref:
        path, name = ref.split("::", 1)
        return re.search(rf"^def {re.escape(name)}\(", (ROOT / path).read_text(encoding="utf-8"), re.M) is not None
    sources = "\n".join(p.read_text(encoding="utf-8") for p in REMORA_TESTS)
    return all(part.strip() in sources for part in ref.split(" | "))


def test_the_map_is_pinned_to_the_reproduced_revision() -> None:
    cov = _load()
    script = (ROOT / "integrations/federation-port/remora-adapter/reproduce.sh").read_text(encoding="utf-8")
    match = re.search(r"^PIN=([0-9a-f]{40})$", script, re.M)
    assert match is not None
    pin = match.group(1)
    assert cov["transport_revision"] == f"aeoess/federation-port@{pin}"
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", cov["contract"]["digest"])


def test_every_clause_has_a_defined_status_and_its_tests() -> None:
    cov = _load()
    ids = [c["id"] for c in cov["clauses"]]
    assert len(ids) == len(set(ids))
    for clause in cov["clauses"]:
        assert clause["status"] in cov["statuses"], clause["id"]
        tests = clause.get("upstream", []) + clause.get("probes", []) + clause.get("remora", [])
        if clause["status"] == "stated_limit":
            assert clause.get("note"), clause["id"]
        else:
            assert tests, f"{clause['id']} claims {clause['status']} with no test"
        if clause["status"] == "probed":
            assert clause.get("probes"), clause["id"]
        if clause["status"] in ("covered", "partly_covered"):
            assert clause.get("upstream") or clause.get("remora"), clause["id"]


def test_every_named_remora_test_exists() -> None:
    cov = _load()
    refs = [r["test"] for c in cov["clauses"] for r in c.get("remora", [])]
    for family in cov["sdd_overlap"]["families"]:
        for v in family["variants"]:
            refs += [x[len("remora:"):] for x in v.get("covered_by", []) + v.get("new", []) if x.startswith("remora:")]
        refs += [x[len("remora:"):] for x in family.get("new", []) if x.startswith("remora:")]
    assert refs
    missing = [r for r in refs if not _remora_ref_exists(r)]
    assert missing == []


def test_probes_and_the_map_agree_both_ways() -> None:
    cov = _load()
    probes = _probe_ids()
    assert len(probes) == len(set(probes))
    mapped = {p for c in cov["clauses"] for p in c.get("probes", [])} | {f["probe"] for f in cov["findings"]}
    assert mapped == set(probes)
    named_in_sdd = {x[len("probe:"):] for fam in cov["sdd_overlap"]["families"]
                    for x in fam.get("new", []) if x.startswith("probe:")}
    assert named_in_sdd <= set(probes)


def test_findings_name_real_clauses_and_are_not_claimed_upstream() -> None:
    cov = _load()
    clause_ids = {c["id"] for c in cov["clauses"]}
    for f in cov["findings"]:
        assert f["id"] == f["probe"] and f["id"].startswith("CP-F")
        assert set(f["clauses"]) <= clause_ids, f["id"]
        for field in ("observed", "conditions", "consequence", "suggested_change"):
            assert f[field].strip(), (f["id"], field)
        # A finding is reported, proposed upstream, or fixed upstream at a named merge revision.
        assert f["status"] in ("reported_not_upstreamed", "patch_proposed_upstream",
                               "wording_proposed_upstream", "fixed_upstream"), f["id"]
        if f["status"] != "reported_not_upstreamed":
            assert f.get("upstream") == "aeoess/federation-port#1", f["id"]
        if f["status"] == "fixed_upstream":
            # Fixed only at the revision the probes now pin, and the observation keeps its own revision.
            assert f["fixed_in"] == cov["transport_revision"], f["id"]
            assert re.fullmatch(r"aeoess/federation-port@[0-9a-f]{40}", f["observed_at"]), f["id"]
            assert f["observed_at"] != f["fixed_in"], f["id"]


def test_the_probe_readme_counts_match_the_map() -> None:
    cov = _load()
    readme = (ROOT / "integrations/federation-port/contract-probes/README.md").read_text(encoding="utf-8")
    counts = {s: sum(c["status"] == s for c in cov["clauses"]) for s in cov["statuses"]}
    rows = {"covered": "covered by upstream or REMORA tests", "partly_covered": "partly covered, probes added",
            "probed": "probed, nothing covered it before", "stated_limit": "stated limit (section 10 says it itself)"}
    for status, label in rows.items():
        assert f"| {label} | {counts[status]} |" in readme, status
    assert f"lists {len(cov['clauses'])} rules" in readme
    assert f"holds {len(_probe_ids())} probes" in readme
