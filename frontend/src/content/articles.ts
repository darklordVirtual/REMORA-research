// SEO content library for REMORA. Each article is long-form, search-optimised,
// and grounded in the research — every number keeps its caveat (CLAUDE.md). Add
// new articles by appending to ARTICLES; the /articles index and /articles/$slug
// route render them automatically.

export type Block =
  | { t: "p"; text: string }
  | { t: "h2"; text: string }
  | { t: "h3"; text: string }
  | { t: "ul"; items: string[] }
  | { t: "quote"; text: string }
  | { t: "callout"; text: string };

export interface Article {
  slug: string;
  title: string;
  /** <=160 chars — used verbatim as the meta description. */
  description: string;
  /** Short dek shown under the title on the page and in the index. */
  dek: string;
  published: string; // ISO date
  updated?: string;
  readingMinutes: number;
  keywords: string[];
  /** Tag chips shown in the UI. */
  tags: string[];
  body: Block[];
}

const SITE = "https://remora.razorsharp.workers.dev";
export const ARTICLES_BASE_URL = `${SITE}/articles`;
export const PAPER_PDF =
  "https://remora-agent-control.razorsharp.workers.dev/papers/remora_paper.pdf";
export const GITHUB = "https://github.com/darklordVirtual/REMORA";

export const ARTICLES: Article[] = [
  {
    slug: "why-ai-agents-need-an-assurance-layer",
    title: "Why AI Agents Need an Assurance Layer, Not a Better Model",
    description:
      "Tool-calling AI agents take irreversible actions. Alignment and majority vote can't stop a confident, wrong consensus. The missing piece is an assurance layer.",
    dek: "Alignment makes models safer to talk to. It does nothing to decide whether a specific proposed action should execute. That is a different problem — and it needs a different layer.",
    published: "2026-06-11",
    readingMinutes: 7,
    keywords: [
      "AI agent safety",
      "agentic AI governance",
      "AI assurance layer",
      "tool-calling agents",
      "policy-as-code",
      "human-in-the-loop AI",
      "LLM governance",
    ],
    tags: ["Governed autonomy", "Architecture"],
    body: [
      {
        t: "p",
        text: "An AI agent that can only write text can, at worst, be wrong. An AI agent that can call tools can drop a database, wire a payment, or withdraw a network route. The failure mode changes from embarrassing to irreversible — and the safeguards the industry built for chat do not transfer.",
      },
      {
        t: "p",
        text: "RLHF alignment, system prompts, and content classifiers are semantic filters applied at training or prompt time. They make a model safer to converse with. None of them evaluate a specific proposed action against a specific operational context, evidence base, and regulatory policy at the moment of execution. That is the gap REMORA addresses.",
      },
      { t: "h2", text: "Majority vote is not a safety mechanism" },
      {
        t: "p",
        text: "The intuitive fix is to ask several models and take the majority. More votes do improve answer accuracy. But a vote cannot block a confident, wrong consensus: if three models agree to do the wrong thing, the vote simply rubber-stamps it. Worse, the cases where models agree most strongly are not always the cases where they are most correct.",
      },
      {
        t: "callout",
        text: "The need is not a better oracle. It is a system that asks whether the conditions for autonomous action are actually met — and can say no regardless of the vote.",
      },
      { t: "h2", text: "What an assurance layer does" },
      {
        t: "p",
        text: "REMORA sits between an agent's proposed action and its execution. For every action it produces one of four governed outcomes:",
      },
      {
        t: "ul",
        items: [
          "ACCEPT — assurance conditions are met; the action may proceed autonomously.",
          "VERIFY — plausible, but validation is required before execution.",
          "ABSTAIN — uncertainty is too high to decide; the action is held.",
          "ESCALATE — a human reviews it, with the specific evidence required.",
        ],
      },
      {
        t: "p",
        text: "Crucially, ACCEPT does not mean the action is correct. It means the conditions that justify executing it without a human are verifiably present. ABSTAIN does not mean the action is wrong; it means the conditions for deciding are not present. The layer governs execution permission, not truth.",
      },
      { t: "h2", text: "Policy overrides consensus" },
      {
        t: "p",
        text: "REMORA evaluates a set of hard policy blocks before any routing logic runs. If a block fires — an adversarial pattern, a critical-risk action in an unstable regime, a missing evidence requirement — the action is escalated regardless of how confident the model consensus was. A confident, wrong majority cannot push an unsafe action through. In an adversarial 700-task tool-call benchmark, this took unsafe execution from 10–20% (across baselines) to 0% (Wilson 95% confidence interval [0.00%, 0.55%]); the policy hard-blocks accounted for the entire reduction.",
      },
      {
        t: "p",
        text: "That last clause matters: a thermodynamic-style uncertainty gate alone left 10% of unsafe actions getting through. It is the policy layer, not the uncertainty signal, that closes the gap. Uncertainty routing tells you where to look; policy decides what cannot run.",
      },
      { t: "h2", text: "Auditable by construction" },
      {
        t: "p",
        text: "Every decision emits an immutable envelope and is hash-chained: each record's hash includes the previous record's, so any later modification breaks the chain. This is tamper-evident, not tamper-proof — preventing tampering requires external append-only (WORM) storage as a deployment dependency. We say so explicitly, because a governance system that overstates its guarantees is worse than one that states them precisely.",
      },
      { t: "h2", text: "The honest scope" },
      {
        t: "p",
        text: "REMORA is a research-grade reference architecture, not a certified product. Evidence retrieval is currently a proxy; thresholds are uncalibrated for any specific production environment; the benchmarks have documented composition biases. The project publishes its negative results alongside its positive ones — because the audience that matters checks.",
      },
      {
        t: "quote",
        text: "Governed autonomy requires explicit routing of uncertainty — not suppression of it.",
      },
      {
        t: "p",
        text: "If you are deploying agents that act, the question is not whether your model is aligned. It is whether you can decide, defensibly and on the record, which of its actions are allowed to run. That decision is what an assurance layer is for.",
      },
    ],
  },
  {
    slug: "the-trust-inversion-in-ai-uncertainty",
    title: "The Trust Inversion: When Your Most Confident AI Predictions Are the Most Wrong",
    description:
      "In the hardest cases, an AI system's confidence can anti-correlate with correctness. Here is the measured effect — and how to route around it instead of trusting it.",
    dek: "A confidence score is only useful where it tracks correctness. We found a regime where it does the opposite — and the safe move is to invert the selection rule, not to trust the number.",
    published: "2026-06-11",
    readingMinutes: 6,
    keywords: [
      "AI calibration",
      "model confidence",
      "selective prediction",
      "uncertainty quantification",
      "conformal prediction",
      "trust scoring",
      "LLM reliability",
    ],
    tags: ["Research finding", "Calibration"],
    body: [
      {
        t: "p",
        text: "Most selective-prediction systems rest on one assumption: higher confidence means more likely correct, so you accept the high-confidence answers and abstain on the rest. For much of the input space that holds. In the hardest cases, we measured it breaking — and breaking in a specific, exploitable way.",
      },
      { t: "h2", text: "The measurement" },
      {
        t: "p",
        text: "REMORA classifies each decision into a phase based on the structure of model disagreement. In the 'critical' phase — where consensus sits near a boundary — the trust score anti-correlated with correctness on a set of real-oracle items:",
      },
      {
        t: "ul",
        items: [
          "Low-trust critical items (trust < 0.10): 71.4% correct (N = 21).",
          "High-trust critical items (trust ≥ 0.10): 27.3% correct (N = 11).",
        ],
      },
      {
        t: "p",
        text: "Trusting the confident answers in this regime would have been worse than a coin flip. And a standard conformal calibration aimed at a 5% risk target collapsed here — 100% observed risk, coverage falling to zero — because the assumption that calibration and test data are exchangeable is violated across the phase boundary.",
      },
      {
        t: "callout",
        text: "These are small samples (N = 32 real-oracle critical items total). The effect is reported as a directional finding with its sample size attached, not a precise constant — and it is published as a negative result, not buried.",
      },
      { t: "h2", text: "Why this happens" },
      {
        t: "p",
        text: "In the critical phase, strong agreement is a sign of correlated error — a shared prior, a shared training blind spot, a plausible-but-wrong framing that all models latch onto — rather than of independent convergence on truth. The confidence is real; what it is confident about is the consensus, not the answer. A safety system that reads that confidence at face value is most certain exactly when it should be most cautious.",
      },
      { t: "h2", text: "Route around it, don't trust it" },
      {
        t: "p",
        text: "The wrong response is to try to 'fix' the model into being well-calibrated everywhere. The right response is to treat the inversion as a selection-criterion reversal. Where the data say confidence is anti-informative, REMORA inverts the score for critical-phase items, calibrates the threshold on the inverted score, and hard-rejects anything above the groupthink boundary regardless of the calibration result.",
      },
      {
        t: "p",
        text: "Combining the ordered-phase items with the inverted low-trust critical items extends coverage to 22.1% at 85.0% accuracy (Wilson CI [77.5%, 90.3%]) — a coverage gain bought without lowering the safety floor, in precisely the regime where naive trust-based routing produces zero usable coverage.",
      },
      { t: "h2", text: "The general lesson" },
      {
        t: "quote",
        text: "A safety system's job is not to be confident. It is to know when its confidence is worthless — and route around it.",
      },
      {
        t: "p",
        text: "Calibration is not a global property you can assume. It is a regime-dependent one you have to measure. When you find a regime where confidence betrays you, the honest engineering move is to document the betrayal and design a selection rule that survives it — not to paper over it with a number that looks reassuring on a dashboard.",
      },
    ],
  },
];

export function getArticle(slug: string): Article | undefined {
  return ARTICLES.find((a) => a.slug === slug);
}
