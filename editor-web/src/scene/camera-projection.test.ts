import { describe, expect, it } from 'vitest';
import * as THREE from 'three';

import { applyOrthographic, isOrthographic, rayThrough, scaleDistance } from './camera-projection';

const camera = () => {
  const c = new THREE.PerspectiveCamera(42, 2, 0.01, 100);
  c.position.set(0, -5, 0);
  c.up.set(0, 0, 1);
  c.lookAt(0, 0, 0);
  c.updateMatrixWorld(true);
  return c;
};

describe('the orthographic projection of the sketch canvas', () => {
  it('keeps the size the perspective view has at the target', () => {
    const c = camera();
    const near = new THREE.Vector3(1, 0, 0).applyMatrix4(c.matrixWorldInverse).applyMatrix4(c.projectionMatrix).x;
    c.userData.orthographic = true;
    applyOrthographic(c, 5);
    const flat = new THREE.Vector3(1, 0, 0).applyMatrix4(c.matrixWorldInverse).applyMatrix4(c.projectionMatrix).x;
    expect(flat).toBeCloseTo(near, 6);
  });
  it('has no foreshortening: the same offset reads the same at any depth', () => {
    const c = camera();
    c.userData.orthographic = true;
    applyOrthographic(c, 5);
    const at = (y: number) => new THREE.Vector3(1, y, 0).applyMatrix4(c.matrixWorldInverse).applyMatrix4(c.projectionMatrix).x;
    expect(at(-2)).toBeCloseTo(at(30), 9);
  });
  it('casts parallel pick rays that start at the pixel', () => {
    const c = camera();
    c.userData.orthographic = true;
    applyOrthographic(c, 5);
    const a = new THREE.Raycaster();
    const b = new THREE.Raycaster();
    rayThrough(a, new THREE.Vector2(0.3, 0.2), c);
    rayThrough(b, new THREE.Vector2(-0.4, -0.1), c);
    expect(a.ray.direction.distanceTo(b.ray.direction)).toBeCloseTo(0, 9);
    expect(a.ray.direction.y).toBeCloseTo(1, 9);
    expect(a.ray.origin.distanceTo(b.ray.origin)).toBeGreaterThan(0.1);
  });
  it('is perspective until asked, and then scales apparent sizes by the target distance', () => {
    const c = camera();
    expect(isOrthographic(c)).toBe(false);
    expect(scaleDistance(c, 7)).toBe(7);
    c.userData.orthographic = true;
    applyOrthographic(c, 5);
    expect(scaleDistance(c, 7)).toBe(5);
  });
});
