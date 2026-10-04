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

import { describeShape, humanSize, seconds } from "./labels";

describe("data formatting", () => {
  it("removes float noise from times", () => {
    expect(seconds(0.6500000965625)).toBe("0.65 s");
    expect(seconds(2)).toBe("2 s");
    expect(seconds(null)).toBe("-");
  });
  it("describes images and sizes in plain words", () => {
    expect(describeShape([74, 74, 62, 360])).toBe("74 x 74 x 62, 360 volumes");
    expect(describeShape([256, 256, 192])).toBe("256 x 256 x 192");
    expect(describeShape(null)).toBe("-");
    expect(humanSize(127_000_000)).toBe("127 MB");
    expect(humanSize(1_500_000_000)).toBe("1.5 GB");
    expect(humanSize(100)).toBe("1 kB");
  });
});
