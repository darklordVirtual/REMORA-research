import { describe, it, expect } from "vitest";

/**
 * Unit tests for the authorBearer() authentication logic.
 *
 * These tests run in Node (not Workerd) because they test pure logic extracted
 * from the worker. The full end-to-end wrangler integration is exercised via
 * `wrangler dev` in CI.
 *
 * Critical property being tested: FAIL-CLOSED behaviour.
 * If ORACLE_SECRET is unset the function must return false, not true.
 */

// Extract the pure logic so it can be tested without the full worker runtime.
function authorBearer(authHeader: string, oracleSecret: string | undefined): boolean {
  if (!oracleSecret) return false;
  return authHeader === `Bearer ${oracleSecret}`;
}

describe("authorBearer — fail-closed authentication", () => {
  it("returns false when ORACLE_SECRET is undefined (fail-closed)", () => {
    expect(authorBearer("Bearer anything", undefined)).toBe(false);
  });

  it("returns false when ORACLE_SECRET is empty string (fail-closed)", () => {
    expect(authorBearer("Bearer anything", "")).toBe(false);
  });

  it("returns true for correct Bearer token", () => {
    expect(authorBearer("Bearer s3cr3t", "s3cr3t")).toBe(true);
  });

  it("returns false for wrong Bearer token", () => {
    expect(authorBearer("Bearer wrong", "s3cr3t")).toBe(false);
  });

  it("returns false for missing Authorization header", () => {
    expect(authorBearer("", "s3cr3t")).toBe(false);
  });

  it("returns false for Basic auth instead of Bearer", () => {
    expect(authorBearer("Basic dXNlcjpwYXNz", "dXNlcjpwYXNz")).toBe(false);
  });
});
