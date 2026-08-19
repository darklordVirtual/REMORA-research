/**
 * Typed authenticated principals for the agent-control Worker.
 *
 * Trusted identity is derived ONLY from credentials verified in auth.ts —
 * never from body fields (user_id, approved_by), query parameters or any
 * other caller-controlled value. Body-supplied identity may be recorded as an
 * explicitly unverified annotation, but it never becomes the principal.
 */

export type PrincipalType = "workload" | "human";

export interface AuthContext {
  tenantId: string;
  principalId: string;
  principalType: PrincipalType;
  roles: string[];
  authMethod: string;
}

/** Role required to grant approvals. Granted in auth.ts from deployment config. */
export const ROLE_REVIEWER = "reviewer";

export function isHumanReviewer(ctx: AuthContext): boolean {
  return ctx.principalType === "human" && ctx.roles.includes(ROLE_REVIEWER);
}
