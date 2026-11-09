import { describe, expect, it } from "vitest";

import { moveIndex } from "./segmented";

const opts = (...disabled: boolean[]) => disabled.map((d) => ({ disabled: d }));

describe("moveIndex (arrow keys of a segmented control)", () => {
  it("moves right/down to the next and left/up to the previous, wrapping", () => {
    const o = opts(false, false, false);
    expect(moveIndex(o, 0, "ArrowRight")).toBe(1);
    expect(moveIndex(o, 2, "ArrowRight")).toBe(0);
    expect(moveIndex(o, 0, "ArrowLeft")).toBe(2);
    expect(moveIndex(o, 1, "ArrowDown")).toBe(2);
    expect(moveIndex(o, 1, "ArrowUp")).toBe(0);
  });
  it("skips disabled options", () => {
    const o = opts(false, true, false);
    expect(moveIndex(o, 0, "ArrowRight")).toBe(2);
    expect(moveIndex(o, 2, "ArrowLeft")).toBe(0);
  });
  it("stays where it is when nothing else is enabled", () => expect(moveIndex(opts(false, true), 0, "ArrowRight")).toBe(0));
  it("goes to the first and last enabled with Home and End", () => {
    const o = opts(true, false, false, true);
    expect(moveIndex(o, 2, "Home")).toBe(1);
    expect(moveIndex(o, 1, "End")).toBe(2);
  });
  it("ignores other keys and empty lists", () => {
    expect(moveIndex(opts(false, false), 0, "a")).toBeNull();
    expect(moveIndex([], 0, "ArrowRight")).toBeNull();
    expect(moveIndex(opts(true), 0, "Home")).toBeNull();
  });
});
