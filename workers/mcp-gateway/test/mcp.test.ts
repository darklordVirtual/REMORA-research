/**
 * Protocol and governance tests for the MCP gateway.
 *
 * The REMORA client is faked so these tests pin the gateway's own behaviour:
 * what it exposes, what it does with each decision, and — most importantly —
 * that it never reaches a side effect without an authorisation.
 */
import { describe, expect, it } from "vitest";
import {
  handleRpc,
  PROTOCOL_VERSION,
  type Deps,
  type PendingProposal,
  type ProposalStore,
} from "../src/mcp";
import type { AssessResult, ExecuteResult, ToolCall } from "../src/remora";

class MemoryStore implements ProposalStore {
  map = new Map<string, PendingProposal>();
  async put(id: string, p: PendingProposal) {
    this.map.set(id, p);
  }
  async get(id: string) {
    return this.map.get(id) ?? null;
  }
  async delete(id: string) {
    this.map.delete(id);
  }
}

interface Recorded {
  assess: ToolCall[];
  execute: [string, ToolCall][];
  accepted: ToolCall[];
}

function deps(
  assessBody: Partial<AssessResult>,
  opts: {
    executeStatus?: number;
    executeBody?: Partial<ExecuteResult>;
    assessStatus?: number;
  } = {},
): { deps: Deps; rec: Recorded } {
  const rec: Recorded = { assess: [], execute: [], accepted: [] };
  const remora = {
    async assess(call: ToolCall) {
      rec.assess.push(call);
      return {
        status: opts.assessStatus ?? 200,
        body: assessBody as AssessResult,
      };
    },
    async execute(itemId: string, call: ToolCall) {
      rec.execute.push([itemId, call]);
      return {
        status: opts.executeStatus ?? 200,
        body: (opts.executeBody ?? { outcome: "executed" }) as ExecuteResult,
      };
    },
    async executeAccepted(_t: Record<string, unknown>, call: ToolCall) {
      rec.accepted.push(call);
      return { status: 200, body: { outcome: "executed" } as ExecuteResult };
    },
  };
  let n = 0;
  return {
    rec,
    deps: {
      remora: remora as unknown as Deps["remora"],
      store: new MemoryStore(),
      newId: () => "proposal-" + ++n,
      // Both sets configured, so the protocol tests see the full surface.
      env: {
        REMORA_GITHUB_TOKEN: "t",
        REMORA_GITHUB_REPOS: "o/r",
        REMORA_KG_TENANT: "acme",
      },
    },
  };
}

const call = (name: string, args: Record<string, unknown>, id = 1) => ({
  jsonrpc: "2.0" as const,
  id,
  method: "tools/call",
  params: { name, arguments: args },
});

const payload = (r: unknown) =>
  JSON.parse((r as any).result.content[0].text);

describe("protocol", () => {
  it("initialize reports the protocol version and tool capability", async () => {
    const { deps: d } = deps({});
    const r: any = await handleRpc(
      { jsonrpc: "2.0", id: 1, method: "initialize" },
      d,
    );
    expect(r.result.protocolVersion).toBe(PROTOCOL_VERSION);
    expect(r.result.capabilities.tools).toBeDefined();
    expect(r.result.serverInfo.name).toBe("remora-mcp-gateway");
  });

  it("notifications get no reply", async () => {
    const { deps: d } = deps({});
    expect(
      await handleRpc(
        { jsonrpc: "2.0", method: "notifications/initialized" },
        d,
      ),
    ).toBeNull();
  });

  it("tools/list exposes the governed tools plus the status tool", async () => {
    const { deps: d } = deps({});
    const r: any = await handleRpc(
      { jsonrpc: "2.0", id: 1, method: "tools/list" },
      d,
    );
    const names = r.result.tools.map((t: any) => t.name);
    expect(names).toContain("gh_read_issue");
    expect(names).toContain("gh_close_issue");
    expect(names).toContain("kg_assert_fact");
    expect(names).toContain("remora_proposal_status");
    expect(r.result.tools).toHaveLength(14);
  });

  it("every governed tool requires an intent_ref", async () => {
    const { deps: d } = deps({});
    const r: any = await handleRpc(
      { jsonrpc: "2.0", id: 1, method: "tools/list" },
      d,
    );
    for (const t of r.result.tools) {
      if (t.name === "remora_proposal_status") continue;
      expect(
        t.inputSchema.required,
        t.name + " must require intent_ref",
      ).toContain("intent_ref");
    }
  });

  it("a set with no credential is not listed at all", async () => {
    // An agent cannot tell "refused" from "broken". A governance refusal has
    // to mean something, and it stops meaning anything if half the failures
    // are configuration.
    const { deps: d } = deps({});
    d.env = { REMORA_KG_TENANT: "acme" };
    const r: any = await handleRpc(
      { jsonrpc: "2.0", id: 1, method: "tools/list" },
      d,
    );
    const names = r.result.tools.map((t: any) => t.name);
    expect(names).toContain("kg_assert_fact");
    expect(names).not.toContain("gh_create_issue");
    expect(names).toContain("remora_proposal_status");
  });

  it("a tool from an unconfigured set never reaches REMORA", async () => {
    const { deps: d, rec } = deps({ decision: "accept" });
    d.env = { REMORA_KG_TENANT: "acme" };
    const r: any = await handleRpc(
      call("gh_create_issue", { repo: "o/r", title: "t", intent_ref: "o/r#1" }),
      d,
    );
    expect(r.result.isError).toBe(true);
    expect(rec.assess).toHaveLength(0);
  });

  it("an unknown method is a JSON-RPC error, not a crash", async () => {
    const { deps: d } = deps({});
    const r: any = await handleRpc(
      { jsonrpc: "2.0", id: 9, method: "nope" },
      d,
    );
    expect(r.error.code).toBe(-32601);
  });
});

