import { describe, expect, it } from "vitest";

import { emptyDoc, entityHit, type Loop, type SketchDoc } from "@/lib/sketch";
import {
  applyEdit,
  cornerAt,
  cornerOfLines,
  cornerRequest,
  defaultCornerValue,
  describeEdit,
  extendRequest,
  isProjected,
  nearerEnd,
  parseCornerValue,
  projectRequest,
  projectSources,
  projectedCount,
  pushHistory,
  remapChoice,
  trimRequest,
} from "@/lib/sketch-edit";

const doc: SketchDoc = {
  ...emptyDoc("XY"),
  points: [
    { id: "p1", x: 0, y: 0 },
    { id: "p2", x: 10, y: 0 },
    { id: "p3", x: 5, y: -5 },
    { id: "p4", x: 5, y: 5 },
  ],
  entities: [
    { id: "l1", kind: "line", start: "p1", end: "p2" },
    { id: "l2", kind: "line", start: "p3", end: "p4" },
    { id: "c1", kind: "circle", center: "p1", radius: 3 },
  ],
};
const pts = new Map<string, [number, number]>(doc.points.map((p) => [p.id, [p.x, p.y]]));

describe("trimRequest", () => {
  it("names the entity and carries the click in sketch coordinates", () => {
    const request = trimRequest(doc, "l1", [8.5, 0.2]);
    expect(request).toEqual({ sketch: doc, op: "trim", args: { entity: "l1", at: [8.5, 0.2] } });
  });
  it("does not alias the click array", () => {
    const click: [number, number] = [1, 2];
    const request = trimRequest(doc, "l1", click);
    click[0] = 99;
    expect((request.args as { at: number[] }).at).toEqual([1, 2]);
  });
});

describe("nearerEnd / extendRequest", () => {
  it("picks the end nearer to the click", () => {
    expect(nearerEnd(doc, pts, "l1", [9, 1])).toBe("end");
    expect(nearerEnd(doc, pts, "l1", [1, 1])).toBe("start");
  });
  it("takes the start on a tie", () => expect(nearerEnd(doc, pts, "l1", [5, 3])).toBe("start"));
  it("has no end for a circle or an unknown id", () => {
    expect(nearerEnd(doc, pts, "c1", [3, 0])).toBeNull();
    expect(nearerEnd(doc, pts, "nope", [0, 0])).toBeNull();
    expect(extendRequest(doc, pts, "c1", [3, 0])).toBeNull();
  });
  it("builds the extend body", () => expect(extendRequest(doc, pts, "l2", [5, 4.5])).toEqual({ sketch: doc, op: "extend", args: { entity: "l2", end: "end" } }));
});

describe("entityHit", () => {
  it("answers entities only, never points", () => {
    expect(entityHit(doc, null, [0, 0.1], 0.5)?.kind).toBe("entity");
    expect(entityHit(doc, null, [20, 20], 0.5)).toBeNull();
  });
});

describe("applyEdit and history", () => {
  const response = { sketch: { ...doc, entities: doc.entities.slice(1) }, created: ["l9", "p9"] };
  it("adopts the returned document and flashes what was created", () => {
    const { doc: next, flash } = applyEdit(response);
    expect(next.entities.map((e) => e.id)).toEqual(["l2", "c1"]);
    expect(flash).toEqual(["l9", "p9"]);
  });
  it("pushes the previous document so that undo restores it", () => {
    const history = pushHistory([], doc);
    expect(history).toEqual([doc]);
    expect(history[history.length - 1]).toBe(doc);
  });
  it("keeps the history bounded", () => {
    let history: SketchDoc[] = [];
    for (let i = 0; i < 200; i++) history = pushHistory(history, doc, 80);
    expect(history.length).toBe(81);
  });
});

describe("describeEdit", () => {
  it("keeps the SDK notes visible", () => {
    const text = describeEdit("trim", { created: ["l9"], removed: ["l1"], changed: [], notes: ["cut between l2 and the wall"] });
    expect(text).toContain("created l9");
    expect(text).toContain("removed l1");
    expect(text).toContain("cut between l2 and the wall");
  });
  it("says so when nothing changed", () => expect(describeEdit("extend", { created: [], removed: [], changed: [], notes: [] })).toBe("extend: nothing changed"));
});

