/** Points of a fixed size in pixels (vertex markers, picked vertices, a curve's points) for the WebGPU renderer: WebGPU
 * draws point primitives one pixel wide, so a sized point is an instanced sprite, one instance per point, in the same
 * coordinates as the positions it is given. */

import * as THREE from 'three';
import { PointsNodeMaterial } from 'three/webgpu';
import {
  cameraProjectionMatrix,
  cameraWorldMatrix,
  float,
  instancedBufferAttribute,
  modelViewMatrix,
  modelWorldMatrixInverse,
  select,
  vec3,
  vec4,
} from 'three/tsl';

/** About one pixel's angle in a 45° view a few hundred pixels high: a dot is pulled towards the camera by its radius in
 * this measure, so a surface curving towards the camera next to a vertex does not cover half the dot. */
const PULL_PER_PIXEL = 0.0012;

export type PointSpriteOptions = { color: THREE.ColorRepresentation; size: number; opacity?: number; depthTest?: boolean };

/** One sprite drawing every point of `positions` (an (n, 3) position attribute) as a `size` px dot. */
export function pointSprites(positions: THREE.BufferAttribute | THREE.InterleavedBufferAttribute, options: PointSpriteOptions): THREE.Sprite {
  const count = positions.count;
  const array = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) array.set([positions.getX(i), positions.getY(i), positions.getZ(i)], i * 3);
  const material = new PointsNodeMaterial({
    color: new THREE.Color(options.color),
    transparent: (options.opacity ?? 1) < 1 || options.depthTest === false,
    opacity: options.opacity ?? 1,
    depthTest: options.depthTest ?? true,
    depthWrite: false,
    sizeAttenuation: false,
  });
  const center = instancedBufferAttribute(new THREE.InstancedBufferAttribute(array, 3)) as unknown as ReturnType<typeof vec3>;
  const view = vec3(modelViewMatrix.mul(vec4(center, 1)).xyz);
  const pull = float((options.size / 2) * PULL_PER_PIXEL);
  // along the view ray in perspective (the dot stays where it is on screen), along the view axis in orthographic
  // (`element` indexes a matrix node at run time; the typings do not declare it)
  const projection = cameraProjectionMatrix as unknown as { element(i: number): { element(j: number): ReturnType<typeof float> } };
  const perspective = projection.element(2).element(3).equal(-1);
  const pulled = select(perspective, view.mul(float(1).sub(pull)), view.add(vec3(0, 0, view.z.negate().mul(pull))));
  material.positionNode = modelWorldMatrixInverse.mul(cameraWorldMatrix).mul(vec4(pulled, 1)).xyz;
  material.sizeNode = float(options.size);
  const sprite = new THREE.Sprite(material as unknown as THREE.SpriteMaterial);
  // The sprite's own quad is one unit wide at its origin: bounds (fitting the camera, sizing the grid) take the points
  // instead, and the points are picked through what they mark, never through the sprite.
  sprite.geometry = sprite.geometry.clone();
  sprite.geometry.boundingBox = new THREE.Box3().setFromArray(array);
  sprite.geometry.boundingSphere = sprite.geometry.boundingBox.getBoundingSphere(new THREE.Sphere());
  sprite.raycast = () => {};
  sprite.count = count;
  sprite.frustumCulled = false;
  sprite.userData.pickable = false;
  return sprite;
}

/** The sprite's colour (a theme change recolours vertex markers). */
export function setPointSpriteColor(sprite: THREE.Sprite, color: THREE.ColorRepresentation): void {
  (sprite.material as unknown as PointsNodeMaterial).color.set(color);
}
