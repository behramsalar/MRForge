import { describe, expect, it } from "vitest";
import { helpFor } from "./qcHelp";

describe("QC help texts", () => {
  it("every QC picture the steps produce has a plain-language explanation", () => {
    for (const name of [
      "Head motion",
      "Registration to the T1",
      "Distortion correction (before above, after below)",
      "Alignment to standard space (red: outline of the MNI brain)",
    ]) {
      expect(helpFor(name), name).toBeTruthy();
    }
  });
  it("never tells the user to exclude data", () => {
    for (const name of ["Head motion", "Registration to the T1"]) {
      expect(helpFor(name)).not.toMatch(/exclude data automatically|you must exclude/i);
    }
    expect(helpFor("Head motion")).toMatch(/you decide/i);
  });
});
