import { META } from "@/content/whitepaper";

export function SiteFooter() {
  return (
    <footer className="border-t border-border mt-32">
      <div className="mx-auto max-w-6xl px-6 py-12 grid gap-8 md:grid-cols-3 text-sm">
        <div>
          <div className="font-serif text-lg">{META.name}</div>
          <p className="mt-2 text-muted-foreground max-w-xs">
            Source-available pre-execution governance for AI agent actions.
          </p>
        </div>
        <div className="font-mono text-xs text-muted-foreground space-y-1">
          <div>release · {META.version}</div>
          <div>BUSL-1.1 · source-available · commercial license required for commercial use</div>
        </div>
        <div className="text-xs text-muted-foreground md:text-right">
          © {new Date().getFullYear()} REMORA Research. All claims scoped to inspected evidence.
        </div>
      </div>
    </footer>
  );
}
