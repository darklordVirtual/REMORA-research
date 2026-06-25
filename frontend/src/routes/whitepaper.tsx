import { createFileRoute, Link } from "@tanstack/react-router";
import { Callout, Cite, EvidenceTable, PageHeader, SectionLabel } from "@/components/primitives";
import { CITATIONS, META, QA_BENCH, THREATS, TOOL_BENCH } from "@/content/whitepaper";

export const Route = createFileRoute("/whitepaper")({
  head: () => ({
    meta: [
      { title: "Whitepaper — REMORA Governed Agentic AI" },
      {
        name: "description",
        content:
          "Full whitepaper: executive thesis, decision framework, runtime components, evidence, threat model and roadmap.",
      },
      { property: "og:title", content: "REMORA Whitepaper" },
      {
        property: "og:description",
        content: "Evidence-scoped technical whitepaper for governed agentic AI.",
      },
    ],
  }),
  component: WhitepaperPage,
});

const toc = [
  { id: "thesis", n: "01", label: "Executive thesis" },
  { id: "scope", n: "02", label: "Evidence scope" },
  { id: "problem", n: "03", label: "Problem statement" },
  { id: "framework", n: "06", label: "Decision framework" },
  { id: "gui-demo", n: "08", label: "GUI demo" },
  { id: "evidence", n: "09", label: "Benchmarks" },
  { id: "threats", n: "12", label: "Threat model" },
  { id: "citations", n: "A", label: "Citations" },
];

