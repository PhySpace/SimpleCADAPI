// The sketches of the notebook as real objects of the 3D scene, drawn in their own plane frames.
//
// Why scene objects and not an SVG overlay: a sketch lies ON the model (a face it was drawn on, the base of the block it was
// extruded into).  Depth-tested lines are hidden by the model exactly where the model hides them, and they stay registered with
// the model in every orbit, zoom and resize because the GPU projects them with the same camera as the faces.  An SVG overlay
// could only be projected, never occluded.  Each sketch is drawn in three passes: a halo (the page's background, so the curve
// reads on any face), the crisp depth-tested curve, and a faint pass without depth test so a sketch behind the model is still
// found.  Picking is done in screen space (lib/sketch-scene.ts hitSketches) over the same polylines.
//
// Units: the scene's world is the CAD frame in metres, Z up; sketch points are in mm in the sketch's plane frame.

import * as THREE from 'three';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { planeToWorld, planeNormal, type PlaneSpec, type Vec3 } from '../lib/sketch-plane';
import { worldToScreen } from '../lib/sketch-view';
import { hitSketches, type Pickable, type SketchShape } from '../lib/sketch-scene';
import { EDGE_LAYER, type BRepRenderer } from './renderer';

export type LayerSketch = {
  name: string;
  plane: PlaneSpec;
  shape: SketchShape;
  /** Consumed by an extrude, revolve, cut or boss: drawn dimmer. */
  used: boolean;
};

export type LayerInk = { curve: string; construction: string; selected: string; hover: string; fail: string; halo: string };

export type LayerState = {
  hidden: ReadonlySet<string>;
  /** The sketch being edited in sketch mode: its static copy is not drawn. */
  editing: string | null;
  selected: ReadonlySet<string>;
  hover: string | null;
  /** An arrow showing which way (and how far) an operation on a sketch pushes. */
  arrow: { sketch: string; direction: Vec3; distance: number } | null;
};

const MM = 0.001;
const OFFSET = { polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 } as const;

type Built = { name: string; group: THREE.Group; materials: LineMaterial[] };

/** `a` pulled toward `b` by `t` (0: a, 1: b), as a hex colour: how a dimmed curve is made.  Dimming by alpha would show a bead at
 * every joint of a polyline (the segments overlap), so curves are always opaque and only their colour fades. */
export function mixColor(a: string, b: string, t: number): string {
  return `#${new THREE.Color(a).lerp(new THREE.Color(b), t).getHexString()}`;
}

const toWorld = (plane: PlaneSpec, uv: readonly [number, number]): Vec3 => planeToWorld(plane, uv[0], uv[1]);

/** Triangles of a region (outer loop minus holes) in the plane, as world positions in metres. */
export function regionTriangles(plane: PlaneSpec, outer: readonly [number, number][], holes: readonly (readonly [number, number][])[]): number[] {
  const strip = (loop: readonly [number, number][]) => {
    const points = loop.map(([u, v]) => new THREE.Vector2(u, v));
    if (points.length > 1 && points[0].distanceTo(points[points.length - 1]) < 1e-9) points.pop();
    return points;
  };
  const contour = strip(outer);
  const holeLoops = holes.map(strip);
  const all = [...contour, ...holeLoops.flat()];
  const triangles = THREE.ShapeUtils.triangulateShape(contour, holeLoops);
  const out: number[] = [];
  for (const [a, b, c] of triangles) {
    for (const index of [a, b, c]) {
      const w = toWorld(plane, [all[index].x, all[index].y]);
      out.push(w[0] * MM, w[1] * MM, w[2] * MM);
    }
  }
  return out;
}

export class SketchLayer {
  private readonly root = new THREE.Group();
  private built: Built[] = [];
  private sketches: LayerSketch[] = [];
  private state: LayerState = { hidden: new Set(), editing: null, selected: new Set(), hover: null, arrow: null };
  private ink: LayerInk = { curve: '#1a62c4', construction: '#6b6b6b', selected: '#d56a00', hover: '#d56a00', fail: '#d12b3c', halo: '#ffffff' };
  private readonly observer: ResizeObserver;
  private disposed = false;

  constructor(private readonly engine: BRepRenderer) {
    this.root.name = 'sketch-layer';
    this.engine.threeScene.add(this.root);
    this.observer = new ResizeObserver(() => this.resolution());
    this.observer.observe(this.engine.domElement);
  }

