import { describe, expect, it } from "vitest";
import { statusColor, statusLabel } from "../theme/tokens";
import { elapsed, kindName } from "./labels";

describe("labels", () => {
  it("shows plain-language names, and the raw kind when unknown", () => {
    expect(kindName("bold")).toBe("Functional (BOLD)");
    expect(kindName("something-new")).toBe("something-new");
  });
  it("formats elapsed time from UTC timestamps without a zone", () => {
    expect(elapsed("2026-10-04T10:00:00", "2026-10-04T10:00:42")).toBe("42 s");
    expect(elapsed("2026-10-04T10:00:00", "2026-10-04T11:05:03")).toBe("1 h 5 min");
    expect(elapsed(null, null)).toBe("");
  });
  it("every engine state has a colour and a plain-language label", () => {
    for (const state of ["Queued", "Running", "Completed", "Failed", "Cancelled", "Interrupted"]) {
      expect(statusColor[state]).toBeTruthy();
      expect(statusLabel[state]).toBeTruthy();
    }
  });
});
