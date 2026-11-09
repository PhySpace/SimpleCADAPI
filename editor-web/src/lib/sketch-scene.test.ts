import { describe, expect, it } from "vitest";

import type { FeatureRow } from "@/lib/features";
import { addCircle, addConstraint, addLine, emptyDoc, type SketchDoc, type SolveResult } from "@/lib/sketch";
import {
  SolveCache,
  defaultExtrudeDistance,
  docKey,
  hitSketches,
  nextSketchSelection,
  profileSummary,
  readHidden,
  sketchInfos,
  sketchShape,
  stableStringify,
  toggleHidden,
  writeHidden,
} from "@/lib/sketch-scene";

const rectDoc = (w: number, h: number, plane: SketchDoc["plane"] = "XY"): SketchDoc => {
  let doc = emptyDoc(plane);
  const corners: [number, number][] = [[0, 0], [w, 0], [w, h], [0, h]];
  doc = { ...doc, points: corners.map(([x, y], i) => ({ id: `p${i + 1}`, x, y })), entities: corners.map((_, i) => ({ id: `l${i + 1}`, kind: "line" as const, start: `p${i + 1}`, end: `p${((i + 1) % 4) + 1}` })) };
  return doc;
};

const row = (cell: string, slug: string, spec: string, values: Record<string, unknown>, makes: string[] = [slug]): FeatureRow =>
  ({ cell, index: 1, slug, role: "build", gui: { spec, values, picked: {} }, makes, reads: [], status: "ok", errors: [], params_cell: null }) as FeatureRow;

describe("the sketches of the notebook", () => {
  const features = [
    row("c1", "base", "sketch", { sketch: rectDoc(40, 20) }),
    row("c2", "pad", "extrude_sketch", { profile: "base", distance: 10 }, ["pad"]),
    row("c3", "top", "sketch", { sketch: rectDoc(10, 10) }),
    row("c4", "hole_cut", "cut_sketch", { profile: "top", body: "pad" }, ["hole_cut"]),
    row("c5", "block", "box", {}),
  ];
  const infos = sketchInfos(features);

  it("lists only the sketch features, in order", () => expect(infos.map((i) => i.name)).toEqual(["base", "top"]));
  it("knows which ones an extrude, revolve, cut or boss consumes", () => {
    expect(infos[0].usedBy).toEqual(["pad"]);
    expect(infos[1].usedBy).toEqual(["hole_cut"]);
    expect(sketchInfos([features[0]])[0].usedBy).toEqual([]);
  });
  it("keys the document so an unchanged one has the same key and a changed one another", () => {
    expect(infos[0].key).toBe(sketchInfos(features)[0].key);
    expect(infos[0].key).not.toBe(infos[1].key);
  });
});