  setInk(ink: LayerInk): void {
    this.ink = ink;
    this.rebuild();
  }

  setSketches(sketches: readonly LayerSketch[]): void {
    this.sketches = [...sketches];
    this.rebuild();
  }

  setState(state: LayerState): void {
    this.state = state;
    this.rebuild();
  }

  /** What the viewport can pick right now: the visible sketches. */
  private pickables(): Pickable[] {
    return this.sketches
      .filter((sketch) => this.visible(sketch.name))
      .map((sketch) => ({
        name: sketch.name,
        curves: sketch.shape.curves.filter((curve) => !curve.construction).map((curve) => curve.uv.map((uv) => toWorld(sketch.plane, uv))),
        regions: sketch.shape.regions.map((region) => ({ outer: region.outer.map((uv) => toWorld(sketch.plane, uv)), holes: region.holes.map((hole) => hole.map((uv) => toWorld(sketch.plane, uv))) })),
      }));
  }

  private visible(name: string): boolean {
    return !this.state.hidden.has(name) && this.state.editing !== name;
  }

  /** The sketch under a pointer position (client pixels), or null. */
  hit(clientX: number, clientY: number, tolerance = 7): string | null {
    const rect = this.engine.domElement.getBoundingClientRect();
    const viewer = { camera: this.engine.camera, width: rect.width, height: rect.height };
    return hitSketches(this.pickables(), (point) => worldToScreen(viewer, point), clientX - rect.left, clientY - rect.top, tolerance)?.name ?? null;
  }

  private resolution(): void {
    const dom = this.engine.domElement;
    for (const built of this.built) for (const material of built.materials) material.resolution.set(Math.max(dom.clientWidth, 1), Math.max(dom.clientHeight, 1));
    this.engine.invalidate();
  }

