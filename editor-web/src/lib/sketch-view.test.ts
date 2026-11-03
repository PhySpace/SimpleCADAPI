import * as THREE from "three";
import { describe, expect, it } from "vitest";

import type { Frame } from "@/lib/sketch-plane";
import { cameraSignature, fitDistanceMm, planeToScreen, scaleAt, screenToPlane, type Viewer } from "@/lib/sketch-view";

function viewer(position: [number, number, number], target: [number, number, number], up: [number, number, number], width = 800, height = 600): Viewer {
  const camera = new THREE.PerspectiveCamera(40, width / height, 0.001, 100);
  camera.up.set(...up);
  camera.position.set(...position);
  camera.lookAt(...target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
  return { camera, width, height };
}

describe("plane <-> screen through a camera", () => {
  it("the target of a straight-on camera projects to the centre and the axes follow screen right and up", () => {
    const v = viewer([0, 0, 1], [0, 0, 0], [0, 1, 0]);
    const o = planeToScreen(v, "XY", 0, 0)!;
    expect(o[0]).toBeCloseTo(400, 4);
    expect(o[1]).toBeCloseTo(300, 4);
    const right = planeToScreen(v, "XY", 10, 0)!;
    const up = planeToScreen(v, "XY", 0, 10)!;
    expect(right[0]).toBeGreaterThan(o[0]);
    expect(right[1]).toBeCloseTo(o[1], 4);
    expect(up[1]).toBeLessThan(o[1]);
    expect(up[0]).toBeCloseTo(o[0], 4);
  });
  it("screenToPlane inverts planeToScreen on a named plane, a face frame and an oblique camera", () => {
    const frame: Frame = { origin: [100, 50, 20], x_axis: [1, 0, 0], y_axis: [0, 1, 0] };
    for (const [plane, cam] of [
      ["XY", viewer([0.05, -0.1, 0.4], [0, 0, 0], [0, 1, 0])],
      [frame, viewer([0.4, 0.3, 0.5], [0.1, 0.05, 0.02], [0, 0, 1])],
      ["XZ", viewer([0.3, -0.5, 0.2], [0, 0, 0], [0, 0, 1])],
    ] as const) {
      for (const [u, w] of [[0, 0], [20, -15], [-33, 41]]) {
        const s = planeToScreen(cam, plane, u, w)!;
        const back = screenToPlane(cam, plane, s[0], s[1])!;
        expect(back[0]).toBeCloseTo(u, 3);
        expect(back[1]).toBeCloseTo(w, 3);
      }
    }
  });
  it("looking along -normal with up = y gives a similarity: equal scale on both axes", () => {
    const v = viewer([0, 0, 0.5], [0, 0, 0], [0, 1, 0]);
    const a = planeToScreen(v, "XY", 0, 0)!;
    const b = planeToScreen(v, "XY", 10, 0)!;
    const c = planeToScreen(v, "XY", 0, 10)!;
    expect(Math.hypot(b[0] - a[0], b[1] - a[1])).toBeCloseTo(Math.hypot(c[0] - a[0], c[1] - a[1]), 4);
    expect(scaleAt(v, "XY", 0, 0)).toBeCloseTo(Math.hypot(b[0] - a[0], b[1] - a[1]) / 10, 4);
  });
  it("a ray that cannot reach the plane gives null, and a point behind the camera has no screen position", () => {
    const v = viewer([0, 0, 1], [0, 0, 2], [0, 1, 0]);
    expect(planeToScreen(v, "XY", 0, 0)).toBeNull();
    const ground = viewer([0, 0, 1], [1, 0, 1], [0, 0, 1]);
    expect(screenToPlane(ground, "XY", 400, 300)).toBeNull();
  });
  it("the signature changes with the camera and the size", () => {
    const v = viewer([0, 0, 1], [0, 0, 0], [0, 1, 0]);
    const before = cameraSignature(v);
    expect(cameraSignature(v)).toBe(before);
    v.camera.position.x = 0.1;
    expect(cameraSignature(v)).not.toBe(before);
    expect(cameraSignature({ ...v, width: 801 })).not.toBe(cameraSignature(v));
  });
  it("fits an extent into the view", () => {
    expect(fitDistanceMm(100, 40, 1.33)).toBeGreaterThan(fitDistanceMm(50, 40, 1.33));
    expect(fitDistanceMm(100, 40, 0.5)).toBeGreaterThan(fitDistanceMm(100, 40, 2));
  });
});
