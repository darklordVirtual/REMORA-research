import { CODEGRAPH_PATHS } from "./codegraph.paths";

export type CodegraphEntry = {
  path: string;
  summary: string;
  kind: "entrypoint" | "core" | "doc" | "worker" | "config" | "test";
  tags: string[];
};

const STOPWORDS = new Set([
  "a", "an", "and", "asset", "assets", "bin", "chart", "doc", "docs",
  "file", "final", "for", "from", "guide", "index", "legacy", "md",
  "notes", "page", "paper", "readme", "src", "the", "to", "v1", "v2",
]);

const ROOT_SUMMARIES: Record<string, string> = {
  "README.md": "Top-level project overview and navigation",
  "CODEGRAPH.md": "Canonical codegraph scope and usage contract",
  "codegraph.yaml": "Machine-readable repository codegraph manifest",
  ".codegraphignore": "Codegraph ignore rules for non-indexed paths",
  "AGENTS.md": "Agent instructions and operating guidance",
  "ARCHITECTURE.md": "High-level system architecture",
  "CHANGELOG.md": "Project change history",
  "NEGATIVE_RESULTS.md": "Documented negative results and failure modes",
  "PORTFOLIO.md": "Project portfolio and evidence overview",
  "SECURITY.md": "Security policy and reporting guidance",
  "LICENSE": "Repository license text",
  "Makefile": "Repository task and automation entrypoint",
};

export const CODEGRAPH_SCOPE = {
  include: ["**/*"],
  exclude: [
    ".git/**",
    "node_modules/**",
    ".pytest_cache/**",
    "__pycache__/**",
    ".remora_session/**",
  ],
  entrypoints: [
    "README.md",
    "CODEGRAPH.md",
    "codegraph.yaml",
    ".codegraphignore",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "NEGATIVE_RESULTS.md",
    "docs/mcp-integration.md",
    "docs/agent_tool_hook.md",
    "docs/use-cases/README.md",
    "remora/README.md",
    "workers/agent-control/README.md",
    "servers/mcp_remora.py",
  ],
  notes: [
    "Repo-wide scope includes tracked source, docs, data, deployment assets, and evidence artifacts.",
    "Ephemeral caches and dependency directories remain excluded.",
  ],
} as const;

function normalizeTokens(value: string): string[] {
  return value
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 1 && !STOPWORDS.has(part));
}

function titleCase(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function humanizeStem(path: string): string {
  return path
    .split("/")
    .pop()!
    .replace(/\.[^.]+$/, "")
    .replace(/^\d+[-_.]*/, "")
    .replace(/[_.-]+/g, " ")
    .trim();
}

function inferKind(path: string): CodegraphEntry["kind"] {
  const lower = path.toLowerCase();
  const base = lower.split("/").pop() ?? lower;

  if (lower.startsWith("workers/")) return "worker";
  if (lower.startsWith("tests/") || base.startsWith("test_") || base.endsWith(".test.py") || base.endsWith("_test.py")) return "test";
  if (base === "readme.md" || base === "codegraph.md" || lower.startsWith("docs/") || lower.startsWith("paper/") || lower.startsWith("enterprise/") || lower.startsWith("deploy/") || lower.startsWith("artifacts/") || lower.startsWith("frontend/") || lower.startsWith("examples/") || lower.startsWith("datasets/") || lower.startsWith(".github/") || lower.startsWith(".claude/")) return "doc";
  if (base === "makefile" || base === ".gitignore" || base === ".gitattributes" || base === "citation.cff" || base === "pyproject.toml" || base === "package.json" || base === "package-lock.json" || base === "bun.lock" || base === "bunfig.toml" || base === "components.json" || base === "eslint.config.js" || base === ".prettierrc" || base === ".prettierignore" || base === "wrangler.toml" || base.endsWith(".yaml") || base.endsWith(".yml") || base.endsWith(".json") || base.endsWith(".toml") || base.endsWith(".cff") || base.endsWith(".ini") || base.endsWith(".cfg")) return "config";
  return "core";
}

function summarizePath(path: string, kind: CodegraphEntry["kind"]): string {
  const rootSummary = ROOT_SUMMARIES[path];
  if (rootSummary) return rootSummary;

  const base = humanizeStem(path);
  const topic = base ? titleCase(base) : path;

  switch (kind) {
    case "entrypoint":
      return `Entry point for ${topic}`;
    case "doc":
      return `Documentation for ${topic}`;
    case "worker":
      return `Cloudflare worker source for ${topic}`;
    case "config":
      return `Configuration for ${topic}`;
    case "test":
      return `Test coverage for ${topic}`;
    case "core":
    default:
      return `Core source for ${topic}`;
  }
}

function tagsFor(path: string, kind: CodegraphEntry["kind"]): string[] {
  const tags = new Set<string>();
  tags.add(kind);

  const parts = path.split("/");
  if (parts.length > 0) {
    tags.add(parts[0].toLowerCase());
  }
  if (parts.length > 1) {
    tags.add(parts[1].toLowerCase());
  }

  const stem = path.split("/").pop()!.replace(/\.[^.]+$/, "");
  for (const token of normalizeTokens(stem)) tags.add(token);
  for (const segment of parts.slice(0, -1)) {
    for (const token of normalizeTokens(segment)) tags.add(token);
  }

  return Array.from(tags).slice(0, 8);
}

export const CODEGRAPH_CATALOG: CodegraphEntry[] = CODEGRAPH_PATHS.map((path) => {
  const kind = inferKind(path);
  return {
    path,
    summary: summarizePath(path, kind),
    kind,
    tags: tagsFor(path, kind),
  };
});

function normalizeQuery(query: string): string[] {
  return query
    .toLowerCase()
    .split(/[^a-z0-9_./-]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function scoreEntry(entry: CodegraphEntry, terms: string[]): number {
  if (!terms.length) return entry.kind === "entrypoint" ? 10 : 1;

  const haystack = `${entry.path} ${entry.summary} ${entry.kind} ${entry.tags.join(" ")}`.toLowerCase();
  let score = 0;

  for (const term of terms) {
    if (entry.path.toLowerCase().includes(term)) score += 8;
    if (entry.summary.toLowerCase().includes(term)) score += 5;
    if (entry.tags.some((tag) => tag.toLowerCase().includes(term))) score += 4;
    if (haystack.includes(term)) score += 1;
  }

  if ((CODEGRAPH_SCOPE.entrypoints as readonly string[]).includes(entry.path)) score += 3;
  return score;
}

export function queryCodegraph(query: string, limit: number): CodegraphEntry[] {
  const terms = normalizeQuery(query);
  return [...CODEGRAPH_CATALOG]
    .map((entry) => ({ entry, score: scoreEntry(entry, terms) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score || a.entry.path.localeCompare(b.entry.path))
    .slice(0, limit)
    .map(({ entry }) => entry);
}

export function buildCodegraphPayload(query: string, limit: number) {
  const entrypoints = CODEGRAPH_SCOPE.entrypoints as readonly string[];
  const matches = query
    ? queryCodegraph(query, limit)
    : CODEGRAPH_CATALOG.filter((entry) => entrypoints.includes(entry.path));

  return {
    service: "remora-agent-control",
    generated_at: new Date().toISOString(),
    query: query || null,
    limit,
    total_files: CODEGRAPH_CATALOG.length,
    scope: CODEGRAPH_SCOPE,
    matches,
  };
}
