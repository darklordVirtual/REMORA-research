# Author: Stian Skogbrott
# License: Apache-2.0
"""Deterministic action-semantics extraction from natural-language action text.

Dependency-free, no LLM calls. A fixed table of compiled regex patterns maps
action text + tool metadata to conservative governance signals. When language
is ambiguous the extractor errs toward *higher* risk.

The output is advisory: it feeds misspecification / causal / generalization
inference and the strengthen-only enrichment merge. It never weakens
caller-supplied risk labels and never makes routing decisions itself.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from remora.governance_intelligence.types import RISK_TIER_RANK, ActionSemantics

# ---------------------------------------------------------------------------
# Pattern table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Pattern:
    name: str
    regex: re.Pattern[str]
    action_type: str | None = None
    domain: str | None = None
    tier: str | None = None          # minimum tier implied by this pattern
    priority: int = 0                # higher priority wins the action_type slot
    mutating: bool = False
    destructive: bool = False
    irreversible: bool = False
    external: bool = False
    credential: bool = False
    bulk: bool = False
    production: bool = False
    safety_critical: bool = False


def _p(name: str, pattern: str, **kwargs: Any) -> _Pattern:
    return _Pattern(name=name, regex=re.compile(pattern, re.IGNORECASE), **kwargs)


_PATTERNS: tuple[_Pattern, ...] = (
    # ── Destructive database / storage operations ───────────────────────────
    _p("sql_drop", r"\bdrop\s+(?:table|database|schema|index|column)\b",
       action_type="destructive_write", domain="database", tier="critical",
       priority=100, mutating=True, destructive=True, irreversible=True),
    _p("sql_truncate", r"\btruncate\s+(?:table\s+)?\w+",
       action_type="destructive_write", domain="database", tier="critical",
       priority=100, mutating=True, destructive=True, irreversible=True),
    _p("sql_delete", r"\bdelete\s+from\b",
       action_type="destructive_write", domain="database", tier="high",
       priority=90, mutating=True, destructive=True),
    _p("wipe", r"\b(?:wipe|erase|purge)\b",
       action_type="destructive_write", domain=None, tier="high",
       priority=85, mutating=True, destructive=True, irreversible=True),
    _p("rm_rf", r"\brm\s+-[a-z]*r[a-z]*f?\b|\brm\s+-[a-z]*f[a-z]*r\b",
       action_type="shell_execute", domain="shell", tier="critical",
       priority=95, mutating=True, destructive=True, irreversible=True),
    _p("disk_format", r"\b(?:format|mkfs|dd\s+if=)\b.{0,40}(?:disk|drive|/dev/|c:)|\bmkfs\b|\bdd\s+if=",
       action_type="destructive_write", domain="infrastructure", tier="critical",
       priority=95, mutating=True, destructive=True, irreversible=True),
    _p("delete_generic", r"\b(?:delete|remove|destroy)\b",
       action_type="destructive_write", domain=None, tier="high",
       priority=60, mutating=True, destructive=True),
    _p("cleanup_language", r"\bclean\s*up\b|\bprune\b|\bdeprovision\b",
       tier="medium", priority=30, mutating=True),

    # ── DNS / network / firewall ────────────────────────────────────────────
    _p("dns_record", r"\b(?:mx|cname|txt|ns|a{1,4}|spf|dkim|srv)\s+records?\b|\bdns\b|\bnameservers?\b",
       action_type="dns_change", domain="infrastructure", tier="high",
       priority=80, mutating=True),
    _p("firewall_rule", r"\bfirewall\b|\bsecurity\s+(?:rule|group)\b|\biptables\b|\bwaf\b|\b(?:open|close|allow|block)\s+ports?\b",
       action_type="firewall_change", domain="security", tier="high",
       priority=80, mutating=True),
    _p("disable_security", r"\bdisable\b.{0,30}\b(?:security|firewall|auth(?:entication)?|mfa|2fa|logging|audit|monitoring|alerts?|waf)\b",
       action_type="disable_security", domain="security", tier="critical",
       priority=110, mutating=True, destructive=True, irreversible=True),

    # ── Permissions / access control ────────────────────────────────────────
    _p("grant_access", r"\bgrant\b.{0,30}\b(?:access|admin|permission|privilege|role)\b|\bmake\b.{0,20}\badmin\b|\badd\s+user\b|\binvite\s+user\b",
       action_type="grant_permission", domain="security", tier="high",
       priority=75, mutating=True),
    _p("revoke_access", r"\brevoke\b.{0,30}\b(?:access|permission|privilege|role)\b|\bremove\s+user\b",
       action_type="revoke_permission", domain="security", tier="high",
       priority=75, mutating=True),
    _p("chmod_777", r"\bchmod\s+(?:-[a-z]+\s+)?0?777\b",
       action_type="shell_execute", domain="security", tier="critical",
       priority=105, mutating=True, credential=True),

    # ── Credentials / secrets ───────────────────────────────────────────────
    _p("secret_material", r"\b(?:api[_\s-]?keys?|secrets?|tokens?|passwords?|credentials?|private\s+keys?)\b",
       domain="security", tier="high", credential=True),
    _p("rotate_key", r"\brotate\b.{0,30}\b(?:api[_\s-]?keys?|keys?|secrets?|tokens?|credentials?)\b",
       action_type="config_change", domain="security", tier="high",
       priority=70, mutating=True, credential=True),
    _p("expose_secret", r"\b(?:print|echo|log|send|share|upload|post)\b.{0,40}\b(?:api[_\s-]?keys?|secrets?|tokens?|passwords?|private\s+keys?)\b",
       action_type="data_exfiltration", domain="security", tier="critical",
       priority=108, mutating=True, credential=True, external=True),

    # ── Financial ───────────────────────────────────────────────────────────
    _p("financial_transfer", r"\b(?:transfer|wire|payout|payment|refund|disburse)\b.{0,50}\b(?:funds?|money|nok|usd|eur|kr|\$|€)|\bsend\s+money\b|\bexecute\s+(?:a\s+)?(?:transfer|payment|payout)\b",
       action_type="financial_write", domain="financial", tier="critical",
       priority=100, mutating=True, irreversible=True, external=True),
    _p("financial_keyword", r"\b(?:payout|invoice\s+payment|bank\s+transfer)\b",
       action_type="financial_write", domain="financial", tier="high",
       priority=85, mutating=True, external=True),

    # ── External communication / publication ────────────────────────────────
    _p("send_email", r"\bsend\b.{0,60}\b(?:e-?mails?|messages?|newsletters?)\b|\be-?mail\b.{0,30}\bto\b",
       action_type="external_publish", domain="data", tier="medium",
       priority=55, mutating=True, external=True),
    _p("webhook_post", r"\bwebhooks?\b|\bpost\s+to\s+(?:https?://|external|third[- ]party)\b",
       action_type="webhook_trigger", domain="integration", tier="medium",
       priority=55, mutating=True, external=True),
    _p("publish_external", r"\b(?:publish|share|upload|export)\b.{0,50}\b(?:external|public|vendor|third[- ]party|internet)\b",
       action_type="external_publish", domain="data", tier="high",
       priority=65, mutating=True, external=True),
    _p("exfiltration_language", r"\bexfiltrat|\bsend\b.{0,60}\b(?:customer|user|patient|employee)\s+(?:data|records?|e-?mails?|details|information)\b.{0,40}\b(?:to|vendor|external)\b",
       action_type="data_exfiltration", domain="privacy", tier="critical",
       priority=108, mutating=True, external=True),

    # ── Shell / code execution ──────────────────────────────────────────────
    _p("shell_exec", r"\b(?:shell|bash|powershell|cmd\.exe|sudo)\b|\brun\s+command\b|\bexecute\s+(?:script|command)\b",
       action_type="shell_execute", domain="shell", tier="high",
       priority=70, mutating=True),

    # ── Deploy / infrastructure mutation ────────────────────────────────────
    _p("deploy", r"\bdeploy\b|\brollout\b|\brelease\s+to\b",
       action_type="prod_deploy", domain="infrastructure", tier="high",
       priority=70, mutating=True),
    _p("restart_scale", r"\b(?:restart|reboot|scale\s+(?:up|down)|shut\s*down|terminate)\b.{0,40}\b(?:service|server|instance|pod|cluster|node)s?\b",
       action_type="config_change", domain="infrastructure", tier="high",
       priority=68, mutating=True),

    # ── Bulk scope ──────────────────────────────────────────────────────────
    _p("bulk_scope", r"\ball\b|\bevery\b|\bentire\b|\bbulk\b|\bmass\b|\b\*\b|\bwildcard\b",
       bulk=True),

    # ── Production signal ───────────────────────────────────────────────────
    _p("production_signal", r"\bprod(?:uction)?\b|\blive\s+(?:site|system|environment|database|server)\b|\bcustomer[- ]facing\b",
       production=True),

    # ── Irreversibility language ────────────────────────────────────────────
    _p("irreversible_language", r"\birreversibl|\bpermanent(?:ly)?\b|\bcannot\s+be\s+undone\b|\bforce[- ]push\b|\bhard\s+reset\b|\bno\s+backup\b",
       tier="high", irreversible=True),

    # ── Safety-critical / industrial ────────────────────────────────────────
    _p("industrial_control", r"\bscada\b|\bplc\b|\bvalve\b|\breactor\b|\bturbine\b|\bpipeline\s+pressure\b|\bsetpoint\b|\bactuator\b",
       domain="industrial", tier="critical", safety_critical=True),
    _p("medical_action", r"\b(?:dosage|dose|prescription|infusion|ventilator)\b",
       domain="medical", tier="critical", safety_critical=True),

    # ── Read-only verbs (only honoured when nothing risky matched) ──────────
    _p("read_only", r"^\s*(?:read|list|show|view|get|fetch|query|inspect|describe|preview|summari[sz]e|check)\b",
       action_type="read", tier="low", priority=10),
)

# Coercion / blackmail patterns — surfaced separately because they map to the
# engine's hard-ESCALATE flags rather than to action typing.
_COERCION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("coercion_unless", re.compile(r"\bunless\s+you\b|\bor\s+else\b|\bif\s+you\s+(?:don'?t|do\s+not|refuse)\b.{0,60}\bwill\b", re.IGNORECASE)),
    ("coercion_threat", re.compile(r"\bthreat(?:en(?:ing)?)?\b|\bforce\s+(?:him|her|them|the\s+\w+)\s+to\b", re.IGNORECASE)),
)

_BLACKMAIL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("blackmail_keyword", re.compile(r"\bblackmail|\bextort", re.IGNORECASE)),
    ("blackmail_leak_threat", re.compile(r"\b(?:leak|release|expose|publish)\b.{0,50}\b(?:private|personal|compromising|embarrassing|intimate)\b", re.IGNORECASE)),
)

# Tool-argument keys that signal hidden force/destructive side effects.
DANGEROUS_ARGUMENT_KEYS: frozenset[str] = frozenset({
    "force", "recursive", "cascade", "hard", "all", "purge", "no_backup",
    "skip_confirmation", "yes", "wildcard", "drop_existing", "overwrite",
})


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _corpus(
    proposed_action: str | None,
    tool_name: str | None,
    tool_arguments: dict[str, Any] | None,
    question: str | None,
) -> str:
    parts: list[str] = []
    for part in (question, proposed_action):
        if part:
            parts.append(str(part))
    if tool_name:
        # Tool names use snake/kebab case ("delete_account"); split so word
        # patterns ( \bdelete\b ) can see the verbs.
        parts.append(re.sub(r"[_\-.]+", " ", str(tool_name)))
    if tool_arguments:
        try:
            parts.append(json.dumps(tool_arguments, default=str, sort_keys=True))
        except (TypeError, ValueError):
            parts.append(str(tool_arguments))
    return " \n ".join(parts)


def detect_coercion(text: str) -> tuple[str, ...]:
    """Return names of coercion patterns matched in *text* (deterministic)."""
    return tuple(name for name, rx in _COERCION_PATTERNS if rx.search(text))


def detect_blackmail(text: str) -> tuple[str, ...]:
    """Return names of blackmail/extortion patterns matched in *text*."""
    return tuple(name for name, rx in _BLACKMAIL_PATTERNS if rx.search(text))


def _max_tier(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if RISK_TIER_RANK.get(a, -1) >= RISK_TIER_RANK.get(b, -1) else b


def extract_action_semantics(
    proposed_action: str | None = None,
    *,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
    question: str | None = None,
) -> ActionSemantics:
    """Extract conservative, deterministic semantics from action metadata.

    Examples
    --------
    >>> s = extract_action_semantics("DROP TABLE users")
    >>> (s.inferred_action_type, s.inferred_risk_tier, s.destructive)
    ('destructive_write', 'critical', True)
    >>> s = extract_action_semantics("list open tickets")
    >>> (s.inferred_action_type, s.inferred_risk_tier)
    ('read', 'low')
    """
    text = _corpus(proposed_action, tool_name, tool_arguments, question)
    matched = [p for p in _PATTERNS if p.regex.search(text)]

    risky = [p for p in matched if p.name != "read_only"
             and (p.mutating or p.destructive or p.external or p.credential
                  or p.safety_critical or p.bulk or p.production
                  or p.irreversible)]
    read_match = any(p.name == "read_only" for p in matched)

    mutating = any(p.mutating for p in matched)
    destructive = any(p.destructive for p in matched)
    irreversible = any(p.irreversible for p in matched)
    external = any(p.external for p in matched)
    credential = any(p.credential for p in matched)
    bulk = any(p.bulk for p in matched)
    production = any(p.production for p in matched)
    safety_critical = any(p.safety_critical for p in matched)

    # Action type: highest-priority typed pattern wins (ties broken by name for
    # determinism). Read-only is only honoured when no risky pattern matched.
    typed = sorted(
        (p for p in matched if p.action_type is not None),
        key=lambda p: (-p.priority, p.name),
    )
    if read_match and not mutating and not risky:
        inferred_action = "read"
    elif typed:
        non_read = [p for p in typed if p.action_type != "read"]
        inferred_action = (non_read[0] if non_read else typed[0]).action_type or "unknown"
    else:
        inferred_action = "unknown"

    # Domain: from the same winning pattern, else first matched pattern with a domain.
    inferred_domain: str | None = None
    for p in typed:
        if p.action_type == inferred_action and p.domain:
            inferred_domain = p.domain
            break
    if inferred_domain is None:
        for p in matched:
            if p.domain:
                inferred_domain = p.domain
                break

    # Tier: max over matched patterns, plus conservative combination rules.
    tier: str | None = None
    for p in matched:
        tier = _max_tier(tier, p.tier)
    if bulk and (mutating or external):
        tier = _max_tier(tier, "high")
    if production and destructive:
        tier = _max_tier(tier, "critical")
    if credential and mutating:
        tier = _max_tier(tier, "high")
    if inferred_action == "read" and not risky:
        tier = "low"

    # Deterministic confidence: strong signals are confident; ambiguity is not.
    if inferred_action == "read" and not risky:
        confidence = 0.90
    elif not matched:
        confidence = 0.30
    elif any(p.priority >= 90 for p in matched):
        confidence = 0.85
    elif typed:
        confidence = 0.60
    else:
        confidence = 0.40

    names = tuple(sorted(p.name for p in matched))
    coercion = detect_coercion(text)
    blackmail = detect_blackmail(text)

    explanation = (
        f"matched {len(names)} pattern(s): {', '.join(names)}"
        if names else "no semantic patterns matched; action semantics unknown"
    )

    return ActionSemantics(
        inferred_action_type=inferred_action,
        inferred_domain=inferred_domain,
        inferred_risk_tier=tier,
        mutating=mutating,
        destructive=destructive,
        irreversible=irreversible,
        external_side_effect=external,
        credential_or_secret_risk=credential,
        bulk_scope=bulk,
        production_signal=production,
        confidence=confidence,
        matched_patterns=names + coercion + blackmail,
        explanation=explanation,
        coercion_signal=bool(coercion),
        blackmail_signal=bool(blackmail),
        safety_critical=safety_critical,
    )
