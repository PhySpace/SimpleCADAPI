/** The sketch plane in 3D: named datum planes and free frames (origin + two unit axes, in mm, as the sketch document
 * carries them), the frame of a planar face from its entity info, the ray/plane intersection and the camera pose that
 * looks straight at a plane.  Pure (no three.js): the camera mapping lives in sketch-view.ts. */

export type Vec3 = [number, number, number];
export type Plane = "XY" | "XZ" | "YZ";
export const PLANES: Plane[] = ["XY", "XZ", "YZ"];

/** A plane by its origin and unit axes (mm); the normal is x_axis cross y_axis. */
export type Frame = { origin: Vec3; x_axis: Vec3; y_axis: Vec3 };
export type PlaneSpec = Plane | Frame;

export const isNamedPlane = (plane: unknown): plane is Plane => typeof plane === "string" && PLANES.includes(plane as Plane);

// -- vectors --------------------------------------------------------------------------------------------------------

export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export const length = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
export function unit(a: Vec3): Vec3 | null {
  const n = length(a);
  return n > 1e-12 ? [a[0] / n, a[1] / n, a[2] / n] : null;
}

/** A 3-vector from an array or an {x, y, z} object; null when it is neither (or not finite). */
export function vec3(value: unknown): Vec3 | null {
  if (Array.isArray(value) && value.length === 3 && value.every((c) => typeof c === "number" && Number.isFinite(c))) return [value[0], value[1], value[2]];
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.x === "number" && typeof o.y === "number" && typeof o.z === "number" && [o.x, o.y, o.z].every(Number.isFinite)) return [o.x, o.y, o.z];
  }
  return null;
}

const round = (v: number, digits: number) => {
  const k = 10 ** digits;
  return Math.round(v * k) / k + 0;
};
const roundVec = (a: Vec3, digits: number): Vec3 => [round(a[0], digits), round(a[1], digits), round(a[2], digits)];

// -- frames ---------------------------------------------------------------------------------------------------------

const NAMED: Record<Plane, Frame> = {
  XY: { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0] },
  XZ: { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 0, 1] },
  YZ: { origin: [0, 0, 0], x_axis: [0, 1, 0], y_axis: [0, 0, 1] },
};

/** The frame of a named plane (the SDK's own: XY x->X y->Y, XZ x->X y->Z, YZ x->Y y->Z) or the frame itself. */
export function frameOf(plane: PlaneSpec): Frame {
  return isNamedPlane(plane) ? NAMED[plane] : plane;
}

export const frameNormal = (frame: Frame): Vec3 => cross(frame.x_axis, frame.y_axis);
export const planeNormal = (plane: PlaneSpec): Vec3 => frameNormal(frameOf(plane));

/** A plane from whatever a document held: a named plane, or a frame with finite vectors (axes normalised, y made square to x). */
export function normalizePlane(raw: unknown): PlaneSpec {
  if (isNamedPlane(raw)) return raw;
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    const origin = vec3(o.origin);
    const x = vec3(o.x_axis);
    const y = vec3(o.y_axis);
    const ux = x && unit(x);
    if (origin && ux && y) {
      const along = dot(y, ux);
      const uy = unit([y[0] - ux[0] * along, y[1] - ux[1] * along, y[2] - ux[2] * along]);
      if (uy) return { origin, x_axis: ux, y_axis: uy };
    }
  }
  return "XY";
}

/** The frame the document stores: numbers rounded so the axes stay unit and square (the server checks both). */
export function frameSpec(frame: Frame): Frame {
  const x = unit(roundVec(unit(frame.x_axis) ?? [1, 0, 0], 9)) ?? [1, 0, 0];
  const n = unit(cross(x, unit(frame.y_axis) ?? [0, 1, 0])) ?? [0, 0, 1];
  const y = unit(roundVec(unit(cross(n, x)) ?? [0, 1, 0], 9)) ?? [0, 1, 0];
  return { origin: roundVec(frame.origin, 6), x_axis: x, y_axis: y };
}

/** A stable x axis for a plane that came without one: horizontal (Z cross n); for floors and ceilings, X. */
export function stableXAxis(normal: Vec3): Vec3 {
  if (Math.abs(normal[2]) > 0.999) return [1, 0, 0];
  return unit(cross([0, 0, 1], normal)) ?? [1, 0, 0];
}

/** The frame of a planar face from its entity info ({type:"plane", origin, normal, x_direction} and properties.centroid):
 * the origin is the face centroid on the plane (else the geometry origin), x the given x_direction made square to the
 * normal (else a stable one), y = normal cross x.  Null when the face is not a plane. */