describe("governance", () => {
  it("ACCEPT redeems the execution token and runs the call", async () => {
    const { deps: d, rec } = deps({
      decision: "accept",
      execution_token: { t: 1 },
    });
    const r = await handleRpc(
      call("gh_read_issue", { repo: "o/r", number: 1, intent_ref: "o/r#1" }),
      d,
    );
    expect(payload(r).status).toBe("executed");
    expect(rec.accepted).toHaveLength(1);
  });

  it("VERIFY executes nothing and returns a pollable proposal", async () => {
    const { deps: d, rec } = deps({
      decision: "verify",
      reasons: ["evidence_insufficient"],
      review_item_id: "item-1",
    });
    const r = await handleRpc(
      call("gh_close_issue", {
        repo: "o/r",
        number: 7,
        intent_ref: "o/r#7",
      }),
      d,
    );
    const p = payload(r);
    expect(p.status).toBe("pending_approval");
    expect(p.proposal_id).toBe("proposal-1");
    expect(rec.execute, "nothing may run before approval").toHaveLength(0);
    expect(rec.accepted).toHaveLength(0);
  });

  it("ABSTAIN refuses outright: there is nothing for a person to decide", async () => {
    const { deps: d, rec } = deps({ decision: "abstain", reasons: ["r"] });
    const r = await handleRpc(
      call("gh_close_issue", { repo: "o/r", number: 1, intent_ref: "o/r#9" }),
      d,
    );
    expect(payload(r).status).toBe("refused");
    expect(rec.execute).toHaveLength(0);
    expect(rec.accepted).toHaveLength(0);
  });

  it("ESCALATE goes to a person, it is not a refusal", async () => {
    // servers/execution_api.py: "VERIFY/ESCALATE enqueue a review item for a
    // human; ABSTAIN returns [nothing]". Treating escalate as refused threw
    // away the one route a person had to say yes — and escalate is the case
    // where a person is most needed, because the call did not resolve under
    // the intent it claimed.
    const { deps: d, rec } = deps({
      decision: "escalate", reasons: ["expected_effect_contradicted"],
      review_item_id: "item-3",
    });
    const r = await handleRpc(
      call("gh_close_issue", { repo: "o/r", number: 1, intent_ref: "o/r#9" }),
      d,
    );
    const p = payload(r);
    expect(p.status).toBe("pending_approval");
    expect(p.approval_reference).toBe("item-3");
    expect(p.explanation).toContain("did not resolve under the intent");
    expect(rec.execute, "still nothing runs before approval").toHaveLength(0);
  });

  it("a refusal is not flagged as a tool error", async () => {
    // isError would invite the model to treat governance as a fault to route
    // around. A refusal is the system working.
    const { deps: d } = deps({ decision: "abstain", reasons: ["r"] });
    const r: any = await handleRpc(
      call("gh_close_issue", { repo: "o/r", number: 1, intent_ref: "o/r#1" }),
      d,
    );
    expect(r.result.isError).toBe(false);
  });

  it("intent_ref is sent as intent, never as a tool argument", async () => {
    const { deps: d, rec } = deps({
      decision: "verify",
      review_item_id: "i",
    });
    await handleRpc(
      call("gh_add_label", { repo: "o/r", number: 3, label: "bug", intent_ref: "o/r#3" }),
      d,
    );
    expect(rec.assess[0].intent_ref).toBe("o/r#3");
    expect(rec.assess[0].arguments).toEqual({ repo: "o/r", number: 3, label: "bug" });
  });

  it("an unknown tool is refused without reaching REMORA", async () => {
    const { deps: d, rec } = deps({ decision: "accept" });
    const r: any = await handleRpc(
      call("rm_minus_rf", { intent_ref: "X" }),
      d,
    );
    expect(r.result.isError).toBe(true);
    expect(rec.assess).toHaveLength(0);
  });
});

