import * as THREE from "three";

import { anchorOfEntity, meanPoint } from "@/lib/action-bar";
import type { SelectionItem } from "@/lib/selection";
import type { Vec3 } from "@/lib/sketch-plane";
import type { SceneView } from "@/scene/scene-view";

/** The centre of a body's bounds in the world (mm), or null when the scene holds no node of that id. */
export function nodeCentreMm(view: SceneView, nodeId: string): Vec3 | null {
  const object = view.nodeObject(nodeId);
  if (!object) return null;
  object.updateWorldMatrix(true, true);
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return null;
  const c = box.getCenter(new THREE.Vector3());
  return [c.x * 1000, c.y * 1000, c.z * 1000];
}

/** Where on the model the bar for a selection hangs (mm): the middle of the picked faces and edges, the middle of picked bodies'
 * bounds, or `sketchAt` for picked sketches.  Null when nothing says (the bar then docks at the top). */
export function selectionAnchorMm(view: SceneView, items: readonly SelectionItem[], sketchAt: Vec3 | null): Vec3 | null {
  if (sketchAt) return sketchAt;
  const points: Vec3[] = [];
  for (const item of items) {
    const point = item.kind === "solid" || item.kind === "component" ? nodeCentreMm(view, item.nodeId) : (anchorOfEntity(item) ?? nodeCentreMm(view, item.nodeId));
    if (point) points.push(point);
  }
  return meanPoint(points);
}
