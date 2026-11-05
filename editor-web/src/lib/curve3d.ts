/** Drawing a 3D curve in the viewport: the document the `curve` feature takes (points in space, on workplanes, at model
 * vertices or at the ends of other curves; lines, arcs and splines that follow one another), what the pointer snaps to,
 * and the shape drawn while drawing.  A path drawn in one go becomes one curve feature per line, arc or spline (each an
 * edge), each starting at the end of the one before (see splitPath).  Pure: no React, no three.js.  World coordinates are
 * CAD mm, Z up. */

import { add, cross, dot, length, scale, sub, unit, type Vec3 } from "@/lib/sketch-plane";

export type CurveKind = "line" | "arc" | "spline";

/** Where another curve of the notebook starts or ends (a point there follows it). */
export type CurveEnd = { curve: string; end: "start" | "end" };

/** A point of the document: `at` (world mm) always (a hint for vertices and workplane points), `on` + `uv` for a point
 * drawn on a workplane variable, `entity_id` for one snapped to a model vertex (the server names it by its reference),
 * `end_of` for one at an end of another curve. */
export type CurvePoint = { id: string; at: Vec3; on?: string; uv?: [number, number]; entity_id?: string; end_of?: CurveEnd };
export type CurveSegment = { id: string; kind: CurveKind; points: string[] };
export type CurveDoc = { points: CurvePoint[]; curves: CurveSegment[] };

/** A drawing plane: a named plane or a workplane, its frame in world mm. */
export type DrawPlane = { name: string; workplane: boolean; origin: Vec3; x_axis: Vec3; y_axis: Vec3; normal: Vec3 };

/** Something the pointer can snap to. `screen` is where it is drawn (CSS px), `priority` breaks ties (lower wins). */
export type SnapCandidate = {
  kind: "vertex" | "midpoint" | "point" | "origin" | "grid";
  at: Vec3;
  screen: [number, number];
  entityId?: string;
  pointId?: string;
  /** For a workplane's origin: the workplane, so the point is kept on it. */
  workplane?: string;
  /** For an end of another curve: which, so the point is kept at it. */
  endOf?: CurveEnd;
  label: string;
  priority: number;
};

export const SNAP_PX = 14;

/** The candidate nearest the pointer within `radius` px (ties by priority), or null. */
export function pickSnap(candidates: readonly SnapCandidate[], pointer: [number, number], radius = SNAP_PX): SnapCandidate | null {
  let best: SnapCandidate | null = null;
  let bestScore = Infinity;
  for (const c of candidates) {
    const d = Math.hypot(c.screen[0] - pointer[0], c.screen[1] - pointer[1]);
    if (d > radius) continue;
    const score = d + c.priority * 4; // a vertex 4 px further still beats a grid point
    if (score < bestScore) {
      best = c;
      bestScore = score;
    }
  }
  return best;
}

/** Where a ray meets the plane, or null when it runs along it. */
export function rayOnPlane(origin: Vec3, direction: Vec3, plane: DrawPlane): Vec3 | null {
  const denom = dot(direction, plane.normal);
  if (Math.abs(denom) < 1e-9) return null;
  const t = dot(sub(plane.origin, origin), plane.normal) / denom;
  return t < 0 ? null : add(origin, scale(direction, t));
}

/** The plane coordinates (u, v) of a world point (projected onto the plane). */
export function planeUV(plane: DrawPlane, p: Vec3): [number, number] {
  const d = sub(p, plane.origin);
  return [dot(d, plane.x_axis), dot(d, plane.y_axis)];
}

export function planePoint(plane: DrawPlane, u: number, v: number): Vec3 {
  return add(plane.origin, add(scale(plane.x_axis, u), scale(plane.y_axis, v)));
}

/** A grid step for the plane: 1, 2 or 5 times a power of ten mm, about `targetMm` across. */
export function gridStep(targetMm: number): number {
  const power = 10 ** Math.floor(Math.log10(Math.max(targetMm, 1e-6)));
  for (const k of [1, 2, 5, 10]) if (k * power >= targetMm) return k * power;
  return 10 * power;
}

/** The point snapped to the plane's grid (in its own u, v). */
export function onGrid(plane: DrawPlane, p: Vec3, step: number): Vec3 {
  const [u, v] = planeUV(plane, p);
  return planePoint(plane, Math.round(u / step) * step, Math.round(v / step) * step);
}

/** Points along a circle arc through a, m, b (world mm); the straight segment when they are (nearly) on one line. */
export function arcPoints(a: Vec3, m: Vec3, b: Vec3, steps = 48): Vec3[] {
  const ab = sub(b, a);
  const am = sub(m, a);
  const n = cross(ab, am);
  const nn = dot(n, n);
  if (nn < 1e-12 * Math.max(dot(ab, ab), 1) ** 2) return [a, b];
  // circumcentre of the triangle a, m, b
  const center = add(a, scale(add(scale(cross(n, ab), dot(am, am)), scale(cross(am, n), dot(ab, ab))), 1 / (2 * nn)));
  const ra = sub(a, center);
  const radius = length(ra);
  const e1 = unit(ra)!;
  const e2 = unit(cross(unit(n)!, e1))!;
  const angle = (p: Vec3) => {
    const d = sub(p, center);
    const t = Math.atan2(dot(d, e2), dot(d, e1));
    return t < 0 ? t + 2 * Math.PI : t;
  };
  const tm = angle(m);
  const tb = angle(b);
  // a is at 0; go the way that passes m
  const sweep = tm <= tb ? tb : tb - 2 * Math.PI;
  return Array.from({ length: steps + 1 }, (_, i) => {
    const t = (sweep * i) / steps;
    return add(center, add(scale(e1, radius * Math.cos(t)), scale(e2, radius * Math.sin(t))));
  });
}

