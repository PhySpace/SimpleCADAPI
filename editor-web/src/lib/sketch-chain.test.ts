import { describe, expect, it } from "vitest";

import { addLine, emptyDoc, ensurePoint, type SketchDoc } from "@/lib/sketch";

const opts = { auto: false, construction: false };
const line = (doc: SketchDoc, a: [number, number], b: [number, number]) => {
  const start = ensurePoint(doc, { x: a[0], y: a[1] });
  return addLine(start.doc, start.id, { x: b[0], y: b[1] }, opts)!.doc;
};

describe("joining lines end to end", () => {
  const open = () => {
    // three lines drawn apart: a(0,0)-(10,0), b(10.2,0.1)-(10,10), c(9.9,10.1)-(0,10)
    let doc = line(emptyDoc(), [0, 0], [10, 0]);
    doc = line(doc, [10.2, 0.1], [10, 10]);
    return line(doc, [9.9, 10.1], [0, 10]);
  };
  it("offers coincident for lines and arcs alone, and links the nearest ends whatever the click order", async () => {
    const { applicableConstraints, constraintTargets } = await import("@/lib/sketch");
    const doc = open();
    const ids = doc.entities.map((e) => e.id);
    expect(applicableConstraints(ids, doc)).toContain("coincident");
    const ends = (id: string) => [doc.entities.find((e) => e.id === id)!.start, doc.entities.find((e) => e.id === id)!.end];
    const forward = constraintTargets("coincident", ids, doc);
    const shuffled = constraintTargets("coincident", [ids[2], ids[0], ids[1]], doc);
    expect(forward).toHaveLength(2); // l1-l2 and l2-l3; the open ends are far apart relative to the shortest line
    const norm = (pairs: string[][]) => pairs.map((pair) => [...pair].sort().join("-")).sort();
    expect(norm(shuffled)).toEqual(norm(forward));
    expect(forward[0].every((p) => [...ends(ids[0]), ...ends(ids[1])].includes(p))).toBe(true);
  });
  it("closes an outline whose open ends are close", async () => {
    const { constraintTargets } = await import("@/lib/sketch");
    let doc = open();
    doc = line(doc, [0.1, 9.9], [0, 0.3]); // a fourth line back to near the start
    const ids = doc.entities.map((e) => e.id);
    expect(constraintTargets("coincident", ids, doc)).toHaveLength(4);
  });
});

describe("B-splines in a sketch", () => {
  it("are made from clicked control points (degree 3, less with fewer), and close on their first point", async () => {
    const { addSpline, entityPointIds, emptyDoc: empty } = await import("@/lib/sketch");
    const four = addSpline(empty(), [{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 0 }, { x: 30, y: 10 }], { auto: false, construction: false })!;
    const spline = four.doc.entities[0];
    expect(spline).toMatchObject({ kind: "bspline", degree: 3, start: "p1", end: "p4", control_points: ["p1", "p2", "p3", "p4"] });
    expect(entityPointIds(spline)).toEqual(["p1", "p4", "p2", "p3"]);
    const two = addSpline(empty(), [{ x: 0, y: 0 }, { x: 10, y: 0 }], { auto: false, construction: false })!;
    expect(two.doc.entities[0].degree).toBe(1);
    expect(addSpline(empty(), [{ x: 0, y: 0 }], { auto: false, construction: false })).toBeNull();
    const ring = addSpline(empty(), [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 0, pointId: "p1" }], { auto: false, construction: false })!;
    expect(ring.doc.entities[0]).toMatchObject({ start: "p1", end: "p1", control_points: ["p1", "p2", "p3", "p1"] });
  });
  it("are drawn by the SDK's samples, and make a loop the SDK offers", async () => {
    const { addSpline, addLine, emptyDoc: empty, findLoops, splinePath, solvedPoints } = await import("@/lib/sketch");
    let doc = addSpline(empty(), [{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 0 }], { auto: false, construction: false })!.doc;
    doc = addLine(doc, "p3", { x: 0, y: 0, pointId: "p1" }, { auto: false, construction: false })!.doc;
    const samples: [number, number][] = [[0, 0], [5, 4], [10, 5], [15, 4], [20, 0]];
    const solve = { ok: true, status: "underconstrained" as const, dof: 6, residual: 0, points: {}, scalars: {}, entities: {}, diagnostics: [], unusable: [],
      profiles: [{ index: 0, id: "s1", kind: "edge_loop", closed: true, entity_ids: ["s1", "l1"], reversed: [false, false] }],
      curves: { s1: { points: samples, normals: samples.map(() => [0, 1] as [number, number]), curvatures: samples.map(() => 0.1) } } };
    expect(splinePath(doc.entities[0], solvedPoints(doc, solve), solve)).toEqual(samples);
    expect(splinePath(doc.entities[0], solvedPoints(doc, null), null)).toEqual([[0, 0], [10, 10], [20, 0]]); // control polygon until solved
    const [loop] = findLoops(doc, solve);
    expect(loop.index).toBe(0);
    expect(Math.abs(loop.area)).toBeGreaterThan(50);
  });
});
