/** Picking through bounding volume hierarchies (three-mesh-bvh): a ray tests the few triangles, edge segments or vertices
 * near it instead of every one of a part, which keeps hover and click picks immediate on parts of a million triangles.
 *
 * Only the model's own objects are accelerated (faces, the invisible edge pick lines, the vertex clouds); the hierarchy
 * is built `indirect`, so the index buffers keep their order: the face and edge groups of a part are ranges in them.
 * It is built when the browser is idle, and a pick before that tests every primitive as three does. */

import * as THREE from 'three';
import { LineSegmentsBVH, MeshBVH, PointsBVH, acceleratedRaycast } from 'three-mesh-bvh';

type Accelerated = THREE.BufferGeometry;

const pending = new Set<Accelerated>();
let scheduled = false;

const idle: (callback: () => void) => void =
  typeof requestIdleCallback === 'function' ? (callback) => requestIdleCallback(callback, { timeout: 500 }) : (callback) => setTimeout(callback, 50);

function typeOf(object: THREE.Object3D): typeof MeshBVH | typeof LineSegmentsBVH | typeof PointsBVH {
  if (object instanceof THREE.Points) return PointsBVH;
  if (object instanceof THREE.LineSegments) return LineSegmentsBVH;
  return MeshBVH;
}

function buildPending(): void {
  scheduled = false;
  for (const geometry of pending) {
    pending.delete(geometry);
    const type = geometry.userData.bvhType as typeof MeshBVH | undefined;
    if (!type || geometry.boundsTree) continue;
    geometry.boundsTree = new type(geometry, { indirect: true });
  }
}

/** Pick `object` (a mesh, line segments or points of the model) through a hierarchy of its geometry. */
export function accelerate(object: THREE.Mesh | THREE.LineSegments | THREE.Points): void {
  const geometry = object.geometry as Accelerated;
  object.raycast = acceleratedRaycast as THREE.Object3D['raycast'];
  if (geometry.boundsTree) return;
  geometry.userData.bvhType = typeOf(object);
  pending.add(geometry);
  if (!scheduled) {
    scheduled = true;
    idle(buildPending);
  }
}

/** Forget the hierarchy of a geometry that is disposed. */
export function release(geometry: THREE.BufferGeometry): void {
  pending.delete(geometry as Accelerated);
  (geometry as Accelerated).boundsTree = undefined;
}
