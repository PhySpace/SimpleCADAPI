/** Raycast picking helpers for overlay objects: generous, invisible hit areas and the ray plumbing.
 *
 * An overlay object that wants to be clickable adds hit-area meshes (`hitSphere`, `hitSegment`): invisible (never
 * drawn, never ghosted) but answered by the raycaster, sized much larger than the visible strokes so a 2 px arrow
 * is still easy to hit.  `SceneLayer.pick` returns the key of the item whose hit area is nearest to the camera. */

import * as THREE from 'three';

import { OVERLAY_LAYER } from '../renderer';

const HIT_MATERIAL = new THREE.MeshBasicMaterial({ visible: false });

function asHitArea(mesh: THREE.Mesh): THREE.Mesh {
  mesh.userData.hitArea = true;
  mesh.userData.noGhost = true;
  mesh.layers.set(OVERLAY_LAYER);
  return mesh;
}

/** An invisible sphere hit area of `radius` centred at `center` (the object's local space). */
export function hitSphere(radius: number, center: THREE.Vector3 = new THREE.Vector3()): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 12, 8), HIT_MATERIAL);
  mesh.position.copy(center);
  return asHitArea(mesh);
}

/** An invisible capsule-ish (cylinder) hit area along the segment from `a` to `b` with `radius` (local space). */
export function hitSegment(a: THREE.Vector3, b: THREE.Vector3, radius: number): THREE.Mesh {
  const length = a.distanceTo(b);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, Math.max(length, 1e-9), 8, 1), HIT_MATERIAL);
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  return asHitArea(mesh);
}

/** A client (pointer) position as normalised device coordinates for the element's rectangle. */
export function ndcFromClient(rect: { left: number; top: number; width: number; height: number }, clientX: number, clientY: number): THREE.Vector2 {
  return new THREE.Vector2(((clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1, -((clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1);
}

export type PickHit = { key: string; distance: number; point: THREE.Vector3 };

/** The nearest hit-area intersection among `roots` (each carrying `userData.itemKey`, directly or on an ancestor
 * of the hit mesh), or null.  Invisible roots are skipped. */
export function pickHitAreas(raycaster: THREE.Raycaster, roots: Iterable<THREE.Object3D>): PickHit | null {
  raycaster.layers.set(OVERLAY_LAYER);
  let best: PickHit | null = null;
  for (const root of roots) {
    if (!root.visible) continue;
    for (const hit of raycaster.intersectObject(root, true)) {
      if (!hit.object.userData.hitArea || !isVisibleChain(hit.object, root)) continue;
      const key = itemKeyOf(hit.object);
      if (key === null) continue;
      if (!best || hit.distance < best.distance) best = { key, distance: hit.distance, point: hit.point.clone() };
      break; // intersections are sorted: the first valid one is this root's nearest
    }
  }
  return best;
}

function isVisibleChain(object: THREE.Object3D, stop: THREE.Object3D): boolean {
  for (let o: THREE.Object3D | null = object; o; o = o.parent) {
    if (!o.visible) return false;
    if (o === stop) break;
  }
  return true;
}

function itemKeyOf(object: THREE.Object3D): string | null {
  for (let o: THREE.Object3D | null = object; o; o = o.parent) if (typeof o.userData.itemKey === 'string') return o.userData.itemKey as string;
  return null;
}
