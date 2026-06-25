import type { AssetInfo } from "../types";

export function AssetCAD({ asset }: { asset: AssetInfo }) {
  return (
    <div className="border border-border bg-muted/5">
      <svg viewBox="0 0 280 130" className="w-full block" style={{ height: 110 }}>
        <line x1="0" y1="118" x2="280" y2="118" stroke="var(--border)" strokeWidth="1" />
        <line x1="0" y1="12" x2="280" y2="12" stroke="var(--border)" strokeWidth="1" />
        <line x1="20" y1="12" x2="20" y2="118" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="100" y1="12" x2="100" y2="118" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="180" y1="12" x2="180" y2="118" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="260" y1="12" x2="260" y2="118" stroke="var(--border)" strokeWidth="0.75" />
        {/* Left bay */}
        <rect
          x="27"
          y="28"
          width="60"
          height="40"
          fill="none"
          stroke="var(--border)"
          strokeWidth="0.75"
        />
        <text
          x="57"
          y="52"
          textAnchor="middle"
          fill="var(--muted-foreground)"
          fontSize="8"
          fontFamily="monospace"
          opacity="0.4"
        >
          A-01
        </text>
        {/* Centre bay — escalated */}
        <rect
          x="107"
          y="22"
          width="60"
          height="50"
          fill="rgba(239,68,68,0.05)"
          stroke="var(--state-escalate)"
          strokeWidth="1.5"
        />
        <circle
          cx="137"
          cy="42"
          r="13"
          fill="none"
          stroke="var(--state-escalate)"
          strokeWidth="1"
          strokeDasharray="2.5 2"
        />
        <text
          x="137"
          y="46"
          textAnchor="middle"
          fill="var(--state-escalate)"
          fontSize="9"
          fontFamily="monospace"
          fontWeight="bold"
        >
          {asset.id}
        </text>
        <text
          x="137"
          y="63"
          textAnchor="middle"
          fill="var(--state-escalate)"
          fontSize="6.5"
          fontFamily="monospace"
          opacity="0.85"
        >
          OVERDUE
        </text>
        {/* Annotation */}
        <line
          x1="167"
          y1="38"
          x2="205"
          y2="22"
          stroke="var(--state-escalate)"
          strokeWidth="0.75"
          strokeDasharray="3 2"
          opacity="0.75"
        />
        <circle cx="167" cy="38" r="2" fill="var(--state-escalate)" opacity="0.75" />
        <text
          x="208"
          y="20"
          fill="var(--state-escalate)"
          fontSize="6.5"
          fontFamily="monospace"
          opacity="0.9"
        >
          INSPECTION
        </text>
        <text
          x="208"
          y="30"
          fill="var(--state-escalate)"
          fontSize="6.5"
          fontFamily="monospace"
          opacity="0.9"
        >
          OVERDUE
        </text>
        {/* Right bay */}
        <rect
          x="187"
          y="32"
          width="60"
          height="34"
          fill="none"
          stroke="var(--border)"
          strokeWidth="0.75"
        />
        <text
          x="217"
          y="53"
          textAnchor="middle"
          fill="var(--muted-foreground)"
          fontSize="8"
          fontFamily="monospace"
          opacity="0.4"
        >
          C-03
        </text>
        {/* Pipe connections */}
        <line x1="20" y1="48" x2="27" y2="48" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="87" y1="48" x2="107" y2="48" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="167" y1="48" x2="187" y2="48" stroke="var(--border)" strokeWidth="0.75" />
        <line x1="247" y1="48" x2="260" y2="48" stroke="var(--border)" strokeWidth="0.75" />
        {/* Zone labels */}
        <text
          x="57"
          y="126"
          textAnchor="middle"
          fill="var(--muted-foreground)"
          fontSize="7"
          fontFamily="monospace"
          opacity="0.4"
        >
          Zone A
        </text>
        <text
          x="137"
          y="126"
          textAnchor="middle"
          fill="var(--state-escalate)"
          fontSize="7"
          fontFamily="monospace"
          opacity="0.7"
        >
          Zone B ←
        </text>
        <text
          x="217"
          y="126"
          textAnchor="middle"
          fill="var(--muted-foreground)"
          fontSize="7"
          fontFamily="monospace"
          opacity="0.4"
        >
          Zone C
        </text>
      </svg>
      <div className="px-3 py-2 grid grid-cols-2 gap-x-5 gap-y-0.5 border-t border-border/40 font-mono text-[10px]">
        <span className="text-muted-foreground/58">Asset</span>{" "}
        <span className="text-foreground/82">
          {asset.id} — {asset.type}
        </span>
        <span className="text-muted-foreground/58">Zone</span>{" "}
        <span className="text-foreground/82">{asset.zone}</span>
        <span className="text-muted-foreground/58">System</span>{" "}
        <span className="text-foreground/82">{asset.system}</span>
        <span className="text-muted-foreground/58">Criticality</span>{" "}
        <span className="text-foreground/82">{asset.criticality}</span>
        <span className="text-muted-foreground/58">Last insp.</span>{" "}
        <span className="text-foreground/82">{asset.lastInspection}</span>
        <span className="text-muted-foreground/58">Overdue by</span>{" "}
        <span className="text-state-escalate font-medium">
          {asset.nextDue} · {asset.overdueBy}
        </span>
        <span className="text-muted-foreground/58">CMMS ref</span>{" "}
        <span className="text-foreground/82">{asset.cmmsRef}</span>
        <span className="text-muted-foreground/58">CAD match</span>{" "}
        <span className="text-state-accept/82">Matched by asset_id</span>
      </div>
    </div>
  );
}
