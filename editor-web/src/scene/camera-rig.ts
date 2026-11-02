// Direct camera control for sketch mode: the viewport's trackball is parked and the sketch overlay drives the camera
// (orbit, pan, dolly toward the cursor, an animated turn to look at a plane).  Units are the scene's: metres, CAD frame, Z up.

import * as THREE from 'three';
import type { BRepRenderer } from './renderer';

export type Pose = { position: THREE.Vector3; target: THREE.Vector3; up: THREE.Vector3 };

type Trackball = {
  _movePrev: THREE.Vector2; _moveCurr: THREE.Vector2; _lastAngle: number;
  _zoomStart: THREE.Vector2; _zoomEnd: THREE.Vector2;
  _panStart: THREE.Vector2; _panEnd: THREE.Vector2;
};

export class CameraRig {
  private animation = 0;
  private saved: { min: number; max: number } | null = null;

  constructor(private readonly engine: BRepRenderer) {}

  private get camera() { return this.engine.camera; }
  private get controls() { return this.engine.controls; }

  /** Park the trackball (sketch mode) or give the camera back to it. */
  setManual(on: boolean): void {
    this.cancelAnimation();
    if (on) {
      this.saved ??= { min: this.controls.minDistance, max: this.controls.maxDistance };
      this.controls.minDistance = 1e-5;
      this.controls.maxDistance = 1e5;
      this.controls.enabled = false;
    } else {
      if (this.saved) {
        this.controls.minDistance = this.saved.min;
        this.controls.maxDistance = this.saved.max;
        this.saved = null;
      }
      this.controls.enabled = true;
    }
    this.settle();
  }

  /** Kill the trackball's inertia, which would otherwise keep rolling a camera that was placed by hand. */
  private settle(): void {
    const t = this.controls as unknown as Trackball;
    t._movePrev.copy(t._moveCurr);
    t._lastAngle = 0;
    t._zoomStart.copy(t._zoomEnd);
    t._panStart.copy(t._panEnd);
  }

  get pose(): Pose {
    return { position: this.camera.position.clone(), target: this.controls.target.clone(), up: this.camera.up.clone() };
  }

  distance(): number {
    return this.camera.position.distanceTo(this.controls.target);
  }

  set(pose: Pose): void {
    this.camera.position.copy(pose.position);
    this.camera.up.copy(pose.up).normalize();
    this.controls.target.copy(pose.target);
    this.camera.lookAt(pose.target);
    this.camera.updateMatrixWorld(true);
    this.settle();
    this.engine.invalidate();
  }

  cancelAnimation(): void {
    if (this.animation) cancelAnimationFrame(this.animation);
    this.animation = 0;
  }

  /** Move to a pose over `ms` (eased); resolves when it arrives or is replaced. */
  animateTo(to: Pose, ms = 450): Promise<void> {
    this.cancelAnimation();
    const from = this.pose;
    const start = performance.now();
    return new Promise((resolve) => {
      const step = (now: number) => {
        const k = Math.min(1, (now - start) / Math.max(ms, 1));
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        this.set({
          position: from.position.clone().lerp(to.position, e),
          target: from.target.clone().lerp(to.target, e),
          up: from.up.clone().lerp(to.up, e),
        });
        if (k < 1) this.animation = requestAnimationFrame(step);
        else {
          this.animation = 0;
          this.set(to);
          resolve();
        }
      };
      this.animation = requestAnimationFrame(step);
    });
  }

  /** Free (trackball-like) rotation about the target; `dx`, `dy` in radians. */
  orbit(dx: number, dy: number): void {
    const camera = this.camera;
    camera.updateMatrixWorld(true);
    const target = this.controls.target;
    const eye = camera.position.clone().sub(target);
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    const up = camera.up.clone().normalize();
    const q = new THREE.Quaternion()
      .setFromAxisAngle(up, -dx)
      .multiply(new THREE.Quaternion().setFromAxisAngle(right, -dy));
    eye.applyQuaternion(q);
    camera.up.copy(up.applyQuaternion(q)).normalize();
    this.set({ position: target.clone().add(eye), target: target.clone(), up: camera.up.clone() });
  }

  /** Slide the view by a pixel delta (the scene follows the cursor). */
  pan(dxPx: number, dyPx: number, height: number): void {
    const camera = this.camera;
    camera.updateMatrixWorld(true);
    const perPixel = (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * this.distance()) / Math.max(height, 1);
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize();
    const move = right.multiplyScalar(-dxPx * perPixel).add(up.multiplyScalar(dyPx * perPixel));
    this.set({ position: camera.position.clone().add(move), target: this.controls.target.clone().add(move), up: camera.up.clone() });
  }

  /** Dolly by `factor` (< 1 moves in) toward a world point (metres), so the point under the cursor stays under it. */
  dolly(factor: number, anchor?: THREE.Vector3 | null): void {
    const camera = this.camera;
    const target = this.controls.target;
    const distance = THREE.MathUtils.clamp(this.distance() * factor, 0.002, 500);
    const k = distance / Math.max(this.distance(), 1e-9);
    const about = anchor ?? target;
    const position = about.clone().add(camera.position.clone().sub(about).multiplyScalar(k));
    const nextTarget = about.clone().add(target.clone().sub(about).multiplyScalar(k));
    this.set({ position, target: nextTarget, up: camera.up.clone() });
  }
}
