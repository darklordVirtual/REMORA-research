import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { PageHeader, SectionLabel } from "@/components/primitives";
import { SourceBadge } from "@/components/source-badge";
import { apiConfig, getGovernanceMetrics, getPolicyVersion } from "@/lib/api/execution";

export const Route = createFileRoute("/executions")({
  head: () => ({
    meta: [
      { title: "Executions — Governance read models" },
      {
        name: "description",
        content:
          "Live governance metrics and policy identity from the canonical /v1 API, with an explicit data-source state.",
      },
    ],
  }),
  component: ExecutionsPage,
});

/**
 * Product Console: the first surface consuming the REAL read-model API
 * (Phase 12). Every panel states its data source explicitly; with no API
 * configured the page says DEMO/no data instead of rendering anything
 * synthetic — this page never imports the sim engine.
 */
function ExecutionsPage() {
  const config = apiConfig();

  const metrics = useQuery({
    queryKey: ["governance-metrics"],
    queryFn: () => getGovernanceMetrics(config),
    refetchInterval: 15_000,
  });
  const policy = useQuery({
    queryKey: ["policy-version"],
    queryFn: () => getPolicyVersion(config),
    refetchInterval: 60_000,
  });

  const metricsResult = metrics.data;
  const policyResult = policy.data;
  const decisionCounts = metricsResult?.data?.execution_decision_counts ?? {};
  const refusals = metricsResult?.data?.execution_refusals ?? {};

  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="Product Console"
        title="Executions"
        lede="Governance read models from the canonical /v1 API. Every panel carries its real data-source state — nothing on this page is simulated."
      />

      <section className="mt-10">
        <div className="flex items-center gap-3">
          <SectionLabel number="1">Decision volume</SectionLabel>
          {metricsResult ? (
            <SourceBadge state={metricsResult.state} detail={metricsResult.detail} />
          ) : null}
        </div>
        {metricsResult?.data ? (
          <div className="mt-6 grid grid-cols-2 gap-px border border-border/40 bg-border/40 md:grid-cols-4">
            {(["accept", "verify", "abstain", "escalate"] as const).map((k) => (
              <div key={k} className="bg-background px-4 py-4">
                <div className="font-serif text-3xl tracking-tight">{decisionCounts[k] ?? 0}</div>
                <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {k}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-6 text-sm text-muted-foreground">
            No live data. Configure <code>VITE_REMORA_API_URL</code> and{" "}
            <code>VITE_REMORA_API_TOKEN</code> to connect this console to a deployed governance API.
          </p>
        )}
      </section>

      <section className="mt-12">
        <div className="flex items-center gap-3">
          <SectionLabel number="2">Dispatch & refusals</SectionLabel>
          {metricsResult ? (
            <SourceBadge state={metricsResult.state} detail={metricsResult.detail} />
          ) : null}
        </div>
        {metricsResult?.data ? (
          <div className="mt-6 divide-y divide-border border-y border-border text-sm">
            <div className="flex justify-between py-3">
              <span>Tool calls actually executed</span>
              <span className="font-mono">
                {metricsResult.data.execution_tool_calls_executed ?? 0}
              </span>
            </div>
            {Object.entries(refusals).map(([reason, count]) => (
              <div key={reason} className="flex justify-between py-3">
                <span className="text-muted-foreground">{reason}</span>
                <span className="font-mono">{count}</span>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="mt-12">
        <div className="flex items-center gap-3">
          <SectionLabel number="3">Policy identity</SectionLabel>
          {policyResult ? (
            <SourceBadge state={policyResult.state} detail={policyResult.detail} />
          ) : null}
        </div>
        {policyResult?.data ? (
          <div className="mt-6 divide-y divide-border border-y border-border font-mono text-xs">
            <div className="flex justify-between gap-6 py-3">
              <span className="text-muted-foreground">policy_version</span>
              <span>{policyResult.data.policy_version}</span>
            </div>
            <div className="flex justify-between gap-6 py-3">
              <span className="text-muted-foreground">policy_hash</span>
              <span className="truncate">{policyResult.data.policy_hash}</span>
            </div>
            <div className="flex justify-between gap-6 py-3">
              <span className="text-muted-foreground">runtime_mode</span>
              <span>{policyResult.data.runtime_mode}</span>
            </div>
            <div className="flex justify-between gap-6 py-3">
              <span className="text-muted-foreground">execution_state_durable</span>
              <span>{String(policyResult.data.execution_state_durable)}</span>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
