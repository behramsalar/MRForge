import { describe, expect, it } from "vitest";
import type { Overview } from "../api/types";
import { processSegments, processState, qualityCounts, yourMove } from "./overviewSummary";

type Row = Overview["subjects"][number];
const chip = (id: string, state: string, label = id) => ({ id, label, state }) as Row["stages"][number];
const row = (label: string, states: Record<string, string>, extra: Partial<Row> = {}): Row =>
  ({
    label,
    n_files: 1,
    anatomical: { state: "none" },
    functional: { state: "none" },
    stages: Object.entries(states).map(([id, s]) => chip(id, s)),
    complete: false,
    needs_review: false,
    ...extra,
  }) as Row;

describe("overview summary", () => {
  const subjects = [
    row("sub-001", { preprocessing: "done" }, { complete: true, qc_decision: "accept" }),
    row("sub-002", { preprocessing: "done" }, { complete: true }),
    row("sub-003", { anatomical: "failed" }),
    row("sub-004", { preprocessing: "running" }),
    row("sub-005", { artifact_rejection: "review" }),
    row("sub-006", { anatomical: "none" }),
  ];
  it("puts each subject in exactly one processing group", () => {
    expect(processState(subjects[2])).toBe("failed");
    const seg = Object.fromEntries(processSegments(subjects).map((s) => [s.key, s.n]));
    expect(seg).toEqual({ done: 2, running: 1, waiting: 1, failed: 1, rest: 1 });
  });
  it("counts quality decisions only among subjects with preprocessing done", () => {
    expect(qualityCounts(subjects)).toEqual({ total: 2, decided: 1, undecided: 1 });
  });
  it("lists failures first, then labels, then undecided quality", () => {
    const moves = yourMove({ subjects, review: [{ subject: "sub-005", what: "Label the components", since: "", page: "process/ica" }] });
    expect(moves.map((m) => m.id.split(":")[0])).toEqual(["failed", "review", "quality"]);
    expect(moves[0].to).toBe("subject/sub-003");
    expect(moves[2].to).toBe("subject/sub-002");
  });
  it("has nothing to say when nothing waits", () => {
    expect(yourMove({ subjects: [row("sub-001", { preprocessing: "done" }, { complete: true, qc_decision: "accept" })], review: [] })).toEqual([]);
  });
});
