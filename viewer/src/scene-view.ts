// Interactive BRep selection view used by the reverse-engineering mode.
// A thin selection/annotation layer on top of the standalone BRepRenderer
// component (src/renderer): this class adds raycast picking, selection
// modes and annotation marks. All rendering — materials, edge display,
// lighting, ambient occlusion, camera — lives in the renderer component.

import * as THREE from 'three';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { bindClickSelection } from './components/click-selection';
import { disposeObject } from './cad-three';
import { BRepRenderer, OVERLAY_LAYER, type CameraState } from './renderer';
import type { PackageFiles } from './product-package';
import type { Entity, EntitySidecar, FaceGroup, SceneNode } from './scene2';

export type SelectionMode = 'component' | 'solid' | 'face' | 'edge' | 'vertex';
export type PickResult = { nodeId: string; entityId: string | null; mode: SelectionMode; entity: Entity | null };
export type { CameraState };

export const MARK_COLORS = ['#ff5c5c', '#ffd23f', '#4ade80', '#60a5fa', '#c084fc', '#fb923c', '#f472b6', '#34d399'];

export type SceneViewOptions = {
  onPick?: (result: PickResult) => void;
  selectionMode?: SelectionMode;
  background?: string;
  interactive?: boolean;
  /** GTAO ambient occlusion (default on). */
  ssao?: boolean;
  /** Show seam/degenerate edges (default off). */
  seams?: boolean;
};

type Mark = { key: string; color: string; overlays: THREE.Object3D[] };

export class SceneView {
  readonly engine: BRepRenderer;
  onPick: ((result: PickResult) => void) | null;

  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  selectionMode: SelectionMode;
  marks: Mark[] = [];
  private unbindClick: (() => void) | null = null;
  private disposed = false;

  constructor(host: HTMLElement, options: SceneViewOptions = {}) {
    this.onPick = options.onPick ?? null;
    this.selectionMode = options.selectionMode ?? 'face';
    this.engine = new BRepRenderer(host, { background: options.background, ssao: options.ssao, seams: options.seams });
    if (options.interactive !== false) {
      this.unbindClick = bindClickSelection({
        element: this.engine.domElement,
        camera: this.engine.camera,
        controls: this.engine.controls,
        onClick: (event) => {
          const result = this.pick(event);
          if (result) this.onPick?.(result);
        },
      });
    }
  }

  // -- scene loading ---------------------------------------------------------

  async loadScene(files: PackageFiles): Promise<void> {
    this.clearMarks();
    await this.engine.loadScene(files);
    this.applySelectionModeVisibility();
  }

  clearScene(): void {
    this.clearMarks();
    this.engine.clearScene();
  }

  sidecarFor(node: SceneNode | undefined): EntitySidecar | null {
    return this.engine.sidecarFor(node);
  }

  entityFor(nodeId: string, entityId: string): Entity | null {
    return this.engine.entityFor(nodeId, entityId);
  }

  get nodes(): SceneNode[] {
    return this.engine.nodes;
  }

  nodeObject(nodeId: string): THREE.Group | undefined {
    return this.engine.nodeObject(nodeId);
  }

  // -- picking ---------------------------------------------------------------

  setSelectionMode(mode: SelectionMode): void {
    this.selectionMode = mode;
    this.applySelectionModeVisibility();
  }

  private applySelectionModeVisibility(): void {
    this.engine.setVertexCloudsVisible(this.selectionMode === 'vertex');
  }

  private isEffectivelyVisible(object: THREE.Object3D): boolean {
    for (let current: THREE.Object3D | null = object; current; current = current.parent) {
      if (!current.visible) return false;
      if (current === this.engine.modelRoot) break;
    }
    return true;
  }

