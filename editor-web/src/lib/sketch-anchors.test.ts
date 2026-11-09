import { describe, expect, it } from "vitest";

import { emptyDoc, normalizeDoc, wireProfiles, type SketchDoc, type SolveResult } from "@/lib/sketch";
import { addPenSpline, anchorAction, anchorRoles, bezierPath, curveAt, handlePoints, isAnchorSpline, isSmooth, mirrorHandle, penPoles, shownHandles, smoothAnchors } from "@/lib/sketch-anchors";
import { convertSplineRequest, insertAnchorRequest, removeAnchorRequest } from "@/lib/sketch-edit";

const opts = { auto: false, construction: false };
const at = (spot: { x: number; y: number }): [number, number] => [spot.x, spot.y];

describe("the pen tool makes B-splines in anchor form", () => {
  it("three clicks: anchors with a handle on each side, knots 0..n, inner multiplicities 3", () => {
    const made = addPenSpline(emptyDoc(), [{ spot: { x: 0, y: 0 } }, { spot: { x: 10, y: 10 } }, { spot: { x: 20, y: 0 } }], false, opts, at)!;
    const spline = made.doc.entities[0];
    expect(spline).toMatchObject({ kind: "bspline", degree: 3, knots: [0, 1, 2], multiplicities: [4, 3, 4] });
    expect(spline.control_points).toHaveLength(7);
    expect(spline.start).toBe(spline.control_points![0]);
    expect(spline.end).toBe(spline.control_points![6]);
    expect(isAnchorSpline(spline)).toBe(true);
    // the middle anchor is smooth: its handles lie on one line through it (Catmull-Rom tangent, a sixth of the neighbours' span)
    const p = new Map(made.doc.points.map((q) => [q.id, [q.x, q.y] as [number, number]]));
    const [, , inH, mid, outH] = spline.control_points!.map((id) => p.get(id)!);
    expect(mid).toEqual([10, 10]);
    expect(inH).toEqual([10 - 20 / 6, 10].map((v) => Math.round(v * 1e4) / 1e4));
    expect(isSmooth(mid, inH, outH)).toBe(true);
  });

  it("a dragged anchor has the symmetric handles of the drag; a closed path returns to its first anchor", () => {
    const poles = penPoles([[0, 0], [10, 0]], [[2, 3], null], false);
    expect(poles[1]).toEqual([2, 3]);
    const made = addPenSpline(emptyDoc(), [{ spot: { x: 0, y: 0 }, handle: [0, 4] }, { spot: { x: 10, y: 0 } }, { spot: { x: 5, y: 8 } }], true, opts, at)!;
    const spline = made.doc.entities[0];
    const ids = spline.control_points!;
    expect(ids).toHaveLength(10); // three spans
    expect(ids[0]).toBe(ids[9]);
    expect(spline.multiplicities).toEqual([4, 3, 3, 4]);
    const p = new Map(made.doc.points.map((q) => [q.id, [q.x, q.y]]));
    expect(p.get(ids[1])).toEqual([0, 4]); // the out-handle of the first anchor
    expect(p.get(ids[8])).toEqual([0, -4]); // and its in-handle, at the end of the closing span
    expect(addPenSpline(emptyDoc(), [{ spot: { x: 0, y: 0 } }], false, opts, at)).toBeNull();
  });

  it("the drawn path passes through the anchors", () => {
    const path = bezierPath([[0, 0], [0, 5], [10, 5], [10, 0], [10, -5], [20, -5], [20, 0]], 8);
    expect(path[0]).toEqual([0, 0]);
    expect(path[8]).toEqual([10, 0]);
    expect(path[16]).toEqual([20, 0]);
  });
});

function twoSpans(): SketchDoc {
  return addPenSpline(emptyDoc(), [{ spot: { x: 0, y: 0 } }, { spot: { x: 10, y: 10 } }, { spot: { x: 20, y: 0 } }], false, opts, at)!.doc;
}

