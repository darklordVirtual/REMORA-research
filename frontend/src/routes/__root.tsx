import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  useRouterState,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";

import appCss from "../styles.css?url";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="max-w-md">
        <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          Error · 404
        </div>
        <h1 className="mt-4 font-serif text-5xl tracking-tight">Page not found.</h1>
        <p className="mt-4 text-sm text-muted-foreground">
          The URL did not match any documented route in this whitepaper.
        </p>
        <Link
          to="/"
          className="mt-8 inline-block border-b border-foreground pb-0.5 text-sm hover:text-signal hover:border-signal"
        >
          Return to overview →
        </Link>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <div className="max-w-md">
        <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-state-escalate">
          Decision · ESCALATE
        </div>
        <h1 className="mt-4 font-serif text-4xl tracking-tight">This page did not load.</h1>
        <p className="mt-4 text-sm text-muted-foreground">
          The runtime returned an unexpected state. Retry or return to the overview.
        </p>
        <div className="mt-8 flex gap-4 text-sm">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="border-b border-foreground pb-0.5 hover:text-signal hover:border-signal"
          >
            Retry →
          </button>
          <a
            href="/"
            className="border-b border-border pb-0.5 text-muted-foreground hover:text-foreground"
          >
            Overview
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "REMORA — Governed Agentic AI" },
      {
        name: "description",
        content:
          "A reference architecture for governed agentic AI: selective trust, policy-gated action, auditable decisions.",
      },
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: "REMORA" },
      { property: "og:url", content: "https://remora.razorsharp.workers.dev/" },
      { property: "og:image", content: "https://remora.razorsharp.workers.dev/og-card.png" },
      { property: "og:image:width", content: "1200" },
      { property: "og:image:height", content: "630" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:image", content: "https://remora.razorsharp.workers.dev/og-card.png" },
    ],
    links: [
      { rel: "stylesheet", href: appCss },
      { rel: "preconnect", href: "https://fonts.googleapis.com" },
      { rel: "preconnect", href: "https://fonts.gstatic.com", crossOrigin: "anonymous" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap",
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isFullScreen =
    pathname === "/" ||
    pathname.startsWith("/cascade") ||
    pathname.startsWith("/control-room") ||
    pathname.startsWith("/operations") ||
    pathname.startsWith("/eye");

  return (
    <QueryClientProvider client={queryClient}>
      {isFullScreen ? (
        <Outlet />
      ) : (
        <div className="min-h-screen flex flex-col">
          <SiteHeader />
          <main className="flex-1">
            <Outlet />
          </main>
          <SiteFooter />
        </div>
      )}
    </QueryClientProvider>
  );
}
