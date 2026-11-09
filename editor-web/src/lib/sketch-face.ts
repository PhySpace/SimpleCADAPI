/** The model's edges that lie in the sketch plane (the boundary of the face a sketch is drawn on, and any edge coplanar with
 * it), as segments in sketch coordinates: drawn faintly under the sketch and snapped to while drawing, the way Plasticity
 * and Onshape show the face a sketch sits on.  Snapping copies the place; to tie the sketch to the face so it follows the
 * model, the SDK's `project_rsketch(sketch, face)` brings the face's lines and arcs in as fixed reference geometry. */

import { dot, frameNormal, frameOf, sub, worldToPlane, type PlaneSpec, type Vec3 } from "@/lib/sketch-plane";

type P = [number, number];
export type Segment = [P, P];

/** The segments of `edges` (world mm, pairs of points) whose two ends lie within `tol` mm of the plane, in sketch coordinates;
 * repeated segments (an edge two faces share) once. */
export function planeSegments(edges: readonly (readonly [Vec3, Vec3])[], plane: PlaneSpec, tol = 1e-3): Segment[] {
  const frame = frameOf(plane);
  const normal = frameNormal(frame);
  const off = (p: Vec3) => Math.abs(dot(sub(p, frame.origin), normal));
  const seen = new Set<string>();
  const out: Segment[] = [];
  const key = (p: P) => `${Math.round(p[0] * 1e3)}:${Math.round(p[1] * 1e3)}`;
  for (const [a, b] of edges) {
    if (off(a) > tol || off(b) > tol) continue;
    const ua = worldToPlane(plane, a);
    const ub = worldToPlane(plane, b);
    if (Math.hypot(ub[0] - ua[0], ub[1] - ua[1]) < 1e-9) continue;
    const k = [key(ua), key(ub)].sort().join("|");
    if (seen.has(k)) continue;
    seen.add(k);
    out.push([ua, ub]);
  }
  return out;
}

/** The point on the face's edges nearest `pos`, within `tol` (sketch units), or null. */
export function edgeSnap(pos: readonly [number, number], segments: readonly Segment[], tol: number): P | null {
  let best: { at: P; d: number } | null = null;
  for (const [a, b] of segments) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.min(1, Math.max(0, ((pos[0] - a[0]) * dx + (pos[1] - a[1]) * dy) / len2)) : 0;
    const at: P = [a[0] + t * dx, a[1] + t * dy];
    const d = Math.hypot(pos[0] - at[0], pos[1] - at[1]);
    if (d <= tol && (!best || d < best.d)) best = { at, d };
  }
  return best ? best.at : null;
}
