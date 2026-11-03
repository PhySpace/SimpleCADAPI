/** AxisTriad: the X red / Y green / Z blue arrow set with an origin dot and a contact-plane square, as a three.js
 * object factory (no scene access, no React).
 *
 * CONTRACT
 *  - The object is built in UNIT size, in the frame's own axes: +X, +Y, +Z are the arrows (X and Y are 1 long, Z is
 *    `zLength` long: the connection direction), the square lies in the XY plane.  Scale the object to the wanted world
 *    size, pose it with `cadFramePose` (scene/cad-pose.ts), and put it in a SceneLayer.
 *  - Two passes: the normal depth-tested drawing, and (`ghost`) a faint always-visible second pass (scene/layers/ghost.ts),
 *    so a triad hidden behind the model is still findable but clearly behind.
 *  - Every stroke has a thin dark outline (an inverted hull) so it stays visible over a white model and on both scene
 *    backgrounds.  Colours are the fixed constants of ./axis-colors, never theme tokens.
 *  - `setState({hover, selected, active})` thickens the arrows and the square's border and turns the border and the dot
 *    to the highlight colour.
 *  - Hit areas (invisible, generous) are children flagged `userData.hitArea`; `SceneLayer.pick` answers them. */

import * as THREE from 'three';

import { addGhostPass } from '@/scene/layers/ghost';
import { hitSegment, hitSphere } from '@/scene/layers/pick';
import { AXIS_COLORS, AXIS_HIGHLIGHT, AXIS_OUTLINE, AXIS_Z } from './axis-colors';

export type AxisTriadOptions = {
  /** Length of the Z arrow relative to X and Y (default 1.7). */
  zLength?: number;
  /** The contact plane: a square (default), a circle, or none. */
  plane?: 'square' | 'circle' | false;
  /** Add the faint always-visible second pass (default true). */
  ghost?: boolean;
  /** Add invisible hit areas for picking (default true). */
  pickable?: boolean;
};

export type TriadState = { hover: boolean; selected: boolean; active: boolean };

export interface AxisTriad {
  readonly object: THREE.Group;
  setState(state: TriadState): void;
}

const SHAFT_R = 0.03;
const HEAD_R = 0.09;
const HEAD_LEN = 0.28;
const OUTLINE = 0.022;
const PLANE_HALF = 0.62;
const POLY = { polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 } as const;

const basic = (color: string, extra: THREE.MeshBasicMaterialParameters = {}) => new THREE.MeshBasicMaterial({ color, ...POLY, ...extra });

function arrow(length: number, color: string): THREE.Group {
  const group = new THREE.Group();
  const shaftLength = length - HEAD_LEN;
  const fill = basic(color);
  const hull = basic(AXIS_OUTLINE, { side: THREE.BackSide });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(SHAFT_R, SHAFT_R, shaftLength, 10).translate(0, shaftLength / 2, 0), fill);
  const head = new THREE.Mesh(new THREE.ConeGeometry(HEAD_R, HEAD_LEN, 16).translate(0, length - HEAD_LEN / 2, 0), fill);
  const shaftHull = new THREE.Mesh(new THREE.CylinderGeometry(SHAFT_R + OUTLINE, SHAFT_R + OUTLINE, shaftLength, 10).translate(0, shaftLength / 2, 0), hull);
  const headHull = new THREE.Mesh(new THREE.ConeGeometry(HEAD_R + OUTLINE, HEAD_LEN + OUTLINE, 16).translate(0, length - HEAD_LEN / 2 + OUTLINE / 2, 0), hull);
  shaftHull.userData.noGhost = headHull.userData.noGhost = true;
  group.add(shaftHull, headHull, shaft, head);
  return group;
}

/** A flat ring (or disc, inner 0) in the XY plane; a 4-sided ring rotated 45 degrees is an axis-aligned square. */
function plane(kind: 'square' | 'circle', half: number, inner: number, material: THREE.Material, z = 0): THREE.Mesh {
  const square = kind === 'square';
  const radius = square ? half * Math.SQRT2 : half;
  const geometry = new THREE.RingGeometry(inner * (square ? Math.SQRT2 : 1), radius, square ? 4 : 64, 1);
  if (square) geometry.rotateZ(Math.PI / 4);
  geometry.translate(0, 0, z);
  return new THREE.Mesh(geometry, material);
}

export function createAxisTriad(options: AxisTriadOptions = {}): AxisTriad {
  const { zLength = 1.7, plane: planeKind = 'square', ghost = true, pickable = true } = options;
  const object = new THREE.Group();
  object.name = 'axis-triad';

  const lengths = [1, 1, zLength];
  const arrows: THREE.Group[] = [];
  AXIS_COLORS.forEach((color, i) => {
    const holder = new THREE.Group();
    const inner = arrow(lengths[i], color);
    holder.add(inner);
    // The arrow is built along +Y: turn +Y onto +X, +Y, +Z.
    if (i === 0) holder.rotation.z = -Math.PI / 2;
    if (i === 2) holder.rotation.x = Math.PI / 2;
    arrows.push(inner);
    object.add(holder);
  });

  const dotMaterial = basic('#ffffff');
  const dot = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), dotMaterial);
  const dotHull = new THREE.Mesh(new THREE.SphereGeometry(0.1 + OUTLINE, 16, 12), basic(AXIS_OUTLINE, { side: THREE.BackSide }));
  dotHull.userData.noGhost = true;
  object.add(dotHull, dot);

  let fillMaterial: THREE.MeshBasicMaterial | null = null;
  let thin: THREE.Mesh | null = null;
  let thick: THREE.Mesh | null = null;
  if (planeKind) {
    fillMaterial = basic(AXIS_Z, { transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false });
    const fill = plane(planeKind, PLANE_HALF, 0, fillMaterial);
    fill.renderOrder = 9;
    thin = plane(planeKind, PLANE_HALF, PLANE_HALF - 0.025, basic(AXIS_Z, { side: THREE.DoubleSide }));
    thick = plane(planeKind, PLANE_HALF + 0.03, PLANE_HALF - 0.05, basic(AXIS_HIGHLIGHT, { side: THREE.DoubleSide }));
    thick.visible = false;
    object.add(fill, thin, thick);
  }

  if (pickable) {
    object.add(hitSphere(0.4));
    const origin = new THREE.Vector3();
    object.add(hitSegment(origin, new THREE.Vector3(lengths[0], 0, 0), 0.22));
    object.add(hitSegment(origin, new THREE.Vector3(0, lengths[1], 0), 0.22));
    object.add(hitSegment(origin, new THREE.Vector3(0, 0, lengths[2]), 0.22));
    if (planeKind) {
      const pad = hitSphere(PLANE_HALF * 0.9);
      pad.scale.z = 0.12; // a flat pad over the contact plane
      object.add(pad);
    }
  }

  if (ghost) addGhostPass(object);

  const setState = (state: TriadState): void => {
    const emphasised = state.hover || state.selected || state.active;
    for (const a of arrows) a.scale.set(emphasised ? 1.8 : 1, 1, emphasised ? 1.8 : 1);
    dotMaterial.color.set(emphasised ? AXIS_HIGHLIGHT : '#ffffff');
    dot.scale.setScalar(emphasised ? 1.5 : 1);
    if (thin && thick) {
      thin.visible = !emphasised;
      thick.visible = emphasised;
    }
    if (fillMaterial) fillMaterial.opacity = emphasised ? 0.22 : 0.1;
  };
  setState({ hover: false, selected: false, active: false });
  return { object, setState };
}
