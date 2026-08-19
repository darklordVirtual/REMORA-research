/**
 * First-class immutable approvals for the agent-control Worker.
 *
 * Replaces the loose approval-by-audit-id flag (audit_log.approved) with an
 * approval object bound to the exact proposal, exact tool-call hash, ToolSpec
 * identity and policy identity, with expiry and single-use consumption.
 *
 * Guards enforced here (all fail closed):
 *   - only an authenticated human with the reviewer role may grant
 *   - reviewer may never equal the requester principal (no self-approval)
 *   - tenant must match between proposal, approval and consumption
 *   - consumption requires exact tool-call hash, ToolSpec hash and policy
 *     bundle hash match, unexpired, decision=approved, not already consumed
 *
 * Storage is behind ApprovalStore so the guards are testable without a live
 * D1 database; D1ApprovalStore is the deployment implementation.
 */

import { type AuthContext, isHumanReviewer } from "./principal";

export interface ProposalRecord {
  proposalId: number; // audit_log id
  tenantId: string;
  requesterPrincipal: string;
  toolName: string;
  toolCallHash: string; // audit_log.input_hash
}

export interface ApprovalRecord {
  approvalId: string;
  tenantId: string;
  proposalId: number;
  requesterPrincipal: string;
  reviewerPrincipal: string;
  reviewerRoles: string[];
  toolCallHash: string;
  toolspecHash: string;
  toolspecVersion: string;
  policyBundleHash: string;
  issuedAt: string; // ISO-8601 UTC
  expiresAt: string;
  decision: "approved" | "rejected";
  reasonCode: string;
  /** HMAC-SHA256 over the canonical record when a signing key is set; "" = unsigned. */
  signature: string;
  consumedAt: string | null;
}

export interface ApprovalStore {
  getProposal(proposalId: number): Promise<ProposalRecord | null>;
  insertApproval(rec: ApprovalRecord): Promise<void>;
  getApprovalForProposal(proposalId: number): Promise<ApprovalRecord | null>;
  /** Atomically mark consumed; returns false if already consumed. */
  markConsumed(approvalId: string, consumedAt: string): Promise<boolean>;
}

export type GrantResult =
  | { ok: true; approval: ApprovalRecord }
  | { ok: false; reason: string };

export type ConsumeResult =
  | { ok: true; approval: ApprovalRecord }
  | { ok: false; reason: string };

export const DEFAULT_APPROVAL_TTL_SECONDS = 15 * 60;

function canonicalApproval(rec: Omit<ApprovalRecord, "signature" | "consumedAt">): string {
  // Stable key order — matches JSON.stringify over an explicitly ordered object.
  return JSON.stringify({
    approval_id: rec.approvalId,
    decision: rec.decision,
    expires_at: rec.expiresAt,
    issued_at: rec.issuedAt,
    policy_bundle_hash: rec.policyBundleHash,
    proposal_id: rec.proposalId,
    reason_code: rec.reasonCode,
    requester_principal: rec.requesterPrincipal,
    reviewer_principal: rec.reviewerPrincipal,
    reviewer_roles: [...rec.reviewerRoles].sort(),
    tenant_id: rec.tenantId,
    tool_call_hash: rec.toolCallHash,
    toolspec_hash: rec.toolspecHash,
    toolspec_version: rec.toolspecVersion,
  });
}