  private clear(): void {
    for (const built of this.built) {
      this.root.remove(built.group);
      built.group.traverse((object) => {
        const item = object as THREE.Mesh;
        item.geometry?.dispose?.();
        const material = item.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) material.forEach((m) => m.dispose());
        else material?.dispose?.();
      });
    }
    this.built = [];
  }

  private lineSet(built: Built, positions: number[], options: { color: string; width: number; opacity: number; depth: boolean; dashed?: boolean; order: number }): void {
    if (positions.length < 6) return;
    const geometry = new LineSegmentsGeometry();
    geometry.setPositions(positions);
    const dom = this.engine.domElement;
    const material = new LineMaterial({
      color: options.color,
      linewidth: options.width,
      worldUnits: false,
      transparent: options.opacity < 1,
      opacity: options.opacity,
      depthTest: options.depth,
      depthWrite: false,
      dashed: Boolean(options.dashed),
      dashSize: 0.0035,
      gapSize: 0.0025,
      ...(options.depth ? OFFSET : {}),
    });
    material.resolution.set(Math.max(dom.clientWidth, 1), Math.max(dom.clientHeight, 1));
    built.materials.push(material);
    const line = new LineSegments2(geometry, material);
    if (options.dashed) line.computeLineDistances();
    line.layers.set(EDGE_LAYER);
    line.renderOrder = options.order;
    line.userData.pickable = false;
    line.frustumCulled = false;
    built.group.add(line);
  }

  private fill(built: Built, positions: number[], color: string, opacity: number): void {
    if (positions.length < 9) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, side: THREE.DoubleSide, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 }));
    mesh.layers.set(EDGE_LAYER);
    mesh.renderOrder = 1;
    mesh.userData.pickable = false;
    mesh.frustumCulled = false;
    built.group.add(mesh);
  }

  private rebuild(): void {
    if (this.disposed) return;
    this.clear();
    const { hidden, editing, selected, hover, arrow } = this.state;
    for (const sketch of this.sketches) {
      if (hidden.has(sketch.name) || editing === sketch.name) continue;
      const built: Built = { name: sketch.name, group: new THREE.Group(), materials: [] };
      built.group.name = `sketch:${sketch.name}`;
      const isSelected = selected.has(sketch.name);
      const isHover = hover === sketch.name;
      const failed = sketch.shape.failed;
      const base = failed ? this.ink.fail : isSelected ? this.ink.selected : isHover ? this.ink.hover : this.ink.curve;
      const strong = isSelected || isHover;
      const halo = this.ink.halo;
      // a used sketch is dimmer than a free one (its colour fades toward the page's); a picked or hovered one is full
      const color = strong || !sketch.used ? base : mixColor(base, halo, 0.5);
      const width = isSelected ? 3.6 : isHover ? 3.2 : 2.4;
      const solid: number[] = [];
      const dashed: number[] = [];
      for (const curve of sketch.shape.curves) {
        const target = curve.construction ? dashed : solid;
        for (let i = 0; i + 1 < curve.uv.length; i++) {
          const a = toWorld(sketch.plane, curve.uv[i]);
          const b = toWorld(sketch.plane, curve.uv[i + 1]);
          target.push(a[0] * MM, a[1] * MM, a[2] * MM, b[0] * MM, b[1] * MM, b[2] * MM);
        }
      }
      for (const region of sketch.shape.regions) {
        this.fill(built, regionTriangles(sketch.plane, region.outer, region.holes), isSelected || isHover ? this.ink.selected : base, isSelected ? 0.24 : isHover ? 0.18 : sketch.used ? 0.05 : 0.1);
      }
      // faint pass: the whole sketch without depth test, so one behind the model is still there (opaque, in a faded colour)
      this.lineSet(built, solid, { color: mixColor(base, halo, sketch.used ? 0.86 : 0.72), width: 1.2, opacity: 1, depth: false, order: 2 });
      this.lineSet(built, solid, { color: halo, width: width + 3, opacity: 1, depth: true, order: 3 });
      this.lineSet(built, solid, { color, width, opacity: 1, depth: true, order: 4 });
      this.lineSet(built, dashed, { color: mixColor(this.ink.construction, halo, sketch.used ? 0.5 : 0.2), width: 1.4, opacity: 1, depth: true, dashed: true, order: 4 });
      this.root.add(built.group);
      this.built.push(built);
    }
    if (arrow) this.addArrow(arrow);
    this.engine.invalidate();
  }

  /** The preview of a push: a shaft and a head from the sketch's centre, `distance` mm long, along `direction`. */
  private addArrow(arrow: NonNullable<LayerState['arrow']>): void {
    const sketch = this.sketches.find((item) => item.name === arrow.sketch);
    if (!sketch) return;
    const e = sketch.shape.extent;
    const centre = planeToWorld(sketch.plane, e ? (e.min[0] + e.max[0]) / 2 : 0, e ? (e.min[1] + e.max[1]) / 2 : 0);
    const d = new THREE.Vector3(...arrow.direction).normalize();
    const length = Math.max(arrow.distance, 1);
    const tip = new THREE.Vector3(...centre).addScaledVector(d, length);
    const head = Math.min(length * 0.3, 8);
    const ref = Math.abs(d.z) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1);
    const side = new THREE.Vector3().crossVectors(d, ref).normalize().multiplyScalar(head * 0.5);
    const back = tip.clone().addScaledVector(d, -head);
    const segments = [
      new THREE.Vector3(...centre), tip,
      tip, back.clone().add(side),
      tip, back.clone().sub(side),
    ];
    const positions = segments.flatMap((p) => [p.x * MM, p.y * MM, p.z * MM]);
    const built: Built = { name: `arrow:${arrow.sketch}`, group: new THREE.Group(), materials: [] };
    this.lineSet(built, positions, { color: this.ink.halo, width: 7, opacity: 1, depth: false, order: 8 });
    this.lineSet(built, positions, { color: this.ink.selected, width: 3.6, opacity: 1, depth: false, order: 9 });
    this.root.add(built.group);
    this.built.push(built);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.observer.disconnect();
    this.clear();
    this.engine.threeScene.remove(this.root);
  }
}

/** The unit world direction an operation's direction value means for a sketch plane ("+z", "normal", "-normal"). */
export function directionVector(direction: string, plane: PlaneSpec): Vec3 | null {
  const normal = planeNormal(plane);
  if (direction === 'normal') return normal;
  if (direction === '-normal') return [-normal[0], -normal[1], -normal[2]];
  const m = /^([+-])([xyz])$/.exec(direction);
  if (!m) return null;
  const v: Vec3 = [0, 0, 0];
  v['xyz'.indexOf(m[2])] = m[1] === '+' ? 1 : -1;
  return v;
}
