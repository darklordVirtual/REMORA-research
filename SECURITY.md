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
  - **REM-021** (`NOT_STARTED`) — independent human review of safety design
    and claims. No external reviewer has audited the decision engine, the
    PDP/PEP separation, or the headline claims.
  - **REM-024** (`IN_PROGRESS`) — mandatory fail-closed policy enforcement
    point (PEP). A library-level ExecutionLease + governed tool dispatcher
    exists (`remora/enforcement/lease.py`), but enforcement is not yet
    deployment-integrated in front of real tool credentials, so it is not yet
    inseparable from tool execution.

A report demonstrating that either gap is worse than documented is in scope
and welcome. A report that only re-derives the gap as documented will be
answered with a pointer to the register.
