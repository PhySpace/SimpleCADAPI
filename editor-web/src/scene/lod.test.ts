import { describe, expect, it } from "vitest";

import { LOD_LEVELS, MAX_PART_TRIANGLES, cappedLevel, levelFor, mmPerPixel } from "./lod";

describe("level of detail", () => {
  it("picks the coarsest level whose chords stay under half a pixel", () => {
    expect(levelFor(1)).toBe(0); // 0.5 mm allowed: the preview's own 0.35 mm will do
    expect(levelFor(0.3)).toBe(1); // 0.15 mm allowed
    expect(levelFor(0.1)).toBe(2); // 0.05 mm allowed
    expect(levelFor(0.001)).toBe(LOD_LEVELS.length - 1); // closer than any level: the finest
  });

  it("measures a pixel on the part", () => {
    // 0.1 m away, 45° view, 740 px high: a pixel is about 0.112 mm
    expect(mmPerPixel(0.1, 45, 740)).toBeCloseTo(0.1119, 3);
  });

  it("stops before a part grows past the triangle budget", () => {
    expect(cappedLevel(3, 0, 1000)).toBe(3);
    expect(cappedLevel(3, 0, MAX_PART_TRIANGLES / 4)).toBe(2);
    expect(cappedLevel(3, 1, MAX_PART_TRIANGLES)).toBe(1);
  });
});
