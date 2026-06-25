import { useCallback, useEffect, useReducer, useRef } from "react";
import { simulate, type DecisionTrace, type Verdict } from "@/lib/remora-sim";
import { CR_SCENARIOS, LIVE_ALERT_POOL, PLATFORMS, INITIAL_KPI } from "../data";
import type {
  CRScenario,
  EscalationItem,
  ActivityBucket,
  LiveAlert,
  AutoHandled,
  ReviewStatus,
  SessionKPI,
} from "../types";

interface State {
  active: CRScenario;
  running: boolean;
  trace: DecisionTrace | null;
  kpi: SessionKPI;
  sector: string | null;
  escalations: EscalationItem[];
  approvalTarget: EscalationItem | null;
  liveAlerts: LiveAlert[];
  activityBuckets: ActivityBucket[];
  compareOpen: boolean;
  customQuery: string;
  activeQueryText: string;
  inboxHeight: number;
  inboxTab: "escalations" | "auto";
  autoHandled: AutoHandled[];
}

type Action =
  | { type: "START_RUN"; query: string; scenario?: CRScenario }
  | { type: "FINISH_RUN"; trace: DecisionTrace; scenario?: CRScenario }
  | { type: "SET_SECTOR"; sector: string | null }
  | { type: "SET_CUSTOM_QUERY"; value: string }
  | { type: "TOGGLE_COMPARE" }
  | { type: "SET_INBOX_TAB"; tab: "escalations" | "auto" }
  | { type: "SET_INBOX_HEIGHT"; height: number }
  | { type: "DISMISS_ESCALATION"; id: number }
  | { type: "DISMISS_ALL_ESCALATIONS" }
  | { type: "DECIDE_ESCALATION"; id: number; decision: ReviewStatus }
  | { type: "SET_APPROVAL_TARGET"; item: EscalationItem | null }
  | { type: "LIVE_TICK"; alert: LiveAlert; auto?: AutoHandled; escalation?: EscalationItem };

function getInitialKpi(): SessionKPI {
  try {
    const saved = localStorage.getItem("remora_session_kpi");
    if (saved) return { ...INITIAL_KPI, ...JSON.parse(saved) };
  } catch {
    /* ignore */
  }
  return { ...INITIAL_KPI };
}

function pushActivity(buckets: ActivityBucket[], verdict: Verdict): ActivityBucket[] {
  const bucketKey = Math.floor(Date.now() / 15000);
  const d = new Date(bucketKey * 15000);
  const label = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const isEsc = verdict === "ESCALATE";
  const last = buckets[buckets.length - 1];
  if (last && last.label === label) {
    return [
      ...buckets.slice(0, -1),
      { label, auto: last.auto + (isEsc ? 0 : 1), escalated: last.escalated + (isEsc ? 1 : 0) },
    ];
  }
  return [...buckets, { label, auto: isEsc ? 0 : 1, escalated: isEsc ? 1 : 0 }].slice(-22);
}

function updateKpi(kpi: SessionKPI, verdict: Verdict, steps: number, latency: number): SessionKPI {
  return {
    runs: kpi.runs + 1,
    accept: kpi.accept + (verdict === "ACCEPT" ? 1 : 0),
    verify: kpi.verify + (verdict === "VERIFY" ? 1 : 0),
    abstain: kpi.abstain + (verdict === "ABSTAIN" ? 1 : 0),
    escalate: kpi.escalate + (verdict === "ESCALATE" ? 1 : 0),
    unsafe_prevented: kpi.unsafe_prevented + (verdict !== "ACCEPT" ? 1 : 0),
    audit_entries: kpi.audit_entries + steps,
    total_ms: kpi.total_ms + latency,
  };
}

