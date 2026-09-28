/**
 * Who may reach /mcp, and whether this deployment may serve production.
 *
 * /mcp calls REMORA with the Worker's own operator token, so anyone who reaches
 * it acts with that token's authority to propose. Until this module the only
 * thing in front of it was a Cloudflare Access policy configured outside the
 * repository: correct when present, invisible when a route or policy drifted.
 * The Worker now verifies the Access assertion itself (defence in depth, not a
 * replacement for the policy), and refuses when it is not told what to verify
 * against rather than falling open.
 *
 * The production profile turns three deployment facts that used to be
 * optional into prerequisites: a durable tenant audit chain, the authority /
 * executor custody split, and in-Worker Access verification.
 */

export interface AccessConfig {
  /** Team domain, e.g. "remora.cloudflareaccess.com". Scheme optional. */
  teamDomain: string;
  /** The Access application's AUD tag. */
  aud: string;
  fetchJwks: (url: string) => Promise<{ keys?: JsonWebKey[] }>;
  /** Seconds since the epoch. */
  now: () => number;
  /** Key-set cache. Defaults to one shared by the Worker isolate. */
  cache?: JwksCache;
}

export type JwksCache = Map<string, { keys: JsonWebKey[]; fetchedAt: number }>;

export type AccessVerdict =
  | { ok: true; subject: string }
  | { ok: false; reason: string };

export type Admission =
  | { ok: true; subject: string }
  | { ok: false; status: number; reason: string };

/** Clock skew tolerated on exp and nbf, in seconds. */
const SKEW_SECONDS = 60;
/** How long a fetched key set is reused before it is fetched again. */
const JWKS_TTL_SECONDS = 600;

const sharedJwksCache: JwksCache = new Map();

function normaliseTeam(teamDomain: string): string {
  return teamDomain.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

function b64urlDecode(part: string): Uint8Array {
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function decodeJson(part: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(new TextDecoder().decode(b64urlDecode(part)));
    return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

async function keysFor(
  config: AccessConfig,
  team: string,
  refresh: boolean,
): Promise<JsonWebKey[]> {
  const cache = config.cache ?? sharedJwksCache;
  const cached = cache.get(team);
  if (!refresh && cached && config.now() - cached.fetchedAt < JWKS_TTL_SECONDS) {
    return cached.keys;
  }
  const body = await config.fetchJwks(`https://${team}/cdn-cgi/access/certs`);
  const keys = Array.isArray(body?.keys) ? body.keys : [];
  cache.set(team, { keys, fetchedAt: config.now() });
  return keys;
}

/** Verify a Cloudflare Access application token (RS256 JWT). */
export async function verifyAccessJwt(
  token: string,
  config: AccessConfig,
): Promise<AccessVerdict> {
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };
  const header = decodeJson(parts[0]);
  const claims = decodeJson(parts[1]);
  if (!header || !claims) return { ok: false, reason: "malformed" };
  // Pinned, never read from the token: alg "none" and HS256-with-the-public-
  // key are the classic ways a verifier is talked out of verifying.
  if (header.alg !== "RS256") return { ok: false, reason: "unsupported_alg" };
  const kid = typeof header.kid === "string" ? header.kid : "";

  const team = normaliseTeam(config.teamDomain);
  let jwk: JsonWebKey & { kid?: string } | undefined;
  try {
    const find = (keys: JsonWebKey[]) =>
      keys.find((k) => (k as { kid?: string }).kid === kid);
    jwk = find(await keysFor(config, team, false));
    // One refresh for a key id we have not seen: Access rotates its keys, and
    // a stale cache must not turn a rotation into an outage.
    if (!jwk) jwk = find(await keysFor(config, team, true));
  } catch {
    return { ok: false, reason: "jwks_unavailable" };
  }
  if (!jwk) return { ok: false, reason: "unknown_key" };

  let valid = false;
  try {
    const key = await crypto.subtle.importKey(
      "jwk",
      jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    valid = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      b64urlDecode(parts[2]),
      new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
    );
  } catch {
    valid = false;
  }
  if (!valid) return { ok: false, reason: "bad_signature" };

  const aud = claims.aud;
  const audiences = Array.isArray(aud) ? aud : [aud];
  if (!audiences.includes(config.aud)) return { ok: false, reason: "audience_mismatch" };
  if (claims.iss !== `https://${team}`) return { ok: false, reason: "issuer_mismatch" };
  const now = config.now();
  if (typeof claims.exp !== "number" || claims.exp + SKEW_SECONDS < now) {
    return { ok: false, reason: "expired" };
  }
  if (typeof claims.nbf === "number" && claims.nbf - SKEW_SECONDS > now) {
    return { ok: false, reason: "not_yet_valid" };
  }
  // A service token carries its client id as common_name and an empty sub; a
  // person carries sub (and email). Either identifies the caller for audit.
  const subject =
    (typeof claims.sub === "string" && claims.sub) ||
    (typeof claims.common_name === "string" && claims.common_name) ||
    "unknown";
  return { ok: true, subject };
}

export interface AdmissionEnv {
  REMORA_API_URL?: string;
  ACCESS_TEAM_DOMAIN?: string;
  ACCESS_AUD?: string;
}

/** Decide whether this request may reach /mcp. */
export async function admitMcp(
  request: Request,
  env: AdmissionEnv,
  deps: Partial<Pick<AccessConfig, "fetchJwks" | "now" | "cache">> = {},
): Promise<Admission> {
  // The direct transport exists only in the development config (wrangler.dev
  // .toml); there is no edge in front of a local run to verify against.
  if (env.REMORA_API_URL) return { ok: true, subject: "development" };
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) {
    return { ok: false, status: 503, reason: "access_not_configured" };
  }
  const token = request.headers.get("Cf-Access-Jwt-Assertion");
  if (!token) return { ok: false, status: 401, reason: "access_assertion_missing" };
  const verdict = await verifyAccessJwt(token, {
    teamDomain: env.ACCESS_TEAM_DOMAIN,
    aud: env.ACCESS_AUD,
    fetchJwks:
      deps.fetchJwks ??
      (async (url) => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`jwks ${response.status}`);
        return (await response.json()) as { keys?: JsonWebKey[] };
      }),
    now: deps.now ?? (() => Math.floor(Date.now() / 1000)),
    cache: deps.cache,
  });
  return verdict.ok ? verdict : { ok: false, status: 403, reason: verdict.reason };
}

