import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: LandingPage,
});

// Proof points — every number is transcribed from paper/remora_paper.md with its
// caveat intact (CLAUDE.md: claims must match artifacts; keep the qualifiers).
const PROOF = [
  {
    stat: "0%",
    label: "unsafe execution",
    detail: "700 adversarial tool-call tasks · Wilson CI [0, 0.55%] · baselines 10–20%",
  },
  {
    stat: "88%",
    label: "selective accuracy, held-out",
    detail: "locked threshold, out-of-sample · Wilson CI [70.0%, 95.8%] · p = 1.45×10⁻⁵",
  },
  {
    stat: "99.9%",
    label: "ordered-phase conformal coverage",
    detail: "0 of 20 calibration seeds failed",
  },
  {
    stat: "SHA-256",
    label: "tamper-evident audit chain",
    detail: "every decision hash-linked to the last",
  },
];

const OUTCOMES = [
  { name: "ACCEPT", color: "state-accept", note: "assurance conditions met" },
  { name: "VERIFY", color: "state-verify", note: "validation required" },
  { name: "ABSTAIN", color: "state-abstain", note: "too uncertain to decide" },
  { name: "ESCALATE", color: "state-escalate", note: "human review" },
];

function LandingPage() {
  return (
    <div className="min-h-dvh flex flex-col bg-background relative">
      {/* Subtle background gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-background via-background to-muted/[0.15] pointer-events-none" />
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-signal/[0.04] blur-[120px] rounded-full pointer-events-none" />

      <header className="shrink-0 flex items-center justify-between px-8 py-5 border-b border-border/50 relative">
        <div className="flex items-center gap-3">
          <span className="font-serif text-2xl tracking-tight">REMORA</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground/70 border border-border/40 px-2 py-0.5">
            AI Assurance Layer
          </span>
        </div>
        <span className="hidden sm:inline font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
          Policy-as-code · Human-on-the-loop · Immutable Audit
        </span>
      </header>

      <main className="flex-1 flex items-center justify-center p-8 relative">
        <div className="max-w-4xl w-full py-10">
          {/* Hero */}
          <div className="text-center mb-10 animate-fade-in">
            <h1 className="font-serif text-4xl md:text-6xl tracking-tight leading-[1.08] mb-5">
              Stop unsafe AI actions
              <br />
              <span className="text-muted-foreground/50">before they execute</span>
            </h1>
            <p className="text-[14px] md:text-[15px] text-foreground/75 leading-relaxed max-w-2xl mx-auto">
              REMORA is an assurance layer for tool-calling AI agents. Before any action runs, it is
              gated to one of four outcomes — with multi-oracle consensus, policy-as-code that
              overrides a confident-but-wrong majority, and an immutable audit trail. Human
              authority at every safety threshold.
            </p>
          </div>

          {/* Four-outcome strip — instant visual explanation of the gate */}
          <div
            className="grid grid-cols-2 md:grid-cols-4 gap-2.5 mb-8 animate-fade-in"
            style={{ animationDelay: "0.05s" }}
          >
            {OUTCOMES.map((o) => (
              <div
                key={o.name}
                className="border border-border/50 px-3 py-3 flex flex-col gap-1"
                style={{ borderTopColor: `var(--${o.color})`, borderTopWidth: 2 }}
              >
                <span
                  className="font-mono text-[11px] font-semibold tracking-wider"
                  style={{ color: `var(--${o.color})` }}
                >
                  {o.name}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground/65 leading-tight">
                  {o.note}
                </span>
              </div>
            ))}
          </div>

          {/* Proof row — the headline results, above the fold */}
          <div
            className="grid grid-cols-2 md:grid-cols-4 gap-px bg-border/40 border border-border/40 mb-9 animate-fade-in"
            style={{ animationDelay: "0.1s" }}
          >
            {PROOF.map((p) => (
              <div key={p.label} className="bg-background px-4 py-4 flex flex-col gap-1">
                <span className="font-serif text-2xl md:text-3xl tracking-tight text-signal">
                  {p.stat}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-foreground/70">
                  {p.label}
                </span>
                <span className="font-mono text-[9.5px] text-muted-foreground/60 leading-snug mt-0.5">
                  {p.detail}
                </span>
              </div>
            ))}
          </div>

          {/* Primary CTAs */}
          <div
            className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 mb-8 animate-fade-in"
            style={{ animationDelay: "0.15s" }}
          >
            <Link
              to="/control-room"
              className="group border border-signal bg-signal/[0.08] hover:bg-signal/[0.16] transition-all px-6 py-3 text-center"
            >
              <span className="font-mono text-[13px] tracking-wide text-signal font-medium">
                🛡 Open the Control Room — watch a live decision →
              </span>
            </Link>
            <a
              href="https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf"
              target="_blank"
              rel="noreferrer"
              className="border border-foreground/30 hover:border-foreground/60 hover:bg-foreground/[0.03] transition-all px-5 py-3 text-center"
            >
              <span className="font-mono text-[13px] text-foreground font-medium">
                Read the paper (PDF)
              </span>
            </a>
            <a
              href="https://remora-agent-control.razorsharp.workers.dev/papers/REMORA_Enterprise_Whitepaper.pdf"
              target="_blank"
              rel="noreferrer"
              className="border border-foreground/30 hover:border-state-verify hover:bg-state-verify/[0.04] transition-all px-5 py-3 text-center"
            >
              <span className="font-mono text-[13px] text-foreground font-medium">
                Enterprise white paper (PDF)
              </span>
            </a>
            <a
              href="https://github.com/darklordVirtual/REMORA"
              target="_blank"
              rel="noreferrer"
              className="border border-foreground/30 hover:border-foreground/60 hover:bg-foreground/[0.03] transition-all px-5 py-3 text-center"
            >
              <span className="font-mono text-[13px] text-foreground font-medium">
                View on GitHub
              </span>
            </a>
          </div>

          {/* Secondary entry points */}
          <div
            className="grid sm:grid-cols-2 gap-3 animate-fade-in"
            style={{ animationDelay: "0.2s" }}
          >
            <Link
              to="/operations"
              className="group border border-border/50 p-5 hover:border-state-verify/40 hover:bg-state-verify/[0.02] transition-all flex items-center gap-4"
            >
              <span className="text-xl">⏱</span>
              <div className="flex-1">
                <div className="font-serif text-lg tracking-tight">Live Operations</div>
                <div className="font-mono text-[11px] text-muted-foreground/65">
                  Procedure-linked AI assurance · 4 agent proposals
                </div>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground/50 group-hover:text-state-verify/80">
                Enter →
              </span>
            </Link>
            <Link
              to="/aromer"
              className="group border border-border/50 p-5 hover:border-signal/40 hover:bg-signal/[0.02] transition-all flex items-center gap-4"
            >
              <div className="flex gap-1.5 shrink-0">
                <div className="w-3.5 h-3.5 rounded-full bg-emerald-500/80 ring-2 ring-emerald-400/30" />
                <div className="w-3.5 h-3.5 rounded-full bg-amber-400/40 ring-2 ring-amber-400/10" />
                <div className="w-3.5 h-3.5 rounded-full bg-red-500/30 ring-2 ring-red-400/10" />
              </div>
              <div className="flex-1">
                <div className="font-serif text-lg tracking-tight">AROMER Live Status</div>
                <div className="font-mono text-[11px] text-muted-foreground/65">
                  Real-time safety scorecard · the system that learns, running now
                </div>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground/50 group-hover:text-signal/80">
                View →
              </span>
            </Link>
          </div>

          {/* Flow line */}
          <div className="mt-9 text-center animate-fade-in" style={{ animationDelay: "0.25s" }}>
            <p className="font-mono text-[11px] text-muted-foreground/55">
              Agent proposes action → Multi-oracle consensus → Policy gate → One of four outcomes →
              Immutable audit · Human-on-the-loop
            </p>
          </div>
        </div>
      </main>

      <footer className="shrink-0 px-8 py-4 border-t border-border/30 text-center relative">
        <span className="font-mono text-[10px] text-muted-foreground/55">
          REMORA — AI Assurance Layer · Policy-as-code · Human-on-the-loop · Immutable Audit ·
          research-grade, honestly scoped
        </span>
      </footer>
    </div>
  );
}
