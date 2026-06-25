import { cn } from "@/lib/utils";
import type {
  EscalationItem,
  FollowUpForm,
  FieldResponse,
  CaseHistory,
  PolicyLearningSuggestion,
} from "../types";
import { RISK_BADGE } from "../styles";
import { REQUEST_TYPES } from "../data";
import { requestTypeLabel } from "../derivation";

export function FollowUpRequestPanel({
  item,
  form,
  onChange,
  submitted,
  fieldResponse,
  history,
  policyLearning,
  onBack,
  onCreate,
  onMarkReady,
  onExport,
}: {
  item: EscalationItem;
  form: FollowUpForm;
  onChange: (next: FollowUpForm) => void;
  submitted: boolean;
  fieldResponse: FieldResponse | null;
  history: CaseHistory;
  policyLearning: PolicyLearningSuggestion;
  onBack: () => void;
  onCreate: () => void;
  onMarkReady: () => void;
  onExport: () => void;
}) {
  const highNeed = history.rejected + history.follow_up;
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-state-verify/75">
            Follow-up request
          </div>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground/72 leading-relaxed">
            REMORA cannot safely approve or reject this action from the current evidence package.
            Create a controlled site-verification request, then re-run the assessment when field
            evidence arrives.
          </p>
        </div>
        <span
          className={cn(
            "font-mono text-[10px] uppercase tracking-wider border px-2 py-1",
            RISK_BADGE[item.risk],
          )}
        >
          {item.risk} risk
        </span>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="border border-border/50 p-3 space-y-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
            Reason
          </div>
          {Object.entries(form.reasons).map(([reason, checked]) => (
            <label
              key={reason}
              className="flex items-start gap-2 font-mono text-[11px] text-foreground/78 leading-relaxed"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) =>
                  onChange({
                    ...form,
                    reasons: { ...form.reasons, [reason]: e.target.checked },
                  })
                }
                className="mt-0.5 accent-current"
              />
              <span>{reason}</span>
            </label>
          ))}
        </div>

        <div className="border border-border/50 p-3 space-y-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
              Request type
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {REQUEST_TYPES.map((type) => (
                <button
                  key={type.value}
                  onClick={() => onChange({ ...form, requestType: type.value })}
                  className={cn(
                    "font-mono text-[10px] uppercase tracking-wider border px-2 py-1.5 text-left transition-colors",
                    form.requestType === type.value
                      ? "border-state-verify/55 text-state-verify bg-state-verify/8"
                      : "border-border/45 text-muted-foreground/68 hover:text-foreground/82",
                  )}
                >
                  {type.label}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <label className="space-y-1">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/58">
                Priority
              </span>
              <select
                value={form.priority}
                onChange={(e) => onChange({ ...form, priority: e.target.value })}
                className="w-full bg-muted/10 border border-border/50 px-2 py-1.5 font-mono text-[11px] text-foreground/80"
              >
                {["Critical", "High", "Medium", "Low"].map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 col-span-2">
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/58">
                Assign to
              </span>
              <input
                value={form.assignTo}
                onChange={(e) => onChange({ ...form, assignTo: e.target.value })}
                className="w-full bg-muted/10 border border-border/50 px-2 py-1.5 font-mono text-[11px] text-foreground/80"
              />
            </label>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-[1fr_0.9fr]">
        <div className="border border-border/50 p-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62 mb-2">
            Required evidence
          </div>
          <ul className="space-y-1.5">
            {form.evidence.map((evidence) => (
              <li
                key={evidence}
                className="flex items-start gap-2 font-mono text-[11px] text-foreground/78 leading-relaxed"
              >
                <span className="mt-0.5 text-state-verify">□</span>
                <span>{evidence}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 font-mono text-[11px] text-muted-foreground/65">
            Due: <span className="text-foreground/80">{form.sla}</span>
          </div>
        </div>

        <div className="border border-border/50 p-3 space-y-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/62">
            Similar-case memory
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="border border-border/40 p-2">
              <div className="font-mono text-sm text-state-escalate tabular-nums">
                {history.rejected}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/55">
                Rejected
              </div>
            </div>
            <div className="border border-border/40 p-2">
              <div className="font-mono text-sm text-state-verify tabular-nums">
                {history.follow_up}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/55">
                Follow-up
              </div>
            </div>
            <div className="border border-border/40 p-2">
              <div className="font-mono text-sm text-muted-foreground/72 tabular-nums">
                {history.autonomous}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground/55">
                Autonomous
              </div>
            </div>
          </div>
          <p className="font-mono text-[11px] text-muted-foreground/70 leading-relaxed">
            {highNeed} of {history.count} similar cases required rejection or follow-up. History may
            recommend, but policy decides and humans approve rule changes.
          </p>
        </div>
      </div>

      <div className="border border-state-verify/30 bg-state-verify/5 p-3 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-state-verify/75">
            Policy learning
          </div>
          <span className="font-mono text-[10px] text-muted-foreground/60 tabular-nums">
            confidence {(policyLearning.confidence * 100).toFixed(0)}%
          </span>
        </div>
        <p className="font-mono text-[11px] text-foreground/78 leading-relaxed">
          Suggested rule: {policyLearning.recommendation}
        </p>
        <p className="font-mono text-[10px] text-muted-foreground/58 leading-relaxed">
          Candidate only. REMORA can draft a policy proposal; a policy owner must approve it before
          enforcement changes.
        </p>
      </div>

      {submitted && (
        <div className="border border-state-verify/35 p-3 space-y-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-state-verify/75">
            Work order created
          </div>
          <div className="grid gap-1.5 font-mono text-[11px] text-muted-foreground/72">
            <div>
              Request type:{" "}
              <span className="text-foreground/80">{requestTypeLabel(form.requestType)}</span>
            </div>
            <div>
              Assigned to: <span className="text-foreground/80">{form.assignTo}</span>
            </div>
            <div>
              Status: <span className="text-state-verify">SITE_VERIFICATION_PENDING</span>
            </div>
          </div>
        </div>
      )}

      {fieldResponse && (
        <div className="border border-signal/35 bg-signal/5 p-3 space-y-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-signal/80">
            Field response received
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px]">
            <span className="text-muted-foreground/62">Technician</span>
            <span className="text-foreground/82">{fieldResponse.technician}</span>
            <span className="text-muted-foreground/62">Time</span>
            <span className="text-foreground/82">{fieldResponse.time}</span>
            <span className="text-muted-foreground/62">Location verified</span>
            <span className="text-foreground/82">
              {fieldResponse.locationVerified ? "Yes" : "No"}
            </span>
            <span className="text-muted-foreground/62">Photos attached</span>
            <span className="text-foreground/82">{fieldResponse.photosAttached}</span>
            <span className="text-muted-foreground/62">Inspection completed</span>
            <span className="text-foreground/82">
              {fieldResponse.inspectionCompleted ? "Yes" : "No"}
            </span>
          </div>
          <p className="font-mono text-[11px] text-foreground/78 leading-relaxed">
            Recommendation: {fieldResponse.recommendation}
          </p>
        </div>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <button
          onClick={onBack}
          className="font-mono text-[11px] uppercase tracking-[0.10em] border border-border text-muted-foreground/78 hover:border-foreground/30 hover:text-foreground/88 transition-colors px-4 py-2"
        >
          Back to evidence
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={onExport}
            className="font-mono text-[11px] uppercase tracking-[0.10em] border border-border/55 text-muted-foreground/72 hover:text-foreground/85 transition-colors px-4 py-2"
          >
            Export envelope
          </button>
          {fieldResponse ? (
            <button
              onClick={onMarkReady}
              className="font-mono text-[11px] uppercase tracking-[0.10em] border-2 border-signal/45 text-signal bg-signal/5 hover:bg-signal/10 transition-colors px-5 py-2"
            >
              Re-run REMORA assessment
            </button>
          ) : (
            <button
              disabled={submitted}
              onClick={onCreate}
              className={cn(
                "font-mono text-[11px] uppercase tracking-[0.10em] border-2 px-5 py-2 transition-colors",
                submitted
                  ? "border-border/30 text-muted-foreground/35 cursor-wait"
                  : "border-state-verify/45 text-state-verify bg-state-verify/5 hover:bg-state-verify/10",
              )}
            >
              {submitted ? "Awaiting field response" : "Create follow-up request"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
