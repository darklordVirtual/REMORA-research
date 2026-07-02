# REMORA Artifact Manifest v1

**Generated:** 2026-06-30
**Revised:** 2026-07-02 (see Revision Note below)
**Repository commit:** `2cd573d6a7c98e87c1781fd599469d9d46e132e2` (original), revised at working tree of 2026-07-02
**Checksum encoding:** SHA-256, lowercase hex, computed over committed (LF) file bytes

All checksums are computed from the committed file bytes (LF line endings, as
stored in git blobs and as checked out on Linux/macOS and in CI). On Windows
working trees with `autocrlf`, verify against the LF-normalized content or use
`git show HEAD:<path> | sha256sum`. Re-running benchmarks will produce files
with the same content for fully deterministic scripts, but timestamps inside
provenance fields will differ.

Continuous verification: `scripts/check_claim_provenance.py` recomputes every
checksum in this manifest in CI and fails on mismatch.

## Revision Note (2026-07-02)

The 2026-06-30 checksums were computed on a Windows working tree with CRLF
line endings, so they did not match the committed (LF) bytes that CI and
Linux/macOS replicators see. All checksums below are re-issued over LF bytes.
Verification performed before re-issuing:

- 10 of 21 entries already matched LF bytes and are unchanged.
- 10 entries matched byte-for-byte after CRLF→LF normalization (content
  identical; representation-only correction). Two of these additionally had a
  hand-transcription casing typo (`F` for `f`), now canonicalized.
- `results/external_benchmark_agentharm_v1.json` (P0, REM-014) is the only
  content change: the prior hash `b27ccd37…` corresponds to the version at
  commit `e2b235f` (verified against the git blob); commit `59c1670`
  ("Wave 3 P0 — oracle quorum gate + P0 safety artifact provenance") added
  provenance fields to the artifact without updating this manifest. The gate
  invariants (`false_accept_rate = 0.0`, `n_harmful = 208`) are unchanged
  between versions. This entry is re-issued under this documented protocol.

---

## Primary Safety Gate Artifacts

These are the two hard P0 release-blocker artifacts (REM-014, REM-019). Checksums
must not change unless the benchmark is re-run under a documented protocol.

| File | SHA-256 | Size (bytes) | Last modified | Gate |
|------|---------|-------------|---------------|------|
| `results/external_benchmark_agentharm_v1.json` | `5170a7176e7a60fc7afaaa35d005ced97cfd1d2c4ec1f7154b9359b73e70e45a` | 201458 | 2026-06-29T08:02:39 | REM-014 PASS |
| `results/false_accept_regression_v1.json` | `2a1f2b6af17270a36b2a441580246e59a6eabea901a0c30986b63e2fdaa6d54b` | 70606 | 2026-06-29T07:31:54 | REM-019 PASS |

**Invariants verified from artifact content:**
- `external_benchmark_agentharm_v1.json`: `false_accept_rate = 0.0`, `n_harmful = 208`, `n_harmful_blocked = 208`, `gate = "PASS"`
- `false_accept_regression_v1.json`: `false_accept_rate = 0.0`, `n_scenarios = 167`, `n_blocked = 167`, `gate = "PASS"`

---

## Benchmark Result Artifacts

| File | SHA-256 | Size (bytes) | Last modified | Description |
|------|---------|-------------|---------------|-------------|
| `results/toolcall_blind_v3_results.json` | `999b4673d9240e2cbe8fc7cdaaf1db365cf24a5b8cfc5b77628ab74e124208b0` | 601 | 2026-06-28T23:17:36 | Blinded benchmark v3: FAR=0.0, N=700 (REM-009) |
| `results/selective_n500_holdout_results.json` | `eedb8d203d65d5a94aa955d319129e9e27e7e5f48cc527fdbb684c3268e0ed29` | 1670 | 2026-06-01T22:40:21 | Held-out selective accuracy: 88% at 23.2% coverage |
| `results/selective_n500_results.json` | `34fd54479e54437610226452fefb8aab72c7f8cca0aabf8db3c91828c032c12e` | 12725 | 2026-06-09T22:51:30 | Full N=500 selective trust evaluation |
| `results/thermodynamic_eval_n500_calibrated_results.json` | `ec2eacf7ff6ce4e79467fed2f6f9f5cb103d6b0faaa97eac3c6f45e1bf97cce2` | 349515 | 2026-06-09T22:51:30 | N=500 thermodynamic calibration (data source for holdout) |
| `results/phase_aware_guardrail_n544_results.json` | `22961a33638e86be925608eb2301f292d61ac79f9d6f3d62e473cce8ef22e77e` | 4488 | 2026-06-09T22:51:30 | Phase-aware conformal guardrail N=544 |
| `results/conformal_guardrail_holdout.json` | `f9f77b3eace3aacb831a618f8ed50201482d331148663adaab2b8661da8d501d` | 121621 | 2026-06-09T22:51:30 | Conformal guardrail holdout evaluation |
| `results/conformal_repeated_splits.json` | `044c89b1076bfab05df8574eadd3a58e3e5bf88b83b8f88f7f42b15a041f9300` | 1164 | 2026-06-30T11:21:09 | Conformal repeated-splits robustness check |
| `results/toolcall_benchmark_v2_results.json` | `d6e69b37f7b2e3b2a670fbcaa76dd1c2c817dbdd436d1ea70677dafe32cbdb8d` | 17115 | 2026-05-31T22:38:13 | Toolcall benchmark v2: FAR=0.0, N=700 |
| `results/toolcall_llm_baselines_pilot_n100.json` | `a825fd5b3ce36db086b21b72b15d961d3b0e9915d5aab78ae0b539569cdb287a` | 117701 | 2026-06-29T00:07:39 | LLM baselines pilot N=100 (REM-010) |
| `results/m1_flag_coverage.json` | `b8c57f5b8e02ca39107695396d38bff4733eb469c058b90549d50bc3bf4e7c6d` | 544 | 2026-06-28T22:45:40 | M1 structural/keyword flag coverage on toolcall_blind_v3 |
| `results/toolcall_m1_clean_signal.json` | `983b72d7bd04d780c4b99bc6df508ffad61b5da25c8e3a191c27d711626f36b5` | 2601 | 2026-06-28T22:44:52 | M1 leakage clean-signal evaluation (REM-001) |
| `results/ablation_report.txt` | `60c3514bde738affbc65448485812e3b2bcfd2262928d33f6c2f8ac331f9a3c2` | 9217 | 2026-06-08T01:48:02 | Ablation study report |
| `results/trust_calibration_report.json` | `83a5cb4190a6446f6fcb462c0e62226cdc0f52b75ca8569e12e87c305e83acc1` | 9579 | 2026-05-31T22:38:13 | Trust calibration report |
| `results/gainability_routing.json` | `7d5245f410ed360362abed0720aabed2c959a2383951f6cdc35be68536a611e7` | 291 | 2026-06-09T22:51:30 | Gainability routing result |
| `results/evidence_v2_n500.json` | `322a4f8a90bd111e98a48a9ae6f58442395986f86d999afb799467b473d18b1e` | 406 | 2026-06-09T22:51:30 | Evidence routing N=500 |

