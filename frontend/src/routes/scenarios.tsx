import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { PageHeader, SectionLabel, DecisionChip } from "@/components/primitives";
import { PipelineTrace } from "@/components/pipeline-trace";
import { PhaseMeter } from "@/components/phase-meter";
import { OracleBoard } from "@/components/oracle-board";
import { DecisionCard } from "@/components/decision-card";
import { SCENARIOS, simulate, type Scenario } from "@/lib/remora-sim";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/scenarios")({
  head: () => ({
    meta: [
      { title: "REMORA · Scenarios — enterprise demo gallery" },
      {
        name: "description",
        content:
          "Pre-canned enterprise scenarios — maintenance, legal, SOC, document Q&A, prompt-injection — run through the full REMORA decision pipeline.",
      },
    ],
  }),
  component: ScenariosPage,
});

const TAG_LABEL: Record<Scenario["tag"], string> = {
  industrial: "Industrial",
  legal: "Legal",
  security: "Security",
  document: "Document",
  adversarial: "Adversarial",
};

function ScenariosPage() {
  const [active, setActive] = useState<Scenario>(SCENARIOS[0]);
  const trace = useMemo(
    () =>
      simulate(active.query, {
        scenarioId: active.id,
        bias: active.bias,
        risk: active.risk,
        domain: active.domain,
      }),
    [active],
  );

  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="REMORA · scenario gallery"
        title="Six enterprise tests, one control plane."
        lede="Each card runs the same governed pipeline: intent → policy → oracle fan-out → evidence retrieval → phase analysis → decision gate → audit append. Pure simulation — reproducible per scenario."
      />

      <section className="mt-12">
        <SectionLabel number="01">Scenarios</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-3">
          {SCENARIOS.map((s) => {
            const isActive = s.id === active.id;
            return (
              <button
                key={s.id}
                onClick={() => setActive(s)}
                className={cn(
                  "bg-background p-5 text-left transition-colors",
                  isActive ? "ring-1 ring-foreground -m-px relative" : "hover:bg-muted",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {TAG_LABEL[s.tag]}
                  </span>
                  <DecisionChip state={s.expected} />
                </div>
                <h3 className="mt-3 font-serif text-xl tracking-tight">{s.title}</h3>
                <p className="mt-2 text-xs text-muted-foreground leading-relaxed line-clamp-3">
                  {s.blurb}
                </p>
              </button>
            );
          })}
        </div>
      </section>

      <section className="mt-14">
        <SectionLabel number="02">Request</SectionLabel>
        <blockquote className="mt-6 border-l-2 border-signal pl-5 font-serif text-xl leading-snug text-foreground/90 max-w-3xl">
          “{active.query}”
        </blockquote>
      </section>

      <section className="mt-12 grid gap-10 lg:grid-cols-[1.4fr_1fr]">
        <div>
          <SectionLabel number="03">Pipeline</SectionLabel>
          <div className="mt-6">
            <PipelineTrace trace={trace} />
          </div>
          <div className="mt-8">
            <OracleBoard votes={trace.oracles} />
          </div>
        </div>
        <div className="space-y-6">
          <DecisionCard trace={trace} />
          <PhaseMeter thermo={trace.thermo} />
          <PolicyTriggersCard triggers={trace.policy.triggers} />
        </div>
      </section>

      <section className="mt-12">
        <SectionLabel number="04">Evidence</SectionLabel>
        <div className="mt-6 grid gap-px bg-border md:grid-cols-2">
          {trace.evidence.length === 0 && (
            <div className="bg-background p-6 text-sm text-muted-foreground">
              No approved evidence sources returned — gate auto-escalated.
            </div>
          )}
          {trace.evidence.map((e, i) => (
            <div key={i} className="bg-background p-5">
              <div className="flex items-center justify-between font-mono text-[11px]">
                <span>{e.source}</span>
                <span className="text-muted-foreground">
                  {e.section} · {e.score} · {e.fresh_days}d
                </span>
              </div>
              <p className="mt-2 text-sm leading-relaxed">{e.snippet}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function PolicyTriggersCard({
  triggers,
}: {
  triggers: { rule: string; effect: string; reason: string }[];
}) {
  return (
    <div className="border border-border p-5">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        Policy triggers
      </div>
      {triggers.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No rules triggered for this request.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border">
          {triggers.map((t) => (
            <li key={t.rule} className="py-2.5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs">{t.rule}</span>
                <span className="font-mono text-[10px] uppercase tracking-widest text-state-verify">
                  {t.effect.replace("_", " ")}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{t.reason}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
