/**
 * MCP over Streamable HTTP, tools-only.
 *
 * Kept as a pure function of (request, dependencies) so the protocol can be
 * tested without a Worker runtime, a container, or a network.
 */
import { ALL_TOOLS, GOVERNED_NAMES } from "./tools";
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
  /** Injected so the protocol layer stays deterministic under test. */
  newId: () => string;
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
  };
  switch (a.decision) {
    case "abstain":
      return {
        ...base,
        status: "refused",
        explanation:
          "REMORA refused this call and nothing was executed. This is a " +
          "governance decision, not a failure: do not retry the same call, " +
          "and do not try to reach the same effect another way.",
      };
    case "escalate":
      return {
        ...base,
        status: "refused",
        explanation:
          "REMORA escalated this call and nothing was executed. The call did " +
          "not resolve under the intent it claimed. Check that the work order " +
          "actually authorises this action rather than retrying.",
      };
    case "verify":
      return {
        ...base,
        status: "pending_approval",
        proposal_id: proposalId,
        approval_reference: a.review_item_id,
        explanation:
          "Nothing has been executed. A human must approve this call first. " +
          "Give them the approval_reference, then poll remora_proposal_status " +
          "with the proposal_id above; once approved it will execute with " +
          "exactly these arguments. Report the wait to the user rather than " +
          "looking for another route.",
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
  if (!GOVERNED_NAMES.has(name)) {
    return textResult({ error: `unknown tool: ${name}` }, true);
  }

  const { intent_ref, ...rest } = args as { intent_ref?: string };
  const call: ToolCall = {
    tool_name: name,
    arguments: rest as Record<string, unknown>,
    target_environment: "prod",
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
      status: run.status === 200 ? "executed" : "execution_failed",
      outcome: run.body?.outcome,
      result: run.body?.tool_execution,
    }, run.status !== 200);
  }

  // Anything that is not an outright ACCEPT leaves the side effect undone.
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
  return textResult({
    status: "executed",
    proposal_id: proposalId,
    outcome: (body as ExecuteResult).outcome,
    result: (body as ExecuteResult).tool_execution,
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
      return ok(req.id, { tools: ALL_TOOLS });

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
