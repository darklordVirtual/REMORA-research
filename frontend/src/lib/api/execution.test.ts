/**
 * Phase 12: explicit data-source states, never silent substitution.
 *
 * The read-model client must return DEMO with null data when no API is
 * configured, OFFLINE on transport failure, ERROR on non-2xx/unparseable,
 * DEGRADED when the API itself reports non-durable state, and LIVE
 * otherwise — and it must never import simulated data.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  apiConfig,
  getGovernanceMetrics,
  getProposalLifecycle,
  getReviewPacket,
} from "./execution";

const CONFIG = { baseUrl: "https://api.example", token: "tok" };

afterEach(() => vi.unstubAllGlobals());

describe("explicit data-source states", () => {
  it("no config -> DEMO with null data (never a silent default host)", async () => {
    expect(apiConfig({})).toBeNull();
    const result = await getGovernanceMetrics(null);
    expect(result.state).toBe("DEMO");
    expect(result.data).toBeNull();
  });

  it("config requires BOTH url and token", () => {
    expect(apiConfig({ VITE_REMORA_API_URL: "https://x" })).toBeNull();
    expect(apiConfig({ VITE_REMORA_API_TOKEN: "t" })).toBeNull();
    expect(apiConfig({ VITE_REMORA_API_URL: "https://x/", VITE_REMORA_API_TOKEN: "t" })).toEqual({
      baseUrl: "https://x",
      token: "t",
    });
  });

  it("transport failure -> OFFLINE with null data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));
    const result = await getGovernanceMetrics(CONFIG);
    expect(result.state).toBe("OFFLINE");
    expect(result.data).toBeNull();
    expect(result.detail).toContain("ECONNREFUSED");
  });

  it("non-2xx -> ERROR with null data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 503 })));
    const result = await getGovernanceMetrics(CONFIG);
    expect(result.state).toBe("ERROR");
    expect(result.data).toBeNull();
    expect(result.detail).toBe("HTTP 503");
  });

  it("non-durable execution state -> DEGRADED, data still delivered", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ execution_assess_total: 3, execution_state_durable: false }),
        ),
    );
    const result = await getGovernanceMetrics(CONFIG);
    expect(result.state).toBe("DEGRADED");
    expect(result.data?.execution_assess_total).toBe(3);
  });

  it("healthy response -> LIVE", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ execution_assess_total: 3, execution_state_durable: true }),
        ),
    );
    const result = await getGovernanceMetrics(CONFIG);
    expect(result.state).toBe("LIVE");
  });

  it("lifecycle reads carry the bearer and encode the id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ proposal_id: "p 1", events: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await getProposalLifecycle(CONFIG, "p 1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example/v1/execution/proposals/p%201/lifecycle");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("review-packet reads carry the bearer and encode the id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        proposal_id: "p 2",
        review_item_id: "r1",
        decision: "verify",
        reasons: ["limit_dual_control_required"],
        pending_human_decision: true,
        current_state: "REVIEW_PENDING",
        arguments_available: false,
        arguments_note: "joined by tool_call_hash",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await getReviewPacket(CONFIG, "p 2");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.example/v1/execution/proposals/p%202/review-packet");
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(result.state).toBe("LIVE");
    expect(result.data?.arguments_available).toBe(false);
    expect(result.data?.pending_human_decision).toBe(true);
  });

  it("the client never imports simulated data", () => {
    const src = readFileSync(join(__dirname, "execution.ts"), "utf-8");
    const importSpecifiers = [...src.matchAll(/from\s+"([^"]+)"/g)].map((m) => m[1]);
    for (const spec of importSpecifiers) {
      expect(spec).not.toMatch(/remora-sim|remora\.functions|lib\/remora/);
    }
  });
});
