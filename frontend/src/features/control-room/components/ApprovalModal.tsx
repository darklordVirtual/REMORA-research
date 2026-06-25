import React, { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import type { EscalationItem, ReviewStatus, FollowUpForm, FieldResponse } from "../types";
import {
  deriveAsset,
  deriveWhyEscalated,
  deriveRiskMatrix,
  deriveEvidence,
  deriveTimeline,
  deriveHistory,
  derivePolicyLearning,
  deriveFollowUpDefaults,
  deriveFieldResponse,
} from "../derivation";
import { downloadReviewEnvelope } from "../download";
import { RISK_BADGE, RISK_LEVEL_CLS, phaseText } from "../styles";
import { FAMILY_DOT } from "../styles";
import { AssetCAD } from "./AssetCAD";
import { FollowUpRequestPanel } from "./FollowUpRequestPanel";

function ApprovalModalRaw({
  item,
  onDecide,
  onClose,
}: {
  item: EscalationItem;
  onDecide: (id: number, decision: ReviewStatus) => void;
  onClose: () => void;
}) {
  const [decided, setDecided] = useState<"approved" | "rejected" | "escalated" | null>(null);
  const [view, setView] = useState<"review" | "followup_form">(
    item.status === "site_verification_pending" || item.status === "evidence_received"
      ? "followup_form"
      : "review",
  );
  const [evTab, setEvTab] = useState<"evidence" | "asset" | "timeline" | "oracles" | "history">(
    "evidence",
  );
  const [reviewerNote, setReviewerNote] = useState("");
  const [fuForm, setFuForm] = useState<FollowUpForm>(() => deriveFollowUpDefaults(item));
  const [followUpSubmitted, setFollowUpSubmitted] = useState(
    item.status === "site_verification_pending" || item.status === "evidence_received",
  );
  const [fieldResponse, setFieldResponse] = useState<FieldResponse | null>(
    item.status === "evidence_received" ? deriveFieldResponse(item) : null,
  );

  const t = item.trace;
  const auditHash = t.request_id.slice(0, 16);
  const asset = useMemo(() => deriveAsset(item), [item]);
  const whyList = useMemo(() => deriveWhyEscalated(t, item), [t, item]);
  const riskMatrix = useMemo(() => deriveRiskMatrix(item), [item]);
  const evSources = useMemo(() => deriveEvidence(t, t.intent.domain), [t]);
  const timeline = useMemo(() => deriveTimeline(item, asset), [item, asset]);
  const history = useMemo(() => deriveHistory(item), [item]);
  const policyLearning = useMemo(() => derivePolicyLearning(item, history), [item, history]);

  const oracleAgreement = useMemo(() => {
    const c = new Map<string, number>();
    for (const v of t.oracles) c.set(v.answer, (c.get(v.answer) ?? 0) + 1);
    const dom = [...c.entries()].sort((a, b) => b[1] - a[1])[0];
    return dom ? Math.round((dom[1] / t.oracles.length) * 100) : 0;
  }, [t]);

  function decide(d: "approved" | "rejected" | "escalated") {
    setDecided(d);
    const outcome: ReviewStatus =
      d === "approved" ? "approved" : d === "escalated" ? "follow_up_required" : "rejected";
    setTimeout(() => onDecide(item.id, outcome), 1200);
  }

  function createFollowUpRequest() {
    setFollowUpSubmitted(true);
    onDecide(item.id, "site_verification_pending");
    setTimeout(() => {
      setFieldResponse(deriveFieldResponse(item));
      onDecide(item.id, "evidence_received");
    }, 1200);
  }

  function markReadyForReview() {
    onDecide(item.id, "ready_for_review");
    setView("review");
    setEvTab("evidence");
  }

  function exportReviewEnvelope() {
    downloadReviewEnvelope(item, fuForm, fieldResponse, history, policyLearning, reviewerNote);
  }

  const isCritical = item.risk === "critical";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/85 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative w-full max-w-5xl max-h-[94dvh] flex flex-col border border-border bg-background shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="shrink-0 flex items-center justify-between px-6 py-3.5 border-b border-border bg-background/98">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-xl shrink-0">{item.icon}</span>
            <div className="min-w-0">
              <div className="font-serif text-lg tracking-tight leading-tight truncate">
                {item.title}
              </div>
              <div className="font-mono text-[10px] text-muted-foreground/65 mt-0.5 flex items-center gap-2 flex-wrap">
                <span>{item.sector}</span>
                <span className="text-border">·</span>
                <span className="text-state-escalate/80">{asset.id}</span>
                <span className="text-border">·</span>
                <span>{item.ts}</span>
                <span className="text-border">·</span>
                <span className="tabular-nums">{t.request_id}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            <span
              className={cn(
                "font-mono text-[11px] border px-2 py-0.5 uppercase tracking-wider",
                RISK_BADGE[item.risk] ?? RISK_BADGE.high,
              )}
            >
              {item.risk} risk
            </span>
            <span className="font-mono text-[11px] border border-state-escalate/35 text-state-escalate px-2 py-0.5 uppercase tracking-wider">
              ESCALATE
            </span>
            <button
              onClick={onClose}
              className="font-mono text-lg leading-none text-muted-foreground/65 hover:text-foreground transition-colors ml-1"
            >
              ×
            </button>
          </div>
        </div>

        {decided ? (
          /* Post-decision */
          <div className="flex-1 flex flex-col items-center justify-center gap-6 p-10 text-center">
            <div
              className={cn(
                "font-serif text-5xl tracking-tight",
                decided === "approved" ? "text-state-accept" : "text-muted-foreground",
              )}
            >
              {decided === "approved"
                ? "APPROVED"
                : decided === "escalated"
                  ? "ESCALATED TO SME"
                  : "REJECTED"}
            </div>
            <div className="space-y-1 font-mono text-[11px] text-muted-foreground/60">
              <div>Operator: System Operator</div>
              <div>
                Audit hash: <span className="text-foreground/82">{auditHash}</span>
              </div>
              {reviewerNote && (
                <div className="max-w-sm text-left mt-3 border-l-2 border-signal/30 pl-3 text-muted-foreground/75">
                  Note: {reviewerNote}
                </div>
              )}
              <div className="mt-2">Logged to immutable audit ledger</div>
            </div>
          </div>
        ) : (
          <>
            {/* Body: left summary · right evidence pack */}
            <div className="flex-1 overflow-hidden flex min-h-0 divide-x divide-border">
              {/* Left: Decision summary */}
              <div className="w-72 shrink-0 overflow-y-auto flex flex-col divide-y divide-border/50">
                {/* Proposed action */}
                <div className="p-4 space-y-2">
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                    Proposed agent action
                  </div>
                  <div className="border-l-2 border-state-escalate/40 pl-3 font-serif text-sm leading-relaxed text-foreground/82 italic">
                    "{item.proposed_action}"
                  </div>
                </div>

                {/* Why REMORA escalated */}
                <div className="p-4 space-y-2.5">
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                    Why REMORA escalated
                  </div>
                  <ol className="space-y-1.5">
                    {whyList.map((r, i) => (
                      <li
                        key={i}
                        className="flex gap-2 font-mono text-[11px] text-foreground/78 leading-relaxed"
                      >
                        <span className="text-muted-foreground/52 shrink-0 tabular-nums">
                          {i + 1}.
                        </span>
                        {r}
                      </li>
                    ))}
                  </ol>
                </div>

                {/* Risk exposure */}
                <div className="p-4 space-y-2">
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                    Risk exposure
                  </div>
                  <div className="space-y-1.5">
                    {riskMatrix.map((r) => (
                      <div key={r.label} className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-muted-foreground/72 w-24 shrink-0">
                          {r.label}
                        </span>
                        <span
                          className={cn(
                            "font-mono text-[10px] uppercase tracking-wider border px-2 py-px",
                            RISK_LEVEL_CLS[r.level],
                          )}
                        >
                          {r.level}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* REMORA assessment summary */}
                <div className="p-4 space-y-2">
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                    REMORA assessment
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: "Trust", val: `${(t.thermo.trust * 100).toFixed(0)}%` },
                      { label: "Phase", val: t.thermo.phase },
                      { label: "Agreement", val: `${oracleAgreement}%` },
                      { label: "Policy hits", val: `${t.policy.triggers.length}` },
                    ].map(({ label, val }) => (
                      <div key={label} className="border border-border/40 p-2 text-center">
                        <div
                          className={cn(
                            "font-mono text-xs tabular-nums",
                            label === "Phase" ? phaseText(t.thermo.phase) : "text-foreground/82",
                          )}
                        >
                          {val}
                        </div>
                        <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/55 mt-0.5">
                          {label}
                        </div>
                      </div>
                    ))}
                  </div>
                  <p className="font-mono text-[11px] text-muted-foreground/70 leading-relaxed">
                    {t.reason}
                  </p>
                </div>

                {/* Reviewer note */}
                <div className="p-4 space-y-2">
                  <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                    Reviewer note (audit trail)
                  </div>
                  <textarea
                    value={reviewerNote}
                    onChange={(e) => setReviewerNote(e.target.value)}
                    rows={3}
                    placeholder="Add rationale for immutable audit record…"
                    className="w-full resize-none bg-muted/10 border border-border/50 px-3 py-2 font-mono text-[11px] text-foreground/80 placeholder:text-muted-foreground/42 focus:outline-none focus:border-foreground/25 leading-relaxed"
                  />
                </div>
              </div>

              {/* Right: Evidence Pack (tabbed) */}
              <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                {/* Tab bar */}
                <div className="shrink-0 flex border-b border-border">
                  {view === "followup_form" ? (
                    <div className="px-5 py-2.5 font-mono text-[11px] uppercase tracking-[0.10em] text-state-verify bg-state-verify/5 border-r border-state-verify/25">
                      Follow-up request
                    </div>
                  ) : (
                    (["evidence", "asset", "timeline", "oracles", "history"] as const).map(
                      (tab) => (
                        <button
                          key={tab}
                          onClick={() => setEvTab(tab)}
                          className={cn(
                            "px-5 py-2.5 font-mono text-[11px] uppercase tracking-[0.10em] border-r border-border transition-colors",
                            evTab === tab
                              ? "text-foreground/88 bg-foreground/4"
                              : "text-muted-foreground/60 hover:text-muted-foreground/80",
                          )}
                        >
                          {tab === "evidence"
                            ? "Evidence"
                            : tab === "asset"
                              ? "Asset / CAD"
                              : tab === "timeline"
                                ? "Timeline"
                                : tab === "oracles"
                                  ? "Oracle Detail"
                                  : "History"}
                        </button>
                      ),
                    )
                  )}
                </div>

                {/* Tab content */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {view === "followup_form" && (
                    <FollowUpRequestPanel
                      item={item}
                      form={fuForm}
                      onChange={setFuForm}
                      submitted={followUpSubmitted}
                      fieldResponse={fieldResponse}
                      history={history}
                      policyLearning={policyLearning}
                      onBack={() => setView("review")}
                      onCreate={createFollowUpRequest}
                      onMarkReady={markReadyForReview}
                      onExport={exportReviewEnvelope}
                    />
                  )}

                  {view === "review" && (
                    <>
                      {evTab === "evidence" && (
                        <>
                          <div>
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                              Evidence sources
                            </div>
                            <div className="border border-border divide-y divide-border/40">
                              {evSources.map((es, i) => (
                                <div key={i} className="flex items-center gap-3 px-3 py-2">
                                  <span
                                    className={cn(
                                      "font-mono text-[12px] shrink-0 w-4 text-center font-bold",
                                      es.found ? "text-state-accept" : "text-state-escalate/65",
                                    )}
                                  >
                                    {es.found ? "✓" : "✕"}
                                  </span>
                                  <span className="font-mono text-[11px] text-foreground/82 flex-1">
                                    {es.label}
                                  </span>
                                  {!es.found && (
                                    <span className="font-mono text-[10px] text-state-escalate/60 border border-state-escalate/25 px-1.5 py-px">
                                      missing
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                          <div>
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                              RAG evidence detail
                            </div>
                            <div className="border border-border divide-y divide-border/40">
                              {t.evidence.map((e, i) => (
                                <div key={i} className="px-3 py-2.5 space-y-1">
                                  <div className="flex items-baseline gap-2 flex-wrap">
                                    <span className="font-mono text-[11px] font-medium text-foreground/85">
                                      {e.source}
                                    </span>
                                    <span className="font-mono text-[10px] text-muted-foreground/62">
                                      {e.section}
                                    </span>
                                    <span className="font-mono text-[10px] text-muted-foreground/50 ml-auto tabular-nums">
                                      score {e.score} · {e.fresh_days}d
                                    </span>
                                  </div>
                                  <p className="font-mono text-[11px] text-muted-foreground/78 leading-relaxed">
                                    {e.snippet}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                          {t.policy.triggers.length > 0 && (
                            <div>
                              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                                Policy triggers fired
                              </div>
                              <div className="border border-border divide-y divide-border/40">
                                {t.policy.triggers.map((tr) => (
                                  <div
                                    key={tr.rule}
                                    className="flex items-center justify-between px-3 py-2 font-mono text-[11px]"
                                  >
                                    <span className="text-foreground/82">{tr.rule}</span>
                                    <span className="text-state-verify/78 uppercase tracking-wider text-[10px]">
                                      {tr.effect.replace(/_/g, " ")}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </>
                      )}

                      {evTab === "asset" && (
                        <>
                          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                            Asset schematic — {asset.zone}
                          </div>
                          <AssetCAD asset={asset} />
                          {(item.without_remora || item.with_remora) && (
                            <div className="space-y-2">
                              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                                Consequence comparison
                              </div>
                              <div className="border border-state-escalate/25 p-3">
                                <div className="font-mono text-[10px] uppercase tracking-wider text-state-escalate/55 mb-1.5">
                                  Without REMORA
                                </div>
                                <div className="font-mono text-[11px] text-muted-foreground/75 leading-relaxed">
                                  {item.without_remora}
                                </div>
                              </div>
                              <div className="border border-state-accept/25 p-3">
                                <div className="font-mono text-[10px] uppercase tracking-wider text-state-accept/55 mb-1.5">
                                  With REMORA
                                </div>
                                <div className="font-mono text-[11px] text-muted-foreground/75 leading-relaxed">
                                  {item.with_remora}
                                </div>
                              </div>
                            </div>
                          )}
                        </>
                      )}

                      {evTab === "timeline" && (
                        <div>
                          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-4">
                            Decision history
                          </div>
                          <div className="relative pl-5">
                            <div className="absolute left-1.5 top-0 bottom-0 w-px bg-border/50" />
                            {timeline.map((tl, i) => (
                              <div key={i} className="relative flex gap-3 pb-5 last:pb-0">
                                <div
                                  className={cn(
                                    "absolute left-[-14px] top-0.5 h-3 w-3 rounded-full border-2 bg-background",
                                    tl.type === "block"
                                      ? "border-state-escalate"
                                      : tl.type === "warn"
                                        ? "border-state-verify"
                                        : "border-border/60",
                                  )}
                                />
                                <div className="min-w-0 space-y-0.5">
                                  <div className="font-mono text-[10px] text-muted-foreground/55 tabular-nums">
                                    {tl.date}
                                  </div>
                                  <div
                                    className={cn(
                                      "font-mono text-[11px] leading-relaxed",
                                      tl.type === "block"
                                        ? "text-state-escalate/80 font-medium"
                                        : tl.type === "warn"
                                          ? "text-state-verify/78"
                                          : "text-foreground/72",
                                    )}
                                  >
                                    {tl.event}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {evTab === "oracles" && (
                        <div className="space-y-3">
                          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
                            Oracle votes — {t.oracles.length} models queried in parallel
                          </div>
                          <div className="border border-border">
                            <div className="grid grid-cols-4 border-b border-border bg-muted/8">
                              {["Model", "Vote", "Confidence", "Latency"].map((h) => (
                                <div
                                  key={h}
                                  className="px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60"
                                >
                                  {h}
                                </div>
                              ))}
                            </div>
                            {(() => {
                              const counts = new Map<string, number>();
                              for (const v of t.oracles)
                                counts.set(v.answer, (counts.get(v.answer) ?? 0) + 1);
                              const dominant = [...counts.entries()].sort(
                                (a, b) => b[1] - a[1],
                              )[0]?.[0];
                              return t.oracles.map((v) => {
                                const isMaj =
                                  v.answer === dominant &&
                                  (counts.get(dominant ?? "") ?? 0) / t.oracles.length > 0.5;
                                const voteWord = v.answer.split(" ")[0].toUpperCase().slice(0, 10);
                                return (
                                  <div
                                    key={v.oracle}
                                    className={cn(
                                      "grid grid-cols-4 border-b border-border/40 last:border-0 items-center",
                                      isMaj && "bg-muted/5",
                                    )}
                                  >
                                    <div className="px-3 py-2.5 flex items-center gap-2">
                                      <span
                                        className={cn(
                                          "h-2 w-2 rounded-full shrink-0",
                                          FAMILY_DOT[v.family] ?? "bg-border",
                                        )}
                                      />
                                      <span className="font-mono text-[11px] text-foreground/80 truncate">
                                        {v.oracle}
                                      </span>
                                    </div>
                                    <div className="px-3 py-2.5">
                                      <span
                                        className={cn(
                                          "font-mono text-[11px] uppercase tracking-wider",
                                          voteWord === "ESCALATE"
                                            ? "text-state-escalate/80"
                                            : voteWord === "ACCEPT"
                                              ? "text-state-accept/80"
                                              : voteWord === "VERIFY"
                                                ? "text-state-verify/80"
                                                : "text-muted-foreground/72",
                                        )}
                                      >
                                        {voteWord}
                                      </span>
                                    </div>
                                    <div className="px-3 py-2.5 flex items-center gap-2">
                                      <div className="flex-1 h-1 bg-border/25 overflow-hidden">
                                        <div
                                          className="h-full bg-state-verify/50"
                                          style={{ width: `${v.confidence * 100}%` }}
                                        />
                                      </div>
                                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground/72 shrink-0">
                                        {(v.confidence * 100).toFixed(0)}%
                                      </span>
                                    </div>
                                    <div className="px-3 py-2.5 font-mono text-[11px] text-muted-foreground/58 tabular-nums">
                                      {v.latency_ms}ms
                                    </div>
                                  </div>
                                );
                              });
                            })()}
                          </div>
                          <div className="font-mono text-[11px] text-muted-foreground/62 leading-relaxed border-l-2 border-signal/30 pl-3">
                            Agreement {oracleAgreement}% · dissensus D={t.thermo.D.toFixed(3)} ·
                            phase{" "}
                            <span className={phaseText(t.thermo.phase)}>{t.thermo.phase}</span>
                          </div>
                        </div>
                      )}

                      {evTab === "history" && (
                        <div className="space-y-4">
                          <div>
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                              Similar case history
                            </div>
                            <div className="grid grid-cols-4 gap-2">
                              {[
                                ["Cases", history.count],
                                ["Approved", history.approved],
                                ["Rejected", history.rejected],
                                ["Follow-up", history.follow_up],
                              ].map(([label, value]) => (
                                <div
                                  key={label}
                                  className="border border-border/45 p-3 text-center"
                                >
                                  <div className="font-mono text-lg text-foreground/82 tabular-nums">
                                    {value}
                                  </div>
                                  <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/55">
                                    {label}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div>
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                              Recurring blockers
                            </div>
                            <div className="border border-border divide-y divide-border/40">
                              {history.blockers.map((blocker) => (
                                <div
                                  key={blocker}
                                  className="px-3 py-2 font-mono text-[11px] text-foreground/78"
                                >
                                  {blocker}
                                </div>
                              ))}
                            </div>
                          </div>

                          <div>
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
                              Nearest decisions
                            </div>
                            <div className="border border-border divide-y divide-border/40">
                              {history.cases.map((c) => (
                                <div key={c.id} className="px-3 py-2.5 space-y-1">
                                  <div className="flex items-center gap-2">
                                    <span className="font-mono text-[11px] text-foreground/82">
                                      {c.id}
                                    </span>
                                    <span className="font-mono text-[10px] text-muted-foreground/58 tabular-nums">
                                      similarity {(c.similarity * 100).toFixed(0)}%
                                    </span>
                                    <span className="ml-auto font-mono text-[10px] uppercase tracking-wider text-state-verify/75">
                                      {c.human_decision}
                                    </span>
                                  </div>
                                  <p className="font-mono text-[11px] text-muted-foreground/72 leading-relaxed">
                                    {c.outcome}
                                  </p>
                                  <p className="font-mono text-[10px] text-muted-foreground/55 leading-relaxed">
                                    Reason: {c.reason}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="border border-state-verify/30 bg-state-verify/5 p-3">
                            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-state-verify/75 mb-1.5">
                              Policy learning candidate
                            </div>
                            <p className="font-mono text-[11px] text-foreground/78 leading-relaxed">
                              {policyLearning.recommendation}
                            </p>
                            <p className="mt-2 font-mono text-[10px] text-muted-foreground/58">
                              Requires policy-owner approval. History informs the proposal; it never
                              overrides active policy.
                            </p>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Footer: Decision buttons */}
            <div className="shrink-0 border-t border-border px-6 py-3.5 flex items-center gap-2.5 flex-wrap">
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/55 mr-1">
                Your decision
              </span>
              <button
                onClick={() => decide("rejected")}
                className="font-mono text-[11px] uppercase tracking-[0.10em] border-2 border-state-escalate/45 text-state-escalate bg-state-escalate/4 hover:bg-state-escalate/8 transition-colors px-5 py-2"
              >
                Reject autonomous action
              </button>
              <button
                onClick={() => setView("followup_form")}
                className={cn(
                  "font-mono text-[11px] uppercase tracking-[0.10em] border transition-colors px-5 py-2",
                  view === "followup_form"
                    ? "border-state-verify/55 text-state-verify bg-state-verify/8"
                    : "border-state-verify/40 text-state-verify hover:bg-state-verify/6",
                )}
              >
                Request site verification
              </button>
              <button
                onClick={() => decide("escalated")}
                className="font-mono text-[11px] uppercase tracking-[0.10em] border border-border text-muted-foreground/78 hover:border-foreground/30 hover:text-foreground/88 transition-colors px-5 py-2"
              >
                Escalate to SME
              </button>
              <div className="flex-1" />
              <button
                disabled={isCritical}
                onClick={() => decide("approved")}
                title={
                  isCritical
                    ? "Cannot approve critical-risk actions without SME sign-off"
                    : undefined
                }
                className={cn(
                  "font-mono text-[11px] uppercase tracking-[0.10em] border px-5 py-2 transition-colors",
                  isCritical
                    ? "border-border/30 text-muted-foreground/32 cursor-not-allowed"
                    : "border-state-accept/40 text-state-accept hover:bg-state-accept/8",
                )}
              >
                {isCritical ? "Approve — disabled (critical)" : "Approve with conditions"}
              </button>
              <div className="font-mono text-[10px] text-muted-foreground/45 ml-1">
                audit {auditHash}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export const ApprovalModal = React.memo(ApprovalModalRaw);
