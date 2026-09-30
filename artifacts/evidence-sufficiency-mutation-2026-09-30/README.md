# Evidence-sufficiency mutation sweeps: raw outputs (2026-09-30)

Raw outputs behind the sweep totals in `docs/design/evidence-sufficiency-v1.3.md` section 7 and `docs/assurance/mutation_testing_v1.md`.
They were committed after an independent analysis (`artifacts/independent-analysis-2026-09-30/`) found that the historical totals had no raw output in the repository and that the named commands reproduced only the final rows.

Subject: `conformance/evidence-sufficiency-v1/checker.py`, sha256 `c4ca50aee2b2918b11c6fbde1f8615ca6c6bf1e5b6fa2ac1775f49c5e8c20be0`, at `c9113a05ad2a8f1dfa35de799d173e0a08cb12f9`.

| File | Command | Environment | Result |
|---|---|---|---|
| `mutmut-results-v1.2.txt` | `python scripts/mutation_evidence_sufficiency.py --scoring-suite evidence-sufficiency-v1.2 --results-out …` | `python:3.12-slim` container, mutmut 3.8.0 | 489 mutants, 377 killed, 112 survived |
| `mutmut-results-v1.3.txt` | `python scripts/mutation_evidence_sufficiency.py --results-out …` | same | 489 mutants, 469 killed, 20 survived; the 20 equal the baseline |
| `ast-first-run.json.gz` | `python scripts/mutation_evidence_sufficiency_ast.py --corpus first-run --json …` | Windows 11, CPython 3.14 | 905 mutants, 898 killed, 7 survived; 57 kills on one check (reference model 42, rejection 14, crash 1) |
| `ast-without-k1.json.gz` | `python scripts/mutation_evidence_sufficiency_ast.py --corpus without-k1 --json …` | same | 905, 901 killed, 4 survived; 60 kills on one check (42, 17, 1) |
| `ast-merged.json.gz` | `python scripts/mutation_evidence_sufficiency_ast.py --json …` | same | 905, 901 killed, 4 survived; 18 kills on one check (rejection 17, crash 1) |

`ast-merged-v1.4.json.gz` is the same second set scored by the v1.4 runner, with the AST script's `RUNNER` pointed at `conformance/evidence-sufficiency-v1.4/` and `--workers 1`.
It kills 901 with the same 4 survivors, and no kill in it rests on an L1 case alone. sha256 `6c8fc9d11b574e4734c7f52577d7ca48bf99fb74ebd198c011ae4e9a0df58e82`.

The v1.2 survivors contain the v1.3 survivors, and the 92 mutants only v1.3 kills are families A, B, D and E of NEGATIVE_RESULTS.md §65 (41 + 40 + 8 + 3).
The family split itself is a hand classification and is not recomputed here.
`ast-merged.json.gz`, with its `corpus` field removed, is identical to the `ast-sweep.json` the independent analysis produced on its own host.

`first-run` and `without-k1` are reconstructions: neither corpus state was ever committed on its own, so the script rebuilds each by removing the K1 cases and, for `first-run`, rejections R18 to R20.
The `first-run` result corrects the record, which had given the first run 60 one-check kills; 60 belongs to `without-k1` (NEGATIVE_RESULTS.md §67).

sha256 (LF):

```text
8feca023d96e395366238bf69e10d86aed6eb4509ef75858a39ec6f20cf33183  mutmut-results-v1.2.txt
9f8d87c8cbd35e176ced99bd9b085bc2c88451d27cba5dd8d1974685d948a823  mutmut-results-v1.3.txt
b2ed58d4e0bcdd09ae3e01fd043ef2d5f9c5f6130a48a5229ac793dcee07ae0b  ast-first-run.json.gz
08709b4d9bb64010ce3b5d5ed1ae52e24ec7673fc3382ea0f53e18201ab8861d  ast-without-k1.json.gz
6b9d44ed57098879aff7c36039fcadfe34c7a53fecd52abbc3f36d5602e4df80  ast-merged.json.gz
```
