// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// Strict JSON parsing at the Worker edge (RMR-CR-013).
//
// A Worker parses a request body into JavaScript numbers and serialises it
// again before REMORA binds the call. Two kinds of number token change on
// that round trip, so the value REMORA binds would differ from the value the
// caller sent:
//
//   unsafe_integer          an integer literal beyond 2^53 - 1 loses digits
//                           (9007199254740993 becomes 9007199254740992);
//   float_becomes_integer   a float literal whose value JavaScript writes as
//                           an integer (1.0 becomes 1, 1e2 becomes 100), so a
//                           float arrives in Python as an int;
//   non_finite              a literal too large for a double (1e400) becomes
//                           Infinity, which JSON writes as null.
//
// Python binds and executes the same value, so nothing diverges after the
// binding. What this closes is the conversion before it: the caller's value
// silently becoming another one. The edge refuses such a body instead of
// converting it. Every other number (safe integers, floats JavaScript writes
// back as floats) passes unchanged.
//
// The scanner walks the raw text, so it sees the literal as sent, not the
// number JSON.parse already rounded. This file is identical in mcp-gateway
// and agent-control; tests/test_worker_unsafe_numbers.py checks that.

export type UnsafeNumberReason = "unsafe_integer" | "float_becomes_integer" | "non_finite";

export class UnsafeNumberError extends Error {
  constructor(
    readonly reason: UnsafeNumberReason,
    readonly literal: string,
    readonly offset: number,
  ) {
    super(`unsafe_number:${reason}: ${literal.slice(0, 40)} at offset ${offset}`);
    this.name = "UnsafeNumberError";
  }
}

const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const MAX_SAFE = BigInt(Number.MAX_SAFE_INTEGER);

/** Why a number literal would change across a JavaScript round trip, or null. */
export function unsafeNumberReason(literal: string): UnsafeNumberReason | null {
  const isFloatLiteral = /[.eE]/.test(literal);
  if (!isFloatLiteral) {
    const value = BigInt(literal);
    return (value > MAX_SAFE || value < -MAX_SAFE) ? "unsafe_integer" : null;
  }
  const value = Number(literal);
  if (!Number.isFinite(value)) return "non_finite";
  return /[.eE]/.test(JSON.stringify(value)) ? null : "float_becomes_integer";
}

/** Throw UnsafeNumberError for the first number token that would change. */
export function assertSafeNumbers(text: string): void {
  let inString = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (ch === "\\") i++;
      else if (ch === "\"") inString = false;
      continue;
    }
    if (ch === "\"") {
      inString = true;
      continue;
    }
    if (ch === "-" || (ch >= "0" && ch <= "9")) {
      NUMBER.lastIndex = i;
      const match = NUMBER.exec(text);
      if (!match) continue; // not a number; JSON.parse reports the syntax error
      const reason = unsafeNumberReason(match[0]);
      if (reason) throw new UnsafeNumberError(reason, match[0], i);
      i += match[0].length - 1;
    }
  }
}

/** JSON.parse that refuses numbers a JavaScript round trip would change. */
export function parseJsonStrict(text: string): unknown {
  const value: unknown = JSON.parse(text); // syntax errors first, as before
  assertSafeNumbers(text);
  return value;
}
