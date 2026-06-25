import { describe, it, expect } from "vitest";
import {
  EXPECTED_BADGE,
  EXPECTED_STRIPE,
  RISK_STRIPE,
  RISK_BADGE,
  VERDICT_TICKER,
  FAMILY_DOT,
  STATUS_LABEL,
  RISK_LEVEL_CLS,
  statusPillClass,
  canOpenEscalation,
  verdictBorderBg,
  verdictText,
  phaseText,
} from "./styles";

describe("styles - verdict helpers", () => {
  it("verdictBorderBg returns correct classes", () => {
    expect(verdictBorderBg("ACCEPT")).toContain("border-state-accept");
    expect(verdictBorderBg("ESCALATE")).toContain("border-state-escalate");
    expect(verdictBorderBg("VERIFY")).toContain("border-state-verify");
    expect(verdictBorderBg("ABSTAIN")).toContain("border-border");
  });

  it("verdictText returns correct text colors", () => {
    expect(verdictText("ACCEPT")).toBe("text-state-accept");
    expect(verdictText("ESCALATE")).toBe("text-state-escalate");
    expect(verdictText("VERIFY")).toBe("text-state-verify");
    expect(verdictText("ABSTAIN")).toBe("text-muted-foreground");
  });

  it("phaseText returns correct phase colors", () => {
    expect(phaseText("ordered")).toBe("text-state-accept");
    expect(phaseText("critical")).toBe("text-state-verify");
    expect(phaseText("disordered")).toBe("text-state-escalate");
  });
});

describe("styles - status helpers", () => {
  it("canOpenEscalation returns true for actionable statuses", () => {
    expect(canOpenEscalation("pending")).toBe(true);
    expect(canOpenEscalation("evidence_received")).toBe(true);
    expect(canOpenEscalation("ready_for_review")).toBe(true);
    expect(canOpenEscalation("follow_up_required")).toBe(true);
    expect(canOpenEscalation("site_verification_pending")).toBe(true);
  });

  it("canOpenEscalation returns false for terminal statuses", () => {
    expect(canOpenEscalation("approved")).toBe(false);
    expect(canOpenEscalation("rejected")).toBe(false);
    expect(canOpenEscalation("closed")).toBe(false);
  });

  it("statusPillClass returns distinct classes for each status", () => {
    const classes = new Set([
      statusPillClass("approved"),
      statusPillClass("rejected"),
      statusPillClass("pending"),
      statusPillClass("follow_up_required"),
      statusPillClass("site_verification_pending"),
      statusPillClass("evidence_received"),
      statusPillClass("ready_for_review"),
      statusPillClass("closed"),
    ]);
    expect(classes.size).toBeGreaterThanOrEqual(5);
  });
});

describe("styles - badge mappings", () => {
  it("EXPECTED_BADGE covers all verdicts", () => {
    expect(EXPECTED_BADGE["ACCEPT"]).toBeTruthy();
    expect(EXPECTED_BADGE["VERIFY"]).toBeTruthy();
    expect(EXPECTED_BADGE["ABSTAIN"]).toBeTruthy();
    expect(EXPECTED_BADGE["ESCALATE"]).toBeTruthy();
  });

  it("RISK_STRIPE covers all risk levels", () => {
    expect(RISK_STRIPE["low"]).toBeTruthy();
    expect(RISK_STRIPE["medium"]).toBeTruthy();
    expect(RISK_STRIPE["high"]).toBeTruthy();
    expect(RISK_STRIPE["critical"]).toBeTruthy();
  });

  it("FAMILY_DOT covers known oracle families", () => {
    expect(FAMILY_DOT["groq"]).toBeTruthy();
    expect(FAMILY_DOT["anthropic"]).toBeTruthy();
    expect(FAMILY_DOT["openai"]).toBeTruthy();
    expect(FAMILY_DOT["mistral"]).toBeTruthy();
    expect(FAMILY_DOT["local"]).toBeTruthy();
  });

  it("STATUS_LABEL has human-readable labels", () => {
    expect(STATUS_LABEL["approved"]).toBe("APPROVED");
    expect(STATUS_LABEL["rejected"]).toBe("REJECTED");
    expect(STATUS_LABEL["pending"]).toBe("PENDING REVIEW");
  });
});