---

## Artifact Summary Files

| File | SHA-256 | Size (bytes) | Last modified | Description |
|------|---------|-------------|---------------|-------------|
| `artifacts/benchmark_summary.json` | `f5034dc8af12bbff9ab3b13a2b184fcd42b13dd10cdcbd50d0a2332a4c9dfd64` | 1933 | 2026-06-11T11:02:42 | Snapshot of headline benchmark metrics |
| `artifacts/benchmark_n500_locked.json` | `6618dfde3ec1aec8d5a27f832b1998113dc1ba4945c85f3a0d6df70f1d1eff28` | 415749 | 2026-05-31T22:38:13 | N=500 locked benchmark data |
| `artifacts/agentharm_test_public_results.json` | `c5be1c536723f5cb3631f39cb9e8563eba78b2a5282ec27776b9be36388d9283` | 35303 | 2026-06-04T00:51:25 | AgentHarm test_public live results |
| `artifacts/domain_benchmark_results.json` | `10275f3ea6525aad1802aafb890881575b3d10868f11a8e13e566a3773defea5` | 21010 | 2026-06-03T22:54:13 | Cross-domain benchmark (cyber + AI governance + finance) |

---

## Assurance Documents

These documents are referenced by the remediation register and are part of the
assurance trail. They do not carry SHA-256 checksums here as they are living
documents that may be updated as gates are closed.

| File | Description | Status |
|------|-------------|--------|
| `docs/assurance/baseline_snapshot.md` | Quantitative state at assurance start (2026-06-28) | Locked |
| `docs/assurance/release_gates.md` | P0/P3 gate definitions and closure record | Living |
| `docs/assurance/remediation_register.yaml` | Full REM-001..022 register with artifacts and notes | Living |
| `docs/assurance/statistical_analysis_plan.md` | Pre-registered SAP for H1–H5 (REM-012) | Pre-registered, locked |
| `docs/assurance/operation_baseline_2026_06_30.md` | Wave 0 operational baseline | Locked |
| `docs/assurance/reproducibility_scorecard_v1.md` | This audit's reproducibility scorecard | Living |
| `docs/assurance/artifact_manifest_v1.md` | This document | Living |

---

## Provenance Gaps (Known)

The following result files lack a top-level `git_commit` or `current_system_commit`
field. This means the exact code version that generated them cannot be reconstructed
from the artifact alone.

| File | Gap | Recommendation |
|------|-----|---------------|
| `results/thermodynamic_eval_n500_calibrated_results.json` | No commit hash | Add `meta.git_commit` field in `experiments/end_to_end_n500_v3.py` |
| `results/ablation_report.txt` | Plain text, no provenance | Add header block: `# generated_by: ...\n# git_commit: ...\n# timestamp: ...` |
| `results/trust_calibration_report.json` | No commit hash | Add `git_commit` field in generating script |
| `results/selective_n500_results.json` | No top-level commit hash | Add `meta.git_commit` in generating script |

---

## How to Verify

To re-verify any checksum from this manifest:

```python
import hashlib, pathlib
def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

print(sha256("results/external_benchmark_agentharm_v1.json"))
# Expected: 5170a7176e7a60fc7afaaa35d005ced97cfd1d2c4ec1f7154b9359b73e70e45a
```

Or from the shell:
```bash
sha256sum results/external_benchmark_agentharm_v1.json
```

On Windows PowerShell:
```powershell
Get-FileHash results/external_benchmark_agentharm_v1.json -Algorithm SHA256 | Select-Object Hash
```

---

## Not Included in This Manifest

- `results/external_validation_raw.jsonl` (364 KB): large JSONL, checksummed separately per
  `docs/06-reproducibility.md` guidance. Add to next manifest revision.
- `results/external_validation_extended_raw.jsonl` (130 KB): same.
- `results/agentharm/` subdirectory: contains experiment-run outputs; paths vary by run.
- AROMER D1 episode corpus: stored in Cloudflare D1, not in this repository.
