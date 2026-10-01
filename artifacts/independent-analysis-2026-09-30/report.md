# Independent analysis of evidence-sufficiency v1.3

Reviewed commit: `c9113a05ad2a8f1dfa35de799d173e0a08cb12f9` (master, fetched 2026-09-30).

## Files opened in order (A1 evidence)

Before selecting faults I opened, in order: `CONTRIBUTING.md`, `DEVELOPER_OVERVIEW.md`, `ARCHITECTURE.md`, `docs/10-contributing.md`, `conformance/evidence-sufficiency-v1/checker.py`, `conformance/evidence-sufficiency-v1/README.md`, and `conformance/evidence-sufficiency-v1/cases.json`. I had not opened the v1.3 tree, its design document, mutation scripts or baselines, or sections 65 and 66 of `NEGATIVE_RESULTS.md` before the fault definitions were hashed. The Git pull output exposed filenames but no contents. The first display of `ARCHITECTURE.md` was truncated; I reviewed its omitted middle sections only after scoring. Thus I did not fully satisfy the requested “read first” step, though no v1.3 content entered fault selection.

## Fault definitions hash (A3)

Before opening v1.3 or running its cases, I wrote 24 hand-picked and 19 systematic single-edit definitions to `fault-definitions.json`. Its SHA-256 is `241fe7d878df28021b3ee3294ea780a13a1b12c27fcba6c495fd14fe0c6d1733`. Each definition includes a unified diff, a witness input found from v1 cases and bounded perturbations, the original output, and the expected wrong output. The systematic class changes each of the 19 occurrences of `is not True` into `is not False`, one occurrence per mutant.

## Systematic class table

Measurement: I replaced each of the 19 occurrences of `is not True` in the complete frozen checker with `is not False`, one occurrence at a time. The catalogue and every edit are in `fault-definitions.json`; the per-case outputs and runner failures are in `raw-row-outputs.json.gz`. A cell is the number of mutants killed out of 19. Row 1 compares `(status, reason)` to authored expectations; row 2 compares guidance to the original checker; row 3 requires a nonempty runner `failures` list or a crash.

| Fault IDs | Operator denominator | v1.2 row 1 | v1.2 row 2 | v1.2 row 3 | v1.3 row 1 | v1.3 row 2 | v1.3 row 3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| S01-S19 | 19/19 occurrences | 19 | 19 | 19 | 19 | 19 | 19 |

Judgement: This class changes ordinary boolean behavior that v1.2 already covered. It provides a full denominator for one operator, but no differential evidence for v1.3. The source locations and witness inputs for every member are in the immutable definition file.

## Hand-picked fault table

Measurement: These 24 single-edit faults were chosen from the v1 checker and its v1 cases. `Y` means at least one case or runner check killed the fault. `N` means none did. Every row's exact cases, verdicts and failures are in `raw-row-outputs.json.gz` under the fault ID.

| Faults | Edit family | v1.2 rows 1/2/3 | v1.3 rows 1/2/3 |
|---|---|---|---|
| H01-H04 | execution, scope and admission source field confusion | Y/Y/Y each | Y/Y/Y each |
| H05-H06 | admission match and presence comparison | Y/Y/Y each | Y/Y/Y each |
| H07-H09 | admission requirement, window and coverage field confusion | Y/Y/Y each | Y/Y/Y each |
| H10-H13 | route, operation, PEP and effect source field confusion | Y/Y/Y each | Y/Y/Y each |
| H14 | protected-effect guard reads window completeness | Y/Y/Y | Y/Y/Y |
| H15 | `protected_effect_observed is not False` becomes `is None` | N/N/N | Y/Y/Y |
| H16-H18 | effect window, control and attribution field confusion | Y/Y/Y each | Y/Y/Y each |
| H19-H23 | read-back, source, target, freshness and settlement field confusion | Y/Y/Y each | Y/Y/Y each |
| H24 | compare states with Python `==` instead of `canonical()` | Y/N/Y | Y/N/Y |
| **Total killed / 24** | | **23/22/23** | **24/23/24** |

