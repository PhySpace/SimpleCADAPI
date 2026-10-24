// Embeddable entry for the Scene Viewer's BRep renderer.
//
// Serves two consumers:
//  - gif-harness.html (dev server): mounts a package's scene projection and
//    exposes deterministic camera aiming for turntable frame capture.
//  - Future embeds (release notes, replay demos) get the same mountScene API.
//
// Everything except mountScene/openCadPackage is considered capture tooling.

import * as THREE from 'three';
import { SceneView } from './scene-view';
import { openCadPackage } from './product-package';
import type { PackageFiles } from './product-package';

export { openCadPackage, SceneView };

export type MountOptions = {
  background?: string;
  interactive?: boolean;
};

export async function mountScene(
  host: HTMLElement,
  files: PackageFiles,
  options: MountOptions = {},
): Promise<SceneView> {
  const view = new SceneView(host, {
    background: options.background ?? '#0b0e12',
    interactive: options.interactive ?? true,
  });
  await view.loadScene(files);
  view.frame();
  return view;
}

function aim(view: SceneView, direction: THREE.Vector3, distanceFactor: number): void {
  const box = new THREE.Box3().setFromObject(view.modelRoot);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() * 0.5, 0.01);
  view.camera.position.copy(center).addScaledVector(direction.clone().normalize(), radius * distanceFactor);
  view.camera.updateProjectionMatrix();
  view.controls.target.copy(center);
  view.controls.update();
}

/** Camera helpers shared by the harness and future embeds. */
export const utils = {
  setIso(view: SceneView, distanceFactor = 2.6): void {
    aim(view, new THREE.Vector3(1, 0.78, 1), distanceFactor);
  },
  /** Azimuth degrees around +Z (CAD up), elevation degrees above the XY plane. */
  setAzimuth(view: SceneView, azimuthDeg: number, elevationDeg = 26, distanceFactor = 2.6): void {
    const az = (azimuthDeg * Math.PI) / 180;
    const el = (elevationDeg * Math.PI) / 180;
    aim(view, new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el)), distanceFactor);
  },
  setWireframe(view: SceneView, on: boolean): void {
    view.modelRoot.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const material of materials) {
        const standard = material as THREE.MeshStandardMaterial;
        if ('wireframe' in standard) standard.wireframe = on;
      }
    });
  },
};

const global = globalThis as unknown as Record<string, unknown>;
global.ScadEmbed = { mountScene, openCadPackage, SceneView, utils };
