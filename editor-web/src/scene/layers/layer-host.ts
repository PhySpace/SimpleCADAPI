/** Scene layers: named groups of overlay objects living in the viewer's three.js scene (connector frames, sketch
 * display, dimensions, datum planes, mate previews, ...).
 *
 * CONTRACT
 *  - `layerHostFor(view)` gives the one SceneLayerHost of a SceneView; `host.layer(name)` gets or creates a named
 *    SceneLayer, `host.removeLayer(name)` / `layer.dispose()` removes it.
 *  - A layer's `root` is a child of the viewer's THREE scene (NOT of the model root, so a scene reload cannot
 *    delete it and the model's bounds / grid / framing never include overlay geometry).  It carries the same
 *    rotation as the model root, so layer space is glTF space: metres, +Y up (see cad-three.ts for the CAD
 *    helpers).  Objects are drawn on the viewer's OVERLAY layer: depth-tested against the model's faces, never
 *    darkened by ambient occlusion.
 *  - Items: `layer.add({ key, object, anchor?, fallback?, onState?, onFrame? })`.  The object lives in an item
 *    `holder`.  If `anchor` names a component (or a viewer node), the holder follows that node object's
 *    transform every frame: a solved joint or the exploded view moves the item with the part.  A component whose
 *    node is not (yet) in the viewer uses `fallback` (a glTF-space matrix, e.g. its document placement) or, with
 *    no fallback, is hidden.  Without an anchor the item sits in the world.
 *  - State: `layer.setHover(key)`, `setSelected(keys)`, `setActive(keys)` propagate to each item's `onState`.
 *  - `onFrame(ctx)` runs when the camera moved (or anchors changed): use it for apparent-size scaling.
 *  - `layer.pick(clientX, clientY)` raycasts the layer's hit areas (see pick.ts) and returns the nearest key.
 *  - `host.subscribe(fn)` calls `fn` after every camera / anchor change (labels use it to re-project).
 */

import * as THREE from 'three';

import { OVERLAY_LAYER } from '../renderer';
import { ndcFromClient, pickHitAreas, type PickHit } from './pick';

/** What a SceneLayerHost needs of a viewer: SceneView satisfies it, and tests can fake it. */
export interface LayerViewLike {
  readonly engine: {
    readonly camera: THREE.PerspectiveCamera;
    readonly domElement: HTMLElement;
    readonly modelRoot: THREE.Object3D;
    readonly controls: { addEventListener(type: 'change', listener: () => void): void; removeEventListener(type: 'change', listener: () => void): void };
    invalidate(): void;
  };
  readonly nodes: ReadonlyArray<{ node_id: string; component_id?: string | null }>;
  nodeObject(nodeId: string): THREE.Object3D | undefined;
}

export type Anchor = { componentId: string } | { nodeId: string };

export type ItemState = { hover: boolean; selected: boolean; active: boolean };

export type FrameContext = { camera: THREE.PerspectiveCamera; host: SceneLayerHost; item: LayerItem };

export type LayerItemOptions = {
  key: string;
  object: THREE.Object3D;
  anchor?: Anchor | null;
  /** The pose (relative to the layer root, glTF space) used while `anchor` resolves to no node. */
  fallback?: THREE.Matrix4;
  onState?: (state: ItemState, item: LayerItem) => void;
  onFrame?: (context: FrameContext) => void;
};

export class LayerItem {
  readonly key: string;
  readonly object: THREE.Object3D;
  /** Follows the anchor; `object` is its child. */
  readonly holder = new THREE.Group();
  anchor: Anchor | null;
  fallback: THREE.Matrix4 | undefined;
  state: ItemState = { hover: false, selected: false, active: false };
  readonly onState: LayerItemOptions['onState'];
  readonly onFrame: LayerItemOptions['onFrame'];

  constructor(options: LayerItemOptions) {
    this.key = options.key;
    this.object = options.object;
    this.anchor = options.anchor ?? null;
    this.fallback = options.fallback;
    this.onState = options.onState;
    this.onFrame = options.onFrame;
    this.holder.name = `layer-item:${options.key}`;
    this.holder.userData.itemKey = options.key;
    this.holder.matrixAutoUpdate = false;
    this.holder.add(options.object);
    this.holder.traverse((o) => o.layers.set(OVERLAY_LAYER));
  }

  /** Where the item is in the world (its holder's origin). */
  worldPosition(target = new THREE.Vector3()): THREE.Vector3 {
    this.object.updateWorldMatrix(true, false);
    return this.object.getWorldPosition(target);
  }
}

const sameState = (a: ItemState, b: ItemState) => a.hover === b.hover && a.selected === b.selected && a.active === b.active;

