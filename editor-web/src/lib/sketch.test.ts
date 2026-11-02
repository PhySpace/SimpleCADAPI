import { describe, expect, it } from "vitest";

import {
  LatestSolver,
  addArc,
  addCircle,
  addConstraint,
  addLine,
  applicableConstraints,
  applySolved,
  choiceToIndices,
  constraintTargets,
  docToJson,
  dragDoc,
  dragPoints,
  emptyDoc,
  ensurePoint,
  findLoops,
  gridStep,
  hitTest,
  isFixed,
  loopAt,
  matchLoops,
  measure,
  nextId,
  normalizeDoc,
  parseDimension,
  pickLoop,
  reconcileChoice,
  removeEntity,
  removePoint,
  screenToWorld,
  snap,
  stripTemp,
  worldToScreen,
  zoomAt,
  type SketchDoc,
  type SolveResult,
} from "@/lib/sketch";

const opts = { auto: true, construction: false };

function rectangle(w = 40, h = 20): SketchDoc {
  let doc = emptyDoc();
  const a = ensurePoint(doc, { x: 0, y: 0 });
  doc = a.doc;
  let at = a.id;
  const first = a.id;
  for (const [x, y] of [[w, 0], [w, h], [0, h]] as const) {
    const made = addLine(doc, at, { x, y }, opts)!;
    doc = made.doc;
    at = made.endId;
  }
  return addLine(doc, at, { x: 0, y: 0, pointId: first }, opts)!.doc;
}

const result = (over: Partial<SolveResult> = {}): SolveResult => ({ ok: true, status: "underconstrained", dof: 1, residual: 0, points: {}, scalars: {}, entities: {}, diagnostics: [], profiles: [], ...over });

describe("ids", () => {
  it("generates p, l, c, a, k ids without clashes", () => {
    const doc = rectangle();
    expect(doc.points.map((p) => p.id)).toEqual(["p1", "p2", "p3", "p4"]);
    expect(doc.entities.map((e) => e.id)).toEqual(["l1", "l2", "l3", "l4"]);
    expect(nextId("l", doc)).toBe("l5");
    expect(nextId("k", doc)).toBe("k5"); // four auto constraints exist
    const circle = addCircle(doc, { x: 10, y: 10 }, { x: 13, y: 10 }, opts)!;
    expect(circle.id).toBe("c1");
    const arc = addArc(circle.doc, { x: 0, y: 0 }, { x: 5, y: 0 }, { x: 0, y: 7 }, opts)!;
    expect(arc.id).toBe("a1");
    const all = [...arc.doc.points.map((p) => p.id), ...arc.doc.entities.map((e) => e.id), ...arc.doc.constraints.map((c) => c.id)];
    expect(new Set(all).size).toBe(all.length);
    for (const id of all) expect(id).toMatch(/^[a-z][a-z0-9_]{0,30}$/);
  });
});

describe("drawing", () => {
  it("adds horizontal/vertical constraints to near-aligned lines and aligns the seed", () => {
    const doc = rectangle(40, 20);
    expect(doc.constraints.map((c) => c.kind)).toEqual(["horizontal", "vertical", "horizontal", "vertical"]);
    const slanted = addLine(emptyDoc(), ensurePoint(emptyDoc(), { x: 0, y: 0 }).id, { x: 10, y: 0.3 }, opts);
    expect(slanted).toBeNull(); // the start point is not in the document yet
    const start = ensurePoint(emptyDoc(), { x: 0, y: 0 });
    const made = addLine(start.doc, start.id, { x: 10, y: 0.3 }, opts)!;
    expect(made.doc.points[1].y).toBe(0);
    expect(made.doc.constraints[0].kind).toBe("horizontal");
    const off = addLine(start.doc, start.id, { x: 10, y: 5 }, opts)!;
    expect(off.doc.constraints).toHaveLength(0);
    const manual = addLine(start.doc, start.id, { x: 10, y: 0.3 }, { auto: false, construction: true })!;
    expect(manual.doc.constraints).toHaveLength(0);
    expect(manual.doc.entities[0].construction).toBe(true);
  });

  it("reuses an existing point and refuses a zero length line", () => {
    const doc = rectangle();
    expect(doc.points).toHaveLength(4);
    const same = addLine(doc, "p1", { x: 0, y: 0, pointId: "p1" }, opts);
    expect(same).toBeNull();
  });

  it("makes a circle with a radius seed and an arc whose end lies on the circle", () => {
    const circle = addCircle(emptyDoc(), { x: 1, y: 2 }, { x: 4, y: 6 }, opts)!;
    expect(circle.doc.entities[0]).toMatchObject({ kind: "circle", center: "p1", radius: 5 });
    expect(addCircle(emptyDoc(), { x: 1, y: 2 }, { x: 1, y: 2 }, opts)).toBeNull();
    const arc = addArc(emptyDoc(), { x: 0, y: 0 }, { x: 5, y: 0 }, { x: 0, y: 20 }, opts)!;
    const end = arc.doc.points.find((p) => p.id === "p3")!;
    expect(end.x).toBeCloseTo(0);
    expect(end.y).toBeCloseTo(5);
  });

  it("deletes entities with their constraints and orphan points", () => {
    const doc = rectangle();
    const without = removeEntity(doc, "l1");
    expect(without.entities.map((e) => e.id)).toEqual(["l2", "l3", "l4"]);
    expect(without.constraints.some((c) => c.targets.includes("l1"))).toBe(false);
    expect(without.points).toHaveLength(4); // still held by the other lines
    const gone = removePoint(doc, "p1");
    expect(gone.entities.map((e) => e.id)).toEqual(["l2", "l3"]);
    expect(gone.points.map((p) => p.id)).not.toContain("p1");
  });
});

