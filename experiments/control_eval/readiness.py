# SPDX-License-Identifier: BUSL-1.1
"""Machine-checkable readiness gates for the sealed control-evaluation run.

``scripts/check_study_readiness.py`` prints these as a table and exits 0
only when every gate passes; ``scripts/run_control_eval.py --test`` refuses
to start otherwise. Each gate reports PASS, FAIL (something exists and is
wrong) or PENDING (the step has not been done yet), with a reason.

G0  plan file exists and is not marked DRAFT
G1  development futility artifact exists and its verdict is ``pass``
G2  harness files present, and a test marker shows the harness tests passed
    on exactly these files
G3  pilot artifact: measured cost per episode, undefended attack success on
    development at or above the configured minimum (otherwise the study
    cannot discriminate; WS1 Study B had 3/60), thresholds frozen, and no
    held-out suite in the pilot
G4  sealed manifest: status ``locked_never_run``, LF SHA-256 of every listed
    file matches the working tree, the plan and harness files are listed, an
    OpenTimestamps proof path exists and ``scripts/ots_seal.py`` exists
G5  OSF registration id recorded in the manifest and verified on the public
    OSF API (200, not withdrawn, protocol hash matching when retrievable)
G6  remaining test budget in the ledger covers the cost projected from the
    pilot for the manifest's planned sample

The OSF fetch is injected (``fetch(url) -> (status, json_or_None)``), so the
tests run without network.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiments.control_eval.sealed_run import LOCKED, changed_files
from experiments.sap_v7_addenda.seal import lf_sha256

PASS, FAIL, PENDING = "PASS", "FAIL", "PENDING"
OSF_API = "https://api.osf.io/v2/registrations/{id}/"
Fetch = Callable[[str], tuple[int, Any]]
_HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


@dataclass(frozen=True)
class GateResult:
    gate: str
    title: str
    status: str
    reason: str


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _r(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    return cfg.get("readiness") or {}


def g0_plan(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "plan registered, not DRAFT"
    rel = _r(cfg).get("plan")
    if not rel:
        return GateResult("G0", title, PENDING, "readiness.plan not set")
    path = root / rel
    if not path.is_file():
        return GateResult("G0", title, PENDING, f"{rel} does not exist")
    head = path.read_text(encoding="utf-8").splitlines()[:40]
    if any(re.search(r"\bDRAFT\b", line) for line in head):
        return GateResult("G0", title, FAIL, f"{rel} is marked DRAFT")
    return GateResult("G0", title, PASS, f"{rel} exists, not marked DRAFT")


def g1_futility(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "dev futility check passed"
    rel = _r(cfg).get("futility_artifact")
    if not rel or not (root / rel).is_file():
        return GateResult("G1", title, PENDING, f"futility artifact {rel!r} not present")
    try:
        verdict = _json(root / rel).get("verdict")
    except (ValueError, AttributeError):
        return GateResult("G1", title, FAIL, f"{rel} is not a JSON object")
    if verdict == "pass":
        return GateResult("G1", title, PASS, f"{rel}: verdict pass")
    return GateResult("G1", title, FAIL, f"{rel}: verdict {verdict!r}")


def harness_digest(root: Path, files: Sequence[str]) -> dict[str, str]:
    return {rel: lf_sha256(root / rel) for rel in files}


def write_harness_marker(root: Path, files: Sequence[str], tests: Sequence[str],
                         marker: Path, python: str = sys.executable) -> bool:
    """Run *tests* with pytest; write a marker binding the pass to *files*' hashes."""
    missing = [f for f in [*files, *tests] if not (root / f).is_file()]
    if missing:
        raise FileNotFoundError(f"missing: {missing}")
    proc = subprocess.run([python, "-m", "pytest", "-q", "--no-cov", "-p", "no:cacheprovider",
                           *tests], cwd=root, capture_output=True, text=True, check=False)
    passed = proc.returncode == 0
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"passed": passed, "tests": list(tests),
                                  "files": harness_digest(root, files),
                                  "summary": proc.stdout.strip().splitlines()[-1:]},
                                 indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return passed


