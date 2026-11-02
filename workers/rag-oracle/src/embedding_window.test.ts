import { describe, it, expect } from "vitest";
import worker from "./index";

/**
 * W-08 / F-10: embedText cut every input to its first 512 characters, so a
 * passage was retrievable only by its opening. The full chunk was still
 * stored and returned as context, which made the loss invisible. Inputs are
 * now fitted to the embedding model's token window, and an ingest that still
 * had to cut reports it.
 */

const SECRET = "test-oracle-secret";
const TAIL = "zebrafishsentinel";

function makeEnv(embedModel = "@cf/baai/bge-base-en-v1.5") {
  const embedded: string[] = [];
  const inserted: unknown[] = [];
  const upserted: unknown[] = [];
  const env = {
    ORACLE_SECRET: SECRET,
    AI: {
      run: async (_model: string, input: { text?: string[] }) => {
        if (input.text) embedded.push(...input.text);
        return { data: [[0.1, 0.2, 0.3]] };
      },
    },
    VECTORIZE: {
      query: async () => ({ matches: [] }),
      insert: async (vectors: unknown[]) => { inserted.push(...vectors); return {}; },
      upsert: async (vectors: unknown[]) => { upserted.push(...vectors); return {}; },
    },
    VECTORIZE_MULTI: {
      query: async () => ({ matches: [] }),
      insert: async (vectors: unknown[]) => { inserted.push(...vectors); return {}; },
      upsert: async (vectors: unknown[]) => { upserted.push(...vectors); return {}; },
    },
    DB: {
      prepare: () => {
        const stmt = { bind: () => stmt, run: async () => ({ success: true }) };
        return stmt;
      },
    },
    EMBED_MODEL: embedModel,
    EMBED_MODEL_MULTI: "@cf/baai/bge-m3",
  };
  return { env, embedded, inserted, upserted };
}

function ingest(body: Record<string, unknown>): Request {
  return new Request("https://oracle.test/ingest", {
    method: "POST",
    headers: { Authorization: `Bearer ${SECRET}`, "Content-Type": "application/json" },
    body: JSON.stringify({ source: "doc.md", domain: "general", ...body }),
  });
}

const prose = (words: number) =>
  Array.from({ length: words }, (_, i) => `word${i % 7}`).join(" ");

describe("embedding window (W-08)", () => {
  it("embeds content past character 512 when it fits the model window", async () => {
    const { env, embedded } = makeEnv();
    const content = `${prose(90)} ${TAIL}`;
    expect(content.indexOf(TAIL)).toBeGreaterThan(512);

    const res = await worker.fetch(ingest({ content }), env as never);
    expect(res.status).toBe(200);
    expect(embedded[0]).toContain(TAIL);
    const body = (await res.json()) as { embedding: { truncated: boolean } };
    expect(body.embedding.truncated).toBe(false);
  });

  it("reports truncation instead of hiding it when content exceeds the window", async () => {
    const { env, embedded } = makeEnv();
    const content = `${prose(2000)} ${TAIL}`;

    const res = await worker.fetch(ingest({ content }), env as never);
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      embedding: { truncated: boolean; embedded_chars: number; content_chars: number };
    };
    expect(body.embedding.truncated).toBe(true);
    expect(body.embedding.content_chars).toBe(content.length);
    expect(body.embedding.embedded_chars).toBeLessThan(content.length);
    expect(embedded[0].length).toBe(body.embedding.embedded_chars);
    expect(embedded[0]).not.toContain(TAIL);
  });

  it("gives the multilingual model its larger window", async () => {
    const { env, embedded } = makeEnv();
    const content = `${prose(2000)} ${TAIL}`;
    const res = await worker.fetch(ingest({ content, multilingual: true }), env as never);
    expect(res.status).toBe(200);
    expect(embedded[0]).toContain(TAIL);
  });

  it("embeds a long query past character 512", async () => {
    const { env, embedded } = makeEnv();
    const question = `${prose(90)} ${TAIL}`;
    await worker.fetch(
      new Request("https://oracle.test/query", {
        method: "POST",
        headers: { Authorization: `Bearer ${SECRET}`, "Content-Type": "application/json" },
        body: JSON.stringify({ query: question, domain: "general", use_cache: false }),
      }),
      env as never,
    );
    expect(embedded.some((text) => text.includes(TAIL))).toBe(true);
  });

  it("re-ingesting a changed chunk replaces its vector (upsert, not insert)", async () => {
    // The vector id hashes source, chunk_index and the first 64 characters.
    // Vectorize ignores an insert whose id exists, while D1 replaced the
    // text, so a chunk edited after character 64 kept its old embedding.
    const { env, inserted, upserted } = makeEnv();
    const head = "x".repeat(64);
    await worker.fetch(ingest({ content: `${head} first version` }), env as never);
    await worker.fetch(ingest({ content: `${head} second version` }), env as never);
    expect(inserted).toHaveLength(0);
    expect(upserted).toHaveLength(2);
    const ids = upserted.map((v) => (v as { id: string }).id);
    expect(ids[0]).toBe(ids[1]);
  });
});