describe("applicableConstraints", () => {
  const doc = (() => {
    let d = rectangle();
    d = addCircle(d, { x: 10, y: 10 }, { x: 12, y: 10 }, opts)!.doc;
    d = addCircle(d, { x: 30, y: 10 }, { x: 32, y: 10 }, opts)!.doc;
    return d;
  })();
  it("offers nothing for an empty selection or an unknown id", () => {
    expect(applicableConstraints([], doc)).toEqual([]);
    expect(applicableConstraints(["nope"], doc)).toEqual([]);
  });
  it("one line", () => expect(applicableConstraints(["l1"], doc)).toEqual(["horizontal", "vertical", "length"]));
  it("two lines", () => expect(applicableConstraints(["l1", "l2"], doc)).toEqual(["parallel", "perpendicular", "collinear", "equal_length", "line_distance", "angle"]));
  it("a point and a line", () => expect(applicableConstraints(["p3", "l1"], doc)).toEqual(["point_on", "midpoint", "fix"]));
  it("two points", () =>
    expect(applicableConstraints(["p1", "p3"], doc)).toEqual(["points_horizontal", "points_vertical", "coincident", "fix", "distance", "distance_x", "distance_y"]));
  it("a circle", () => expect(applicableConstraints(["c1"], doc)).toEqual(["radius", "diameter"]));
  it("two circles", () => expect(applicableConstraints(["c1", "c2"], doc)).toEqual(["tangent", "concentric", "equal_radius"]));
  it("a line and a circle", () => expect(applicableConstraints(["l1", "c1"], doc)).toEqual(["tangent"]));
  it("fix for any point", () => expect(applicableConstraints(["p2"], doc)).toEqual(["fix"]));
  it("symmetric needs two points and a line", () => expect(applicableConstraints(["p1", "p3", "l2"], doc)).toEqual(["symmetric", "fix"]));
  it("orders targets as the server wants them", () => {
    expect(constraintTargets("point_on", ["l1", "p3"], doc)).toEqual([["p3", "l1"]]);
    expect(constraintTargets("tangent", ["c1", "l1"], doc)).toEqual([["l1", "c1"]]);
    expect(constraintTargets("symmetric", ["l2", "p1", "p3"], doc)).toEqual([["p1", "p3", "l2"]]);
    expect(constraintTargets("fix", ["p1", "p2"], doc)).toEqual([["p1"], ["p2"]]);
    expect(constraintTargets("radius", ["l1"], doc)).toEqual([]);
  });
});

