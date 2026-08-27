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
| MultiNLI | Williams et al. 2018 | Evidence-router proxy benchmark inputs | OANC/MultiNLI dataset terms; not relicensed |
| BoolQ | Clark et al. 2019 | QA benchmark subset (n=377) | CC BY-SA 3.0; not relicensed |
| TruthfulQA | Lin et al. 2022 | QA benchmark subset (n=85) | Apache License 2.0 (upstream dataset's own license); not relicensed |
| ARC-Challenge / MMLU-Pro | AI2 / TIGER-Lab | Referenced benchmark materials | Respective dataset licenses; not relicensed |
| Open Policy Agent (OPA) | openpolicyagent.org | Pinned binary in CI; Rego adapter target | Apache License 2.0 (upstream project's own license); not bundled |
| Business Source License text | MariaDB Corporation Ab | License text in `LICENSE` / `LICENSES/BUSL-1.1.txt` | Used under MariaDB's permission subject to the Covenants of Licensor |
| Model outputs (Groq/Cloudflare-hosted Llama, Qwen, Mistral) | Respective providers | Stored oracle responses in committed result artifacts | Provider terms of service; review before commercial redistribution |

Rows referencing an upstream project's own license describe THAT
project's license; they do not make any part of REMORA available under
that license.

For any material added later, record it here before release: source,
included files, original terms, and how REMORA uses it.

No third-party material is relicensed under the REMORA Business Source
License unless the rights holder has expressly authorized that
relicensing.
