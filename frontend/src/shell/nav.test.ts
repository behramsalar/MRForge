import { describe, expect, it } from "vitest";
import { GLOBAL_NAV, SETTINGS_NAV, SYSTEM_NAV, WORKSPACE_NAV, pageLabel } from "./nav";

describe("sidebar", () => {
  it("has unique pages with a label and an icon", () => {
    const all = [...WORKSPACE_NAV, ...GLOBAL_NAV, SYSTEM_NAV, SETTINGS_NAV];
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
  it("has one Process page without a tree, and results listed under Results", () => {
    expect(WORKSPACE_NAV.map((n) => n.id)).toEqual(["dashboard", "import", "data", "process", "quality", "results", "viewer", "jobs"]);
    expect(WORKSPACE_NAV.find((n) => n.id === "process")?.children).toBeUndefined();
    expect(WORKSPACE_NAV.find((n) => n.id === "results")?.children?.map((c) => c.id)).toEqual(["connectivity", "diffusion"]);
    expect(defaultChild("results")).toBe("connectivity");
    expect(defaultChild("viewer")).toBeUndefined();
  });
  it("names the trail in the top bar", () => {
    expect(crumbs("results", "diffusion")).toEqual(["Results", "Diffusion (ALPS)"]);
    expect(crumbs("results")).toEqual(["Results", "Connectivity"]);
    expect(crumbs("process")).toEqual(["Process"]);
    expect(crumbs("process", "func")).toEqual(["Process", "Functional preprocessing"]);
    expect(crumbs("viewer")).toEqual(["Viewer"]);
  });
});
