/**
 * Authentication for the agent-control Worker.
 *
 * Two principal classes, two credential paths — deliberately disjoint so the
 * same credential can never act as both proposer and approver:
 *
 *   workload (AI/service):  shared bearer CONTROL_SECRET (existing contract).
 *   human (reviewer):       Cloudflare Access OIDC identity, proven by a
 *                           verified `Cf-Access-Jwt-Assertion` JWT (RS256,
 *                           checked against the team's JWKS, aud + exp + nbf).
 *
 * The human path is pluggable via HumanIdentityVerifier so tests (and
 * non-Access deployments) inject their own verifier instead of depending on a
 * live Cloudflare Access account. Everything fails closed: missing config,
 * missing header, bad signature, wrong audience — all yield "no identity",
 * never a downgraded-but-accepted one.
 */

import { type AuthContext, ROLE_REVIEWER } from "./principal";

export interface HumanIdentity {
  /** Verified stable identity (email claim from the Access JWT). */
  principalId: string;
  roles: string[];
  authMethod: string;
}

export interface HumanIdentityVerifier {
  verify(request: Request): Promise<HumanIdentity | null>;
}

export interface AuthEnvConfig {
  CONTROL_SECRET?: string;
  TENANT_ID?: string;
  /** Cloudflare Access team domain, e.g. "myteam.cloudflareaccess.com". */
  ACCESS_TEAM_DOMAIN?: string;
  /** Expected `aud` of the Access application protecting the review surface. */
  ACCESS_AUD?: string;
  /** Comma-separated allowlist of reviewer identities (emails). */
  REVIEWER_EMAILS?: string;
}

/**
 * Resolve the authenticated context for a request.
 *
 * Order matters for safety: a request presenting the workload bearer IS the
 * workload, even if it also carries Access headers — the shared credential
 * can never be upgraded to a human identity by adding headers to the call.
 */
export async function authenticate(
  request: Request,
  env: AuthEnvConfig,
  humanVerifier: HumanIdentityVerifier,
): Promise<AuthContext | null> {
  const tenantId = env.TENANT_ID ?? "default";
  const auth = request.headers.get("Authorization") ?? "";

  if (auth.startsWith("Bearer ")) {
    if (!env.CONTROL_SECRET) return null; // fail closed on misconfiguration
    if (auth === `Bearer ${env.CONTROL_SECRET}`) {
      return {
        tenantId,
        principalId: "control_secret_bearer",
        principalType: "workload",
        roles: ["workload"],
        authMethod: "shared_bearer",
      };
    }
    return null;
  }

  const human = await humanVerifier.verify(request);
  if (human) {
    return {
      tenantId,
      principalId: human.principalId,
      principalType: "human",
      roles: human.roles,
      authMethod: human.authMethod,
    };
  }
  return null;
}

// ── Cloudflare Access verifier (production adapter) ───────────────────────────

interface AccessJwtPayload {
  aud?: string | string[];
  email?: string;
  exp?: number;
  nbf?: number;
  iss?: string;
  sub?: string;
}

interface Jwk {
  kid: string;
  kty: string;
  alg?: string;
  n: string;
  e: string;
}

// Module-scope JWKS cache: Access rotates keys rarely; a 5-minute TTL keeps
// verification off the network on the hot path without pinning stale keys.
let jwksCache: { domain: string; keys: Jwk[]; fetchedAt: number } | null = null;
const JWKS_TTL_MS = 5 * 60 * 1000;

function b64urlToBytes(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + pad;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function fetchJwks(teamDomain: string): Promise<Jwk[]> {
  const now = Date.now();
  if (jwksCache && jwksCache.domain === teamDomain && now - jwksCache.fetchedAt < JWKS_TTL_MS) {
    return jwksCache.keys;
  }
  const resp = await fetch(`https://${teamDomain}/cdn-cgi/access/certs`);
  if (!resp.ok) throw new Error(`JWKS fetch failed: ${resp.status}`);
  const data = (await resp.json()) as { keys?: Jwk[] };
  const keys = data.keys ?? [];
  jwksCache = { domain: teamDomain, keys, fetchedAt: now };
  return keys;
}

async function verifyAccessJwt(
  token: string,
  teamDomain: string,
  expectedAud: string,
): Promise<AccessJwtPayload | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;

  let header: { kid?: string; alg?: string };
  let payload: AccessJwtPayload;
  try {
    header = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[0])));
    payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(parts[1])));
  } catch {
    return null;
  }
  if (header.alg !== "RS256" || !header.kid) return null;

  const jwks = await fetchJwks(teamDomain);
  const jwk = jwks.find((k) => k.kid === header.kid);
  if (!jwk) return null;

  const key = await crypto.subtle.importKey(
    "jwk",
    { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const data = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const valid = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    b64urlToBytes(parts[2]) as unknown as ArrayBuffer,
    data,
  );
  if (!valid) return null;

  const nowSec = Math.floor(Date.now() / 1000);
  if (typeof payload.exp !== "number" || payload.exp <= nowSec) return null;
  if (typeof payload.nbf === "number" && payload.nbf > nowSec + 60) return null;
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(expectedAud)) return null;
  if (!payload.email) return null;

  return payload;
}

/**
 * Production human-identity adapter backed by Cloudflare Access.
 *
 * Roles: an identity on the REVIEWER_EMAILS allowlist gets ROLE_REVIEWER.
 * Access group/MFA policy is enforced by the Access application itself; the
 * allowlist is the worker-side authorization layer on top of authentication.
 */
export function cloudflareAccessVerifier(env: AuthEnvConfig): HumanIdentityVerifier {
  return {
    async verify(request: Request): Promise<HumanIdentity | null> {
      if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) return null;
      const token = request.headers.get("Cf-Access-Jwt-Assertion");
      if (!token) return null;
      let payload: AccessJwtPayload | null;
      try {
        payload = await verifyAccessJwt(token, env.ACCESS_TEAM_DOMAIN, env.ACCESS_AUD);
      } catch {
        return null; // fail closed on JWKS/network errors
      }
      if (!payload?.email) return null;

      const reviewers = (env.REVIEWER_EMAILS ?? "")
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
      const email = payload.email.toLowerCase();
      const roles = reviewers.includes(email) ? [ROLE_REVIEWER] : [];
      return { principalId: email, roles, authMethod: "cloudflare_access_jwt" };
    },
  };
}
