import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { PageHeader, SectionLabel } from "@/components/primitives";
import {
  remoraPublic,
  verdictTone,
  type ExecuteResponse,
  type LawMatch,
  type RagQueryResponse,
  type Verdict,
  type WorkerStatus,
} from "@/lib/remora";
import { createSession, endSession, executeTool, getAudit } from "@/lib/remora.functions";

export const Route = createFileRoute("/console")({
  head: () => ({
    meta: [
      { title: "REMORA Console — interactive governance demo" },
      {
        name: "description",
        content:
          "Live interaction with the REMORA control plane: verify claims, search Norwegian law, query the RAG oracle, and inspect the audit log.",
      },
    ],
  }),
  component: ConsolePage,
});

// ---------- Local types ----------

type ToolKey = "verify" | "law" | "rag" | "citation" | "artifact";

type ToolResult =
  | { kind: "execute"; data: ExecuteResponse }
  | { kind: "rag"; data: RagQueryResponse }
  | { kind: "law"; data: { query: string; total: number; matches: LawMatch[] } }
  | { kind: "citation"; data: Awaited<ReturnType<typeof remoraPublic.verifyCitation>> }
  | { kind: "error"; message: string };

// ---------- Session persistence ----------

const SESSION_STORAGE_KEY = "remora.session";

function loadSession(): { id: string; user: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as { id: string; user: string }) : null;
  } catch {
    return null;
  }
}

function saveSession(s: { id: string; user: string } | null) {
  if (typeof window === "undefined") return;
  if (s) window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(s));
  else window.localStorage.removeItem(SESSION_STORAGE_KEY);
}

// ---------- Page ----------

function ConsolePage() {
  const [session, setSession] = useState<{ id: string; user: string } | null>(null);
  const [tool, setTool] = useState<ToolKey>("verify");
  const [result, setResult] = useState<ToolResult | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    setSession(loadSession());
  }, []);

  const createFn = useServerFn(createSession);
  const endFn = useServerFn(endSession);

  const startMut = useMutation({
    mutationFn: async (user: string) => createFn({ data: { user_id: user, user_label: user } }),
    onSuccess: (data, user) => {
      const next = { id: data.session_id, user };
      saveSession(next);
      setSession(next);
      setResult(null);
    },
  });

  const stopMut = useMutation({
    mutationFn: async (id: string) => endFn({ data: { session_id: id } }),
    onSettled: () => {
      saveSession(null);
      setSession(null);
      setResult(null);
      queryClient.invalidateQueries({ queryKey: ["audit"] });
    },
  });

  return (
    <div className="mx-auto max-w-6xl px-6 pt-16 pb-24">
      <PageHeader
        eyebrow="REMORA · live control plane"
        title="Console."
        lede="Open a governed session, invoke the live tool catalog, and inspect every decision the audit log records. Calls are proxied server-side; no control secret reaches the browser."
      />

      <SystemStatus />

      <SessionBar
        session={session}
        starting={startMut.isPending}
        stopping={stopMut.isPending}
        onStart={(u) => startMut.mutate(u)}
        onStop={(id) => stopMut.mutate(id)}
        error={startMut.error?.message ?? stopMut.error?.message ?? null}
      />

      <section className="mt-12">
        <SectionLabel number="02">Tool</SectionLabel>
        <ToolTabs value={tool} onChange={setTool} />
        <div className="mt-8 grid gap-12 lg:grid-cols-[1fr_1fr]">
          <ToolForm
            tool={tool}
            session={session}
            onResult={(r) => {
              setResult(r);
              if (r.kind === "execute") {
                queryClient.invalidateQueries({ queryKey: ["audit", session?.id] });
              }
            }}
          />
          <ResultPanel result={result} />
        </div>
      </section>

      <AuditLog sessionId={session?.id} />
    </div>
  );
}

// ---------- System status ----------

