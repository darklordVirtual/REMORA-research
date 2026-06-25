import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { PageHeader, SectionLabel, DecisionChip } from "@/components/primitives";
import { buildApprovals, type ApprovalCase } from "@/lib/remora-sim";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/approvals")({
  head: () => ({
    meta: [
      { title: "REMORA · Approvals — human-on-the-loop queue" },
      {
        name: "description",
        content:
          "Escalated REMORA cases awaiting human review. Reviewer packet, separation-of-duties, approval guardrails.",
      },
    ],
  }),
  component: ApprovalsPage,
});

type Decision = "pending" | "approved" | "rejected" | "needs_more_evidence";

function ApprovalsPage() {
  const [cases] = useState<ApprovalCase[]>(() => buildApprovals());
  const [active, setActive] = useState<ApprovalCase>(cases[0]);
  const [state, setState] = useState<Record<string, Decision>>(() =>
    Object.fromEntries(cases.map((c) => [c.id, "pending" as Decision])),
  );
  const [reason, setReason] = useState("");

  function decide(id: string, d: Decision) {
    setState((s) => ({ ...s, [id]: d }));
  }

  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="REMORA · human approval"
        title="Approval queue."
        lede="REMORA never converts an ESCALATE into an action without an authorised reviewer. Every case carries the full decision trace, evidence, model disagreement, and policy version."
      />

      <section className="mt-12 grid gap-10 lg:grid-cols-[320px_1fr]">
        <div>
          <SectionLabel number="01">Open cases</SectionLabel>
          <ul className="mt-6 divide-y divide-border border-y border-border">
            {cases.map((c) => {
              const sla = state[c.id];
              return (
                <li key={c.id}>
                  <button
                    onClick={() => setActive(c)}
                    className={cn(
                      "w-full text-left p-4 transition-colors",
                      active.id === c.id ? "bg-muted" : "hover:bg-muted/50",
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs">{c.id}</span>
                      <span
                        className={cn(
                          "font-mono text-[10px] uppercase tracking-widest",
                          sla === "approved"
                            ? "text-state-accept"
                            : sla === "rejected"
                              ? "text-state-escalate"
                              : sla === "needs_more_evidence"
                                ? "text-state-verify"
                                : "text-muted-foreground",
                        )}
                      >
                        {sla.replace("_", " ")}
                      </span>
                    </div>
                    <div className="mt-1 text-sm font-medium truncate">{c.query}</div>
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                      {c.domain} · {c.risk} · {c.opened}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div>
          <SectionLabel number="02">Reviewer packet</SectionLabel>
          <div className="mt-6 border border-foreground p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="font-mono text-xs">{active.id}</div>
              <DecisionChip state={active.verdict} />
            </div>
            <h2 className="mt-4 font-serif text-2xl leading-snug tracking-tight">{active.query}</h2>
            <dl className="mt-6 grid grid-cols-[140px_1fr] gap-y-2 font-mono text-[11px]">
              <Row k="Requester" v={active.requester} />
              <Row k="Approver group" v={active.approver_group} />
              <Row k="Risk profile" v={active.risk.toUpperCase()} />
              <Row k="Domain" v={active.domain} />
              <Row k="Trust score" v={`${(active.trust * 100).toFixed(0)}/100`} />
              <Row k="Triggered rules" v="require_evidence · require_judge · require_approval" />
              <Row k="Policy version" v="policy@2026.05.0" />
              <Row k="Reason" v={active.reason} />
              <Row k="SLA" v={`${active.sla_minutes} min from open`} />
              <Row k="Bundle hash" v="sha256:7c2…a91" />
            </dl>

            <div className="mt-6 border-t border-border pt-5">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                Reason code
              </div>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. evidence_sufficient, unsafe_action, needs_procedure_ref"
                className="mt-2 w-full border border-border bg-background p-3 text-sm font-mono focus:border-foreground outline-none"
              />

              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  onClick={() => decide(active.id, "approved")}
                  className="border border-state-accept text-state-accept px-4 py-2 font-mono text-xs uppercase tracking-widest hover:bg-state-accept hover:text-background"
                >
                  Approve →
                </button>
                <button
                  onClick={() => decide(active.id, "needs_more_evidence")}
                  className="border border-state-verify text-state-verify px-4 py-2 font-mono text-xs uppercase tracking-widest hover:bg-state-verify hover:text-background"
                >
                  Needs more evidence
                </button>
                <button
                  onClick={() => decide(active.id, "rejected")}
                  className="border border-state-escalate text-state-escalate px-4 py-2 font-mono text-xs uppercase tracking-widest hover:bg-state-escalate hover:text-background"
                >
                  Reject
                </button>
              </div>

              <ul className="mt-5 space-y-1 font-mono text-[10px] text-muted-foreground">
                <li>· requester is not eligible as sole approver (separation of duties)</li>
                <li>· approval cannot override missing audit logging</li>
                <li>· rejected decisions remain blocked even on retry</li>
              </ul>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-foreground">{v}</dd>
    </>
  );
}
