# REMORA CLI reference

One command surface for the whole governance stack: send a tool call, get an
auditable `ACCEPT / VERIFY / ABSTAIN / ESCALATE`, inspect why, replay a log,
fingerprint the policy, or serve the REST API. Everything runs offline with no
API keys unless you explicitly opt into `--live`.

```bash
python -m pip install -e .    # from the repo root (REMORA is not on PyPI)
python -m remora try          # start here
```

`remora <command>` works too when your Python scripts directory is on `PATH`;
`python -m remora` always works.

## The 30-second tour

```bash
python -m remora try            # interactive: pick a preset, watch REMORA decide
python -m remora try 3          # one preset, no menu (drop production DB -> ESCALATE)
python -m remora demo           # eight-scenario governed-agent walkthrough
python -m remora assess drop_database        # zero flags: risk/type inferred from the name
```

## Commands

| Command | What it does |
|---------|--------------|
| `try` | Interactive menu: send a tool call, get a verdict. `try N` runs preset N and exits. |
| `demo` | Eight-scenario governance walkthrough (offline; needs a repo checkout). |
| `assess NAME` | Assess one tool call. Scriptable: `--json`, `--exit-code`, `--envelope-out`. |
| `explain NAME` | Every policy rule in order — triggered or not — for one tool call. |
| `replay LOG.jsonl` | Shadow-Mode counterfactual batch replay of an action log. |
| `serve` | Launch the governance REST API (needs the `api` extra). |
| `provenance` | Policy bundle hash + per-file SHA-256 manifest + version. |
| `verify` | Formal safety invariant verification (CI-friendly with `--json`). |
| `maturity` | Module stability maturity report. |

Mistyped a command? The CLI suggests the closest one (`remora asses` →
`did you mean 'assess'?`).

## Minimal parameters by design

You only ever need the tool name. When `--risk` / `--action-type` are not
given, the CLI infers stand-in values from well-known name patterns and marks
them `(inferred)` in the output (and under `"inferred"` in `--json`):

| Name has a word starting with | Inferred action type | Inferred risk |
|---|---|---|
| drop, delete, remove, truncate, destroy, wipe, purge | `destructive_write` | `critical` |
| disable, revoke, unlock, mfa, firewall, permission | `security_change` | `critical` |
| wire, transfer, payment, payout, refund, charge | `financial_transaction` | `high` |
| deploy, release, rollout, restart, scale, migrate | `deploy` | `medium` |
| send, publish, notify, write, update, create, insert, upload | `write` | `medium` |
| read, get, list, fetch, query, search, view, describe | `read` | `low` |

Explicit flags always win. Inference is a CLI convenience only — it never
reaches the engine as policy; anything left unset is handled fail-closed by
the engine itself (unknown risk routes to VERIFY, never ACCEPT).

```bash
python -m remora assess drop_database          # ESCALATE (inferred critical/destructive_write)
python -m remora assess read_file              # inferred read/low
python -m remora assess drop_database --risk low   # your flag wins (engine still guards)
```

## `assess` — the scriptable core

```bash
python -m remora assess NAME [--arg KEY=VALUE ...] [options]
```

| Option | Meaning |
|--------|---------|
| `--arg KEY=VALUE` | Tool argument (repeatable; values JSON-decoded). Mutually exclusive with `--arguments-json`. |
| `--arguments-json` | Full arguments as one JSON object string. |
| `--risk` | `low` / `medium` / `high` / `critical` (else inferred / fail-closed). |
| `--action-type` | e.g. `read` / `deploy` / `destructive_write` (else inferred). |
| `--target-env` | Target environment (default `prod`). |
| `--trust`, `--phase` | Stand-in consensus signals (trust must be 0..1). |
| `--live` | Real multi-oracle consensus instead of stand-ins (see below). |
| `--json` | Machine-readable output: `decision`, `trace`, `inferred`. |
| `--envelope` | Also print/emit the full auditable DecisionEnvelope. |
| `--envelope-out PATH` | Write the DecisionEnvelope JSON to PATH (audit artifact). |
| `--exit-code` | Map the verdict to the exit code (below). |

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (with `--exit-code`: verdict was ACCEPT) |
| 2 | Usage error (bad arguments, missing input) — clean message, never a traceback |
| 10 / 20 / 30 | With `--exit-code`: VERIFY / ABSTAIN / ESCALATE |

CI gate in one line:

```bash
python -m remora assess "$TOOL" --arguments-json "$ARGS" --exit-code --envelope-out audit/env.json \
  || echo "blocked with exit $?"
```

## Live mode: test a real run

By default `assess` is deterministic: hard blocks, admission firewall, risk
routing — no network, no keys. `--live` runs the same tool call through real
multi-oracle consensus (the machinery behind the REST API's `/v1/assess`):

```bash
export GROQ_API_KEY=gsk_...        # or GEMINI_API_KEY=AIza..., or run local Ollama
python -m remora assess drop_database --live
```

- Keys are read **from the environment only** and are never printed, logged,
  or stored. On an interactive terminal with no key set, the CLI offers a
  hidden prompt (`getpass`) and keeps the key in process memory only.
- Backend is auto-detected from what is available: `GROQ_API_KEY` → Groq
  swarm; `GROQ_API_KEY` + `OPENROUTER_API_KEY` → the cross-family
  "recommended" swarm; `GEMINI_API_KEY` → Gemini; a running local Ollama →
  Ollama. Override with `REMORA_ORACLE_BACKEND`. `mock` is refused — live
  mode never silently fakes a real run.
- Live calls cost real API credits and take seconds, not milliseconds.
- Hard guards keep absolute priority: live consensus can inform, never
  override, a deterministic block.

## Output conventions

- Colour is TTY-gated: piped output and CI logs are plain text. Force off
  with `--no-color` or the `NO_COLOR` env var.
- `--json` output goes to stdout only; confirmations and errors go to stderr,
  so pipelines stay clean.
- Unicode punctuation is down-converted on narrow consoles (cp1252-safe).

## See also

- [README Quickstart](../README.md#quickstart) — install and first run
- [docs/07-api-reference.md](07-api-reference.md) — REST API (`remora serve`)
- [docs/03-experiments.md](03-experiments.md) — how the evidence was produced
- `python -m remora --help` / `python -m remora <command> --help`
