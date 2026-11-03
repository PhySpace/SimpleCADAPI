// The viewport camera is a PerspectiveCamera; the sketch canvas looks through the same camera with an orthographic projection
// (a drawing has no foreshortening, and a millimetre is the same number of pixels everywhere).  The camera object stays one
// type (the trackball, the occlusion pass and the layers all hold it); only its projection matrix is swapped, framed so the
// target plane keeps its size: the change of projection does not zoom.

import * as THREE from 'three';

/** Whether the camera currently projects orthographically. */
export const isOrthographic = (camera: THREE.Camera): boolean => camera.userData.orthographic === true;

/** Write the orthographic projection of `camera` looking at distance `distance` (the same view height as the perspective one there). */
export function applyOrthographic(camera: THREE.PerspectiveCamera, distance: number): void {
  const halfHeight = Math.max(distance, 1e-6) * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const halfWidth = halfHeight * camera.aspect;
  camera.projectionMatrix.makeOrthographic(-halfWidth, halfWidth, halfHeight, -halfHeight, camera.near, camera.far);
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  camera.userData.orthoDistance = distance;
}

/** The distance a perspective camera would have to see the same scale at the target: what apparent-size scaling follows. */
export const scaleDistance = (camera: THREE.Camera, fallback: number): number =>
  isOrthographic(camera) ? (camera.userData.orthoDistance as number) : fallback;

/** `raycaster.setFromCamera` for either projection (three decides by the camera class, which stays perspective here). */
export function rayThrough(raycaster: THREE.Raycaster, ndc: THREE.Vector2, camera: THREE.PerspectiveCamera): void {
  if (!isOrthographic(camera)) {
    raycaster.setFromCamera(ndc, camera);
    return;
  }
  camera.updateMatrixWorld();
  raycaster.ray.origin.set(ndc.x, ndc.y, (camera.near + camera.far) / (camera.near - camera.far)).unproject(camera);
  raycaster.ray.direction.set(0, 0, -1).transformDirection(camera.matrixWorld);
  raycaster.camera = camera;
}
