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
| `whatif NAME` | What would have to change for this call to reach ACCEPT (or, with `--target verify`, to reach a person). Proves by enumeration whether model signals alone, or the agent alone, can lift it. `--log` runs it over a shadow action log. |
| `replay LOG.jsonl` | Shadow-Mode counterfactual batch replay of an action log. |
| `serve` | Launch the governance REST API (needs the `api` extra). |
| `provenance` | Policy bundle hash + per-file SHA-256 manifest + version. |
| `verify` | Formal safety invariant verification (CI-friendly with `--json`). |
| `maturity` | Module stability maturity report. |
| `init-review` | Generate a complete strict-profile configuration under `.remora/`: generated keys, a signed ToolSpec bundle for a demo tool, a registry module, an intent source, durable-state path, and one env file per custody half. Automates the ceremony; removes no invariant. |
| `effect-verify` | Read back an external object over HTTP and verify a declared delta (property G). Exit 0 only for `EFFECT_VERIFIED`; mismatch 40, unobservable 41, verifier failed 42. |
| `doctor` | Environment self-check: what works, what's missing, how to fix it (`--json` for CI). |
| `sign-limits POLICY --out FILE` | Validate a `remora-cumulative-limits/v1` policy against the loader and Ed25519-sign it to a `limits.json` envelope. `--new-key` prints a fresh signing seed and its public key. The seed comes from `REMORA_LIMITS_SIGNING_SEED`; run it where the key is kept, never on the REMORA host. |
| `build-toolspec BUNDLE --out FILE` | Author a signed ToolSpec bundle from the installed package. Each spec names its callable as `module:function` (`--module-path DIR` adds an import directory) and the command measures it the way registration does, or declares `callable_digest` itself. The description digest is computed, the bundle is Ed25519-signed with the seed in `REMORA_TOOLSPEC_SIGNING_SEED`, and the result is loaded with the runtime's own strict loader before anything is written, so a bundle REMORA would refuse is never produced. Prints the public key and the pinned digest for `REMORA_TOOLSPEC_VERIFY_KEYS` and `REMORA_TOOLSPEC_PINNED_DIGEST` as JSON. `--signed-at` fixes the recorded signing time for a reproducible file (also on `sign-limits`); `--new-key` prints a fresh seed and public key. Run it where the key is kept, never on the REMORA host. |
| `export-contract-files DIR` | Write the contract files an external host pins to, from the installed package: the SDK public-API snapshot (`public_api_v1.json`), the OpenAPI document (`openapi.json`) and the ToolSpec schemas. |

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

Explicit flags always win. Inference is a CLI convenience only; it never
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
| `--registry PATH` | Tool registry JSON in the `REMORA_TOOL_METADATA_FILE` format. Only labels from it can reach ACCEPT; a tool it does not name fails closed. |
| `--live` | Real multi-oracle consensus instead of stand-ins (see below). |
| `--json` | Machine-readable output: `decision`, `trace`, `inferred`, `label_source`, `label_cap`. |
| `--envelope` | Also print/emit the full auditable DecisionEnvelope. |
| `--envelope-out PATH` | Write the DecisionEnvelope JSON to PATH (audit artifact). |
| `--exit-code` | Map the verdict to the exit code (below). |

### Where the labels come from (PRF-040)

`--risk` and `--action-type`, and anything inferred from the name, are
caller labels. A call labelled by its caller can only lower the verdict: if
the engine reaches ACCEPT, `assess`, `explain` and `whatif` report VERIFY
with the reason `caller_labels_untrusted`. To let a call reach ACCEPT, pass
`--registry FILE`:

```json
{"version": 1, "tools": {"read_file": {"risk_tier": "low", "domain": "files", "action_type": "read"}}}
```

With a registry, `--risk` may raise the tier and an `--action-type` that
disagrees with the registry caps ACCEPT (`registry_label_conflict`). A tool
the registry does not name is assessed as critical/unknown
(`label_source: unregistered`). The `try` presets carry labels fixed in
REMORA's own demo registry, so preset 1 still shows ACCEPT; a custom call
typed into the menu does not.

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
routing; no network, no keys. `--live` runs the same tool call through real
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
  Ollama. Override with `REMORA_ORACLE_BACKEND`. `mock` is refused; live
  mode never silently fakes a real run.
