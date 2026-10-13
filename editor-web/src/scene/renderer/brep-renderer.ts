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
import { DEFAULT_BASE_COLOR, CAD_EDGE_LINE_WIDTH, cadPointToGltf, disposeObject, materialFor, placementMatrix } from '../cad-three';
import { PALETTES, type SceneTheme, type ScenePalette } from '../theme';
import type { PackageFiles } from '../product-package';
import type { PreviewData, PreviewPart } from '../../lib/preview';
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
  /** The scene's theme (default dark); `setTheme` changes it later. */
  theme?: SceneTheme;
  /** Overrides the theme's background (sRGB). */
  background?: string;
  /** GTAO ambient occlusion pass (default on). */
  ssao?: boolean;
  /** Show seam/degenerate edges (default off — pro viewers hide them). */
  seams?: boolean;
};

type Resolution = { width: number; height: number };

/** Direct geometry channel payload (no .scadpkg container): the authoring
 * runtime tessellates the live solid and ships the render mesh as-is. */
export type LiveGeometryPayload = {
  schema: 'sca-live-geometry-1';
  step: string;
  /** Triangle vertices in CAD space (mm, +Z up). */
  positions: number[][];
  normals: number[][];
  indices: number[];
  /** Flat segment endpoints in CAD space (x1,y1,z1,x2,y2,z2, ...). */
  edge_positions: number[];
  face_groups: { entity_id: string; first: number; count: number }[];
  stats: { volume: number; faces: number };
};

function isHiddenEdge(entity: Entity | undefined): boolean {
  const props = entity?.properties as { seam?: unknown; degenerate?: unknown } | undefined;
  return props?.seam === true || props?.degenerate === true;
}

/**
 * Edges and faces are tessellated independently, so where a chord of the
 * mesh bulges past the edge's own polyline the edge sinks behind the surface
 * and breaks into dashes.  Slope-scaled polygon offset cannot cover that (the
 * gap is a distance, not a slope), so the line shader pulls its fragments
 * towards the camera by EDGE_DEPTH_BIAS (scene units, metres): a little more
 * than the mesh's chord deviation.  Only depth moves; the line stays where it
 * is on screen, and anything further behind than the bias still hides it.
 */
const EDGE_DEPTH_BIAS = 0.0004;