Measurement: H15's witness is a route observation with `protected_effect_observed: 0`. The original returns `not_established/protected_effect_unknown`; the mutant returns `not_established/refusal_not_attributed_to_required_boundary` (fault definitions, H15). v1.3 cases B21 and B25 kill it on rows 1 and 2, and its runner lists those cases plus 12 model disagreements. v1.2 returns an empty `failures` list. H24 is killed by E08 on row 1 and by both runners, while guidance stays empty for both decisive verdicts. No fault was killed only by row 3.

## Survivor judgements

Measurement: All 43 faults were killed on v1.3 row 3; there is no v1.3 survivor to relabel. H15 is the only fault to survive all three v1.2 rows. H24 survives the guidance projection in both versions but is killed by status/reason and runner checks (`raw-row-outputs.json.gz`).

Judgement: H15 is an open v1.2 gap, not an equivalent fault. The accepted JSON vocabulary includes the integer `0`; exact `is not False` treats it as an unknown observation, whereas `is None` lets it pass to a different reason. It is in scope under the exact-boolean premise discipline of `conformance/evidence-sufficiency-v1/checker.py:238-240` and `docs/design/evidence-sufficiency-v1.3.md:273-279`. v1.3 closes it with K1 cases. H24's row-2 survival is outside that projection's contract: decisive verdicts carry no guidance (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md:98-100`).

## v1.2 versus v1.3 comparison

Measurement: On the same 43 faults, v1.2 kills 42 on runner row 3 and v1.3 kills 43. The only new runner kill is H15. v1.3 adds B21 and B25, both K1 typed-premise cases, and a model disagreement check. The original committed runners reproduce byte for byte with `python conformance/evidence-sufficiency-v1.2/run_evidence_sufficiency.py --check` and the corresponding v1.3 command (both exited 0).

Judgement: This is a measured improvement on this preselected set. It does not establish transfer to a new fault family: the added cases were derived from the same typed-premise family (`docs/design/evidence-sufficiency-v1.3.md:273-300`).

## Post-hoc comparison with the answer key (A6)

Measurement: Only after the two-version scoring did I read `docs/design/evidence-sufficiency-v1.3.md` sections 6-8 and 12, `docs/assurance/mutation_testing_v1.md`, and `NEGATIVE_RESULTS.md` sections 65-66. The named families in the answer key are field confusion, comparison variants, state comparison, and typed premises (`docs/design/evidence-sufficiency-v1.3.md:256-279`; `NEGATIVE_RESULTS.md:4061-4102`). H01-H14 and H16-H23 fit field confusion or guard comparison. H15 fits the typed-premise comparison family and is killed by K1. H24 is the raw-equality fault already discussed in the external v1.1 run (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md:96-105`). The S class fits comparison variants. There is no new survivor family in this experiment.

Judgement: The repository's classifications hold for my witnesses. The H15 witness is a real v1.2 gap and is correctly closed by v1.3. H24 is a row-2 projection limit rather than an untested overall fault. I found no evidence here to overturn the four v1.3 AST survivor equivalence arguments (`docs/assurance/mutation_testing_v1.md:269-286`), but this experiment did not independently prove equivalence.

## Claim audit (B1 to B5)

### B1. Numerical claims and reproducibility