// A 20 x 10 rectangle (r1 bottom, r2 right, r3 top, r4 left), a stray line l9 off the corner p3 and a circle on p1.
const box: SketchDoc = {
  ...emptyDoc("XY"),
  points: [
    { id: "q1", x: 0, y: 0 },
    { id: "q2", x: 20, y: 0 },
    { id: "q3", x: 20, y: 10 },
    { id: "q4", x: 0, y: 10 },
    { id: "q5", x: 30, y: 10 },
  ],
  entities: [
    { id: "r1", kind: "line", start: "q1", end: "q2" },
    { id: "r2", kind: "line", start: "q2", end: "q3" },
    { id: "r3", kind: "line", start: "q3", end: "q4" },
    { id: "r4", kind: "line", start: "q4", end: "q1" },
    { id: "l9", kind: "line", start: "q3", end: "q5" },
    { id: "c9", kind: "circle", center: "q1", radius: 2 },
  ],
};
const boxPts = new Map<string, [number, number]>(box.points.map((p) => [p.id, [p.x, p.y]]));

describe("corners", () => {
  it("is a point shared by exactly two lines", () => {
    expect(cornerAt(box, "q1")).toEqual({ point: "q1", a: "r1", b: "r4" });
    expect(cornerAt(box, "q2")).toEqual({ point: "q2", a: "r1", b: "r2" });
  });
  it("is not a point with three lines, one line, or none", () => {
    expect(cornerAt(box, "q3")).toBeNull(); // r2, r3 and l9
    expect(cornerAt(box, "q5")).toBeNull();
    expect(cornerAt(box, "nope")).toBeNull();
  });
  it("is found from two lines in turn, in either order", () => {
    expect(cornerOfLines(box, "r1", "r2")).toEqual({ point: "q2", a: "r1", b: "r2" });
    expect(cornerOfLines(box, "r2", "r1")).toEqual({ point: "q2", a: "r2", b: "r1" });
  });
  it("is not found from lines that do not meet, the same line twice, or a circle", () => {
    expect(cornerOfLines(box, "r1", "r3")).toBeNull();
    expect(cornerOfLines(box, "r1", "r1")).toBeNull();
    expect(cornerOfLines(box, "r1", "c9")).toBeNull();
    expect(cornerOfLines(box, "r2", "l9")).toBeNull(); // they meet at q3, which has three lines
  });
});

describe("the value of a corner", () => {
  it("defaults to a tenth of the shorter line", () => {
    expect(defaultCornerValue(box, boxPts, { point: "q2", a: "r1", b: "r2" })).toBe(1); // r2 is 10 long
    expect(defaultCornerValue(box, boxPts, { point: "q1", a: "r1", b: "r4" })).toBe(1);
  });
  it("is zero when a line is unknown", () => expect(defaultCornerValue(box, boxPts, { point: "q1", a: "zz", b: "r4" })).toBe(0));
  it("parses a number above zero", () => {
    expect(parseCornerValue(" 4 ")).toBe(4);
    expect(parseCornerValue("0.75")).toBe(0.75);
    expect(parseCornerValue(".5")).toBe(0.5);
    for (const bad of ["", "0", "-3", "abc", "1,5", "NaN", "Infinity", "4mm"]) expect(parseCornerValue(bad)).toBeNull();
  });
});

