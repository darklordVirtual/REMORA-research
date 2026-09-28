/**
 * The tenant an administrative read is allowed to see.
 *
 * CONTROL_SECRET authenticates the operator of THIS deployment, and
 * TENANT_ID says which tenant the deployment serves. A request may name that
 * tenant or none; naming another one is refused rather than honoured, so a
 * D1 database shared between deployments cannot be read across tenants with
 * one deployment's secret. Plain TypeScript with no Workers imports, so it can
 * be executed outside the runtime (tests/test_agent_control_tenant_binding.py).
 */

export type TenantResolution =
  | { ok: true; tenant: string }
  | { ok: false; status: 403; reason: "tenant_mismatch" };

export function resolveReadTenant(
  requested: string | null,
  configured: string | undefined,
): TenantResolution {
  const tenant = configured || "default";
  if (requested && requested !== tenant) {
    return { ok: false, status: 403, reason: "tenant_mismatch" };
  }
  return { ok: true, tenant };
}
