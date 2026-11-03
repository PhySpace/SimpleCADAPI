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
