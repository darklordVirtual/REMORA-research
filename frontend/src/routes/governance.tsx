import { createFileRoute } from "@tanstack/react-router";
import { PageHeader, SectionLabel } from "@/components/primitives";
import { ROADMAP, THREATS } from "@/content/whitepaper";

export const Route = createFileRoute("/governance")({
  head: () => ({
    meta: [
      { title: "Governance — Threat model & roadmap" },
      {
        name: "description",
        content:
          "Threat model for governed agents, residual risks, and the roadmap from prototype to externally credible governance system.",
      },
      { property: "og:title", content: "REMORA Governance" },
      {
        property: "og:description",
        content: "Policy boundary in front of agent tools, with NIST AI RMF alignment.",
      },
    ],
  }),
  component: GovernancePage,
});

function GovernancePage() {
  return (
    <div className="mx-auto max-w-6xl px-6">
      <section className="pt-24 pb-16">
        <PageHeader
          eyebrow="Section 12 · Governance"
          title="A policy and verification boundary in front of agent tools."
          lede="REMORA cannot make a compromised model safe by itself. It can reduce the probability that a model proposal becomes an ungoverned action."
        />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="12.1">Threat model</SectionLabel>
        <div className="mt-8 divide-y divide-border border-y border-border">
          {THREATS.map((t) => (
            <div key={t.threat} className="grid gap-4 py-6 md:grid-cols-4 md:gap-8">
              <div className="font-serif text-xl tracking-tight">{t.threat}</div>
              <div className="text-sm text-muted-foreground">{t.example}</div>
              <div className="text-sm">{t.control}</div>
              <div className="text-sm text-muted-foreground italic">{t.residual}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-4 md:gap-8 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <div>Threat</div>
          <div>Example</div>
          <div>REMORA control</div>
          <div>Residual risk</div>
        </div>
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="14">Roadmap to world-class credibility</SectionLabel>
        <ol className="mt-8 grid gap-px bg-border md:grid-cols-2">
          {ROADMAP.map((step, i) => (
            <li key={step} className="bg-background p-6 flex gap-4">
              <span className="font-mono text-xs text-muted-foreground mt-1">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-sm leading-relaxed">{step}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
