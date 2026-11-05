import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { Move3d, RotateCw } from "lucide-react";

import { patchCorners } from "@/lib/workplanes";
import { placeValues, placedFrame, type PlaceFrame, type PlaceValues } from "@/lib/workplane-place";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";
import type { Vec3 } from "@/lib/sketch-plane";

export type PlaceMode = "translate" | "rotate";

/** One base the placer offers: a name the cell writes (XY, a workplane variable, "face") and its frame in world mm. */
export type PlaceBase = { value: string; label: string; frame: PlaceFrame };

const COLOR = "#2563eb";
/** Default snapping while dragging (Shift drags freely): 1 mm, 5 degrees. */
const SNAP = { move: 0.001, turn: THREE.MathUtils.degToRad(5) };

/** World (CAD mm, Z up) frame -> the pose of an object in the viewer's world (metres, the same axes). */
function poseOf(frame: PlaceFrame): { position: THREE.Vector3; quaternion: THREE.Quaternion } {
  const basis = new THREE.Matrix4().makeBasis(new THREE.Vector3(...frame.x_axis), new THREE.Vector3(...frame.y_axis), new THREE.Vector3(...frame.normal));
  return { position: new THREE.Vector3(frame.origin[0] / 1000, frame.origin[1] / 1000, frame.origin[2] / 1000), quaternion: new THREE.Quaternion().setFromRotationMatrix(basis) };
}

function frameOf(object: THREE.Object3D): PlaceFrame {
  const axis = (x: number, y: number, z: number): Vec3 => {
    const v = new THREE.Vector3(x, y, z).applyQuaternion(object.quaternion);
    return [v.x, v.y, v.z];
  };
  return {
    origin: [object.position.x * 1000, object.position.y * 1000, object.position.z * 1000],
    x_axis: axis(1, 0, 0),
    y_axis: axis(0, 1, 0),
    normal: axis(0, 0, 1),
  };
}

/** The draft plane: a square patch in the frame's XY with its outline and a normal tick, drawn over the model. */
function draftPatch(half: number): THREE.Group {
  const group = new THREE.Group();
  const frame: PlaceFrame = { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0], normal: [0, 0, 1] };
  const corners = patchCorners(frame, half / 1000).map((c) => new THREE.Vector3(...c));
  group.add(
    new THREE.Mesh(
      new THREE.BufferGeometry().setFromPoints([corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]),
      new THREE.MeshBasicMaterial({ color: COLOR, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }),
    ),
  );
  group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([...corners, corners[0]]), new THREE.LineBasicMaterial({ color: COLOR })));
  group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, half / 2000)]), new THREE.LineBasicMaterial({ color: COLOR })));
  return group;
}

/** Places a new workplane with handles: the draft plane sits on `base` moved and turned by `values`; dragging the move
 * arrows or the turn rings changes the values (snapped to 1 mm / 5 degrees, Shift for free), typing them moves the
 * handles.  Nothing is computed from the model: the frame is the base's and the SDK's own formula (lib/workplane-place). */
export function WorkplanePlacer({
  view,
  base,
  values,
  mode,
  half,
  onChange,
}: {
  view: SceneView;
  base: PlaceFrame;
  values: PlaceValues;
  mode: PlaceMode;
  /** Half the patch's side, mm. */
  half: number;
  onChange: (values: PlaceValues) => void;
}) {
  const targetRef = useRef<THREE.Group | null>(null);
  const controlsRef = useRef<TransformControls | null>(null);
  const dragging = useRef(false);
  const changeRef = useRef(onChange);
  changeRef.current = onChange;
  const baseRef = useRef(base);
  baseRef.current = base;

  // The draft and its handles, for the life of the placer.
  useEffect(() => {
    const { engine } = view;
    const target = new THREE.Group();
    target.add(draftPatch(half));
    target.traverse((o) => o.layers.enable(OVERLAY_LAYER));
    engine.threeScene.add(target);
    const controls = new TransformControls(engine.camera, engine.domElement);
    controls.setSpace("local");
    controls.setTranslationSnap(SNAP.move);
    controls.setRotationSnap(SNAP.turn);
    controls.attach(target);
    const helper = controls.getHelper();
    helper.traverse((o) => o.layers.enable(OVERLAY_LAYER));
    engine.threeScene.add(helper);
    const onRender = () => engine.invalidate();
    const onDrag = (event: { value: unknown }) => {
      dragging.current = Boolean(event.value);
      engine.controls.enabled = !dragging.current;
    };
    const onObject = () => changeRef.current(placeValues(baseRef.current, frameOf(target)));
    controls.addEventListener("change", onRender);
    controls.addEventListener("dragging-changed", onDrag);
    controls.addEventListener("objectChange", onObject);
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Shift") return;
      const free = event.type === "keydown";
      controls.setTranslationSnap(free ? null : SNAP.move);
      controls.setRotationSnap(free ? null : SNAP.turn);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    targetRef.current = target;
    controlsRef.current = controls;
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
      target.traverse((o) => {
        const mesh = o as THREE.Mesh;
        mesh.geometry?.dispose();
        (mesh.material as THREE.Material | undefined)?.dispose?.();
      });
      engine.controls.enabled = true;
      engine.invalidate();
      targetRef.current = null;
      controlsRef.current = null;
    };
  }, [view, half]);

  useEffect(() => {
    controlsRef.current?.setMode(mode);
    view.engine.invalidate();
  }, [mode, view]);

  // Typed values (or a new base) move the draft; a drag in progress is the source of the values, not their target.
  useEffect(() => {
    const target = targetRef.current;
    if (!target || dragging.current) return;
    const pose = poseOf(placedFrame(base, values));
    target.position.copy(pose.position);
    target.quaternion.copy(pose.quaternion);
    target.updateMatrixWorld(true);
    view.engine.invalidate();
  }, [base, values, view, half]);

  return null;
}

