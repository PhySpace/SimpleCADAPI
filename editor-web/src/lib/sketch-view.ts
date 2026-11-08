/** The sketch plane seen through the live camera: plane (u, v) in mm <-> screen pixels.  The scene's world is the CAD
 * frame in metres (Z up), the plane is in mm, hence the 1000. */

import * as THREE from "three";

import { rayPlane, type PlaneSpec, type Vec3, planeToWorld } from "@/lib/sketch-plane";

export type Viewer = { camera: THREE.PerspectiveCamera; width: number; height: number };

const MM_PER_M = 1000;

function refresh(camera: THREE.PerspectiveCamera) {
  camera.updateMatrixWorld(true);
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
}

/** The screen position (pixels, origin top left) of a world point in mm, or null when it is behind the camera. */
export function worldToScreen(viewer: Viewer, p: Vec3): [number, number] | null {
  refresh(viewer.camera);
  const v = new THREE.Vector3(p[0] / MM_PER_M, p[1] / MM_PER_M, p[2] / MM_PER_M).applyMatrix4(viewer.camera.matrixWorldInverse);
  if (v.z >= -1e-9) return null;
  v.applyMatrix4(viewer.camera.projectionMatrix);
  return [((v.x + 1) / 2) * viewer.width, ((1 - v.y) / 2) * viewer.height];
}

export function planeToScreen(viewer: Viewer, plane: PlaneSpec, u: number, v: number): [number, number] | null {
  return worldToScreen(viewer, planeToWorld(plane, u, v));
}

/** The pick ray of a screen position: origin (mm) and unit direction. */
export function screenRay(viewer: Viewer, sx: number, sy: number): { origin: Vec3; dir: Vec3 } {
  refresh(viewer.camera);
  const camera = viewer.camera;
  // through the near and the far plane: the ray of either projection (a perspective one starts at the eye, an orthographic one
  // is parallel to the view direction and starts at the pixel)
  const x = (sx / viewer.width) * 2 - 1;
  const y = -(sy / viewer.height) * 2 + 1;
  const origin = new THREE.Vector3(x, y, -1).unproject(camera);
  const dir = new THREE.Vector3(x, y, 1).unproject(camera).sub(origin).normalize();
  return { origin: [origin.x * MM_PER_M, origin.y * MM_PER_M, origin.z * MM_PER_M], dir: [dir.x, dir.y, dir.z] };
}

/** The plane position under a screen position (ray-plane intersection), or null when the ray misses the plane. */
export function screenToPlane(viewer: Viewer, plane: PlaneSpec, sx: number, sy: number): [number, number] | null {
  const ray = screenRay(viewer, sx, sy);
  const hit = rayPlane(ray.origin, ray.dir, plane);
  return hit ? [hit[0], hit[1]] : null;
}

/** Pixels per mm of the plane at a plane position (the mean of the two axes: perspective makes it local). */
export function scaleAt(viewer: Viewer, plane: PlaneSpec, u: number, v: number): number {
  const o = planeToScreen(viewer, plane, u, v);
  const a = planeToScreen(viewer, plane, u + 1, v);
  const b = planeToScreen(viewer, plane, u, v + 1);
  if (!o || !a || !b) return 1;
  return (Math.hypot(a[0] - o[0], a[1] - o[1]) + Math.hypot(b[0] - o[0], b[1] - o[1])) / 2 || 1;
}

/** A string that changes whenever the camera or the canvas size does (to know when the overlay must be projected again). */
export function cameraSignature(viewer: Viewer): string {
  const c = viewer.camera;
  c.updateMatrixWorld(true);
  const m = c.matrixWorld.elements;
  return `${viewer.width}x${viewer.height}|${c.fov}|${c.near}|${c.far}|${m[0]},${m[1]},${m[2]},${m[4]},${m[5]},${m[6]},${m[8]},${m[9]},${m[10]},${m[12]},${m[13]},${m[14]}`;
}

/** How far (mm) the camera must stand from a plane for `extent` mm to fill the view comfortably. */
export function fitDistanceMm(extent: number, fovDeg: number, aspect: number): number {
  const half = Math.tan((fovDeg * Math.PI) / 360);
  const narrow = Math.min(half, half * aspect);
  return (Math.max(extent, 10) / 2 / narrow) * 1.35;
}
