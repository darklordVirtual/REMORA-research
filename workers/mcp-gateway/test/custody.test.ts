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

import { isReadOnlySql } from "../src/sql";

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
  // To the end of the constructor body. Matched with a regex rather than a
  // literal because this file is stored CRLF: the literal "\n  }\n}" never
  // matched, so every block silently ran to end-of-file and the execution
  // assertions passed only because the authority class is declared ABOVE it.
  // A test that passes for the wrong reason is worse than one that fails.
  const rest = SOURCE.slice(ctor);
  const closer = /\r?\n {2}\}\r?\n\}/.exec(rest);
  const block = closer ? rest.slice(0, closer.index) : rest;
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

describe("the authority domain cannot cause effects", () => {
  const authEnv = envBlock("RemoraContainer");

  it("holds no downstream credential", () => {
    // Three documents claimed this before the configuration did. On the
    // deployment no REMORA_GITHUB_TOKEN secret was set, so the claim held by
    // accident. A component that can both mint authority and use it is the
    // single point of failure the split exists to remove.
    expect(authEnv).not.toContain("REMORA_GITHUB_TOKEN");
  });

  it("declares the same tool registry as the executor", () => {
    // Not a grant of callables: the bundle hash covers the module's spec and
    // source digest, resolved WITHOUT importing it. Both domains must declare
    // the same registry or their bundle hashes differ and every lease is
    // refused as policy_bundle_mismatch. Removing it here to "hold no tools"
    // did exactly that on the deployment.
    expect(authEnv).toContain("REMORA_TOOL_REGISTRY_MODULE");
    expect(envBlock("RemoraExecutionContainer"))
      .toContain("REMORA_TOOL_REGISTRY_MODULE");
  });

  it("still holds what it needs to DECIDE", () => {
    // Declarations, not credentials: they carry no ability to act.
    expect(authEnv).toContain("REMORA_TOOL_METADATA_FILE");
    expect(authEnv).toContain("REMORA_SEMANTIC_BUNDLE_MODULE");
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

describe("the authority may read the graph but not write it", () => {
  // Behavioural, not source-scraping. The first version of these tests read the
  // regex out of the file and asserted its shape; that cannot catch a semantic
  // bypass, and one shipped: `WITH x AS (...) INSERT` was accepted because the
  // allowlist admitted a leading WITH. Testing the predicate with real SQL is
  // what would have caught it.

  it("admits the reads this deployment actually issues", () => {
    for (const sql of [
      "SELECT graph AS graph_uri, COUNT(*) AS facts FROM knowledge_facts WHERE tenant_id = ?",
      "select id, subject from knowledge_facts where tenant_id = ? limit 50",
      "SELECT DISTINCT subject AS v FROM knowledge_facts WHERE tenant_id = ?;",
      "PRAGMA table_info(knowledge_facts)",
    ]) {
      expect(isReadOnlySql(sql), sql).toBe(true);
    }
  });

  it("refuses a CTE-prefixed mutation", () => {
    // The reported bypass. SQLite lets WITH prefix INSERT/UPDATE/DELETE.
    for (const sql of [
      "WITH x AS (SELECT 1) INSERT INTO knowledge_facts SELECT * FROM x",
      "with cte as (select 1) delete from knowledge_facts",
      "WITH a AS (SELECT 1) UPDATE knowledge_facts SET object_json = 'x'",
    ]) {
      expect(isReadOnlySql(sql), sql).toBe(false);
    }
  });

  it("refuses a bare CTE even when it ends in a SELECT", () => {
    // Refused outright rather than parsed: no query here uses a CTE, so the
    // capability bought nothing and cost a bypass.
    expect(isReadOnlySql("WITH x AS (SELECT 1) SELECT * FROM x")).toBe(false);
  });

  it("refuses direct mutation", () => {
    for (const sql of [
      "INSERT INTO knowledge_facts (tenant_id) VALUES (?)",
      "UPDATE knowledge_facts SET source = 'agent'",
      "DELETE FROM knowledge_facts",
      "DROP TABLE knowledge_facts",
      "ALTER TABLE knowledge_facts ADD COLUMN x TEXT",
      "REPLACE INTO knowledge_facts VALUES (?)",
      "ATTACH DATABASE 'x' AS y",
      "CREATE TABLE t (a TEXT)",
    ]) {
      expect(isReadOnlySql(sql), sql).toBe(false);
    }
  });

  it("refuses statement chaining", () => {
    expect(isReadOnlySql(
      "SELECT 1; DELETE FROM knowledge_facts")).toBe(false);
    expect(isReadOnlySql(
      "SELECT 1;\nINSERT INTO knowledge_facts VALUES (1)")).toBe(false);
  });

  it("refuses a mutation hidden behind a comment or parenthesis", () => {
    for (const sql of [
      "/* select */ INSERT INTO knowledge_facts VALUES (1)",
      "-- select\nDELETE FROM knowledge_facts",
      "(INSERT INTO knowledge_facts VALUES (1))",
    ]) {
      expect(isReadOnlySql(sql), sql).toBe(false);
    }
  });

  it("refuses a write pragma", () => {
    expect(isReadOnlySql("PRAGMA writable_schema = ON")).toBe(false);
    expect(isReadOnlySql("PRAGMA journal_mode = DELETE")).toBe(false);
  });

  it("routes the authority's graph access through the read-only wrapper", () => {
    const auth = SOURCE.slice(SOURCE.indexOf("RemoraContainer.outboundByHost"),
                              SOURCE.indexOf("RemoraExecutionContainer.outboundByHost"));
    expect(auth).toContain("d1ReadOnly(env.GRAPH_DB");
    expect(auth).not.toContain("d1Request(env.GRAPH_DB");
  });

  it("leaves the executor's graph access unrestricted", () => {
    // Causing effects is the executor's job; restricting it here would move
    // the problem rather than solve it.
    const exec = SOURCE.slice(
      SOURCE.indexOf("RemoraExecutionContainer.outboundByHost"));
    expect(exec).toContain("d1Request(env.GRAPH_DB");
  });
});
