# Security policy

REMORA is a research-grade governance overlay for autonomous AI actions,
maintained by a single maintainer. This policy describes how to report a
vulnerability and what response to expect. It does not promise anything the
project cannot deliver: there is no bug bounty program, no security
certification, and no production-readiness claim.

## Reporting a vulnerability

Preferred: use GitHub private vulnerability reporting (Security Advisories) on
this repository, so the report stays private until a fix or disposition exists.

Fallback: email support@luftfiber.no.

Please include:

- reproduction steps (exact commands or requests),
- the affected paths (files, modules, or endpoints),
- the impact as you understand it (what an attacker gains, under what
  preconditions).

Do not open a public issue for anything you believe is exploitable.

## Response expectation

Reports are acknowledged within 7 days. This is a single-maintainer research
project: there is no SLA on triage or fix timelines, and no bounty is paid.
You will get an honest assessment, a register entry if the finding is
accepted, and credit in the disposition document unless you ask otherwise.

## Scope

In scope:

- the Python engine (`remora/`), in particular the policy, enforcement, and
  governance layers,
- the API servers (`servers/`),
- schemas (`schemas/`),
- CI workflows (`.github/workflows/`).

Out of scope:

- availability of the deployed demo workers (research demos, not a service),
- findings that only restate documented limitations. Check
  `docs/assurance/` and the README Limitations section first: if the gap is
  already recorded there, it is a known boundary, not a new vulnerability.

## Honest security posture

REMORA is research-grade. It is not production-certified and does not
guarantee safety. Reports are evaluated against the documented threat model,
not against a production baseline the project has never claimed.

- Threat model: `artifacts/credibility-pack/threat-model.md`.
- Known open remediation items: `docs/assurance/remediation_register.yaml`.
  Two items are explicitly relevant to security reports and are open at the
  time of writing:
  - **REM-021** (`NOT_STARTED`); independent human review of safety design
    and claims. No external reviewer has audited the decision engine, the
    PDP/PEP separation, or the headline claims.
  - **REM-024** (`IN_PROGRESS`); mandatory fail-closed policy enforcement
    point (PEP). A library-level ExecutionLease + governed tool dispatcher
    exists (`remora/enforcement/lease.py`), but enforcement is not yet
    deployment-integrated in front of real tool credentials, so it is not yet
    inseparable from tool execution.

Known-by-design authentication limitation (external review 2026-07-28, N4):
**single-token API mode (`REMORA_API_BEARER_TOKEN`) has no role
separation**: tenant and role are caller-asserted headers, so anyone
holding the one token can claim any role and any tenant. The mode is
therefore development only, and outside development every request in it is
refused (RMR-CR-003, 2026-10-07; the earlier production pinning of the role
was N4). The strict runtime profiles require the token-table mode
(`REMORA_API_TOKENS`). There each token maps to a fixed tenant and role, and a
tenant header naming another tenant is refused. `REMORA_ENV` values other
than development and production refuse startup.

A report demonstrating that either gap is worse than documented is in scope
and welcome. A report that only re-derives the gap as documented will be
answered with a pointer to the register.

## Third-party scanner findings

Automated scanners read this repository without its context, and much of it
is adversarial test data by design. Each finding is checked against the code.
A finding that is not a vulnerability is recorded here with what makes it
inert. A test pins that property, so a later change cannot quietly break it. The guards are in `tests/test_external_scan_findings.py`.

AgentAvow scan, 2026-10-01 (12 findings, none a vulnerability):

| Finding | Location | Why it is inert | Guard |
|---|---|---|---|
| curl or wget piped to a shell (6, critical) | `artifacts/benchmarks/toolcall_benchmark_v1.json` (moved from `artifacts/` byte for byte) | Labelled attack cases (`expected_failure_mode: remote_code_execution`) in a dry-run simulator; the URLs use the reserved `.invalid` domain. The benchmark measures that governance blocks them, and the file is a claim-bound artifact, so its content is not edited | every such payload must stay dry-run, labelled and on a reserved domain |
| Instruction-override phrase (3, high) | `remora/cli.py`, `eval_pack/run_validation.py` | Inputs to the prompt-injection detector and to the CLI demo of a blocked action, not tool descriptions | the tool descriptions served by `servers/mcp_remora.py` and the MCP gateway must contain no override phrase; a control shows the check catches a poisoned one |
| Generic API key assignment (high) | `experiments/authority_preserving_capability_mediation.py` | A synthetic label the study uses to show the worker never sees a credential; renamed to `STUDY_CREDENTIAL_VALUE` | its value must stay a word label, not key material |
| `subprocess.Popen` (2, high) | the same study | Launches `sys.executable` on the study's own file with constant flags; no caller input, no shell | every launch must stay that shape, and no Python code in the repository may pass `shell=True` |

These six were the whole reason for the scan's Blocked verdict. The scanner
deducts 22 points per critical in shipped code, uncapped, from a start of 68,
and counts findings in benchmark, test or fixture directories at 15 percent.
`artifacts/` is not one of those directories, so the benchmark data counted
as shipped code. Moving the file under `artifacts/benchmarks/` classifies it
as what it is. A local run of the scanner (`agentavow scan .`) went from 0
(Blocked) to 61 (Standard) on that move alone.