describe("measure", () => {
  const doc = rectangle(40, 20);
  it("measures from the solved geometry when there is one, else from the seeds", () => {
    expect(measure("length", ["l1"], doc, null)).toBeCloseTo(40);
    const solved = result({ points: { p1: [0, 0], p2: [50, 0], p3: [50, 20], p4: [0, 20] } });
    expect(measure("length", ["l1"], doc, solved)).toBeCloseTo(50);
    expect(measure("distance", ["p1", "p3"], doc, null)).toBeCloseTo(Math.hypot(40, 20));
    expect(measure("distance_x", ["p1", "p2"], doc, null)).toBe(40);
    expect(measure("distance_y", ["p2", "p1"], doc, null)).toBeCloseTo(0);
    expect(measure("angle", ["l1", "l2"], doc, null)).toBeCloseTo(90);
    expect(measure("line_distance", ["l1", "l3"], doc, null)).toBeCloseTo(20);
  });
  it("measures a circle", () => {
    const d = addCircle(emptyDoc(), { x: 0, y: 0 }, { x: 3, y: 0 }, opts)!.doc;
    expect(measure("radius", ["c1"], d, null)).toBe(3);
    expect(measure("diameter", ["c1"], d, null)).toBe(6);
    expect(measure("radius", ["c1"], d, result({ entities: { c1: { radius: 4 } } }))).toBe(4);
  });
  it("parses dimension text", () => {
    expect(parseDimension(" 12.5 ", "length")).toBe(12.5);
    expect(parseDimension("45°", "angle")).toBe(45);
    expect(parseDimension("-3", "length")).toBeNull();
    expect(parseDimension("-3", "distance_x")).toBe(-3);
    expect(parseDimension("abc", "length")).toBeNull();
  });
});

describe("snapping and view", () => {
  const points = new Map<string, [number, number]>([["p1", [10, 10]]]);
  it("snaps to a nearby point before the grid", () => {
    expect(snap([10.3, 9.8], points, { grid: 5, tol: 1 })).toMatchObject({ pointId: "p1", x: 10, y: 10, kind: "point" });
  });
  it("snaps to the grid, or stays free", () => {
    expect(snap([12.4, 7.6], points, { grid: 5, tol: 0.5 })).toMatchObject({ x: 10, y: 10, kind: "grid" });
    expect(snap([12.4, 7.6], points, { grid: null, tol: 0.5 })).toMatchObject({ x: 12.4, y: 7.6, kind: "free" });
  });
  it("skips given points", () => {
    expect(snap([10, 10], points, { grid: null, tol: 1, skip: new Set(["p1"]) }).kind).toBe("free");
  });
  it("round-trips world and screen and zooms about the cursor", () => {
    const view = { scale: 4, ox: 100, oy: 200 };
    const [sx, sy] = worldToScreen(view, 3, 5);
    expect(screenToWorld(view, sx, sy)).toEqual([3, 5]);
    const zoomed = zoomAt(view, 250, 120, 2);
    const before = screenToWorld(view, 250, 120);
    const after = screenToWorld(zoomed, 250, 120);
    expect(after[0]).toBeCloseTo(before[0]);
    expect(after[1]).toBeCloseTo(before[1]);
    expect(zoomed.scale).toBe(8);
  });
  it("picks a readable grid step", () => {
    expect(gridStep(10)).toBe(2);
    expect(gridStep(1)).toBe(20);
    expect(gridStep(100)).toBe(0.2);
  });
});

describe("hit testing", () => {
  const doc = addCircle(rectangle(), { x: 10, y: 10 }, { x: 13, y: 10 }, opts)!.doc;
  it("finds points before entities, and entities near their curves", () => {
    expect(hitTest(doc, null, [0.2, 0.1], 1)).toEqual({ kind: "point", id: "p1" });
    expect(hitTest(doc, null, [20, 0.4], 1)).toEqual({ kind: "entity", id: "l1" });
    expect(hitTest(doc, null, [13.2, 10], 1)).toEqual({ kind: "entity", id: "c1" });
    expect(hitTest(doc, null, [20, 5], 1)).toBeNull();
  });
});

