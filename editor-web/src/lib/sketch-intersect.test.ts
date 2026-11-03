import { describe, expect, it } from "vitest";

import { addCircle, addLine, emptyDoc, ensurePoint, type SketchDoc } from "@/lib/sketch";
import { findIntersections } from "@/lib/sketch-intersect";

const opts = { auto: false, construction: false };
const line = (doc: SketchDoc, a: [number, number], b: [number, number]) => {
  const start = ensurePoint(doc, { x: a[0], y: a[1] });
  return addLine(start.doc, start.id, { x: b[0], y: b[1] }, opts)!.doc;
};

describe("crossings of the sketch's curves", () => {
  it("finds where two lines cross, and not where they only would", () => {
    let doc = line(emptyDoc(), [-10, 0], [10, 0]);
    doc = line(doc, [0, -5], [0, 5]);
    expect(findIntersections(doc, null)).toEqual([[0, 0]]);
    expect(findIntersections(line(line(emptyDoc(), [-10, 0], [10, 0]), [0, 5], [0, 9]), null)).toEqual([]);
  });
  it("finds a line through a circle twice, and none where a shared point already is", () => {
    const circle = addCircle(emptyDoc(), { x: 0, y: 0 }, { x: 5, y: 0 }, opts)!.doc;
    const crossing = findIntersections(line(circle, [-10, 0], [10, 0]), null);
    expect(crossing).toHaveLength(2);
    expect(crossing.map((p) => Math.round(p[0])).sort((a, b) => a - b)).toEqual([-5, 5]);
    // a line that ends on the circle with a point there: that point is the crossing already
    const ends = line(circle, [0, 0], [5, 0]);
    expect(findIntersections(ends, null)).toEqual([]);
  });
  it("finds two circles crossing, and ignores construction geometry", () => {
    let doc = addCircle(emptyDoc(), { x: 0, y: 0 }, { x: 5, y: 0 }, opts)!.doc;
    doc = addCircle(doc, { x: 6, y: 0 }, { x: 11, y: 0 }, opts)!.doc;
    expect(findIntersections(doc, null)).toHaveLength(2);
    const construction = { ...doc, entities: doc.entities.map((e) => (e.kind === "circle" ? { ...e, construction: true } : e)) };
    expect(findIntersections(construction, null)).toEqual([]);
  });
});

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
