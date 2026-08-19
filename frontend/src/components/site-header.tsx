import { Link } from "@tanstack/react-router";
import { META } from "@/content/whitepaper";

/**
 * Phase 11: the navigation separates the PRODUCT CONSOLE (operational
 * surfaces) from the RESEARCH LAB (benchmarks, experiments, papers) so the
 * enforcement product and the research material can never be mistaken for
 * one another. The Lab lives behind its own labelled disclosure; native
 * <details> keeps it keyboard-operable without custom focus handling.
 */

const CONSOLE_NAV = [
  { to: "/executions", label: "Executions" },
  { to: "/operations", label: "Operations" },
  { to: "/approvals", label: "Approvals" },
  { to: "/control-room", label: "Control Room" },
  { to: "/evidence", label: "Evidence" },
  { to: "/policy", label: "Policies" },
  { to: "/telemetry", label: "Telemetry" },
] as const;

const LAB_NAV = [
  { to: "/eye", label: "👁 Live" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/aromer", label: "AROMER" },
  { to: "/cascade", label: "Cascade" },
  { to: "/scenarios", label: "Scenarios" },
  { to: "/lab", label: "Lab" },
  { to: "/articles", label: "Articles" },
  { to: "/whitepaper", label: "Whitepaper" },
] as const;

function NavLinks({
  items,
  className,
}: {
  items: ReadonlyArray<{ to: string; label: string }>;
  className?: string;
}) {
  return (
    <>
      {items.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          className={className ?? "text-muted-foreground hover:text-foreground transition-colors"}
          activeProps={{ className: "text-foreground" }}
        >
          {item.label}
        </Link>
      ))}
    </>
  );
}

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-background/80 backdrop-blur sticky top-0 z-40">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link to="/" className="flex items-baseline gap-3 group">
          <span className="font-serif text-xl tracking-tight">{META.name}</span>
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground border border-border px-1.5 py-0.5">
            {META.version}
          </span>
        </Link>

        {/* Desktop: Console links inline; Research Lab behind a labelled disclosure */}
        <nav aria-label="Product console" className="hidden md:flex items-center gap-5 text-sm">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/60">
            Console
          </span>
          <NavLinks items={CONSOLE_NAV} />
          <details className="relative group/lab">
            <summary
              className="cursor-pointer list-none select-none font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/60 border border-border/50 px-2 py-1 hover:text-foreground focus-visible:outline focus-visible:outline-2"
              aria-label="Research Lab navigation"
            >
              Research Lab ▾
            </summary>
            <div className="absolute right-0 mt-2 flex min-w-40 flex-col gap-2 border border-border bg-background p-3 text-sm shadow-lg">
              <NavLinks items={LAB_NAV} />
            </div>
          </details>
        </nav>

        {/* Mobile: single disclosure listing both groups with their labels */}
        <details className="md:hidden relative">
          <summary
            className="cursor-pointer list-none select-none border border-border/60 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-2"
            aria-label="Open navigation menu"
          >
            Menu
          </summary>
          <div className="absolute right-0 mt-2 flex w-56 flex-col gap-2 border border-border bg-background p-4 text-sm shadow-lg">
            <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/60">
              Product Console
            </span>
            <NavLinks items={CONSOLE_NAV} />
            <span className="mt-2 font-mono text-[9px] uppercase tracking-[0.18em] text-muted-foreground/60">
              Research Lab
            </span>
            <NavLinks items={LAB_NAV} />
          </div>
        </details>
      </div>
    </header>
  );
}