describe("fixable mistakes get fixable answers", () => {
  it("a missing required argument says which, and says retry", async () => {
    // The generic refusal says "do not retry" — right for a governance
    // refusal, exactly wrong for a shape mistake the agent can correct.
    const { deps: d, rec } = deps({ decision: "accept" });
    const r: any = await handleRpc(
      call("kg_query_facts", { graph: "g", intent_ref: "task:x" }),
      d,
    );
    const p = payload(r);
    expect(r.result.isError).toBe(true);
    expect(p.error).toBe("missing_required_arguments");
    expect(p.missing).toContain("subject");
    expect(p.explanation).toContain("Retry");
    expect(rec.assess, "shape errors never reach REMORA").toHaveLength(0);
  });

  it("a missing intent_ref explains what an intent_ref is", async () => {
    const { deps: d, rec } = deps({ decision: "accept" });
    const r: any = await handleRpc(
      call("kg_query_facts", { graph: "g", subject: "s" }),
      d,
    );
    const p = payload(r);
    expect(p.missing).toContain("intent_ref");
    expect(p.explanation).toContain("work order");
    expect(rec.assess).toHaveLength(0);
  });
});

describe("proposal redemption", () => {
  it("executes with the stored arguments, not ones supplied later", async () => {
    const { deps: d, rec } = deps({
      decision: "verify",
      review_item_id: "item-7",
    });
    await handleRpc(
      call("gh_comment_issue", {
        repo: "o/r",
        number: 5,
        body: "as approved",
        intent_ref: "o/r#5",
      }),
      d,
    );
    const r = await handleRpc(
      call("remora_proposal_status", { proposal_id: "proposal-1" }, 2),
      d,
    );
    expect(payload(r).status).toBe("executed");
    expect(rec.execute[0][0]).toBe("item-7");
    expect(rec.execute[0][1].arguments).toEqual({
      repo: "o/r",
      number: 5,
      body: "as approved",
    });
  });

  it("still-unapproved reports waiting rather than an error", async () => {
    const { deps: d } = deps(
      { decision: "verify", review_item_id: "item-1" },
      { executeStatus: 409, executeBody: { outcome: "not_approved" } },
    );
    await handleRpc(
      call("gh_add_label", { repo: "o/r", number: 2, label: "x", intent_ref: "o/r#2" }),
      d,
    );
    const r: any = await handleRpc(
      call("remora_proposal_status", { proposal_id: "proposal-1" }, 2),
      d,
    );
    expect(payload(r).status).toBe("pending_approval");
    expect(r.result.isError).toBe(false);
  });

  it("a redeemed proposal cannot be replayed", async () => {
    const { deps: d, rec } = deps({
      decision: "verify",
      review_item_id: "item-1",
    });
    await handleRpc(
      call("gh_create_issue", { repo: "o/r", title: "t", intent_ref: "o/r#1" }),
      d,
    );
    await handleRpc(
      call("remora_proposal_status", { proposal_id: "proposal-1" }, 2),
      d,
    );
    const again: any = await handleRpc(
      call("remora_proposal_status", { proposal_id: "proposal-1" }, 3),
      d,
    );
    expect(payload(again).status).toBe("unknown_proposal");
    expect(
      rec.execute,
      "the second attempt must not reach REMORA",
    ).toHaveLength(1);
  });

  it("an unknown proposal id is refused", async () => {
    const { deps: d } = deps({});
    const r: any = await handleRpc(
      call("remora_proposal_status", { proposal_id: "nope" }),
      d,
    );
    expect(payload(r).status).toBe("unknown_proposal");
    expect(r.result.isError).toBe(true);
  });
});

describe("failure handling", () => {
  it("an assess HTTP failure is an error and executes nothing", async () => {
    const { deps: d, rec } = deps({}, { assessStatus: 503 });
    const r: any = await handleRpc(
      call("gh_read_issue", { repo: "o/r", number: 1, intent_ref: "o/r#1" }),
      d,
    );
    expect(r.result.isError).toBe(true);
    expect(rec.execute).toHaveLength(0);
    expect(rec.accepted).toHaveLength(0);
  });
});