function makeEscalation(
  trace: DecisionTrace,
  sc: CRScenario | undefined,
  query: string,
  ts: string,
  id: number,
): EscalationItem {
  return {
    id,
    title: sc?.title ?? query.slice(0, 40) + (query.length > 40 ? "…" : ""),
    sector: sc?.sector ?? "Custom",
    icon: sc?.icon ?? "⚡",
    proposed_action: sc?.proposed_action ?? query.slice(0, 80),
    without_remora: sc?.without_remora,
    with_remora: sc?.with_remora,
    reason: trace.reason,
    risk: trace.intent.risk,
    trust: trace.thermo.trust,
    phase: trace.thermo.phase,
    ts,
    trace,
    status: "pending",
  };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "START_RUN": {
      const next: State = {
        ...state,
        active: action.scenario ?? state.active,
        activeQueryText: action.query,
        running: true,
        trace: null,
        compareOpen: false,
      };
      return next;
    }
    case "FINISH_RUN": {
      const { trace, scenario } = action;
      const now = new Date();
      const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      const next: State = {
        ...state,
        running: false,
        trace,
        kpi: updateKpi(state.kpi, trace.verdict, trace.steps.length, trace.total_latency_ms),
        activityBuckets: pushActivity(state.activityBuckets, trace.verdict),
      };
      if (trace.verdict === "ESCALATE") {
        next.escalations = [
          makeEscalation(trace, scenario, state.activeQueryText, ts, ++_seq),
          ...state.escalations,
        ].slice(0, 20);
      }
      return next;
    }
    case "SET_SECTOR":
      return { ...state, sector: action.sector };
    case "SET_CUSTOM_QUERY":
      return { ...state, customQuery: action.value };
    case "TOGGLE_COMPARE":
      return { ...state, compareOpen: !state.compareOpen };
    case "SET_INBOX_TAB":
      return { ...state, inboxTab: action.tab };
    case "SET_INBOX_HEIGHT":
      return { ...state, inboxHeight: action.height };
    case "DISMISS_ESCALATION":
      return { ...state, escalations: state.escalations.filter((e) => e.id !== action.id) };
    case "DISMISS_ALL_ESCALATIONS":
      return { ...state, escalations: [] };
    case "DECIDE_ESCALATION": {
      const { id, decision } = action;
      const updated = state.escalations.map((e) => (e.id === id ? { ...e, status: decision } : e));
      const target = state.approvalTarget;
      const newTarget = target && target.id === id ? { ...target, status: decision } : target;
      // Auto-close modal for terminal decisions
      const shouldClose =
        decision === "approved" || decision === "rejected" || decision === "closed";
      return {
        ...state,
        escalations: updated,
        approvalTarget: shouldClose && newTarget && newTarget.id === id ? null : newTarget,
      };
    }
    case "SET_APPROVAL_TARGET":
      return { ...state, approvalTarget: action.item };
    case "LIVE_TICK": {
      const { alert, auto, escalation } = action;
      const next: State = {
        ...state,
        liveAlerts: [alert, ...state.liveAlerts].slice(0, 60),
        activityBuckets: pushActivity(state.activityBuckets, alert.verdict),
        kpi: {
          runs: state.kpi.runs + 1,
          accept: state.kpi.accept + (alert.verdict === "ACCEPT" ? 1 : 0),
          verify: state.kpi.verify + (alert.verdict === "VERIFY" ? 1 : 0),
          abstain: state.kpi.abstain + (alert.verdict === "ABSTAIN" ? 1 : 0),
          escalate: state.kpi.escalate + (alert.verdict === "ESCALATE" ? 1 : 0),
          unsafe_prevented: state.kpi.unsafe_prevented + (alert.verdict !== "ACCEPT" ? 1 : 0),
          audit_entries: state.kpi.audit_entries + 6,
          total_ms: state.kpi.total_ms + 180 + Math.floor(Math.random() * 240),
        },
      };
      if (escalation) {
        next.escalations = [escalation, ...state.escalations].slice(0, 20);
      }
      if (auto) {
        next.autoHandled = [auto, ...state.autoHandled].slice(0, 60);
      }
      return next;
    }
    default:
      return state;
  }
}

let _seq = 0;
let _liveSeq = 1000;

