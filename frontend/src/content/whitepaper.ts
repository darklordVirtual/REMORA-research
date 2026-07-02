export const META = {
  name: "REMORA",
  version: "v0.9.0",
  repoHead: "current main branch",
  preparedFor: "Stian Skogbrott / Luftfiber AS",
  tagline: "A Reference Architecture for Governed Agentic AI",
  thesis:
    "REMORA is a governance control plane for agentic AI. It decides when probabilistic model output is reliable enough to answer, when evidence must be consulted, when action must be blocked, and when a human must approve.",
};

export const DECISIONS = [
  {
    state: "ACCEPT",
    token: "state-accept",
    meaning: "Consensus, low uncertainty, no policy violation. Output is released.",
  },
  {
    state: "VERIFY",
    token: "state-verify",
    meaning: "Evidence route is consulted before release. RAG or external verifier.",
  },
  {
    state: "ABSTAIN",
    token: "state-abstain",
    meaning: "Uncertainty or dissensus too high. The system declines to answer.",
  },
  {
    state: "ESCALATE",
    token: "state-escalate",
    meaning: "Policy gate or risk threshold breached. A human approver is required.",
  },
] as const;

export const PILLARS = [
  {
    title: "Selective reliability",
    body: "Treat each model output as a proposal. Release only when consensus, calibration and evidence align.",
  },
  {
    title: "Safe tool execution",
    body: "PreToolUse hooks and OPA-style policy gates block unsafe actions before they reach the runtime.",
  },
  {
    title: "Auditable decisions",
    body: "Every ACCEPT, VERIFY, ABSTAIN or ESCALATE is written to a DecisionEnvelope carrying a SHA-256 tamper-evident hash chain (tamper-evident, not tamper-proof, without external WORM storage).",
  },
];

export const CAPABILITIES = [
  { name: "FastGate", role: "Fast confidence gate", status: "Integrated" },
  { name: "OracleDiversityTracker", role: "Independence of model pool", status: "Integrated" },
  { name: "PlattScaler", role: "Calibrated probabilities", status: "v0.6.0 quality lift" },
  {
    name: "DomainCoverageOptimizer",
    role: "Routing across domains",
    status: "v0.6.0 quality lift",
  },
  { name: "PolicyGate", role: "OPA / rules-based action gate", status: "Integrated" },
  { name: "PreToolUse Hook", role: "Block unsafe tool calls", status: "Integrated" },
  { name: "Audit chain", role: "SHA-256 hash-chain DecisionEnvelope", status: "Integrated" },
];

export const QA_BENCH = {
  caption: "Full-coverage QA accuracy. REMORA is not positioned as a raw accuracy maximizer.",
  cols: ["Category", "N = 302", "N = 544 (cached)"],
  rows: [
    ["Single model", "57.0", "8.8"],
    ["Naive ensemble", "61.4", "12.3"],
    ["REMORA (governed)", "54.2", "9.1"],
  ],
};

export const TOOL_BENCH = {
  caption: "Tool-call safety v2. Full policy gate dominates benchmark-scoped safety.",
  cols: ["Configuration", "Unsafe execution", "Decision accuracy", "Mean utility"],
  rows: [
    ["Single-model heuristic", "20.0%", "0.20", "-0.25"],
    ["Majority-vote heuristic", "10.0%", "0.30", "0.00"],
    ["REMORA full gate", "0.0%", "0.90", "0.62"],
  ],
};

export const THREATS = [
  {
    threat: "False consensus",
    example: "Multiple models repeat the same wrong claim.",
    control: "Diversity tracking and evidence route.",
    residual: "Correlated training data can still bias the pool.",
  },
  {
    threat: "Prompt injection",
    example: "Tool output contains adversarial instructions.",
    control: "PreToolUse hook re-evaluates policy on tool input.",
    residual: "Novel injection patterns may bypass static rules.",
  },
  {
    threat: "Compromised model",
    example: "An oracle model is silently swapped or fine-tuned.",
    control: "Audit graph records provenance and version hash.",
    residual: "REMORA cannot prove a model is benign by itself.",
  },
  {
    threat: "Policy drift",
    example: "Rules are loosened without review.",
    control: "Signed policy bundles and change audit.",
    residual: "Out-of-band changes to the gate runtime.",
  },
];

export const ROADMAP = [
  "Claim-to-test CI: every published claim mapped to a runnable test.",
  "External holdout benchmark with independent ground truth.",
  "Runtime integration with a reference MCP tool host.",
  "Control-room follow-up workflow: site verification, evidence return, re-review and audit envelopes.",
  "Red-team corpus for prompt injection and policy bypass.",
  "Governance alignment to NIST AI RMF Govern / Map / Measure / Manage.",
  "Flagship demo: governed infrastructure change on production-like systems.",
];

export const CITATIONS = [
  { id: "S1", label: "paper/whitepaper.md — current technical framing." },
  {
    id: "S2",
    label:
      "Repository quality gates — Ruff, claim consistency, result snapshot, pytest, frontend lint and frontend build.",
  },
  { id: "S3", label: "Cascade module — Oracle pool and canonicalization." },
  { id: "S6", label: "OracleDiversityTracker — rolling pairwise agreement." },
  { id: "S12", label: "Audit envelope — SHA-256 hash-chain DecisionEnvelope." },
  {
    id: "S14",
    label: "Control Room GUI — deterministic review-loop demo with follow-up request envelope.",
  },
  { id: "S13", label: "docs/thermodynamics/claim_ledger.yaml — claim status classes." },
  { id: "E1", label: "NIST AI Risk Management Framework — Govern / Map / Measure / Manage." },
];
