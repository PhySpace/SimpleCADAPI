import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { applyApparentScale, apparentFactor, sizeFromExtent } from "./apparent-size";
import { addGhostPass, GHOST_OPACITY } from "./ghost";
import { SceneLayerHost, type LayerViewLike } from "./layer-host";
import { hitSphere, ndcFromClient } from "./pick";
import { projectPoint } from "../../components/scene/project";

function fakeView() {
  const scene = new THREE.Scene();
  const modelRoot = new THREE.Group();
  modelRoot.rotation.x = Math.PI / 2;
  scene.add(modelRoot);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
  camera.up.set(0, 0, 1);
  camera.position.set(0, -1, 0.3);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const listeners = new Set<() => void>();
  const nodeObjects = new Map<string, THREE.Object3D>();
  let invalidated = 0;
  const view: LayerViewLike = {
    engine: {
      camera,
      domElement: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 200 }) } as unknown as HTMLElement,
      modelRoot,
      controls: { addEventListener: (_t, l) => listeners.add(l), removeEventListener: (_t, l) => listeners.delete(l) },
      invalidate: () => void invalidated++,
    },
    nodes: [{ node_id: "n1", component_id: "arm" }],
    nodeObject: (id) => nodeObjects.get(id),
  };
  return { view, scene, modelRoot, camera, nodeObjects, invalidated: () => invalidated };
}

describe("apparent size", () => {
  it("is distance / reference, clamped", () => {
    const o = { referenceDistance: 2, minFactor: 0.5, maxFactor: 2 };
    expect(apparentFactor(2, o)).toBe(1);
    expect(apparentFactor(3, o)).toBe(1.5);
    expect(apparentFactor(0.1, o)).toBe(0.5);
    expect(apparentFactor(100, o)).toBe(2);
    expect(apparentFactor(NaN, o)).toBe(1);
    expect(apparentFactor(1, { referenceDistance: 0 })).toBe(1);
  });
  it("sizeFromExtent clamps", () => {
    expect(sizeFromExtent(100, 0.1, 2, 50)).toBe(10);
    expect(sizeFromExtent(1, 0.1, 2, 50)).toBe(2);
    expect(sizeFromExtent(1e6, 0.1, 2, 50)).toBe(50);
  });
  it("applyApparentScale scales an object by its camera distance", () => {
    const { camera } = fakeView();
    const near = new THREE.Object3D();
    near.position.set(0, -0.5, 0.15); // half the camera distance
    near.updateMatrixWorld(true);
    const d = near.position.distanceTo(camera.position);
    const f = applyApparentScale(near, camera, 0.01, { referenceDistance: d * 2 });
    expect(f).toBeCloseTo(0.5, 9);
    expect(near.scale.x).toBeCloseTo(0.005, 9);
  });
});

describe("ghost pass", () => {
  it("adds a depth-off translucent child per mesh and skips hit areas and flagged meshes", () => {
    const root = new THREE.Group();
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({ color: "#f00" }));
    const hull = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
    hull.userData.noGhost = true;
    root.add(mesh, hull, hitSphere(1));
    const ghosts = addGhostPass(root);
    expect(ghosts).toHaveLength(1);
    const m = ghosts[0].material as THREE.MeshBasicMaterial;
    expect(m.depthTest).toBe(false);
    expect(m.transparent).toBe(true);
    expect(m.opacity).toBeCloseTo(GHOST_OPACITY, 9);
    expect(m.color.getHexString()).toBe("ff0000");
    expect((mesh.material as THREE.Material).depthTest).toBe(true);
    expect(ghosts[0].parent).toBe(mesh);
  });
});

