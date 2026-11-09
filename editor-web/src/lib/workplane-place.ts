/** Placing a workplane by hand: a base frame (XY / XZ / YZ, a workplane of the notebook, a picked face), the offset along
 * the base's own axes and three turns about them, as `make_workplane_offset_rworkplane` takes them.  The handles in the
 * viewport move a frame; this module turns a frame into those numbers and back, with the SDK's formula, so what is shown
 * is what the cell makes.  Pure: no React, no three.js. */

import { add, cross, dot, scale, unit, vec3, type Vec3 } from "@/lib/sketch-plane";

/** A frame in world mm: an origin and three orthonormal axes (normal = x cross y). */
export type PlaceFrame = { origin: Vec3; x_axis: Vec3; y_axis: Vec3; normal: Vec3 };

/** What the cell writes: `offset=(move)`, `rx`, `ry`, `rz` (degrees). */
export type PlaceValues = { move: Vec3; rx: number; ry: number; rz: number };

export const ZERO_PLACE: PlaceValues = { move: [0, 0, 0], rx: 0, ry: 0, rz: 0 };

/** The named planes as sketches (and the SDK's base_plane) read them. */
export const NAMED_FRAMES: Record<"XY" | "XZ" | "YZ", PlaceFrame> = {
  XY: { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0], normal: [0, 0, 1] },
  XZ: { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 0, 1], normal: [0, -1, 0] },
  YZ: { origin: [0, 0, 0], x_axis: [0, 1, 0], y_axis: [0, 0, 1], normal: [1, 0, 0] },
};

const RAD = Math.PI / 180;
type M3 = [Vec3, Vec3, Vec3]; // rows

const mul = (a: M3, b: M3): M3 =>
  a.map((row) => [0, 1, 2].map((j) => row[0] * b[0][j] + row[1] * b[1][j] + row[2] * b[2][j])) as M3;
const rx = (t: number): M3 => [[1, 0, 0], [0, Math.cos(t), -Math.sin(t)], [0, Math.sin(t), Math.cos(t)]];
const ry = (t: number): M3 => [[Math.cos(t), 0, Math.sin(t)], [0, 1, 0], [-Math.sin(t), 0, Math.cos(t)]];
const rz = (t: number): M3 => [[Math.cos(t), -Math.sin(t), 0], [Math.sin(t), Math.cos(t), 0], [0, 0, 1]];
const column = (m: M3, j: number): Vec3 => [m[0][j], m[1][j], m[2][j]];

/** The frame `values` place on `base`: the origin moved along the base's x, y and normal, the axes turned about the
 * base's x, then the y that left, then the z (R = Rx Ry Rz in the base's frame), as the SDK does. */
export function placedFrame(base: PlaceFrame, values: PlaceValues): PlaceFrame {
  const [dx, dy, dz] = values.move;
  const origin = add(base.origin, add(scale(base.x_axis, dx), add(scale(base.y_axis, dy), scale(base.normal, dz))));
  const local = mul(mul(rx(values.rx * RAD), ry(values.ry * RAD)), rz(values.rz * RAD));
  const world = (v: Vec3): Vec3 => add(scale(base.x_axis, v[0]), add(scale(base.y_axis, v[1]), scale(base.normal, v[2])));
  return { origin, x_axis: world(column(local, 0)), y_axis: world(column(local, 1)), normal: world(column(local, 2)) };
}

const round = (value: number, step: number) => Math.round(value / step) * step + 0; // + 0: no -0

/** The values that place `frame` on `base` (the inverse of placedFrame); offsets to 0.001 mm, turns to 0.001 degree. */
export function placeValues(base: PlaceFrame, frame: PlaceFrame): PlaceValues {
  const d: Vec3 = [frame.origin[0] - base.origin[0], frame.origin[1] - base.origin[1], frame.origin[2] - base.origin[2]];
  const move: Vec3 = [dot(d, base.x_axis), dot(d, base.y_axis), dot(d, base.normal)].map((v) => round(v, 0.001)) as Vec3;
  // M = B^T R: the new axes in the base's coordinates (columns), = Rx(a) Ry(b) Rz(c)
  const inBase = (v: Vec3): Vec3 => [dot(v, base.x_axis), dot(v, base.y_axis), dot(v, base.normal)];
  const x = inBase(frame.x_axis);
  const y = inBase(frame.y_axis);
  const z = inBase(frame.normal);
  const m13 = Math.max(-1, Math.min(1, z[0]));
  const b = Math.asin(m13);
  let a: number;
  let c: number;
  if (Math.abs(m13) < 0.9999999) {
    a = Math.atan2(-z[1], z[2]);
    c = Math.atan2(-y[0], x[0]);
  } else {
    a = Math.atan2(y[2], y[1]);
    c = 0;
  }
  return { move, rx: round(a / RAD, 0.001), ry: round(b / RAD, 0.001), rz: round(c / RAD, 0.001) };
}

/** A frame from a picked planar face's connector frame (entity info `properties.connector_frame`: its centroid, outward
 * normal and an x axis); null for anything else.  The cell passes that x axis as `x_dir`, so the plane made matches. */
export function faceFrame(properties: Record<string, unknown> | null | undefined): PlaceFrame | null {
  const raw = properties?.connector_frame as Record<string, unknown> | undefined;
  const origin = vec3(raw?.origin);
  const x = vec3(raw?.x_axis) && unit(vec3(raw?.x_axis)!);
  const z = vec3(raw?.z_axis) && unit(vec3(raw?.z_axis)!);
  if (!origin || !x || !z) return null;
  return { origin, x_axis: x, y_axis: cross(z, x), normal: z };
}

/** The values a cell can be given for a place: rounded, no -0. */
export function cleanValues(values: PlaceValues): PlaceValues {
  return {
    move: values.move.map((v) => round(v, 0.001)) as Vec3,
    rx: round(values.rx, 0.001),
    ry: round(values.ry, 0.001),
    rz: round(values.rz, 0.001),
  };
}
