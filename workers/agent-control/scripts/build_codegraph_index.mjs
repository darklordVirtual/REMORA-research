#!/usr/bin/env node
// Build (or refresh) the CodeGraph semantic index.
//
// Chunks every tracked, indexable file at HEAD, embeds the chunks with
// Workers AI and upserts them into the Vectorize index that the
// agent-control worker queries for /codegraph?mode=semantic|hybrid.
//
//   node scripts/build_codegraph_index.mjs --dry-run
//   CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_API_TOKEN=... \
//     node scripts/build_codegraph_index.mjs [--version V] [--prune-previous FILE]
//
// The API token needs Workers AI: Read and Vectorize: Edit. A manifest of
// the written vector ids goes to <repo>/.codegraph/ (gitignored); pass the
// previous run's manifest as --prune-previous to delete vectors for chunks
// that no longer exist. After a run, set CODEGRAPH_INDEX_VERSION in
// wrangler.toml to the printed version and redeploy, so stale vectors are
// filtered out even before they are pruned.

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseArgs } from "node:util";

import {
  chunkId,
  chunkText,
  embeddingInput,
  isIndexablePath,
  looksBinary,
  snippetOf,
} from "./codegraph_chunk.mjs";

const EMBED_BATCH = 50;
const UPSERT_BATCH = 500;
const DELETE_BATCH = 1000;
const API = "https://api.cloudflare.com/client/v4";

const { values: args } = parseArgs({
  options: {
    "dry-run": { type: "boolean", default: false },
    "allow-dirty": { type: "boolean", default: false },
    version: { type: "string" },
    index: { type: "string", default: "remora-codegraph" },
    model: { type: "string", default: "@cf/baai/bge-base-en-v1.5" },
    "prune-previous": { type: "string" },
  },
});

function git(repo, ...argv) {
  return execFileSync("git", ["-C", repo, ...argv], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
}

const repo = git(process.cwd(), "rev-parse", "--show-toplevel").trim();
const commit = git(repo, "rev-parse", "HEAD").trim();
const dirty = git(repo, "status", "--porcelain", "--untracked-files=no").trim();
if (dirty && !args["allow-dirty"]) {
  console.error("Refusing to index a dirty tree: vectors are stamped with HEAD's commit.");
  console.error("Commit or stash tracked changes, or pass --allow-dirty for a local experiment.");
  process.exit(2);
}
const version = args.version ?? `${commit.slice(0, 12)}-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}`;
if (!/^[A-Za-z0-9._-]{1,64}$/.test(version)) {
  console.error(`Invalid --version ${JSON.stringify(version)}: use 1-64 chars of [A-Za-z0-9._-].`);
  process.exit(2);
}

// ── Collect chunks ────────────────────────────────────────────────────────────
const tracked = git(repo, "ls-files", "-z").split("\0").filter(Boolean);
const records = [];
let filesIndexed = 0;
let skipped = 0;
for (const path of tracked) {
  let size;
  try {
    const st = statSync(join(repo, path));
    if (!st.isFile()) { skipped += 1; continue; }
    size = st.size;
  } catch {
    skipped += 1; // deleted in the working tree, or a submodule
    continue;
  }
  if (!isIndexablePath(path, size)) { skipped += 1; continue; }
  const buffer = readFileSync(join(repo, path));
  if (looksBinary(buffer)) { skipped += 1; continue; }
  const chunks = chunkText(buffer.toString("utf8"));
  if (chunks.length === 0) { skipped += 1; continue; }
  filesIndexed += 1;
  for (const chunk of chunks) {
    records.push({
      id: chunkId(path, chunk),
      input: embeddingInput(path, chunk),
      metadata: {
        path,
        start_line: chunk.start_line,
        end_line: chunk.end_line,
        snippet: snippetOf(chunk.text),
        commit,
        index_version: version,
      },
    });
  }
}

const summary = {
  version,
  commit,
  index: args.index,
  model: args.model,
  tracked_files: tracked.length,
  files_indexed: filesIndexed,
  files_skipped: skipped,
  chunks: records.length,
};
console.log(JSON.stringify(summary, null, 2));
if (args["dry-run"]) process.exit(0);

// ── Cloudflare API ────────────────────────────────────────────────────────────
const account = process.env.CLOUDFLARE_ACCOUNT_ID;
const token = process.env.CLOUDFLARE_API_TOKEN;
if (!account || !token) {
  console.error("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required (or use --dry-run).");
  process.exit(2);
}

async function cf(pathname, init) {
  for (let attempt = 1; ; attempt += 1) {
    const response = await fetch(`${API}/accounts/${account}${pathname}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, ...(init.headers ?? {}) },
    });
    if ((response.status === 429 || response.status >= 500) && attempt < 4) {
      await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
      continue;
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.success === false) {
      const detail = JSON.stringify(body.errors ?? body).slice(0, 500);
      throw new Error(`${init.method ?? "GET"} ${pathname} -> HTTP ${response.status}: ${detail}`);
    }
    return body.result;
  }
}

async function embed(texts) {
  const result = await cf(`/ai/run/${args.model}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: texts }),
  });
  if (!Array.isArray(result?.data) || result.data.length !== texts.length) {
    throw new Error("embedding response did not return one vector per input");
  }
  return result.data;
}

const indexPath = `/vectorize/v2/indexes/${encodeURIComponent(args.index)}`;

let pending = [];
let upserted = 0;
async function flush() {
  if (pending.length === 0) return;
  const ndjson = pending.map((vector) => JSON.stringify(vector)).join("\n");
  await cf(`${indexPath}/upsert`, {
    method: "POST",
    headers: { "Content-Type": "application/x-ndjson" },
    body: ndjson,
  });
  upserted += pending.length;
  pending = [];
  console.log(`upserted ${upserted}/${records.length}`);
}

for (let i = 0; i < records.length; i += EMBED_BATCH) {
  const batch = records.slice(i, i + EMBED_BATCH);
  const vectors = await embed(batch.map((record) => record.input));
  batch.forEach((record, j) => pending.push({ id: record.id, values: vectors[j], metadata: record.metadata }));
  if (pending.length >= UPSERT_BATCH) await flush();
}
await flush();

const ids = records.map((record) => record.id);
mkdirSync(join(repo, ".codegraph"), { recursive: true });
const manifestPath = join(repo, ".codegraph", `semantic-manifest-${version}.json`);
writeFileSync(manifestPath, JSON.stringify({ ...summary, ids }, null, 2));
console.log(`manifest: ${manifestPath}`);

if (args["prune-previous"]) {
  const previous = JSON.parse(readFileSync(args["prune-previous"], "utf8"));
  const current = new Set(ids);
  const stale = (previous.ids ?? []).filter((id) => !current.has(id));
  for (let i = 0; i < stale.length; i += DELETE_BATCH) {
    await cf(`${indexPath}/delete_by_ids`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: stale.slice(i, i + DELETE_BATCH) }),
    });
  }
  console.log(`pruned ${stale.length} stale vectors from ${args["prune-previous"]}`);
}

console.log(`\nNext: set CODEGRAPH_INDEX_VERSION = "${version}" in wrangler.toml and redeploy.`);
