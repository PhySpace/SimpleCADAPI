/** The "ghost pass": a faint second drawing of an overlay object with the depth test OFF, so the overlay stays
 * findable when the model hides it, but clearly behind (low opacity).  The normal pass (depth tested, opaque)
 * is the object's own materials.
 *
 * Usage: build the object with ordinary depth-tested materials, then `addGhostPass(object)`.  Meshes flagged
 * `userData.noGhost` (outline hulls, hit areas) get no ghost.  The ghost meshes are children of their source
 * mesh (identity transform), so they follow every later change of the source's transform or visibility. */

import * as THREE from 'three';

export const GHOST_OPACITY = 0.22;
/** Ghosts draw before the normal pass so the depth-tested pass lands on top where both are visible. */
export const GHOST_RENDER_ORDER = 8;
export const NORMAL_RENDER_ORDER = 12;

/** A ghost version of a material: same colour and side, depth test off, translucent. */
export function ghostMaterial(source: THREE.Material, opacity = GHOST_OPACITY): THREE.Material {
  const material = source.clone();
  const base = source.opacity < 1 ? source.opacity : 1;
  material.transparent = true;
  material.opacity = Math.min(1, base * opacity);
  material.depthTest = false;
  material.depthWrite = false;
  material.name = `${source.name || 'material'}:ghost`;
  return material;
}

/** Add a ghost child to every mesh under `root` (see the file header); returns the ghosts created.
 * Also sets the normal pass's render order so ghosts are drawn first. */
export function addGhostPass(root: THREE.Object3D, opacity = GHOST_OPACITY): THREE.Mesh[] {
  const sources: THREE.Mesh[] = [];
  root.traverse((object) => {
    if (object instanceof THREE.Mesh && !object.userData.noGhost && !object.userData.ghost && !object.userData.hitArea) sources.push(object);
  });
  const ghosts: THREE.Mesh[] = [];
  for (const source of sources) {
    const ghost = new THREE.Mesh(
      source.geometry,
      Array.isArray(source.material) ? source.material.map((m) => ghostMaterial(m, opacity)) : ghostMaterial(source.material, opacity),
    );
    ghost.userData.ghost = true;
    ghost.renderOrder = GHOST_RENDER_ORDER;
    source.renderOrder = NORMAL_RENDER_ORDER;
    source.add(ghost);
    ghosts.push(ghost);
  }
  return ghosts;
}
