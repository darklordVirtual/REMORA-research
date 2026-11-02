import { describe, expect, it, vi } from "vitest";

import worker from "./index";
import { CODEGRAPH_CATALOG, type CodegraphEntry } from "./codegraph";
import {
  BGE_QUERY_INSTRUCTION,
  DEFAULT_CODEGRAPH_EMBED_MODEL,
  MAX_SEMANTIC_QUERY_CHARS,
  buildCodegraphSearch,
  fuseRankings,
  parseSearchMode,
  semanticSearch,
  type CodegraphSemanticEnv,
  type SemanticMatch,
} from "./codegraph.semantic";

type FakeMatch = { id: string; score: number; metadata?: Record<string, unknown> };

function fakeEnv(matches: FakeMatch[], overrides: Partial<CodegraphSemanticEnv> = {}) {
  const run = vi.fn(async () => ({ data: [[0.1, 0.2, 0.3]] }));
  const query = vi.fn(async (_vector: number[], _options: VectorizeQueryOptions) => ({ matches, count: matches.length }));
  const env: CodegraphSemanticEnv = {
    AI: { run },
    CODEGRAPH_VECTORS: { query } as unknown as VectorizeIndex,
    ...overrides,
  };
  return { env, run, query };
}

const meta = (path: string, extra: Record<string, unknown> = {}) => ({
  path,
  start_line: 1,
  end_line: 40,
  snippet: `snippet of ${path}`,
  commit: "abc123",
  index_version: "v1",
  ...extra,
});

describe("parseSearchMode", () => {
  it("defaults to keyword", () => {
    expect(parseSearchMode(null)).toBe("keyword");
    expect(parseSearchMode("")).toBe("keyword");
  });

  it("accepts the three modes case-insensitively", () => {
    expect(parseSearchMode("Semantic")).toBe("semantic");
    expect(parseSearchMode(" hybrid ")).toBe("hybrid");
  });

  it("rejects anything else instead of guessing", () => {
    expect(parseSearchMode("vector")).toBeNull();
  });
});

describe("semanticSearch", () => {
  it("embeds the query with the bge retrieval instruction and the configured model", async () => {
    const { env, run } = fakeEnv([]);
    await semanticSearch("ledger integrity", 5, env);
    expect(run).toHaveBeenCalledWith(DEFAULT_CODEGRAPH_EMBED_MODEL, {
      text: [BGE_QUERY_INSTRUCTION + "ledger integrity"],
    });
  });

  it("keeps the best chunk per file, best first, and respects the limit", async () => {
    const { env } = fakeEnv([
      { id: "1", score: 0.71, metadata: meta("remora/a.py", { start_line: 41, end_line: 80 }) },
      { id: "2", score: 0.92, metadata: meta("remora/a.py") },
      { id: "3", score: 0.85, metadata: meta("docs/b.md") },
      { id: "4", score: 0.5, metadata: meta("tests/test_c.py") },
    ]);
    const matches = await semanticSearch("q", 2, env);
    expect(matches.map((m) => [m.path, m.score, m.start_line])).toEqual([
      ["remora/a.py", 0.92, 1],
      ["docs/b.md", 0.85, 1],
    ]);
    expect(matches[1].kind).toBe("doc");
  });

  it("requests at most Vectorize's metadata topK cap", async () => {
    const { env, query } = fakeEnv([]);
    await semanticSearch("q", 25, env);
    expect(query.mock.calls[0][1]).toMatchObject({ topK: 50, returnMetadata: "all" });
  });

  it("filters by index_version when configured and drops vectors that claim another version", async () => {
    const { env, query } = fakeEnv(
      [
        { id: "1", score: 0.9, metadata: meta("stale.py", { index_version: "v0" }) },
        { id: "2", score: 0.8, metadata: meta("fresh.py", { index_version: "v1" }) },
      ],
      { CODEGRAPH_INDEX_VERSION: "v1" },
    );
    const matches = await semanticSearch("q", 5, env);
    expect(query.mock.calls[0][1]).toMatchObject({ filter: { index_version: "v1" } });
    expect(matches.map((m) => m.path)).toEqual(["fresh.py"]);
  });

  it("ignores matches without a path", async () => {
    const { env } = fakeEnv([{ id: "1", score: 0.9, metadata: {} }, { id: "2", score: 0.1 }]);
    expect(await semanticSearch("q", 5, env)).toEqual([]);
  });

  it("throws when the model returns no vector rather than querying with garbage", async () => {
    const { env, query } = fakeEnv([], { AI: { run: async () => ({ data: [] }) } });
    await expect(semanticSearch("q", 5, env)).rejects.toThrow("no vector");
    expect(query).not.toHaveBeenCalled();
  });
});

