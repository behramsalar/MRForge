import { describe, expect, it } from "vitest";
import { counts, nextUnlabelled, noiseList, toLabels } from "./icaLabels";

describe("component labels", () => {
  it("reads saved labels and ignores anything else", () => {
    expect(toLabels({ "1": "noise", "2": "signal", "3": "maybe" })).toEqual({ 1: "noise", 2: "signal" });
  });
  it("counts every choice and what is left", () => {
    expect(counts({ 1: "noise", 2: "signal", 3: "uncertain" }, 5)).toEqual({
      signal: 1,
      noise: 1,
      uncertain: 1,
      unlabelled: 2,
    });
  });
  it("finds the next component without a label, wrapping round", () => {
    expect(nextUnlabelled({ 1: "signal", 2: "noise" }, 4, 2)).toBe(3);
    expect(nextUnlabelled({ 2: "signal", 3: "noise", 4: "noise" }, 4, 3)).toBe(1);
    expect(nextUnlabelled({ 1: "signal", 2: "noise" }, 2, 1)).toBeNull();
  });
  it("lists the noise components in order", () => {
    expect(noiseList({ 4: "noise", 1: "noise", 2: "signal" })).toEqual([1, 4]);
  });
});