- Live calls cost real API credits and take seconds, not milliseconds.
- Hard guards keep absolute priority: live consensus can inform, never
  override, a deterministic block.

## Something not working? `remora doctor`

```bash
python -m remora doctor
```

Checks Python version, package health (the engine must escalate a known
hard-block case), policy provenance, installed extras, repo checkout, and
which live backends are available; each failing line comes with the exact
command that fixes it. Hard failures exit 1 (CI-friendly with `--json`).
Env-var **names** may be shown; key **values** never are.

## The same thing as a library — three lines

The CLI's deterministic assessment is `remora.assess_tool_call`, importable
directly (the CLI delegates to it, so behavior is identical):

```python
from remora import assess_tool_call

REGISTRY = {"drop_database": {"risk_tier": "critical",
                              "action_type": "destructive_write"}}
a = assess_tool_call("drop_database", {"db": "prod-main"},
                     registry=REGISTRY)            # YOUR tool registry
if a.should_execute:              # ACCEPT on registry labels only
    run_tool(...)
audit_log.write(a.envelope.to_dict())   # the canonical DecisionEnvelope
```

`a.action`, `a.decision`, `a.trace` and `a.inferred` carry the verdict, full
decision report, rule-by-rule trace, and what name inference filled in.
`a.label_source` says where the labels came from (`registry`, `caller`,
`inferred`, `unregistered` or `none`) and `a.label_cap` names the reason when
an ACCEPT was lowered to VERIFY. `remora.assess.load_tool_registry(path)`
reads a `REMORA_TOOL_METADATA_FILE`-format file into a registry.

Advisory, not enforcement. `assess_tool_call` judges the metadata it is
given, and the registry binds labels to a tool name, not to the callable that
will run. Labels passed as `risk_tier=`/`action_type=` or filled by
`infer=True` cannot produce ACCEPT and `should_execute` stays False for them
(PRF-040, a breaking change on 2026-10-18). `trust_score`/`phase` are still
caller-supplied stand-ins; with registry labels they can lift a low-risk read
to ACCEPT. Argument content is not inspected (PRF-041). The
enforcement-grade path is the `/v1/execution` API, where metadata is
resolved server-side and dispatch runs through the `GovernedToolDispatcher`
under an `ExecutionLease`. Worked registry-based loop:
[examples/agent_gate.py](../examples/agent_gate.py); worked framework examples
(OpenAI function-calling, LangGraph, CrewAI, AutoGen) live in
[examples/](../examples/) as standalone scripts. (`remora.integrations`
currently ships only the GO-STAR bridge.)

## `whatif` — what would it take?

`explain` says which rule fired. `whatif` answers the question that follows:
what would have to change for the same call to be ACCEPTed? It searches every
combination of a fixed catalogue of levers (each one an observation field set
to the value the engine treats as most favourable) against the real engine,
and reports five things.

```bash
python -m remora whatif drop_database                 # a critical production write
python -m remora whatif read_file --target-env staging --target verify
python -m remora whatif wire_transfer --execution-profile --json
python -m remora whatif --log artifacts/demo/shadow_mode_sample_agent_action_log.jsonl
python -m remora whatif --list-levers                 # what the search may change
```

1. Whether model signals alone (trust, consensus phase, evidence confidence,
   oracle quorum, temperature) reach the target. For `drop_database` they do
   not, and the report says so after trying every combination.
2. Whether the agent alone reaches it: model signals plus every property of
   the proposal the agent controls (target environment, schema, payload),
   with nothing the deployment declares. This is the statement a security
   reviewer wants, because a persuasive agent controls both.
3. The smallest change sets that do reach the target, each change tagged with
   who can bring it about: `deployment_fact` (tool registry, Signed ToolSpec,
   intent source, system of record), `proposal` (the call itself) or
   `model_signal`. For `drop_database` every path re-declares the tool as low
   or medium risk and read-only, which is to say it has to be a different
   tool.
4. What each single lever does on its own, so inert changes are shown as
   inert.
5. The hard guard currently blocking the call, if any. A hard guard is the
   one class of block no softer signal can pass.

