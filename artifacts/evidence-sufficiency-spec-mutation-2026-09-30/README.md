# Evidence-sufficiency specification mutation: raw report (2026-09-30)

The full report behind section 13.6 of `docs/design/evidence-sufficiency-v1.3.md` and NEGATIVE_RESULTS.md §68.

| Field | Value |
|---|---|
| Pre-registration | `37b1aac`, pushed 2026-09-30T20:08:58+02:00, before any mutant was scored |
| Catalogue sha256 | `2fbf983a5b29f7f6c2b4bba8319fd8c8d7a59105651f38e11b4e6b3d8c5bd5a8` (446 first-order, 300 second-order, seed 20261001) |
| Subject | `conformance/evidence-sufficiency-v1.3/model.json`, sha256 `861e5dc80ff1983e2b3a640ad0f20b340fb0157c6ecfc6df259d1c2083dba201` |
| Command | `python scripts/spec_mutation_evidence_sufficiency.py --json spec-mutation.json` |
| Environment | Windows 11, CPython 3.14; `--workers 1` gives the same report byte for byte |
| `spec-mutation.json.gz` | sha256 `e4e012bbd2a0f0e36bac0f778594e8ac8e52177059678abc36e866ef06934d8e` |

Each row of the report names one mutant: its operator, the premises its edit touches, whether it is equivalent on the value-class domain, and a witness where it is not.
It also carries the authored cases that kill it on rows 1 and 2, and the runner checks that kill it on row 3.

| Set | Mutants | Equivalent | Live | Row 1 | Row 2 | Row 3 |
|---|---:|---:|---:|---:|---:|---:|
| first order | 446 | 54 | 392 | 380 | 356 | 392 |
| second order | 300 | 2 | 298 | 298 | 294 | 298 |

The pre-registered criterion S-2 is not met: twelve live first-order mutants survive row 1.
All twelve add a premise of one `admission_present` arm to a guard of the other.
`tests/test_evidence_sufficiency_spec_mutation.py` pins this report to the baseline and to the published counts.
