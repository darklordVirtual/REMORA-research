export function ArchitectureDiagram() {
  return (
    <div className="my-12 border border-border bg-card p-6 md:p-10">
      <svg
        viewBox="0 0 760 360"
        className="w-full h-auto"
        role="img"
        aria-label="REMORA control plane"
      >
        <defs>
          <marker
            id="arr"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
          </marker>
        </defs>
        <g className="text-border" stroke="currentColor" fill="none" strokeWidth="1">
          {/* Top row */}
          <Box x={20} y={60} label="Input claim / tool call" />
          <Box x={200} y={20} label="Oracle pool" sub="Independent models" />
          <Box x={380} y={20} label="Canonicalize φ(output)" />
          <Box x={560} y={20} label="Consensus C, ρ, support" />
          <Box x={200} y={120} label="Evidence path" sub="RAG / verifier" />
          <Box x={380} y={120} label="Uncertainty H, D, T" sub="phase regime" />
          <Box x={560} y={120} label="Policy gate" sub="OPA / rules" />
          <Box x={380} y={230} label="Decision" sub="ACCEPT · VERIFY · ABSTAIN · ESCALATE" wide />
          <Box x={560} y={230} label="Action gate" sub="PreToolUse hook" />
          <Box x={200} y={310} label="Audit & telemetry" sub="RDF · OTel · envelope" wide />
        </g>
        <g
          className="text-muted-foreground"
          stroke="currentColor"
          fill="none"
          markerEnd="url(#arr)"
        >
          <path d="M170,80 L200,55" />
          <path d="M170,90 L200,135" />
          <path d="M330,40 L380,40" />
          <path d="M510,40 L560,40" />
          <path d="M330,140 L380,140" />
          <path d="M510,140 L560,140" />
          <path d="M620,75 L620,120" />
          <path d="M620,175 L500,230" />
          <path d="M460,170 L460,230" />
          <path d="M540,260 L560,260" />
          <path d="M460,275 L330,310" />
        </g>
      </svg>
      <div className="mt-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        Figure 1 · Control-plane architecture
      </div>
    </div>
  );
}

function Box({
  x,
  y,
  label,
  sub,
  wide,
}: {
  x: number;
  y: number;
  label: string;
  sub?: string;
  wide?: boolean;
}) {
  const w = wide ? 180 : 150;
  const h = sub ? 56 : 40;
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect width={w} height={h} className="fill-background" />
      <text
        x={w / 2}
        y={sub ? 22 : 24}
        textAnchor="middle"
        className="fill-foreground font-sans"
        fontSize="12"
        stroke="none"
      >
        {label}
      </text>
      {sub && (
        <text
          x={w / 2}
          y={42}
          textAnchor="middle"
          className="fill-muted-foreground font-mono"
          fontSize="9"
          stroke="none"
        >
          {sub}
        </text>
      )}
    </g>
  );
}
