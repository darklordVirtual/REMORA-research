import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { callLLM, CF_FAST, CF_JUDGE, OR_FAST, OR_FREE, OR_SYNTH } from "./ai-gateway.server";

// ---------------------------------------------------------------------------
// Cost-control constants. We deliberately mix OpenRouter (free/cheap) and
// Cloudflare Workers AI (per-neuron billed Llama-3.x) so a full cascade stays
// well below 1¢. Token caps stay tight at every stage.
// ---------------------------------------------------------------------------

const ANSWER_TOKENS = 220;
const JUDGE_TOKENS = 60;
const CRITIQUE_TOKENS = 160;
const SYNTH_TOKENS = 260;

// ---------------------------------------------------------------------------
// Adversarial χ-gate — pure heuristics, runs against raw query before oracles.
// ---------------------------------------------------------------------------

const INJECTION_PATTERNS = [
  /ignore (all |any )?(previous|prior|above) (instructions|prompts|rules)/i,
  /(reveal|print|leak|exfiltrate|disclose)\s+(the\s+)?(system|developer|hidden)\s+prompt/i,
  /you are (now |hereby )?(dan|developer mode|jailbroken|sudo)/i,
  /(send|post|upload|exfiltrate).*(https?:\/\/|api[_ ]?key|token|password|secret)/i,
  /act as (an? )?(unrestricted|uncensored|unfiltered)/i,
];
const TOXICITY_PATTERNS = [/(kill|murder|harm)\s+(myself|himself|herself|themselves)/i];

