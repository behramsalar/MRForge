import { describe, expect, it } from "vitest";
import { stageColor, stageLabel, statusColor, statusLabel } from "./tokens";

const STAGE_STATES = ["none", "unavailable", "waiting", "running", "partial", "done", "failed", "stopped"];
const JOB_STATES = ["Queued", "Running", "Completed", "Failed", "Cancelled", "Interrupted"];

describe("status vocabulary", () => {
  it("every dashboard state has a colour and a plain-language label", () => {
    for (const s of STAGE_STATES) {
      expect(stageColor[s], s).toBeTruthy();
      expect(stageLabel[s], s).toBeTruthy();
    }
  });
  it("the same meaning has the same colour for stages and jobs", () => {
    expect(stageColor.done).toBe(statusColor.Completed);
    expect(stageColor.failed).toBe(statusColor.Failed);
    expect(stageColor.running).toBe(statusColor.Running);
    expect(stageColor.stopped).toBe(statusColor.Interrupted);
    expect(stageLabel.stopped).toBe(statusLabel.Interrupted);
  });
  it("every job state has a label", () => {
    for (const s of JOB_STATES) expect(statusLabel[s], s).toBeTruthy();
  });
});