| Claimed quantity | Committed source and reproduction | My result |
|---|---|---|
| 26 v1, 50 v1.1, 53 v1.2, 79 v1.3 authored cases; 23 K1 cases; 11 metamorphic relations | Each version's `cases.json` and `run-record.json`; v1.3 `invariants.json`. `audit_counts.py` counts these directly; all four `run_evidence_sufficiency.py --check` commands exited 0. | Reproduced. v1.3 has 79 cases, including 23 K1, and 11 recorded relations. |
| 61,236 lattice documents + 308 typed documents = 61,544; no checker/model disagreement | `conformance/evidence-sufficiency-v1.3/run-record.json:934-943`, `model.json`, runner `--check`; design `:243-254`. | Reproduced byte for byte; `disagreement_count` is 0. |
| 489 mutmut mutants; v1.2 377 killed/112 survived; v1.3 469 killed/20 survived | `docs/assurance/mutation_testing_v1.md:219-250`, design `:281-290`, `scripts/mutation_evidence_sufficiency.py`; the committed v1.3 baseline names 20 survivors. | The 20 names are on disk. I could not rerun either sweep: mutmut 3.8.0 refuses native Windows, and WSL returns access denied. No raw `mutmut results --all` for either sweep is committed here. The current script scores v1.3 only, so its named reproduce command alone cannot reproduce the historical v1.2 377/112 comparison. These three totals and the v1.2 family counts remain unverified by my run. |
| Second set: 705 first-order + 200 second-order = 905; 901 killed, 4 survived; 18 one-label kills | `scripts/mutation_evidence_sufficiency_ast.py`, `docs/assurance/mutation_baseline_evidence_sufficiency_ast_v1.txt`, design `:256-269`, and the committed narrative at `docs/assurance/mutation_testing_v1.md:252-284`. | Reproduced using the unchanged scoring function with a sequential executor because Windows blocked its process pool. `ast-sweep.json` records 905/901/4, exactly four baseline survivors, and 18 one-label kills (17 rejection, 1 crash). |
| Historical second-set figures: 898/905, seven survivors, 60 one-label kills, 42 model-only kills before K1, and three `isinstance` survivors before R18-R20 | Design `:281-299`, `NEGATIVE_RESULTS.md:4061-4102`. | Not reproducible at this pinned commit without reconstructing the superseded pre-K1 corpus and earlier rejection table. The current script reproduces only the final 901/4. No raw historical sweep output is committed here. |
| Earlier external v1 and v1.1 row counts, plus the v1.2 rerun | `docs/assurance/external_adequacy_evidence_sufficiency_v1.md:1-145` links pinned external reports and gives tool identities; the v1.2 report is still private (`:121-145`). | I verified the local record, not those external packages or their raw rows. The v1.2 counts are intentionally absent locally. They cannot be reproduced from the committed local tree alone. |
| 300 derandomised generated examples per property | `docs/research/research_control_matrix_v1.yaml:991-1003` and generated `.md:360`. | Incorrect as written: `tests/test_evidence_sufficiency_v1_3.py:357` sets `max_examples=150` for each decorated property. Design `:291-293` says 150. |
| A 17-input rejection contract | `docs/research/research_control_matrix_v1.yaml:987-989` and generated `.md:360`. | Stale for merged v1.3: `cases.json` has ten JSON rejections and `run_evidence_sufficiency.py:51-64` declares ten non-JSON inputs. The current README describes ten plus ten. |

The numerical drift in the control matrix is a documentation finding, not evidence that checker behavior is wrong. The matrix's single reproduce sentence also combines `--check` with the mutmut script while making historical v1.2 and pre-K1 claims that neither current command produces (`docs/research/research_control_matrix_v1.yaml:982-1003`). I found no evidence-sufficiency entry in `docs/assurance/claim_register_v1.yaml` or `results_manifest_v1.yaml`; its numerical narrative lives mainly in RES-021, the design, and mutation-testing notes. The document register catalogs those files (`docs/assurance/document_register_v1.yaml:2571-2603`) but does not supply the missing historical rows.

### B2. Fitted results and generalisation language

I found no sentence that explicitly says the fitted kills establish generalisation. The repository says the opposite in `docs/design/evidence-sufficiency-v1.3.md:295-300`, `conformance/evidence-sufficiency-v1.3/README.md` under “Non-claims”, and `docs/research/research_control_matrix.generated.md:362`. However, `CHANGELOG.md:24` introduces the fitted model and second-set results as “Generalisation measures, same day.” That label is easy to read more strongly than the immediately preceding caveat at `CHANGELOG.md:21-23`. It should be read as an internal stress test, not independent confirmation.

### B3. Identity of external runs