// Patterns indicating a model has no factual basis for an answer.
const EPISTEMIC_REFUSAL_PATTERNS = [
  /\b(cannot|can't|unable to|it'?s impossible to|not possible to)\s+(predict|forecast|know|determine|tell|provide|give)\b/i,
  /\b(no one|nobody)\s+(can|could|is able to)\b.*(predict|know|forecast)/i,
  /\bfuture\b.*(price|value|rate|cost|level)\b.*(cannot|can't|unknown|unpredictable|impossible)/i,
  /\b(predict|forecast|tell)\b.*\b(future|next month|next week|next year|tomorrow)\b.*\b(price|cost|rate|value)/i,
  /\b(outside|beyond)\b.*(knowledge|training|capabilities|ability)\b/i,
  /\b(don'?t|do not|cannot)\s+have (access to|knowledge of|information about)\s+(real.?time|live|current|future)/i,
  /\bspeculate\b.*(would be irresponsible|should not|cannot)/i,
];

export function detectEpistemicRefusal(text: string): boolean {
  return EPISTEMIC_REFUSAL_PATTERNS.some((re) => re.test(text));
}

// High-stakes domains where FastGate must NEVER short-circuit — always run
// the full ConsensusGate + VerifierGate pipeline.
const HIGH_STAKES_PATTERNS = [
  /\b(gdpr|ccpa|hipaa|pci.?dss|sox|ferpa|glba|sccs?|adequacy decision|data transfer)\b/i,
  /\b(article \d+|regulation \(eu\)|directive \d+|compliance|violat)\b/i,
  /\b(legal|illegal|lawful|unlawful|liable|liability|lawsuit|court|judge|attorney|lawyer)\b/i,
  /\b(medical|diagnosis|diagnose|treatment|prescription|medication|symptoms|disease|cancer|surgery)\b/i,
  /\b(financial advice|invest|portfolio|stock|bond|mortgage|loan|bankruptcy|tax advice)\b/i,
  /\b(safety.?critical|life.?critical|fail.?safe|hazard|injury|fatality|explosion|fire|emergency)\b/i,
  /\b(should (we|i|the company)|auto.?issue|work order|maintenance decision|approve|escalat)\b.*\b(risk|safety|offshore|critical)/i,
];

// Hedging phrases that indicate the model itself is uncertain — ACCEPT is wrong.
const HEDGING_PATTERNS = [
  /\b(likely|probably|arguably|generally|typically|usually|may|might|could|would)\b.*\bviolat/i,
  /\bdepend(s| on)\b.*(specific|circumstances|context|case|situation)/i,
  /\bhowever\b.*(final|determin|depend|specific|circumstances)/i,
  /\b(consult|seek).*(legal|lawyer|attorney|professional|expert|specialist)/i,
  /\bnot (a|an) (lawyer|attorney|legal|medical|financial|tax) (advice|professional|expert)/i,
  /\b(further|additional).*(analysis|assessment|review|evaluation|investigation)/i,
  /\b(unclear|ambiguous|debatable|contested|open question|gray area|nuanced)\b/i,
  /\b(this (is|remains|could be) (complex|complicated|nuanced|situation-specific))/i,
];

export function detectHighStakes(query: string): boolean {
  return HIGH_STAKES_PATTERNS.some((re) => re.test(query));
}

export function detectHedging(answer: string): boolean {
  return HEDGING_PATTERNS.some((re) => re.test(answer));
}

export function chiSusceptibility(text: string): number {
  let chi = 0.2;
  for (const re of INJECTION_PATTERNS) if (re.test(text)) chi += 0.45;
  for (const re of TOXICITY_PATTERNS) if (re.test(text)) chi += 0.35;
  const imperatives = (text.match(/\b(ignore|reveal|exfiltrate|bypass|disable|override)\b/gi) || [])
    .length;
  chi += Math.min(0.4, imperatives * 0.08);
  return Math.round(Math.min(2, chi) * 100) / 100;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function tokenizeWords(s: string): string[] {
  return s
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2);
}

function jaccard(a: string, b: string): number {
  const A = new Set(tokenizeWords(a));
  const B = new Set(tokenizeWords(b));
  if (A.size === 0 && B.size === 0) return 1;
  let inter = 0;
  for (const w of A) if (B.has(w)) inter++;
  return inter / (A.size + B.size - inter || 1);
}

function answerEntropy(answers: string[]): number {
  const counts = new Map<string, number>();
  let total = 0;
  for (const a of answers)
    for (const t of tokenizeWords(a)) {
      counts.set(t, (counts.get(t) ?? 0) + 1);
      total++;
    }
  if (total === 0) return 0;
  let H = 0;
  for (const c of counts.values()) {
    const p = c / total;
    H -= p * Math.log2(p);
  }
  return Math.round(Math.min(2, H / 6) * 1000) / 1000;
}

function dissensus(answers: string[]): number {
  if (answers.length < 2) return 0;
  let pairs = 0;
  let sumSim = 0;
  for (let i = 0; i < answers.length; i++) {
    for (let j = i + 1; j < answers.length; j++) {
      sumSim += jaccard(answers[i], answers[j]);
      pairs++;
    }
  }
  const avgSim = sumSim / pairs;
  return Math.round((1 - avgSim) * 1000) / 1000;
}

function extractConfidence(raw: string): {
  confidence: number;
  answer: string;
  epistemicRefusal: boolean;
  hedging: boolean;
} {
  const m =
    raw.match(/confidence\s*[:=]\s*([01](?:\.\d+)?)/i) ||
    raw.match(/"confidence"\s*:\s*([01](?:\.\d+)?)/i);
  const answer = raw.replace(/confidence\s*[:=]\s*[01](?:\.\d+)?/i, "").trim();
  const epistemicRefusal = detectEpistemicRefusal(answer);
  const hedging = detectHedging(answer);
  // Force very low confidence if the model explicitly refuses to answer.
  const confidence = epistemicRefusal
    ? 0.05
    : m
      ? Math.max(0, Math.min(1, parseFloat(m[1])))
      : 0.55;
  return { confidence, answer, epistemicRefusal, hedging };
}

// ---------------------------------------------------------------------------
// Stage 1 — FastGate (Cloudflare Workers AI · llama-3.2-3b)
// ---------------------------------------------------------------------------

export const stageFastGate = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) => z.object({ query: z.string().min(1).max(2000) }).parse(d))
  .handler(async ({ data }) => {
    const t0 = Date.now();
    const highStakes = detectHighStakes(data.query);
    const r = await callLLM({
      provider: "cloudflare",
      model: CF_FAST,
      maxTokens: ANSWER_TOKENS,
      temperature: 0.2,
      system:
        "You are FastGate, the first oracle in REMORA's adaptive cascade. " +
        "Answer concisely (≤ 3 sentences). On the final line, output exactly: " +
        "`confidence: <number between 0 and 1>` reflecting your verbalized confidence in your own answer. " +
        "Be honest — if you do not know, give a low confidence. " +
        "For legal, compliance, medical, or safety-critical questions, reflect genuine uncertainty.",
      prompt: data.query,
    });
    const { confidence, answer, epistemicRefusal, hedging } = extractConfidence(r.text);
    const platt = Math.round((confidence * 0.92 + 0.02) * 1000) / 1000;
    // High-stakes queries and hedged answers must never short-circuit to ACCEPT.
    const short_circuit = platt >= 0.9 && !highStakes && !hedging && !epistemicRefusal;
    return {
      stage: "fastgate" as const,
      answer,
      raw_confidence: confidence,
      trust: platt,
      epistemic_refusal: epistemicRefusal,
      hedging,
      high_stakes: highStakes,
      ms: Date.now() - t0,
      oracles: 1,
      cost_usd: r.costUsd,
      tokens_in: r.tokensIn,
      tokens_out: r.tokensOut,
      provider: r.provider,
      model: r.model,
      short_circuit,
    };
  });

