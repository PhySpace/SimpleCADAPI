import { useEffect, useRef } from "react";
import * as THREE from "three";

import type { Vec3 } from "@/lib/sketch-plane";
import { rayThrough } from "@/scene/camera-projection";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";

const AXES: Record<string, Vec3> = { "+x": [1, 0, 0], "-x": [-1, 0, 0], "+y": [0, 1, 0], "-y": [0, -1, 0], "+z": [0, 0, 1], "-z": [0, 0, -1] };
const PLACED = "#e4572e";
const HOVER = "#f2a65a";

/** Where a hole goes, as its form says: the start point, how the direction is chosen ("face" follows the surface's
 * normal into the material), the vector for "face"/"vector", the diameter and the depth (mm). */
export type HoleDraft = { position: Vec3 | null; direction: string; vector: Vec3 | null; diameter: number; depth: number };

/** The drilling direction of a draft at a surface point with outward normal `normal` (null when not on the model). */
export function drillDirection(draft: Pick<HoleDraft, "direction" | "vector">, normal: Vec3 | null): Vec3 | null {
  if (draft.direction in AXES) return AXES[draft.direction];
  if (draft.direction === "face" && normal) return [-normal[0], -normal[1], -normal[2]];
  const v = draft.vector;
  const length = v ? Math.hypot(v[0], v[1], v[2]) : 0;
  return v && length > 1e-9 ? [v[0] / length, v[1] / length, v[2] / length] : null;
}

/** A ghost of the hole: the cylinder it cuts and a ring where it starts, drawn through the model (world = CAD / 1000). */
function ghost(color: string, opacity: number): THREE.Group {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.CylinderGeometry(1, 1, 1, 40, 1, true).rotateX(Math.PI / 2).translate(0, 0, 0.5),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthTest: false, depthWrite: false, side: THREE.DoubleSide }),
  );
  body.name = "body";
  const ring = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(Array.from({ length: 48 }, (_, i) => new THREE.Vector3(Math.cos((i / 48) * Math.PI * 2), Math.sin((i / 48) * Math.PI * 2), 0))),
    new THREE.LineBasicMaterial({ color, depthTest: false }),
  );
  ring.name = "ring";
  group.add(body, ring);
  group.renderOrder = 20;
  group.traverse((o) => {
    o.layers.enable(OVERLAY_LAYER);
    o.renderOrder = 20;
  });
  group.visible = false;
  return group;
}

/** Puts a ghost at `point` (mm), cutting along `direction`, `diameter` across and `depth` deep. */
function place(object: THREE.Group, point: Vec3, direction: Vec3, diameter: number, depth: number): void {
  const r = Math.max(diameter, 0.01) / 2000;
  object.position.set(point[0] / 1000, point[1] / 1000, point[2] / 1000);
  object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...direction));
  object.getObjectByName("body")!.scale.set(r, r, Math.max(depth, 0.01) / 1000);
  object.getObjectByName("ring")!.scale.set(r, r, 1);
  object.visible = true;
}

/** While a hole's form is open: a ghost of the hole follows the pointer over the model (its axis along the drilling
 * direction: the surface's normal there for "face"), and a click on the model places it, filling the start point (and
 * the direction, for "face").  The placed hole stays drawn while the form's numbers change.  Display only: the point and
 * normal come from the drawn surface under the pointer; nothing is computed by the kernel. */
export function HolePlacer({ view, draft, onPlace }: { view: SceneView; draft: HoleDraft; onPlace: (point: Vec3, normal: Vec3) => void }) {
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const placeRef = useRef(onPlace);
  placeRef.current = onPlace;
  const placedRef = useRef<THREE.Group | null>(null);
  const placedNormal = useRef<Vec3 | null>(null);

  useEffect(() => {
    const { engine } = view;
    const hover = ghost(HOVER, 0.28);
    const placed = ghost(PLACED, 0.45);
    engine.threeScene.add(hover, placed);
    placedRef.current = placed;
    const raycaster = new THREE.Raycaster();
    const element = engine.domElement;
    const surfaceAt = (event: PointerEvent): { point: Vec3; normal: Vec3 } | null => {
      const rect = element.getBoundingClientRect();
      const ndc = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      rayThrough(raycaster, ndc, engine.camera);
      const hit = raycaster.intersectObjects(engine.modelRoot.children, true).find((h) => h.object instanceof THREE.Mesh && h.face && h.object.visible);
      if (!hit || !hit.face) return null;
      const normal = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
      // the side the camera looks at: a normal facing away is the triangle's back
      if (normal.dot(raycaster.ray.direction) > 0) normal.negate();
      return { point: [hit.point.x * 1000, hit.point.y * 1000, hit.point.z * 1000], normal: [normal.x, normal.y, normal.z] };
    };
    let down: { x: number; y: number } | null = null;
    const onMove = (event: PointerEvent) => {
      if (event.buttons !== 0) {
        hover.visible = false;
        return;
      }
      const at = surfaceAt(event);
      const direction = at && drillDirection(draftRef.current, at.normal);
      if (at && direction) place(hover, at.point, direction, draftRef.current.diameter, draftRef.current.depth);
      else hover.visible = false;
      element.style.cursor = at ? "crosshair" : "";
      engine.invalidate();
    };
    const onDown = (event: PointerEvent) => {
      down = event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
    };
    const onUp = (event: PointerEvent) => {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) return;
      down = null;
      const at = surfaceAt(event);
      if (!at) return;
      placedNormal.current = at.normal;
      placeRef.current(at.point, at.normal);
    };
    const onLeave = () => {
      hover.visible = false;
      engine.invalidate();
    };
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointerleave", onLeave);
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointerleave", onLeave);
      element.style.cursor = "";
      for (const object of [hover, placed]) {
        object.removeFromParent();
        object.traverse((o) => {
          const mesh = o as THREE.Mesh;
          mesh.geometry?.dispose();
          (mesh.material as THREE.Material | undefined)?.dispose?.();
        });
      }
      placedRef.current = null;
      engine.invalidate();
    };
  }, [view]);

  // The placed hole follows the form: its point, direction, diameter and depth.
  useEffect(() => {
    const placed = placedRef.current;
    if (!placed) return;
    const direction = draft.position && drillDirection(draft, placedNormal.current);
    if (draft.position && direction) place(placed, draft.position, direction, draft.diameter, draft.depth);
    else placed.visible = false;
    view.engine.invalidate();
  }, [draft, view]);

  return null;
}
