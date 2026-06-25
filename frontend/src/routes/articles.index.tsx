import { createFileRoute, Link } from "@tanstack/react-router";
import { ARTICLES, ARTICLES_BASE_URL } from "@/content/articles";

export const Route = createFileRoute("/articles/")({
  head: () => {
    const jsonld = {
      "@context": "https://schema.org",
      "@type": "Blog",
      name: "REMORA — Research Notes",
      url: ARTICLES_BASE_URL,
      description:
        "Plain-language notes on governed agentic AI: assurance layers, selective trust, calibration, and auditable AI decisions.",
      blogPost: ARTICLES.map((a) => ({
        "@type": "BlogPosting",
        headline: a.title,
        description: a.description,
        datePublished: a.published,
        url: `${ARTICLES_BASE_URL}/${a.slug}`,
      })),
    };
    return {
      meta: [
        { title: "Articles — REMORA · Governed Agentic AI" },
        {
          name: "description",
          content:
            "Research notes on governed agentic AI: why agents need an assurance layer, the trust inversion in AI confidence, and the four-outcome governance model.",
        },
        {
          name: "keywords",
          content:
            "agentic AI, AI governance, AI agent safety, assurance layer, selective prediction, AI calibration",
        },
        { property: "og:type", content: "website" },
        { property: "og:title", content: "REMORA — Research Notes on Governed Agentic AI" },
        { property: "og:url", content: ARTICLES_BASE_URL },
      ],
      links: [{ rel: "canonical", href: ARTICLES_BASE_URL }],
      scripts: [{ type: "application/ld+json", children: JSON.stringify(jsonld) }],
    };
  },
  component: ArticlesIndex,
});

function ArticlesIndex() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-16">
      <div className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
        Research notes
      </div>
      <h1 className="mt-4 font-serif text-4xl md:text-5xl tracking-tight">
        Governed agentic AI, in plain language
      </h1>
      <p className="mt-5 text-[15px] leading-relaxed text-foreground/75 max-w-2xl">
        Short, honest essays on the ideas behind REMORA — why tool-calling agents need an assurance
        layer, what model confidence is worth in the hardest cases, and how to keep autonomous
        actions auditable. Grounded in the research, with the caveats kept.
      </p>

      <div className="mt-12 flex flex-col divide-y divide-border/60 border-y border-border/60">
        {ARTICLES.map((a) => (
          <Link
            key={a.slug}
            to="/articles/$slug"
            params={{ slug: a.slug }}
            className="group py-7 block"
          >
            <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
              <time dateTime={a.published}>
                {new Date(a.published).toLocaleDateString("en-GB", {
                  year: "numeric",
                  month: "short",
                  day: "numeric",
                })}
              </time>
              <span>·</span>
              <span>{a.readingMinutes} min read</span>
              {a.tags.map((t) => (
                <span
                  key={t}
                  className="border border-border/50 px-1.5 py-px normal-case tracking-normal"
                >
                  {t}
                </span>
              ))}
            </div>
            <h2 className="mt-3 font-serif text-2xl tracking-tight group-hover:text-signal transition-colors">
              {a.title}
            </h2>
            <p className="mt-2 text-[14px] leading-relaxed text-muted-foreground">{a.dek}</p>
            <span className="mt-3 inline-block font-mono text-[12px] text-muted-foreground/60 group-hover:text-signal/80">
              Read →
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
