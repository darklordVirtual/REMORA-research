import { createFileRoute } from "@tanstack/react-router";
import { ArchitectureDiagram } from "@/components/architecture-diagram";
import { EvidenceTable, PageHeader, SectionLabel } from "@/components/primitives";
import { CAPABILITIES } from "@/content/whitepaper";

export const Route = createFileRoute("/architecture")({
  head: () => ({
    meta: [
      { title: "Architecture — REMORA control plane" },
      {
        name: "description",
        content:
          "Runtime components, decision function and capability inventory for the REMORA governance control plane.",
      },
      { property: "og:title", content: "REMORA Architecture" },
      {
        property: "og:description",
        content: "Decision function D = g(C, U, P, E, R) and runtime capability inventory.",
      },
    ],
  }),
  component: ArchitecturePage,
});

function ArchitecturePage() {
  return (
    <div className="mx-auto max-w-6xl px-6">
      <section className="pt-24 pb-16">
        <PageHeader
          eyebrow="Section 07 · Architecture"
          title="Runtime components."
          lede="REMORA decomposes into a fast confidence gate, an oracle pool, a canonicalization stage, consensus and uncertainty estimators, a policy gate, and an audit envelope."
        />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="07.1">Control plane</SectionLabel>
        <ArchitectureDiagram />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="07.2">Decision function</SectionLabel>
        <div className="mt-8 grid gap-10 md:grid-cols-2">
          <div className="border border-border p-8 bg-card">
            <div className="font-mono text-xs text-muted-foreground">decision</div>
            <div className="mt-3 font-mono text-2xl">D = g(C, U, P, E, R)</div>
            <p className="mt-4 text-sm text-muted-foreground leading-relaxed">
              C is canonical consensus state, U is uncertainty state, P is policy observation, E is
              evidence status, R is operational risk. The output D is one of ACCEPT, VERIFY, ABSTAIN
              or ESCALATE.
            </p>
          </div>
          <div className="border border-border p-8 bg-card">
            <div className="font-mono text-xs text-muted-foreground">session stability</div>
            <div className="mt-3 font-mono text-2xl">V(t) = H(t) + λD(t)</div>
            <p className="mt-4 text-sm text-muted-foreground leading-relaxed">
              A non-increasing V(t) trajectory is a monitor for whether entropy and dissensus are
              not growing across a session. It is not a proof of general agent correctness.
            </p>
          </div>
        </div>
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="07.3">Runtime capability inventory</SectionLabel>
        <EvidenceTable
          cols={["Capability", "Role", "Status"]}
          rows={CAPABILITIES.map((c) => [c.name, c.role, c.status])}
          caption="Components inspected at repository head 5e051b9."
        />
      </section>
    </div>
  );
}
