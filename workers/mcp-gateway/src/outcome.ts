// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// What the gateway tells the model actually happened.
//
// Both execution sites in mcp.ts reported `status: "executed"` on any HTTP 200:
//
//     status: run.status === 200 ? "executed" : "execution_failed"
//
// A 200 means the execution API answered, not that the tool ran. The body it
// answers with carries the real outcome, and after RMR-003 that outcome is
// explicit: `tool_execution.executed`, `dispatch_began` and `state_unknown`.
// A refused dispatch and a dispatch whose result was lost both arrived at the
// model as "executed" (RMR-006).
//
// This is the same rule as remora/execution/outcome.py, kept deliberately
// small and in its own module so it can be unit tested rather than exercised
// only through a deploy — the lesson from the read-only SQL predicate.
//
// The vocabulary is the model's, not the lifecycle model's. What the model has
// to decide is whether it may tell the user the thing was done, and "unknown"
// has to be a word it cannot read as success.

export type DispatchStatus =
  | "executed"
  | "refused"
  | "unknown"
  | "execution_failed";

export interface ToolExecution {
  executed?: unknown;
  dispatch_began?: unknown;
  state_unknown?: unknown;
  refusal_reason?: unknown;
}

/**
 * Classify a dispatch from the transport status and the body.
 *
 * `execution_failed` is reserved for the case where the execution API itself
 * did not answer with 200. It says nothing about the side effect, which is why
 * a 200 whose body reports a lost result is `unknown` and not this.
 *
 * A 200 with no tool_execution at all is `unknown`, not `executed`. Absence of
 * evidence is the exact thing this module exists to stop reading as success.
 */
export function dispatchStatus(
  httpStatus: number,
  execution: ToolExecution | null | undefined,
): DispatchStatus {
  if (httpStatus !== 200) return "execution_failed";
  if (!execution || typeof execution !== "object") return "unknown";

  if (execution.executed === true) return "executed";
  if (execution.state_unknown === true) return "unknown";
  if (execution.dispatch_began === true) return "unknown";

  // Refused requires the dispatcher to have SAID it did not dispatch, not
  // merely to have left the field out. This is stricter than the Python
  // classifier, which reads a dict its own dispatcher built and can rely on
  // the keys being present. Here the object is wire data: an empty body would
  // otherwise become the strongest negative claim the gateway can make, out of
  // no evidence whatsoever.
  if (execution.dispatch_began === false) return "refused";
  return "unknown";
}

/**
 * What the model must be told alongside the status.
 *
 * Empty for `executed`: adding prose to the success path is how a caveat
 * becomes noise. The other three each carry the thing a model would otherwise
 * get wrong, and `unknown` carries the strongest wording because retrying a
 * call that may already have taken effect is the one move that must not
 * happen.
 */
export function statusExplanation(status: DispatchStatus): string {
  switch (status) {
    case "executed":
      return "";
    case "refused":
      return "Nothing was executed. REMORA declined the call before it " +
        "could take effect, so the side effect did not happen.";
    case "unknown":
      return "The call was dispatched and the outcome is NOT known. It may " +
        "have taken effect. Do not retry it, and do not tell the user it " +
        "succeeded or that it failed. Report that the result is unknown and " +
        "that the system of record needs to be checked.";
    case "execution_failed":
      return "The execution API did not answer successfully. This says " +
        "nothing about whether the side effect happened.";
  }
}
