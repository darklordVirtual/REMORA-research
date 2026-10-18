/**
 * MCP over Streamable HTTP, tools-only.
 *
 * Kept as a pure function of (request, dependencies) so the protocol can be
 * tested without a Worker runtime, a container, or a network.
 */
import type { EffectBinding, EffectReport } from "./effect";
import { dispatchStatus, statusExplanation } from "./outcome";
import { governedNames, toolsFor } from "./tools";
import type { GovernedTool } from "./tools";
import type {
  AssessResult, ExecuteResult, RemoraClient, RequestRef, ToolCall,
} from "./remora";

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
  /** REMORA's proposal identity and call hash from assess, kept so an effect
   *  receipt names the dispatch it is about. Absent on proposals stored
   *  before receipts were bound. */
  proposal_id?: string;
  tool_call_hash?: string;
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
   * Read the effect back, compare it against the approved arguments, and file
   * the result with REMORA as a receipt bound to this dispatch.
   *
   * `toolResult` only locates what the tool wrote; the expected values come
   * from `approvedArgs`. Injected rather than imported so the protocol layer
   * stays testable without a database, and so a deployment with no reader
   * simply does not verify instead of pretending it did.
   */
  verifyEffect?: (tool: string, approvedArgs: Record<string, unknown>,
                  toolResult: Record<string, unknown>, binding: EffectBinding,
                  dispatchedAt: number) => Promise<EffectReport | null>;
  /** Milliseconds since the epoch. Injected so tests are deterministic. */
  now?: () => number;
  /** Injected so the protocol layer stays deterministic under test. */
  newId: () => string;
  /** Deployment configuration, which decides which tool sets are live. */
  env: Record<string, unknown>;
  /** SHA-256 (lowercase hex) of the HTTP body bytes this message arrived in.
   *  When set, every tools/call carries a request_ref built from it. */
  bodySha256?: string;
}

/** True when a string has no lone surrogate, which JSON.stringify would escape
 *  and Python's json.dumps(ensure_ascii=False) would not. */
function wellFormed(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const next = s.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      i++;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      return false;
    }
  }
  return true;
}

/** The reference REMORA binds into the grant, or undefined when the message
 *  has no referenceable id or the transport supplied no body digest.
 *
 *  The id is recorded in canonical form, not as the bytes on the wire: only a
 *  string without lone surrogates or a safe integer gets a reference, written
 *  as JSON.stringify writes the parsed value ("7" becomes "7"; 7 and "7"
 *  stay distinct). The body digest is what covers the exact bytes. The rule
 *  is pinned by integrations/invocation-evidence/fixtures/jsonrpc-id-vectors.json,
 *  which the Python side checks too. */
