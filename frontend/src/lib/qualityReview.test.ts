import { describe, expect, it } from "vitest";
import type { ReportQc, ReportRun } from "../api/types";
import { afterDecision, findQc, thumbnailOf } from "./qualityReview";

const qc = (name: string, image?: string, slices: string[] = []): ReportQc => ({
  name,
  kind: "image",
  image,
  slices: slices.map((s) => ({ plane: "axial", position: 0, layer: "t1", image: s })),
});
const run = (items: ReportQc[]) => ({ step: "func_qc", title: "Functional checks", qc: items }) as unknown as ReportRun;

describe("findQc", () => {
  const report = { sections: [{ runs: [run([qc("Head motion (x)"), qc("Registration to the T1 image")])] }, { runs: [run([qc("Alignment to standard space")])] }] };
  it("finds the results of one check across sections", () => {
    expect(findQc(report, "motion")).toHaveLength(1);
    expect(findQc(report, "t1")[0].qc.name).toBe("Registration to the T1 image");
    expect(findQc(report, "standard")).toHaveLength(1);
    expect(findQc(report, "fieldmap")).toEqual([]);
  });
  it("copes with a report that is not loaded", () => {
    expect(findQc(undefined, "motion")).toEqual([]);
  });
});

describe("thumbnailOf", () => {
  it("prefers the joined picture, else the first slice", () => {
    expect(thumbnailOf(qc("a", "joined.png", ["s1.png"]))).toBe("joined.png");
    expect(thumbnailOf(qc("a", undefined, ["s1.png", "s2.png"]))).toBe("s1.png");
    expect(thumbnailOf(qc("a"))).toBeNull();
  });
});

describe("afterDecision", () => {
  it("moves to the next subject, or back from the last, or to none", () => {
    expect(afterDecision(["a", "b", "c"], "a")).toBe("b");
    expect(afterDecision(["a", "b", "c"], "c")).toBe("b");
    expect(afterDecision(["a"], "a")).toBeNull();
    expect(afterDecision(["a", "b"], "gone")).toBe("a");
  });
});
