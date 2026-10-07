/**
 * RMR-CR-013: the Worker refuses a number it would change before REMORA binds
 * the call. Before this, a JSON-RPC body was parsed with request.json(), so
 * 9007199254740993 reached REMORA as 9007199254740992 and 1.0 as 1, and the
 * changed value is what REMORA bound and executed.
 */
import { describe, expect, it } from "vitest";
import {
  assertSafeNumbers,
  parseJsonStrict,
  unsafeNumberReason,
  UnsafeNumberError,
} from "../src/json_numbers";

describe("unsafe numbers are refused, not converted", () => {
  it.each([
    ["9007199254740993", "unsafe_integer"],
    ["-9007199254740993", "unsafe_integer"],
    ["123456789012345678901234567890", "unsafe_integer"],
    ["1.0", "float_becomes_integer"],
    ["-0.0", "float_becomes_integer"],
    ["1e2", "float_becomes_integer"],
    ["2.50e1", "float_becomes_integer"],
    ["123456789012345678.0", "float_becomes_integer"],
    ["1e400", "non_finite"],
  ])("%s -> %s", (literal, reason) => {
    expect(unsafeNumberReason(literal)).toBe(reason);
  });

  it.each([
    "0", "-1", "42", "9007199254740991", "-9007199254740991",
    "1.5", "0.1", "2.50", "-3.25e-2", "1e21", "1.7976931348623157e308",
  ])("%s passes unchanged", (literal) => {
    expect(unsafeNumberReason(literal)).toBeNull();
  });
});

describe("the scanner reads the raw text, outside strings", () => {
  it("finds a nested unsafe number and names its offset", () => {
    const text = '{"params":{"arguments":{"id":9007199254740993}}}';
    try {
      parseJsonStrict(text);
      throw new Error("expected a refusal");
    } catch (e) {
      expect(e).toBeInstanceOf(UnsafeNumberError);
      expect((e as UnsafeNumberError).reason).toBe("unsafe_integer");
      expect((e as UnsafeNumberError).offset).toBe(text.indexOf("9007"));
    }
  });

  it("ignores digits inside strings, including after escaped quotes", () => {
    expect(() => assertSafeNumbers('{"a":"9007199254740993","b":"x\\"1.0","c":1}'))
      .not.toThrow();
  });

  it("refuses inside arrays and after other values", () => {
    expect(() => parseJsonStrict('[1, 2, {"x": [3, 1.0]}]')).toThrow(UnsafeNumberError);
  });

  it("parses a safe body to the same value JSON.parse gives", () => {
    const text = '{"jsonrpc":"2.0","id":7,"params":{"arguments":{"price":2.5,"n":-3}}}';
    expect(parseJsonStrict(text)).toEqual(JSON.parse(text));
  });

  it("reports syntax errors as JSON.parse does", () => {
    expect(() => parseJsonStrict('{"a":')).toThrow(SyntaxError);
  });
});