describe("loops", () => {
  it("finds the rectangle and a free circle, and not dangling edges", () => {
    const doc = addCircle(rectangle(), { x: 20, y: 10 }, { x: 23, y: 10 }, opts)!.doc;
    const loops = findLoops(doc, null);
    expect(loops).toHaveLength(2);
    const rect = loops.find((l) => l.entities.length === 4)!;
    expect(rect.area).toBeCloseTo(800);
    expect(rect.centroid[0]).toBeCloseTo(20);
    expect(rect.centroid[1]).toBeCloseTo(10);
    expect(loops.find((l) => l.key === "c1")!.area).toBeCloseTo(Math.PI * 9);
    const open = removeEntity(rectangle(), "l4");
    expect(findLoops(open, null)).toHaveLength(0);
  });
  it("splits a rectangle with a divider into two faces", () => {
    let doc = rectangle(40, 20);
    const a = ensurePoint(doc, { x: 20, y: 0 });
    doc = a.doc;
    // split the bottom edge: p1-p2 stays, so build a fresh doc with a mid point instead
    doc = emptyDoc();
    let at = ensurePoint(doc, { x: 0, y: 0 });
    doc = at.doc;
    const ids: string[] = [at.id];
    for (const spot of [{ x: 20, y: 0 }, { x: 40, y: 0 }, { x: 40, y: 20 }, { x: 20, y: 20 }, { x: 0, y: 20 }]) {
      const made = addLine(doc, ids[ids.length - 1], spot, opts)!;
      doc = made.doc;
      ids.push(made.endId);
    }
    doc = addLine(doc, ids[ids.length - 1], { x: 0, y: 0, pointId: ids[0] }, opts)!.doc;
    doc = addLine(doc, ids[1], { x: 20, y: 20, pointId: ids[4] }, opts)!.doc;
    const loops = findLoops(doc, null);
    expect(loops.map((l) => Math.round(l.area)).sort()).toEqual([400, 400]);
  });
  it("traverses arcs counter-clockwise: a D shape", () => {
    let doc = emptyDoc();
    const c = ensurePoint(doc, { x: 0, y: 0 });
    doc = c.doc;
    const arc = addArc(doc, { x: 0, y: 0, pointId: c.id }, { x: 0, y: -5 }, { x: 0, y: 5 }, opts)!;
    doc = arc.doc;
    doc = addLine(doc, "p3", { x: 0, y: -5, pointId: "p2" }, opts)!.doc;
    const [loop] = findLoops(doc, null);
    expect(loop.area).toBeGreaterThan(30);
    expect(loop.area).toBeLessThan(40); // about half of pi * 25 = 39.3 (24 chord samples)
    expect(loop.centroid[0]).toBeGreaterThan(0);
  });
  it("finds the loop under a position, smallest first", () => {
    const doc = addCircle(rectangle(), { x: 20, y: 10 }, { x: 23, y: 10 }, opts)!.doc;
    const loops = findLoops(doc, null);
    expect(loopAt(loops, [20, 10])!.key).toBe("c1");
    expect(loopAt(loops, [2, 2])!.entities).toHaveLength(4);
    expect(loopAt(loops, [100, 100])).toBeNull();
  });
});

describe("profile matching and choice", () => {
  const doc = addCircle(rectangle(), { x: 20, y: 10 }, { x: 23, y: 10 }, opts)!.doc;
  const profiles = [
    { index: 0, area: Math.PI * 9, centroid: [20, 10, 0] as [number, number, number] },
    { index: 1, area: 800, centroid: [20, 10, 0] as [number, number, number] },
  ];
  it("matches loops to server profiles by area and centroid, whatever the order", () => {
    const loops = matchLoops(findLoops(doc, null), profiles, "XY");
    expect(loops.find((l) => l.key === "c1")!.index).toBe(0);
    expect(loops.find((l) => l.entities.length === 4)!.index).toBe(1);
    const reversed = matchLoops(findLoops(doc, null), [{ ...profiles[1], index: 0 }, { ...profiles[0], index: 1 }], "XY");
    expect(reversed.find((l) => l.key === "c1")!.index).toBe(1);
  });
  it("reads centroids in the sketch plane", () => {
    const xz = matchLoops(findLoops(doc, null), [{ index: 5, area: 800, centroid: [20, 0, 10] }], "XZ");
    expect(xz.find((l) => l.entities.length === 4)!.index).toBe(5);
    expect(matchLoops(findLoops(doc, null), [{ index: 5, area: 800, centroid: [20, 0, 10] }], "XY").every((l) => l.index === null)).toBe(true);
  });
  it("defaults the outer profile to the largest loop and turns choices into indices", () => {
    const loops = matchLoops(findLoops(doc, null), profiles, "XY");
    let choice = reconcileChoice({ outer: null, inner: [], chosen: false }, loops);
    expect(choiceToIndices(choice, loops)).toEqual({ profile: 1, inner: [] });
    choice = pickLoop(choice, "c1", true);
    expect(choiceToIndices(choice, loops)).toEqual({ profile: 1, inner: [0] });
    choice = pickLoop(choice, "c1", true);
    expect(choice.inner).toEqual([]);
    choice = pickLoop(pickLoop(choice, "c1", true), "c1", false);
    expect(choice.outer).toBe("c1");
    expect(choice.inner).toEqual([]);
    const removed = reconcileChoice(choice, loops.filter((l) => l.key !== "c1"));
    expect(removed.outer).toBeNull();
  });
});