// ---------------------------------------------------------------------------
// Stage 2 — ConsensusGate (3 oracles, mixed providers for real diversity)
// ---------------------------------------------------------------------------

const CONSENSUS_PROMPTS = [
  {
    name: "literal",
    provider: "cloudflare" as const,
    model: CF_FAST,
    temperature: 0.0,
    frame: "Answer literally and precisely, no hedging.",
  },
  {
    name: "skeptical",
    provider: "openrouter" as const,
    model: OR_FAST,
    temperature: 0.4,
    frame: "Be skeptical. Note assumptions before concluding.",
  },
  {
    name: "creative",
    provider: "openrouter" as const,
    model: OR_FREE,
    temperature: 0.8,
    frame: "Consider unconventional angles before answering.",
  },
];

export const stageConsensus = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) => z.object({ query: z.string().min(1).max(2000) }).parse(d))
  .handler(async ({ data }) => {
    const t0 = Date.now();
    const results = await Promise.all(
      CONSENSUS_PROMPTS.map((p) =>
        callLLM({
          provider: p.provider,
          model: p.model,
          maxTokens: ANSWER_TOKENS,
          temperature: p.temperature,
          system: `You are a consensus oracle (${p.name}). ${p.frame} Reply in ≤ 3 sentences.`,
          prompt: data.query,
        }).then((r) => ({ name: p.name, ...r })),
      ),
    );
    const answers = results.map((r) => r.text);
    const H = answerEntropy(answers);
    const D = dissensus(answers);
    const T = Math.round((0.2 + D * 0.9) * 1000) / 1000;
    const lambda = 0.6;
    const F = Math.max(0, Math.round((lambda * D - T * H) * 1000) / 1000);
    const trust = Math.max(0, Math.min(1, Math.round((1 - F - 0.1 * D) * 1000) / 1000));
    const inTok = results.reduce((s, r) => s + r.tokensIn, 0);
    const outTok = results.reduce((s, r) => s + r.tokensOut, 0);
    const cost = Math.round(results.reduce((s, r) => s + r.costUsd, 0) * 1e6) / 1e6;
    // Count how many oracle answers contain epistemic refusals.
    const refusal_count = answers.filter(detectEpistemicRefusal).length;
    return {
      stage: "consensus" as const,
      answers,
      refusal_count,
      oracles_meta: results.map((r) => ({ name: r.name, provider: r.provider, model: r.model })),
      H,
      D,
      T,
      F,
      trust,
      ms: Date.now() - t0,
      oracles: 3,
      cost_usd: cost,
      tokens_in: inTok,
      tokens_out: outTok,
    };
  });

// ---------------------------------------------------------------------------
// Stage 3 — VerifierGate (Cloudflare llama-3.1-8b fast judge)
// ---------------------------------------------------------------------------

export const stageVerifier = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z
      .object({
        query: z.string().min(1).max(2000),
        candidate: z.string().min(1).max(4000),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const t0 = Date.now();
    const r = await callLLM({
      provider: "cloudflare",
      model: CF_JUDGE,
      maxTokens: JUDGE_TOKENS,
      temperature: 0,
      system:
        "You are an independent verifier. Given a question and a candidate answer, " +
        "decide if the candidate is factually defensible. " +
        "Respond on a single line as: `verdict=SUPPORTED|REFUTED|UNCLEAR, score=<0..1>`. No other text.",
      prompt: `Question: ${data.query}\nCandidate answer: ${data.candidate}`,
    });
    const m = r.text.match(/verdict\s*=\s*(SUPPORTED|REFUTED|UNCLEAR)/i);
    const s = r.text.match(/score\s*=\s*([01](?:\.\d+)?)/i);
    const verdict = (m?.[1]?.toUpperCase() ?? "UNCLEAR") as "SUPPORTED" | "REFUTED" | "UNCLEAR";
    const score = s
      ? Math.max(0, Math.min(1, parseFloat(s[1])))
      : verdict === "SUPPORTED"
        ? 0.75
        : 0.3;
    return {
      stage: "verifier" as const,
      verdict,
      score,
      raw: r.text.trim(),
      ms: Date.now() - t0,
      oracles: 1,
      cost_usd: r.costUsd,
      tokens_in: r.tokensIn,
      tokens_out: r.tokensOut,
      provider: r.provider,
      model: r.model,
    };
  });