function SystemStatus() {
  const { data } = useQuery({
    queryKey: ["remora-status"],
    queryFn: () => remoraPublic.pingAll(),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const workers: WorkerStatus[] = data ?? [
    { name: "Agent Control", url: "", ok: false, latency_ms: 0 },
    { name: "RAG Oracle", url: "", ok: false, latency_ms: 0 },
    { name: "Law Search", url: "", ok: false, latency_ms: 0 },
  ];

  return (
    <section className="mt-12 border-t border-border pt-8">
      <SectionLabel number="01">Workers</SectionLabel>
      <div className="mt-6 grid gap-px bg-border md:grid-cols-3">
        {workers.map((w) => (
          <div key={w.name} className="bg-background p-5">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs">{w.name}</span>
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  w.ok ? "bg-state-accept" : "bg-state-escalate",
                )}
              />
            </div>
            <div className="mt-2 font-mono text-[11px] text-muted-foreground tabular-nums">
              {w.ok ? `${w.latency_ms} ms` : "unreachable"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------- Session bar ----------

function SessionBar({
  session,
  starting,
  stopping,
  onStart,
  onStop,
  error,
}: {
  session: { id: string; user: string } | null;
  starting: boolean;
  stopping: boolean;
  onStart: (user: string) => void;
  onStop: (id: string) => void;
  error: string | null;
}) {
  const [user, setUser] = useState("demo-user");

  return (
    <section className="mt-10 border border-border p-5">
      <div className="flex flex-wrap items-end gap-4">
        {session ? (
          <>
            <Field label="Session">
              <code className="font-mono text-xs">{session.id}</code>
            </Field>
            <Field label="User">
              <span className="text-sm">{session.user}</span>
            </Field>
            <button
              onClick={() => onStop(session.id)}
              disabled={stopping}
              className="ml-auto border border-foreground px-4 py-2 font-mono text-xs uppercase tracking-widest hover:bg-foreground hover:text-background disabled:opacity-40"
            >
              {stopping ? "Ending…" : "End session"}
            </button>
          </>
        ) : (
          <>
            <Field label="User ID">
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                className="bg-transparent border-b border-border focus:border-foreground outline-none py-1 text-sm font-mono w-48"
              />
            </Field>
            <button
              onClick={() => onStart(user.trim() || "demo-user")}
              disabled={starting}
              className="ml-auto border border-foreground bg-foreground text-background px-4 py-2 font-mono text-xs uppercase tracking-widest hover:bg-signal hover:border-signal disabled:opacity-40"
            >
              {starting ? "Opening…" : "Open session"}
            </button>
          </>
        )}
      </div>
      {error && <div className="mt-4 font-mono text-xs text-state-escalate">{error}</div>}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

// ---------- Tool tabs ----------

const TOOLS: { key: ToolKey; label: string; sub: string }[] = [
  { key: "verify", label: "Verify Claim", sub: "remora_verify_claim" },
  { key: "law", label: "Search Law", sub: "law-search · public" },
  { key: "rag", label: "RAG Query", sub: "rag-oracle · public" },
  { key: "citation", label: "Verify Citation", sub: "law-search · public" },
  { key: "artifact", label: "Store Artifact", sub: "store_artifact" },
];

function ToolTabs({ value, onChange }: { value: ToolKey; onChange: (k: ToolKey) => void }) {
  return (
    <div className="mt-6 grid gap-px bg-border md:grid-cols-5">
      {TOOLS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "bg-background p-4 text-left transition-colors",
            value === t.key ? "ring-1 ring-foreground -m-px" : "hover:bg-muted",
          )}
        >
          <div className="text-sm font-medium">{t.label}</div>
          <div className="mt-1 font-mono text-[10px] text-muted-foreground truncate">{t.sub}</div>
        </button>
      ))}
    </div>
  );
}

// ---------- Tool forms ----------

function ToolForm({
  tool,
  session,
  onResult,
}: {
  tool: ToolKey;
  session: { id: string; user: string } | null;
  onResult: (r: ToolResult) => void;
}) {
  const execFn = useServerFn(executeTool);
  const [pending, setPending] = useState(false);

  async function run(action: () => Promise<ToolResult>) {
    setPending(true);
    try {
      onResult(await action());
    } catch (e) {
      onResult({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      setPending(false);
    }
  }

  switch (tool) {
    case "verify":
      return (
        <VerifyClaimForm
          disabled={!session || pending}
          pending={pending}
          requiresSession={!session}
          onSubmit={(payload) =>
            run(async () => ({
              kind: "execute",
              data: await execFn({
                data: {
                  tool: "remora_verify_claim",
                  input: payload,
                  session_id: session!.id,
                  user_id: session!.user,
                },
              }),
            }))
          }
        />
      );
    case "law":
      return (
        <LawSearchForm
          pending={pending}
          onSubmit={(body) =>
            run(async () => ({
              kind: "law",
              data: await remoraPublic.lawSearch(body),
            }))
          }
        />
      );
    case "rag":
      return (
        <RagQueryForm
          pending={pending}
          onSubmit={(body) =>
            run(async () => ({
              kind: "rag",
              data: await remoraPublic.ragQuery(body),
            }))
          }
        />
      );
    case "citation":
      return (
        <CitationForm
          pending={pending}
          onSubmit={(c) =>
            run(async () => ({
              kind: "citation",
              data: await remoraPublic.verifyCitation(c),
            }))
          }
        />
      );
    case "artifact":
      return (
        <StoreArtifactForm
          disabled={!session || pending}
          pending={pending}
          requiresSession={!session}
          onSubmit={(payload) =>
            run(async () => ({
              kind: "execute",
              data: await execFn({
                data: {
                  tool: "store_artifact",
                  input: payload,
                  session_id: session!.id,
                  user_id: session!.user,
                },
              }),
            }))
          }
        />
      );
  }
}

function FormShell({
  children,
  onSubmit,
  pending,
  warn,
  cta = "Execute",
}: {
  children: React.ReactNode;
  onSubmit: () => void;
  pending: boolean;
  warn?: string | null;
  cta?: string;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="space-y-5"
    >
      {children}
      {warn && <div className="font-mono text-[11px] text-state-escalate">{warn}</div>}
      <button
        type="submit"
        disabled={pending}
        className="border border-foreground bg-foreground text-background px-5 py-2 font-mono text-xs uppercase tracking-widest hover:bg-signal hover:border-signal disabled:opacity-40"
      >
        {pending ? "Running…" : cta} →
      </button>
    </form>
  );
}

function LabeledTextarea({
  label,
  value,
  onChange,
  hint,
  rows = 3,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  rows?: number;
}) {
  return (
    <label className="block">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        className="mt-2 w-full border border-border bg-background p-3 text-sm focus:border-foreground outline-none font-sans"
      />
      {hint && <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div>}
    </label>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-2 w-full border border-border bg-background p-3 text-sm focus:border-foreground outline-none font-mono"
      />
    </label>
  );
}

function LabeledSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="block">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-full border border-border bg-background p-3 text-sm focus:border-foreground outline-none font-mono"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function VerifyClaimForm({
  disabled,
  pending,
  requiresSession,
  onSubmit,
}: {
  disabled: boolean;
  pending: boolean;
  requiresSession: boolean;
  onSubmit: (input: { claim: string; context?: string; domain?: string }) => void;
}) {
  const [claim, setClaim] = useState("GDPR § 17 gir rett til sletting uten unntak");
  const [context, setContext] = useState("");
  const [domain, setDomain] = useState("law");
  return (
    <FormShell
      pending={pending}
      warn={requiresSession ? "Open a session to invoke audited tools." : null}
      onSubmit={() => {
        if (disabled) return;
        onSubmit({ claim, context: context || undefined, domain });
      }}
    >
      <LabeledTextarea label="Claim" value={claim} onChange={setClaim} rows={3} />
      <LabeledTextarea label="Context (optional)" value={context} onChange={setContext} rows={2} />
      <LabeledSelect
        label="Domain"
        value={domain}
        onChange={setDomain}
        options={[
          { value: "law", label: "law" },
          { value: "medical", label: "medical" },
          { value: "technical", label: "technical" },
          { value: "general", label: "general" },
        ]}
      />
    </FormShell>
  );
}

function LawSearchForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: (body: { query: string; top_k: number; filter?: Record<string, string> }) => void;
}) {
  const [query, setQuery] = useState("inkasso varsel betalingsfrist");
  const [topK, setTopK] = useState(5);
  const [domain, setDomain] = useState("");
  return (
    <FormShell
      pending={pending}
      onSubmit={() =>
        onSubmit({
          query,
          top_k: topK,
          filter: domain ? { domain } : undefined,
        })
      }
    >
      <LabeledTextarea label="Query" value={query} onChange={setQuery} rows={2} />
      <div className="grid grid-cols-2 gap-4">
        <LabeledInput
          label="Top K"
          value={String(topK)}
          onChange={(v) => setTopK(Math.max(1, Math.min(10, Number(v) || 5)))}
          type="number"
        />
        <LabeledInput
          label="Domain filter (optional)"
          value={domain}
          onChange={setDomain}
          placeholder="inkassoloven"
        />
      </div>
    </FormShell>
  );
}

function RagQueryForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: (body: {
    query: string;
    domain?: string;
    top_k?: number;
    use_case: "legal" | "security" | "general";
    complexity: "auto" | "low" | "high";
    dual_consensus: boolean;
  }) => void;
}) {
  const [query, setQuery] = useState(
    "Har en leietaker rett til å si opp leieavtalen med 1 måneds varsel?",
  );
  const [domain, setDomain] = useState("husleie");
  const [useCase, setUseCase] = useState<"legal" | "security" | "general">("legal");
  const [complexity, setComplexity] = useState<"auto" | "low" | "high">("auto");
  const [dual, setDual] = useState(false);
  return (
    <FormShell
      pending={pending}
      onSubmit={() =>
        onSubmit({
          query,
          domain: domain || undefined,
          top_k: 5,
          use_case: useCase,
          complexity,
          dual_consensus: dual,
        })
      }
    >
      <LabeledTextarea label="Query" value={query} onChange={setQuery} rows={3} />
      <div className="grid grid-cols-2 gap-4">
        <LabeledInput label="Domain" value={domain} onChange={setDomain} placeholder="husleie" />
        <LabeledSelect
          label="Use case"
          value={useCase}
          onChange={(v) => setUseCase(v as typeof useCase)}
          options={[
            { value: "legal", label: "legal" },
            { value: "security", label: "security" },
            { value: "general", label: "general" },
          ]}
        />
        <LabeledSelect
          label="Complexity"
          value={complexity}
          onChange={(v) => setComplexity(v as typeof complexity)}
          options={[
            { value: "auto", label: "auto" },
            { value: "low", label: "low (8B)" },
            { value: "high", label: "high (70B)" },
          ]}
        />
        <label className="flex items-end gap-2 pb-3">
          <input
            type="checkbox"
            checked={dual}
            onChange={(e) => setDual(e.target.checked)}
            className="h-4 w-4 accent-current"
          />
          <span className="font-mono text-xs uppercase tracking-wider">Dual consensus</span>
        </label>
      </div>
    </FormShell>
  );
}