describe("SceneLayerHost", () => {
  it("puts layer roots in the scene (not the model root) with the model's orientation", () => {
    const { view, scene, modelRoot } = fakeView();
    const host = new SceneLayerHost(view);
    const layer = host.layer("a");
    expect(layer.root.parent).toBe(scene);
    expect(layer.root.parent).not.toBe(modelRoot);
    expect(layer.root.rotation.x).toBeCloseTo(Math.PI / 2, 9);
    expect(host.layer("a")).toBe(layer);
    host.dispose();
  });

  it("propagates hover / selected / active to item state callbacks", () => {
    const { view } = fakeView();
    const host = new SceneLayerHost(view);
    const layer = host.layer("a");
    const seen: string[] = [];
    layer.add({ key: "k", object: new THREE.Group(), onState: (s) => seen.push(`${+s.hover}${+s.selected}${+s.active}`) });
    layer.setHover("k");
    layer.setSelected(["k"]);
    layer.setActive(["k"]);
    layer.setHover(null);
    expect(seen).toEqual(["000", "100", "110", "111", "011"]);
    host.dispose();
  });

  it("makes an anchored item follow its component's node object, and hides it without a node or fallback", () => {
    const { view, nodeObjects } = fakeView();
    const host = new SceneLayerHost(view);
    const layer = host.layer("a");
    const item = layer.add({ key: "k", object: new THREE.Group(), anchor: { componentId: "arm" } });
    expect(item.holder.visible).toBe(false); // no node object yet
    const node = new THREE.Group();
    node.position.set(1, 2, 3);
    view.engine.modelRoot.add(node);
    nodeObjects.set("n1", node);
    host.sync();
    expect(item.holder.visible).toBe(true);
    expect(item.holder.matrix.elements[12]).toBeCloseTo(1, 9);
    node.position.set(4, 0, 0); // a joint moved the part
    host.sync();
    expect(item.holder.matrix.elements[12]).toBeCloseTo(4, 9);
    // the frame's world position follows (layer space is glTF space: same rotation as the model root)
    item.object.updateWorldMatrix(true, false);
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    item.object.getWorldPosition(a);
    node.getWorldPosition(b);
    expect(a.distanceTo(b)).toBeLessThan(1e-9);
    host.dispose();
  });

  it("uses the fallback pose while no node exists", () => {
    const { view } = fakeView();
    const host = new SceneLayerHost(view);
    const item = host.layer("a").add({ key: "k", object: new THREE.Group(), anchor: { componentId: "arm" }, fallback: new THREE.Matrix4().makeTranslation(0, 0, 5) });
    expect(item.holder.visible).toBe(true);
    expect(item.holder.matrix.elements[14]).toBe(5);
    host.dispose();
  });

  it("runs onFrame when the camera moves and picks the nearest hit area", () => {
    const { view, camera } = fakeView();
    const host = new SceneLayerHost(view);
    const layer = host.layer("a");
    let frames = 0;
    const near = new THREE.Group();
    near.add(hitSphere(0.05));
    const far = new THREE.Group();
    far.add(hitSphere(0.05));
    far.position.set(0, 0.5, 0); // glTF: +z toward... behind the near one along the view
    layer.add({ key: "near", object: near, onFrame: () => frames++ });
    layer.add({ key: "far", object: far });
    const before = frames;
    camera.position.x += 0.1;
    camera.lookAt(0, 0, 0);
    host.sync();
    expect(frames).toBeGreaterThan(before);
    // the near item is at the origin: it projects to the centre of the 200x200 canvas
    const centre = projectPoint(new THREE.Vector3(0, 0, 0), camera, 200, 200);
    const hit = layer.pick(centre.x, centre.y);
    expect(hit?.key).toBe("near");
    expect(layer.pick(1, 1)).toBeNull();
    layer.visible = false;
    expect(layer.pick(centre.x, centre.y)).toBeNull();
    host.dispose();
  });
});

describe("projectPoint", () => {
  it("projects the origin to the canvas centre and flags behind-camera points", () => {
    const { camera } = fakeView();
    const p = projectPoint(new THREE.Vector3(0, 0, 0), camera, 400, 200);
    expect(p.x).toBeCloseTo(200, 6);
    expect(p.y).toBeCloseTo(100, 6);
    expect(p.visible).toBe(true);
    expect(projectPoint(new THREE.Vector3(0, -5, 0), camera, 400, 200).visible).toBe(false);
    expect(projectPoint(new THREE.Vector3(50, 0, 0), camera, 400, 200).visible).toBe(false);
  });
  it("ndcFromClient maps the rect corners", () => {
    const r = { left: 10, top: 20, width: 100, height: 50 };
    expect(ndcFromClient(r, 10, 20).toArray()).toEqual([-1, 1]);
    expect(ndcFromClient(r, 110, 70).toArray()).toEqual([1, -1]);
  });
});

describe("component anchors without component_id", () => {
  it("finds the node by the last segment of its id", () => {
    const { view, nodeObjects } = fakeView();
    (view as { nodes: unknown }).nodes = [{ node_id: "node/rig/post" }, { node_id: "node/rig/arm", component_id: null }];
    const host = new SceneLayerHost(view);
    const node = new THREE.Group();
    node.position.set(0.025, 0, 0.02);
    view.engine.modelRoot.add(node);
    nodeObjects.set("node/rig/arm", node);
    const item = host.layer("a").add({ key: "k", object: new THREE.Group(), anchor: { componentId: "arm" } });
    expect(item.holder.visible).toBe(true);
    expect(item.holder.matrix.elements[12]).toBeCloseTo(0.025, 9);
    host.dispose();
  });
});