async function hmacHex(key: string, message: string): Promise<string> {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function grantApproval(
  store: ApprovalStore,
  ctx: AuthContext,
  args: {
    proposalId: number;
    decision: "approved" | "rejected";
    reasonCode: string;
    toolspecHash: string;
    toolspecVersion: string;
    policyBundleHash: string;
    ttlSeconds?: number;
    signingKey?: string;
    now?: Date;
  },
): Promise<GrantResult> {
  // Identity comes ONLY from the authenticated context — there is deliberately
  // no approved_by/user_id input on this path.
  if (!isHumanReviewer(ctx)) {
    return { ok: false, reason: "REVIEWER_IDENTITY_REQUIRED" };
  }

  const proposal = await store.getProposal(args.proposalId);
  if (!proposal) return { ok: false, reason: "PROPOSAL_NOT_FOUND" };
  if (proposal.tenantId !== ctx.tenantId) {
    return { ok: false, reason: "TENANT_MISMATCH" };
  }
  if (proposal.requesterPrincipal === ctx.principalId) {
    return { ok: false, reason: "SELF_APPROVAL_FORBIDDEN" };
  }
  const existing = await store.getApprovalForProposal(args.proposalId);
  if (existing) return { ok: false, reason: "APPROVAL_ALREADY_EXISTS" };

  const now = args.now ?? new Date();
  const ttl = args.ttlSeconds ?? DEFAULT_APPROVAL_TTL_SECONDS;
  const base = {
    approvalId: crypto.randomUUID(),
    tenantId: proposal.tenantId,
    proposalId: proposal.proposalId,
    requesterPrincipal: proposal.requesterPrincipal,
    reviewerPrincipal: ctx.principalId,
    reviewerRoles: ctx.roles,
    toolCallHash: proposal.toolCallHash,
    toolspecHash: args.toolspecHash,
    toolspecVersion: args.toolspecVersion,
    policyBundleHash: args.policyBundleHash,
    issuedAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + ttl * 1000).toISOString(),
    decision: args.decision,
    reasonCode: args.reasonCode,
  };
  const signature = args.signingKey ? await hmacHex(args.signingKey, canonicalApproval(base)) : "";
  const approval: ApprovalRecord = { ...base, signature, consumedAt: null };
  await store.insertApproval(approval);
  return { ok: true, approval };
}

/**
 * Consume an approval for execution. Single-use; every binding re-checked at
 * consumption time so a ToolSpec/policy/payload change after approval, an
 * expired approval, or a cross-tenant replay all refuse.
 */
export async function consumeApproval(
  store: ApprovalStore,
  args: {
    proposalId: number;
    tenantId: string;
    toolCallHash: string;
    toolspecHash: string;
    policyBundleHash: string;
    signingKey?: string;
    now?: Date;
  },
): Promise<ConsumeResult> {
  const approval = await store.getApprovalForProposal(args.proposalId);
  if (!approval) return { ok: false, reason: "APPROVAL_NOT_FOUND" };
  if (approval.decision !== "approved") return { ok: false, reason: "APPROVAL_REJECTED" };
  if (approval.tenantId !== args.tenantId) return { ok: false, reason: "TENANT_MISMATCH" };
  if (approval.toolCallHash !== args.toolCallHash) {
    return { ok: false, reason: "PAYLOAD_CHANGED_AFTER_APPROVAL" };
  }
  if (approval.toolspecHash !== args.toolspecHash) {
    return { ok: false, reason: "TOOLSPEC_CHANGED_AFTER_APPROVAL" };
  }
  if (approval.policyBundleHash !== args.policyBundleHash) {
    return { ok: false, reason: "POLICY_CHANGED_AFTER_APPROVAL" };
  }
  const now = args.now ?? new Date();
  if (now.toISOString() >= approval.expiresAt) {
    return { ok: false, reason: "APPROVAL_EXPIRED" };
  }
  if (args.signingKey) {
    const { signature: _sig, consumedAt: _c, ...base } = approval;
    const expected = await hmacHex(args.signingKey, canonicalApproval(base));
    if (approval.signature !== expected) {
      return { ok: false, reason: "APPROVAL_SIGNATURE_INVALID" };
    }
  }
  const claimed = await store.markConsumed(approval.approvalId, now.toISOString());
  if (!claimed) return { ok: false, reason: "APPROVAL_ALREADY_CONSUMED" };
  return { ok: true, approval };
}

// ── Stores ────────────────────────────────────────────────────────────────────

/** In-memory store for tests and local development. */
export class MemoryApprovalStore implements ApprovalStore {
  proposals = new Map<number, ProposalRecord>();
  approvals = new Map<string, ApprovalRecord>();