describe("document round trip", () => {
  it("survives JSON and fills in defaults", () => {
    const doc = addConstraint(rectangle(), { kind: "length", targets: ["l1"], value: 40, driving: true });
    expect(normalizeDoc(JSON.parse(JSON.stringify(docToJson(doc))))).toEqual(doc);
    expect(normalizeDoc(null)).toEqual(emptyDoc());
    expect(normalizeDoc({ plane: "XZ", profile: 2, inner: [0, "x"], points: [{ id: "a", x: 1, y: 2 }] })).toMatchObject({ plane: "XZ", profile: 2, inner: [0], fully_constrained: false });
    expect(normalizeDoc({ plane: "QQ" }).plane).toBe("XY");
  });
  it("writes solved coordinates and circle radii back into the seeds", () => {
    const doc = addCircle(rectangle(), { x: 20, y: 10 }, { x: 23, y: 10 }, opts)!.doc;
    const next = applySolved(doc, result({ points: { p2: [41.00001, 0] }, entities: { c1: { radius: 4.25 } } }));
    expect(next.points.find((p) => p.id === "p2")!.x).toBe(41);
    expect(next.entities.find((e) => e.id === "c1")!.radius).toBe(4.25);
    expect(next.points.find((p) => p.id === "p1")).toEqual(doc.points.find((p) => p.id === "p1"));
  });
});

describe("drag: the temporary fix", () => {
  const doc = rectangle();
  it("moves the dragged points and holds each with a temporary fix, never touching the original", () => {
    const eff = dragDoc(doc, { p3: [45, 22] });
    expect(eff.points.find((p) => p.id === "p3")).toMatchObject({ x: 45, y: 22 });
    const temp = eff.constraints.filter((c) => c.kind === "fix");
    expect(temp).toEqual([{ id: "tmp1", kind: "fix", targets: ["p3"] }]);
    expect(doc.constraints.some((c) => c.kind === "fix")).toBe(false);
    expect(stripTemp(eff).constraints).toEqual(doc.constraints);
    const ids = eff.constraints.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
  it("one temporary fix per point of a dragged line", () => {
    expect(dragPoints(doc, "l1")).toEqual(["p1", "p2"]);
    expect(dragPoints(doc, "p4")).toEqual(["p4"]);
    expect(dragPoints(doc, "zzz")).toEqual([]);
    const eff = dragDoc(doc, { p1: [1, 1], p2: [41, 1] });
    expect(eff.constraints.filter((c) => c.id.startsWith("tmp")).map((c) => c.id)).toEqual(["tmp1", "tmp2"]);
  });
  it("knows which points are fixed (they are not dragged)", () => {
    const fixed = addConstraint(doc, { kind: "fix", targets: ["p1"] });
    expect(isFixed(fixed, "p1")).toBe(true);
    expect(isFixed(fixed, "p2")).toBe(false);
  });
  it("drops only temporary constraints a person did not add", () => {
    const eff = dragDoc(addConstraint(doc, { kind: "fix", targets: ["p1"] }), { p3: [1, 1] });
    expect(stripTemp(eff).constraints.some((c) => c.kind === "fix" && c.targets[0] === "p1")).toBe(true);
    expect(stripTemp(eff).constraints.some((c) => c.id === "tmp1")).toBe(false);
  });
});

describe("LatestSolver", () => {
  it("keeps one request in flight and answers only the latest of those that queue up", async () => {
    const calls: number[] = [];
    let release: (() => void) | null = null;
    const solver = new LatestSolver(async (doc) => {
      calls.push(doc.profile);
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return result({ dof: doc.profile });
    });
    const first = solver.request({ ...emptyDoc(), profile: 1 });
    const second = solver.request({ ...emptyDoc(), profile: 2 });
    const third = solver.request({ ...emptyDoc(), profile: 3 });
    expect(calls).toEqual([1]);
    release!();
    expect((await first)!.dof).toBe(1);
    expect(await second).toBeNull();
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
    release!();
    expect((await third)!.dof).toBe(3);
    expect(calls).toEqual([1, 3]);
  });
  it("turns a failing fetch into null", async () => {
    const solver = new LatestSolver(async () => {
      throw new Error("down");
    });
    expect(await solver.request(emptyDoc())).toBeNull();
  });
});
