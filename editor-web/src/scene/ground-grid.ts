/** The ground of the viewport: a grid on the XY plane (z = 0) drawn per pixel, and the X, Y and Z axes as lines through
 * the origin as long as the camera sees.
 *
 * The grid's spacing follows the screen, not the model: at each pixel the finest power-of-ten spacing (metres: 1 mm,
 * 1 cm, 10 cm ...) whose cells are at least `MIN_CELL_PX` wide is drawn faint, the next one (ten times wider) strong,
 * and the two fade into each other as the camera moves, so zooming never pops a level and a grazing view thins its far
 * side out instead of shimmering.  It fades out around the target, a few camera distances away. */

import * as THREE from 'three';
import { MeshBasicNodeMaterial } from 'three/webgpu';
import { abs, float, floor, fract, fwidth, length, log, max, min, mix, positionWorld, pow, smoothstep, uniform, vec2 } from 'three/tsl';

import { LineMaterial, LineSegments2, LineSegmentsGeometry } from './fat-lines';
import type { ScenePalette } from './theme';

/** The finest cells drawn are about this wide on screen (pixels). */
const MIN_CELL_PX = 9;
/** Where the grid has faded out, in camera distances from the target. */
const REACH = 7;

export class GroundGrid {
  readonly object = new THREE.Group();
  private readonly color = uniform(new THREE.Color());
  private readonly minorAlpha = uniform(0.3);
  private readonly majorAlpha = uniform(0.7);
  private readonly center = uniform(new THREE.Vector2());
  private readonly reach = uniform(1);
  private readonly plane: THREE.Mesh;
  private readonly axes: LineSegments2[] = [];

  constructor(palette: ScenePalette, layer: number) {
    const p = positionWorld.xy;
    const perPixel = max(fwidth(p), vec2(1e-9));
    const lod = log(max(perPixel.x, perPixel.y).mul(MIN_CELL_PX)).div(Math.LN10);
    const blend = fract(lod);
    const fine = pow(float(10), floor(lod));
    // coverage of the lines every `spacing` metres: 1 on a line, 0 a pixel and more away from it
    const lines = (spacing: typeof fine, widthPx: number) => {
      const offPx = abs(fract(p.div(spacing).sub(0.5)).sub(0.5)).mul(spacing).div(perPixel);
      return float(1).sub(smoothstep(widthPx * 0.5 - 0.5, widthPx * 0.5 + 0.5, min(offPx.x, offPx.y)));
    };
    const minor = this.minorAlpha;
    const major = this.majorAlpha;
    const alpha = max(
      max(lines(fine, 1).mul(minor).mul(float(1).sub(blend)), lines(fine.mul(10), 1.25).mul(mix(major, minor, blend))),
      lines(fine.mul(100), 1.25).mul(major).mul(blend),
    );
    const fade = float(1).sub(smoothstep(this.reach.mul(0.45), this.reach, length(p.sub(this.center))));
    const material = new MeshBasicNodeMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
    material.colorNode = this.color;
    material.opacityNode = alpha.mul(fade);
    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    this.plane.name = 'ground-grid';
    this.plane.raycast = () => {};
    this.plane.renderOrder = -2;
    this.object.add(this.plane);

    [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)].forEach((dir) => {
      const geometry = new LineSegmentsGeometry();
      geometry.setPositions([-dir.x, -dir.y, -dir.z, dir.x, dir.y, dir.z]);
      const line = new LineSegments2(geometry, new LineMaterial({ linewidth: 1.5, transparent: true, opacity: 0.85, depthWrite: false }));
      line.name = 'ground-axis';
      line.raycast = () => {};
      line.renderOrder = -1;
      line.frustumCulled = false;
      this.axes.push(line);
      this.object.add(line);
    });
    this.object.name = 'ground';
    this.object.userData.pickable = false;
    this.object.traverse((child) => child.layers.set(layer));
    this.setPalette(palette);
  }

  setPalette(palette: ScenePalette): void {
    this.color.value.set(palette.grid);
    this.minorAlpha.value = palette.gridMinorAlpha;
    this.majorAlpha.value = palette.gridMajorAlpha;
    this.axes.forEach((line, index) => (line.material as LineMaterial).color.set(palette.axes[index]));
  }

  /** Follow the camera: the grid is centred under the target and reaches a few camera distances; the axes reach as far
   * as the camera sees. */
  update(camera: THREE.PerspectiveCamera, target: THREE.Vector3): void {
    const distance = camera.position.distanceTo(target);
    const reach = distance * REACH;
    this.center.value.set(target.x, target.y);
    this.reach.value = reach;
    this.plane.position.set(target.x, target.y, 0);
    this.plane.scale.setScalar(reach);
    this.plane.updateMatrixWorld();
    for (const line of this.axes) {
      line.scale.setScalar(camera.far + camera.position.length());
      line.updateMatrixWorld();
    }
  }

  dispose(): void {
    this.plane.geometry.dispose();
    (this.plane.material as THREE.Material).dispose();
    for (const line of this.axes) {
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    }
  }
}
