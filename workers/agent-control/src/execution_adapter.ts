/**
 * Canonical-execution adapter (ADR-single-authoritative-execution-path,
 * migration step 3).
 *
 * When the deployment binds EXECUTION_SERVICE (a service binding or URL to
 * the canonical REMORA execution API), write-effect tools are no longer
 * executed in-worker: the proposal is forwarded through the canonical
 * proposal → decision → grant → PEP → lease path, and this worker becomes
 * pure ingress for those calls. Without the binding, the structural
 * write floor (WRITE_IMPACT_TOOLS + first-class approvals) remains in force
 * — the adapter never weakens it, it replaces it with something stronger.
 *
 * Fail-closed: any transport error, malformed response or non-accept
 * decision results in NOT executing. There is no fallback from canonical to
 * in-worker execution — a deployment that binds the canonical service has
 * chosen its authority.
 */

export interface CanonicalExecutionEnv {
  /** Service binding or absent. When absent the adapter is inactive. */
  EXECUTION_SERVICE?: { fetch(input: string, init?: RequestInit): Promise<Response> };
  /** Bearer for the canonical API (workload principal there). */
  EXECUTION_API_TOKEN?: string;
}

export interface CanonicalOutcome {
  /** True only when the canonical service reports a real dispatch. */
  executed: boolean;
  /** accept | verify | abstain | escalate | error */
  decision: string;
  proposal_id?: string;
  review_item_id?: string;
  refusal_reason?: string;
  result?: unknown;
  detail?: string;
}

export function canonicalExecutionConfigured(env: CanonicalExecutionEnv): boolean {
  return Boolean(env.EXECUTION_SERVICE && env.EXECUTION_API_TOKEN);
}

async function post(
  env: CanonicalExecutionEnv,
  path: string,
  body: unknown,
): Promise<{ ok: boolean; status: number; data: Record<string, unknown> | null }> {
  const resp = await env.EXECUTION_SERVICE!.fetch(`https://execution${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.EXECUTION_API_TOKEN}`,
    },
    body: JSON.stringify(body),
  });
  let data: Record<string, unknown> | null = null;
  try {
    data = (await resp.json()) as Record<string, unknown>;
  } catch {
    data = null;
  }
  return { ok: resp.ok, status: resp.status, data };
}

/**
 * Run one write-effect tool call through the canonical execution service.
 *
 * assess → (accept) execute-accepted under the single-use token, or
 * (verify/escalate) surface the review item id so the canonical review path
 * — not this worker — owns the approval. Every other shape refuses.
 */
export async function executeViaCanonicalService(
  env: CanonicalExecutionEnv,
  toolName: string,
  args: Record<string, unknown>,
  targetEnvironment: string,
): Promise<CanonicalOutcome> {
  const toolCall = {
    tool_name: toolName,
    arguments: args,
    target_environment: targetEnvironment,
  };

  let assess;
  try {
    assess = await post(env, "/v1/execution/assess", toolCall);
  } catch (e) {
    return {
      executed: false,
      decision: "error",
      refusal_reason: "canonical_service_unreachable",
      detail: e instanceof Error ? e.message : String(e),
    };
  }
  if (!assess.ok || !assess.data) {
    return {
      executed: false,
      decision: "error",
      refusal_reason: `canonical_assess_failed:${assess.status}`,
    };
  }

  const decision = String(assess.data.decision ?? "");
  const proposalId = assess.data.proposal_id as string | undefined;

  if (decision !== "accept") {
    return {
      executed: false,
      decision: decision || "error",
      proposal_id: proposalId,
      review_item_id: assess.data.review_item_id as string | undefined,
      refusal_reason:
        decision === "verify" || decision === "escalate"
          ? "canonical_review_required"
          : "canonical_not_accepted",
    };
  }

  const token = assess.data.execution_token;
  if (!token) {
    return {
      executed: false,
      decision,
      proposal_id: proposalId,
      refusal_reason: "canonical_accept_without_token",
    };
  }

  let exec;
  try {
    exec = await post(env, "/v1/execution/execute-accepted", {
      execution_token: token,
      tool_call: toolCall,
    });
  } catch (e) {
    // The token may or may not have been consumed server-side; state is
    // unknown and MUST NOT be retried from here (the outbox owns it).
    return {
      executed: false,
      decision,
      proposal_id: proposalId,
      refusal_reason: "canonical_execute_unreachable_state_unknown",
      detail: e instanceof Error ? e.message : String(e),
    };
  }
  if (!exec.ok || !exec.data) {
    return {
      executed: false,
      decision,
      proposal_id: proposalId,
      refusal_reason: `canonical_execute_refused:${exec.status}`,
    };
  }

  const toolExecution = (exec.data.tool_execution ?? {}) as Record<string, unknown>;
  return {
    executed: toolExecution.executed === true,
    decision,
    proposal_id: proposalId,
    refusal_reason:
      toolExecution.executed === true
        ? undefined
        : String(toolExecution.refusal_reason ?? "canonical_dispatch_refused"),
    result: toolExecution.result,
  };
}