describe("corner and project requests", () => {
  const corner = { point: "q2", a: "r1", b: "r2" };
  it("builds the fillet arguments from the two lines and the radius", () => {
    expect(cornerRequest("fillet_corner", box, corner, 4)).toEqual({ sketch: box, op: "fillet_corner", args: { a: "r1", b: "r2", radius: 4 } });
  });
  it("builds the chamfer arguments with a distance", () => {
    expect(cornerRequest("chamfer_corner", box, corner, 3)).toEqual({ sketch: box, op: "chamfer_corner", args: { a: "r1", b: "r2", distance: 3 } });
  });
  it("names the source sketch of a projection by its feature slug", () => {
    expect(projectRequest(box, "plate_sketch")).toEqual({ sketch: box, op: "project", args: { from_sketch: "plate_sketch" } });
  });
  it("offers the sketch features but the one being edited", () => {
    const row = (slug: string, spec: string | null) => ({ slug, gui: spec ? { spec, values: {}, picked: {} } : null });
    const rows = [row("sketch", "sketch"), row("sketch_2", "sketch"), row("extrude", "extrude"), row("raw", null)];
    expect(projectSources(rows, null)).toEqual(["sketch", "sketch_2"]);
    expect(projectSources(rows, "sketch")).toEqual(["sketch_2"]);
    expect(projectSources([row("extrude", "extrude")], null)).toEqual([]);
  });
});

describe("the answer of a corner or a projection", () => {
  const filleted: SketchDoc = {
    ...box,
    points: [...box.points, { id: "p_a", x: 16, y: 0 }, { id: "p_b", x: 20, y: 4 }],
    entities: [...box.entities, { id: "arc1", kind: "arc", center: "q2", start: "p_a", end: "p_b" }],
    profile: 0,
    inner: [],
  };
  it("adopts the document and flashes what was created", () => {
    const { doc: next, flash } = applyEdit({ sketch: filleted, created: ["arc1", "p_a", "p_b"] });
    expect(next.entities.map((e) => e.id)).toContain("arc1");
    expect(flash).toEqual(["arc1", "p_a", "p_b"]);
  });
  it("describes the projection with its count and source", () => {
    const projected: SketchDoc = {
      ...box,
      points: [...box.points, { id: "proj_s_1", x: 1, y: 1 }, { id: "proj_s_2", x: 5, y: 1 }],
      entities: [...box.entities, { id: "proj_s_3", kind: "line", start: "proj_s_1", end: "proj_s_2", construction: true }],
    };
    const created = ["proj_s_1", "proj_s_2", "proj_s_3"];
    const count = projectedCount(projected, created);
    expect(count).toEqual({ entities: 1, points: 2 });
    const text = describeEdit("project", { created, removed: [], changed: [], notes: ["reused none"] }, { ...count, from: "plate" });
    expect(text).toBe("project: 1 entity and 2 points from plate (construction, fixed). reused none");
  });
  it("counts only what this answer created", () => expect(projectedCount({ ...box, entities: [...box.entities, { id: "proj_s_3", kind: "line", start: "q1", end: "q2" }] }, [])).toEqual({ entities: 0, points: 0 }));
  it("recognises projected ids", () => {
    expect(isProjected("proj_s_3")).toBe(true);
    expect(isProjected("p3")).toBe(false);
  });
});

describe("the chosen profile across an edit", () => {
  const loop = (key: string, entities: string[]): Loop => ({ key, entities, polygon: [], area: 1, centroid: [0, 0], index: null });
  const before = [loop("r1+r2+r3+r4", ["r1", "r2", "r3", "r4"]), loop("c9", ["c9"])];
  const choice = { outer: "r1+r2+r3+r4", inner: ["c9"], chosen: true };
  it("keeps a loop whose key survives", () => {
    expect(remapChoice(before, choice, before)).toEqual(choice);
  });
  it("moves to the loop that replaces the old one (a fillet adds an arc and shortens two lines)", () => {
    const after = [loop("arc1+r1+r2+r3+r4", ["arc1", "r1", "r2", "r3", "r4"]), loop("c9", ["c9"])];
    expect(remapChoice(before, choice, after)).toEqual({ outer: "arc1+r1+r2+r3+r4", inner: ["c9"], chosen: true });
  });
  it("drops a loop with nothing left of it", () => {
    expect(remapChoice(before, choice, [loop("x+y", ["x", "y"])])).toEqual({ outer: null, inner: [], chosen: true });
  });
});
