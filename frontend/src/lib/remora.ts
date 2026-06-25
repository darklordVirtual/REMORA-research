// Shared REMORA types + public endpoint client (browser-safe).
// Authenticated calls go via src/lib/remora.functions.ts (server functions).

export const REMORA_URLS = {
  agentControl: "https://remora-agent-control.razorsharp.workers.dev",
  ragOracle: "https://remora-rag-oracle.razorsharp.workers.dev",
  lawSearch: "https://remora-law-search.razorsharp.workers.dev",
} as const;

export type Verdict = "VERIFIED" | "CONTRADICTED" | "SUSPICIOUS" | "UNCERTAIN";

export type ToolName =
  | "remora_verify_claim"
  | "dce_search_law"
  | "store_artifact"
  | "audit_decision";

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type ExecuteResponse = {
  tool: ToolName;
  success: boolean;
  output: JsonValue;
  verdict?: Verdict;
  confidence?: number;
  duration_ms: number;
  session_id: string;
  audit_id: number;
  approval_required: boolean;
  error?: string;
};

export type AuditRow = {
  id: number;
  session_id: string;
  ts: string;
  tool_called: ToolName | string;
  input_preview: string;
  output_preview: string;
  verdict: Verdict | null;
  confidence: number | null;
  duration_ms: number | null;
  approval_required: 0 | 1;
  approved: 0 | 1 | null;
  approved_by: string | null;
};

export type RagQueryResponse = {
  answer: boolean;
  claim: string;
  confidence: number;
  sources: string[];
  retrieved_chunks: number;
  reranked: boolean;
  cache_hit: boolean;
  multilingual?: boolean;
  model: string;
  use_case: string;
  dual_consensus?: boolean;
  models_agreed?: boolean;
};

export type LawMatch = {
  id: string;
  score: number;
  law_id: string;
  title: string;
  section: string;
  content: string;
  heading?: string;
  url?: string;
};

export type CitationResponse = {
  citation: string;
  found_in_d1: boolean;
  d1_matches: Array<{ vector_id: string; namespace: string; snippet: string }>;
  vector_matches: Array<{ id: string; score: number; law_id: string }>;
  verdict: "FOUND_IN_DATABASE" | "POSSIBLE_MATCH_VECTOR" | "NOT_FOUND";
  note: string;
};

export type WorkerStatus = {
  name: string;
  url: string;
  ok: boolean;
  latency_ms: number;
  data?: unknown;
};

async function getJson<T>(url: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

// ---------- Public endpoints (browser-callable) ----------

export const remoraPublic = {
  async ragQuery(body: {
    query: string;
    domain?: string;
    top_k?: number;
    use_case?: "legal" | "security" | "general";
    complexity?: "auto" | "low" | "high";
    dual_consensus?: boolean;
    multilingual?: boolean;
    bypass_cache?: boolean;
  }): Promise<RagQueryResponse> {
    return getJson(`${REMORA_URLS.ragOracle}/query`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async lawSearch(body: {
    query: string;
    top_k?: number;
    filter?: Record<string, string>;
  }): Promise<{ query: string; total: number; matches: LawMatch[] }> {
    return getJson(`${REMORA_URLS.lawSearch}/search`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async verifyCitation(citation: string): Promise<CitationResponse> {
    return getJson(`${REMORA_URLS.lawSearch}/verify-citation`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ citation }),
    });
  },

  async pingAll(): Promise<WorkerStatus[]> {
    const targets = [
      { name: "Agent Control", url: `${REMORA_URLS.agentControl}/status` },
      { name: "RAG Oracle", url: `${REMORA_URLS.ragOracle}/status` },
      { name: "Law Search", url: `${REMORA_URLS.lawSearch}/status` },
    ];
    return Promise.all(
      targets.map(async (t) => {
        const started = typeof window !== "undefined" ? performance.now() : Date.now();
        try {
          const data = await getJson<unknown>(t.url);
          return {
            ...t,
            ok: true,
            latency_ms: Math.round(
              (typeof window !== "undefined" ? performance.now() : Date.now()) - started,
            ),
            data,
          };
        } catch {
          return {
            ...t,
            ok: false,
            latency_ms: Math.round(
              (typeof window !== "undefined" ? performance.now() : Date.now()) - started,
            ),
          };
        }
      }),
    );
  },

  async tools(): Promise<{
    tools: Array<{ name: ToolName; description: string; parameters: unknown }>;
    count: number;
  }> {
    return getJson(`${REMORA_URLS.agentControl}/tools`);
  },
};

export function verdictTone(v?: Verdict | null) {
  switch (v) {
    case "VERIFIED":
      return "accept";
    case "CONTRADICTED":
      return "escalate";
    case "SUSPICIOUS":
      return "verify";
    case "UNCERTAIN":
      return "abstain";
    default:
      return "abstain";
  }
}
