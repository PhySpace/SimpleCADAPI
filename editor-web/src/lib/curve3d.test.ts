import { describe, expect, it } from "vitest";

import { addSegment, arcPoints, dropLast, gridStep, onGrid, pathEnd, pickSnap, pointFor, rayOnPlane, type CurveDoc, type DrawPlane, type SnapCandidate } from "./curve3d";

const XY: DrawPlane = { name: "XY", workplane: false, origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0], normal: [0, 0, 1] };
const WP: DrawPlane = { name: "wp", workplane: true, origin: [0, 0, 10], x_axis: [1, 0, 0], y_axis: [0, 0, 1], normal: [0, -1, 0] };
const close = (a: readonly number[], b: readonly number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 9));

describe("drawing a 3D curve", () => {
  it("snaps to the nearest candidate, a vertex before a grid point", () => {
    const c = (kind: SnapCandidate["kind"], x: number, priority: number): SnapCandidate => ({ kind, at: [x, 0, 0], screen: [x, 0], label: kind, priority });
    expect(pickSnap([c("grid", 2, 3), c("vertex", 5, 0)], [2, 0])?.kind).toBe("vertex");
    expect(pickSnap([c("grid", 2, 3)], [40, 0])).toBeNull();
  });

  it("puts the pointer on the drawing plane and its grid", () => {
    close(rayOnPlane([0, 0, 10], [0, 0, -1], XY)!, [0, 0, 0]);
    expect(rayOnPlane([0, 0, 10], [1, 0, 0], XY)).toBeNull();
    expect(gridStep(3.2)).toBe(5);
    close(onGrid(WP, [1.4, 0, 12.6], 1), [1, 0, 13]);
  });

  it("draws an arc through its middle point", () => {
    const points = arcPoints([1, 0, 0], [0, 1, 0], [-1, 0, 0], 4);
    close(points[2], [0, 1, 0]);
    points.forEach((p) => expect(Math.hypot(...p)).toBeCloseTo(1, 9));
  });

  it("keeps a workplane point on its workplane and a vertex by its entity", () => {
    let doc: CurveDoc = { points: [], curves: [] };
    const a = pointFor(doc, WP, [3, 0, 14], null);
    doc = a.doc;
    expect(doc.points[0]).toEqual({ id: "p1", at: [3, 0, 14], on: "wp", uv: [3, 4] });
    const b = pointFor(doc, XY, [5, 5, 5], { kind: "vertex", at: [5, 5, 5], screen: [0, 0], entityId: "entity/p/vertex/vertex_2", label: "", priority: 0 });
    doc = addSegment(b.doc, "line", [a.id, b.id]);
    expect(doc.points[1].entity_id).toBe("entity/p/vertex/vertex_2");
    expect(pathEnd(doc)).toBe("p2");
    expect(dropLast(doc)).toEqual({ points: [doc.points[0]], curves: [] });
  });
});
