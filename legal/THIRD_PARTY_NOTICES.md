# Third-Party Notices

The Business Source License applies only to original material for which
the REMORA Licensor has the necessary rights.

Third-party software, datasets, models, publications and other materials
remain governed by their original licenses and terms. Nothing in the
REMORA licensing model relicenses third-party material.

## Python and JavaScript dependencies

Dependencies installed through Python or frontend package managers are
not relicensed as part of REMORA. Their applicable licenses are defined
by the corresponding dependency distributions (see `requirements-lock.txt`
and `frontend/package-lock.json` for the exact resolved versions).

## External datasets, benchmarks and tools

| Material | Source | Use in REMORA | Original license/terms |
|---|---|---|---|
| AgentHarm | ai-safety-institute/AgentHarm (arXiv:2410.09024) | Imported historical benchmark artifact (`results/external_benchmark_agentharm_v1.json`); referenced scenarios | Dataset terms of the AgentHarm release; not relicensed |
| tau2-bench | sierra-research/tau2-bench at `363133a` | Source tasks and domain state for `data/routing_bench_v1/`, `data/routing_bench_v2/` and the `data/routing_bench_holdout/`, `_holdout_a/` and `_holdout_b/` tracks | MIT (upstream project's own license); not relicensed |
| AgentDojo | ethz-spylab/agentdojo at `089ed46` | Source episodes in `data/routing_bench_v1/agentdojo.jsonl` | MIT (upstream project's own license); not relicensed |
| Berkeley Function Calling Leaderboard (BFCL) | ShishirPatil/gorilla at `c15b2a1` (v3) and `6ea5797` (v4) | Sampled tasks in `data/routing_bench_bfcl*/` | Apache License 2.0 (upstream project's own license); not relicensed |
| ToolSandbox | apple/ToolSandbox | Episodes built locally for development; never committed | Apple license, not redistributable; nothing from it is in the repository |
| MultiNLI | Williams et al. 2018 | Evidence-router proxy benchmark inputs | OANC/MultiNLI dataset terms; not relicensed |
| BoolQ | Clark et al. 2019 | QA benchmark subset (n=377) | CC BY-SA 3.0; not relicensed |
| TruthfulQA | Lin et al. 2022 | QA benchmark subset (n=85) | Apache License 2.0 (upstream dataset's own license); not relicensed |
| ARC-Challenge / MMLU-Pro | AI2 / TIGER-Lab | Referenced benchmark materials | Respective dataset licenses; not relicensed |
| Open Policy Agent (OPA) | openpolicyagent.org | Pinned binary in CI; Rego adapter target | Apache License 2.0 (upstream project's own license); not bundled |
| TRACE v0.2 JSON Schema | agentrust-io/trace-spec `schema/trace-claim.json` at `4c7d6ec` | Vendored unchanged as `integrations/agentrust-trace/upstream/trace-claim.json` to validate the REMORA mapping offline | Community Specification License 1.0 (upstream project's own license); not relicensed |
| E6 producer fixture (demo receipts, manifest, bills, keys, cases) | VeritasActa/e6-fixture `v1.1.0` at `8d8fc50` | Vendored subset unchanged as `integrations/acta-e6/upstream/e6-fixture/` to run REMORA's E6 consumer offline | Apache License 2.0 (upstream project's own license, `LICENSE` vendored with it); not relicensed |
| Business Source License text | MariaDB Corporation Ab | License text in `LICENSE` / `LICENSES/BUSL-1.1.txt` | Used under MariaDB's permission subject to the Covenants of Licensor |
| Model outputs (Groq/Cloudflare-hosted Llama, Qwen, Mistral) | Respective providers | Stored oracle responses in committed result artifacts | Provider terms of service; review before commercial redistribution |

## Publications and specifications implemented

| Material | Source | Use in REMORA | Original terms |
|---|---|---|---|
| Jailbreak Rating Framework for Frontier Cyber Threats, Version 1.0 | Frontier Model Forum, 2026-11-05, https://www.frontiermodelforum.org/uploads/2026/11/PDF-FMF-Version-1.0-Cyber-Jailbreak-Framework.pdf | The rating method is implemented as independently written code in `remora/jailbreak/` and described in REMORA's own words in `docs/design/jailbreak-rated-model-posture-v1.md` (§12). Dimension, band and category names are used as identifiers for comparability. No copy, excerpt, table or figure of the document is included; the repository links to it | Copyright 2026, the Frontier Model Forum. All Rights Reserved. Website terms: informational, non-commercial or personal use; no modification or redistribution. Not relicensed. Use of the name implies no endorsement by the Frontier Model Forum or its members |

Rows referencing an upstream project's own license describe THAT
project's license; they do not make any part of REMORA available under
that license.

For any material added later, record it here before release: source,
included files, original terms, and how REMORA uses it.

No third-party material is relicensed under the REMORA Business Source
License unless the rights holder has expressly authorized that
relicensing.
