import { describe, expect, it } from "vitest";
import { href, parse } from "./router";

describe("router", () => {
  it("starts at the workspace list", () => {
    expect(parse("")).toEqual({ page: "workspaces" });
    expect(parse("#/")).toEqual({ page: "workspaces" });
  });
  it("reads workspace, page and extra", () => {
    expect(parse("#/w/demo/view/sub-001")).toEqual({ workspace: "demo", page: "view", extra: "sub-001" });
  });
  it("defaults a workspace to the import page", () => {
    expect(parse("#/w/demo").page).toBe("import");
  });
  it("round-trips links", () => {
    expect(parse(href("my study", "import", "import-002"))).toEqual({
      workspace: "my study",
      page: "import",
      extra: "import-002",
    });
  });
});