export class SceneLayer {
  readonly name: string;
  readonly root = new THREE.Group();
  private items = new Map<string, LayerItem>();
  private hover: string | null = null;
  private selected = new Set<string>();
  private active = new Set<string>();
  private _visible = true;

  constructor(readonly host: SceneLayerHost, name: string) {
    this.name = name;
    this.root.name = `scene-layer:${name}`;
    this.root.userData.pickable = false;
  }

  get visible(): boolean { return this._visible; }
  set visible(value: boolean) {
    if (value === this._visible) return;
    this._visible = value;
    this.root.visible = value;
    this.host.invalidate();
  }

  get size(): number { return this.items.size; }
  keys(): string[] { return [...this.items.keys()]; }
  get(key: string): LayerItem | undefined { return this.items.get(key); }

  /** Add (replacing any item with the same key) an object to the layer. */
  add(options: LayerItemOptions): LayerItem {
    this.remove(options.key);
    const item = new LayerItem(options);
    this.items.set(item.key, item);
    this.root.add(item.holder);
    this.applyState(item, true);
    this.host.sync(true);
    this.host.invalidate();
    return item;
  }

  remove(key: string): void {
    const item = this.items.get(key);
    if (!item) return;
    this.items.delete(key);
    item.holder.removeFromParent();
    disposeTree(item.holder);
    this.host.invalidate();
  }

  clear(): void {
    for (const key of this.keys()) this.remove(key);
  }

  /** Items in `values` are hovered / selected / active (an unknown key is ignored, but remembered for later adds). */
  setHover(key: string | null): void {
    if (key === this.hover) return;
    this.hover = key;
    this.refreshStates();
  }
  setSelected(keys: Iterable<string>): void {
    this.selected = new Set(keys);
    this.refreshStates();
  }
  setActive(keys: Iterable<string>): void {
    this.active = new Set(keys);
    this.refreshStates();
  }
  hoverKey(): string | null { return this.hover; }

  private applyState(item: LayerItem, force = false): void {
    const next: ItemState = { hover: this.hover === item.key, selected: this.selected.has(item.key), active: this.active.has(item.key) };
    if (!force && sameState(next, item.state)) return;
    item.state = next;
    item.onState?.(next, item);
  }

  private refreshStates(): void {
    for (const item of this.items.values()) this.applyState(item);
    this.host.invalidate();
  }

  /** The nearest item whose hit area is under the pointer, or null. */
  pick(clientX: number, clientY: number): PickHit | null {
    if (!this._visible) return null;
    const { camera, domElement } = this.host.view.engine;
    const raycaster = this.host.raycaster;
    camera.updateMatrixWorld();
    raycaster.setFromCamera(ndcFromClient(domElement.getBoundingClientRect(), clientX, clientY), camera);
    this.root.updateMatrixWorld(true);
    return pickHitAreas(raycaster, [...this.items.values()].map((i) => i.holder));
  }

  dispose(): void {
    this.clear();
    this.root.removeFromParent();
    this.host.forget(this);
  }
}

export class SceneLayerHost {
  readonly raycaster = new THREE.Raycaster();
  private layers = new Map<string, SceneLayer>();
  private subscribers = new Set<() => void>();
  private scene: THREE.Object3D | null;
  private lastPos = new THREE.Vector3(NaN, 0, 0);
  private lastQuat = new THREE.Quaternion();
  private lastFov = NaN;
  private raf = 0;
  private listening = false;
  private disposed = false;
  private readonly onControlsChange = () => this.sync();
  private readonly scratch = new THREE.Matrix4();
  private readonly inverse = new THREE.Matrix4();

  constructor(readonly view: LayerViewLike) {
    this.scene = view.engine.modelRoot.parent;
  }

  /** Get or create the layer `name`. */
  layer(name: string): SceneLayer {
    let layer = this.layers.get(name);
    if (!layer) {
      layer = new SceneLayer(this, name);
      // Same orientation as the model root: layer space is glTF space.
      layer.root.rotation.copy(this.view.engine.modelRoot.rotation);
      layer.root.renderOrder = 10;
      (this.scene ?? this.view.engine.modelRoot.parent)?.add(layer.root);
      this.layers.set(name, layer);
      this.start();
    }
    return layer;
  }

  hasLayer(name: string): boolean { return this.layers.has(name); }

  removeLayer(name: string): void {
    this.layers.get(name)?.dispose();
  }

  /** Called by SceneLayer.dispose. */
  forget(layer: SceneLayer): void {
    if (this.layers.get(layer.name) === layer) this.layers.delete(layer.name);
    this.view.engine.invalidate();
    if (this.layers.size === 0 && this.subscribers.size === 0) this.stop();
  }

