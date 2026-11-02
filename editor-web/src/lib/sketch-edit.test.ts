import { describe, expect, it } from "vitest";

import { emptyDoc, entityHit, type SketchDoc } from "@/lib/sketch";
import { applyEdit, describeEdit, extendRequest, nearerEnd, pushHistory, trimRequest } from "@/lib/sketch-edit";

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
