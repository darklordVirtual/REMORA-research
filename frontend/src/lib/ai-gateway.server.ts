// Unified LLM gateway — all calls route through the Cloudflare AI Gateway
// compat endpoint (OpenAI-compatible). Auth: CF_AI_GATEWAY_KEY.
// Model names: @cf/... for CF-hosted Workers AI, provider/name for proxied.

// `provider` is kept for backwards compat with cascade.functions.ts but
// is not used for routing — all calls go through the same CF Gateway.
export type Provider = "openrouter" | "cloudflare";

export interface LLMCall {
  provider?: Provider;
  model: string;
  system?: string;
  prompt: string;
  maxTokens?: number;
  temperature?: number;
}

export interface LLMResult {
  text: string;
  tokensIn: number;
  tokensOut: number;
  provider: Provider;
  model: string;
  costUsd: number;
}

// ---------- CF Workers AI hosted models ----------
// The compat endpoint requires the model prefixed with "workers-ai/" for
// CF-hosted models: workers-ai/@cf/meta/llama-3.2-3b-instruct
// The constants below are the bare @cf/... names; callLLM() adds the prefix.
export const CF_FAST = "@cf/meta/llama-3.2-3b-instruct"; // 3B fast
export const CF_JUDGE = "@cf/meta/llama-3.1-8b-instruct-fp8"; // 8B judge
export const CF_MED = "@cf/mistralai/mistral-small-3.1-24b-instruct"; // 24B balanced
export const CF_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"; // 70B fast

// Aliases used by cascade.functions.ts — diverse CF hosted models.
export const OR_FAST = CF_MED; // skeptical oracle (24B)
export const OR_FREE = CF_LARGE; // creative oracle  (70B)
export const OR_SYNTH = CF_LARGE; // synthesis oracle (70B)

// Rough price table (USD per 1M tokens) — CF Workers AI rates.
const PRICES: Record<string, { in: number; out: number }> = {
  [CF_FAST]: { in: 0.027, out: 0.2 },
  [CF_JUDGE]: { in: 0.05, out: 0.25 },
  [CF_MED]: { in: 0.06, out: 0.3 },
  [CF_LARGE]: { in: 0.1, out: 0.4 },
};

function priceFor(model: string, inTok: number, outTok: number): number {
  const p = PRICES[model] ?? { in: 0.05, out: 0.2 };
  return Math.round(((inTok * p.in + outTok * p.out) / 1_000_000) * 1e6) / 1e6;
}

// ---------- Single unified gateway call ----------
export async function callLLM(c: LLMCall): Promise<LLMResult> {
  const key = process.env.CF_AI_GATEWAY_KEY;
  if (!key) throw new Error("CF_AI_GATEWAY_KEY missing on server");

  // Build the compat chat/completions URL.
  // Env var may include the full path or just the base; normalise to .../compat/chat/completions
  const rawUrl =
    process.env.CF_AI_GATEWAY_URL ??
    "https://gateway.ai.cloudflare.com/v1/ca139047698b35c49bc921b778cd26b1/r-e-m-o-r-a/compat/chat/completions";
  const url = rawUrl.endsWith("/chat/completions")
    ? rawUrl
    : rawUrl.replace(/\/?$/, "/chat/completions");

  // CF Workers AI models need the "workers-ai/" prefix on the compat endpoint.
  const model = c.model.startsWith("@cf/") ? `workers-ai/${c.model}` : c.model;

  const body = {
    model,
    temperature: c.temperature ?? 0.2,
    max_tokens: c.maxTokens ?? 220,
    messages: [
      ...(c.system ? [{ role: "system", content: c.system }] : []),
      { role: "user", content: c.prompt },
    ],
  };

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const t = await res.text();
    throw new Error(`CF Gateway ${res.status}: ${t.slice(0, 300)}`);
  }

  const json = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
    usage?: { prompt_tokens?: number; completion_tokens?: number };
  };

  const text = json.choices?.[0]?.message?.content?.trim() ?? "";
  const tokensIn = json.usage?.prompt_tokens ?? 0;
  const tokensOut = json.usage?.completion_tokens ?? 0;

  return {
    text,
    tokensIn,
    tokensOut,
    provider: "cloudflare",
    model: c.model,
    costUsd: priceFor(c.model, tokensIn, tokensOut),
  };
}