function CitationForm({
  pending,
  onSubmit,
}: {
  pending: boolean;
  onSubmit: (citation: string) => void;
}) {
  const [c, setC] = useState("HR-2021-2847-A");
  return (
    <FormShell pending={pending} onSubmit={() => onSubmit(c)}>
      <LabeledInput label="Citation" value={c} onChange={setC} />
      <div className="text-[11px] text-muted-foreground">
        Checks the DCE legal database for the exact citation and a vector neighbor.
      </div>
    </FormShell>
  );
}

function StoreArtifactForm({
  disabled,
  pending,
  requiresSession,
  onSubmit,
}: {
  disabled: boolean;
  pending: boolean;
  requiresSession: boolean;
  onSubmit: (input: {
    key: string;
    content: string;
    content_type?: string;
    approved?: boolean;
  }) => void;
}) {
  const [key, setKey] = useState("demo/report.md");
  const [content, setContent] = useState("# REMORA demo artifact\n\nGenerated from the console.");
  const [contentType, setContentType] = useState("text/markdown");
  const [approved, setApproved] = useState(false);
  return (
    <FormShell
      pending={pending}
      warn={requiresSession ? "Open a session to invoke audited tools." : null}
      onSubmit={() => {
        if (disabled) return;
        onSubmit({ key, content, content_type: contentType, approved });
      }}
    >
      <LabeledInput label="Key" value={key} onChange={setKey} />
      <LabeledTextarea label="Content" value={content} onChange={setContent} rows={5} />
      <div className="grid grid-cols-2 gap-4">
        <LabeledInput label="Content type" value={contentType} onChange={setContentType} />
        <label className="flex items-end gap-2 pb-3">
          <input
            type="checkbox"
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
            className="h-4 w-4 accent-current"
          />
          <span className="font-mono text-xs uppercase tracking-wider">Approved (commit)</span>
        </label>
      </div>
    </FormShell>
  );
}

