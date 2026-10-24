// Standalone BRep scene renderer component.
//
// Owns everything visual about rendering a scene-2.0 package (GLB faces +
// line edges + entity sidecars): materials, lighting (studio environment +
// key light), postprocessing (GTAO ambient occlusion), camera (free
// trackball), edge display (seam/degenerate edges split into their own
// toggleable visuals), fit/snapshot and lifecycle. It has no notion of
// selection or annotation — embed it directly, or compose it under a
// higher-level view (see src/scene-view.ts for the picking/marks layer).
//
//     import { BRepRenderer } from './renderer';
//     const viewer = new BRepRenderer(hostElement);
//     await viewer.loadScene(files);   // scene-2.0 files (see product-package)
//     viewer.setSeamsVisible(false);   // default
//     viewer.setSSAO(true);            // default

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { TrackballControls } from 'three/addons/controls/TrackballControls.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { strFromU8 } from 'fflate';
import { CAD_EDGE_COLOR, CAD_EDGE_LINE_WIDTH, cadPointToGltf, disposeObject, materialFor, placementMatrix } from '../cad-three';
import type { PackageFiles } from '../product-package';
import type { Entity, EntitySidecar, FaceGroup, SceneManifest, SceneNode, Vec3 } from '../scene2';

/** Render layers: faces (0, default) go through lighting + AO; edges (1) and
 * annotation overlays (2) composite AFTER the AO pass so their color is
 * constant — no GI darkening — while still depth-testing against faces. */
export const FACE_LAYER = 0;
export const EDGE_LAYER = 1;
export const OVERLAY_LAYER = 2;

export type CameraState = {
  position: Vec3;
  target: Vec3;
  up: Vec3;
  fov_deg: number;
  width: number;
  height: number;
};

export type BRepRendererOptions = {
  background?: string;
  /** GTAO ambient occlusion pass (default on). */
  ssao?: boolean;
  /** Show seam/degenerate edges (default off — pro viewers hide them). */
  seams?: boolean;
};

type Resolution = { width: number; height: number };

function isHiddenEdge(entity: Entity | undefined): boolean {
  const props = entity?.properties as { seam?: unknown; degenerate?: unknown } | undefined;
  return props?.seam === true || props?.degenerate === true;
}

export class BRepRenderer {
  readonly host: HTMLElement;
  readonly threeScene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: TrackballControls;
  readonly modelRoot = new THREE.Group();

  manifest: SceneManifest | null = null;
  files: PackageFiles | null = null;
  nodeVisibility = new Map<string, boolean>();

  private loader = new GLTFLoader();
  private geometryCache = new Map<string, THREE.Object3D>();
  private edgeCache = new Map<string, THREE.Object3D>();
  private entityCache = new Map<string, EntitySidecar>();
  private nodeObjects = new Map<string, THREE.Group>();
  private faceRT: THREE.WebGLRenderTarget | null = null;
  private beautyRT: THREE.WebGLRenderTarget | null = null;
  private ssaoPass: GTAOPass | null = null;
  private ssaoEnabled: boolean;
  private rendererClearColor: THREE.Color;
  private blitScene: THREE.Scene | null = null;
  private blitCamera: THREE.OrthographicCamera | null = null;
  private copyMaterial: THREE.MeshBasicMaterial | null = null;
  private presentMaterial: THREE.MeshBasicMaterial | null = null;
  private edgesVisible = true;
  private seamsVisible: boolean;
  private observer: ResizeObserver;
  private pendingFrame = true;
  private disposed = false;

