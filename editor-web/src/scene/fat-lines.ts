/** Wide lines (CAD edges, sketch curves, highlight outlines) for the WebGPU renderer: three's node-material lines behind
 * the interface the editor used with the WebGL ones (`LineMaterial` with `color`, `linewidth`, `resolution`, `opacity`),
 * so the scene code keeps building lines the same way.
 *
 * `edgeDepthBias` (scene units, metres) pulls a line's fragments towards the camera by that distance, in perspective and
 * orthographic projection alike: faces and edges are tessellated apart, a chord of the face mesh can bulge past the edge
 * polyline, and a slope-scaled offset cannot cover a distance.  Only depth moves; the line stays where it is on screen. */

import * as THREE from 'three';
import { Line2NodeMaterial } from 'three/webgpu';
import {
  cameraProjectionMatrix,
  cameraWorldMatrix,
  float,
  modelViewMatrix,
  modelWorldMatrixInverse,
  positionLocal,
  select,
  vec3,
  vec4,
} from 'three/tsl';

export { LineSegments2 } from 'three/addons/lines/webgpu/LineSegments2.js';
export { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';

export type LineMaterialParameters = {
  color?: THREE.ColorRepresentation;
  linewidth?: number;
  worldUnits?: boolean;
  transparent?: boolean;
  opacity?: number;
  depthTest?: boolean;
  depthWrite?: boolean;
  polygonOffset?: boolean;
  polygonOffsetFactor?: number;
  polygonOffsetUnits?: number;
  dashed?: boolean;
  dashSize?: number;
  gapSize?: number;
  /** Pull the fragments towards the camera by this distance (metres): see the module comment. */
  edgeDepthBias?: number;
};

export class LineMaterial extends Line2NodeMaterial {
  /** Kept for the callers that set it: node lines take the viewport's size themselves. */
  readonly resolution = new THREE.Vector2(1, 1);
  private readonly edgeDepthBias: number;

  constructor(parameters: LineMaterialParameters = {}) {
    const { edgeDepthBias, color, ...rest } = parameters;
    super({ ...rest, color: color === undefined ? undefined : new THREE.Color(color) } as ConstructorParameters<typeof Line2NodeMaterial>[0]);
    this.edgeDepthBias = edgeDepthBias ?? 0;
    // node lines default to no blending: a transparent line blends like any other material
    if (parameters.transparent) this.blending = THREE.NormalBlending;
  }

  /** The expanded line vertex, moved `edgeDepthBias` towards the camera along its view ray (perspective) or the view
   * axis (orthographic): either way it stays where it is on screen. */
  setupPosition(builder: Parameters<Line2NodeMaterial['setupPosition']>[0]) {
    const local = super.setupPosition(builder);
    if (!this.edgeDepthBias) return local;
    const bias = float(this.edgeDepthBias);
    const view = modelViewMatrix.mul(vec4(positionLocal, 1)).xyz;
    // perspective projections have -1 at [2][3] (column 2, row 3); orthographic ones 0
    // (`element` indexes a matrix node at run time; the typings do not declare it)
    const projection = cameraProjectionMatrix as unknown as { element(i: number): { element(j: number): ReturnType<typeof float> } };
    const perspective = projection.element(2).element(3).equal(-1);
    const pulled = select(perspective, view.mul(float(1).sub(bias.div(view.length()))), view.add(vec3(0, 0, bias)));
    positionLocal.assign(modelWorldMatrixInverse.mul(cameraWorldMatrix).mul(vec4(pulled, 1)).xyz);
    return positionLocal;
  }
}