/** Points along a smooth curve through `points` (centripetal Catmull-Rom): what a spline looks like while it is drawn
 * (the kernel's interpolation is close to it; the curve made is the kernel's). */
export function splinePoints(points: readonly Vec3[], perSpan = 16): Vec3[] {
  if (points.length < 3) return [...points];
  const out: Vec3[] = [];
  const at = (i: number) => points[Math.max(0, Math.min(points.length - 1, i))];
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = i === 0 ? sub(scale(at(0), 2), at(1)) : at(i - 1);
    const p1 = at(i);
    const p2 = at(i + 1);
    const p3 = i + 2 >= points.length ? sub(scale(at(points.length - 1), 2), at(points.length - 2)) : at(i + 2);
    const t0 = 0;
    const t1 = t0 + Math.sqrt(Math.max(length(sub(p1, p0)), 1e-9));
    const t2 = t1 + Math.sqrt(Math.max(length(sub(p2, p1)), 1e-9));
    const t3 = t2 + Math.sqrt(Math.max(length(sub(p3, p2)), 1e-9));
    for (let k = 0; k < perSpan; k++) {
      const t = t1 + ((t2 - t1) * k) / perSpan;
      const lerp = (a: Vec3, b: Vec3, ta: number, tb: number) => add(scale(a, (tb - t) / (tb - ta)), scale(b, (t - ta) / (tb - ta)));
      const a1 = lerp(p0, p1, t0, t1);
      const a2 = lerp(p1, p2, t1, t2);
      const a3 = lerp(p2, p3, t2, t3);
      const b1 = lerp(a1, a2, t0, t2);
      const b2 = lerp(a2, a3, t1, t3);
      out.push(lerp(b1, b2, t1, t2));
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

/** The polyline a segment is drawn as. */
export function segmentPoints(kind: CurveKind, points: readonly Vec3[]): Vec3[] {
  if (kind === "arc" && points.length === 3) return arcPoints(points[0], points[1], points[2]);
  if (kind === "spline") return splinePoints(points);
  return [...points];
}

/** The world point of a document point. */
export const pointAt = (doc: CurveDoc, id: string): Vec3 | null => doc.points.find((p) => p.id === id)?.at ?? null;

/** The next free point id ("p1", "p2" ...) or curve id ("c1" ...). */
export function nextId(taken: readonly string[], prefix: string): string {
  let n = 1;
  while (taken.includes(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

/** The document's point for a place the pointer chose: the snapped session point itself, a model vertex (named later by
 * the server), a point on a workplane (u, v: it follows the workplane), or a point in space. */
export function pointFor(doc: CurveDoc, plane: DrawPlane, at: Vec3, snap: SnapCandidate | null): { doc: CurveDoc; id: string } {
  if (snap?.pointId) return { doc, id: snap.pointId };
  const id = nextId(doc.points.map((p) => p.id), "p");
  let point: CurvePoint = { id, at };
  if (snap?.kind === "vertex" && snap.entityId) point = { id, at, entity_id: snap.entityId };
  else if (snap?.kind === "origin" && snap.workplane) point = { id, at, on: snap.workplane, uv: [0, 0] };
  else if (snap?.endOf) point = { id, at, end_of: snap.endOf };
  else if (plane.workplane && (!snap || snap.kind === "grid")) point = { id, at, on: plane.name, uv: planeUV(plane, at) };
  return { doc: { ...doc, points: [...doc.points, point] }, id };
}

/** The document with one more segment from the path's end through `ids`, and the points it no longer uses dropped. */
export function addSegment(doc: CurveDoc, kind: CurveKind, ids: string[]): CurveDoc {
  const id = nextId(doc.curves.map((c) => c.id), "c");
  return { ...doc, curves: [...doc.curves, { id, kind, points: ids }] };
}

/** The path's last point id (where the next segment starts), or null before the first segment. */
export const pathEnd = (doc: CurveDoc): string | null => doc.curves.at(-1)?.points.at(-1) ?? null;

/** The document without its last segment, and without the points only that segment used. */
export function dropLast(doc: CurveDoc): CurveDoc {
  const curves = doc.curves.slice(0, -1);
  const used = new Set(curves.flatMap((c) => c.points));
  const first = doc.curves[0]?.points[0];
  if (curves.length === 0 && first) used.add(first);
  return { points: doc.points.filter((p) => used.has(p.id)), curves };
}

/** The documents of a path drawn in one go, one per line, arc or spline (each feature is one edge), named `names` in order:
 * a curve that starts where the one before it ends starts at its end (`end_of`), and a path closed on its first point
 * ends at the first curve's start, so the curves stay joined when one of them changes. */
export function splitPath(doc: CurveDoc, names: readonly string[]): CurveDoc[] {
  const first = doc.curves[0]?.points[0];
  return doc.curves.map((curve, index) => {
    const previous = doc.curves[index - 1];
    const points = curve.points.map((id, at) => {
      const point = doc.points.find((p) => p.id === id) as CurvePoint;
      if (at === 0 && previous && previous.points.at(-1) === id) return { id, at: point.at, end_of: { curve: names[index - 1], end: "end" as const } };
      if (at === curve.points.length - 1 && index > 0 && id === first) return { id, at: point.at, end_of: { curve: names[0], end: "start" as const } };
      return point;
    });
    const unique = points.filter((point, at) => points.findIndex((p) => p.id === point.id) === at);
    return { points: unique, curves: [{ ...curve, id: "c1" }] };
  });
}
