import { describe, it, expect } from "vitest";
import worker from "./index";

/**
 * SR-02 / SR-04 (SEC-04): /search must be authenticated, tenant/clearance
 * scoped and k-clamped, and no route may fail open when ORACLE_SECRET is
 * unset. These tests drive the real worker fetch handler with a mock env.
 */

const SECRET = "test-oracle-secret";

interface CapturedQuery {
  embedding: number[];
  opts: { topK: number; filter?: Record<string, unknown> };
}

function makeEnv(opts: { secret?: string } = {}) {
  const captured: CapturedQuery[] = [];
  const env = {
    ORACLE_SECRET: opts.secret,
    AI: {
      run: async () => ({ data: [[0.1, 0.2, 0.3]] }),
    },
    VECTORIZE: {
      query: async (embedding: number[], qopts: CapturedQuery["opts"]) => {
        captured.push({ embedding, opts: qopts });
        return { matches: [] };
      },
    },
    VECTORIZE_MULTI: {
      query: async (embedding: number[], qopts: CapturedQuery["opts"]) => {
        captured.push({ embedding, opts: qopts });
        return { matches: [] };
      },
    },
    EMBED_MODEL: "embed",
    EMBED_MODEL_MULTI: "embed-multi",
  };
  return { env, captured };
}

function searchReq(params: string, withAuth = true): Request {
  const headers: Record<string, string> = {};
  if (withAuth) headers["Authorization"] = `Bearer ${SECRET}`;
  return new Request(`https://oracle.test/search?${params}`, { headers });
}

describe("fail-closed secret (SR-04)", () => {
  it("returns 503 on /search when ORACLE_SECRET is unset", async () => {
    const { env } = makeEnv({ secret: undefined });
    const res = await worker.fetch(searchReq("q=x"), env as never);
    expect(res.status).toBe(503);
  });

  it("returns 503 on /query when ORACLE_SECRET is unset (was allow-all)", async () => {
    const { env } = makeEnv({ secret: undefined });
    const res = await worker.fetch(
      new Request("https://oracle.test/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "x" }),
      }),
      env as never,
    );
    expect(res.status).toBe(503);
  });

  it("returns 503 on /rerank and /translate when ORACLE_SECRET is unset", async () => {
    const { env } = makeEnv({ secret: undefined });
    for (const path of ["/rerank", "/translate"]) {
      const res = await worker.fetch(
        new Request(`https://oracle.test${path}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: "x", texts: ["a"], text: "x" }),
        }),
        env as never,
      );
      expect(res.status).toBe(503);
    }
  });
});

describe("/search authentication (SR-02)", () => {
  it("returns 401 without a token", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq("q=x", false), env as never);
    expect(res.status).toBe(401);
  });

  it("returns 401 with a wrong token", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const req = new Request("https://oracle.test/search?q=x", {
      headers: { Authorization: "Bearer wrong" },
    });
    const res = await worker.fetch(req, env as never);
    expect(res.status).toBe(401);
  });

  it("returns 401 for a token that only shares a prefix", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const req = new Request("https://oracle.test/search?q=x", {
      headers: { Authorization: `Bearer ${SECRET.slice(0, -1)}` },
    });
    const res = await worker.fetch(req, env as never);
    expect(res.status).toBe(401);
  });

  it("returns 401 for a non-Bearer scheme carrying the secret", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const req = new Request("https://oracle.test/search?q=x", {
      headers: { Authorization: `Basic ${SECRET}` },
    });
    const res = await worker.fetch(req, env as never);
    expect(res.status).toBe(401);
  });

  it("/status stays unauthenticated", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const statusEnv = {
      ...env,
      DB: {
        prepare: () => ({
          all: async () => ({ results: [] }),
          first: async () => null,
        }),
      },
      CACHE: { get: async () => null },
      DEFAULT_TOP_K: "5",
    };
    const res = await worker.fetch(
      new Request("https://oracle.test/status"),
      statusEnv as never,
    );
    expect(res.status).not.toBe(401);
    expect(res.status).not.toBe(503);
  });
});

describe("/search k clamp (SR-02)", () => {
  it.each(["1.5", "2x", "20.5"])("rejects a non-integer k=%s without querying the index", async (k) => {
    const { env, captured } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq(`q=x&k=${k}`), env as never);
    expect(res.status).toBe(400);
    expect(captured).toEqual([]);
  });

  it("rejects k=10000", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq("q=x&k=10000"), env as never);
    expect(res.status).toBe(400);
  });

  it("rejects non-numeric k", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq("q=x&k=abc"), env as never);
    expect(res.status).toBe(400);
  });

  it("rejects k=0", async () => {
    const { env } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq("q=x&k=0"), env as never);
    expect(res.status).toBe(400);
  });

  it("accepts k=20 and passes it to Vectorize", async () => {
    const { env, captured } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(searchReq("q=x&k=20"), env as never);
    expect(res.status).toBe(200);
    expect(captured[0].opts.topK).toBe(20);
  });
});

describe("/search tenant and clearance scoping (SR-02)", () => {
  it("applies tenant_id as a metadata filter", async () => {
    const { env, captured } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(
      searchReq("q=x&k=5&tenant_id=tenant-a"),
      env as never,
    );
    expect(res.status).toBe(200);
    expect(captured[0].opts.filter).toEqual({ tenant_id: { $eq: "tenant-a" } });
  });

  it("applies clearance levels as a metadata filter", async () => {
    const { env, captured } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(
      searchReq("q=x&k=5&clearance=public&clearance=internal"),
      env as never,
    );
    expect(res.status).toBe(200);
    expect(captured[0].opts.filter).toEqual({
      clearance_level: { $in: ["public", "internal"] },
    });
  });

  it("combines tenant, clearance and domain filters", async () => {
    const { env, captured } = makeEnv({ secret: SECRET });
    const res = await worker.fetch(
      searchReq("q=x&k=5&tenant_id=a&clearance=public&domain=legal"),
      env as never,
    );
    expect(res.status).toBe(200);
    expect(captured[0].opts.filter).toEqual({
      tenant_id: { $eq: "a" },
      clearance_level: { $in: ["public"] },
      domain: { $eq: "legal" },
    });
  });
});
