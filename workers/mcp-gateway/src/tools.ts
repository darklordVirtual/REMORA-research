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

export const ALL_TOOLS: GovernedTool[] = [...TOOLS, STATUS_TOOL];
export const GOVERNED_NAMES = new Set(TOOLS.map((t) => t.name));
