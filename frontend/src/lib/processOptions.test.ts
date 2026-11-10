import { describe, expect, it } from "vitest";
import { DEFAULTS, resetStage, settingsChanged, stageCounts } from "./processOptions";

describe("settingsChanged", () => {
  it("is false for the defaults and true after a change", () => {
    expect(settingsChanged("functional", DEFAULTS)).toBe(false);
    const o = { ...DEFAULTS, functional: { ...DEFAULTS.functional, smoothing_fwhm_mm: 6 } };
    expect(settingsChanged("functional", o)).toBe(true);
    expect(settingsChanged("anatomical", o)).toBe(false);
  });
  it("never flags a stage without settings", () => {
    expect(settingsChanged("standard_space", { ...DEFAULTS, stages: { standard_space: false } })).toBe(false);
  });
});

describe("resetStage", () => {
  it("restores only that stage", () => {
    const o = {
      ...DEFAULTS,
      functional: { ...DEFAULTS.functional, smoothing_fwhm_mm: 6 },
      anatomical: { ...DEFAULTS.anatomical, strong_bias: true },
    };
    const r = resetStage("functional", o);
    expect(settingsChanged("functional", r)).toBe(false);
    expect(settingsChanged("anatomical", r)).toBe(true);
  });
});

describe("stageCounts", () => {
  it("counts done and unavailable subjects for a stage", () => {
    const rows = [
      { stages: [{ id: "preprocessing", state: "done" }] },
      { stages: [{ id: "preprocessing", state: "unavailable" }] },
      { stages: [{ id: "preprocessing", state: "none" }] },
    ];
    expect(stageCounts("functional", rows)).toEqual({ done: 1, unavailable: 1, total: 3 });
  });
});
