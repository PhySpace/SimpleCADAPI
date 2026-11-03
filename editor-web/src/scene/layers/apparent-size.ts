/** Apparent-size scaling for overlay objects (pure functions plus one object helper).
 *
 * An overlay that is "world sized" shrinks to a speck when the camera pulls back and swallows the model when it
 * zooms in.  One that is "screen sized" never relates to the model.  The compromise used here: the object's
 * world scale follows the camera distance (so its on-screen size stays roughly constant), but only inside
 * [minFactor, maxFactor] times its base size, so at the extremes it behaves like a real object again. */

import * as THREE from 'three';

import { scaleDistance } from '../camera-projection';

export type ApparentSizeOptions = {
  /** The distance (world units) at which the factor is exactly 1: usually the framing distance of the model. */
  referenceDistance: number;
  /** Lower clamp of the factor (default 0.4): a close-up never makes the object smaller than this. */
  minFactor?: number;
  /** Upper clamp of the factor (default 2.5). */
  maxFactor?: number;
};

/** The scale factor for an object at `distance` from the camera: distance / referenceDistance, clamped. */
export function apparentFactor(distance: number, { referenceDistance, minFactor = 0.4, maxFactor = 2.5 }: ApparentSizeOptions): number {
  if (!(referenceDistance > 0) || !Number.isFinite(distance) || distance <= 0) return 1;
  return Math.min(maxFactor, Math.max(minFactor, distance / referenceDistance));
}

/** The base size (same unit as the extents) of an overlay from the model's largest extent: `fraction` of it, clamped. */
export function sizeFromExtent(largestExtent: number, fraction: number, min: number, max: number): number {
  const raw = Number.isFinite(largestExtent) ? largestExtent * fraction : min;
  return Math.min(max, Math.max(min, raw));
}

const scratch = new THREE.Vector3();

/** Set `object.scale` to `baseScale` times the apparent factor for the object's current distance to the camera.
 * Returns the factor used (callers can detect a change).  `object` must have an up-to-date world matrix. */
export function applyApparentScale(object: THREE.Object3D, camera: THREE.Camera, baseScale: number, options: ApparentSizeOptions): number {
  object.getWorldPosition(scratch);
  const factor = apparentFactor(scaleDistance(camera, scratch.distanceTo(camera.position)), options);
  object.scale.setScalar(baseScale * factor);
  return factor;
}
