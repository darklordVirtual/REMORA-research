/**
 * The MCP tool surface.
 *
 * These schemas describe the *shape* of a call, nothing more. Effect,
 * capability, resource type and every other safety signal are derived
 * server-side from the deployment-owned registry inside REMORA; a caller
 * cannot assert its way to an ACCEPT (see servers/execution_contracts.py,
 * ToolCallRequest). Adding a field here can never widen authority — it only
 * changes what the agent is able to propose.
 */
export interface GovernedTool {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties: Record<string, { type: string; description: string }>;
    required: string[];
  };
}

/**
 * Every governed tool takes an intent_ref: the authority the call claims to
 * act under. For this deployment that is a GitHub issue — written by a
 * person, stating what should happen, and existing independently of the agent
 * that later proposes a call.
 *
 * REMORA reads the issue and checks the proposal against what it actually
 * asks for, so closing an issue that only asked for a label is refused for
 * the reason it deserves. A reference that does not resolve is not an error:
 * it means no authority was established, which sends the call to review.
 */
const INTENT: Record<string, { type: string; description: string }> = {
  intent_ref: {
    type: "string",
    description:
      "The GitHub issue authorising this call, as owner/repo#123. The issue " +
      "text is what the call is checked against, so reference the issue that " +
      "actually asks for this action.",
  },
};

const REPO = {
  type: "string",
  description: "Repository as owner/name. Must be in the deployment allowlist.",
};

export const TOOLS: GovernedTool[] = [
  {
    name: "gh_read_issue",
    description:
      "Read one issue: title, state, body and labels. Read-only, but still " +
      "governed — the read happens only when the call resolves under a valid " +
      "intent.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        number: { type: "number", description: "Issue number." },
        ...INTENT,
      },
      required: ["repo", "number", "intent_ref"],
    },
  },
  {
    name: "gh_list_issues",
    description: "List up to 30 issues in a repository. Pull requests are excluded.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        state: {
          type: "string",
          description: "open, closed or all. Defaults to open.",
        },
        ...INTENT,
      },
      required: ["repo", "intent_ref"],
    },
  },
  {
    name: "gh_create_issue",
    description:
      "Open a new issue. Mutating and visible to everyone with access to the " +
      "repository; expect approval to be required before it is created.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        title: { type: "string", description: "Issue title." },
        body: { type: "string", description: "Issue body, Markdown." },
        ...INTENT,
      },
      required: ["repo", "title", "intent_ref"],
    },
  },
  {
    name: "gh_comment_issue",
    description:
      "Post a comment on an issue. Mutating and public; expect approval to be " +
      "required. The comment text cannot change between approval and posting.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        number: { type: "number", description: "Issue number." },
        body: { type: "string", description: "Comment text, Markdown." },
        ...INTENT,
      },
      required: ["repo", "number", "body", "intent_ref"],
    },
  },
  {
    name: "gh_close_issue",
    description:
      "Close an issue. Mutating. An issue that only asks to be labelled or " +
      "commented on does not authorise closing it.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        number: { type: "number", description: "Issue number." },
        ...INTENT,
      },
      required: ["repo", "number", "intent_ref"],
    },
  },
  {
    name: "gh_add_label",
    description: "Add one label to an issue. Mutating.",
    inputSchema: {
      type: "object",
      properties: {
        repo: REPO,
        number: { type: "number", description: "Issue number." },
        label: { type: "string", description: "Label name." },
        ...INTENT,
      },
      required: ["repo", "number", "label", "intent_ref"],
    },
  },
];

/**
 * Knowledge-graph tools (exeQta).
 *
 * The tenant is deliberately absent from every schema. It comes from
 * deployment configuration and is written into every statement server-side,
 * so no proposal — however well-formed — can reach across the boundary.
 */
