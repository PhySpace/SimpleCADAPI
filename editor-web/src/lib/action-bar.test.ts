import { describe, expect, it } from "vitest";

import { anchorOfEntity, enterRunsFirst, meanPoint, placeBar } from "@/lib/action-bar";

describe("placing the action bar", () => {
  const bar = { w: 200, h: 36 };
  const bounds = { w: 800, h: 600 };
  it("hangs below and to the right of the anchor", () => expect(placeBar([100, 100], bar, bounds)).toEqual({ x: 116, y: 116, docked: false }));
  it("flips to the left and above near the far edges", () => {
    const at = placeBar([780, 590], bar, bounds);
    expect(at.x + bar.w).toBeLessThanOrEqual(bounds.w - 8);
    expect(at.x).toBeLessThan(780);
    expect(at.y + bar.h).toBeLessThanOrEqual(590);
  });
  it("never leaves the container", () => {
    for (const anchor of [[-50, -50], [1000, 1000], [0, 700], [900, 0]] as [number, number][]) {
      const at = placeBar(anchor, bar, bounds);
      expect(at.x).toBeGreaterThanOrEqual(8);
      expect(at.y).toBeGreaterThanOrEqual(8);
      expect(at.x + bar.w).toBeLessThanOrEqual(bounds.w - 8);
      expect(at.y + bar.h).toBeLessThanOrEqual(bounds.h - 8);
    }
  });
  it("docks at the top centre without an anchor", () => expect(placeBar(null, bar, bounds)).toEqual({ x: 300, y: 8, docked: true }));
});

describe("Enter runs the first action", () => {
  const target = (selector: string | null) => ({ closest: (s: string) => (selector && s.includes(selector) ? {} : null) });
  it("does for a bare Enter on the page", () => expect(enterRunsFirst({ key: "Enter", target: target(null) })).toBe(true));
  it("does not while typing, on a button, in a list or with a modifier", () => {
    expect(enterRunsFirst({ key: "Enter", target: target("input") })).toBe(false);
    expect(enterRunsFirst({ key: "Enter", target: target("button") })).toBe(false);
    expect(enterRunsFirst({ key: "Enter", target: target("[role=option]") })).toBe(false);
    expect(enterRunsFirst({ key: "Enter", target: target(null), ctrlKey: true })).toBe(false);
    expect(enterRunsFirst({ key: "a", target: target(null) })).toBe(false);
  });
});

describe("where the bar hangs on a selection", () => {
  it("takes a face's centroid and an edge's midpoint", () => {
    expect(anchorOfEntity({ kind: "face", properties: { centroid: [1, 2, 3] } })).toEqual([1, 2, 3]);
    expect(anchorOfEntity({ kind: "edge", properties: { midpoint: [4, 5, 6], centroid: [0, 0, 0] } })).toEqual([4, 5, 6]);
    expect(anchorOfEntity({ kind: "face", properties: { area: 3 } })).toBeNull();
    expect(anchorOfEntity({ kind: "face", properties: null })).toBeNull();
  });
  it("means several anchors", () => {
    expect(meanPoint([[0, 0, 0], [2, 4, 6]])).toEqual([1, 2, 3]);
    expect(meanPoint([])).toBeNull();
  });
});