def g2_harness(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "harness present, tests passed"
    r = _r(cfg)
    files = list(r.get("harness_files") or [])
    if not files:
        return GateResult("G2", title, PENDING, "readiness.harness_files not set")
    missing = [f for f in files if not (root / f).is_file()]
    if missing:
        return GateResult("G2", title, FAIL, f"harness files missing: {missing}")
    rel = r.get("harness_marker")
    if not rel or not (root / rel).is_file():
        return GateResult("G2", title, PENDING, "no harness test marker; run "
                          "check_study_readiness.py --write-harness-marker")
    marker = _json(root / rel)
    if marker.get("passed") is not True:
        return GateResult("G2", title, FAIL, f"{rel}: harness tests failed")
    if marker.get("files") != harness_digest(root, files):
        return GateResult("G2", title, FAIL, f"{rel} was written for other file contents; rerun")
    return GateResult("G2", title, PASS, f"{len(files)} files, tests passed on these hashes")


def _pilot(cfg: Mapping[str, Any], root: Path) -> tuple[Mapping[str, Any] | None, str]:
    rel = _r(cfg).get("pilot_artifact")
    if not rel or not (root / rel).is_file():
        return None, f"pilot artifact {rel!r} not present"
    return _json(root / rel), str(rel)


def g3_pilot(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "pilot: cost, undefended ASR, thresholds"
    pilot, rel = _pilot(cfg, root)
    if pilot is None:
        return GateResult("G3", title, PENDING, rel)
    held = sorted(set(pilot.get("suites") or ()) & set(cfg.get("holdout_suites") or ()))
    if held:
        return GateResult("G3", title, FAIL, f"pilot ran held-out suites {held}")
    per_episode = (pilot.get("cost") or {}).get("per_episode_usd")
    if not isinstance(per_episode, int | float) or per_episode <= 0:
        return GateResult("G3", title, FAIL, "pilot has no measured cost.per_episode_usd")
    und = pilot.get("undefended") or {}
    k, n = und.get("attack_successes"), und.get("attacked_pairs")
    minimum = _r(cfg).get("min_undefended_asr")
    if not isinstance(minimum, int | float):
        return GateResult("G3", title, PENDING, "readiness.min_undefended_asr not set")
    if not isinstance(k, int) or not isinstance(n, int) or n <= 0:
        return GateResult("G3", title, FAIL, "pilot has no undefended attack counts")
    if k / n < minimum:
        return GateResult("G3", title, FAIL, f"undefended ASR {k}/{n} = {k / n:.3f} below the "
                          f"minimum {minimum}; the study cannot discriminate")
    thresholds = pilot.get("thresholds") or {}
    needed = list(_r(cfg).get("required_thresholds") or ())
    if thresholds.get("frozen") is not True:
        return GateResult("G3", title, PENDING, "thresholds not frozen")
    absent = [t for t in needed if t not in thresholds]
    if absent:
        return GateResult("G3", title, FAIL, f"frozen thresholds lack {absent}")
    return GateResult("G3", title, PASS, f"{per_episode:.4f} USD/episode, undefended ASR "
                      f"{k}/{n}, thresholds frozen")


def _manifest(cfg: Mapping[str, Any], root: Path) -> tuple[Mapping[str, Any] | None, str]:
    rel = _r(cfg).get("manifest")
    if not rel or not (root / rel).is_file():
        return None, f"sealed manifest {rel!r} not present"
    try:
        return _json(root / rel), str(rel)
    except ValueError:
        return {}, str(rel)


def g4_seal(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "sealed manifest, hashes, timestamp proof"
    body, rel = _manifest(cfg, root)
    if body is None:
        return GateResult("G4", title, PENDING, rel)
    if body.get("status") != LOCKED:
        return GateResult("G4", title, FAIL, f"{rel}: status {body.get('status')!r}, not {LOCKED!r}")
    needed = [*(_r(cfg).get("harness_files") or ()), _r(cfg).get("plan")]
    unlisted = sorted(f for f in needed if f and f not in (body.get("files") or {}))
    if unlisted:
        return GateResult("G4", title, FAIL, f"not sealed: {unlisted}")
    changed = changed_files(body, root)
    if changed:
        return GateResult("G4", title, FAIL, f"changed after sealing: {changed}")
    if not (root / "scripts" / "ots_seal.py").is_file():
        return GateResult("G4", title, FAIL, "scripts/ots_seal.py is missing")
    proof = body.get("ots_proof")
    if not proof or not (root / proof).is_file():
        return GateResult("G4", title, PENDING, f"OpenTimestamps proof {proof!r} not present")
    return GateResult("G4", title, PASS, f"{len(body['files'])} files match; proof {proof}")


def osf_fetch(url: str) -> tuple[int, Any]:  # pragma: no cover - network
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.api+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - fixed https host
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


def g5_osf(cfg: Mapping[str, Any], root: Path, fetch: Fetch | None = None) -> GateResult:
    title = "OSF registration verified"
    body, rel = _manifest(cfg, root)
    if body is None:
        return GateResult("G5", title, PENDING, rel)
    reg = body.get("osf_registration_id")
    if not reg:
        return GateResult("G5", title, PENDING, f"{rel} records no osf_registration_id")
    if not re.fullmatch(r"[A-Za-z0-9]{5,}", str(reg)):
        return GateResult("G5", title, FAIL, f"registration id {reg!r} is malformed")
    try:
        status, doc = (fetch or osf_fetch)(OSF_API.format(id=reg))
    except OSError as exc:
        return GateResult("G5", title, FAIL, f"OSF API unreachable: {exc}")
    if status != 200 or not isinstance(doc, Mapping):
        return GateResult("G5", title, FAIL, f"OSF API returned {status} for {reg}")
    attrs = (doc.get("data") or {}).get("attributes") or {}
    if attrs.get("withdrawn") or attrs.get("pending_withdrawal"):
        return GateResult("G5", title, FAIL, f"registration {reg} is withdrawn")
    plan = _r(cfg).get("plan")
    expected = (body.get("files") or {}).get(plan) if plan else None
    if expected is None and plan and (root / plan).is_file():
        expected = lf_sha256(root / plan)
    found = set(_HEX64.findall(json.dumps(
        {k: attrs.get(k) for k in ("description", "registration_responses", "registered_meta")},
        default=str).lower()))
    if found and expected not in found:
        return GateResult("G5", title, FAIL, f"registration {reg} records a protocol hash that "
                          "is not the sealed plan's")
    if expected in found:
        return GateResult("G5", title, PASS, f"{reg} live; protocol hash matches")
    return GateResult("G5", title, PASS, f"{reg} live, not withdrawn; no protocol hash "
                      "retrievable from the public metadata")


def ledger_spend(path: Path) -> tuple[float, dict[str, float]]:
    if not path.is_file():
        return 0.0, {}
    from experiments.control_eval.spend_ledger import PriceTable, SpendLedger
    t = SpendLedger(path, PriceTable({}), phase_caps_usd={}).totals()
    return t.total_usd, t.by_phase


def g6_budget(cfg: Mapping[str, Any], root: Path) -> GateResult:
    title = "budget covers projected run"
    pilot, prel = _pilot(cfg, root)
    body, mrel = _manifest(cfg, root)
    if pilot is None or body is None:
        return GateResult("G6", title, PENDING, prel if pilot is None else mrel)
    cost = pilot.get("cost") or {}
    pairs, benign = body.get("planned_pairs"), body.get("planned_benign_tasks")
    per_pair, per_benign = cost.get("per_attacked_pair_usd"), cost.get("per_benign_task_usd")
    if not all(isinstance(v, int | float) for v in (pairs, benign, per_pair, per_benign)):
        return GateResult("G6", title, PENDING, "planned sample or pilot unit costs missing")
    projected = pairs * per_pair + benign * per_benign
    budget = cfg.get("budget") or {}
    total_cap = float(budget.get("total_cap_usd", 50.0))
    test_cap = float((budget.get("phase_caps_usd") or {}).get("test", 0.0))
    spent, by_phase = ledger_spend(root / str(budget.get("ledger", "")))
    remaining = min(total_cap - spent, test_cap - by_phase.get("test", 0.0))
    if remaining < projected:
        return GateResult("G6", title, FAIL, f"projected {projected:.2f} USD > remaining "
                          f"{remaining:.2f} USD")
    return GateResult("G6", title, PASS, f"projected {projected:.2f} USD <= remaining "
                      f"{remaining:.2f} USD")


def check_readiness(cfg: Mapping[str, Any], root: Path, fetch: Fetch | None = None
                    ) -> list[GateResult]:
    return [g0_plan(cfg, root), g1_futility(cfg, root), g2_harness(cfg, root),
            g3_pilot(cfg, root), g4_seal(cfg, root), g5_osf(cfg, root, fetch),
            g6_budget(cfg, root)]


def all_pass(results: Sequence[GateResult]) -> bool:
    return all(r.status == PASS for r in results)


def render(results: Sequence[GateResult]) -> str:
    rows = [("Gate", "Check", "Status", "Reason")] + [(r.gate, r.title, r.status, r.reason)
                                                      for r in results]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = []
    for n, row in enumerate(rows):
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(3)) + "  " + row[3])
        if n == 0:
            lines.append("  ".join("-" * w for w in widths) + "  " + "-" * 6)
    return "\n".join(lines)
