// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// The gateway must tell the model what happened, not that the API answered.
//
// RMR-006. Both execution sites in mcp.ts read
//
//     status: run.status === 200 ? "executed" : "execution_failed"
//
// A 200 means the execution API answered. The body says what happened, and
// after RMR-003 it says so explicitly. A refused dispatch and a dispatch whose
// result was lost both reached the model as "executed", which is the single
// worst thing this gateway can say: the model then tells a person the work is
// done.

import { describe, expect, it } from "vitest";
import { dispatchStatus, statusExplanation } from "../src/outcome";

const EXECUTED = { executed: true, dispatch_began: true, state_unknown: false };
const REFUSED = { executed: false, dispatch_began: false, state_unknown: false,
                  refusal_reason: "pep_denied" };
const UNKNOWN = { executed: false, dispatch_began: true, state_unknown: true,
                  refusal_reason: "tool_failed_nonce_burned" };

describe("the status comes from the body, not the transport", () => {
  it("reports executed only when the body says so", () => {
    expect(dispatchStatus(200, EXECUTED)).toBe("executed");
  });

  it("reports a refusal as refused, not as executed", () => {
    // The headline case. HTTP 200, nothing happened.
    expect(dispatchStatus(200, REFUSED)).toBe("refused");
  });

  it("reports a lost or unproven result as unknown", () => {
    expect(dispatchStatus(200, UNKNOWN)).toBe("unknown");
  });

  it("treats a dispatch that began without a verdict as unknown", () => {
    expect(dispatchStatus(200, { executed: false, dispatch_began: true }))
      .toBe("unknown");
  });

  it("treats a 200 with no tool_execution as unknown, never executed", () => {
    // Absence of evidence is the exact thing this module exists to stop
    // reading as success. The old test fixtures were shaped like this and
    // asserted "executed" from them.
    for (const body of [undefined, null, {}]) {
      expect(dispatchStatus(200, body as never)).toBe("unknown");
    }
  });

  it("does not accept a truthy non-true executed value", () => {
    // "false", 0, "yes" -- a JSON body is not a trusted type.
    for (const value of ["true", 1, "yes", {}]) {
      expect(dispatchStatus(200, { executed: value })).not.toBe("executed");
    }
  });

  it("keeps a transport failure distinct from a refusal", () => {
    // execution_failed says the API did not answer. It says NOTHING about the
    // side effect, so it must not collapse into refused.
    for (const code of [401, 409, 500, 503]) {
      expect(dispatchStatus(code, EXECUTED)).toBe("execution_failed");
      expect(dispatchStatus(code, REFUSED)).toBe("execution_failed");
    }
  });
});

describe("what the model is told", () => {
  it("says nothing extra on success", () => {
    // Prose on the success path is how a caveat becomes noise.
    expect(statusExplanation("executed")).toBe("");
  });

  it("tells the model an unknown outcome may have taken effect", () => {
    const text = statusExplanation("unknown");
    expect(text).toMatch(/not known/i);
    expect(text).toMatch(/do not retry/i);
    // It must not be readable as either verdict.
    expect(text).toMatch(/succeeded or that it failed/i);
  });

  it("tells the model a refusal means nothing happened", () => {
    expect(statusExplanation("refused")).toMatch(/did not happen/i);
  });

  it("does not claim a transport failure means no effect", () => {
    expect(statusExplanation("execution_failed"))
      .toMatch(/says nothing about whether the side effect happened/i);
  });

  it("has an explanation for every status but the successful one", () => {
    // A new status with no explanation would reach the model bare.
    for (const status of ["refused", "unknown", "execution_failed"] as const) {
      expect(statusExplanation(status).length).toBeGreaterThan(40);
    }
  });
});