// ---------- Result panel ----------

function ResultPanel({ result }: { result: ToolResult | null }) {
  if (!result) {
    return (
      <div className="border border-dashed border-border p-8 text-sm text-muted-foreground">
        Execute a tool to see the verdict, confidence and raw response here.
      </div>
    );
  }

  if (result.kind === "error") {
    return (
      <div className="border border-state-escalate/40 bg-state-escalate/5 p-5">
        <SectionLabel>Error</SectionLabel>
        <pre className="mt-3 font-mono text-xs whitespace-pre-wrap break-words text-state-escalate">
          {result.message}
        </pre>
      </div>
    );
  }

  if (result.kind === "execute") {
    return <ExecuteResultView data={result.data} />;
  }

  if (result.kind === "rag") {
    return <RagResultView data={result.data} />;
  }

  if (result.kind === "law") {
    return <LawResultView data={result.data} />;
  }

  return <CitationResultView data={result.data} />;
}

function ExecuteResultView({ data }: { data: ExecuteResponse }) {
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        {data.verdict ? <VerdictChip verdict={data.verdict} /> : null}
        {typeof data.confidence === "number" ? <ConfidenceGauge value={data.confidence} /> : null}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular-nums">
          {data.duration_ms} ms · audit #{data.audit_id}
        </span>
      </div>
      <KeyValueGrid
        items={[
          ["tool", data.tool],
          ["success", String(data.success)],
          ["approval_required", String(data.approval_required)],
          ["session", data.session_id.slice(0, 8) + "…"],
        ]}
      />
      <RawJson value={data.output} />
    </div>
  );
}