// ---------------------------------------------------------------------------
// Stage 3b — CritiqueRevision (OpenRouter critique + Cloudflare revise)
// ---------------------------------------------------------------------------

export const stageCritique = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z
      .object({
        query: z.string().min(1).max(2000),
        candidate: z.string().min(1).max(4000),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const t0 = Date.now();
    const crit = await callLLM({
      provider: "openrouter",
      model: OR_FAST,
      maxTokens: CRITIQUE_TOKENS,
      temperature: 0.2,
      system:
        "You are a constitutional critic. List up to 3 concrete weaknesses or unsupported claims in the candidate answer. Be terse.",
      prompt: `Question: ${data.query}\nCandidate answer: ${data.candidate}`,
    });
    const rev = await callLLM({
      provider: "cloudflare",
      model: CF_FAST,
      maxTokens: ANSWER_TOKENS,
      temperature: 0.2,
      system:
        "You revise the candidate to address the listed critiques. " +
        "Output only the revised answer (≤ 3 sentences). No preamble.",
      prompt: `Question: ${data.query}\nOriginal: ${data.candidate}\nCritiques:\n${crit.text}`,
    });
    const cost = Math.round((crit.costUsd + rev.costUsd) * 1e6) / 1e6;
    return {
      stage: "critique" as const,
      critique: crit.text.trim(),
      revised: rev.text.trim(),
      ms: Date.now() - t0,
      oracles: 2,
      cost_usd: cost,
      tokens_in: crit.tokensIn + rev.tokensIn,
      tokens_out: crit.tokensOut + rev.tokensOut,
      providers: [
        { stage: "critique", provider: crit.provider, model: crit.model },
        { stage: "revise", provider: rev.provider, model: rev.model },
      ],
    };
  });

// ---------------------------------------------------------------------------
// Stage 6 — MoA Synth (OpenRouter — slightly stronger free Gemini)
// ---------------------------------------------------------------------------

export const stageMoA = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) =>
    z
      .object({
        query: z.string().min(1).max(2000),
        pool: z.array(z.string().min(1).max(4000)).min(1).max(8),
      })
      .parse(d),
  )
  .handler(async ({ data }) => {
    const t0 = Date.now();
    const numbered = data.pool.map((p, i) => `[${i + 1}] ${p}`).join("\n");
    const r = await callLLM({
      provider: "openrouter",
      model: OR_SYNTH,
      maxTokens: SYNTH_TOKENS,
      temperature: 0.1,
      system:
        "You are the MoA (Mixture of Agents) synthesis oracle. " +
        "Read the question and the candidate answers, then output a single hedged answer " +
        "that reflects the consensus where one exists, and explicitly flags disagreement otherwise. " +
        "Maximum 4 sentences. End with a 1-line trust note (e.g. 'trust note: hedged, oracles disagreed on X').",
      prompt: `Question: ${data.query}\nCandidates:\n${numbered}`,
    });
    return {
      stage: "moa" as const,
      answer: r.text.trim(),
      ms: Date.now() - t0,
      oracles: 1,
      cost_usd: r.costUsd,
      tokens_in: r.tokensIn,
      tokens_out: r.tokensOut,
      provider: r.provider,
      model: r.model,
    };
  });

// χ-gate — pure, no model call
export const stageChi = createServerFn({ method: "POST" })
  .inputValidator((d: unknown) => z.object({ query: z.string().min(1).max(2000) }).parse(d))
  .handler(async ({ data }) => {
    const chi = chiSusceptibility(data.query);
    return { stage: "chi" as const, chi, threshold: 1.45, escalate: chi >= 1.45 };
  });