export function useControlRoom() {
  const initialStateRef = useRef<State>({
    active: CR_SCENARIOS[0],
    running: false,
    trace: null,
    kpi: getInitialKpi(),
    sector: null,
    escalations: [],
    approvalTarget: null,
    liveAlerts: [],
    activityBuckets: [],
    compareOpen: false,
    customQuery: "",
    activeQueryText: "",
    inboxHeight: 220,
    inboxTab: "escalations",
    autoHandled: [],
  });

  const [state, dispatch] = useReducer(reducer, initialStateRef.current);

  // Persist KPI
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("remora_session_kpi", JSON.stringify(state.kpi));
    }
  }, [state.kpi]);

  // Run query
  const runQuery = useCallback(async (query: string, sc?: CRScenario) => {
    dispatch({ type: "START_RUN", query, scenario: sc });
    await new Promise<void>((r) => setTimeout(r, 420));
    const t = simulate(query, {
      scenarioId: sc?.id,
      bias: sc?.bias,
      risk: sc?.risk,
      domain: sc?.domain,
    });
    dispatch({ type: "FINISH_RUN", trace: t, scenario: sc });
  }, []);

  const runScenario = useCallback(
    (sc: CRScenario) => {
      if (!state.running) runQuery(sc.query, sc);
    },
    [state.running, runQuery],
  );

  const submitCustom = useCallback(() => {
    const q = state.customQuery.trim();
    if (!q || state.running) return;
    dispatch({ type: "SET_CUSTOM_QUERY", value: "" });
    runQuery(q);
  }, [state.customQuery, state.running, runQuery]);

  // Initial run
  useEffect(() => {
    runQuery(CR_SCENARIOS[0].query, CR_SCENARIOS[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Drag resize
  const isDragging = useRef(false);
  const dragStartY = useRef(0);
  const dragStartH = useRef(0);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = dragStartY.current - e.clientY;
      dispatch({
        type: "SET_INBOX_HEIGHT",
        height: Math.max(72, Math.min(520, dragStartH.current + delta)),
      });
    };
    const onUp = () => {
      isDragging.current = false;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Live feed timer
  useEffect(() => {
    let poolIdx = Math.floor(Math.random() * LIVE_ALERT_POOL.length);
    let platIdx = Math.floor(Math.random() * PLATFORMS.length);
    let timerId: ReturnType<typeof setTimeout>;

    function tick() {
      const template = LIVE_ALERT_POOL[poolIdx % LIVE_ALERT_POOL.length];
      const platform = PLATFORMS[platIdx % PLATFORMS.length];
      poolIdx++;
      platIdx++;
      const now = new Date();
      const ts = [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map((n) => String(n).padStart(2, "0"))
        .join(":");
      const alertId = ++_liveSeq;

      const alert: LiveAlert = {
        id: alertId,
        platform,
        title: template.title,
        verdict: template.verdict,
        risk: template.risk,
        ts,
      };

      let escalation: EscalationItem | undefined;
      let auto: AutoHandled | undefined;

      if (template.verdict === "ESCALATE") {
        const t = simulate(template.query, {
          bias: template.bias,
          risk: template.risk,
          domain: template.domain,
        });
        escalation = {
          id: alertId,
          title: template.title,
          sector: platform,
          icon: "⛽",
          proposed_action: template.proposed_action,
          reason: template.reason,
          risk: template.risk,
          trust: t.thermo.trust,
          phase: t.thermo.phase,
          ts,
          trace: t,
          status: "pending",
        };
      } else {
        auto = {
          id: alertId,
          platform,
          title: template.title,
          verdict: template.verdict as "ACCEPT" | "VERIFY",
          trust: 0.68 + Math.random() * 0.28,
          latency_ms: 160 + Math.floor(Math.random() * 260),
          ts,
        };
      }

      dispatch({ type: "LIVE_TICK", alert, escalation, auto });
      timerId = setTimeout(tick, 3000 + Math.random() * 3000);
    }

    timerId = setTimeout(tick, 2000);
    return () => clearTimeout(timerId);
  }, []);

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      isDragging.current = true;
      dragStartY.current = e.clientY;
      dragStartH.current = state.inboxHeight;
      e.preventDefault();
    },
    [state.inboxHeight],
  );

  return {
    state,
    dispatch,
    runScenario,
    submitCustom,
    onDragStart,
  };
}
