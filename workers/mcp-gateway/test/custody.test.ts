/**
 * The custody split, asserted against the deployment configuration (ADR-A).
 *
 * The security property of this deployment is an ABSENCE: the execution
 * container never receives lease-minting material. Absences are exactly what
 * code review misses, and what a later "just add the key so it works" commit
 * silently removes. So it is a test.
 *
 * These read the source of index.ts rather than instantiating the containers,
 * because what matters is which names appear in which envVars block, and the
 * containers cannot be constructed outside the Workers runtime. That makes
 * this a configuration test, and it is honest about that: it proves the
 * deployment is CONFIGURED for the split. Whether the running container's
 * environment matches is verified separately, against the deployment.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// join(process.cwd(), ...) rather than a URL relative to import.meta: the
// Workers tsconfig and node's fs types disagree on the URL shape, and vitest
// runs from the package root. A path keeps the typecheck honest without
// widening the Worker's own type surface.
const SOURCE = readFileSync(join(process.cwd(), "src", "index.ts"), "utf8");

/** The envVars literal of one container class. */
function envBlock(className: string): string {
  const start = SOURCE.indexOf(`export class ${className}`);
  expect(start, `${className} not found`).toBeGreaterThan(-1);
  const ctor = SOURCE.indexOf("this.envVars = {", start);
  expect(ctor, `${className} has no envVars`).toBeGreaterThan(-1);
  // To the end of the constructor body.
  const end = SOURCE.indexOf("\n  }\n}", ctor);
  const block = SOURCE.slice(ctor, end === -1 ? SOURCE.length : end);
  // Strip comments. The first version of this test matched the sentence
  // "REMORA_LEASE_SIGNING_KEY ... deliberately NOT listed" and failed on the
  // comment documenting the very property it was asserting. Assertions here
  // are about what the deployment ASSIGNS, never about what the source says.
  return block
    .split("\n")
    .filter((line: string) => !line.trim().startsWith("//"))
    .join("\n");
}

describe("the execution domain holds no minting material", () => {
  const execEnv = envBlock("RemoraExecutionContainer");

  it("receives the Ed25519 PUBLIC key", () => {
    expect(execEnv).toContain("REMORA_LEASE_VERIFY_KEY_ED25519_PUBLIC");
  });

  it("never receives the Ed25519 private key", () => {
    // The property. If this fails, the split is decorative.
    expect(execEnv).not.toContain("ED25519_PRIVATE");
  });

  it("never receives the symmetric lease key", () => {
    // Equally fatal: the HMAC key mints just as well as the Ed25519 one, and
    // it is the key the pre-split deployment used, so it is the likely thing
    // for someone to paste back in.
    expect(execEnv).not.toContain("REMORA_LEASE_SIGNING_KEY");
  });

  it("holds the downstream credentials, because it is the one that executes", () => {
    expect(execEnv).toContain("REMORA_GITHUB_TOKEN");
  });

  it("reaches durable state, so its nonce ledger survives replacement", () => {
    expect(execEnv).toMatch(/REMORA_STATE_ENDPOINT|REMORA_PG_DSN/);
  });
});

describe("the authority domain holds the minting material", () => {
  const authEnv = envBlock("RemoraContainer");

  it("receives the Ed25519 private key when one is configured", () => {
    expect(authEnv).toContain("REMORA_LEASE_SIGNING_KEY_ED25519_PRIVATE");
  });

  it("is told where the execution domain is", () => {
    expect(authEnv).toContain("REMORA_EXECUTION_ENDPOINT");
  });

  it("only points at an execution domain once a keypair exists", () => {
    // Ordering matters for the migration: an endpoint without a keypair would
    // send leases the executor cannot verify, breaking the gateway rather than
    // degrading it. Both are gated on the same condition.
    const gate = "env.REMORA_LEASE_ED25519_PRIVATE";
    const endpointAt = authEnv.indexOf("REMORA_EXECUTION_ENDPOINT");
    const gateBefore = authEnv.lastIndexOf(gate, endpointAt);
    expect(gateBefore).toBeGreaterThan(-1);
  });
});

describe("what the split does not claim", () => {
  it("records that the executor can still reach downstream systems", () => {
    // The ambient-bypass property (E2) is NOT bought by splitting keys, and
    // the source says so where someone changing it will read it. A comment is
    // weak evidence; its absence would be worse, because the next reader would
    // reasonably assume the split covers more than it does.
    const cls = SOURCE.slice(
      SOURCE.indexOf("The EXECUTION domain"),
      SOURCE.indexOf("export class RemoraExecutionContainer"));
    expect(cls).toContain("CANNOT mint");
    expect(cls).toContain("CAN still reach");
  });
});
