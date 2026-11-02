import { describe, expect, it } from "vitest";

import { axisName, frameFromEntity, frameNormal, frameOf, normalizePlane, planeCoords, planeToWorld, planeValue, rayPlane, viewPose, worldToPlane, type Frame } from "@/lib/sketch-plane";

const close = (a: readonly number[], b: readonly number[], digits = 6) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], digits));

describe("named planes and frames", () => {
  it("have the SDK's axes and normals", () => {
    close(frameNormal(frameOf("XY")), [0, 0, 1]);
    close(frameNormal(frameOf("XZ")), [0, -1, 0]);
    close(frameNormal(frameOf("YZ")), [1, 0, 0]);
  });
  it("normalizes a stored plane: names stay names, frames get unit square axes, junk becomes XY", () => {
    expect(normalizePlane("XZ")).toBe("XZ");
    expect(normalizePlane("QQ")).toBe("XY");
    expect(normalizePlane({ origin: [1, 2, 3], x_axis: [2, 0, 0] })).toBe("XY");
    const f = normalizePlane({ origin: [1, 2, 3], x_axis: [0, 3, 0], y_axis: [0, 1, 4] }) as Frame;
    close(f.x_axis, [0, 1, 0]);
    close(f.y_axis, [0, 0, 1]);
    expect(f.origin).toEqual([1, 2, 3]);
  });
  it("a frame at the origin with a named plane's axes is that plane", () => {
    expect(planeValue({ origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 0, 1] })).toBe("XZ");
    expect(typeof planeValue({ origin: [0, 0, 5], x_axis: [1, 0, 0], y_axis: [0, 1, 0] })).toBe("object");
  });
});

describe("frame from entity info", () => {
  const top = { type: "plane", origin: [0, 0, 10], normal: [0, 0, 1], x_direction: [1, 0, 0] };
  it("uses the centroid as origin and y = normal x x_direction", () => {
    const f = frameFromEntity(top, { centroid: [20, 15, 10] })!;
    expect(f.origin).toEqual([20, 15, 10]);
    close(f.x_axis, [1, 0, 0]);
    close(f.y_axis, [0, 1, 0]);
    close(frameNormal(f), [0, 0, 1]);
  });
  it("squares x_direction to the normal and normalises it", () => {
    const f = frameFromEntity({ type: "plane", origin: [0, 0, 0], normal: [0, 0, 2], x_direction: [3, 0, 4] })!;
    close(f.x_axis, [1, 0, 0]);
    close(f.y_axis, [0, 1, 0]);
  });
  it("projects the centroid onto the plane", () => {
    const f = frameFromEntity({ type: "plane", origin: [0, 0, 10], normal: [0, 0, 1], x_direction: [1, 0, 0] }, { centroid: [1, 2, 13] })!;
    expect(f.origin).toEqual([1, 2, 10]);
  });
  it("derives a stable x when x_direction is missing: horizontal on walls, X on floors", () => {
    const wall = frameFromEntity({ type: "plane", origin: [0, 0, 0], normal: [0, -1, 0] })!;
    close(wall.x_axis, [1, 0, 0]);
    close(wall.y_axis, [0, 0, 1]);
    const floor = frameFromEntity({ type: "plane", origin: [0, 0, 0], normal: [0, 0, -1] })!;
    close(floor.x_axis, [1, 0, 0]);
    close(frameNormal(floor), [0, 0, -1]);
    const slanted = frameFromEntity({ type: "plane", origin: [0, 0, 0], normal: [1, 1, 1] })!;
    expect(slanted.x_axis[2]).toBeCloseTo(0, 9);
    close(frameNormal(slanted), [1 / Math.sqrt(3), 1 / Math.sqrt(3), 1 / Math.sqrt(3)]);
  });
  it("accepts {x,y,z} vectors and rejects non-planar or empty geometry", () => {
    expect(frameFromEntity({ type: "plane", origin: { x: 1, y: 2, z: 3 }, normal: { x: 0, y: 0, z: 1 } })!.origin).toEqual([1, 2, 3]);
    expect(frameFromEntity({ type: "cylinder", origin: [0, 0, 0], normal: [0, 0, 1] })).toBeNull();
    expect(frameFromEntity({})).toBeNull();
    expect(frameFromEntity(null)).toBeNull();
  });
  it("yields axes the server accepts: unit and square", () => {
    const f = frameFromEntity({ type: "plane", origin: [0.1, 0.2, 0.3], normal: [0.3, 0.5, 0.8], x_direction: [0.7, -0.1, 0.2] })!;
    const len = (a: number[]) => Math.hypot(a[0], a[1], a[2]);
    expect(len(f.x_axis)).toBeCloseTo(1, 8);
    expect(len(f.y_axis)).toBeCloseTo(1, 8);
    expect(f.x_axis[0] * f.y_axis[0] + f.x_axis[1] * f.y_axis[1] + f.x_axis[2] * f.y_axis[2]).toBeCloseTo(0, 8);
  });
});

describe("ray-plane intersection", () => {
  it("hits a named plane and returns plane coordinates", () => {
    const hit = rayPlane([3, 4, 10], [0, 0, -1], "XY")!;
    close(hit, [3, 4, 10]);
  });
  it("handles XZ (x -> X, y -> Z) and a slanted ray", () => {
    const hit = rayPlane([0, -10, 0], [0.5, 1, 0.25].map((c) => c / Math.hypot(0.5, 1, 0.25)) as [number, number, number], "XZ")!;
    expect(hit[0]).toBeCloseTo(5, 6);
    expect(hit[1]).toBeCloseTo(2.5, 6);
  });
  it("misses when parallel or when the plane is behind the ray", () => {
    expect(rayPlane([0, 0, 5], [1, 0, 0], "XY")).toBeNull();
    expect(rayPlane([0, 0, 5], [0, 0, 1], "XY")).toBeNull();
  });
  it("works on an offset frame", () => {
    const frame: Frame = { origin: [10, 0, 5], x_axis: [0, 1, 0], y_axis: [0, 0, 1] };
    const hit = rayPlane([0, 2, 6], [1, 0, 0], frame)!;
    close(hit, [2, 1, 10]);
  });
});

describe("world <-> plane", () => {
  it("maps named-plane centroids", () => {
    expect(planeCoords("XY", [3, 4, 9])).toEqual([3, 4]);
    expect(planeCoords("XZ", [3, 9, 4])).toEqual([3, 4]);
    expect(planeCoords("YZ", [9, 3, 4])).toEqual([3, 4]);
  });
  it("maps centroids on any frame and round trips", () => {
    const frame: Frame = { origin: [10, 20, 30], x_axis: [0, 1, 0], y_axis: [0, 0, 1] };
    expect(planeCoords(frame, [99, 25, 37])).toEqual([5, 7]);
    close(planeToWorld(frame, 5, 7), [10, 25, 37]);
    close(worldToPlane(frame, planeToWorld(frame, -3, 8)), [-3, 8]);
  });
});

describe("view pose and axis names", () => {
  it("looks straight at the plane from its normal side with y up", () => {
    const pose = viewPose("XZ", [0, 0, 0], 100);
    close(pose.position, [0, -100, 0]);
    close(pose.up, [0, 0, 1]);
  });
  it("names axis-aligned vectors only", () => {
    expect(axisName([0, 0, 1])).toBe("+z");
    expect(axisName([0, -1, 0])).toBe("-y");
    expect(axisName([0.6, 0, 0.8])).toBeNull();
  });
});
