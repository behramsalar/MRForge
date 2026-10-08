import { describe, expect, it } from "vitest";
import { arrange, move, nextSize, resize, setHidden } from "./reportLayout";

const paths = ["a.png", "b.png", "c.png"];

describe("report layout", () => {
  it("keeps the original order and default size when nothing was saved", () => {
    expect(arrange(paths, [], "m").map((p) => [p.image, p.size, p.hidden])).toEqual([
      ["a.png", "m", false],
      ["b.png", "m", false],
      ["c.png", "m", false],
    ]);
  });
  it("moves a picture one place and stops at the ends", () => {
    const one = move([], paths, "c.png", -1, "m");
    expect(arrange(paths, one, "m").map((p) => p.image)).toEqual(["a.png", "c.png", "b.png"]);
    const stay = move(one, paths, "a.png", -1, "m");
    expect(arrange(paths, stay, "m").map((p) => p.image)).toEqual(["a.png", "c.png", "b.png"]);
  });
  it("resizes and hides one picture without touching the others", () => {
    let items = resize([], paths, "b.png", "l", "m");
    items = setHidden(items, paths, "a.png", true, "m");
    const out = arrange(paths, items, "m");
    expect(out.find((p) => p.image === "b.png")?.size).toBe("l");
    expect(out.find((p) => p.image === "a.png")?.hidden).toBe(true);
    expect(out.find((p) => p.image === "c.png")).toMatchObject({ size: "m", hidden: false });
  });
  it("puts pictures that were not saved after the saved ones", () => {
    const saved = [{ image: "c.png" }];
    expect(arrange(paths, saved, "m").map((p) => p.image)).toEqual(["c.png", "a.png", "b.png"]);
  });
  it("cycles the size", () => {
    expect([nextSize("s"), nextSize("m"), nextSize("l")]).toEqual(["m", "l", "s"]);
  });
});
