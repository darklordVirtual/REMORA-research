/**
 * Phase 11 guard: every route backed by the remora-sim engine must render
 * the persistent DemoBanner, so a simulated screen can never present itself
 * as live operations. A new sim-backed route without the banner fails here.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROUTES_DIR = join(__dirname, "..", "routes");

const SIM_MARKERS = [
  'from "@/lib/remora',
  "features/control-room",
  "features/operations",
  "remora-sim",
];

describe("demo banner coverage", () => {
  const routeFiles = readdirSync(ROUTES_DIR).filter((f) => f.endsWith(".tsx"));

  it("every sim-backed route renders <DemoBanner />", () => {
    const missing: string[] = [];
    for (const file of routeFiles) {
      const src = readFileSync(join(ROUTES_DIR, file), "utf-8");
      const simBacked = SIM_MARKERS.some((m) => src.includes(m));
      if (simBacked && !src.includes("<DemoBanner />")) {
        missing.push(file);
      }
    }
    expect(missing).toEqual([]);
  });

  it("the known sim surfaces are covered", () => {
    for (const file of [
      "approvals.tsx",
      "console.tsx",
      "control-room.tsx",
      "lab.tsx",
      "operations.tsx",
      "scenarios.tsx",
      "telemetry.tsx",
    ]) {
      const src = readFileSync(join(ROUTES_DIR, file), "utf-8");
      expect(src, file).toContain("<DemoBanner />");
    }
  });
});
