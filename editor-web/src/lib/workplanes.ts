/** The notebook's workplanes in the editor: the frames the kernel reports (a `workplanes` envelope), the plane a sketch on
 * one uses, the small patch drawn for each, and which constructor a selection asks for when Space is pressed.
 * Pure: no React, no three.js.  The frames are the SDK's own; nothing here computes geometry from the model. */

import { add, frameSpec, isNamedPlane, scale, unit, vec3, type Frame, type PlaneSpec, type Vec3 } from "@/lib/sketch-plane";

/** One workplane variable of the notebook, in world mm. */
export type WorkplaneFrame = { name: string; origin: Vec3; x_axis: Vec3; y_axis: Vec3; normal: Vec3 };

const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** The workplanes of a `workplanes` envelope; malformed entries are dropped. */
export function parseWorkplanes(raw: unknown): WorkplaneFrame[] {
  if (!Array.isArray(raw)) return [];
  const out: WorkplaneFrame[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const origin = vec3(o.origin);
    const x = vec3(o.x_axis) && unit(vec3(o.x_axis)!);
    const y = vec3(o.y_axis) && unit(vec3(o.y_axis)!);
    const n = vec3(o.normal) && unit(vec3(o.normal)!);
    if (typeof o.name === "string" && NAME.test(o.name) && origin && x && y && n) out.push({ name: o.name, origin, x_axis: x, y_axis: y, normal: n });
  }
  return out;
}

/** The sketch plane of a workplane: its frame, tagged with its variable (the cell writes `plane=<name>`). */
export const workplanePlane = (wp: WorkplaneFrame): Frame => frameSpec({ workplane: wp.name, origin: wp.origin, x_axis: wp.x_axis, y_axis: wp.y_axis });

/** A plane as it is now: a plane on a workplane takes the frame the kernel last reported for that variable (the face it
 * was made from may have moved); anything else is itself. */
export function resolvePlane(plane: PlaneSpec, workplanes: readonly WorkplaneFrame[]): PlaneSpec {
  if (isNamedPlane(plane) || !plane.workplane) return plane;
  const found = workplanes.find((wp) => wp.name === plane.workplane);
  return found ? workplanePlane(found) : plane;
}

/** The corners (world mm) of the square patch drawn for a workplane, `half` from its origin along x and y. */
export function patchCorners(wp: Pick<WorkplaneFrame, "origin" | "x_axis" | "y_axis">, half: number): Vec3[] {
  const at = (u: number, v: number) => add(wp.origin, add(scale(wp.x_axis, u), scale(wp.y_axis, v)));
  return [at(-half, -half), at(half, -half), at(half, half), at(-half, half)];
}

/** What a picked item needs to be here (a SelectionItem fits). */
export type PickLike = { kind: string };

/** How Space makes a workplane from the selection: the method of the `workplane` feature and the item per slot, or null
 * when the selection names no workplane.  One planar face -> on it; a face and an edge -> on it, x along the edge; two
 * faces -> halfway between them; three vertices (in pick order) -> through them; one edge -> through it. */
export function workplaneRequest<T extends PickLike>(items: readonly T[]): { method: string; selections: Record<string, T[]> } | null {
  const faces = items.filter((i) => i.kind === "face");
  const edges = items.filter((i) => i.kind === "edge");
  const vertices = items.filter((i) => i.kind === "vertex");
  if (faces.length + edges.length + vertices.length !== items.length) return null;
  if (faces.length === 1 && edges.length === 0 && vertices.length === 0) return { method: "face", selections: { face: faces } };
  if (faces.length === 1 && edges.length === 1 && vertices.length === 0) return { method: "face_edge", selections: { face: faces, edge: edges } };
  if (faces.length === 2 && edges.length === 0 && vertices.length === 0) return { method: "midplane", selections: { face: [faces[0]], face_b: [faces[1]] } };
  if (vertices.length === 3 && faces.length === 0 && edges.length === 0)
    return { method: "points", selections: { point_a: [vertices[0]], point_b: [vertices[1]], point_c: [vertices[2]] } };
  if (edges.length === 1 && faces.length === 0 && vertices.length === 0) return { method: "axis", selections: { edge: edges } };
  return null;
}
