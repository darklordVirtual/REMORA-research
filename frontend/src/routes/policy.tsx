import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader, SectionLabel } from "@/components/primitives";

export const Route = createFileRoute("/policy")({
  head: () => ({
    meta: [
      { title: "REMORA · Policy — nested governance layers" },
      {
        name: "description",
        content:
          "REMORA policy-as-code: nested governance layers, risk profiles, evidence ABAC and approval workflow rendered as inspectable cards.",
      },
    ],
  }),
  component: PolicyPage,
});

const LAYERS = [
  {
    name: "runtime_context",
    freq: "per_request",
    writable: true,
    retention: "short",
    risk: "low",
    boundary: "request_window",
    audit: false,
    examples: ["prompt", "current user input", "current tool result"],
  },
  {
    name: "session_memory",
    freq: "per_session",
    writable: true,
    retention: "short",
    risk: "medium",
    boundary: "session_scope",
    audit: true,
    examples: ["transient workflow state", "approval status", "active plan"],
  },
  {
    name: "case_memory",
    freq: "per_case",
    writable: false,
    retention: "medium",
    risk: "high",
    boundary: "reviewed_case_record",
    audit: true,
    examples: ["reviewed facts", "case-local decisions", "approved constraints"],
  },
  {
    name: "trust_memory",
    freq: "per_decision",
    writable: false,
    retention: "medium",
    risk: "medium",
    boundary: "evaluation_runtime",
    audit: true,
    examples: ["model failure history", "abstain rate", "drift telemetry"],
  },
  {
    name: "evidence_memory",
    freq: "per_retrieval",
    writable: false,
    retention: "medium",
    risk: "medium",
    boundary: "approved_evidence_connectors",
    audit: true,
    examples: ["source refs", "retrieval hashes", "freshness metadata"],
  },
];

const RISK_PROFILES = [
  {
    tier: "low",
    evidence: "optional",
    judge: "no",
    action: "allowed (allowlist)",
    approval: "no",
    outcomes: "ACCEPT · VERIFY · ABSTAIN",
  },
  {
    tier: "medium",
    evidence: "≥ 1 source",
    judge: "optional",
    action: "allowed (sandbox)",
    approval: "optional",
    outcomes: "ACCEPT · VERIFY · ABSTAIN · ESCALATE",
  },
  {
    tier: "high",
    evidence: "≥ 2 sources",
    judge: "required",
    action: "blocked",
    approval: "1 reviewer",
    outcomes: "ACCEPT · VERIFY · ABSTAIN · ESCALATE",
  },
  {
    tier: "critical",
    evidence: "≥ 2 sources + freshness",
    judge: "required",
    action: "blocked",
    approval: "two-person review",
    outcomes: "VERIFY · ABSTAIN · ESCALATE",
  },
];

const STARTER_REGO = `package remora.gate

default allow = false

allow {
  input.risk_tier == "low"
  input.action_type == "read"
  input.trust_score >= 0.7
}

escalate {
  input.action_type == "destructive_write"
  input.target_environment == "prod"
}`;

const STARTER_INPUT = JSON.stringify(
  { risk_tier: "low", action_type: "read", trust_score: 0.85, target_environment: "staging" },
  null,
  2,
);

