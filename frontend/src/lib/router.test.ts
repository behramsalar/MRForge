import { describe, expect, it } from "vitest";
import { href, parse } from "./router";

describe("router", () => {
  it("starts at the workspace list", () => {
    expect(parse("")).toEqual({ page: "workspaces" });
    expect(parse("#/")).toEqual({ page: "workspaces" });
  });
  it("has global pages", () => {
    expect(parse("#/settings")).toEqual({ page: "settings" });
    expect(parse("#/system")).toEqual({ page: "system" });
    expect(parse("#/design")).toEqual({ page: "design" });
  });
  it("opens a workspace on its dashboard", () => {
    expect(parse("#/w/demo")).toEqual({ workspace: "demo", page: "dashboard", extra: undefined, extra2: undefined });
  });
  it("reads workspace, page and extra", () => {
    expect(parse("#/w/demo/viewer/sub-001")).toEqual({ workspace: "demo", page: "viewer", extra: "sub-001" });
    expect(parse("#/w/demo/process/func")).toEqual({ workspace: "demo", page: "process", extra: "func" });
  });
  it("keeps addresses from before the sidebar working", () => {
    expect(parse("#/w/demo/import/import-002")).toEqual({ workspace: "demo", page: "data", extra: "import-002" });
    expect(parse("#/w/demo/anat")).toEqual({ workspace: "demo", page: "process", extra: "anat" });
    expect(parse("#/w/demo/func")).toEqual({ workspace: "demo", page: "process", extra: "func" });
    expect(parse("#/w/demo/process/full")).toEqual({ workspace: "demo", page: "process", extra: "pipelines" });
    expect(parse("#/w/demo/view/sub-001")).toEqual({ workspace: "demo", page: "viewer", extra: "sub-001" });
  });
  it("can name the image to show in the viewer", () => {
    const link = href("demo", "viewer", "sub-001", "rawbids/sub-001/anat/sub-001_T1w.nii.gz");
    expect(parse(link)).toEqual({
      workspace: "demo",
      page: "viewer",
      extra: "sub-001",
      extra2: "rawbids/sub-001/anat/sub-001_T1w.nii.gz",
    });
  });
  it("round-trips links", () => {
    expect(parse(href("my study", "data", "import-002"))).toEqual({
      workspace: "my study",
      page: "data",
      extra: "import-002",
    });
  });
});
