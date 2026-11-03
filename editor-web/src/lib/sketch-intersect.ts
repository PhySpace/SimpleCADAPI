/** Where the curves of a sketch cross: display and snapping only (the sketch's geometry stays the SDK's; a crossing becomes a point
 * of the sketch only when a person constrains to it, or trims at it, which the SDK does). */

import { arcSweep, circleRadius, solvedPoints, type SketchDoc, type SolveResult } from "@/lib/sketch";

type P = [number, number];
type Curve =
  | { kind: "line"; id: string; a: P; b: P }
  | { kind: "circle"; id: string; c: P; r: number }
  | { kind: "arc"; id: string; c: P; r: number; a0: number; sweep: number };

const EPS = 1e-9;

function curvesOf(doc: SketchDoc, solve: SolveResult | null): Curve[] {
  const pts = solvedPoints(doc, solve);
  const out: Curve[] = [];
  for (const e of doc.entities) {
    if (e.construction) continue;
    if (e.kind === "line") {
      const a = pts.get(e.start ?? "");
      const b = pts.get(e.end ?? "");
      if (a && b && Math.hypot(a[0] - b[0], a[1] - b[1]) > EPS) out.push({ kind: "line", id: e.id, a, b });
    } else if (e.kind === "circle") {
      const c = pts.get(e.center ?? "");
      const r = c ? circleRadius(doc, e, pts, solve) : 0;
      if (c && r > 0) out.push({ kind: "circle", id: e.id, c, r });
    } else if (e.kind === "arc") {
      const c = pts.get(e.center ?? "");
      const s = pts.get(e.start ?? "");
      const t = pts.get(e.end ?? "");
      if (c && s && t) out.push({ kind: "arc", id: e.id, c, r: Math.hypot(s[0] - c[0], s[1] - c[1]), a0: Math.atan2(s[1] - c[1], s[0] - c[0]), sweep: arcSweep(c, s, t) });
    }
  }
  return out;
}

const onArc = (arc: Extract<Curve, { kind: "arc" }>, p: P): boolean => {
  let d = Math.atan2(p[1] - arc.c[1], p[0] - arc.c[0]) - arc.a0;
  while (d < -1e-9) d += 2 * Math.PI;
  while (d > 2 * Math.PI + 1e-9) d -= 2 * Math.PI;
  return d <= arc.sweep + 1e-9;
};

/** Candidate crossings of the full curves (a line as its infinite line; an arc as its full circle), with the parameter on a segment. */
function lineLine(a: Extract<Curve, { kind: "line" }>, b: Extract<Curve, { kind: "line" }>): P[] {
  const d1: P = [a.b[0] - a.a[0], a.b[1] - a.a[1]];
  const d2: P = [b.b[0] - b.a[0], b.b[1] - b.a[1]];
  const den = d1[0] * d2[1] - d1[1] * d2[0];
  if (Math.abs(den) < EPS * Math.hypot(...d1) * Math.hypot(...d2)) return [];
  const t = ((b.a[0] - a.a[0]) * d2[1] - (b.a[1] - a.a[1]) * d2[0]) / den;
  const u = ((b.a[0] - a.a[0]) * d1[1] - (b.a[1] - a.a[1]) * d1[0]) / den;
  if (t < -1e-9 || t > 1 + 1e-9 || u < -1e-9 || u > 1 + 1e-9) return [];
  return [[a.a[0] + t * d1[0], a.a[1] + t * d1[1]]];
}

function lineCircle(line: Extract<Curve, { kind: "line" }>, c: P, r: number): P[] {
  const d: P = [line.b[0] - line.a[0], line.b[1] - line.a[1]];
  const f: P = [line.a[0] - c[0], line.a[1] - c[1]];
  const A = d[0] * d[0] + d[1] * d[1];
  const B = 2 * (f[0] * d[0] + f[1] * d[1]);
  const C = f[0] * f[0] + f[1] * f[1] - r * r;
  const disc = B * B - 4 * A * C;
  if (disc < -1e-9 * A * r * r) return [];
  const root = Math.sqrt(Math.max(disc, 0));
  const hits: P[] = [];
  for (const t of disc <= 1e-12 ? [-B / (2 * A)] : [(-B - root) / (2 * A), (-B + root) / (2 * A)]) {
    if (t >= -1e-9 && t <= 1 + 1e-9) hits.push([line.a[0] + t * d[0], line.a[1] + t * d[1]]);
  }
  return hits;
}

function circleCircle(c1: P, r1: number, c2: P, r2: number): P[] {
  const d = Math.hypot(c2[0] - c1[0], c2[1] - c1[1]);
  if (d < EPS || d > r1 + r2 + 1e-9 || d < Math.abs(r1 - r2) - 1e-9) return [];
  const a = (r1 * r1 - r2 * r2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(r1 * r1 - a * a, 0));
  const mid: P = [c1[0] + (a * (c2[0] - c1[0])) / d, c1[1] + (a * (c2[1] - c1[1])) / d];
  if (h < 1e-9) return [mid];
  const ox = (h * (c2[1] - c1[1])) / d;
  const oy = (h * (c2[0] - c1[0])) / d;
  return [[mid[0] + ox, mid[1] - oy], [mid[0] - ox, mid[1] + oy]];
}

/** The crossings of the sketch's curves that are not already one of its points (within `tol`), each once. */
export function findIntersections(doc: SketchDoc, solve: SolveResult | null, tol = 1e-3): P[] {
  const curves = curvesOf(doc, solve);
  const pts = [...solvedPoints(doc, solve).values()];
  const found: P[] = [];
  const keep = (p: P) => {
    if (pts.some((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) <= tol)) return;
    if (found.some((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) <= tol)) return;
    found.push(p);
  };
  for (let i = 0; i < curves.length; i++) {
    for (let j = i + 1; j < curves.length; j++) {
      const a = curves[i];
      const b = curves[j];
      let hits: P[] = [];
      if (a.kind === "line" && b.kind === "line") hits = lineLine(a, b);
      else if (a.kind === "line") hits = lineCircle(a, (b as Exclude<Curve, { kind: "line" }>).c, (b as Exclude<Curve, { kind: "line" }>).r).filter((p) => b.kind !== "arc" || onArc(b, p));
      else if (b.kind === "line") hits = lineCircle(b, a.c, a.r).filter((p) => a.kind !== "arc" || onArc(a, p));
      else hits = circleCircle(a.c, a.r, b.c, b.r).filter((p) => (a.kind !== "arc" || onArc(a, p)) && (b.kind !== "arc" || onArc(b, p)));
      hits.forEach(keep);
    }
  }
  return found;
}