The v1 and v1.1 local record gives subject commits, checker hash, corpus hash for v1, tool version and commit, and pinned external report URLs (`docs/assurance/external_adequacy_evidence_sufficiency_v1.md:5-14,48-61`). It does not carry the complete fault definitions or their digest locally. The six additional v1.1 faults are said to have been committed by hash in an external commit (`:79-86`), but the digest is not copied into this record. The v1.2 run names its subject commit and tool, but its linked package and counts are private (`:121-145`); a third party cannot redo that run from this checkout alone. My own definitions, hash, scripts, and raw rows are attached here, with Python 3.14.0 as the interpreter. The hash was written to a local report before v1.3 was opened, but it was **not publicly committed before execution**. This run therefore does not meet section 8's public-commit requirement (`docs/design/evidence-sufficiency-v1.3.md:302-313`).

### B4. Limits and non-claims

Judgement: The main non-claims are appropriately cautious: the checker uses trusted synthetic premises, does not validate deployment provenance, and the reference model shares author and specification with it (`conformance/evidence-sufficiency-v1.3/README.md`, “Non-claims”; `docs/design/evidence-sufficiency-v1.3.md:112-120`). The `scope` coercion limitation is disclosed in the spec and run record, but under-disclosed in the README: a sequence of pairs is accepted, and an unconvertible non-mapping raises `TypeError` rather than the stated `ValueError` rejection class (`docs/design/evidence-sufficiency-v1.3.md:194-207`). This experiment did not exercise that out-of-contract path.

Judgement: The RES-021 scope boundary says “One tool with its default operators” even though the same entry reports a second authored operator set (`docs/research/research_control_matrix_v1.yaml:997-1010`). More importantly, the final second-set count is fitted: K1 cases and R18-R20 were added after its survivors were seen (`docs/design/evidence-sufficiency-v1.3.md:129-134,273-300`). The design itself discloses this accurately. The two stale RES-021 numbers above overstate the actual generated-example budget and understate the present rejection count.

### B5. Acceptance criterion for generalisation

I would require a public, time-ordered commitment of the fault definitions and source commit before any v1.3 access; at least 30 held-out, behavior-changing faults across two distinct operators plus one complete operator class with its full denominator; the three raw rows and crashes for both v1.2 and v1.3; and survivor labels fixed before corpus changes. A pass would require **every non-equivalent held-out fault to be killed on v1.3 runner row 3**. Report row-1 and row-2 misses independently, and treat any non-equivalent row-3 survivor as an open gap rather than adjusting the denominator. This uses the repository's own zero-open-gap threshold (`docs/design/evidence-sufficiency-v1.3.md:307-313`) while requiring broader fault selection and a verifiable public commitment. My 43-fault run met the numeric row-3 threshold, but not the public commitment or new-family breadth requirements.

## What you did not do and why

I did not edit the frozen v1-v1.3 suites or the checker. The assignment asked for measurement and criticism, and changing the subject would invalidate the comparison. I did not claim that the corpus or REMORA's production security is proved: the checker accepts synthetic fixture premises, and no deployment path was tested (`conformance/evidence-sufficiency-v1/README.md`, “Synthetic premise boundary”).

For assignment B, I searched the complete `CHANGELOG.md`, `NEGATIVE_RESULTS.md`, research matrix, and assurance registers for evidence-sufficiency claims and reviewed the matching passages and their cited artifacts. I did not read every unrelated register entry and negative-result section end to end. This is a deviation from the attachment's “in full” reading instruction; the audit is focused on the identified evidence-sufficiency claims.

I did not reproduce the mutmut counts on this Windows host; `python -m mutmut --version` exits with “To run mutmut on Windows, please use the WSL,” and `wsl --status` returns `E_ACCESSDENIED`. The original AST command also failed because Windows denied the process pool's pipe; `run_ast_sequential.py` changed only the executor and then reproduced its final counts. The focused pytest command collected 77 tests, with 53 passing and 24 setup errors because this sandbox denied pytest's temporary directory. Four committed suite `--check` commands and the independent 43-fault run completed.

The fault hash was local rather than public before the run, so this is a locally pre-registered analysis, not the external confirmation specified in the v1.3 design. No v1.4 changes should be inferred from these results alone. The immediately actionable documentation corrections are the RES-021 example and rejection counts and the reproducibility wording for historical mutation totals.
