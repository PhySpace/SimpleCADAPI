/** Pure CAD-frame -> layer-space pose math (no scene access), for overlays that draw a CAD frame.
 *
 * CAD world: millimetres, +Z up.  Layer space (= glTF space, see layers/layer-host.ts): metres, +Y up, CAD z -> y and
 * CAD y -> -z.  An object that shows a frame is built in the frame's OWN axes (local +X/+Y/+Z are the frame's x/y/z,
 * unit = the object's own size), and posed with `cadFramePose`. */

import * as THREE from 'three';

import { cadPointToGltf } from './cad-three';

export type V3 = readonly [number, number, number];
export type CadFrame = { origin: V3; x_axis: V3; y_axis: V3; z_axis?: V3 };

/** CAD (x, y, z) -> glTF (x, z, -y), as a rotation (a turn of -90 degrees about X). */
export const CAD_TO_GLTF_ROTATION = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2);

const toVec = (v: V3) => new THREE.Vector3(v[0], v[1], v[2]);

/** The frame as an orthonormal right-handed basis: x kept, z = x cross y (the declared z_axis is used only when x and y are
 * parallel), y = z cross x.  Returns null for a degenerate frame (zero or parallel axes and no usable z). */
export function orthonormalBasis(frame: Pick<CadFrame, 'x_axis' | 'y_axis' | 'z_axis'>): { x: THREE.Vector3; y: THREE.Vector3; z: THREE.Vector3 } | null {
  const x = toVec(frame.x_axis);
  if (x.lengthSq() < 1e-18) return null;
  x.normalize();
  let z = x.clone().cross(toVec(frame.y_axis));
  if (z.lengthSq() < 1e-12) {
    if (!frame.z_axis) return null;
    z = toVec(frame.z_axis);
    if (z.lengthSq() < 1e-18) return null;
  }
  z.normalize();
  const y = z.clone().cross(x).normalize();
  return { x, y, z };
}

/** The pose of a CAD frame in layer space: its origin in metres (glTF) and the rotation that takes the object's local
 * axes onto the frame's axes.  null for a degenerate frame. */
export function cadFramePose(frame: CadFrame): { position: THREE.Vector3; quaternion: THREE.Quaternion } | null {
  const basis = orthonormalBasis(frame);
  if (!basis) return null;
  const cad = new THREE.Matrix4().makeBasis(basis.x, basis.y, basis.z);
  const quaternion = CAD_TO_GLTF_ROTATION.clone().multiply(new THREE.Quaternion().setFromRotationMatrix(cad));
  return { position: cadPointToGltf(frame.origin as [number, number, number]), quaternion };
}

/** The base size (mm) of a connector gizmo: `fraction` of the model's largest extent, clamped to [min, max] mm. */
export function connectorSizeMm(
  bounds: { min: V3; max: V3 } | null,
  { fraction = 0.12, min = 2, max = 150, fallback = 10 }: { fraction?: number; min?: number; max?: number; fallback?: number } = {},
): number {
  if (!bounds) return fallback;
  const extent = Math.max(bounds.max[0] - bounds.min[0], bounds.max[1] - bounds.min[1], bounds.max[2] - bounds.min[2]);
  if (!(extent > 0)) return fallback;
  return Math.min(max, Math.max(min, extent * fraction));
}