  constructor(host: HTMLElement, options: BRepRendererOptions = {}) {
    this.host = host;
    this.ssaoEnabled = options.ssao ?? true;
    this.seamsVisible = options.seams ?? false;
    this.threeScene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(2.4, 2.1, 3.0);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    // Background comes from the renderer clear color, NOT scene.background:
    // a Color scene.background force-clears the framebuffer on EVERY
    // renderer.render() (even autoClear=false), which would wipe the
    // face/color buffer when the edge pass draws on top of it. The clear
    // color is consumed raw as linear working-space values, so convert the
    // sRGB design color first — otherwise the presented background is ~4x
    // brighter than intended.
    this.rendererClearColor = new THREE.Color(options.background ?? '#0b0e12').convertSRGBToLinear();
    this.renderer.setClearColor(this.rendererClearColor, 1);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    host.append(this.renderer.domElement);
    // Trackball rotation: no fixed orbit axis, so the model can be rolled
    // past any pole — a turntable (OrbitControls) caps vertical sweep below
    // 180° no matter how the polar angle is clamped.
    this.controls = new TrackballControls(this.camera, this.renderer.domElement);
    this.controls.rotateSpeed = 1.0;
    this.controls.zoomSpeed = 1.0;
    this.controls.dynamicDampingFactor = 0.35;
    this.controls.minDistance = 0.01;
    this.controls.maxDistance = 1000;
    // Host pages may own the keyboard (text inputs); TrackballControls'
    // window-level A/S/D drag modifiers must not react to typing. The tuple
    // type is fixed, so park unreachable key codes instead of leaving A/S/D live.
    this.controls.keys = ['__unused_rotate', '__unused_zoom', '__unused_pan'];
    this.modelRoot.name = 'scene-root';
    this.threeScene.add(this.modelRoot);
    this.setupLighting();
    this.setupPostprocessing();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.render();
    });
  }

  private setupLighting(): void {
    // Image-based studio lighting instead of hand-placed fill lights; one
    // directional key stays for crisp specular definition on flats.
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.threeScene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.threeScene.environmentIntensity = 0.7;
    pmrem.dispose();
    const keyLight = new THREE.DirectionalLight('#fff8e9', 1.4);
    keyLight.position.set(4, 7, 5);
    this.threeScene.add(keyLight, keyLight.target);
  }

  private setupPostprocessing(): void {
    // Manual pipeline instead of EffectComposer, so edges can composite AFTER
    // the AO blend:
    //   1. faces (layer 0) render into faceRT — this carries the face depth
    //   2. GTAO blends beauty*ao into beautyRT; a copy brings it back onto
    //      faceRT, keeping faceRT's depth attachment intact
    //   3. edges (layer 1) + overlays (layer 2) render into faceRT with plain
    //      depth testing — after AO, hence constant color, correctly occluded
    //   4. faceRT presents to screen through tone mapping
    const size = this.resolution();
    const pixelRatio = this.renderer.getPixelRatio();
    const width = Math.max(size.width * pixelRatio, 1);
    const height = Math.max(size.height * pixelRatio, 1);
    const options: THREE.RenderTargetOptions = { type: THREE.HalfFloatType, samples: 4 };
    this.faceRT = new THREE.WebGLRenderTarget(width, height, options);
    this.beautyRT = new THREE.WebGLRenderTarget(width, height, options);
    if (this.ssaoEnabled) {
      const ssaoPass = new GTAOPass(this.threeScene, this.camera, width, height);
      ssaoPass.output = GTAOPass.OUTPUT.Default;
      ssaoPass.blendIntensity = 0.65;
      this.tuneSSAO(ssaoPass, 0.01);
      this.ssaoPass = ssaoPass;
    }
    this.blitScene = new THREE.Scene();
    this.blitCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.copyMaterial = new THREE.MeshBasicMaterial({ map: this.beautyRT.texture, toneMapped: false, depthTest: false, depthWrite: false });
    this.presentMaterial = new THREE.MeshBasicMaterial({ map: this.faceRT.texture, toneMapped: true, depthTest: false, depthWrite: false });
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.copyMaterial);
    quad.frustumCulled = false;
    this.blitScene.add(quad);
  }

  /** Draws one material over the whole current render target. */
  private blit(material: THREE.Material): void {
    const quad = this.blitScene!.children[0] as THREE.Mesh;
    quad.material = material;
    this.renderer.render(this.blitScene!, this.blitCamera!);
  }

  /** GTAO works in world units — retune the radius to the model's scale. */
  private tuneSSAO(pass: GTAOPass, modelRadius: number): void {
    pass.updateGtaoMaterial({
      radius: Math.max(modelRadius * 0.14, 0.002),
      distanceExponent: 1.0,
      thickness: 1.0,
      scale: 1.0,
      samples: 16,
      distanceFallOff: 1.0,
      screenSpaceRadius: false,
    });
  }

  private render(): void {
    if (!this.faceRT || !this.blitScene) return;
    const previousTarget = this.renderer.getRenderTarget();
    const previousAutoClear = this.renderer.autoClear;

    // 1. faces + background (layer 0) — carries the face depth buffer
    this.camera.layers.set(FACE_LAYER);
    this.renderer.setRenderTarget(this.faceRT);
    this.renderer.clear();
    this.renderer.render(this.threeScene, this.camera);

    // 2. ambient occlusion on faces only
    if (this.ssaoPass && this.ssaoEnabled && this.beautyRT) {
      this.ssaoPass.render(this.renderer, this.beautyRT, this.faceRT, 0, false);
      // 2b. bring the AO'ed color back onto faceRT; its depth survives because
      // the copy quad does not write depth
      this.renderer.setRenderTarget(this.faceRT);
      this.renderer.autoClear = false;
      this.copyMaterial!.map = this.beautyRT.texture;
      this.blit(this.copyMaterial!);
    }

    // 3. edges + annotation overlays, composited after AO with plain depth
    // testing against the face depth — constant color, correctly occluded
    this.camera.layers.set(EDGE_LAYER);
    this.camera.layers.enable(OVERLAY_LAYER);
    this.renderer.setRenderTarget(this.faceRT);
    this.renderer.render(this.threeScene, this.camera);
    this.camera.layers.set(FACE_LAYER);

    // 4. present through tone mapping
    this.renderer.setRenderTarget(previousTarget);
    this.renderer.autoClear = previousAutoClear;
    this.blit(this.presentMaterial!);
  }

  // -- scene loading -------------------------------------------------------

  private bytesFor(uri: string): Uint8Array {
    const value = this.files?.[uri];
    if (!value) throw new Error(`scene file is missing: ${uri}`);
    return value;
  }

  private async loadGlb(uri: string): Promise<THREE.Object3D> {
    const bytes = this.bytesFor(uri);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const gltf = await this.loader.parseAsync(buffer, '');
    return gltf.scene;
  }

  private resolution(): Resolution {
    return { width: this.renderer.domElement.clientWidth, height: this.renderer.domElement.clientHeight };
  }

  sidecarFor(node: SceneNode | undefined): EntitySidecar | null {
    if (!this.manifest || !this.files || !node?.entity_asset_id) return null;
    const asset = this.manifest.entity_assets.find((item) => item.asset_id === node.entity_asset_id);
    if (!asset) return null;
    const cached = this.entityCache.get(asset.asset_id);
    if (cached) return cached;
    const parsed = JSON.parse(strFromU8(this.bytesFor(asset.uri))) as EntitySidecar;
    if (parsed.schema_version !== '2.0') throw new Error(`entity sidecar schema differs: ${asset.uri}`);
    this.entityCache.set(asset.asset_id, parsed);
    return parsed;
  }

  async loadScene(files: PackageFiles): Promise<void> {
    const sceneBytes = files['scene.json'];
    if (!sceneBytes) throw new Error('scene.json is missing from the scene files');
    const manifest = JSON.parse(strFromU8(sceneBytes)) as SceneManifest;
    if (manifest.schema_version !== '2.0') throw new Error(`unsupported scene schema: ${manifest.schema_version}`);
    this.clearScene();
    this.files = files;
    this.manifest = manifest;
    const nodesByParent = new Map<string | null, SceneNode[]>();
    for (const node of manifest.nodes) nodesByParent.set(node.parent_node_id, [...(nodesByParent.get(node.parent_node_id) ?? []), node]);
    const build = async (parent: THREE.Object3D, parentId: string | null): Promise<void> => {
      for (const node of nodesByParent.get(parentId) ?? []) {
        const object = new THREE.Group();
        object.name = node.node_id;
        object.matrixAutoUpdate = false;
        object.matrix.copy(placementMatrix(node.transform));
        object.visible = this.nodeVisibility.get(node.node_id) ?? true;
        object.userData.nodeId = node.node_id;
        object.userData.definitionId = node.definition_id;
        this.nodeObjects.set(node.node_id, object);
        parent.add(object);
        if (node.node_kind === 'part' || node.node_kind === 'solid') {
          const instance = await this.instantiateNode(node);
          instance.traverse((child: THREE.Object3D) => { child.userData.nodeId = node.node_id; child.userData.definitionId = node.definition_id; });
          object.add(instance);
        }
        await build(object, node.node_id);
      }
    };
    await build(this.modelRoot, null);
    this.setVertexCloudsVisible(false);
    this.pendingFrame = true;
    this.resize();
  }

  private async instantiateNode(node: SceneNode): Promise<THREE.Group> {
    if (!this.manifest) throw new Error('scene is not loaded');
    const sidecar = this.sidecarFor(node);
    const group = new THREE.Group();
    group.name = node.display_name || node.node_id;
    const geometryAsset = node.geometry_asset_id ? this.manifest.geometry_assets.find((asset) => asset.asset_id === node.geometry_asset_id) : undefined;
    if (geometryAsset) {
      let geometry = this.geometryCache.get(geometryAsset.asset_id);
      if (!geometry) {
        geometry = await this.loadGlb(geometryAsset.uri);
        this.geometryCache.set(geometryAsset.asset_id, geometry);
      }
      const renderGeometry = geometry.clone(true);
      renderGeometry.traverse((child) => {
        if (child instanceof THREE.Mesh) child.material = materialFor(node);
      });
      group.add(renderGeometry);
    }
    const edgeAsset = sidecar ? this.manifest.geometry_assets.find((asset) => asset.asset_id === sidecar.edge_asset_id) : undefined;
    if (edgeAsset && sidecar) {
      let edge = this.edgeCache.get(edgeAsset.asset_id);
      if (!edge) {
        edge = await this.loadGlb(edgeAsset.uri);
        this.edgeCache.set(edgeAsset.asset_id, edge);
      }
      const edgeInstance = edge.clone(true);
      this.buildEdgeVisuals(edgeInstance, sidecar);
      group.add(edgeInstance);
    }
    if (sidecar) {
      const vertices = sidecar.entities.filter((entity) => entity.kind === 'vertex');
      if (vertices.length) {
        const positions = new Float32Array(vertices.length * 3);
        vertices.forEach((entity, index) => {
          const position = entity.properties.position;
          if (Array.isArray(position) && position.length === 3 && position.every((item) => typeof item === 'number')) cadPointToGltf(position as Vec3).toArray(positions, index * 3);
        });
        const vertexGeometry = new THREE.BufferGeometry();
        vertexGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        const vertexPoints = new THREE.Points(vertexGeometry, new THREE.PointsMaterial({ color: '#d8ff83', size: 7, sizeAttenuation: false, depthWrite: false, transparent: true, opacity: 0.48 }));
        vertexPoints.visible = false;
        vertexPoints.userData.pickRole = 'vertex';
        vertexPoints.userData.pickable = true;
        vertexPoints.userData.vertexEntityIds = vertices.map((entity) => entity.entity_id);
        group.add(vertexPoints);
      }
    }
    return group;
  }

  /** Split the edge asset into regular and seam/degenerate wide-line visuals. */
  private buildEdgeVisuals(edgeObject: THREE.Object3D, sidecar: EntitySidecar): void {
    const entitiesById = new Map(sidecar.entities.map((entity) => [entity.entity_id, entity]));
    edgeObject.traverse((child) => {
      if (!(child instanceof THREE.LineSegments)) return;
      const source = child as THREE.LineSegments;
      const index = source.geometry.index;
      const position = source.geometry.getAttribute('position');
      const indexCount = index?.count ?? position.count;
      const groups = [...sidecar.edge_groups].sort((a, b) => a.first_index - b.first_index);
      const regular: number[] = [];
      const seams: number[] = [];
      const pushRange = (target: number[], first: number, count: number): void => {
        for (let offset = first; offset + 1 < first + count; offset += 2) {
          const a = index ? index.getX(offset) : offset;
          const b = index ? index.getX(offset + 1) : offset + 1;
          target.push(position.getX(a), position.getY(a), position.getZ(a), position.getX(b), position.getY(b), position.getZ(b));
        }
      };
      let cursor = 0;
      for (const group of groups) {
        const start = Math.max(group.first_index, 0);
        if (start > cursor) pushRange(regular, cursor, start - cursor);
        const target = isHiddenEdge(entitiesById.get(group.entity_id)) ? seams : regular;
        pushRange(target, start, group.index_count);
        cursor = Math.max(cursor, start + group.index_count);
      }
      if (cursor < indexCount) pushRange(regular, cursor, indexCount - cursor);
      // the source keeps the original geometry for index-based picking only
      source.material = new THREE.LineBasicMaterial({ visible: false });
      if (regular.length) source.add(this.edgeLineVisual(regular, 'cad-edge-visual'));
      if (seams.length) {
        const seamVisual = this.edgeLineVisual(seams, 'cad-edge-seam');
        seamVisual.visible = this.seamsVisible && this.edgesVisible;
        source.add(seamVisual);
      }
    });
  }

  private edgeLineVisual(positions: number[], name: string): LineSegments2 {
    const geometry = new LineSegmentsGeometry();
    geometry.setPositions(positions);
    // Negative slope-scaled offset mirrors the faces' push (see materialFor):
    // keeps silhouette edges continuous where a flat bias loses.
    const material = new LineMaterial({ color: CAD_EDGE_COLOR, linewidth: CAD_EDGE_LINE_WIDTH, worldUnits: false, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    const size = this.resolution();
    material.resolution.set(Math.max(size.width, 1), Math.max(size.height, 1));
    const visual = new LineSegments2(geometry, material);
    visual.name = name;
    visual.layers.set(EDGE_LAYER);
    visual.userData.pickable = false;
    return visual;
  }

  clearScene(): void {
    for (const object of this.geometryCache.values()) disposeObject(object);
    for (const object of this.edgeCache.values()) disposeObject(object);
    while (this.modelRoot.children.length) {
      const child = this.modelRoot.children[0];
      disposeObject(child);
      this.modelRoot.remove(child);
    }
    this.nodeObjects.clear();
    this.nodeVisibility.clear();
    this.edgeCache.clear();
    this.entityCache.clear();
    this.geometryCache.clear();
    this.manifest = null;
    this.files = null;
  }

  // -- display options -------------------------------------------------------

  setEdgesVisible(visible: boolean): void {
    this.edgesVisible = visible;
    this.modelRoot.traverse((object) => {
      if (object.name === 'cad-edge-visual') object.visible = visible;
      if (object.name === 'cad-edge-seam') object.visible = visible && this.seamsVisible;
    });
  }

  setSeamsVisible(visible: boolean): void {
    this.seamsVisible = visible;
    this.modelRoot.traverse((object) => {
      if (object.name === 'cad-edge-seam') object.visible = visible && this.edgesVisible;
    });
  }

  get seamsShown(): boolean {
    return this.seamsVisible;
  }

  setSSAO(enabled: boolean): void {
    if (!this.ssaoPass || this.ssaoEnabled === enabled) return;
    this.ssaoEnabled = enabled;
    this.ssaoPass.enabled = enabled;
  }

  get ssaoOn(): boolean {
    return this.ssaoEnabled && this.ssaoPass !== null;
  }

  setVertexCloudsVisible(visible: boolean): void {
    this.modelRoot.traverse((child) => {
      if (child.userData.pickRole === 'vertex') child.visible = visible;
    });
  }

  setNodeVisible(nodeId: string, visible: boolean): void {
    const object = this.nodeObjects.get(nodeId);
    if (!object) return;
    object.visible = visible;
    this.nodeVisibility.set(nodeId, visible);
  }

  // -- accessors -------------------------------------------------------------

  get nodes(): SceneNode[] {
    return this.manifest?.nodes ?? [];
  }

  get domElement(): HTMLCanvasElement {
    return this.renderer.domElement;
  }

  nodeObject(nodeId: string): THREE.Group | undefined {
    return this.nodeObjects.get(nodeId);
  }

  entityFor(nodeId: string, entityId: string): Entity | null {
    const node = this.manifest?.nodes.find((item) => item.node_id === nodeId);
    return this.sidecarFor(node)?.entities.find((item) => item.entity_id === entityId) ?? null;
  }

  // -- camera + lifecycle --------------------------------------------------------

  frame(): void {
    const box = new THREE.Box3().setFromObject(this.modelRoot);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    // The 0.0005 floor only guards degenerate/empty geometry; it must stay
    // well below real model radii (a 0.01 floor pushed small parts 3.6x away).
    const radius = Math.max(size.length() * 0.5, 0.0005);
    // FIT is also the escape hatch from a rolled-around trackball orientation:
    // restore the canonical Z-up before re-framing.
    this.camera.up.set(0, 0, 1);
    // 2.3 (not the textbook ~2.8, nor 2.05): the bounding sphere over-covers
    // flat parts, but 2.05 read as slightly too large in review.
    this.camera.position.copy(center).add(new THREE.Vector3(1, 0.78, 1).normalize().multiplyScalar(radius * 2.3));
    this.camera.near = Math.max(radius / 100, 1e-5);
    this.camera.far = Math.max(radius * 100, 0.5);
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    // Absolute minDistance (0.01 in the constructor) would clamp the zoomed-in
    // camera for small models; frame re-derives both bounds from the radius.
    this.controls.minDistance = radius * 0.2;
    this.controls.maxDistance = radius * 12;
    // Kill the trackball's rotational inertia — otherwise it keeps rolling the
    // freshly framed camera away from the canonical pose. These internals are
    // stable across three.js versions; there is no public "stop momentum" API.
    const trackball = this.controls as unknown as {
      _movePrev: THREE.Vector2; _moveCurr: THREE.Vector2; _lastAngle: number;
      _zoomStart: THREE.Vector2; _zoomEnd: THREE.Vector2;
      _panStart: THREE.Vector2; _panEnd: THREE.Vector2;
    };
    trackball._movePrev.copy(trackball._moveCurr);
    trackball._lastAngle = 0;
    trackball._zoomStart.copy(trackball._zoomEnd);
    trackball._panStart.copy(trackball._panEnd);
    this.controls.update();
    if (this.ssaoPass) this.tuneSSAO(this.ssaoPass, radius);
  }

  getCameraState(): CameraState {
    const bounds = this.renderer.domElement.getBoundingClientRect();
    return {
      position: [this.camera.position.x, this.camera.position.y, this.camera.position.z],
      target: [this.controls.target.x, this.controls.target.y, this.controls.target.z],
      up: [this.camera.up.x, this.camera.up.y, this.camera.up.z],
      fov_deg: this.camera.fov,
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
    };
  }

  snapshotPng(): string | null {
    try {
      this.render();
      return this.renderer.domElement.toDataURL('image/png');
    } catch {
      return null;
    }
  }

  private resize(): void {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    if (width <= 0 || height <= 0) return;
    this.renderer.setSize(width, height, false);
    // TrackballControls maps pointer deltas through the element rect, which
    // this host changes on load and panel resizes.
    this.controls.handleResize();
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
    const pixelRatio = this.renderer.getPixelRatio();
    const deviceWidth = Math.max(Math.round(width * pixelRatio), 1);
    const deviceHeight = Math.max(Math.round(height * pixelRatio), 1);
    this.faceRT?.setSize(deviceWidth, deviceHeight);
    this.beautyRT?.setSize(deviceWidth, deviceHeight);
    this.ssaoPass?.setSize(deviceWidth, deviceHeight);
    // The scene may load before the host has its final layout; re-frame once.
    if (this.pendingFrame && this.modelRoot.children.length) {
      this.pendingFrame = false;
      this.frame();
    }
    const resolution = this.resolution();
    this.modelRoot.traverse((object) => {
      if (object instanceof LineSegments2) object.material.resolution.set(resolution.width, resolution.height);
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.observer.disconnect();
    this.renderer.setAnimationLoop(null);
    this.clearScene();
    this.controls.dispose();
    this.faceRT?.dispose();
    this.beautyRT?.dispose();
    this.ssaoPass?.dispose?.();
    if (this.blitScene) {
      const quad = this.blitScene.children[0] as THREE.Mesh | undefined;
      quad?.geometry.dispose();
      this.copyMaterial?.dispose();
      this.presentMaterial?.dispose();
    }
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