describe("the solve cache", () => {
  const ok = (doc: SketchDoc): SolveResult => ({ ok: true, status: "solved", dof: doc.points.length, residual: 0, points: {}, scalars: {}, entities: {}, diagnostics: [], profiles: [], unusable: [] });

  it("is independent of key order", () => {
    expect(stableStringify({ b: 1, a: [2, { d: 1, c: 2 }] })).toBe(stableStringify({ a: [2, { c: 2, d: 1 }], b: 1 }));
    expect(docKey(rectDoc(40, 20))).toBe(docKey(JSON.parse(JSON.stringify(rectDoc(40, 20)))));
  });
  it("solves a document once and a changed one again", async () => {
    let calls = 0;
    const cache = new SolveCache(async (doc) => {
      calls += 1;
      return ok(doc);
    });
    const a = rectDoc(40, 20);
    const key = cache.request(a);
    cache.request(a);
    cache.request(JSON.parse(JSON.stringify(a)));
    expect(calls).toBe(1);
    expect(cache.get(key)?.state).toBe("pending");
    await Promise.resolve();
    await Promise.resolve();
    expect(cache.get(key)?.state).toBe("ok");
    cache.request(rectDoc(41, 20));
    expect(calls).toBe(2);
  });
  it("remembers a failure and tells the listeners", async () => {
    const cache = new SolveCache(async () => {
      throw new Error("boom");
    });
    let heard = 0;
    cache.subscribe(() => (heard += 1));
    const key = cache.request(rectDoc(1, 1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cache.get(key)).toEqual({ state: "failed", error: "boom" });
    expect(heard).toBe(1);
  });
  it("forgets the oldest beyond its limit", () => {
    const cache = new SolveCache(async (doc) => ok(doc), 2);
    const keys = [1, 2, 3].map((n) => cache.request(rectDoc(n, 1)));
    expect(cache.get(keys[0])).toBeUndefined();
    expect(cache.get(keys[2])).toBeDefined();
  });
});

describe("the shape of a sketch", () => {
  it("samples lines, circles and arcs, and fills the chosen profile", () => {
    const loop = { index: 0, id: "l1", kind: "edge_loop", closed: true, entity_ids: ["l1", "l2", "l3", "l4"], reversed: [false, false, false, false] };
    const shape = sketchShape(rectDoc(40, 20), { ok: true, status: "solved", dof: 0, residual: 0, points: {}, scalars: {}, entities: {}, diagnostics: [], profiles: [loop], unusable: [] });
    expect(shape.curves).toHaveLength(4);
    expect(shape.extent).toEqual({ min: [0, 0], max: [40, 20] });
    expect(shape.regions).toHaveLength(1);
    expect(shape.loopCount).toBe(1);
    const circle = addCircle(emptyDoc(), { x: 0, y: 0 }, { x: 5, y: 0 }, { auto: false, construction: false });
    expect(circle).not.toBeNull();
    const round = sketchShape(circle!.doc, null);
    expect(round.curves[0].uv.length).toBeGreaterThan(40);
    expect(round.extent?.max[0]).toBeCloseTo(5);
  });
  it("keeps construction geometry out of the extent and the fill", () => {
    const doc = rectDoc(10, 10);
    const withConstruction = { ...doc, points: [...doc.points, { id: "p9", x: -100, y: -100 }, { id: "p10", x: 100, y: 100 }], entities: [...doc.entities, { id: "l9", kind: "line" as const, start: "p9", end: "p10", construction: true }] };
    const shape = sketchShape(withConstruction, null);
    expect(shape.extent).toEqual({ min: [0, 0], max: [10, 10] });
    expect(shape.curves.find((c) => c.id === "l9")?.construction).toBe(true);
  });
  it("draws the seeds, flagged failed, when the solve failed", () => {
    const failed = { ok: false, status: "failed", dof: 0, residual: null, points: { p1: [500, 500] }, scalars: {}, entities: {}, diagnostics: [], profiles: [], unusable: [] } as SolveResult;
    const shape = sketchShape(rectDoc(40, 20), failed);
    expect(shape.failed).toBe(true);
    expect(shape.extent).toEqual({ min: [0, 0], max: [40, 20] });
  });
  it("uses the solved points over the seeds", () => {
    const solved = { ok: true, status: "solved", dof: 0, residual: 0, points: { p2: [60, 0], p3: [60, 20] }, scalars: {}, entities: {}, diagnostics: [], profiles: [], unusable: [] } as SolveResult;
    expect(sketchShape(rectDoc(40, 20), solved).extent?.max[0]).toBe(60);
  });
  it("needs a line to have been drawn for addLine to be used", () => {
    // addLine / addConstraint are imported by other suites; here they only guard the fixtures' shapes
    expect(typeof addLine).toBe("function");
    expect(typeof addConstraint).toBe("function");
  });
});

describe("the default extrude distance", () => {
  const shape = (w: number, h: number) => ({ extent: { min: [0, 0] as [number, number], max: [w, h] as [number, number] } });
  it("is a quarter of the largest extent, in a round number", () => {
    expect(defaultExtrudeDistance(shape(40, 20))).toBe(10);
    expect(defaultExtrudeDistance(shape(20, 100))).toBe(25);
    expect(defaultExtrudeDistance(shape(30, 10))).toBe(7.5);
    expect(defaultExtrudeDistance(shape(2, 2))).toBe(0.5);
  });
  it("falls back without an extent", () => {
    expect(defaultExtrudeDistance(null)).toBe(10);
    expect(defaultExtrudeDistance({ extent: null }, 5)).toBe(5);
    expect(defaultExtrudeDistance(shape(0, 0))).toBe(10);
  });
});

describe("the profile summary", () => {
  it("says nothing for a single loop and names the choice for several", () => {
    expect(profileSummary({ profile: 0, inner: [] }, 1)).toBeNull();
    expect(profileSummary({ profile: 0, inner: [1] }, 2)).toBe("outer: loop 1, holes: 1");
    expect(profileSummary({ profile: 1, inner: [] }, 3)).toBe("outer: loop 2, holes: 0");
  });
});

describe("hidden sketches are remembered per notebook", () => {
  const memory = () => {
    const data = new Map<string, string>();
    return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
  };
  it("round-trips, separately for each notebook", () => {
    const store = memory();
    writeHidden("a.py", new Set(["top", "base"]), store);
    writeHidden("b.py", new Set(["x"]), store);
    expect([...readHidden("a.py", store)].sort()).toEqual(["base", "top"]);
    expect([...readHidden("b.py", store)]).toEqual(["x"]);
    expect(readHidden("c.py", store).size).toBe(0);
  });
  it("survives blocked storage and garbage", () => {
    expect(readHidden("a", null).size).toBe(0);
    writeHidden("a", new Set(["x"]), null);
    const store = memory();
    store.setItem("sca.sketch.hidden:a", "{not json");
    expect(readHidden("a", store).size).toBe(0);
    store.setItem("sca.sketch.hidden:a", JSON.stringify(["ok", 3, null]));
    expect([...readHidden("a", store)]).toEqual(["ok"]);
  });
  it("toggles without touching the old set", () => {
    const a = new Set(["x"]);
    expect([...toggleHidden(a, "y")].sort()).toEqual(["x", "y"]);
    expect([...toggleHidden(a, "x")]).toEqual([]);
    expect([...a]).toEqual(["x"]);
  });
});

describe("the sketch selection shared by the tree and the viewport", () => {
  it("selects one on a plain click, toggles with Ctrl/Cmd, clears on nothing", () => {
    expect(nextSketchSelection([], "a", false)).toEqual(["a"]);
    expect(nextSketchSelection(["a"], "b", false)).toEqual(["b"]);
    expect(nextSketchSelection(["a"], "b", true)).toEqual(["a", "b"]);
    expect(nextSketchSelection(["a", "b"], "a", true)).toEqual(["b"]);
    expect(nextSketchSelection(["a", "b"], null, false)).toEqual([]);
    expect(nextSketchSelection(["a", "b"], null, true)).toEqual(["a", "b"]);
  });
});

describe("hitting a sketch in the viewport", () => {
  // an orthographic view straight down +z: the screen is (x, y)
  const project = (p: [number, number, number]): [number, number] => [p[0], p[1]];
  const square = (name: string, size: number) => ({
    name,
    curves: [[[0, 0, 0], [size, 0, 0], [size, size, 0], [0, size, 0], [0, 0, 0]] as [number, number, number][]],
    regions: [{ outer: [[0, 0, 0], [size, 0, 0], [size, size, 0], [0, size, 0]] as [number, number, number][], holes: [] }],
  });
  it("takes the nearest curve within the tolerance", () => {
    expect(hitSketches([square("a", 100)], project, 50, 3, 7)).toEqual({ name: "a", kind: "curve", distance: 3 });
    expect(hitSketches([square("a", 100)], project, 50, 20, 7)?.kind).toBe("region");
    expect(hitSketches([square("a", 100)], project, 200, 200, 7)).toBeNull();
  });
  it("prefers a curve to a region, and the smaller region among several", () => {
    const big = square("big", 100);
    const small = square("small", 30);
    expect(hitSketches([big, small], project, 10, 10, 7)?.name).toBe("small"); // nearest of the two corners' edges is ambiguous: both within tol
    expect(hitSketches([big, small], project, 20, 20, 7)).toEqual({ name: "small", kind: "region", distance: 0 });
    expect(hitSketches([big, small], project, 60, 60, 7)?.name).toBe("big");
  });
  it("leaves a hole of the profile unpickable by its fill", () => {
    const ring = { name: "ring", curves: [], regions: [{ outer: square("o", 100).regions[0].outer, holes: [square("h", 40).regions[0].outer.map((p) => [p[0] + 30, p[1] + 30, 0] as [number, number, number])] }] };
    expect(hitSketches([ring], project, 50, 50, 7)).toBeNull();
    expect(hitSketches([ring], project, 10, 50, 7)?.name).toBe("ring");
  });
  it("ignores points behind the camera", () => {
    expect(hitSketches([square("a", 100)], () => null, 50, 3, 7)).toBeNull();
  });
});