  async getProposal(proposalId: number): Promise<ProposalRecord | null> {
    return this.proposals.get(proposalId) ?? null;
  }
  async insertApproval(rec: ApprovalRecord): Promise<void> {
    this.approvals.set(rec.approvalId, rec);
  }
  async getApprovalForProposal(proposalId: number): Promise<ApprovalRecord | null> {
    for (const rec of this.approvals.values()) {
      if (rec.proposalId === proposalId) return rec;
    }
    return null;
  }
  async markConsumed(approvalId: string, consumedAt: string): Promise<boolean> {
    const rec = this.approvals.get(approvalId);
    if (!rec || rec.consumedAt !== null) return false;
    this.approvals.set(approvalId, { ...rec, consumedAt });
    return true;
  }
}

/** D1-backed deployment store (tables in schema.sql). */
export class D1ApprovalStore implements ApprovalStore {
  constructor(private db: D1Database) {}

  async getProposal(proposalId: number): Promise<ProposalRecord | null> {
    const row = await this.db
      .prepare(
        `SELECT a.id AS proposal_id, p.tenant_id, p.principal AS requester_principal,
                a.tool_called, a.input_hash
           FROM audit_log a JOIN proposal_principals p ON p.audit_id = a.id
          WHERE a.id = ?`,
      )
      .bind(proposalId)
      .first<{
        proposal_id: number;
        tenant_id: string;
        requester_principal: string;
        tool_called: string;
        input_hash: string;
      }>();
    if (!row) return null;
    return {
      proposalId: row.proposal_id,
      tenantId: row.tenant_id,
      requesterPrincipal: row.requester_principal,
      toolName: row.tool_called,
      toolCallHash: row.input_hash,
    };
  }

  async insertApproval(rec: ApprovalRecord): Promise<void> {
    await this.db
      .prepare(
        `INSERT INTO approvals
           (approval_id, tenant_id, proposal_id, requester_principal,
            reviewer_principal, reviewer_roles, tool_call_hash, toolspec_hash,
            toolspec_version, policy_bundle_hash, issued_at, expires_at,
            decision, reason_code, signature, consumed_at)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)`,
      )
      .bind(
        rec.approvalId,
        rec.tenantId,
        rec.proposalId,
        rec.requesterPrincipal,
        rec.reviewerPrincipal,
        JSON.stringify(rec.reviewerRoles),
        rec.toolCallHash,
        rec.toolspecHash,
        rec.toolspecVersion,
        rec.policyBundleHash,
        rec.issuedAt,
        rec.expiresAt,
        rec.decision,
        rec.reasonCode,
        rec.signature,
      )
      .run();
  }

  async getApprovalForProposal(proposalId: number): Promise<ApprovalRecord | null> {
    const row = await this.db
      .prepare(`SELECT * FROM approvals WHERE proposal_id = ? ORDER BY issued_at ASC LIMIT 1`)
      .bind(proposalId)
      .first<Record<string, unknown>>();
    if (!row) return null;
    return {
      approvalId: String(row.approval_id),
      tenantId: String(row.tenant_id),
      proposalId: Number(row.proposal_id),
      requesterPrincipal: String(row.requester_principal),
      reviewerPrincipal: String(row.reviewer_principal),
      reviewerRoles: JSON.parse(String(row.reviewer_roles)),
      toolCallHash: String(row.tool_call_hash),
      toolspecHash: String(row.toolspec_hash),
      toolspecVersion: String(row.toolspec_version),
      policyBundleHash: String(row.policy_bundle_hash),
      issuedAt: String(row.issued_at),
      expiresAt: String(row.expires_at),
      decision: row.decision as "approved" | "rejected",
      reasonCode: String(row.reason_code),
      signature: String(row.signature),
      consumedAt: row.consumed_at == null ? null : String(row.consumed_at),
    };
  }

  async markConsumed(approvalId: string, consumedAt: string): Promise<boolean> {
    const result = await this.db
      .prepare(`UPDATE approvals SET consumed_at = ? WHERE approval_id = ? AND consumed_at IS NULL`)
      .bind(consumedAt, approvalId)
      .run();
    return (result.meta?.changes ?? 0) > 0;
  }
}
