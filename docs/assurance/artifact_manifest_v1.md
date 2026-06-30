# REMORA Artifact Manifest v1

**Generated:** 2026-06-30
**Repository commit:** `2cd573d6a7c98e87c1781fd599469d9d46e132e2`
**Python runtime used for checksums:** PowerShell `System.Security.Cryptography.SHA256` (equivalent to `hashlib.sha256`)
**Checksum encoding:** SHA-256, uppercase hex

All checksums were computed from the committed file bytes as they exist at the above
commit. Re-running benchmarks will produce files with the same content for fully
deterministic scripts, but timestamps inside provenance fields will differ.

---

## Primary Safety Gate Artifacts

These are the two hard P0 release-blocker artifacts (REM-014, REM-019). Checksums
must not change unless the benchmark is re-run under a documented protocol.

| File | SHA-256 | Size (bytes) | Last modified | Gate |
|------|---------|-------------|---------------|------|
| `results/external_benchmark_agentharm_v1.json` | `b27ccd376c7f8b1fd46d213947136bbc82a99db1ee3ff73b58e70719e7f532f7` | 206438 | 2026-06-29T08:02:39 | REM-014 PASS |
| `results/false_accept_regression_v1.json` | `1aadbb68236de3eecc07dc2f105f5bd6e49bdac05407ec187ffeef98dd673115` | 72955 | 2026-06-29T07:31:54 | REM-019 PASS |

**Invariants verified from artifact content:**
- `external_benchmark_agentharm_v1.json`: `false_accept_rate = 0.0`, `n_harmful = 208`, `n_harmful_blocked = 208`, `gate = "PASS"`
- `false_accept_regression_v1.json`: `false_accept_rate = 0.0`, `n_scenarios = 167`, `n_blocked = 167`, `gate = "PASS"`

---

## Benchmark Result Artifacts

| File | SHA-256 | Size (bytes) | Last modified | Description |
|------|---------|-------------|---------------|-------------|
| `results/toolcall_blind_v3_results.json` | `4c257a36213ef46039d5f75d873ca015ba3dd4cab42067132649f5162c863a9b` | 616 | 2026-06-28T23:17:36 | Blinded benchmark v3: FAR=0.0, N=700 (REM-009) |
| `results/selective_n500_holdout_results.json` | `eedb8d203d65d5a94aa955d319129e9e27e7e5F48cc527fdbb684c3268e0ed29` | 1670 | 2026-06-01T22:40:21 | Held-out selective accuracy: 88% at 23.2% coverage |
| `results/selective_n500_results.json` | `34fd54479e54437610226452fefb8aab72c7f8cca0aabf8db3c91828c032c12e` | 12725 | 2026-06-09T22:51:30 | Full N=500 selective trust evaluation |
| `results/thermodynamic_eval_n500_calibrated_results.json` | `ec2eacf7ff6ce4e79467fed2f6f9f5cb103d6b0faaa97eac3c6f45e1bf97cce2` | 349515 | 2026-06-09T22:51:30 | N=500 thermodynamic calibration (data source for holdout) |
| `results/phase_aware_guardrail_n544_results.json` | `22961a33638e86be925608eb2301f292d61ac79f9d6f3d62e473cce8ef22e77e` | 4488 | 2026-06-09T22:51:30 | Phase-aware conformal guardrail N=544 |
| `results/conformal_guardrail_holdout.json` | `f9f77b3eace3aacb831a618f8ed50201482d331148663adaab2b8661da8d501d` | 121621 | 2026-06-09T22:51:30 | Conformal guardrail holdout evaluation |
| `results/conformal_repeated_splits.json` | `b849795c449c5b5e7778bf43deef932289c598cf605be2febdcf518b768b922e` | 1201 | 2026-06-30T11:21:09 | Conformal repeated-splits robustness check |
| `results/toolcall_benchmark_v2_results.json` | `d6e69b37f7b2e3b2a670fbcaa76dd1c2c817dbdd436d1ea70677dafe32cbdb8d` | 17115 | 2026-05-31T22:38:13 | Toolcall benchmark v2: FAR=0.0, N=700 |
| `results/toolcall_llm_baselines_pilot_n100.json` | `977e430b7d7f0e18e330f1f7cef1ab869765721d7cb7989f6e9cf70b3668b676` | 122660 | 2026-06-29T00:07:39 | LLM baselines pilot N=100 (REM-010) |
| `results/m1_flag_coverage.json` | `9283b87fb3facf782a1554d4b2fd4f199a01b6060319e628a628da3b749e52bd` | 555 | 2026-06-28T22:45:40 | M1 structural/keyword flag coverage on toolcall_blind_v3 |
| `results/toolcall_m1_clean_signal.json` | `c49e64d8c0be15dde1686aa5b9ead0709ad8114412edff6e2261cec09b2f49aa` | 2653 | 2026-06-28T22:44:52 | M1 leakage clean-signal evaluation (REM-001) |
| `results/ablation_report.txt` | `26ef84d022ef8a14736054220e140b624fff14f6f8ceab46a4bd7b32d71ffa48` | 9365 | 2026-06-08T01:48:02 | Ablation study report |
| `results/trust_calibration_report.json` | `83a5cb4190a6446f6fcb462c0e62226cdc0f52b75ca8569e12e87c305e83acc1` | 9579 | 2026-05-31T22:38:13 | Trust calibration report |
| `results/gainability_routing.json` | `7d5245f410ed360362abed0720aabed2c959a2383951f6cdc35be68536a611e7` | 291 | 2026-06-09T22:51:30 | Gainability routing result |
| `results/evidence_v2_n500.json` | `322a4f8a90bd111e98a48a9ae6f58442395986f86d999afb799467b473d18b1e` | 406 | 2026-06-09T22:51:30 | Evidence routing N=500 |

---

## Artifact Summary Files

| File | SHA-256 | Size (bytes) | Last modified | Description |
|------|---------|-------------|---------------|-------------|
| `artifacts/benchmark_summary.json` | `7bdff2676eff2021c69a62b833fb1fe84083a1855e0729f7047d9ea34feaf8ec` | 1982 | 2026-06-11T11:02:42 | Snapshot of headline benchmark metrics |
| `artifacts/benchmark_n500_locked.json` | `6618dfde3ec1aec8d5a27f832b1998113dc1ba4945c85f3a0d6df70f1d1eff28` | 415749 | 2026-05-31T22:38:13 | N=500 locked benchmark data |
| `artifacts/agentharm_test_public_results.json` | `9ebb2b8e0561419c0097ee91aa8536f84f136b0108244c6d1ebebfe40f0b460e` | 36488 | 2026-06-04T00:51:25 | AgentHarm test_public live results |
| `artifacts/domain_benchmark_results.json` | `b8a1de4382b866e10bF9c8b387b4984def735ff79d3b1c8884fde51beca66827` | 21644 | 2026-06-03T22:54:13 | Cross-domain benchmark (cyber + AI governance + finance) |

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
# Expected: b27ccd376c7f8b1fd46d213947136bbc82a99db1ee3ff73b58e70719e7f532f7
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
