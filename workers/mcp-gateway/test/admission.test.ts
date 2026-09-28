/**
 * Admission to /mcp and the production profile, asserted as behaviour.
 *
 * The gateway used to rely entirely on a Cloudflare Access policy configured
 * outside this repository: /mcp itself authenticated nothing before calling
 * REMORA with the operator token. These tests pin the in-Worker check that
 * replaces that assumption, and the deployment profile that refuses to serve
 * production traffic without the durable chain and the custody split.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  admitMcp,
  productionReadiness,
  verifyAccessJwt,
  type AccessConfig,
} from "../src/admission";

const TEAM = "remora.cloudflareaccess.com";
const AUD = "aud-tag-123";
const NOW = 1_800_000_000; // seconds

function b64url(data: ArrayBuffer | Uint8Array | string): string {
  const bytes =
    typeof data === "string"
      ? new TextEncoder().encode(data)
      : new Uint8Array(data instanceof Uint8Array ? data : new Uint8Array(data));
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function keypair(kid: string) {
  const pair = (await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  const jwk = (await crypto.subtle.exportKey("jwk", pair.publicKey)) as JsonWebKey;
  return { privateKey: pair.privateKey, jwk: { ...jwk, kid, alg: "RS256" } };
}

async function sign(
  privateKey: CryptoKey,
  header: Record<string, unknown>,
  claims: Record<string, unknown>,
): Promise<string> {
  const input = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(claims))}`;
  const sig = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    privateKey,
    new TextEncoder().encode(input),
  );
  return `${input}.${b64url(sig)}`;
}

const goodClaims = {
  aud: [AUD],
  iss: `https://${TEAM}`,
  exp: NOW + 300,
  iat: NOW - 10,
  nbf: NOW - 10,
  sub: "",
  common_name: "service-token-client-id",
};

async function fixture() {
  const { privateKey, jwk } = await keypair("k1");
  let fetches = 0;
  const config: AccessConfig = {
    teamDomain: TEAM,
    aud: AUD,
    fetchJwks: async (url: string) => {
      fetches += 1;
      expect(url).toBe(`https://${TEAM}/cdn-cgi/access/certs`);
      return { keys: [jwk] };
    },
    now: () => NOW,
    cache: new Map(),
  };
  return { privateKey, config, fetches: () => fetches };
}

describe("verifyAccessJwt", () => {
  it("admits a token signed by the team key for this application", async () => {
    const { privateKey, config } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, goodClaims);
    const result = await verifyAccessJwt(token, config);
    expect(result).toEqual({ ok: true, subject: "service-token-client-id" });
  });

  it("refuses a token for another Access application", async () => {
    const { privateKey, config } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, {
      ...goodClaims,
      aud: ["another-app"],
    });
    expect(await verifyAccessJwt(token, config)).toEqual({
      ok: false,
      reason: "audience_mismatch",
    });
  });

  it("refuses a token from another team", async () => {
    const { privateKey, config } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, {
      ...goodClaims,
      iss: "https://evil.cloudflareaccess.com",
    });
    expect(await verifyAccessJwt(token, config)).toEqual({
      ok: false,
      reason: "issuer_mismatch",
    });
  });

  it("refuses an expired token", async () => {
    const { privateKey, config } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, {
      ...goodClaims,
      exp: NOW - 120,
    });
    expect(await verifyAccessJwt(token, config)).toEqual({
      ok: false,
      reason: "expired",
    });
  });

  it("refuses a token signed by a key the team does not publish", async () => {
    const { config } = await fixture();
    const stranger = await keypair("k1");
    const token = await sign(stranger.privateKey, { alg: "RS256", kid: "k1" }, goodClaims);
    expect(await verifyAccessJwt(token, config)).toEqual({
      ok: false,
      reason: "bad_signature",
    });
  });

  it("refuses alg none and any algorithm other than RS256", async () => {
    const { config } = await fixture();
    const unsigned =
      `${b64url(JSON.stringify({ alg: "none", kid: "k1" }))}.` +
      `${b64url(JSON.stringify(goodClaims))}.`;
    expect(await verifyAccessJwt(unsigned, config)).toEqual({
      ok: false,
      reason: "unsupported_alg",
    });
  });

  it("refuses an unknown key id after one refresh of the key set", async () => {
    const { privateKey, config, fetches } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "rotated" }, goodClaims);
    expect(await verifyAccessJwt(token, config)).toEqual({
      ok: false,
      reason: "unknown_key",
    });
    expect(fetches()).toBeLessThanOrEqual(2);
  });

  it("refuses a malformed token and a key set that cannot be fetched", async () => {
    const { config } = await fixture();
    expect(await verifyAccessJwt("not.a.jwt.at.all", config)).toEqual({
      ok: false,
      reason: "malformed",
    });
    const { privateKey } = await keypair("k1");
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, goodClaims);
    const unreachable: AccessConfig = {
      ...config,
      fetchJwks: async () => {
        throw new Error("network down");
      },
    };
    expect(await verifyAccessJwt(token, unreachable)).toEqual({
      ok: false,
      reason: "jwks_unavailable",
    });
  });
});

describe("admitMcp", () => {
  const req = (headers: Record<string, string> = {}) =>
    new Request("https://gw.example/mcp", { method: "POST", headers });

  it("refuses when Access is not configured, instead of trusting the edge", async () => {
    const result = await admitMcp(req(), {});
    expect(result).toMatchObject({ ok: false, status: 503, reason: "access_not_configured" });
  });

  it("refuses a request with no Access assertion", async () => {
    const result = await admitMcp(req(), {
      ACCESS_TEAM_DOMAIN: TEAM,
      ACCESS_AUD: AUD,
    });
    expect(result).toMatchObject({ ok: false, status: 401, reason: "access_assertion_missing" });
  });

  it("admits a verified assertion", async () => {
    const { privateKey, config } = await fixture();
    const token = await sign(privateKey, { alg: "RS256", kid: "k1" }, goodClaims);
    const result = await admitMcp(
      req({ "Cf-Access-Jwt-Assertion": token }),
      { ACCESS_TEAM_DOMAIN: `https://${TEAM}/`, ACCESS_AUD: AUD },
      { fetchJwks: config.fetchJwks, now: config.now, cache: new Map() },
    );
    expect(result).toEqual({ ok: true, subject: "service-token-client-id" });
  });

  it("answers 403 for an assertion that fails verification", async () => {
    const { config } = await fixture();
    const stranger = await keypair("k1");
    const token = await sign(stranger.privateKey, { alg: "RS256", kid: "k1" }, goodClaims);
    const result = await admitMcp(
      req({ "Cf-Access-Jwt-Assertion": token }),
      { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD },
      { fetchJwks: config.fetchJwks, now: config.now, cache: new Map() },
    );
    expect(result).toMatchObject({ ok: false, status: 403, reason: "bad_signature" });
  });

  it("skips the check only in the direct development transport", async () => {
    const result = await admitMcp(req(), { REMORA_API_URL: "http://127.0.0.1:8000" });
    expect(result).toEqual({ ok: true, subject: "development" });
  });
});

describe("productionReadiness", () => {
  const complete = {
    REMORA_DEPLOYMENT_PROFILE: "production",
    REMORA_PG_DSN: "postgresql://db/remora",
    EXECUTION: {},
    REMORA_LEASE_ED25519_PRIVATE: "priv",
    REMORA_LEASE_ED25519_PUBLIC: "pub",
    ACCESS_TEAM_DOMAIN: TEAM,
    ACCESS_AUD: AUD,
  };

  it("passes a production profile that has every prerequisite", () => {
    expect(productionReadiness(complete)).toEqual({ profile: "production", problems: [] });
  });

  it("names a D1 binding as not durable for the tenant audit chain", () => {
    const { REMORA_PG_DSN: _dsn, ...rest } = complete;
    const readiness = productionReadiness({ ...rest, STATE_DB: {} });
    expect(readiness.problems).toEqual(["durable_audit_chain_missing"]);
  });

  it("refuses production without the custody split", () => {
    const { REMORA_LEASE_ED25519_PRIVATE: _p, EXECUTION: _e, ...rest } = complete;
    expect(productionReadiness(rest).problems).toEqual(["custody_split_missing"]);
  });

  it("refuses production without in-Worker Access verification", () => {
    const { ACCESS_AUD: _a, ...rest } = complete;
    expect(productionReadiness(rest).problems).toEqual(["access_not_configured"]);
  });

  it("does not enforce outside production, and rejects an unknown profile", () => {
    expect(productionReadiness({ REMORA_DEPLOYMENT_PROFILE: "staging" })).toEqual({
      profile: "staging",
      problems: [],
    });
    expect(productionReadiness({}).problems).toEqual(["deployment_profile_missing"]);
    expect(productionReadiness({ REMORA_DEPLOYMENT_PROFILE: "prod-ish" }).problems).toEqual([
      "deployment_profile_unknown",
    ]);
  });
});

describe("deployment configuration", () => {
  const profileOf = (file: string) => {
    const text = readFileSync(join(process.cwd(), file), "utf8");
    const match = /^REMORA_DEPLOYMENT_PROFILE\s*=\s*"([^"]*)"/m.exec(text);
    return match ? match[1] : null;
  };

  it("every wrangler config declares a known deployment profile", () => {
    expect(profileOf("wrangler.toml")).toBe("staging");
    expect(profileOf("wrangler.dev.toml")).toBe("development");
  });

  it("the /mcp route checks readiness and admission before parsing a call", () => {
    const source = readFileSync(join(process.cwd(), "src", "index.ts"), "utf8");
    const route = source.indexOf('url.pathname !== "/mcp"');
    const admit = source.indexOf("await admitMcp(request, env)", route);
    const ready = source.indexOf("productionReadiness(env)", route);
    const parse = source.indexOf("body = await request.json()", route);
    expect(route).toBeGreaterThan(-1);
    expect(ready).toBeGreaterThan(route);
    expect(admit).toBeGreaterThan(ready);
    expect(parse).toBeGreaterThan(admit);
  });
});