export function frameFromEntity(geometry: Record<string, unknown> | null | undefined, properties?: Record<string, unknown> | null): Frame | null {
  const geo = geometry ?? {};
  const kind = typeof geo.type === "string" ? geo.type.toLowerCase() : null;
  if (kind !== null && kind !== "plane") return null;
  const n = unit(vec3(geo.normal) ?? ([NaN, 0, 0] as Vec3));
  if (!n) return null;
  const given = vec3(geo.origin);
  const centroid = vec3(properties?.centroid);
  const base = centroid ?? given;
  if (!base) return null;
  const onPlane: Vec3 = given ? sub(base, scale(n, dot(sub(base, given), n))) : base;
  const xd = vec3(geo.x_direction);
  const projected = xd ? unit(sub(xd, scale(n, dot(xd, n)))) : null;
  const x = projected ?? stableXAxis(n);
  const y = cross(n, x);
  return frameSpec({ origin: onPlane, x_axis: x, y_axis: y });
}

/** The document's plane value for a frame: a named plane when it is exactly one at the origin, else the frame. */
export function planeValue(frame: Frame): PlaneSpec {
  for (const name of PLANES) {
    const n = NAMED[name];
    if (length(sub(frame.origin, n.origin)) < 1e-6 && length(sub(frame.x_axis, n.x_axis)) < 1e-6 && length(sub(frame.y_axis, n.y_axis)) < 1e-6) return name;
  }
  return frameSpec(frame);
}

export const planeLabel = (plane: PlaneSpec): string => (isNamedPlane(plane) ? plane : "face");

/** The position of a world point (mm) in the plane's (u, v). */
export function worldToPlane(plane: PlaneSpec, p: Vec3): [number, number] {
  const f = frameOf(plane);
  const d = sub(p, f.origin);
  return [dot(d, f.x_axis), dot(d, f.y_axis)];
}

/** The world point (mm) of a plane position. */
export function planeToWorld(plane: PlaneSpec, u: number, v: number): Vec3 {
  const f = frameOf(plane);
  return [f.origin[0] + f.x_axis[0] * u + f.y_axis[0] * v, f.origin[1] + f.x_axis[1] * u + f.y_axis[1] * v, f.origin[2] + f.x_axis[2] * u + f.y_axis[2] * v];
}

/** A profile centroid the server reports in world coordinates, in the sketch plane's (u, v) (named or any frame). */
export const planeCoords = (plane: PlaneSpec, c: readonly [number, number, number]): [number, number] => worldToPlane(plane, [c[0], c[1], c[2]]);

/** Where the ray (origin + t * dir, same units as the frame) meets the plane: [u, v, t], or null when parallel or behind. */
export function rayPlane(origin: Vec3, dir: Vec3, plane: PlaneSpec): [number, number, number] | null {
  const f = frameOf(plane);
  const n = frameNormal(f);
  const denom = dot(dir, n);
  if (Math.abs(denom) < 1e-12) return null;
  const t = dot(sub(f.origin, origin), n) / denom;
  if (!(t >= 0)) return null;
  const hit = add(origin, scale(dir, t));
  const d = sub(hit, f.origin);
  return [dot(d, f.x_axis), dot(d, f.y_axis), t];
}

/** The camera pose (mm) that looks straight at the plane: it sits `distance` out along the normal, looks along -normal, up = y. */
export function viewPose(plane: PlaneSpec, center: Vec3, distance: number): { position: Vec3; target: Vec3; up: Vec3 } {
  const f = frameOf(plane);
  const n = frameNormal(f);
  return { position: add(center, scale(n, distance)), target: center, up: f.y_axis };
}

/** The point of the plane nearest to a world point (mm). */
export function projectOnPlane(plane: PlaneSpec, p: Vec3): Vec3 {
  const f = frameOf(plane);
  const n = frameNormal(f);
  return sub(p, scale(n, dot(sub(p, f.origin), n)));
}

/** The axis option ("+z", "-y") a unit vector equals, or null when it is not axis-aligned. */
export function axisName(v: readonly number[]): string | null {
  const names = ["x", "y", "z"];
  for (let i = 0; i < 3; i++) {
    if (Math.abs(Math.abs(v[i]) - 1) < 1e-6 && names.every((_, j) => j === i || Math.abs(v[j]) < 1e-6)) return `${v[i] > 0 ? "+" : "-"}${names[i]}`;
  }
  return null;
}
