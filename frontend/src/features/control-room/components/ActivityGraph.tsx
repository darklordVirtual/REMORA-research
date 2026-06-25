import React from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ActivityBucket, SessionKPI } from "../types";

function ActivityGraphRaw({ data, kpi }: { data: ActivityBucket[]; kpi: SessionKPI }) {
  const autoTotal = kpi.accept + kpi.verify + kpi.abstain;
  const timeSavedMin = kpi.accept * 12 + kpi.verify * 6 + kpi.abstain * 3;
  const timeSavedStr =
    timeSavedMin >= 60
      ? `${(timeSavedMin / 60).toFixed(1)} hrs`
      : timeSavedMin > 0
        ? `${timeSavedMin} min`
        : "—";
  const pctAuto = kpi.runs > 0 ? Math.round((autoTotal / kpi.runs) * 100) : 0;

  const empty = data.length === 0;

  return (
    <div className="shrink-0 border-b border-border bg-background" style={{ height: 196 }}>
      <div className="flex items-center justify-between px-5 pt-3 pb-1">
        <div className="font-mono text-[11px] uppercase tracking-[0.12em] text-muted-foreground/75">
          REMORA decisions — simulated session
        </div>
        <div className="flex items-center gap-5 font-mono text-[11px]">
          <span className="text-muted-foreground/72">{pctAuto}% autonomous</span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-state-accept inline-block" />
            <span className="text-muted-foreground/72">auto-handled</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-state-escalate inline-block" />
            <span className="text-muted-foreground/72">escalated</span>
          </span>
          <span className="text-state-accept font-medium tabular-nums">
            {timeSavedStr} engineer-time freed
          </span>
        </div>
      </div>

      {empty ? (
        <div className="flex items-center justify-center h-36 font-mono text-[11px] text-muted-foreground/48 uppercase tracking-[0.12em]">
          Awaiting events…
        </div>
      ) : (
        <div style={{ height: 148 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} barSize={14} margin={{ top: 4, right: 16, left: -24, bottom: 0 }}>
              <XAxis
                dataKey="label"
                stroke="var(--muted-foreground)"
                fontSize={8}
                tickLine={false}
                axisLine={false}
                tick={{ opacity: 0.4 }}
              />
              <YAxis
                stroke="var(--muted-foreground)"
                fontSize={8}
                tickLine={false}
                axisLine={false}
                tick={{ opacity: 0.4 }}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--background)",
                  border: "1px solid var(--border)",
                  fontSize: 10,
                  fontFamily: "var(--font-mono)",
                  borderRadius: 0,
                }}
                cursor={{ fill: "rgba(255,255,255,0.03)" }}
                formatter={(val, name) => [val, name === "auto" ? "Auto-handled" : "Escalated"]}
              />
              <Bar
                dataKey="auto"
                stackId="a"
                fill="var(--state-accept)"
                fillOpacity={0.65}
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="escalated"
                stackId="a"
                fill="var(--state-escalate)"
                fillOpacity={0.75}
                radius={[2, 2, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export const ActivityGraph = React.memo(ActivityGraphRaw);
