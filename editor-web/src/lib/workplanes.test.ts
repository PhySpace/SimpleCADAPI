import { describe, expect, it } from "vitest";
import { frameSpec, normalizePlane, planeLabel, planeValue, planeWorkplane } from "@/lib/sketch-plane";
import { parseWorkplanes, patchCorners, resolvePlane, workplanePlane, workplaneRequest } from "@/lib/workplanes";

const TOP = { name: "wp_top", origin: [0, 0, 5], x_axis: [1, 0, 0], y_axis: [0, 1, 0], normal: [0, 0, 1] };

describe("workplanes", () => {
  it("reads the kernel's frames and drops what is not one", () => {
    const parsed = parseWorkplanes([TOP, { name: "bad name", origin: [0, 0, 0] }, { name: "x" }, 3]);
    expect(parsed).toEqual([TOP]);
    expect(parseWorkplanes(null)).toEqual([]);
  });

  it("a sketch plane on a workplane keeps its variable through the document round trip", () => {
    const plane = workplanePlane(parseWorkplanes([TOP])[0]);
    expect(plane.workplane).toBe("wp_top");
    expect(normalizePlane(JSON.parse(JSON.stringify(plane)))).toEqual(plane);
    expect(planeLabel(plane)).toBe("wp_top");
    expect(planeWorkplane(plane)).toBe("wp_top");
    expect(planeWorkplane("XY")).toBeNull();
    // the XY plane at the origin stays the workplane, not the datum plane
    expect(planeValue({ ...plane, origin: [0, 0, 0] })).toMatchObject({ workplane: "wp_top" });
    expect(frameSpec({ origin: [0, 0, 1], x_axis: [1, 0, 0], y_axis: [0, 1, 0] })).not.toHaveProperty("workplane");
    expect(normalizePlane({ workplane: "not ok!", origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0] })).not.toHaveProperty("workplane");
  });

  it("a plane on a workplane is drawn where the kernel says the workplane is now", () => {
    const stale = workplanePlane(parseWorkplanes([TOP])[0]);
    const moved = parseWorkplanes([{ ...TOP, origin: [0, 0, 9] }]);
    expect(resolvePlane(stale, moved)).toMatchObject({ workplane: "wp_top", origin: [0, 0, 9] });
    expect(resolvePlane(stale, [])).toBe(stale);
    expect(resolvePlane("XZ", moved)).toBe("XZ");
  });

  it("the patch is a square about the origin in the plane", () => {
    expect(patchCorners({ origin: [0, 0, 5], x_axis: [1, 0, 0], y_axis: [0, 1, 0] }, 2)).toEqual([
      [-2, -2, 5],
      [2, -2, 5],
      [2, 2, 5],
      [-2, 2, 5],
    ]);
  });

  it("Space reads the selection as one of the constructors", () => {
    const f = (n: number) => ({ kind: "face", n });
    const e = { kind: "edge", n: 9 };
    const v = (n: number) => ({ kind: "vertex", n });
    expect(workplaneRequest([f(1)])).toEqual({ method: "face", selections: { face: [f(1)] } });
    expect(workplaneRequest([e, f(1)])).toEqual({ method: "face_edge", selections: { face: [f(1)], edge: [e] } });
    expect(workplaneRequest([f(1), f(2)])).toEqual({ method: "midplane", selections: { face: [f(1)], face_b: [f(2)] } });
    expect(workplaneRequest([v(3), v(1), v(2)])?.selections).toEqual({ point_a: [v(3)], point_b: [v(1)], point_c: [v(2)] });
    expect(workplaneRequest([e])?.method).toBe("axis");
    expect(workplaneRequest([])).toBeNull();
    expect(workplaneRequest([f(1), f(2), f(3)])).toBeNull();
    expect(workplaneRequest([{ kind: "solid" }])).toBeNull();
    expect(workplaneRequest([v(1), v(2)])).toBeNull();
  });
});

import { selectionContext, whenFor } from "@/lib/commands";

describe("the workplane command", () => {
  const when = whenFor("workplane_from_selection")!;
  const ctx = (...kinds: string[]) => selectionContext(kinds.map((kind) => ({ kind, geometry: kind === "face" ? { type: "plane" } : null })));
  it("is offered for the selections Space understands, and only those", () => {
    for (const ok of [["face"], ["face", "edge"], ["face", "face"], ["vertex", "vertex", "vertex"], ["edge"]]) expect(when(ctx(...ok))).toBe(true);
    for (const no of [[], ["solid"], ["edge", "edge"], ["vertex"], ["face", "vertex"]]) expect(when(ctx(...no))).toBe(false);
    expect(when(selectionContext([{ kind: "face", geometry: { type: "cylinder" } }]))).toBe(false);
  });
});
