import { useEffect, useRef } from "react";
import * as THREE from "three";
import { TransformControls } from "three/addons/controls/TransformControls.js";

import type { Vec3 } from "@/lib/sketch-plane";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";

/** Snap of a drag, mm (Shift drags freely). */
const SNAP_MM = 0.5;

/** An arrow on a picked face that drags a distance (mm) along `normal`: a press / pull's (along the outward normal; dragged
 * in, the distance goes negative), a shell's wall thickness (into the body, at least `min`).  Typing the number moves it.
 * The scene is the CAD frame in metres. */
export function PressPullHandle({
  view,
  origin,
  normal,
  distance,
  min,
  onChange,
}: {
  view: SceneView;
  /** A point of the face, mm (its centroid). */
  origin: Vec3;
  /** The face's outward unit normal. */
  normal: Vec3;
  distance: number;
  /** The smallest distance the drag gives (none: any, negative included). */
  min?: number;
  onChange: (distance: number, done: boolean) => void;
}) {
  const targetRef = useRef<THREE.Group | null>(null);
  const dragging = useRef(false);
  const changeRef = useRef((value: number, done: boolean) => onChange(min === undefined ? value : Math.max(min, value), done));
  changeRef.current = (value: number, done: boolean) => onChange(min === undefined ? value : Math.max(min, value), done);
  const at = useRef({ origin, normal });
  at.current = { origin, normal };

  useEffect(() => {
    const { engine } = view;
    const axis = new THREE.Vector3(...normal).normalize();
    const base = new THREE.Vector3(...origin).multiplyScalar(0.001);
    const target = new THREE.Group();
    target.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axis);
    target.position.copy(base);
    engine.threeScene.add(target);
    const controls = new TransformControls(engine.camera, engine.domElement);
    controls.setMode("translate");
    controls.setSpace("local");
    controls.showX = false;
    controls.showY = false;
    controls.setTranslationSnap(SNAP_MM / 1000);
    controls.attach(target);
    const helper = controls.getHelper();
    helper.traverse((o) => o.layers.enable(OVERLAY_LAYER));
    engine.threeScene.add(helper);
    const measured = () => Math.round(target.position.clone().sub(base).dot(axis) * 1e6) / 1e3;
    const onRender = () => engine.invalidate();
    const onDrag = (event: { value: unknown }) => {
      dragging.current = Boolean(event.value);
      engine.controls.enabled = !dragging.current;
      if (!dragging.current) changeRef.current(measured(), true);
    };
    const onObject = () => changeRef.current(measured(), false);
    controls.addEventListener("change", onRender);
    controls.addEventListener("dragging-changed", onDrag);
    controls.addEventListener("objectChange", onObject);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Shift") controls.setTranslationSnap(event.type === "keydown" ? null : SNAP_MM / 1000);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    targetRef.current = target;
    engine.invalidate();
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
      controls.removeEventListener("change", onRender);
      controls.removeEventListener("dragging-changed", onDrag);
      controls.removeEventListener("objectChange", onObject);
      controls.detach();
      helper.removeFromParent();
      controls.dispose();
      target.removeFromParent();
      engine.controls.enabled = true;
      engine.invalidate();
      targetRef.current = null;
    };
    // the handle is made once per face: origin and normal do not change while it stands
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // A typed distance moves the arrow; a drag in progress is the source of the distance, not its target.
  useEffect(() => {
    const target = targetRef.current;
    if (!target || dragging.current || !Number.isFinite(distance)) return;
    const { origin: o, normal: n } = at.current;
    target.position.set(...o).multiplyScalar(0.001).addScaledVector(new THREE.Vector3(...n).normalize(), distance / 1000);
    view.engine.invalidate();
  }, [distance, view]);

  return null;
}