export function requestRefFor(req: JsonRpcRequest, deps: Deps): RequestRef | undefined {
  if (!deps.bodySha256) return undefined;
  const id = req.id;
  const referenceable =
    (typeof id === "string" && wellFormed(id)) ||
    (typeof id === "number" && Number.isSafeInteger(id));
  if (!referenceable) return undefined;
  return {
    transport: "mcp-streamable-http",
    jsonrpc_id: JSON.stringify(id),
    body_sha256: deps.bodySha256,
  };
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

/** Outcomes where REMORA returned the item to its queue: nothing ran, and a
 *  person can approve it again, so the proposal is kept for the next poll. */
const LAPSED = new Set(["approval_expired", "approval_invalidated"]);

/** The dispatch an effect receipt is about, read from REMORA's own assess
 *  and execute responses. Nothing here comes from the tool. */
function bindingFrom(
  assessed: { proposal_id?: string; tool_call_hash?: string },
  run: ExecuteResult | undefined,
  tokenJti: unknown,
): EffectBinding {
  const execution = (run?.tool_execution ?? {}) as Record<string, unknown>;
  const jti = String(run?.execution_grant?.jti ?? tokenJti ?? "");
  return {
    proposal_id: String(run?.proposal_id ?? execution.proposal_id
                        ?? assessed.proposal_id ?? ""),
    tool_call_hash: String(assessed.tool_call_hash ?? ""),
    grant_jti: jti,
    execution_id: String(execution.execution_id ?? jti),
    execution_context_hash: String(execution.execution_context_hash ?? ""),
  };
}

async function readBack(
  deps: Deps, call: ToolCall, run: ExecuteResult | undefined,
  binding: EffectBinding, dispatchedAt: number,
): Promise<EffectReport | null> {
  if (!deps.verifyEffect) return null;
  const result = (run?.tool_execution as { result?: unknown } | undefined)?.result;
  return deps.verifyEffect(
    call.tool_name, call.arguments,
    result && typeof result === "object" ? result as Record<string, unknown> : {},
    binding, dispatchedAt);
}

/** What the model is told about the effect. `effect` is REMORA's recorded
 *  verdict and appears only when REMORA recorded the receipt; the gateway's
 *  own reading is reported beside it, labelled as such. */
function effectFields(report: EffectReport | null): {
  fields: Record<string, unknown>; notes: string[]; mismatch: boolean;
} {
  if (!report) return { fields: {}, notes: [], mismatch: false };
  const { observation, record } = report;
  const mismatch = observation.status === "EFFECT_MISMATCH"
    || record.status === "EFFECT_MISMATCH";
  const notes: string[] = [];
  if (mismatch) {
    notes.push(
      "The system of record does not match what was approved. Do not assume " +
      "it worked. Report this rather than retrying.",
    );
  }
  if (!record.recorded && record.reason !== "nothing_to_attest") {
    notes.push(
      "The gateway read the system of record back, but REMORA has not " +
      `recorded that reading (${record.reason ?? "unknown reason"}). It is ` +
      "the gateway's own observation, not evidence that the effect happened.",
    );
  }
  // A reported VERIFIED REMORA had no signed postcondition to check is a
  // claim. The model is told so; it never reads EFFECT_VERIFIED (SDD L7).
  const claimed = record.recorded && record.verdict_source === "claimed";
  if (claimed) {
    notes.push(
      "REMORA recorded the gateway's reading as a claim: it has no signed " +
      "postcondition for this tool, so it did not check the effect itself.",
    );
  }
  return {
    fields: {
      ...(record.recorded && record.status
        ? { effect: claimed ? "EFFECT_CLAIMED" : record.status,
            effect_reason: observation.reason_code }
        : {}),
      effect_observation: {
        status: observation.status,
        reason_code: observation.reason_code,
        ...(observation.detail ? { detail: observation.detail } : {}),
      },
      effect_record: record,
    },
    notes,
    mismatch,
  };
}

const nowSeconds = (deps: Deps) => Math.floor((deps.now ?? Date.now)() / 1000);

async function callTool(
  name: string,
  args: Record<string, unknown>,
  deps: Deps,
  requestRef?: RequestRef,
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

  // Shape validation before authority. A missing required field is a
  // FIXABLE mistake, and the generic refusal ("do not retry") is exactly the
  // wrong guidance for it — the agent should retry, with the field filled.
  // This checks the schema the tool itself published; it decides nothing
  // about whether the call may happen.
  const schema = toolsFor(deps.env).find((t: GovernedTool) => t.name === name);
  const missing = (schema?.inputSchema.required ?? []).filter(
    (field) => args[field] === undefined || args[field] === null || args[field] === "",
  );
  if (missing.length) {
    return textResult({
      error: "missing_required_arguments",
      missing,
      explanation: missing.includes("intent_ref")
        ? "Every governed call names the work order it acts under. Retry " +
          "with intent_ref set to a task subject (for example " +
          "task:survey-business-graph) or ask the user which task applies."
        : `Retry the same call with ${missing.join(", ")} filled in. ` +
          "Nothing was assessed and nothing ran.",
    }, true);
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
    ...(requestRef ? { request_ref: requestRef } : {}),
  };

  const { status, body } = await deps.remora.assess(call);
  if (status !== 200) {
    return textResult(
      { error: "assess failed", http_status: status, detail: body },
      true,
    );
  }

  if (body.decision === "accept" && body.execution_token) {
    const dispatchedAt = nowSeconds(deps);
    const run = await deps.remora.executeAccepted(body.execution_token, call);
    const acceptStatus = dispatchStatus(run.status, run.body?.tool_execution);
    // Read back on the ACCEPT path as on the review path: it is the path
    // where nobody looked, so the effect is the only check after dispatch.
    const effect = acceptStatus === "refused" || acceptStatus === "execution_failed"
      ? effectFields(null)
      : effectFields(await readBack(
          deps, call, run.body,
          bindingFrom(body, run.body, body.execution_token.jti), dispatchedAt));
    const acceptExplanation = [statusExplanation(acceptStatus), ...effect.notes]
      .filter(Boolean).join(" ");
    return textResult({
      decision: "accept",
      // An ACCEPT is the one outcome that must never be unexplained: it is
      // the only one where nobody looked. Which path allowed it, and which
      // signals carried it, belong in the answer.
      reasons: body.reasons ?? [],
      ...(body.semantic ? { signals: body.semantic } : {}),
      // Derived from the body, not from the transport. A 200 means the
      // execution API answered; the tool_execution object says what happened
      // (RMR-006). A refused dispatch and a lost result both used to arrive
      // here as "executed".
      status: acceptStatus,
      ...(acceptExplanation ? { explanation: acceptExplanation } : {}),
      outcome: run.body?.outcome,
      result: run.body?.tool_execution,
      ...effect.fields,
      // An execution that failed without a tool_execution object has failed
      // BEFORE enforcement reported anything, which is the case an operator
      // cannot diagnose from a bare "execution_failed". Carried only on the
      // failure path, so a successful call gains no new surface.
      ...(run.status !== 200
        ? { http_status: run.status, detail: run.body?.detail ?? run.body }
        : {}),
    }, acceptStatus !== "executed" || effect.mismatch);
  }

  // Anything that is not an outright ACCEPT leaves the side effect undone.
  // VERIFY and ESCALATE both carry a review item; ABSTAIN does not, and gets
  // no proposal to poll because there is nothing for a person to approve.
  let proposalId: string | undefined;
  if (body.review_item_id) {
    proposalId = deps.newId();
    await deps.store.put(proposalId, {
      review_item_id: body.review_item_id,
      call,
      ...(body.proposal_id ? { proposal_id: body.proposal_id } : {}),
      ...(body.tool_call_hash ? { tool_call_hash: body.tool_call_hash } : {}),
    });
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

  const dispatchedAt = nowSeconds(deps);
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

  const run = body as ExecuteResult;
  const outcome = String(run.outcome ?? "");

  // A 200 without a dispatch. REMORA answers 200 when it declines to run an
  // approved item, and those answers carry no tool_execution. Classified from
  // the body alone they read as "unknown" — "it may have run, do not retry" —
  // which is false: nothing ran. The proposal is kept, because the item is
  // still REMORA's to approve again (lapsed) or still approved (refused).
  if (LAPSED.has(outcome)) {
    return textResult({
      status: "pending_approval",
      proposal_id: proposalId,
      outcome,
      detail: run.detail,
      explanation:
        "Nothing has been executed. The approval no longer covers this call " +
        (outcome === "approval_expired"
          ? "because it expired"
          : "because the situation changed after it was given") +
        ", so REMORA put it back in the queue. A person has to approve it " +
        "again; then poll remora_proposal_status with the same proposal_id.",
    });
  }
  if (outcome === "binding_refused") {
    return textResult({
      status: "refused",
      proposal_id: proposalId,
      outcome,
      detail: run.detail,
      explanation: statusExplanation("refused") + " The call presented did " +
        "not match the approved one.",
    }, true);
  }

  await deps.store.delete(proposalId);
  const execution = run.tool_execution ?? {};

  const pollStatus = dispatchStatus(status, execution);

  // Dispatching and the effect happening are different facts. The read-back
  // is what tells them apart, and its verdict is reported as it comes —
  // including a mismatch, which is bad news about ourselves.
  //
  // Not attempted on a refused dispatch: nothing was sent, so the system of
  // record correctly shows no change, and reporting that as EFFECT_MISMATCH
  // would manufacture bad news out of a correct refusal. It IS attempted on an
  // unknown one, which is where a read-back is worth the most.
  const effect = pollStatus === "refused"
    ? effectFields(null)
    : effectFields(await readBack(
        deps, pending.call, run, bindingFrom(pending, run, undefined),
        dispatchedAt));

  // One explanation key, built from every part that has something to say. Two
  // separate `explanation` entries in the same object literal would silently
  // keep the last one, and the one that got dropped would be the dispatch
  // status — the part the model most needs.
  const explanation = [statusExplanation(pollStatus), ...effect.notes]
    .filter(Boolean).join(" ");

  return textResult({
    status: pollStatus,
    ...(explanation ? { explanation } : {}),
    proposal_id: proposalId,
    outcome: run.outcome,
    result: execution,
    ...effect.fields,
  }, pollStatus !== "executed" || effect.mismatch);
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
        return ok(req.id, await callTool(
          params.name, params.arguments ?? {}, deps, requestRefFor(req, deps)));
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