function createEdgeMaterial(color: string): LineMaterial {
  const material = new LineMaterial({ color, linewidth: CAD_EDGE_LINE_WIDTH, worldUnits: false, depthTest: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.edgeDepthBias = { value: EDGE_DEPTH_BIAS };
    shader.vertexShader = shader.vertexShader
      .replace('void main() {', 'uniform float edgeDepthBias;\nvoid main() {')
      .replace('gl_Position = clip;', 'float biasedView = -clip.w + edgeDepthBias;\n\t\t\tclip.z = (projectionMatrix[2][2] * biasedView + projectionMatrix[3][2]) / -biasedView * clip.w;\n\t\t\tgl_Position = clip;');
  };
  material.customProgramCacheKey = () => 'edge-depth-bias';
  material.userData.role = 'edge'; // setTheme recolors these, and only these
  return material;
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
  private palette: ScenePalette;
  /** The gizmo's per-axis parts, kept to recolor on a theme change. */
  private gizmoAxes: { materials: THREE.MeshBasicMaterial[]; tail: THREE.MeshBasicMaterial; canvas: HTMLCanvasElement; texture: THREE.CanvasTexture; label: string }[] = [];
  private blitScene: THREE.Scene | null = null;
  private blitCamera: THREE.OrthographicCamera | null = null;
  private copyMaterial: THREE.MeshBasicMaterial | null = null;
  private presentMaterial: THREE.MeshBasicMaterial | null = null;
  private edgesVisible = true;
  private seamsVisible: boolean;
  private observer: ResizeObserver;
  private pendingFrame = true;
  private disposed = false;
  private grid: THREE.LineSegments | null = null;
  /** Entity sidecars of the preview's parts, by node id (a preview has no package). */
  private previewSidecars = new Map<string, EntitySidecar>();
  private previewGeometries: THREE.BufferGeometry[] = [];
  private readonly gizmoScene = new THREE.Scene();
  private readonly gizmoCamera = new THREE.OrthographicCamera(-1.5, 1.5, 1.5, -1.5, 0.1, 20);

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
    this.palette = PALETTES[options.theme ?? 'dark'];
    this.rendererClearColor = this.clearColorFor(options.background);
    this.renderer.setClearColor(this.rendererClearColor, 1);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;
    host.append(this.renderer.domElement);
    // resize() calls setSize(w, h, updateStyle=false), so the backing store is
    // host-size × pixelRatio while the CSS display size stays unset — a host
    // that does not style the canvas itself then renders the HiDPI buffer at
    // attribute size and crops it. Pin the display size to the host.
    this.renderer.domElement.style.width = '100%';
    this.renderer.domElement.style.height = '100%';
    this.renderer.domElement.style.display = 'block';
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
    // Shift+left-drag pans. TrackballControls has no modifier support, but its
    // `keyState` field (the keyboard A/S/D path) deliberately outranks the
    // mouse-button gesture, so borrowing it reuses the controls' own pan
    // seeding, damping and release. onPointerUp only resets `state`, so the
    // keyState clear is on us. Capture on the host precedes the controls'
    // listeners on the canvas.
    host.addEventListener(
      'pointerdown',
      (event) => {
        if (!event.shiftKey || event.button !== 0 || this.controls.enabled === false) return;
        // `keyState` drives the controls' real keyboard-pan path but is not
        // in the shipped typings; the runtime field is the documented state
        // machine (PAN=2, NONE=-1).
        const controls = this.controls as TrackballControls & { keyState: number };
        controls.keyState = 2; // TrackballControls._STATE.PAN
        const release = (): void => {
          controls.keyState = -1; // TrackballControls._STATE.NONE
          window.removeEventListener('pointerup', release);
          window.removeEventListener('pointercancel', release);
        };
        window.addEventListener('pointerup', release);
        window.addEventListener('pointercancel', release);
      },
      true,
    );
    this.modelRoot.name = 'scene-root';
    // Package geometry is glTF (Y up, CAD z -> y, CAD y -> -z). Rotate it back
    // so the world is the CAD frame: x, y, z in meters and +Z up, which is
    // what the camera's up vector, the ground grid and the axis gizmo assume.
    this.modelRoot.rotation.x = Math.PI / 2;
    this.threeScene.add(this.modelRoot);
    this.buildGizmo();
    this.setupLighting();
    this.setupPostprocessing();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.resize();
    this.renderer.setAnimationLoop(() => this.render());
  }

  private loopRunning = true;

  /** Demand-render flag: the loop always ticks (damping needs it) but the
   * expensive SSAO pipeline only runs when something actually changed. */
  private needsRender = true;

  /** Schedule one repaint (scene loads, picks, selection, external edits). */
  invalidate(): void {
    this.needsRender = true;
  }

  /** Pause/resume the render loop. Inactive panels must not burn GPU —
   * several editor modes stay mounted, each with its own WebGL context. */
  setRunning(running: boolean): void {
    if (running === this.loopRunning) return;
    this.loopRunning = running;
    if (running) {
      this.renderer.setAnimationLoop(() => this.render());
    } else {
      this.renderer.setAnimationLoop(null);
    }
  }

  isRunning(): boolean {
    return this.loopRunning;
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

  private lastCameraPos = new THREE.Vector3();
  private lastCameraQuat = new THREE.Quaternion();

  /** True when the camera pose changed since the previous call. */
  private cameraMoved(): boolean {
    const changed =
      !this.camera.position.equals(this.lastCameraPos) ||
      !this.camera.quaternion.equals(this.lastCameraQuat);
    this.lastCameraPos.copy(this.camera.position);
    this.lastCameraQuat.copy(this.camera.quaternion);
    return changed;
  }

  private render(): void {
    if (!this.faceRT || !this.blitScene) return;
    this.controls.update();
    // Camera pose change (damping, user input) or an explicit invalidation
    // triggers the expensive SSAO chain; an idle scene skips it entirely.
    if (!this.cameraMoved() && !this.needsRender) return;
    this.needsRender = false;
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
    this.renderGizmo();
  }

  // -- ground grid + axis gizmo ---------------------------------------------------

  /** A gray grid on the XY plane (z = 0), sized to the model. */
  private updateGrid(): void {
    if (this.grid) {
      this.threeScene.remove(this.grid);
      this.grid.geometry.dispose();
      (this.grid.material as THREE.Material).dispose();
      this.grid = null;
    }
    this.modelRoot.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.modelRoot);
    if (box.isEmpty()) return;
    const reach = Math.max(Math.abs(box.min.x), Math.abs(box.max.x), Math.abs(box.min.y), Math.abs(box.max.y), 0.02) * 1.5;
    // 1-2-5 step, about eight cells from the origin to the edge
    const raw = reach / 8;
    const decade = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = decade * ([1, 2, 5, 10].find((factor) => factor * decade >= raw) ?? 10);
    const count = Math.ceil(reach / step);
    const extent = count * step;
    const positions: number[] = [];
    const colors: number[] = [];
    const minor = new THREE.Color(this.palette.gridMinor);
    const major = new THREE.Color(this.palette.gridMajor);
    for (let index = -count; index <= count; index += 1) {
      const color = index % 5 === 0 ? major : minor;
      const at = index * step;
      positions.push(at, -extent, 0, at, extent, 0, -extent, at, 0, extent, at, 0);
      for (let vertex = 0; vertex < 4; vertex += 1) colors.push(color.r, color.g, color.b);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const grid = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ vertexColors: true, depthWrite: false, toneMapped: false }),
    );
    grid.name = 'ground-grid';
    grid.userData.pickable = false;
    grid.layers.set(EDGE_LAYER); // composited after AO, depth-tested against the model
    grid.renderOrder = -1;
    this.threeScene.add(grid);
    this.grid = grid;
    this.needsRender = true;
  }

  /** The three axes as blocks and letters; drawn in a corner of the canvas. */
  private buildGizmo(): void {
    const dirs = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)];
    const labels = ['X', 'Y', 'Z'];
    const basic = (color: string) => new THREE.MeshBasicMaterial({ color, toneMapped: false });
    dirs.forEach((dir, index) => {
      const color = this.palette.axes[index];
      const shaftMaterial = basic(color);
      const tipMaterial = basic(color);
      const tailMaterial = basic(this.palette.axisTail);
      const shaft = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 1), shaftMaterial);
      shaft.position.copy(dir).multiplyScalar(0.5);
      shaft.lookAt(dir);
      const tip = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), tipMaterial);
      tip.position.copy(dir);
      const tail = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.12, 0.12), tailMaterial);
      tail.position.copy(dir).multiplyScalar(-1);
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 64;
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: texture, depthTest: false, toneMapped: false, transparent: true }),
      );
      sprite.scale.set(0.42, 0.42, 1);
      sprite.position.copy(dir).multiplyScalar(1.38);
      this.gizmoAxes.push({ materials: [shaftMaterial, tipMaterial], tail: tailMaterial, canvas, texture, label: labels[index] });
      this.paintGizmoLabel(this.gizmoAxes[index], color);
      this.gizmoScene.add(shaft, tip, tail, sprite);
    });
  }

  private vertexMaterial(): THREE.PointsMaterial {
    const material = new THREE.PointsMaterial({ color: this.palette.vertex, size: 7, sizeAttenuation: false, depthWrite: false, transparent: true, opacity: 0.48 });
    material.userData.role = 'vertex';
    return material;
  }

  private paintGizmoLabel(axis: { canvas: HTMLCanvasElement; texture: THREE.CanvasTexture; label: string }, color: string): void {
    const context = axis.canvas.getContext('2d')!;
    context.clearRect(0, 0, 64, 64);
    context.font = '700 44px ui-monospace, SFMono-Regular, Menlo, monospace';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillStyle = color;
    context.fillText(axis.label, 32, 34);
    axis.texture.needsUpdate = true;
  }

  /** The viewport background as a linear color: sRGB design value, brightened by the
   * theme's boost so the tone-mapped result is the page's own background. */
  private clearColorFor(background?: string): THREE.Color {
    const color = new THREE.Color(background ?? this.palette.clear).convertSRGBToLinear();
    if (background === undefined) color.multiplyScalar(this.palette.clearBoost);
    return color;
  }

  /** Switch the scene to another theme in place: background, edges, grid, gizmo, vertex
   * points. The camera, the model and any selection overlay stay as they are. */
  setTheme(theme: SceneTheme): void {
    this.palette = PALETTES[theme];
    this.rendererClearColor = this.clearColorFor();
    this.renderer.setClearColor(this.rendererClearColor, 1);
    this.modelRoot.traverse((object) => {
      const material = (object as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
      if (!material || Array.isArray(material)) return;
      if (material.userData.role === 'edge') (material as LineMaterial).color.set(this.palette.edge);
      else if (material.userData.role === 'vertex') (material as THREE.PointsMaterial).color.set(this.palette.vertex);
    });
    this.gizmoAxes.forEach((axis, index) => {
      const color = this.palette.axes[index];
      axis.materials.forEach((material) => material.color.set(color));
      axis.tail.color.set(this.palette.axisTail);
      this.paintGizmoLabel(axis, color);
    });
    this.updateGrid();
    this.needsRender = true;
  }

  private renderGizmo(): void {
    const size = this.renderer.getSize(new THREE.Vector2());
    const side = 108;
    const margin = 12;
    const offset = this.camera.position.clone().sub(this.controls.target).normalize().multiplyScalar(6);
    this.gizmoCamera.position.copy(offset);
    this.gizmoCamera.up.copy(this.camera.up);
    this.gizmoCamera.lookAt(0, 0, 0);
    const previousAutoClear = this.renderer.autoClear;
    this.renderer.autoClear = false;
    this.renderer.setRenderTarget(null);
    this.renderer.setScissorTest(true);
    this.renderer.setViewport(size.x - side - margin, margin, side, side);
    this.renderer.setScissor(size.x - side - margin, margin, side, side);
    this.renderer.clearDepth();
    this.renderer.render(this.gizmoScene, this.gizmoCamera);
    this.renderer.setScissorTest(false);
    this.renderer.setViewport(0, 0, size.x, size.y);
    this.renderer.autoClear = previousAutoClear;
  }

  // -- scene loading -------------------------------------------------------

  private bytesFor(uri: string): Uint8Array {
    const value = this.files?.[uri];
    if (!value) throw new Error(`scene file is missing: ${uri}`);
    return value;
  }

  private async loadGlb(uri: string): Promise<THREE.Object3D> {
    const bytes = this.bytesFor(uri);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
    const gltf = await this.loader.parseAsync(buffer, '');
    return gltf.scene;
  }

  private resolution(): Resolution {
    return { width: this.renderer.domElement.clientWidth, height: this.renderer.domElement.clientHeight };
  }

  sidecarFor(node: SceneNode | undefined): EntitySidecar | null {
    const previewed = node ? this.previewSidecars.get(node.node_id) : undefined;
    if (previewed) return previewed;
    if (!this.manifest || !this.files || !node?.entity_asset_id) return null;
    const asset = this.manifest.entity_assets.find((item) => item.asset_id === node.entity_asset_id);
    if (!asset) return null;
    const cached = this.entityCache.get(asset.asset_id);
    if (cached) return cached;
    const parsed = JSON.parse(strFromU8(this.bytesFor(asset.uri))) as EntitySidecar;
    if ((parsed.schema_version !== '1.0' && parsed.schema_version !== '2.0') || parsed.definition_id !== node.definition_id) throw new Error(`entity sidecar identity differs: ${asset.uri}`);
    this.entityCache.set(asset.asset_id, parsed);
    return parsed;
  }

  async loadScene(files: PackageFiles): Promise<void> {
    this.needsRender = true;
    const hadScene = this.modelRoot.children.length > 0;
    const sceneBytes = files['scene.json'];
    if (!sceneBytes) throw new Error('scene.json is missing from the scene files');
    const manifest = JSON.parse(strFromU8(sceneBytes)) as SceneManifest;
    if (manifest.schema_version !== '2.0' && manifest.schema_version !== 're-mode-source-1') throw new Error(`unsupported scene schema: ${manifest.schema_version}`);
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
    // Re-frame only on the FIRST load; watched reloads (Studio live view,
    // agent artifact iterations) must keep the user's camera pose and zoom.
    if (!hadScene) this.pendingFrame = true;
    this.updateGrid();
    this.resize();
  }

  /** Live view fast path: build the scene straight from a tessellated render
   * mesh, skipping the .scadpkg container (zip, hash verification, BREP and
   * feature-graph payloads entirely). Camera pose is preserved on reloads. */
  loadLiveGeometry(payload: LiveGeometryPayload): void {
    const hadScene = this.modelRoot.children.length > 0;
    this.clearScene();
    this.files = {};
    this.manifest = null;
    const group = new THREE.Group();
    group.name = 'live-geometry';
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(payload.positions.flat(), 3));
    geometry.setAttribute('normal', new THREE.Float32BufferAttribute(payload.normals.flat(), 3));
    geometry.setIndex(payload.indices);
    const [r, g, b] = DEFAULT_BASE_COLOR;
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: new THREE.Color(r, g, b), metalness: 0.08, roughness: 0.52, side: THREE.FrontSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
    mesh.name = 'live-faces';
    mesh.layers.set(FACE_LAYER);
    group.add(mesh);
    group.add(this.edgeLineVisual(payload.edge_positions, 'live-edges'));
    this.modelRoot.add(group);
    if (!hadScene) this.pendingFrame = true;
    this.updateGrid();
    this.resize();
  }

  /** Build the scene from a preview (see `lib/preview.ts`): no package, no
   * sidecar files. Each part's geometry is built once and shared by its
   * instances; picking and highlighting use the same face and edge groups the
   * package path has. Entity details are not part of a preview: a pick returns
   * the entity without properties and the caller asks for them. */
  loadPreview(preview: PreviewData): void {
    this.needsRender = true;
    const hadScene = this.modelRoot.children.length > 0;
    this.clearScene();
    this.files = {};
    const nodes: SceneNode[] = [];
    const built = new Map<string, { faces: THREE.BufferGeometry; pick: THREE.BufferGeometry; edges: LineSegmentsGeometry; vertices: THREE.BufferGeometry | null; sidecar: EntitySidecar }>();
    const material = (part: PreviewPart) => part && materialFor({ material_id: null } as SceneNode);
    const buildPart = (part: PreviewPart) => {
      const faces = new THREE.BufferGeometry();
      faces.setAttribute('position', new THREE.BufferAttribute(part.positions, 3));
      faces.setAttribute('normal', new THREE.BufferAttribute(part.normals, 3));
      faces.setIndex(new THREE.BufferAttribute(part.indices, 1));
      faces.computeBoundingSphere();
      const pick = new THREE.BufferGeometry();
      pick.setAttribute('position', new THREE.BufferAttribute(part.edgePositions, 3));
      pick.setIndex(new THREE.BufferAttribute(part.edgeIndices, 1));
      const segments: number[] = [];
      for (let offset = 0; offset + 1 < part.edgeIndices.length; offset += 2) {
        const a = part.edgeIndices[offset] * 3;
        const b = part.edgeIndices[offset + 1] * 3;
        segments.push(
          part.edgePositions[a], part.edgePositions[a + 1], part.edgePositions[a + 2],
          part.edgePositions[b], part.edgePositions[b + 1], part.edgePositions[b + 2],
        );
      }
      const edges = new LineSegmentsGeometry();
      if (segments.length) edges.setPositions(segments);
      let vertices: THREE.BufferGeometry | null = null;
      if (part.vertexIds.length) {
        vertices = new THREE.BufferGeometry();
        vertices.setAttribute('position', new THREE.BufferAttribute(part.vertexPositions, 3));
      }
      const empty = { properties: {}, geometry: {}, tags: [] as string[], parent_entity_ids: [] as string[], child_entity_ids: [] as string[], source: { kind: 'preview' } };
      const entity = (id: string, kind: 'solid' | 'face' | 'edge' | 'vertex') => ({ entity_id: id, kind, topo_id: id.split('/').pop() ?? id, ...empty });
      const sidecar: EntitySidecar = {
        schema_version: '2.0',
        definition_id: part.definitionId,
        geometry_asset_id: '',
        edge_asset_id: '',
        entities: [
          entity(part.solidEntityId, 'solid'),
          ...part.faceGroups.map((group) => entity(group.entity_id, 'face')),
          ...part.edgeGroups.map((group) => entity(group.entity_id, 'edge')),
          ...part.vertexIds.map((id) => entity(id, 'vertex')),
        ],
        face_groups: part.faceGroups,
        edge_groups: part.edgeGroups,
      };
      this.previewGeometries.push(faces, pick, edges, ...(vertices ? [vertices] : []));
      return { faces, pick, edges, vertices, sidecar };
    };
    const edgeMaterial = createEdgeMaterial(this.palette.edge);
    const size = this.resolution();
    edgeMaterial.resolution.set(Math.max(size.width, 1), Math.max(size.height, 1));
    for (const item of preview.nodes) {
      const part = preview.parts.get(item.partKey);
      if (!part) continue;
      let geometry = built.get(part.key);
      if (!geometry) {
        geometry = buildPart(part);
        built.set(part.key, geometry);
      }
      const node = {
        node_id: item.nodeId, parent_node_id: null, display_name: item.displayName, node_kind: 'part', definition_id: item.definitionId,
        definition_kind: 'single_solid', component_id: null, instance_id: null, transform: item.transform, geometry_asset_id: null,
        entity_asset_id: null, material_id: null, properties: {},
      } as SceneNode;
      nodes.push(node);
      this.previewSidecars.set(item.nodeId, geometry.sidecar);
      const object = new THREE.Group();
      object.name = item.nodeId;
      object.matrixAutoUpdate = false;
      object.matrix.copy(placementMatrix(item.transform));
      object.userData.nodeId = item.nodeId;
      object.userData.definitionId = item.definitionId;
      const group = new THREE.Group();
      group.name = item.displayName;
      const faces = new THREE.Mesh(geometry.faces, material(part));
      faces.layers.set(FACE_LAYER);
      group.add(faces);
      // the invisible indexed line set is what edge picking hits; the visual hangs off it
      const pickEdges = new THREE.LineSegments(geometry.pick, new THREE.LineBasicMaterial({ visible: false }));
      if (geometry.edges.attributes.instanceStart) {
        const visual = new LineSegments2(geometry.edges, edgeMaterial);
        visual.name = 'cad-edge-visual';
        visual.layers.set(EDGE_LAYER);
        visual.userData.pickable = false;
        pickEdges.add(visual);
      }
      group.add(pickEdges);
      if (geometry.vertices) {
        const points = new THREE.Points(geometry.vertices, this.vertexMaterial());
        points.visible = false;
        points.userData.pickRole = 'vertex';
        points.userData.pickable = true;
        points.userData.vertexEntityIds = part.vertexIds;
        group.add(points);
      }
      group.traverse((child: THREE.Object3D) => {
        child.userData.nodeId = item.nodeId;
        child.userData.definitionId = item.definitionId;
      });
      object.add(group);
      this.nodeObjects.set(item.nodeId, object);
      this.modelRoot.add(object);
    }
    this.manifest = { schema_version: '2.0', nodes } as unknown as SceneManifest;
    this.setVertexCloudsVisible(false);
    if (!hadScene) this.pendingFrame = true;
    this.updateGrid();
    this.resize();
  }

  /** True while the scene on screen is a preview (entity details are asked for, not read). */
  get isPreview(): boolean {
    return this.previewSidecars.size > 0;
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
        const vertexPoints = new THREE.Points(vertexGeometry, this.vertexMaterial());
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
    const material = createEdgeMaterial(this.palette.edge);
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
    for (const geometry of this.previewGeometries) geometry.dispose();
    this.previewGeometries = [];
    this.previewSidecars.clear();
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
    this.needsRender = true;
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
    // Fit the bounding sphere in the narrower of the two view angles, so a
    // tall, narrow viewport frames the model as well as a wide one.
    const verticalFov = THREE.MathUtils.degToRad(this.camera.fov);
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * this.camera.aspect);
    const distance = (radius / Math.sin(Math.min(verticalFov, horizontalFov) / 2)) * 0.82;
    this.camera.position.copy(center).add(new THREE.Vector3(1, 0.78, 1).normalize().multiplyScalar(distance));
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
    // setSize cleared the canvas.
    this.needsRender = true;
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.observer.disconnect();
    this.renderer.setAnimationLoop(null);
    this.clearScene();
    if (this.grid) {
      this.grid.geometry.dispose();
      (this.grid.material as THREE.Material).dispose();
    }
    this.gizmoScene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      mesh.geometry?.dispose?.();
      (mesh.material as THREE.Material | undefined)?.dispose?.();
    });
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
