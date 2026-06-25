# Cybersecurity Triage Policy Cookbook

Cybersecurity agents should separate candidate findings from report-ready
findings. A finding becomes stronger when it has exact identifiers,
reachability, exploit-likelihood metadata, and independent corroboration.

| Scenario | Risk | Recommended outcome | Required evidence |
|----------|------|---------------------|-------------------|
| Exact CISA KEV CVE match in exposed asset | critical | ESCALATE | CVE, KEV, affected version, exposure |
| High EPSS exact CVE match | high | VERIFY or ESCALATE | CVE, EPSS, asset exposure |
| CWE-only static finding | medium | VERIFY | source-to-sink evidence |
| Placeholder secret in test fixture | low | VERIFY | production context check |
| Production credential exposure | critical | ESCALATE | path, credential class, rotation plan |
| Prompt injection against tool-using agent | high | ESCALATE | payload context, tool boundary |
| Unknown emerging weakness | high | VERIFY | reproduction plan, reviewer sign-off |
| Exploit payload request | critical | ABSTAIN or ESCALATE | safety review |

## Public safety boundary

Public REMORA evidence packs should contain advisory metadata, taxonomy,
severity, exploit-likelihood indicators, and remediation guidance. They should
not contain exploit payloads, weaponized proof-of-concept steps, private
customer findings, or proprietary scanner rules.

