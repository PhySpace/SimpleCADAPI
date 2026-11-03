import { describe, expect, it } from "vitest";

import { fitDistance, FIT_MARGIN, horizontalFov } from "./camera-fit";

const deg = (d: number) => (d * Math.PI) / 180;

/** Angular half-size of a sphere of `radius` seen from `distance`. */
const halfAngle = (radius: number, distance: number) => Math.asin(radius / distance);

describe("fitDistance", () => {
  it("keeps the whole bounding sphere inside the narrower view angle with the margin, for 1 mm to 1 m models", () => {
    for (const radius of [0.0005, 0.005, 0.05, 0.5]) {
      for (const aspect of [0.5, 1, 16 / 9, 3]) {
        const vfov = deg(42);
        const d = fitDistance(radius, vfov, aspect);
        const narrow = Math.min(vfov, horizontalFov(vfov, aspect)) / 2;
        expect(halfAngle(radius, d)).toBeLessThan(narrow); // inside
        expect(halfAngle(radius, d)).toBeCloseTo(Math.asin(Math.sin(narrow) / FIT_MARGIN), 9); // with the margin
        expect(d).toBeGreaterThan(radius); // the camera is outside the sphere
      }
    }
  });

  it("scales linearly with the radius and is farther for a narrower view", () => {
    expect(fitDistance(2, deg(42), 1.6)).toBeCloseTo(2 * fitDistance(1, deg(42), 1.6), 12);
    expect(fitDistance(1, deg(42), 0.5)).toBeGreaterThan(fitDistance(1, deg(42), 2));
  });

  it("projects the sphere's silhouette inside the screen with ~15% air (tangent test on the vertical axis)", () => {
    const vfov = deg(42);
    const d = fitDistance(1, vfov, 2); // wide: the vertical angle limits
    const tangent = 1 / Math.sqrt(d * d - 1); // tan of the silhouette half angle
    const ndc = tangent / Math.tan(vfov / 2);
    expect(ndc).toBeLessThan(1);
    expect(ndc).toBeGreaterThan(0.8);
  });

  it("is zero for an empty radius and finite for a degenerate aspect", () => {
    expect(fitDistance(0, deg(42), 1)).toBe(0);
    expect(Number.isFinite(fitDistance(1, deg(42), 0))).toBe(true);
  });
});
