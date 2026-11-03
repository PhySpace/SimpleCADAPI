import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { CAD_TO_GLTF_ROTATION, cadFramePose, connectorSizeMm, orthonormalBasis } from "./cad-pose";
import { placementMatrix } from "./cad-three";

const near = (v: THREE.Vector3, x: number, y: number, z: number) => {
  expect(v.x).toBeCloseTo(x, 9);
  expect(v.y).toBeCloseTo(y, 9);
  expect(v.z).toBeCloseTo(z, 9);
};
/** Where the frame's local unit axes end up in glTF. */
const axes = (q: THREE.Quaternion) => [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)].map((v) => v.applyQuaternion(q));

describe("cadFramePose", () => {
  it("maps CAD mm / Z-up to glTF metres / Y-up", () => {
    const pose = cadFramePose({ origin: [10, 20, 30], x_axis: [1, 0, 0], y_axis: [0, 1, 0] })!;
    near(pose.position, 0.01, 0.03, -0.02); // (x, z, -y) / 1000
    const [x, y, z] = axes(pose.quaternion);
    near(x, 1, 0, 0); // CAD x -> glTF x
    near(y, 0, 0, -1); // CAD y -> glTF -z
    near(z, 0, 1, 0); // CAD z (up) -> glTF +y (up)
  });

  it("a top face connector (Z up, X along the long edge) keeps X on x and Z up", () => {
    const pose = cadFramePose({ origin: [0, 0, 20], x_axis: [1, 0, 0], y_axis: [0, 1, 0] })!;
    const [x, , z] = axes(pose.quaternion);
    near(x, 1, 0, 0);
    near(z, 0, 1, 0);
    near(pose.position, 0, 0.02, 0);
  });

  it("a side frame: x=(0,1,0) y=(0,0,1) gives z=+X in CAD", () => {
    const pose = cadFramePose({ origin: [20, 0, 10], x_axis: [0, 1, 0], y_axis: [0, 0, 1] })!;
    const [x, y, z] = axes(pose.quaternion);
    near(x, 0, 0, -1); // CAD +y -> glTF -z
    near(y, 0, 1, 0); // CAD +z -> glTF +y
    near(z, 1, 0, 0); // CAD +x -> glTF +x
  });

  it("agrees with placementMatrix (the viewer's own node transform) applied to the frame's origin and axes", () => {
    const frame = { origin: [5, -7, 12] as [number, number, number], x_axis: [0, 1, 0] as [number, number, number], y_axis: [0, 0, 1] as [number, number, number], z_axis: [1, 0, 0] as [number, number, number] };
    const pose = cadFramePose(frame)!;
    const m = placementMatrix(frame);
    // placementMatrix maps glTF part coords to glTF world coords; the part frame's origin (0) goes to the frame origin
    near(new THREE.Vector3().applyMatrix4(m), pose.position.x, pose.position.y, pose.position.z);
    // a CAD-oriented local axis goes to glTF (CAD_TO_GLTF_ROTATION), then through the node's own transform
    const rot = new THREE.Quaternion().setFromRotationMatrix(m).multiply(CAD_TO_GLTF_ROTATION);
    const [a, b, c] = axes(pose.quaternion);
    near(a, ...(new THREE.Vector3(1, 0, 0).applyQuaternion(rot).toArray() as [number, number, number]));
    near(b, ...(new THREE.Vector3(0, 1, 0).applyQuaternion(rot).toArray() as [number, number, number]));
    near(c, ...(new THREE.Vector3(0, 0, 1).applyQuaternion(rot).toArray() as [number, number, number]));
  });

  it("orthonormalises sloppy axes and rejects degenerate ones", () => {
    const b = orthonormalBasis({ x_axis: [2, 0, 0], y_axis: [1, 3, 0] })!;
    near(b.x, 1, 0, 0);
    near(b.y, 0, 1, 0);
    near(b.z, 0, 0, 1);
    expect(orthonormalBasis({ x_axis: [0, 0, 0], y_axis: [0, 1, 0] })).toBeNull();
    expect(orthonormalBasis({ x_axis: [1, 0, 0], y_axis: [2, 0, 0] })).toBeNull();
    near(orthonormalBasis({ x_axis: [1, 0, 0], y_axis: [2, 0, 0], z_axis: [0, 0, 5] })!.z, 0, 0, 1);
    expect(cadFramePose({ origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [1, 0, 0] })).toBeNull();
  });
});

describe("connectorSizeMm", () => {
  const box = (e: number) => ({ min: [0, 0, 0] as [number, number, number], max: [e, e / 2, e / 4] as [number, number, number] });
  it("is 12% of the largest extent, clamped", () => {
    expect(connectorSizeMm(box(100))).toBeCloseTo(12, 9);
    expect(connectorSizeMm(box(10))).toBe(2); // clamped up
    expect(connectorSizeMm(box(100000))).toBe(150); // clamped down (1 m+)
    expect(connectorSizeMm(box(1000))).toBeCloseTo(120, 9);
  });
  it("falls back without bounds", () => {
    expect(connectorSizeMm(null)).toBe(10);
    expect(connectorSizeMm({ min: [0, 0, 0], max: [0, 0, 0] })).toBe(10);
  });
});
