/** What a set of picked curves is, for the surfaces they can make: a closed loop (a patch fills it; a flat one is a
 * plane), and a network of two families that cross each other (a Gordon surface interpolates it).  Pure: the curves
 * are the kernel's samples (components/CurveLines.tsx), world mm. */

import type { Vec3 } from "@/lib/sketch-plane";

export type NetCurve = { name: string; edges: Vec3[][] };

const distance = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** A length for "the same point": a thousandth of the curves' extent (at least a micron). */
export function netTolerance(curves: readonly NetCurve[]): number {
  const points = curves.flatMap((curve) => curve.edges.flat());
  if (!points.length) return 1e-3;
  const low = [0, 1, 2].map((i) => Math.min(...points.map((p) => p[i])));
  const high = [0, 1, 2].map((i) => Math.max(...points.map((p) => p[i])));
  return Math.max(Math.hypot(high[0] - low[0], high[1] - low[1], high[2] - low[2]) * 1e-3, 1e-3);
}

const ends = (curve: NetCurve): [Vec3, Vec3] => {
  const first = curve.edges[0];
  const last = curve.edges[curve.edges.length - 1];
  return [first[0], last[last.length - 1]];
};

/** The curves joined end to end into one closed loop (each end meets exactly one end of another curve, or a single
 * curve closes on itself), in loop order; null otherwise. */
export function closedLoop(curves: readonly NetCurve[], tolerance = netTolerance(curves)): NetCurve[] | null {
  if (!curves.length) return null;
  if (curves.length === 1) {
    const [a, b] = ends(curves[0]);
    return distance(a, b) <= tolerance ? [...curves] : null;
  }
  const order = [curves[0]];
  const used = new Set([0]);
  let tip = ends(curves[0])[1];
  while (order.length < curves.length) {
    const next = curves.findIndex((curve, i) => !used.has(i) && ends(curve).some((p) => distance(p, tip) <= tolerance));
    if (next < 0) return null;
    used.add(next);
    order.push(curves[next]);
    const [a, b] = ends(curves[next]);
    tip = distance(a, tip) <= tolerance ? b : a;
  }
  return distance(tip, ends(curves[0])[0]) <= tolerance ? order : null;
}

/** The unit normal of the plane a closed loop lies in (Newell's method over its samples), or null when the loop is
 * not flat (a point is off the plane by more than the tolerance) or encloses no area. */
export function loopNormal(loop: readonly NetCurve[], tolerance = netTolerance(loop)): Vec3 | null {
  const points = loop.flatMap((curve) => curve.edges.flat());
  const n: Vec3 = [0, 0, 0];
  for (let i = 0; i < points.length; i++) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    n[0] += (a[1] - b[1]) * (a[2] + b[2]);
    n[1] += (a[2] - b[2]) * (a[0] + b[0]);
    n[2] += (a[0] - b[0]) * (a[1] + b[1]);
  }
  const length = Math.hypot(...n);
  if (length < 1e-12) return null;
  const unit: Vec3 = [n[0] / length, n[1] / length, n[2] / length];
  const origin = points[0];
  const off = (p: Vec3) => Math.abs((p[0] - origin[0]) * unit[0] + (p[1] - origin[1]) * unit[1] + (p[2] - origin[2]) * unit[2]);
  return points.every((p) => off(p) <= tolerance) ? unit : null;
}

/** The smallest distance between two curves' sampled polylines (sample to segment, both ways). */
function gap(a: NetCurve, b: NetCurve): number {
  const toSegment = (p: Vec3, s: Vec3, e: Vec3) => {
    const d: Vec3 = [e[0] - s[0], e[1] - s[1], e[2] - s[2]];
    const length2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2] || 1;
    const t = Math.max(0, Math.min(1, ((p[0] - s[0]) * d[0] + (p[1] - s[1]) * d[1] + (p[2] - s[2]) * d[2]) / length2));
    return distance(p, [s[0] + t * d[0], s[1] + t * d[1], s[2] + t * d[2]]);
  };
  const oneWay = (from: NetCurve, to: NetCurve) => {
    let best = Infinity;
    for (const p of from.edges.flat())
      for (const edge of to.edges) for (let i = 1; i < edge.length; i++) best = Math.min(best, toSegment(p, edge[i - 1], edge[i]));
    return best;
  };
  return Math.min(oneWay(a, b), oneWay(b, a));
}

/** The picked curves as a Gordon network: two families (profiles and guides) where every profile crosses every guide
 * and no two curves of one family cross; null when they are not one (fewer than two of each, or crossings that do not
 * split them so).  The family with the first picked curve is the profiles. */
export function gordonFamilies(curves: readonly NetCurve[], tolerance = netTolerance(curves) * 5): { profiles: string[]; guides: string[] } | null {
  if (curves.length < 4) return null;
  const crosses = curves.map((a, i) => curves.map((b, j) => i !== j && gap(a, b) <= tolerance));
  const side = new Array<number>(curves.length).fill(-1);
  side[0] = 0;
  const queue = [0];
  while (queue.length) {
    const i = queue.shift() as number;
    for (let j = 0; j < curves.length; j++) {
      if (!crosses[i][j]) continue;
      if (side[j] === side[i]) return null; // two curves of one family cross
      if (side[j] < 0) {
        side[j] = 1 - side[i];
        queue.push(j);
      }
    }
  }
  if (side.includes(-1)) return null; // a curve that crosses none of the others
  const profiles = curves.filter((_, i) => side[i] === 0);
  const guides = curves.filter((_, i) => side[i] === 1);
  if (profiles.length < 2 || guides.length < 2) return null;
  const complete = curves.every((_, i) => curves.every((_, j) => side[i] === side[j] || crosses[i][j]));
  return complete ? { profiles: profiles.map((c) => c.name), guides: guides.map((c) => c.name) } : null;
}