function RagResultView({ data }: { data: RagQueryResponse }) {
  const verdict: Verdict =
    data.confidence >= 0.75
      ? data.answer
        ? "VERIFIED"
        : "CONTRADICTED"
      : data.confidence < 0.45
        ? "UNCERTAIN"
        : "SUSPICIOUS";
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        <VerdictChip verdict={verdict} />
        <ConfidenceGauge value={data.confidence} />
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{data.model}</span>
      </div>
      <div>
        <SectionLabel>Claim</SectionLabel>
        <p className="mt-2 font-serif text-xl leading-snug">{data.claim}</p>
      </div>
      {data.sources.length > 0 && (
        <div>
          <SectionLabel>Sources</SectionLabel>
          <ul className="mt-2 space-y-1 font-mono text-xs">
            {data.sources.map((s) => (
              <li key={s} className="border-l-2 border-signal pl-3">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
      <KeyValueGrid
        items={[
          ["retrieved_chunks", String(data.retrieved_chunks)],
          ["reranked", String(data.reranked)],
          ["cache_hit", String(data.cache_hit)],
          ["use_case", data.use_case],
        ]}
      />
    </div>
  );
}

function LawResultView({ data }: { data: { query: string; total: number; matches: LawMatch[] } }) {
  return (
    <div className="space-y-4">
      <SectionLabel>{data.total} matches</SectionLabel>
      <div className="space-y-3">
        {data.matches.map((m) => (
          <article key={m.id} className="border border-border p-4">
            <div className="flex items-baseline justify-between gap-3">
              <div className="font-medium">{m.title}</div>
              <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                score {m.score.toFixed(3)}
              </span>
            </div>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              {m.law_id} · {m.section}
            </div>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground line-clamp-5">
              {m.content}
            </p>
            {m.url && (
              <a
                href={m.url}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-block font-mono text-[11px] text-signal hover:underline"
              >
                lovdata.no ↗
              </a>
            )}
          </article>
        ))}
        {data.matches.length === 0 && (
          <div className="text-sm text-muted-foreground">No matches.</div>
        )}
      </div>
    </div>
  );
}

function CitationResultView({
  data,
}: {
  data: Awaited<ReturnType<typeof remoraPublic.verifyCitation>>;
}) {
  const tone =
    data.verdict === "FOUND_IN_DATABASE"
      ? "accept"
      : data.verdict === "POSSIBLE_MATCH_VECTOR"
        ? "verify"
        : "escalate";
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "border px-2 py-0.5 font-mono text-[11px] tracking-widest",
            TONE_CLASS[tone],
          )}
        >
          {data.verdict}
        </span>
        <span className="font-mono text-xs">{data.citation}</span>
      </div>
      <p className="text-sm text-muted-foreground">{data.note}</p>
      <KeyValueGrid
        items={[
          ["found_in_d1", String(data.found_in_d1)],
          ["d1_matches", String(data.d1_matches.length)],
          ["vector_matches", String(data.vector_matches.length)],
        ]}
      />
      {data.vector_matches.length > 0 && (
        <div>
          <SectionLabel>Vector neighbors</SectionLabel>
          <ul className="mt-2 space-y-1 font-mono text-xs">
            {data.vector_matches.map((m) => (
              <li key={m.id} className="flex justify-between border-b border-border/60 py-1">
                <span>{m.id}</span>
                <span className="tabular-nums text-muted-foreground">{m.score.toFixed(3)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const TONE_CLASS: Record<string, string> = {
  accept: "text-state-accept border-state-accept",
  verify: "text-state-verify border-state-verify",
  abstain: "text-state-abstain border-state-abstain",
  escalate: "text-state-escalate border-state-escalate",
};

function VerdictChip({ verdict }: { verdict: Verdict }) {
  const tone = verdictTone(verdict);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border px-2 py-0.5 font-mono text-[11px] tracking-widest",
        TONE_CLASS[tone],
      )}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {verdict}
    </span>
  );
}

function ConfidenceGauge({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-3">
      <div className="h-1.5 w-32 bg-muted overflow-hidden">
        <div className="h-full bg-foreground" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs tabular-nums">{pct}%</span>
    </div>
  );
}

function KeyValueGrid({ items }: { items: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-px bg-border border border-border">
      {items.map(([k, v]) => (
        <div key={k} className="bg-background p-3">
          <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            {k}
          </dt>
          <dd className="mt-1 font-mono text-xs break-all">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function RawJson({ value }: { value: unknown }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);
  return (
    <details className="border border-border">
      <summary className="cursor-pointer p-3 font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground">
        Raw response
      </summary>
      <pre className="max-h-80 overflow-auto bg-muted p-4 font-mono text-[11px] leading-relaxed">
        {text}
      </pre>
    </details>
  );
}

// ---------- Audit log ----------

function AuditLog({ sessionId }: { sessionId?: string }) {
  const fetchAudit = useServerFn(getAudit);
  const { data, isFetching, refetch } = useQuery({
    queryKey: ["audit", sessionId],
    queryFn: () =>
      fetchAudit({
        data: sessionId
          ? { session_id: sessionId, limit: 50, offset: 0 }
          : { limit: 50, offset: 0 },
      }),
    refetchInterval: sessionId ? 8_000 : false,
  });

  return (
    <section className="mt-20 border-t border-border pt-10">
      <div className="flex items-baseline justify-between">
        <SectionLabel number="03">Audit log {sessionId ? "· session" : "· global"}</SectionLabel>
        <button
          onClick={() => refetch()}
          className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground"
        >
          {isFetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <div className="mt-6 overflow-x-auto border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40">
              {["#", "Time", "Tool", "Verdict", "Conf.", "Duration", "Input"].map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-widest text-muted-foreground font-normal"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((row) => (
              <tr key={row.id} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-2 font-mono text-xs tabular-nums">{row.id}</td>
                <td className="px-3 py-2 font-mono text-xs">
                  {new Date(row.ts).toLocaleTimeString()}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{row.tool_called}</td>
                <td className="px-3 py-2">
                  {row.verdict ? <VerdictChip verdict={row.verdict as Verdict} /> : "—"}
                </td>
                <td className="px-3 py-2 font-mono text-xs tabular-nums">
                  {row.confidence != null ? row.confidence.toFixed(2) : "—"}
                </td>
                <td className="px-3 py-2 font-mono text-xs tabular-nums">
                  {row.duration_ms != null ? `${row.duration_ms} ms` : "—"}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground max-w-md truncate">
                  {row.input_preview}
                </td>
              </tr>
            ))}
            {(!data || data.rows.length === 0) && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No audit rows yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