function OPAInspector() {
  const [rego, setRego] = useState(STARTER_REGO);
  const [inputJson, setInputJson] = useState(STARTER_INPUT);
  const [result, setResult] = useState<string | null>(null);

  const evaluate = () => {
    try {
      const inp = JSON.parse(inputJson) as {
        risk_tier?: string;
        action_type?: string;
        trust_score?: number;
        target_environment?: string;
      };
      const lines: string[] = [];

      if (inp.action_type === "destructive_write" && inp.target_environment === "prod") {
        lines.push("escalate = true");
        lines.push("allow    = false");
        lines.push("");
        lines.push("→ ESCALATE");
      } else if (
        inp.risk_tier === "low" &&
        inp.action_type === "read" &&
        (inp.trust_score ?? 0) >= 0.7
      ) {
        lines.push("allow    = true");
        lines.push("escalate = false");
        lines.push("");
        lines.push("→ ACCEPT");
      } else if ((inp.trust_score ?? 0) >= 0.5) {
        lines.push("allow    = partial");
        lines.push("escalate = false");
        lines.push("");
        lines.push("→ VERIFY");
      } else {
        lines.push("allow    = false");
        lines.push("escalate = false");
        lines.push("");
        lines.push("→ ABSTAIN");
      }

      setResult(lines.join("\n"));
    } catch {
      setResult("JSON parse error — check input format");
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-6 space-y-4 mb-8">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-foreground">OPA Policy Inspector</h2>
        <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
          client-side simulation
        </span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            REGO Policy
          </label>
          <textarea
            className="w-full h-52 rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
            value={rego}
            onChange={(e) => setRego(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Input (JSON)
          </label>
          <textarea
            className="w-full h-36 rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs text-foreground resize-none focus:outline-none focus:ring-1 focus:ring-primary"
            value={inputJson}
            onChange={(e) => setInputJson(e.target.value)}
            spellCheck={false}
          />
          <button
            onClick={evaluate}
            className="w-full rounded-lg bg-primary text-primary-foreground py-2 text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            Evaluer Policy
          </button>
          {result && (
            <div className="rounded-lg border border-border bg-muted/60 p-3">
              <pre className="font-mono text-xs text-foreground whitespace-pre-wrap">{result}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PolicyPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <OPAInspector />
      <PageHeader
        eyebrow="REMORA · policy-as-code"
        title="Nested governance layers."
        lede="REMORA treats governance as data. Each information flow has its own update frequency, retention, writability and trust boundary. Policies compose into a versioned bundle whose hash is written to every audit row."
      />

      <section className="mt-12">
        <SectionLabel number="01">Risk profiles</SectionLabel>
        <div className="mt-6 overflow-x-auto border-y border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {["tier", "evidence", "judge", "tool action", "approval", "permitted outcomes"].map(
                  (c) => (
                    <th
                      key={c}
                      className="px-4 py-3 text-left font-mono text-[11px] uppercase tracking-[0.16em] text-muted-foreground font-normal"
                    >
                      {c}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {RISK_PROFILES.map((r) => (
                <tr key={r.tier} className="border-b border-border/60 last:border-0">
                  <td className="px-4 py-3 font-mono uppercase">{r.tier}</td>
                  <td className="px-4 py-3">{r.evidence}</td>
                  <td className="px-4 py-3">{r.judge}</td>
                  <td className="px-4 py-3">{r.action}</td>
                  <td className="px-4 py-3">{r.approval}</td>
                  <td className="px-4 py-3 font-mono text-[11px]">{r.outcomes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="02">Governance layers</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-2 lg:grid-cols-3">
          {LAYERS.map((l) => (
            <div key={l.name} className="bg-background p-5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs">{l.name}</span>
                <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  {l.freq}
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-[110px_1fr] gap-y-1 font-mono text-[11px]">
                <dt className="text-muted-foreground">writable</dt>
                <dd>{l.writable ? "agent" : "system"}</dd>
                <dt className="text-muted-foreground">retention</dt>
                <dd>{l.retention}</dd>
                <dt className="text-muted-foreground">risk</dt>
                <dd className="uppercase">{l.risk}</dd>
                <dt className="text-muted-foreground">boundary</dt>
                <dd>{l.boundary}</dd>
                <dt className="text-muted-foreground">audit</dt>
                <dd>{l.audit ? "required" : "not required"}</dd>
              </dl>
              <div className="mt-3 text-[11px] text-muted-foreground">{l.examples.join(" · ")}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="03">Sample policy bundle</SectionLabel>
        <pre className="mt-6 overflow-x-auto border border-border bg-muted p-5 font-mono text-[11px] leading-relaxed">
          {`version: policy@2026.05.0
default_fail_mode: ABSTAIN
risk_profile: high
domain: maintenance_planning
require_evidence: true
min_evidence_sources: 2
require_independent_judge: true
allow_tool_action: false
require_human_approval: true
approval_model: one_authorised_reviewer
audit:
  required_fields: [request_id, tenant, policy_version, evidence_refs, thermo]
  bundle_hash: sha256:7c2…a91
permitted_outcomes:
  - ACCEPT
  - VERIFY
  - ABSTAIN
  - ESCALATE`}
        </pre>
      </section>
    </div>
  );
}
