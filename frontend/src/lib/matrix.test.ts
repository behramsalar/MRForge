import { describe, expect, it } from "vitest";
import { boundaries, cellColor, histogram, meanOffDiagonal } from "./matrix";

describe("matrix helpers", () => {
  it("colours zero white, the limits fully saturated, and clips beyond them", () => {
    expect(cellColor(0, "r")).toEqual([247, 247, 247]);
    expect(cellColor(1, "r")).toEqual([178, 24, 43]);
    expect(cellColor(-1, "r")).toEqual([33, 102, 172]);
    expect(cellColor(5, "r")).toEqual(cellColor(1, "r"));
    expect(cellColor(2, "z")).toEqual(cellColor(1, "r")); // z has its own, wider range
  });
  it("draws the diagonal and missing values neutral, never as a correlation", () => {
    expect(cellColor(1, "r", true)).toEqual([200, 200, 200]);
    expect(cellColor(null, "r")).toEqual([225, 225, 225]);
    expect(cellColor(NaN, "z")).toEqual([225, 225, 225]);
  });
  it("finds group boundaries, and none when there would be too many", () => {
    expect(boundaries(["L_a", "L_a", "L_b", "R_b", "R_b"])).toEqual([2, 3]);
    expect(boundaries(Array.from({ length: 100 }, (_, i) => String(i % 2)))).toEqual([]);
  });
  it("counts each pair once and skips missing values", () => {
    const m = [
      [1, 0.5, null],
      [0.5, 1, -0.5],
      [null, -0.5, 1],
    ];
    const h = histogram(m, "r", 4);
    expect(h.counts.reduce((a, b) => a + b, 0)).toBe(2);
    expect(meanOffDiagonal(m)).toBeCloseTo(0);
    expect(meanOffDiagonal([[null]])).toBeNull();
  });
});
