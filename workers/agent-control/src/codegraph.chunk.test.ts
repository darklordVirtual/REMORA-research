import { describe, expect, it } from "vitest";

// @ts-expect-error -- plain ESM module shared with the indexer script
import * as chunk from "../scripts/codegraph_chunk.mjs";

const lines = (n: number, width = 10) =>
  Array.from({ length: n }, (_, i) => `${String(i + 1).padStart(4, "0")}${"x".repeat(width)}`).join("\n");

describe("isIndexablePath", () => {
  it("indexes source and docs", () => {
    expect(chunk.isIndexablePath("remora/enforcement/gate.py", 1000)).toBe(true);
    expect(chunk.isIndexablePath("docs/README.md", 1000)).toBe(true);
    expect(chunk.isIndexablePath("Makefile", 1000)).toBe(true);
    expect(chunk.isIndexablePath("schemas/openapi.json", 1000)).toBe(true);
  });

  it("skips locks, provenance, generated code, data dumps and oversized files", () => {
    for (const path of [
      "frontend/package-lock.json",
      "requirements-lock.txt",
      "requirements-agentharm.lock",
      "provenance/code-register-v1.json",
      "workers/agent-control/src/codegraph.paths.ts",
      "frontend/src/generated/remora-api.ts",
      "artifacts/interop/summary.json",
      "results/run.json",
      "artifacts/aromer_train_episodes.jsonl",
      "artifacts/figures/cover.png",
    ]) {
      expect(chunk.isIndexablePath(path, 1000), path).toBe(false);
    }
    expect(chunk.isIndexablePath("remora/big.py", chunk.MAX_FILE_BYTES + 1)).toBe(false);
    expect(chunk.isIndexablePath("remora/empty.py", 0)).toBe(false);
  });
});

describe("chunkText", () => {
  it("covers every line, in order, with the configured overlap", () => {
    const chunks = chunk.chunkText(lines(100), { maxLines: 40, overlap: 8, maxChars: 100_000, maxTokens: 100_000 });
    expect(chunks.map((c: { start_line: number; end_line: number }) => [c.start_line, c.end_line])).toEqual([
      [1, 40], [33, 72], [65, 100],
    ]);
  });

  it("closes a window before maxChars and always makes progress", () => {
    const chunks = chunk.chunkText(lines(30, 100), { maxLines: 40, overlap: 8, maxChars: 500, maxTokens: 100_000 });
    for (const c of chunks) expect(c.text.length).toBeLessThanOrEqual(500);
    expect(chunks[chunks.length - 1].end_line).toBe(30);
    const starts = chunks.map((c: { start_line: number }) => c.start_line);
    expect(new Set(starts).size).toBe(starts.length);
  });

  it("truncates a single line longer than maxChars", () => {
    const [only] = chunk.chunkText("y".repeat(5000), { maxLines: 40, overlap: 8, maxChars: 1200, maxTokens: 100_000 });
    expect(only.text.length).toBe(1200);
  });

  it("keeps default chunks inside the embedding model's input window", () => {
    const text = lines(400, 200);
    for (const c of chunk.chunkText(text)) {
      const input = chunk.embeddingInput("some/long/path/to/file.py", c);
      expect(chunk.estimateTokens(input)).toBeLessThan(chunk.MODEL_MAX_TOKENS);
    }
  });

  it("closes a window at the token budget for dense content", () => {
    const dense = Array.from({ length: 40 }, () => '{"a":1,"b":[2,3],"c":"x"}').join("\n");
    for (const c of chunk.chunkText(dense, { maxLines: 40, overlap: 8, maxChars: 100_000, maxTokens: 100 })) {
      expect(chunk.estimateTokens(c.text)).toBeLessThanOrEqual(100);
    }
  });

  it("truncates a single line that alone exceeds the token budget", () => {
    const [only] = chunk.chunkText("{}".repeat(2000), { maxLines: 40, overlap: 8, maxChars: 100_000, maxTokens: 50 });
    expect(chunk.estimateTokens(only.text)).toBeLessThanOrEqual(50);
    expect(only.text.length).toBeGreaterThan(0);
  });

  it("drops whitespace-only windows and normalises CRLF", () => {
    expect(chunk.chunkText("\n\n   \n")).toEqual([]);
    expect(chunk.chunkText("a\r\nb\r\n")[0]).toMatchObject({ start_line: 1, end_line: 2, text: "a\nb" });
  });

  it("refuses an overlap that would never advance", () => {
    expect(() => chunk.chunkText("a", { maxLines: 5, overlap: 5, maxChars: 100 })).toThrow();
  });
});

describe("chunkId and metadata", () => {
  const c = { start_line: 1, end_line: 2, text: "a\nb" };

  it("is a 64-hex id, stable for identical content and different otherwise", () => {
    const id = chunk.chunkId("x.py", c);
    expect(id).toMatch(/^[0-9a-f]{64}$/);
    expect(chunk.chunkId("x.py", { ...c })).toBe(id);
    expect(chunk.chunkId("y.py", c)).not.toBe(id);
    expect(chunk.chunkId("x.py", { ...c, text: "a\nc" })).not.toBe(id);
  });

  it("bounds the snippet", () => {
    expect(chunk.snippetOf("w ".repeat(1000)).length).toBeLessThanOrEqual(chunk.SNIPPET_CHARS);
  });

  it("detects binary content by NUL bytes", () => {
    expect(chunk.looksBinary(Buffer.from([0x50, 0x00, 0x4b]))).toBe(true);
    expect(chunk.looksBinary(Buffer.from("plain text"))).toBe(false);
  });
});