describe("fuseRankings", () => {
  const kw = (path: string): CodegraphEntry => ({ path, summary: `S ${path}`, kind: "core", tags: [] });
  const sem = (path: string): SemanticMatch => ({
    path, kind: "core", score: 0.9, start_line: 3, end_line: 9, snippet: "x", index_commit: null,
  });

  it("ranks a file found by both rankers above files found by one", () => {
    const fused = fuseRankings([kw("a"), kw("b")], [sem("c"), sem("b")], 3);
    expect(fused[0]).toMatchObject({ path: "b", sources: ["keyword", "semantic"], start_line: 3 });
    expect(fused.map((f) => f.path).sort()).toEqual(["a", "b", "c"]);
  });

  it("is deterministic on ties", () => {
    const fused = fuseRankings([kw("z")], [sem("a")], 2);
    expect(fused.map((f) => f.path)).toEqual(["a", "z"]);
  });
});

describe("buildCodegraphSearch", () => {
  it("keyword mode keeps the original payload and needs no bindings", async () => {
    const result = await buildCodegraphSearch("codegraph", 3, "keyword", {});
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.body).toMatchObject({ mode: "keyword", semantic: { status: "not_requested" } });
    expect(result.body.total_files).toBe(CODEGRAPH_CATALOG.length);
  });

  it("semantic mode without bindings is a 503, not an empty result", async () => {
    const result = await buildCodegraphSearch("ledger", 3, "semantic", {});
    expect(result).toMatchObject({ ok: false, status: 503 });
  });

  it("semantic mode surfaces upstream failure as 502", async () => {
    const { env } = fakeEnv([], { AI: { run: async () => { throw new Error("boom"); } } });
    expect(await buildCodegraphSearch("ledger", 3, "semantic", env)).toMatchObject({ ok: false, status: 502 });
  });

  it("hybrid mode degrades to keyword ranking and says so", async () => {
    const result = await buildCodegraphSearch("codegraph", 3, "hybrid", {});
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.body.semantic).toEqual({ status: "unavailable", reason: "AI binding is not configured" });
    expect((result.body.matches as unknown[]).length).toBeGreaterThan(0);
  });

  it("rejects empty and oversized queries for paid modes", async () => {
    const { env, run } = fakeEnv([]);
    expect(await buildCodegraphSearch("", 3, "semantic", env)).toMatchObject({ ok: false, status: 400 });
    const long = "x".repeat(MAX_SEMANTIC_QUERY_CHARS + 1);
    expect(await buildCodegraphSearch(long, 3, "hybrid", env)).toMatchObject({ ok: false, status: 400 });
    expect(run).not.toHaveBeenCalled();
  });
});

describe("worker routing for /codegraph and /search", () => {
  const SECRET = "test-control-secret";
  const call = (path: string, env: object, auth?: string) =>
    worker.fetch(
      new Request(`https://agent-control.test${path}`, {
        headers: auth ? { Authorization: auth } : {},
      }),
      env as never,
    );

  it("keeps keyword search public and /search's historical mode label", async () => {
    const res = await call("/search?q=codegraph", {});
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ mode: "repo_search" });
  });

  it("refuses semantic and hybrid without the bearer", async () => {
    const { env, run } = fakeEnv([]);
    for (const mode of ["semantic", "hybrid"]) {
      const res = await call(`/codegraph?q=ledger&mode=${mode}`, { ...env, CONTROL_SECRET: SECRET });
      expect(res.status).toBe(401);
    }
    const wrong = await call("/codegraph?q=ledger&mode=semantic", { ...env, CONTROL_SECRET: SECRET }, "Bearer nope");
    expect(wrong.status).toBe(401);
    expect(run).not.toHaveBeenCalled();
  });

  it("fails closed with 503 when CONTROL_SECRET is unset", async () => {
    const { env, run } = fakeEnv([]);
    const res = await call("/codegraph?q=ledger&mode=hybrid", env, "Bearer anything");
    expect(res.status).toBe(503);
    expect(run).not.toHaveBeenCalled();
  });

  it("serves semantic results to an authenticated caller", async () => {
    const { env } = fakeEnv([{ id: "1", score: 0.8, metadata: meta("remora/enforcement/gate.py") }]);
    const res = await call("/codegraph?q=ledger&mode=semantic&limit=3", { ...env, CONTROL_SECRET: SECRET }, `Bearer ${SECRET}`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { mode: string; matches: Array<{ path: string }> };
    expect(body.mode).toBe("semantic");
    expect(body.matches[0].path).toBe("remora/enforcement/gate.py");
  });

  it("rejects an unknown mode with 400", async () => {
    expect((await call("/codegraph?q=x&mode=vector", {})).status).toBe(400);
  });

  it("clamps a non-numeric limit instead of returning NaN", async () => {
    const res = await call("/codegraph?q=codegraph&limit=abc", {});
    expect(await res.json()).toMatchObject({ limit: 8 });
  });
});

describe("catalog integrity", () => {
  it("every entrypoint is a cataloged file", async () => {
    const { CODEGRAPH_SCOPE } = await import("./codegraph");
    const cataloged = new Set(CODEGRAPH_CATALOG.map((entry) => entry.path));
    expect(CODEGRAPH_SCOPE.entrypoints.filter((path) => !cataloged.has(path))).toEqual([]);
  });

});