  private pointerRay(event: PointerEvent): void {
    const bounds = this.engine.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    this.pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.engine.camera);
    const distance = this.engine.camera.position.distanceTo(this.engine.controls.target);
    const worldPerPixel = 2 * Math.tan(THREE.MathUtils.degToRad(this.engine.camera.fov * 0.5)) * distance / Math.max(bounds.height, 1);
    this.raycaster.params.Line.threshold = worldPerPixel * 5;
    this.raycaster.params.Points.threshold = worldPerPixel * 8;
  }

  /** A hidden seam/degenerate edge must not answer edge picks. */
  private isEdgePickable(entityId: string | undefined, sidecar: EntitySidecar | null): boolean {
    if (this.engine.seamsShown) return true;
    const entity = sidecar?.entities.find((item) => item.entity_id === entityId);
    const props = entity?.properties as { seam?: unknown; degenerate?: unknown } | undefined;
    return props?.seam !== true && props?.degenerate !== true;
  }

  pick(event: PointerEvent): PickResult | null {
    this.pointerRay(event);
    const hits = this.raycaster.intersectObjects(this.engine.modelRoot.children, true).filter((hit) => {
      if (hit.object.userData.pickable === false || !this.isEffectivelyVisible(hit.object)) return false;
      return typeof hit.object.userData.nodeId === 'string';
    });
    const meshHit = hits.find((hit) => hit.object instanceof THREE.Mesh);
    if (this.selectionMode === 'component' || this.selectionMode === 'solid' || this.selectionMode === 'face') {
      if (!meshHit) return null;
    } else {
      const wanted = this.selectionMode === 'edge'
        ? (hit: THREE.Intersection) => hit.object instanceof THREE.LineSegments
        : (hit: THREE.Intersection) => hit.object instanceof THREE.Points;
      let candidate: THREE.Intersection | undefined;
      for (const hit of hits.filter(wanted)) {
        if (this.selectionMode === 'edge') {
          const nodeId = hit.object.userData.nodeId as string;
          const node = this.engine.nodes.find((item) => item.node_id === nodeId);
          const sidecar = this.engine.sidecarFor(node);
          const entityId = this.edgeEntityIdForHit(hit, sidecar);
          if (!this.isEdgePickable(entityId, sidecar)) continue;
        }
        candidate = hit;
        break;
      }
      if (!candidate) return null;
      if (meshHit) {
        const occlusionAllowance = this.selectionMode === 'edge' ? this.raycaster.params.Line.threshold : this.raycaster.params.Points.threshold;
        if (candidate.distance > meshHit.distance + occlusionAllowance * 1.5) return null;
      }
    }
    const hit = (this.selectionMode === 'edge' || this.selectionMode === 'vertex')
      ? hits.find((item) => this.selectionMode === 'edge' ? item.object instanceof THREE.LineSegments : item.object instanceof THREE.Points) ?? meshHit
      : meshHit;
    if (!hit) return null;
    const nodeId = hit.object.userData.nodeId as string;
    const node = this.engine.nodes.find((item) => item.node_id === nodeId);
    const sidecar = this.sidecarFor(node);
    if (this.selectionMode === 'component') {
      return { nodeId, entityId: null, mode: 'component', entity: null };
    }
    if (this.selectionMode === 'solid') {
      const solid = sidecar?.entities.find((item) => item.kind === 'solid') ?? null;
      return { nodeId, entityId: solid?.entity_id ?? null, mode: 'solid', entity: solid };
    }
    let entityId: string | undefined;
    if (this.selectionMode === 'face' && hit.object instanceof THREE.Mesh && typeof hit.faceIndex === 'number') {
      const triangleOffset = hit.faceIndex * 3;
      entityId = sidecar?.face_groups.find((group: FaceGroup) => triangleOffset >= group.first_index && triangleOffset < group.first_index + group.index_count)?.entity_id;
    } else if (this.selectionMode === 'edge' && hit.object instanceof THREE.LineSegments && typeof hit.index === 'number') {
      entityId = this.edgeEntityIdForHit(hit, sidecar);
    } else if (this.selectionMode === 'vertex' && hit.object instanceof THREE.Points && typeof hit.index === 'number') {
      entityId = hit.object.userData.vertexEntityIds?.[hit.index];
    }
    if (!entityId) return null;
    return { nodeId, entityId, mode: this.selectionMode, entity: this.entityFor(nodeId, entityId) };
  }

  private edgeEntityIdForHit(hit: THREE.Intersection, sidecar: EntitySidecar | null): string | undefined {
    if (!(hit.object instanceof THREE.LineSegments) || typeof hit.index !== 'number' || !sidecar) return undefined;
    return sidecar.edge_groups.find((group: FaceGroup) => hit.index! >= group.first_index && hit.index! < group.first_index + group.index_count)?.entity_id;
  }

  // -- highlight + marks -------------------------------------------------------

  private attachOverlay(source: THREE.Object3D, overlay: THREE.Object3D): THREE.Object3D {
    overlay.name = 'entity-overlay';
    overlay.userData.pickable = false;
    // Overlays composite in the post-AO edge pass (see BRepRenderer): their
    // color must not be darkened by ambient occlusion.
    overlay.layers.set(OVERLAY_LAYER);
    overlay.renderOrder = 10;
    overlay.matrix.copy(source.matrix);
    overlay.matrixAutoUpdate = false;
    overlay.visible = source.visible;
    source.parent?.add(overlay);
    return overlay;
  }

  buildEntityOverlays(nodeId: string, entityId: string | null, color: string, opacity = 0.72): THREE.Object3D[] {
    const object = this.engine.nodeObject(nodeId);
    const node = this.engine.nodes.find((item) => item.node_id === nodeId);
    const sidecar = this.engine.sidecarFor(node);
    if (!object || !sidecar) return [];
    const entityGroup = entityId ? sidecar.face_groups.find((group: FaceGroup) => group.entity_id === entityId) : undefined;
    const edgeGroup = entityId ? sidecar.edge_groups.find((group: FaceGroup) => group.entity_id === entityId) : undefined;
    const isSolid = entityId?.startsWith('entity/solid/');
    const isVertex = entityId?.startsWith('entity/vertex/');
    const overlays: THREE.Object3D[] = [];
    object.traverse((child: THREE.Object3D) => {
      if (overlays.length || !this.isEffectivelyVisible(child) || !(child instanceof THREE.Mesh || child instanceof THREE.LineSegments || child instanceof THREE.Points)) return;
      const source = child as THREE.Mesh | THREE.LineSegments | THREE.Points;
      const range = entityGroup || edgeGroup;
      if (!range && !isVertex && !isSolid) return;
      if (entityGroup && !(source instanceof THREE.Mesh)) return;
      if (edgeGroup && !entityGroup && !(source instanceof THREE.LineSegments)) return;
      if (isVertex && !source.userData.vertexEntityIds?.includes(entityId!)) return;
      if (source instanceof THREE.LineSegments && range) {
        const lineGeometry = new LineSegmentsGeometry();
        const positions: number[] = [];
        const index = source.geometry.index;
        const position = source.geometry.getAttribute('position');
        for (let offset = range.first_index; offset < range.first_index + range.index_count; offset += 2) {
          const a = index ? index.getX(offset) : offset;
          const b = index ? index.getX(offset + 1) : offset + 1;
          positions.push(position.getX(a), position.getY(a), position.getZ(a), position.getX(b), position.getY(b), position.getZ(b));
        }
        lineGeometry.setPositions(positions);
        const material = new LineMaterial({ color, linewidth: 5, worldUnits: false, transparent: true, opacity: 1, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 });
        material.resolution.set(this.engine.domElement.clientWidth, this.engine.domElement.clientHeight);
        overlays.push(this.attachOverlay(source, new LineSegments2(lineGeometry, material)));
      } else if (source instanceof THREE.Points) {
        const geometry = source.geometry.clone();
        const vertexIndex = source.userData.vertexEntityIds.indexOf(entityId!);
        geometry.setDrawRange(vertexIndex, 1);
        overlays.push(this.attachOverlay(source, new THREE.Points(geometry, new THREE.PointsMaterial({ color, size: 16, sizeAttenuation: false, transparent: true, opacity: 1, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }))));
      } else {
        const geometry = source.geometry.clone();
        if (range) geometry.setDrawRange(range.first_index, range.index_count);
        // Depth-tested so highlights hide behind the body like real geometry;
        // the polygon offset keeps the overlay from z-fighting its own face.
        overlays.push(this.attachOverlay(source, new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color, transparent: true, opacity: isSolid ? opacity * 0.55 : opacity, depthTest: true, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }))));
      }
    });
    return overlays;
  }

  addMark(nodeId: string, entityId: string | null, color: string): void {
    const key = `${nodeId}::${entityId ?? 'component'}`;
    if (this.marks.some((mark) => mark.key === key)) return;
    const overlays = this.buildEntityOverlays(nodeId, entityId, color);
    if (overlays.length) this.marks.push({ key, color, overlays });
  }

  removeMark(key: string): void {
    const index = this.marks.findIndex((mark) => mark.key === key);
    if (index < 0) return;
    for (const overlay of this.marks[index].overlays) {
      overlay.parent?.remove(overlay);
      disposeObject(overlay);
    }
    this.marks.splice(index, 1);
  }

  clearMarks(): void {
    for (const mark of this.marks) {
      for (const overlay of mark.overlays) {
        overlay.parent?.remove(overlay);
        disposeObject(overlay);
      }
    }
    this.marks = [];
  }

  hasMark(nodeId: string, entityId: string | null): boolean {
    return this.marks.some((mark) => mark.key === `${nodeId}::${entityId ?? 'component'}`);
  }

  // -- display options + camera + lifecycle --------------------------------------

  setEdgesVisible(visible: boolean): void {
    this.engine.setEdgesVisible(visible);
  }

  setSeamsVisible(visible: boolean): void {
    this.engine.setSeamsVisible(visible);
  }

  setSSAO(enabled: boolean): void {
    this.engine.setSSAO(enabled);
  }

  frame(): void {
    this.engine.frame();
  }

  getCameraState(): CameraState {
    return this.engine.getCameraState();
  }

  snapshotPng(): string | null {
    return this.engine.snapshotPng();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.unbindClick?.();
    this.engine.dispose();
  }
}