function WhitepaperPage() {
  return (
    <div className="mx-auto max-w-6xl px-6">
      <section className="pt-24 pb-12">
        <PageHeader
          eyebrow="Technical whitepaper · evidence scoped"
          title="REMORA: governed agentic AI."
          lede="An evidence-scoped technical overview of REMORA's decision framework, runtime components, benchmarks, and threat model."
        />
        <div className="mt-8 flex flex-wrap gap-3">
          <a
            href="https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf"
            target="_blank"
            rel="noreferrer"
            className="border border-signal/50 bg-signal/[0.04] hover:bg-signal/[0.09] transition-all px-5 py-3 font-mono text-[13px]"
          >
            Download the research paper (PDF) →
          </a>
          <a
            href="https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf"
            target="_blank"
            rel="noreferrer"
            className="border border-state-verify/50 bg-state-verify/[0.04] hover:bg-state-verify/[0.09] transition-all px-5 py-3 font-mono text-[13px]"
          >
            Download the enterprise white paper (PDF, TOGAF-aligned) →
          </a>
        </div>
      </section>

      <div className="grid gap-16 md:grid-cols-[200px_1fr] border-t border-border pt-12">
        <aside className="md:sticky md:top-24 md:self-start">
          <SectionLabel>Contents</SectionLabel>
          <ol className="mt-6 space-y-2 text-sm">
            {toc.map((t) => (
              <li key={t.id}>
                <a
                  href={`#${t.id}`}
                  className="flex gap-3 text-muted-foreground hover:text-foreground"
                >
                  <span className="font-mono text-xs w-6">{t.n}</span>
                  <span>{t.label}</span>
                </a>
              </li>
            ))}
          </ol>
        </aside>

        <article className="max-w-2xl space-y-16 leading-relaxed">
          <Section id="thesis" n="01" title="Executive thesis">
            <p>
              REMORA should be positioned as a governance control plane for agentic AI: it decides
              when probabilistic model output is reliable enough to answer, when evidence must be
              consulted, when action must be blocked, and when a human must approve.
              <Cite id="S1" />
            </p>
            <p>
              Its strongest validated value is selective reliability and safe tool execution — not
              universal full-coverage QA superiority. The right metric is governed action quality.
            </p>
          </Section>

          <Section id="scope" n="02" title="Evidence scope">
            <p>
              Claims in this whitepaper are scoped to the uploaded technical report and the public
              REMORA repository at head {META.repoHead} ({META.version}).
            </p>
            <Callout title="Audit warning" tone="warn">
              The repository commit message reports 1,184 tests passing. This is a repository
              reported status, not an independently re-executed result. <Cite id="S2" />
            </Callout>
          </Section>

          <Section id="problem" n="03" title="Agentic AI turns answers into actions">
            <p>
              Once a model proposal becomes a tool call, the cost of a wrong answer changes shape.
              The minimum control plane therefore needs consensus, uncertainty, evidence, policy and
              audit — together, not in isolation.
            </p>
          </Section>

          <Section id="framework" n="06" title="Decision framework">
            <p>
              The decision function is expressed as{" "}
              <code className="font-mono">D = g(C, U, P, E, R)</code>, producing one of ACCEPT,
              VERIFY, ABSTAIN or ESCALATE. Session stability is tracked by
              <code className="font-mono"> V(t) = H(t) + λD(t)</code>, a monitor for entropy and
              dissensus growth — not a proof of correctness.
            </p>
          </Section>

          <Section id="gui-demo" n="08" title="Control-room GUI demo">
            <p>
              The control-room route demonstrates the operational version of the framework. When
              REMORA cannot approve or reject safely, the reviewer can request site verification
              instead of forcing a binary decision.
              <Cite id="S14" />
            </p>
            <Callout title="Simulation scope" tone="warn">
              The GUI creates deterministic follow-up requests, field responses and review
              envelopes. It does not claim live integration with CMMS, field-service apps or
              production safety systems.
            </Callout>
            <p>
              The simulated lifecycle is <code className="font-mono">PENDING_REVIEW</code>,{" "}
              <code className="font-mono">SITE_VERIFICATION_PENDING</code>,{" "}
              <code className="font-mono">EVIDENCE_RECEIVED</code>,{" "}
              <code className="font-mono">READY_FOR_REVIEW</code>, then final approval, rejection or
              closure. Similar-case history can create a policy-learning candidate, but it cannot
              change policy without owner approval.
            </p>
          </Section>

          <Section id="evidence" n="09" title="Benchmarks">
            <EvidenceTable cols={QA_BENCH.cols} rows={QA_BENCH.rows} caption={QA_BENCH.caption} />
            <EvidenceTable
              cols={TOOL_BENCH.cols}
              rows={TOOL_BENCH.rows}
              caption={TOOL_BENCH.caption}
            />
            <p>
              See{" "}
              <Link to="/evidence" className="border-b border-border hover:border-foreground">
                Evidence
              </Link>{" "}
              for calibration and negative results. <Cite id="S6" />
            </p>
          </Section>

          <Section id="threats" n="12" title="Threat model">
            <ul className="space-y-6">
              {THREATS.map((t) => (
                <li key={t.threat} className="border-l border-border pl-5">
                  <div className="font-serif text-lg">{t.threat}</div>
                  <div className="mt-1 text-sm text-muted-foreground">{t.example}</div>
                  <div className="mt-2 text-sm">{t.control}</div>
                </li>
              ))}
            </ul>
            <p>
              REMORA is a policy and verification boundary in front of agent tools.
              <Cite id="S12" />
            </p>
          </Section>

          <Section id="citations" n="A" title="Citations">
            <ul className="space-y-3 text-sm">
              {CITATIONS.map((c) => (
                <li key={c.id} id={`cite-${c.id}`} className="flex gap-4">
                  <span className="font-mono text-xs text-muted-foreground w-10 mt-0.5">
                    [{c.id}]
                  </span>
                  <span className="text-muted-foreground">{c.label}</span>
                </li>
              ))}
            </ul>
          </Section>
        </article>
      </div>
    </div>
  );
}

function Section({
  id,
  n,
  title,
  children,
}: {
  id: string;
  n: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <SectionLabel number={n}>{title}</SectionLabel>
      <h2 className="mt-4 font-serif text-3xl tracking-tight">{title}</h2>
      <div className="mt-6 space-y-5 text-[15px] text-foreground/90">{children}</div>
    </section>
  );
}