describe("anchors and handles of a spline", () => {
  it("each point knows its role; only the picked spline shows its handles", () => {
    const doc = twoSpans();
    const ids = doc.entities[0].control_points!;
    const roles = anchorRoles(doc);
    expect(roles.get(ids[3])).toMatchObject({ kind: "anchor", handles: [ids[2], ids[4]], end: false });
    expect(roles.get(ids[0])).toMatchObject({ kind: "anchor", handles: [ids[1]], end: true });
    expect(roles.get(ids[2])).toMatchObject({ kind: "handle", anchor: ids[3], other: ids[4] });
    expect(roles.get(ids[1])).toMatchObject({ kind: "handle", anchor: ids[0], other: undefined });
    expect([...handlePoints(roles)].sort()).toEqual([ids[1], ids[2], ids[4], ids[5]].sort());
    expect(shownHandles(doc, []).size).toBe(0);
    expect(shownHandles(doc, [doc.entities[0].id]).size).toBe(4);
    expect(shownHandles(doc, [ids[3]]).size).toBe(4); // an anchor of it
  });

  it("a control-point B-spline (an old file, or a single span with uniform knots) is told apart", () => {
    expect(isAnchorSpline({ id: "s", kind: "bspline", degree: 3, control_points: ["a", "b", "c", "d"] })).toBe(true);
    expect(isAnchorSpline({ id: "s", kind: "bspline", degree: 3, control_points: ["a", "b", "c", "d", "e"] })).toBe(false);
    expect(isAnchorSpline({ id: "s", kind: "bspline", degree: 2, control_points: ["a", "b", "c"] })).toBe(false);
    expect(isAnchorSpline({ id: "s", kind: "bspline", degree: 3, control_points: Array(7).fill("p"), knots: [0, 0.5, 1], multiplicities: [4, 3, 4] })).toBe(true);
    expect(isAnchorSpline({ id: "s", kind: "bspline", degree: 3, control_points: Array(7).fill("p"), knots: [0, 0.3, 0.6, 1], multiplicities: [4, 1, 2, 4] })).toBe(false);
  });

  it("dragging a handle of a smooth anchor turns the opposite handle, which keeps its own length", () => {
    expect(mirrorHandle([0, 0], [3, 4], 10)).toEqual([-6, -8]);
    expect(mirrorHandle([0, 0], [0, 0], 10)).toBeNull();
    expect(isSmooth([0, 0], [-1, 0], [5, 0])).toBe(true);
    expect(isSmooth([0, 0], [-1, 0], [5, 1])).toBe(false);
  });

  it("S smooths a corner: both handles on one line, each keeping its length", () => {
    const doc = twoSpans();
    const ids = doc.entities[0].control_points!;
    const pts = new Map(doc.points.map((p) => [p.id, [p.x, p.y] as [number, number]]));
    pts.set(ids[2], [10, 15]); // a corner: the in-handle straight above the anchor
    pts.set(ids[4], [15, 10]); // the out-handle to the right
    const moved = smoothAnchors(doc, [ids[3]], pts);
    expect(isSmooth([10, 10], moved[ids[2]], moved[ids[4]])).toBe(true);
    expect(Math.hypot(moved[ids[2]][0] - 10, moved[ids[2]][1] - 10)).toBeCloseTo(5, 3);
    expect(smoothAnchors(doc, [ids[0]], pts)).toEqual({}); // an end anchor has one handle
  });
});

describe("anchor edits are SDK requests; a wire sketch chooses any profile", () => {
  it("requests name the spline and the place or the anchor", () => {
    const doc = twoSpans();
    expect(insertAnchorRequest(doc, "s1", [4, 5])).toEqual({ sketch: doc, op: "insert_spline_anchor", args: { spline: "s1", at: [4, 5] } });
    expect(removeAnchorRequest(doc, "s1", "p4").args).toEqual({ spline: "s1", anchor: "p4" });
    expect(convertSplineRequest(doc, "s1").op).toBe("convert_spline_to_anchors");
  });

  it("the output is kept only when it is a wire; open chains are wire profiles", () => {
    expect(normalizeDoc({ output: "wire" }).output).toBe("wire");
    expect("output" in normalizeDoc({ output: "face" })).toBe(false);
    const solve = { profiles: [{ index: 0, id: "l0", kind: "edge_chain", closed: false, entity_ids: ["l1", "l0"], reversed: [false, false] }] } as unknown as SolveResult;
    expect(wireProfiles(solve)).toEqual([{ index: 0, key: "l0+l1", closed: false, entities: ["l1", "l0"] }]);
  });
});

/** Two spans along the x axis (anchors at 0, 15 and 30; the handles on the axis too), so its path is the x axis from 0 to 30. */
function straight(): SketchDoc {
  return addPenSpline(emptyDoc(), [{ spot: { x: 0, y: 0 }, handle: [5, 0] }, { spot: { x: 15, y: 0 }, handle: [5, 0] }, { spot: { x: 30, y: 0 }, handle: [5, 0] }], false, opts, at)!.doc;
}

describe("adding and removing anchors by clicking", () => {
  it("a place on an anchor-form curve is found within the pick distance", () => {
    const doc = straight();
    expect(curveAt(doc, null, [7, 0.5], 1)).toEqual({ spline: "s1", at: [7, 0] });
    expect(curveAt(doc, null, [7, 3], 1)).toBeNull();
    // a control-point B-spline offers no place for an anchor
    const old: SketchDoc = { ...doc, entities: [{ ...doc.entities[0], knots: [0, 0.3, 0.6, 1], multiplicities: [4, 1, 2, 4] }] };
    expect(curveAt(old, null, [7, 0.5], 1)).toBeNull();
  });

  it("anchor mode: an inner anchor is removed, the curve gets an anchor, an end anchor or a handle is refused", () => {
    const doc = straight();
    const ids = doc.entities[0].control_points!;
    expect(anchorAction(doc, null, [15, 0], 1, ids[3])).toEqual({ kind: "remove", spline: "s1", anchor: ids[3] });
    expect(anchorAction(doc, null, [22, 0.2], 1, null)).toEqual({ kind: "add", spline: "s1", at: [22, 0] });
    expect(anchorAction(doc, null, [0, 0], 1, ids[0])).toMatchObject({ kind: "refuse" });
    expect(anchorAction(doc, null, [9, 5], 1, null)).toBeNull();
  });
});