export const GRAPH_TOOLS: GovernedTool[] = [
  {
    name: "kg_list_graphs",
    description: "List the knowledge graphs this deployment can see.",
    inputSchema: {
      type: "object",
      properties: { ...INTENT },
      required: ["intent_ref"],
    },
  },
  {
    name: "kg_list_predicates",
    description:
      "The predicates in use in a graph, most-used first. Start here: the " +
      "other query tools need a predicate or a subject, and this is how you " +
      "find out what they look like.",
    inputSchema: {
      type: "object",
      properties: {
        graph: { type: "string", description: "Graph URI." },
        ...INTENT,
      },
      required: ["graph", "intent_ref"],
    },
  },
  {
    name: "kg_sample_subjects",
    description:
      "Subjects in a graph with the most facts, so you can see what it is " +
      "about before querying one of them.",
    inputSchema: {
      type: "object",
      properties: {
        graph: { type: "string", description: "Graph URI." },
        ...INTENT,
      },
      required: ["graph", "intent_ref"],
    },
  },
  {
    name: "kg_query_facts",
    description:
      "Facts about one subject, newest first. Optionally narrowed to a " +
      "single predicate.",
    inputSchema: {
      type: "object",
      properties: {
        graph: { type: "string", description: "Graph URI." },
        subject: { type: "string", description: "Subject to look up." },
        predicate: { type: "string", description: "Optional predicate filter." },
        ...INTENT,
      },
      required: ["graph", "subject", "intent_ref"],
    },
  },
  {
    name: "kg_find_subjects",
    description:
      "The reverse lookup: subjects carrying a given predicate, optionally " +
      "filtered by a substring of the object.",
    inputSchema: {
      type: "object",
      properties: {
        graph: { type: "string", description: "Graph URI." },
        predicate: { type: "string", description: "Predicate to search on." },
        contains: { type: "string", description: "Optional object substring." },
        ...INTENT,
      },
      required: ["graph", "predicate", "intent_ref"],
    },
  },
  {
    name: "kg_assert_fact",
    description:
      "Assert one fact into the graph. Mutating, and further-reaching than it " +
      "looks: everything that reads the graph afterwards inherits this. A " +
      "source is required — a fact with no recorded origin cannot be audited.",
    inputSchema: {
      type: "object",
      properties: {
        graph: { type: "string", description: "Graph URI." },
        subject: { type: "string", description: "Subject the fact is about." },
        predicate: { type: "string", description: "Relation being asserted." },
        object: { type: "string", description: "The value being asserted." },
        object_kind: {
          type: "string",
          description: "literal, iri, json, number or date. Defaults to literal.",
        },
        source: {
          type: "string",
          description:
            "Where this claim came from, e.g. a document, a system, a person. " +
            "Required.",
        },
        confidence: {
          type: "number",
          description: "0 to 1. Defaults to 1. Say less than 1 when unsure.",
        },
        ...INTENT,
      },
      required: ["graph", "subject", "predicate", "object", "source",
                 "intent_ref"],
    },
  },
  {
    name: "kg_retract_fact",
    description:
      "Retract a fact this tenant owns. Mutating. Anything that already read " +
      "the fact will not un-read it.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", description: "Fact id, from kg_query_facts." },
        ...INTENT,
      },
      required: ["id", "intent_ref"],
    },
  },
];

/** Not a governed tool: it changes nothing. It reports where a proposal that
 *  needed human approval has got to, and executes it once approval exists. */
export const STATUS_TOOL: GovernedTool = {
  name: "remora_proposal_status",
  description:
    "Check a proposal that returned pending_approval. While it is still " +
    "pending this reports that and nothing happens. Once a human has " +
    "approved it, this executes the call exactly as proposed and returns the " +
    "result. The arguments cannot be changed between approval and execution.",
  inputSchema: {
    type: "object",
    properties: {
      proposal_id: {
        type: "string",
        description: "The proposal_id returned by the governed tool call.",
      },
    },
    required: ["proposal_id"],
  },
};

/**
 * The tool sets, and the configuration each one needs to work at all.
 *
 * This mirrors deploy/gateway/registry.py deliberately. An agent cannot tell
 * "refused" from "broken", and should never have to: a set whose credential
 * is absent is not listed, rather than listed and failing at dispatch. A
 * governance refusal has to mean something, and it stops meaning anything if
 * half the failures are configuration.
 */
const SETS: { tools: GovernedTool[]; requires: string[] }[] = [
  { tools: TOOLS, requires: ["REMORA_GITHUB_TOKEN", "REMORA_GITHUB_REPOS"] },
  { tools: GRAPH_TOOLS, requires: ["REMORA_KG_TENANT"] },
];

/** The governed tools this deployment can actually serve. */
export function governedTools(env: Record<string, unknown>): GovernedTool[] {
  return SETS.flatMap((set) =>
    set.requires.every((key) => String(env[key] ?? "").trim() !== "")
      ? set.tools
      : [],
  );
}

export function toolsFor(env: Record<string, unknown>): GovernedTool[] {
  return [...governedTools(env), STATUS_TOOL];
}

export function governedNames(env: Record<string, unknown>): Set<string> {
  return new Set(governedTools(env).map((t) => t.name));
}
