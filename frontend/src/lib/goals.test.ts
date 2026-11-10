import { describe, expect, it } from "vitest";
import { GOALS, goalStages } from "./goals";

const goal = (id: string) => GOALS.find((g) => g.id === id)!;

describe("goalStages", () => {
  it("leaves the server defaults alone for full processing", () => {
    expect(goalStages(goal("full"), true)).toBeUndefined();
  });
  it("adds artifact rejection only when the goal offers it and it is asked for", () => {
    expect(goalStages(goal("mni"), false)).not.toContain("artifact_rejection");
    expect(goalStages(goal("mni"), true)).toContain("artifact_rejection");
    expect(goalStages(goal("diffusion"), true)).toEqual(["diffusion"]);
  });
  it("lists the upstream stages a goal needs", () => {
    expect(goalStages(goal("connectivity"), false)).toEqual(["anatomical", "functional", "standard_space", "connectivity"]);
  });
});
