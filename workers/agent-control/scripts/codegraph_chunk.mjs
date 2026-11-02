// Pure chunking rules for the CodeGraph semantic index.
//
// Kept free of I/O so the same rules are unit-tested (src/codegraph.chunk.test.ts)
// and used by scripts/build_codegraph_index.mjs.

import { createHash } from "node:crypto";

export const MAX_FILE_BYTES = 200_000;
// bge-base-en-v1.5 reads at most 512 tokens and silently drops the rest.
// A character cap alone does not hold for dense JSON, hex or markup, so a
// window also closes at an estimated token budget. Norwegian prose splits
// into more WordPieces than English and needs the extra headroom. Measured
// against the real tokenizer on all 46,925 chunks of this repository at
// 2026-11-02: median 325, p99 399, max 480 tokens including the path header.
export const MODEL_MAX_TOKENS = 512;
export const DEFAULT_CHUNK_OPTIONS = Object.freeze({ maxLines: 40, overlap: 8, maxChars: 1600, maxTokens: 380 });

const TOKEN_ESTIMATE = /[A-Za-z]{1,4}|\d|[^\sA-Za-z\d]/g;

/** Conservative WordPiece length estimate (letters in 4s, digits and symbols singly). */
export function estimateTokens(text) {
  return (text.match(TOKEN_ESTIMATE) ?? []).length;
}

function fitLine(line, maxChars, maxTokens) {
  let out = line.length > maxChars ? line.slice(0, maxChars) : line;
  while (out.length > 0 && estimateTokens(out) > maxTokens) {
    out = out.slice(0, Math.floor(out.length * 0.8));
  }
  return out;
}
export const SNIPPET_CHARS = 300;

export const TEXT_EXTENSIONS = new Set([
  ".py", ".pyi", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx",
  ".md", ".rst", ".txt", ".tex", ".bib",
  ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json",
  ".sql", ".sh", ".rego", ".html", ".css", ".proto", ".go", ".rs",
]);

const EXTENSIONLESS_TEXT = new Set(["Makefile", "Dockerfile", "LICENSE"]);

// Generated, vendored or hash-dominated files: they crowd out real matches
// and say nothing a reader searches for.
export const EXCLUDED_PATTERNS = [
  /(^|\/)node_modules\//,
  /(^|\/)package-lock\.json$/,
  /(^|\/)(bun|yarn|pnpm-lock|poetry|uv)\.lock$/,
  /(^|\/)requirements[^/]*\.lock$/,
  /(^|\/)requirements-lock\.txt$/,
  /^provenance\//,
  /(^|\/)codegraph\.paths\.ts$/,
  /(^|\/)generated\//,
  /\.min\.(js|css)$/,
  /\.(ipynb|svg|jsonl)$/, // notebooks and JSONL logs are output, not source
  // Evidence and result data: searched by path through the keyword ranker,
  // but as embedded content it is a third of all chunks and crowds out code.
  /^(artifacts|results|data|datasets)\/.*\.json$/,
];

export function extensionOf(path) {
  const base = path.split("/").pop() ?? path;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot).toLowerCase() : "";
}

/** Whether a tracked file should be embedded, judged by path and size only. */
export function isIndexablePath(path, sizeBytes) {
  if (sizeBytes <= 0 || sizeBytes > MAX_FILE_BYTES) return false;
  if (EXCLUDED_PATTERNS.some((pattern) => pattern.test(path))) return false;
  const base = path.split("/").pop() ?? path;
  return TEXT_EXTENSIONS.has(extensionOf(path)) || EXTENSIONLESS_TEXT.has(base);
}

/** A NUL byte in the first 8 KiB is treated as binary content. */
export function looksBinary(buffer) {
  const head = buffer.subarray(0, 8192);
  return head.includes(0);
}

/**
 * Split text into overlapping line windows. A window closes at maxLines or
 * before it would exceed maxChars or the estimated maxTokens; a single line
 * over either limit is truncated. Line numbers are 1-based and inclusive.
 */
export function chunkText(text, options = DEFAULT_CHUNK_OPTIONS) {
  const { maxLines, overlap, maxChars, maxTokens } = { ...DEFAULT_CHUNK_OPTIONS, ...options };
  if (overlap >= maxLines) throw new Error("overlap must be smaller than maxLines");

  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();

  const chunks = [];
  let start = 0;
  while (start < lines.length) {
    let end = start;
    let chars = 0;
    let tokens = 0;
    const parts = [];
    while (end < lines.length && end - start < maxLines) {
      const line = fitLine(lines[end], maxChars, maxTokens);
      const lineTokens = estimateTokens(line);
      if (parts.length > 0 && (chars + line.length + 1 > maxChars || tokens + lineTokens > maxTokens)) break;
      parts.push(line);
      chars += line.length + 1;
      tokens += lineTokens;
      end += 1;
    }
    const body = parts.join("\n");
    if (body.trim().length > 0) {
      chunks.push({ start_line: start + 1, end_line: end, text: body });
    }
    if (end >= lines.length) break;
    // Step back by `overlap` lines, but always advance at least one line.
    start = Math.max(end - overlap, start + 1);
  }
  return chunks;
}

/** Text sent to the embedding model: the path anchors otherwise-generic code. */
export function embeddingInput(path, chunk) {
  return `File: ${path} (lines ${chunk.start_line}-${chunk.end_line})\n${chunk.text}`;
}

export function snippetOf(text) {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > SNIPPET_CHARS ? `${collapsed.slice(0, SNIPPET_CHARS - 1)}…` : collapsed;
}

/**
 * Deterministic vector id (64 hex chars, Vectorize's id limit): identical
 * path, line range and content map to the same id across runs, so an
 * unchanged chunk is overwritten in place rather than duplicated.
 */
export function chunkId(path, chunk) {
  return createHash("sha256")
    .update(`${path}\u0000${chunk.start_line}\u0000${chunk.end_line}\u0000${chunk.text}`)
    .digest("hex");
}