  /** `fn` runs after every sync that saw the camera move or an anchor change (and once on subscribe). Returns unsubscribe. */
  subscribe(fn: () => void): () => void {
    this.subscribers.add(fn);
    this.start();
    fn();
    return () => {
      this.subscribers.delete(fn);
      if (this.layers.size === 0 && this.subscribers.size === 0) this.stop();
    };
  }

  invalidate(): void {
    this.view.engine.invalidate();
  }

  /** Follow the anchors and run the per-frame hooks; cheap when nothing moved.  `force` re-runs the hooks. */
  sync(force = false): void {
    if (this.disposed) return;
    const { camera } = this.view.engine;
    const cameraMoved =
      force ||
      !this.lastPos.equals(camera.position) ||
      !this.lastQuat.equals(camera.quaternion) ||
      this.lastFov !== camera.fov;
    this.lastPos.copy(camera.position);
    this.lastQuat.copy(camera.quaternion);
    this.lastFov = camera.fov;
    let anchorsMoved = false;
    for (const layer of this.layers.values()) {
      layer.root.updateMatrixWorld(true);
      for (const item of layer.keys().map((k) => layer.get(k)!)) {
        if (this.follow(layer, item)) anchorsMoved = true;
      }
    }
    if (!cameraMoved && !anchorsMoved) return;
    for (const layer of this.layers.values()) {
      if (!layer.visible) continue;
      for (const key of layer.keys()) {
        const item = layer.get(key)!;
        item.holder.updateWorldMatrix(true, true);
        item.onFrame?.({ camera, host: this, item });
      }
    }
    for (const fn of this.subscribers) fn();
    if (anchorsMoved) this.view.engine.invalidate();
  }

  /** Move one holder to its anchor's pose; true when the holder's matrix or visibility changed. */
  private follow(layer: SceneLayer, item: LayerItem): boolean {
    const target = this.resolve(item.anchor);
    let next: THREE.Matrix4 | null;
    if (!item.anchor) next = this.scratch.identity();
    else if (target) {
      target.updateWorldMatrix(true, false);
      next = this.scratch.multiplyMatrices(this.inverse.copy(layer.root.matrixWorld).invert(), target.matrixWorld);
    } else next = item.fallback ? this.scratch.copy(item.fallback) : null;
    const visible = next !== null;
    let changed = false;
    if (item.holder.visible !== visible) {
      item.holder.visible = visible;
      changed = true;
    }
    if (next && !item.holder.matrix.equals(next)) {
      item.holder.matrix.copy(next);
      item.holder.matrixWorldNeedsUpdate = true;
      changed = true;
    }
    return changed;
  }

  private resolve(anchor: Anchor | null): THREE.Object3D | undefined {
    if (!anchor) return undefined;
    if ('nodeId' in anchor) return this.view.nodeObject(anchor.nodeId);
    // The node of a component: by its `component_id` when the scene carries one, else by the last segment of the
    // node id (the SDK names an assembly's component nodes `node/<assembly>/<component>`).
    const nodes = this.view.nodes;
    const node = nodes.find((n) => n.component_id === anchor.componentId) ?? nodes.find((n) => n.node_id.split('/').pop() === anchor.componentId);
    return node ? this.view.nodeObject(node.node_id) : undefined;
  }

  private start(): void {
    if (this.disposed) return;
    if (!this.listening) {
      this.view.engine.controls.addEventListener('change', this.onControlsChange);
      this.listening = true;
    }
    if (!this.raf && typeof requestAnimationFrame === 'function') {
      const loop = () => {
        this.sync();
        this.raf = requestAnimationFrame(loop);
      };
      this.raf = requestAnimationFrame(loop);
    }
  }

  private stop(): void {
    if (this.raf && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(this.raf);
    this.raf = 0;
    if (this.listening) this.view.engine.controls.removeEventListener('change', this.onControlsChange);
    this.listening = false;
  }

  dispose(): void {
    for (const layer of [...this.layers.values()]) layer.dispose();
    this.subscribers.clear();
    this.stop();
    this.disposed = true;
  }
}

function disposeTree(root: THREE.Object3D): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((o) => {
    if (o instanceof THREE.Mesh || o instanceof THREE.Line || o instanceof THREE.Points) {
      geometries.add(o.geometry);
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) materials.add(m);
    }
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
}

const hosts = new WeakMap<object, SceneLayerHost>();

/** The layer host of a viewer (created on first use; one per SceneView). */
export function layerHostFor(view: LayerViewLike): SceneLayerHost {
  let host = hosts.get(view);
  if (!host) {
    host = new SceneLayerHost(view);
    hosts.set(view, host);
  }
  return host;
}
