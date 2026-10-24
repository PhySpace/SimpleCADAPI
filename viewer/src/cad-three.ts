// Shared CAD<->glTF three.js helpers, extracted from main.ts so the package
// viewer and the reverse-engineering mode load scenes through one code path.

import * as THREE from 'three';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import type { SceneNode, Transform, Vec3 } from './scene2';

export const CAD_TO_GLTF = new THREE.Matrix4().set(0.001, 0, 0, 0, 0, 0, 0.001, 0, 0, -0.001, 0, 0, 0, 0, 0, 1);
export const GLTF_TO_CAD = new THREE.Matrix4().set(1000, 0, 0, 0, 0, 0, -1000, 0, 0, 1000, 0, 0, 0, 0, 0, 1);

export function placementMatrix(transform: Transform): THREE.Matrix4 {
  const { origin, x_axis, y_axis, z_axis } = transform;
  const cad = new THREE.Matrix4().set(
    x_axis[0], y_axis[0], z_axis[0], origin[0],
    x_axis[1], y_axis[1], z_axis[1], origin[1],
    x_axis[2], y_axis[2], z_axis[2], origin[2],
    0, 0, 0, 1,
  );
  return CAD_TO_GLTF.clone().multiply(cad).multiply(GLTF_TO_CAD);
}

export function cadPointToGltf(point: Vec3): THREE.Vector3 {
  return new THREE.Vector3(point[0] / 1000, point[2] / 1000, -point[1] / 1000);
}

export const CAD_EDGE_LINE_WIDTH = 2.4;
/** Explicit dark edge color — must read as a firm outline on the lit body
 * while staying distinguishable from the pure-black viewport background. */
export const CAD_EDGE_COLOR = '#3a414d';
export const DEFAULT_BASE_COLOR: [number, number, number, 1] = [0.72, 0.75, 0.78, 1];

export type Resolution = { width: number; height: number };

export function materialFor(node: SceneNode): THREE.MeshStandardMaterial {
  const color = node.material_id ? [0.68, 0.78, 0.88, 1] as const : DEFAULT_BASE_COLOR;
  // Faces are pushed back in depth: edge lines lie exactly ON the surface, and
  // without the offset the face triangles win the depth fight per-pixel —
  // edges render as broken dashed fragments (classic CAD z-fighting).
  return new THREE.MeshStandardMaterial({ color: new THREE.Color(color[0], color[1], color[2]), metalness: 0.08, roughness: 0.52, side: THREE.FrontSide, transparent: color[3] < 1, opacity: color[3], polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
}

export function edgeMaterial(resolution: Resolution): LineMaterial {
  // Negative slope-scaled polygon offset: at silhouettes the line runs along
  // a surface seen edge-on and parts of its quad sit genuinely behind the
  // local surface depth — a constant bias loses there, a slope-scaled pull
  // (mirror of the faces' +1 push) wins at every viewing angle.
  const material = new LineMaterial({ color: CAD_EDGE_COLOR, linewidth: CAD_EDGE_LINE_WIDTH, worldUnits: false, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  material.resolution.set(Math.max(resolution.width, 1), Math.max(resolution.height, 1));
  return material;
}

export function addWideEdgeVisual(source: THREE.LineSegments, resolution: Resolution): void {
  const position = source.geometry.getAttribute('position');
  const index = source.geometry.index;
  const indexCount = index?.count ?? position.count;
  const positions: number[] = [];
  for (let offset = 0; offset + 1 < indexCount; offset += 2) {
    const a = index ? index.getX(offset) : offset;
    const b = index ? index.getX(offset + 1) : offset + 1;
    positions.push(position.getX(a), position.getY(a), position.getZ(a), position.getX(b), position.getY(b), position.getZ(b));
  }
  const geometry = new LineSegmentsGeometry();
  geometry.setPositions(positions);
  const visual = new LineSegments2(geometry, edgeMaterial(resolution));
  visual.name = 'cad-edge-visual';
  visual.userData.pickable = false;
  source.add(visual);
  const pickingMaterial = new THREE.LineBasicMaterial();
  pickingMaterial.visible = false;
  source.material = pickingMaterial;
}

export function disposeObject(root: THREE.Object3D): void {
  const disposedGeometries = new Set<THREE.BufferGeometry>();
  const disposedMaterials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments || object instanceof THREE.Points) {
      if (!disposedGeometries.has(object.geometry)) {
        object.geometry.dispose();
        disposedGeometries.add(object.geometry);
      }
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material) => {
        if (!disposedMaterials.has(material)) {
          material.dispose();
          disposedMaterials.add(material);
        }
      });
    }
  });
}