| Option | Meaning |
|--------|---------|
| `--target accept` / `verify` | The verdict to reach. `verify` asks what would put an ABSTAINed call in front of a person. |
| `--depth N` | Most levers combined in one change set (4 for a call, 2 for `--log`). |
| `--execution-profile` | Analyse the execution-profile engine, where no probabilistic signal can produce ACCEPT directly. |
| `--log JSONL` | Boundary report over a shadow-mode action log: of the blocked actions, how many model signals, the agent alone, or only a deployment fact could lift. A block liftable by model signals alone is listed record by record as a policy finding. |
| `--list-levers` | Print the lever catalogue and exit. |
| `--no-prune` | Disable hard-guard pruning. The answer is identical; only the evaluation count changes. |
| `--json` | Machine-readable report: `what_if.confidence_can_lift`, `what_if.agent_alone_can_reach`, `what_if.minimal_paths`, `what_if.single_lever_effects`, `what_if.hard_guard`, search bounds. |

The report is an analysis of the policy, not a grant. It names facts; the
only way to obtain the verdict is to establish them and assess again. The
search bounds are printed with the result, so "no path found" is never
mistaken for "no path exists" when the budget ran out. Two devices keep the
search cheap without changing its answer. A memo means a combination decided
in a sub-space search is not decided again. Hard-guard pruning skips
combinations that leave a firing guard's fields untouched. The test suite
asserts pruned and unpruned searches return identical paths.

Library form: `remora.what_if_tool_call(...)` returns the assessment and the
report; `remora.policy.whatif.what_if(obs, engine)` analyses any observation
under any configured engine; `remora.shadow.boundary.boundary_of_action_log`
is the log form. The five `try` presets and the sample shadow log are
analysed in [artifacts/demo/whatif_presets_v1.json](../artifacts/demo/whatif_presets_v1.json)
and [artifacts/demo/whatif_boundary_sample_v1.json](../artifacts/demo/whatif_boundary_sample_v1.json),
regenerated by `python scripts/generate_whatif_presets.py`.

`remora.causal` answers a neighbouring question with hand-declared concept
interventions; `whatif` searches raw observation fields automatically and
includes the non-actionable signals on purpose, to show that they cannot
carry a call past the deployment's declarations.

## `replay` — persist and prove a shadow-mode trail

`replay` re-decides a historical action log and can persist every resulting
`DecisionEnvelope` so the run is reviewable afterwards, not just summarised.

```bash
python -m remora replay log.jsonl --out-dir out/            # envelopes + report + audit JSONL
python -m remora replay log.jsonl --out-dir out/ --verify   # reload from disk, recheck the hash chain
python -m remora replay log.jsonl --store-db shadow.db      # also into a durable control-plane store
```

| Flag | Effect |
|---|---|
| `--out-dir DIR` | Write `decision_envelopes.jsonl`, `governance_delta_report.json`, `replay_audit.jsonl` |
| `--store-db PATH` | Persist each envelope to a SQLite control-plane store, queryable by `request_id` |
| `--store-tenant ID` | Tenant for `--store-db` (default `shadow`, keeping counterfactuals out of live traffic) |
| `--verify` | Reload the written JSONL and recompute the chain; exits non-zero and names every break |

Without `--out-dir` or `--store-db` nothing is written: the report is printed
and the envelopes are gone when the process exits. That is fine for a quick
look and useless as evidence.

To re-verify a stored trail later, or to check one produced by someone else:

```bash
python scripts/verify_envelope_chain.py --envelopes out/decision_envelopes.jsonl
python scripts/verify_envelope_chain.py --store-db shadow.db --tenant shadow
make shadow-audit-smoke     # replay the bundled sample, persist it, verify both forms
```

Verification reports the number of records checked as well as the verdict: an
empty trail passes trivially and proves nothing about what was decided.

## Output conventions

- Colour is TTY-gated: piped output and CI logs are plain text. Force off
  with `--no-color` or the `NO_COLOR` env var.
- `--json` output goes to stdout only; confirmations and errors go to stderr,
  so pipelines stay clean.
- Unicode punctuation is down-converted on narrow consoles (cp1252-safe).

## See also

- [README, Run it](../README.md#run-it): install and first run
- [docs/07-api-reference.md](07-api-reference.md): REST API (`remora serve`)
- [docs/03-experiments.md](03-experiments.md): how the evidence was produced
- `python -m remora --help` / `python -m remora <command> --help`