export const DEPLOYMENT_PROFILES = ["development", "staging", "production"] as const;

export interface ReadinessEnv extends AdmissionEnv {
  REMORA_DEPLOYMENT_PROFILE?: string;
  REMORA_PG_DSN?: string;
  /** Present or not; listed so a test can show it does not satisfy the
   *  durable-chain prerequisite. */
  STATE_DB?: unknown;
  EXECUTION?: unknown;
  REMORA_LEASE_ED25519_PRIVATE?: string;
  REMORA_LEASE_ED25519_PUBLIC?: string;
}

/**
 * What this deployment lacks for its declared profile. Empty means ready.
 *
 * Production requires REMORA_PG_DSN specifically. The D1 binding makes the
 * grant and nonce ledgers durable, but the tenant audit chain has no D1
 * adapter (servers/execution_api.py::_effect_audit_is_durable), and
 * REMORA_CHAIN_DB is a path on the container's disk, which Cloudflare discards
 * at every restart.
 */
export function productionReadiness(env: ReadinessEnv): {
  profile: string;
  problems: string[];
} {
  const profile = String(env.REMORA_DEPLOYMENT_PROFILE ?? "").trim();
  if (!profile) return { profile: "unset", problems: ["deployment_profile_missing"] };
  if (!(DEPLOYMENT_PROFILES as readonly string[]).includes(profile)) {
    return { profile, problems: ["deployment_profile_unknown"] };
  }
  if (profile !== "production") return { profile, problems: [] };
  const problems: string[] = [];
  if (!env.REMORA_PG_DSN) problems.push("durable_audit_chain_missing");
  if (!env.EXECUTION || !env.REMORA_LEASE_ED25519_PRIVATE || !env.REMORA_LEASE_ED25519_PUBLIC) {
    problems.push("custody_split_missing");
  }
  if (!env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) problems.push("access_not_configured");
  return { profile, problems };
}
