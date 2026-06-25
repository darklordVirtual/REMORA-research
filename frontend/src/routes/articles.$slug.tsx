import { createFileRoute, notFound, Link } from "@tanstack/react-router";
import {
  getArticle,
  ARTICLES,
  ARTICLES_BASE_URL,
  PAPER_PDF,
  GITHUB,
  type Block,
} from "@/content/articles";

export const Route = createFileRoute("/articles/$slug")({
  loader: ({ params }) => {
    const article = getArticle(params.slug);
    if (!article) throw notFound();
    return article;
  },
  head: ({ params }) => {
    const a = getArticle(params.slug);
    if (!a) return {};
    const url = `${ARTICLES_BASE_URL}/${a.slug}`;
    const jsonld = {
      "@context": "https://schema.org",
      "@type": "Article",
      headline: a.title,
      description: a.description,
      datePublished: a.published,
      dateModified: a.updated ?? a.published,
      author: { "@type": "Organization", name: "REMORA" },
      publisher: { "@type": "Organization", name: "REMORA" },
      mainEntityOfPage: { "@type": "WebPage", "@id": url },
      keywords: a.keywords.join(", "),
      url,
    };
    return {
      meta: [
        { title: `${a.title} — REMORA` },
        { name: "description", content: a.description },
        { name: "keywords", content: a.keywords.join(", ") },
        { property: "og:type", content: "article" },
        { property: "og:title", content: a.title },
        { property: "og:description", content: a.description },
        { property: "og:url", content: url },
        { property: "article:published_time", content: a.published },
        { name: "twitter:title", content: a.title },
        { name: "twitter:description", content: a.description },
      ],
      links: [{ rel: "canonical", href: url }],
      scripts: [{ type: "application/ld+json", children: JSON.stringify(jsonld) }],
    };
  },
  component: ArticlePage,
});

function renderBlock(b: Block, i: number) {
  switch (b.t) {
    case "h2":
      return (
        <h2 key={i} className="mt-10 font-serif text-2xl tracking-tight">
          {b.text}
        </h2>
      );
    case "h3":
      return (
        <h3 key={i} className="mt-7 font-serif text-xl tracking-tight">
          {b.text}
        </h3>
      );
    case "ul":
      return (
        <ul key={i} className="mt-4 space-y-2 pl-5 list-disc marker:text-signal/60">
          {b.items.map((it, j) => (
            <li key={j} className="text-[15px] leading-relaxed text-foreground/80">
              {it}
            </li>
          ))}
        </ul>
      );
    case "quote":
      return (
        <blockquote
          key={i}
          className="my-8 border-l-2 border-signal/50 pl-5 font-serif text-xl italic text-foreground/85"
        >
          {b.text}
        </blockquote>
      );
    case "callout":
      return (
        <div
          key={i}
          className="my-7 border border-border/60 border-l-2 border-l-state-verify bg-state-verify/[0.03] px-5 py-4 text-[14px] leading-relaxed text-foreground/80"
        >
          {b.text}
        </div>
      );
    default:
      return (
        <p key={i} className="mt-5 text-[15px] leading-relaxed text-foreground/80">
          {b.text}
        </p>
      );
  }
}

function ArticlePage() {
  const a = Route.useLoaderData();
  const more = ARTICLES.filter((x) => x.slug !== a.slug).slice(0, 2);

  return (
    <article className="mx-auto max-w-2xl px-6 py-16">
      <Link
        to="/articles"
        className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground/70 hover:text-foreground"
      >
        ← Research notes
      </Link>

      <div className="mt-6 flex flex-wrap items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
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

      <h1 className="mt-4 font-serif text-4xl md:text-5xl tracking-tight leading-[1.1]">
        {a.title}
      </h1>
      <p className="mt-5 text-[16px] leading-relaxed text-muted-foreground">{a.dek}</p>

      <div className="mt-8 border-t border-border/60 pt-2">{a.body.map(renderBlock)}</div>

      {/* CTA */}
      <div className="mt-12 border border-border/60 p-6 bg-muted/[0.15]">
        <div className="font-serif text-lg tracking-tight">See it for yourself</div>
        <p className="mt-2 text-[14px] leading-relaxed text-muted-foreground">
          REMORA is open and research-grade. Read the full paper, run the live Control Room, or read
          the code — and tell us where we're wrong.
        </p>
        <div className="mt-4 flex flex-wrap gap-3 font-mono text-[12px]">
          <Link
            to="/control-room"
            className="border border-signal/50 bg-signal/[0.05] px-4 py-2 hover:bg-signal/[0.1]"
          >
            Open the Control Room →
          </Link>
          <a
            href={PAPER_PDF}
            target="_blank"
            rel="noreferrer"
            className="border border-border/60 px-4 py-2 hover:border-foreground/30"
          >
            Read the paper (PDF)
          </a>
          <a
            href={GITHUB}
            target="_blank"
            rel="noreferrer"
            className="border border-border/60 px-4 py-2 hover:border-foreground/30"
          >
            View on GitHub
          </a>
        </div>
      </div>

      {/* Related — internal linking for SEO */}
      {more.length > 0 && (
        <div className="mt-12">
          <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
            Keep reading
          </div>
          <div className="mt-4 flex flex-col divide-y divide-border/60 border-y border-border/60">
            {more.map((m) => (
              <Link
                key={m.slug}
                to="/articles/$slug"
                params={{ slug: m.slug }}
                className="group py-4 block"
              >
                <h3 className="font-serif text-lg tracking-tight group-hover:text-signal transition-colors">
                  {m.title}
                </h3>
                <p className="mt-1 text-[13px] text-muted-foreground line-clamp-2">{m.dek}</p>
              </Link>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
