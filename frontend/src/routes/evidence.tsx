import { createFileRoute } from "@tanstack/react-router";
import { Callout, EvidenceTable, PageHeader, SectionLabel } from "@/components/primitives";
import { QA_BENCH, TOOL_BENCH } from "@/content/whitepaper";

export const Route = createFileRoute("/evidence")({
  head: () => ({
    meta: [
      { title: "Evidence — REMORA benchmarks & calibration" },
      {
        name: "description",
        content:
          "Benchmark tables for full-coverage QA and tool-call safety. Calibration and negative results for the REMORA governance layer.",
      },
      { property: "og:title", content: "REMORA Evidence & Benchmarks" },
      {
        property: "og:description",
        content: "Tool-call safety dominates; full-coverage QA is not the headline metric.",
      },
    ],
  }),
  component: EvidencePage,
});

function EvidencePage() {
  return (
    <div className="mx-auto max-w-6xl px-6">
      <section className="pt-24 pb-16">
        <PageHeader
          eyebrow="Section 09 · Evidence"
          title="What the benchmarks say — and what they do not."
          lede="REMORA is not a raw accuracy maximizer. Its commercial center of gravity is governed tool execution, where unsafe-execution rate is the metric that matters."
        />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="09.1">Full-coverage QA</SectionLabel>
        <p className="mt-6 max-w-2xl text-sm text-muted-foreground leading-relaxed">
          Across the committed QA corpora, REMORA does not dominate single-model or naive-ensemble
          baselines. This is expected: the system trades coverage for selective reliability.
        </p>
        <EvidenceTable cols={QA_BENCH.cols} rows={QA_BENCH.rows} caption={QA_BENCH.caption} />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="09.3">Tool-call safety</SectionLabel>
        <p className="mt-6 max-w-2xl text-sm text-muted-foreground leading-relaxed">
          With the full policy gate engaged, unsafe-execution rate collapses by roughly two orders
          of magnitude relative to a single-model baseline on the v2 benchmark.
        </p>
        <EvidenceTable cols={TOOL_BENCH.cols} rows={TOOL_BENCH.rows} caption={TOOL_BENCH.caption} />
      </section>

      <section className="border-t border-border py-12">
        <SectionLabel number="09.4">Calibration & negative results</SectionLabel>
        <Callout title="What REMORA is not">
          REMORA is not a universal accuracy oracle. It does not make a compromised model safe by
          itself. The Lyapunov-style monitor V(t) is a session-level signal, not a proof of agent
          correctness. The mathematical language is strongest when tied to observed routing behavior
          in committed benchmarks.
        </Callout>
      </section>
    </div>
  );
}
