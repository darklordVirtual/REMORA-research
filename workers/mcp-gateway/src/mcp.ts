/**
 * MCP over Streamable HTTP, tools-only.
 *
 * Kept as a pure function of (request, dependencies) so the protocol can be
 * tested without a Worker runtime, a container, or a network.
 */
import type { Verification } from "./effect";
import { governedNames, toolsFor } from "./tools";
import type { AssessResult, ExecuteResult, RemoraClient, ToolCall } from "./remora";

export const PROTOCOL_VERSION = "2025-06-18";

export interface JsonRpcRequest {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

export interface PendingProposal {
  review_item_id: string;
  call: ToolCall;
}

/** Where a proposal awaiting human approval is remembered between the tool
 *  call that created it and the status call that redeems it. */
export interface ProposalStore {
  put(id: string, p: PendingProposal): Promise<void>;
  get(id: string): Promise<PendingProposal | null>;
  delete(id: string): Promise<void>;
}

export interface Deps {
  remora: RemoraClient;
  store: ProposalStore;
  /**
   * Read a fact back and compare it against the delta the tool declared.
   *
   * Injected rather than imported so the protocol layer stays testable
   * without a database, and so a deployment with no reader simply does not
   * verify instead of pretending it did.
   */
  verifyEffect?: (tool: string, declared: Record<string, unknown>,
                  proposalId: string) => Promise<Verification | null>;
  /** Injected so the protocol layer stays deterministic under test. */
  newId: () => string;
  /** Deployment configuration, which decides which tool sets are live. */
  env: Record<string, unknown>;
}

const ok = (id: unknown, result: unknown) => ({ jsonrpc: "2.0", id, result });
const err = (id: unknown, code: number, message: string) => ({
  jsonrpc: "2.0",
  id,
  error: { code, message },
});

/** An MCP tool result. `isError` reports a *tool-level* failure to the model;
 *  it is not a transport error, and a governance refusal is not an error at
 *  all — a refusal is the system working. */
const textResult = (payload: unknown, isError = false) => ({
  content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
  isError,
});

function renderDecision(a: AssessResult, proposalId?: string): unknown {
  // review_item_id is handed back as approval_reference so a human has
  // something to act on. It is not a credential: approving requires the
  // approver role, and REMORA enforces that server-side — the gateway holds
  // only an operator token and cannot approve its own proposals.
  const base = {
    decision: a.decision,
    reasons: a.reasons ?? [],
    // The grounding signals, surfaced rather than swallowed. A refusal that
    // says "nothing to decide on" without saying which question came back
    // unanswered is not an explanation, and it is unusable for anyone trying
    // to make the next call succeed.
    ...(a.semantic ? { signals: a.semantic } : {}),
  };
  switch (a.decision) {
    case "abstain":
      return {
        ...base,
        status: "refused",
        explanation:
          "REMORA refused this call and nothing was executed. Abstain means " +
          "there was nothing to decide on — not that a person should be " +
          "asked. Do not retry the same call, and do not try to reach the " +
          "same effect another way.",
      };
    case "verify":
    case "escalate":
      // Both enqueue a review item for a human. servers/execution_api.py is
      // explicit: "VERIFY/ESCALATE enqueue a review item for a human;
      // ABSTAIN returns [nothing]". Treating escalate as a refusal threw
      // away the one route a person had to say yes.
      return {
        ...base,
        status: "pending_approval",
        proposal_id: proposalId,
        approval_reference: a.review_item_id,
        explanation: a.decision === "escalate"
          ? "Nothing has been executed, and a person has to decide. REMORA " +
            "escalated because the call did not resolve under the intent it " +
            "claimed — so say plainly what you were trying to do and under " +
            "which work order, rather than presenting this as routine. Give " +
            "them the approval_reference, then poll remora_proposal_status."
          : "Nothing has been executed. A person must approve this call " +
            "first. Give them the approval_reference, then poll " +
            "remora_proposal_status with the proposal_id above; once " +
            "approved it will execute with exactly these arguments. Report " +
            "the wait rather than looking for another route.",
      };
    default:
      return base;
  }
}

async function callTool(
  name: string,
  args: Record<string, unknown>,
  deps: Deps,
): Promise<unknown> {
  if (name === "remora_proposal_status") {
    return statusTool(String(args.proposal_id ?? ""), deps);
  }
  if (!governedNames(deps.env).has(name)) {
    // Either the tool does not exist or its set is not configured here.
    // Saying which would be more helpful and less honest: from the agent's
    // side both mean the same thing — this gateway will not do that.
    return textResult({ error: `unknown tool: ${name}` }, true);
  }

  const { intent_ref, ...rest } = args as { intent_ref?: string };
  const call: ToolCall = {
    tool_name: name,
    arguments: rest as Record<string, unknown>,
    // Describes the DEPLOYMENT, not the data it reads. This gateway is a test
    // deployment; hardcoding "prod" conflated the two and made every ACCEPT
    // path structurally unreachable, because both of them exclude production
    // for disclosure blast radius. A production deployment sets this to prod
    // and gets that exclusion back.
    target_environment: String(deps.env.REMORA_TARGET_ENVIRONMENT ?? "prod"),
    ...(intent_ref ? { intent_ref } : {}),
  };

  const { status, body } = await deps.remora.assess(call);
  if (status !== 200) {
    return textResult(
      { error: "assess failed", http_status: status, detail: body },
      true,
    );
  }

  if (body.decision === "accept" && body.execution_token) {
    const run = await deps.remora.executeAccepted(body.execution_token, call);
    return textResult({
      decision: "accept",
      // An ACCEPT is the one outcome that must never be unexplained: it is
      // the only one where nobody looked. Which path allowed it, and which
      // signals carried it, belong in the answer.
      reasons: body.reasons ?? [],
      ...(body.semantic ? { signals: body.semantic } : {}),
      status: run.status === 200 ? "executed" : "execution_failed",
      outcome: run.body?.outcome,
      result: run.body?.tool_execution,
    }, run.status !== 200);
  }

  // Anything that is not an outright ACCEPT leaves the side effect undone.
  // VERIFY and ESCALATE both carry a review item; ABSTAIN does not, and gets
  // no proposal to poll because there is nothing for a person to approve.
  let proposalId: string | undefined;
  if (body.review_item_id) {
    proposalId = deps.newId();
    await deps.store.put(proposalId, { review_item_id: body.review_item_id, call });
  }
  return textResult(renderDecision(body, proposalId));
}

async function statusTool(proposalId: string, deps: Deps): Promise<unknown> {
  const pending = await deps.store.get(proposalId);
  if (!pending) {
    return textResult({
      status: "unknown_proposal",
      explanation:
        "No pending proposal with that id. It was never created, it has " +
        "already been executed, or this is a different session.",
    }, true);
  }

  const { status, body } = await deps.remora.execute(
    pending.review_item_id,
    pending.call,
  );

  // The execution API refuses an unapproved item. That is the expected answer
  // while a human has not acted yet, so it is reported as "still waiting"
  // rather than as an error the model should route around.
  if (status !== 200) {
    return textResult({
      status: "pending_approval",
      proposal_id: proposalId,
      http_status: status,
      detail: body,
      explanation:
        "Still not approved, so nothing has been executed. Wait and poll " +
        "again, or tell the user the call is waiting on their approval.",
    });
  }

  await deps.store.delete(proposalId);
  const execution = (body as ExecuteResult).tool_execution ?? {};

  // Dispatching and the effect happening are different facts. The read-back
  // is what tells them apart, and its verdict is reported as it comes —
  // including a mismatch, which is bad news about ourselves.
  let effect: Verification | null = null;
  if (deps.verifyEffect) {
    const declared = (execution as { result?: Record<string, unknown> }).result
      ?? (execution as Record<string, unknown>);
    effect = await deps.verifyEffect(pending.call.tool_name, declared,
                                     pending.review_item_id);
  }

  return textResult({
    status: "executed",
    proposal_id: proposalId,
    outcome: (body as ExecuteResult).outcome,
    result: execution,
    ...(effect
      ? {
          effect: effect.status,
          effect_reason: effect.reason_code,
          ...(effect.detail ? { effect_detail: effect.detail } : {}),
          ...(effect.status === "EFFECT_MISMATCH"
            ? {
                explanation:
                  "The call was dispatched but the system of record does not " +
                  "match what was approved. Do not assume it worked. Report " +
                  "this rather than retrying.",
              }
            : {}),
        }
      : {}),
  });
}

/** Handle one JSON-RPC message. Returns null for notifications, which take no
 *  response body. */
export async function handleRpc(
  req: JsonRpcRequest,
  deps: Deps,
): Promise<unknown | null> {
  switch (req.method) {
    case "initialize":
      return ok(req.id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: {} },
        serverInfo: { name: "remora-mcp-gateway", version: "0.10.0" },
      });

    case "notifications/initialized":
    case "notifications/cancelled":
      return null;

    case "ping":
      return ok(req.id, {});

    case "tools/list":
      return ok(req.id, { tools: toolsFor(deps.env) });

    case "tools/call": {
      const params = (req.params ?? {}) as {
        name?: string;
        arguments?: Record<string, unknown>;
      };
      if (!params.name) return err(req.id, -32602, "missing tool name");
      try {
        return ok(req.id, await callTool(params.name, params.arguments ?? {}, deps));
      } catch (e) {
        return ok(
          req.id,
          textResult({ error: String(e instanceof Error ? e.message : e) }, true),
        );
      }
    }

    default:
      return err(req.id, -32601, `method not found: ${req.method}`);
  }
}
