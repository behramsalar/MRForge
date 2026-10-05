import { describe, expect, it } from "vitest";
import { GLOBAL_NAV, SETTINGS_NAV, WORKSPACE_NAV, pageLabel } from "./nav";

describe("sidebar", () => {
  it("has unique pages with a label and an icon", () => {
    const all = [...WORKSPACE_NAV, ...GLOBAL_NAV, SETTINGS_NAV];
    expect(new Set(all.map((n) => n.id)).size).toBe(all.length);
    for (const n of all) {
      expect(n.label).toBeTruthy();
      expect(n.icon).toBeTruthy();
    }
  });
  it("opens a workspace on its dashboard and keeps the viewer one click away", () => {
    expect(WORKSPACE_NAV[0].id).toBe("dashboard");
    expect(WORKSPACE_NAV.map((n) => n.id)).toContain("viewer");
  });
  it("names pages for the top bar", () => {
    expect(pageLabel("process")).toBe("Process");
    expect(pageLabel("unknown-page")).toBe("unknown-page");
  });
});

import { crumbs, defaultChild } from "./nav";

describe("sidebar tree", () => {
  it("keeps Process one flat item so new pipelines never lengthen the sidebar", () => {
    const process = WORKSPACE_NAV.find((n) => n.id === "process");
    expect(process?.children).toBeUndefined();
    expect(defaultChild("viewer")).toBeUndefined();
  });
  it("names the trail in the top bar", () => {
    expect(crumbs("process", "steps")).toEqual(["Process"]);
    expect(crumbs("viewer")).toEqual(["Viewer"]);
  });
});