/** The placer's panel: the base, move or turn, the six numbers, create and cancel. */
export function WorkplanePlacePanel({
  title = "Workplane",
  createLabel = "Create",
  bases,
  base,
  values,
  mode,
  name,
  busy,
  error,
  onBase,
  onMode,
  onValues,
  onName,
  onCreate,
  onCancel,
}: {
  /** What is being placed (the panel's heading). */
  title?: string;
  createLabel?: string;
  bases: PlaceBase[];
  base: string;
  values: PlaceValues;
  mode: PlaceMode;
  name: string;
  busy: boolean;
  error: string | null;
  onBase: (value: string) => void;
  onMode: (mode: PlaceMode) => void;
  onValues: (values: PlaceValues) => void;
  onName: (name: string) => void;
  onCreate: () => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const fields: { key: string; label: string; get: (v: PlaceValues) => number; set: (v: PlaceValues, n: number) => PlaceValues }[] = [
    { key: "dx", label: "x", get: (v) => v.move[0], set: (v, n) => ({ ...v, move: [n, v.move[1], v.move[2]] }) },
    { key: "dy", label: "y", get: (v) => v.move[1], set: (v, n) => ({ ...v, move: [v.move[0], n, v.move[2]] }) },
    { key: "dz", label: "n", get: (v) => v.move[2], set: (v, n) => ({ ...v, move: [v.move[0], v.move[1], n] }) },
    { key: "rx", label: "∠x", get: (v) => v.rx, set: (v, n) => ({ ...v, rx: n }) },
    { key: "ry", label: "∠y", get: (v) => v.ry, set: (v, n) => ({ ...v, ry: n }) },
    { key: "rz", label: "∠n", get: (v) => v.rz, set: (v, n) => ({ ...v, rz: n }) },
  ];
  const commit = (key: string, text: string) => {
    const field = fields.find((f) => f.key === key)!;
    const number = Number(text);
    setDraft((d) => {
      const { [key]: _, ...rest } = d;
      return rest;
    });
    if (Number.isFinite(number)) onValues(field.set(values, number));
  };
  return (
    <div className="pointer-events-auto absolute left-3 top-3 z-30 flex max-w-[min(440px,90%)] flex-col gap-2 border-2 border-primary bg-popover px-3 py-2 text-[11px] shadow-[4px_4px_0_var(--shadow-hard)]" data-testid={title === "Workplane" ? "workplane-placer" : `${title.toLowerCase()}-placer`}>
      <div className="scroll-row items-center gap-2">
        <span className="font-semibold">{title}</span>
        <input
          id="workplane-place-name"
          aria-label="name"
          className="w-20 border border-input bg-background px-1 font-mono"
          value={name}
          onChange={(event) => onName(event.target.value)}
        />
        <span className="text-muted-foreground">on</span>
        <select id="workplane-place-base" aria-label="base" className="border border-input bg-background px-1" value={base} onChange={(event) => onBase(event.target.value)}>
          {bases.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <span className="flex border border-input">
          <button type="button" title="Move (G)" className={`flex items-center gap-1 px-1.5 ${mode === "translate" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => onMode("translate")}>
            <Move3d className="size-3" /> move
          </button>
          <button type="button" title="Turn (R)" className={`flex items-center gap-1 px-1.5 ${mode === "rotate" ? "bg-primary text-primary-foreground" : ""}`} onClick={() => onMode("rotate")}>
            <RotateCw className="size-3" /> turn
          </button>
        </span>
      </div>
      <div className="scroll-row items-center gap-1.5">
        {fields.map((field) => (
          <label key={field.key} className="flex items-center gap-0.5">
            <span className="text-muted-foreground">{field.label}</span>
            <input
              id={`workplane-place-${field.key}`}
              className="w-14 border border-input bg-background px-1 text-right font-mono tabular-nums"
              value={draft[field.key] ?? String(+field.get(values).toFixed(3))}
              onChange={(event) => setDraft((d) => ({ ...d, [field.key]: event.target.value }))}
              onBlur={(event) => commit(field.key, event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  commit(field.key, (event.target as HTMLInputElement).value);
                  event.stopPropagation();
                }
              }}
            />
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button type="button" disabled={busy} className="border-2 border-primary bg-primary px-2 py-0.5 font-semibold text-primary-foreground disabled:opacity-50" onClick={onCreate}>
          {createLabel} (Enter)
        </button>
        <button type="button" className="border border-border px-2 py-0.5 hover:bg-accent" onClick={onCancel}>
          Cancel (Esc)
        </button>
        <span className="text-muted-foreground">drag the arrows to move, the rings to turn · Shift: no snapping</span>
      </div>
      {error && (
        <div role="alert" className="text-fail">
          {error}
        </div>
      )}
    </div>
  );
}
