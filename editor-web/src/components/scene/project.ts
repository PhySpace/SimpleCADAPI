/** Projecting ONE 3D point to the screen (pure; no scene access).  A point projects exactly, a direction does not:
 * never project an axis direction and re-normalise it on screen (that destroys foreshortening); draw the axes as 3D
 * objects and use this only to anchor flat things (labels, markers) to an origin point. */

import * as THREE from 'three';

export type ScreenPoint = {
  /** CSS pixels from the canvas' top-left corner. */
  x: number;
  y: number;
  /** False when the point is behind the camera, beyond the far plane or outside the canvas (plus `margin` px). */
  visible: boolean;
};

const scratch = new THREE.Vector3();

export function projectPoint(point: THREE.Vector3, camera: THREE.Camera, width: number, height: number, margin = 0): ScreenPoint {
  camera.updateMatrixWorld(); // the controls move the camera before the renderer refreshes its matrices
  scratch.copy(point).project(camera);
  const x = ((scratch.x + 1) / 2) * width;
  const y = ((1 - scratch.y) / 2) * height;
  const inDepth = scratch.z >= -1 && scratch.z <= 1;
  const inside = x >= -margin && x <= width + margin && y >= -margin && y <= height + margin;
  return { x, y, visible: Number.isFinite(x) && Number.isFinite(y) && inDepth && inside };
}
