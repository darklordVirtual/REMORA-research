// Server-side access gate for the control-plane-facing server functions
// (issue #55). Without it, executeTool / getAudit / session functions were a
// confused deputy: any anonymous visitor made the server attach
// REMORA_CONTROL_SECRET and invoke store_artifact / audit_decision, or dump
// the audit log. These functions now require an operator access token.
//
// Fail-closed: if REMORA_APP_ACCESS_TOKEN is unset the control plane is
// disabled entirely (the public demo does not expose mutating operations).

/** Constant-time comparison to avoid token timing leaks. */
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Throws unless a valid operator access token is presented. Read
 * process.env inside the handler (never at module top level — TanStack
 * inlines module-scope env reads to undefined).
 */
export function assertAppAccess(token: string | undefined): void {
  const expected = (process.env.REMORA_APP_ACCESS_TOKEN || "").trim();
  if (!expected) {
    throw new Error(
      "control plane disabled: REMORA_APP_ACCESS_TOKEN is not configured on the server",
    );
  }
  if (!token || !timingSafeEqual(token.trim(), expected)) {
    throw new Error("unauthorized: a valid operator access token is required");
  }
}
