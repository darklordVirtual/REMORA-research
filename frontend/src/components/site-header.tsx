import { Link } from "@tanstack/react-router";
import { META } from "@/content/whitepaper";

const nav = [
  { to: "/eye", label: "👁 Live" },
  { to: "/control-room", label: "Control Room" },
  { to: "/benchmarks", label: "Benchmarks" },
  { to: "/articles", label: "Articles" },
  { to: "/whitepaper", label: "Whitepaper" },
  { to: "/telemetry", label: "Telemetry" },
] as const;

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
        <nav className="hidden md:flex items-center gap-6 text-sm">
          {nav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="text-muted-foreground hover:text-foreground transition-colors"
              activeProps={{ className: "text-foreground" }}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
