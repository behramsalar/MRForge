import { describe, expect, it } from "vitest";
import { WORKSPACE_NAV } from "../shell/nav";
import { buildEntries, filterEntries } from "./palette";

describe("command palette entries", () => {
  const entries = buildEntries("demo", WORKSPACE_NAV, ["sub-001", "sub-012"]);
  it("offers every sidebar page, every function under it and every subject", () => {
    const ids = entries.map((e) => e.id);
    expect(ids).toContain("page:viewer");
    expect(ids).toContain("page:process/anat");
    expect(ids).toContain("subject:sub-012");
    expect(entries.find((e) => e.id === "subject:sub-001")?.to).toBe("#/w/demo/subject/sub-001");
  });
  it("outside a workspace only offers global pages and actions", () => {
    const g = buildEntries(undefined, WORKSPACE_NAV, ["sub-001"]);
    expect(g.some((e) => e.group === "Subjects")).toBe(false);
    expect(g.map((e) => e.id)).toContain("page:settings");
  });
  it("matches all typed words in any order, label hits first", () => {
    expect(filterEntries(entries, "012")[0].id).toBe("subject:sub-012");
    expect(filterEntries(entries, "anat process").map((e) => e.id)).toContain("page:process/anat");
    expect(filterEntries(entries, "zzzz")).toEqual([]);
  });
});
