import { Check, Pencil, Rocket, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { HintBanner } from "@/components/HintBanner";
import { SketchDrawer, StatusBadge } from "@/components/sketch/SketchDrawer";
import { SketchOverlay, useViewer } from "@/components/sketch/SketchOverlay";
import { SketchProject } from "@/components/sketch/SketchProject";
import { SketchToolbar } from "@/components/sketch/SketchToolbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { FeatureCommand } from "@/lib/features";
import { CellFailure, suggestName, validateName, type FeatureRow } from "@/lib/features";
import { docToJson, type SketchDoc } from "@/lib/sketch";
import { PLANES, frameOf, planeLabel, projectOnPlane, rayPlane, viewPose, worldToPlane, planeToWorld, type Plane, type PlaneSpec } from "@/lib/sketch-plane";
import { defaultExtrudeDistance, sketchShape } from "@/lib/sketch-scene";
import { fitDistanceMm, planeToScreen, screenRay } from "@/lib/sketch-view";
import { projectSources } from "@/lib/sketch-edit";
import { useSketchEditor } from "@/lib/useSketchEditor";
import { planeSegments } from "@/lib/sketch-face";
import { disposeObject } from "@/scene/cad-three";
import type { PickResult, SceneView } from "@/scene/scene-view";

/** The model's edges (the line segments the viewport draws them with) in world mm, visible ones only. */
function modelEdges(view: SceneView): [[number, number, number], [number, number, number]][] {
  const root = view.engine.modelRoot;
  root.updateMatrixWorld(true);
  const out: [[number, number, number], [number, number, number]][] = [];
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const shown = (object: THREE.Object3D): boolean => {
    for (let at: THREE.Object3D | null = object; at; at = at.parent) if (!at.visible) return false;
    return true;
  };
  root.traverse((object) => {
    if (!(object instanceof THREE.LineSegments) || !shown(object)) return;
    const position = object.geometry.getAttribute("position");
    const index = object.geometry.getIndex();
    const count = index ? index.count : position.count;
    for (let i = 0; i + 1 < count; i += 2) {
      a.fromBufferAttribute(position, index ? index.getX(i) : i).applyMatrix4(object.matrixWorld).multiplyScalar(1000);
      b.fromBufferAttribute(position, index ? index.getX(i + 1) : i + 1).applyMatrix4(object.matrixWorld).multiplyScalar(1000);
      out.push([[a.x, a.y, a.z], [b.x, b.y, b.z]]);
    }
  });
  return out;
}

/** A sketch being made or edited in the viewport.  `plane` is null while the plane is being chosen. */
export type SketchSession = { id: number; mode: "new" | "edit"; cell?: string; name: string; plane: PlaneSpec | null; doc: SketchDoc };

/** What the sketch asks the app to do once its feature is added (the "Finish and extrude" button). */
export type SketchAfter = { extrude: { distance: number } };

/** What is known of a face under the pointer: whether a sketch can lie on it, and the kind of surface it is. */
export type FaceCheck = { planar: boolean; type: string | null };

const isTyping = (event: KeyboardEvent) => Boolean((event.target as HTMLElement | null)?.closest?.("input, textarea, select, [contenteditable=true]"));

/** Sketch mode over the 3D viewport: first the choice of a plane (a datum plane or a planar face), then drawing on it. */
export function SketchMode({
  session,
  view,
  taken,
  features,
  notice,
  faceCheck,
  faceInk,
  sketchPlanes,
  workplanes = [],
  onPlane,
  onSubmit,
  onExit,
}: {
  session: SketchSession;
  view: SceneView;
  taken: readonly string[];
  /** The feature rows of the notebook: the other sketches are what Project offers. */
  features: readonly FeatureRow[];
  notice: string | null;
  /** Whether the face of a pick can carry a sketch (asks the kernel for its details when the pick has none). */
  faceCheck: (result: PickResult) => Promise<FaceCheck>;
  /** The colour a hovered face is lit in. */
  faceInk: string;
  /** The planes of the notebook's sketches: a new sketch can lie on one of them. */
  sketchPlanes: { name: string; plane: PlaneSpec }[];
  /** The notebook's workplanes (frames as the kernel reported them): a sketch on one writes `plane=<its variable>`. */
  workplanes?: { name: string; plane: PlaneSpec }[];
  onPlane: (plane: PlaneSpec) => void;
  onSubmit: (command: FeatureCommand, after?: SketchAfter) => Promise<void>;
  onExit: () => void;
}) {
  if (session.plane === null) return <PlaneChooser view={view} notice={notice} faceCheck={faceCheck} faceInk={faceInk} sketchPlanes={sketchPlanes} workplanes={workplanes} onPlane={onPlane} onExit={onExit} />;
  return <SketchEditorView key={session.id} session={session} plane={session.plane} view={view} taken={taken} features={features} onSubmit={onSubmit} onExit={onExit} />;
}

// -- plane choice -------------------------------------------------------------------------------------------------------------

const DATUM_COLOR: Record<Plane, string> = { XY: "var(--name)", XZ: "var(--pass)", YZ: "var(--fail)" };

function PlaneChooser({
  view,
  notice,
  faceCheck,
  faceInk,
  sketchPlanes,
  workplanes,
  onPlane,
  onExit,
}: {
  view: SceneView;
  notice: string | null;
  faceCheck: (result: PickResult) => Promise<FaceCheck>;
  faceInk: string;
  sketchPlanes: { name: string; plane: PlaneSpec }[];
  workplanes: { name: string; plane: PlaneSpec }[];
  onPlane: (plane: PlaneSpec) => void;
  onExit: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { viewer, size } = useViewer(view, host);
  const [hover, setHover] = useState<Plane | null>(null);
  const [faceNote, setFaceNote] = useState<string | null>(null);
  const half = useMemo(() => {
    const bounds = view.modelBoundsMm();
    if (!bounds) return 60;
    const extent = Math.max(...bounds.max.map((v, i) => v - bounds.min[i]), ...bounds.max.map(Math.abs), ...bounds.min.map(Math.abs));
    return Math.max(25, Math.round(extent * 0.6));
  }, [view]);
  const halfRef = useRef(half);
  halfRef.current = half;
  const callbacks = useRef({ onPlane, faceCheck, faceInk });
  callbacks.current = { onPlane, faceCheck, faceInk };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isTyping(event)) {
        event.preventDefault();
        onExit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit]);

  // The pointer over the model lights the face under it (a flat one in the selection ink, a curved one in the fail ink, with
  // the reason); over a datum plane where no face is, it lights that plane.  A click on a face is the app's pick; a click on
  // a plane (no face under it) is taken here.  The planes never swallow the pointer, so every face stays pickable.
  useEffect(() => {
    const element = view.engine.domElement;
    let overlays: THREE.Object3D[] = [];
    let shown: string | null = null;
    let frame = 0;
    let last: PointerEvent | null = null;
    let down: { x: number; y: number } | null = null;
    const drop = () => {
      for (const overlay of overlays) {
        overlay.parent?.remove(overlay);
        disposeObject(overlay);
      }
      overlays = [];
      shown = null;
      view.engine.invalidate();
    };
    const planeAt = (event: PointerEvent): Plane | null => {
      const rect = element.getBoundingClientRect();
      const ray = screenRay({ camera: view.engine.camera, width: rect.width, height: rect.height }, event.clientX - rect.left, event.clientY - rect.top);
      let best: { plane: Plane; t: number } | null = null;
      for (const plane of PLANES) {
        const hit = rayPlane(ray.origin, ray.dir, plane);
        if (hit && Math.abs(hit[0]) <= halfRef.current && Math.abs(hit[1]) <= halfRef.current && (!best || hit[2] < best.t)) best = { plane, t: hit[2] };
      }
      return best?.plane ?? null;
    };
    const run = () => {
      frame = 0;
      const event = last;
      if (!event) return;
      const face = view.pick(event);
      if (!face || !face.entityId) {
        drop();
        setFaceNote(null);
        setHover(planeAt(event));
        return;
      }
      setHover(null);
      const key = `${face.nodeId}::${face.entityId}`;
      if (key === shown) return;
      drop();
      shown = key;
      overlays = view.buildEntityOverlays(face.nodeId, face.entityId, callbacks.current.faceInk, 0.4);
      view.engine.invalidate();
      void callbacks.current.faceCheck(face).then((check) => {
        if (shown !== key) return;
        if (check.planar) {
          setFaceNote(null);
          return;
        }
        setFaceNote(`This face is ${check.type ? `a ${check.type.toLowerCase()}` : "curved"}: a sketch needs a flat face. Pick a flat face or a plane.`);
        for (const overlay of overlays) {
          overlay.parent?.remove(overlay);
          disposeObject(overlay);
        }
        overlays = view.buildEntityOverlays(face.nodeId, face.entityId!, "#d12b3c", 0.4);
        view.engine.invalidate();
      });
    };
    const move = (event: PointerEvent) => {
      if (event.buttons) return;
      last = event;
      if (!frame) frame = requestAnimationFrame(run);
    };
    const leave = () => {
      last = null;
      drop();
      setHover(null);
      setFaceNote(null);
    };
    const pointerDown = (event: PointerEvent) => {
      down = { x: event.clientX, y: event.clientY };
    };
    const pointerUp = (event: PointerEvent) => {
      const start = down;
      down = null;
      if (!start || event.button !== 0 || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4) return;
      if (view.pick(event)) return; // a face: the app's pick takes it
      const plane = planeAt(event);
      if (plane) callbacks.current.onPlane(plane);
    };
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerleave", leave);
    element.addEventListener("pointerdown", pointerDown);
    element.addEventListener("pointerup", pointerUp);
    return () => {
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
      element.removeEventListener("pointerdown", pointerDown);
      element.removeEventListener("pointerup", pointerUp);
      if (frame) cancelAnimationFrame(frame);
      drop();
    };
  }, [view]);

  return (
    <div ref={host} className="pointer-events-none absolute inset-0 z-10 overflow-hidden" data-testid="plane-chooser">
      <svg width={size.w} height={size.h} className="pointer-events-none absolute inset-0 block select-none overflow-hidden">
        {PLANES.map((plane) => {
          const corners: [number, number][] = [[-half, -half], [half, -half], [half, half], [-half, half]];
          const screen = corners.map(([u, v]) => planeToScreen(viewer, plane, u, v));
          if (screen.some((s) => !s)) return null;
          const label = planeToScreen(viewer, plane, half * 0.72, half * 0.88);
          const on = hover === plane;
          return (
            <g key={plane} data-plane={plane} style={{ cursor: "pointer" }} onClick={() => onPlane(plane)}>
              {/* the fill never takes the pointer (faces under it stay pickable); the edge and the label do */}
              <polygon points={screen.map((s) => s!.join(",")).join(" ")} fill={DATUM_COLOR[plane]} fillOpacity={on ? 0.3 : 0.1} stroke={DATUM_COLOR[plane]} strokeWidth={on ? 2.5 : 1.5} style={{ pointerEvents: "stroke" }} />
              {label && (
                <text x={label[0]} y={label[1]} textAnchor="middle" dominantBaseline="middle" fontSize={13} fontWeight={800} fill={DATUM_COLOR[plane]} stroke="var(--background)" strokeWidth={4} paintOrder="stroke" style={{ fontFamily: "var(--mono)", pointerEvents: "all" }}>
                  {plane}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <HintBanner
        testId="chooser-banner"
        icon={<Pencil className="size-3.5 shrink-0" />}
        title="Choose the sketch plane"
        hint="Click a face of the model, or a plane"
        notice={notice ?? faceNote}
        controls={
          <span className="flex flex-wrap items-center gap-1">
            {PLANES.map((plane) => (
              <Button key={plane} type="button" size="sm" variant="outline" className="h-6 px-2" data-testid={`chooser-plane-${plane}`} title={`Sketch on the ${plane} plane`} onClick={() => onPlane(plane)} onPointerEnter={() => setHover(plane)} onPointerLeave={() => setHover(null)}>
                {plane}
              </Button>
            ))}
            {workplanes.map((item) => (
              <Button key={`wp-${item.name}`} type="button" size="sm" variant="outline" className="h-6 border-amber-500/70 px-2 font-mono" data-testid={`chooser-workplane-${item.name}`} title={`Sketch on the workplane ${item.name}`} onClick={() => onPlane(item.plane)}>
                {item.name}
              </Button>
            ))}
            {sketchPlanes.map((item) => (
              <Button key={item.name} type="button" size="sm" variant="outline" className="h-6 px-2" data-testid={`chooser-sketch-${item.name}`} title={`Sketch on the plane of ${item.name}`} onClick={() => onPlane(item.plane)}>
                plane of {item.name}
              </Button>
            ))}
            <Button type="button" size="sm" variant="ghost" className="h-6 px-2" aria-label="Cancel the sketch" onClick={onExit}>
              <X /> esc
            </Button>
          </span>
        }
      />
    </div>
  );
}

// -- drawing --------------------------------------------------------------------------------------------------------------------

function SketchEditorView({
  session,
  plane,
  view,
  taken,
  features,
  onSubmit,
  onExit,
}: {
  session: SketchSession;
  plane: PlaneSpec;
  view: SceneView;
  taken: readonly string[];
  features: readonly FeatureRow[];
  onSubmit: (command: FeatureCommand, after?: SketchAfter) => Promise<void>;
  onExit: () => void;
}) {
  const editing = session.mode === "edit";
  const modelPoints = useMemo(() => view.modelVertices().map((p) => worldToPlane(plane, p)), [view, plane]);
  // The sketch being edited is the feature `session.name` (a new one has no feature yet): every other sketch can be projected.
  const sources = useMemo(() => projectSources(features, editing ? session.name : null), [features, editing, session.name]);
  // The model's edges in the sketch plane (the boundary of the face the sketch is on): drawn faintly and snapped to.
  const faceEdges = useMemo(() => planeSegments(modelEdges(view), plane), [view, plane]);
  const editor = useSketchEditor(session.doc, modelPoints, sources, faceEdges);
  const editorRef = useRef(editor);
  editorRef.current = editor;
  const spaceRef = useRef(false);
  const [name, setName] = useState(session.name);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  // A new sketch whose cell failed exists already: the next finish edits it instead of adding a second one.
  const [created, setCreated] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const measure = () => setWide(el.clientWidth >= 1000);
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, []);
  const confirmingRef = useRef(confirming);
  confirmingRef.current = confirming;

  // The camera: turn to look straight at the plane on entering; the trackball is parked while sketching.
  const turn = useRef<(fit?: boolean) => void>(() => undefined);
  turn.current = (fit = false) => {
    const rig = view.rig;
    const pose0 = rig.pose;
    const frame = frameOf(plane);
    const extents = editorRef.current.extents();
    let centre: [number, number, number];
    const bounds = view.modelBoundsMm();
    const modelExtent = bounds ? Math.max(...bounds.max.map((v, i) => v - bounds.min[i])) : 60;
    // Far enough to see the whole model from the plane's normal: near the distance the person had, within a sane range.
    const fitModel = (factor: number) => fitDistanceMm(modelExtent * factor, view.engine.camera.fov, view.engine.camera.aspect);
    let distance = Math.min(Math.max(rig.distance() * 1000 * 1.3, fitModel(1.3)), fitModel(2.2));
    if (extents) {
      const mid: [number, number] = [(extents.min[0] + extents.max[0]) / 2, (extents.min[1] + extents.max[1]) / 2];
      centre = planeToWorld(plane, mid[0], mid[1]);
      if (fit || editing) distance = Math.max(fitDistanceMm(Math.max(extents.max[0] - extents.min[0], extents.max[1] - extents.min[1], 20), view.engine.camera.fov, view.engine.camera.aspect), 20);
    } else if (session.mode === "new" && !fit) {
      const target = [pose0.target.x * 1000, pose0.target.y * 1000, pose0.target.z * 1000] as [number, number, number];
      centre = typeof plane === "string" ? projectOnPlane(plane, target) : frame.origin;
    } else centre = frame.origin;
    const pose = viewPose(plane, centre, distance);
    void rig.animateTo({
      position: new THREE.Vector3(pose.position[0] / 1000, pose.position[1] / 1000, pose.position[2] / 1000),
      target: new THREE.Vector3(pose.target[0] / 1000, pose.target[1] / 1000, pose.target[2] / 1000),
      up: new THREE.Vector3(...pose.up),
    });
  };
  useEffect(() => {
    const before = view.rig.pose;
    view.rig.setManual(true);
    turn.current();
    return () => {
      // Leaving: the trackball is back, and the view the person had returns (the sketch's turn must not strand them).
      view.rig.setManual(false);
      void view.rig.animateTo(before, 350);
    };
  }, [view]);

  // Keys: the sketch's own, plus N (normal to), F (fit) and space (pan).
  const leave = () => {
    if (editorRef.current.edits === 0) onExit();
    else setConfirming(true);
  };
  const leaveRef = useRef(leave);
  leaveRef.current = leave;
  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (isTyping(event)) return;
      const k = event.key.toLowerCase();
      if (event.key === " ") {
        spaceRef.current = true;
        event.preventDefault();
        return;
      }
      if (!event.metaKey && !event.ctrlKey && !event.altKey && (k === "n" || k === "f")) {
        turn.current(k === "f");
        event.preventDefault();
        return;
      }
      if (k === "escape") {
        if (confirmingRef.current) {
          setConfirming(false);
          event.preventDefault();
          return;
        }
      }
      const outcome = editorRef.current.key(event);
      if (outcome === "ignored") return;
      event.preventDefault();
      event.stopPropagation();
      if (outcome === "leave") leaveRef.current();
    };
    const up = (event: KeyboardEvent) => {
      if (event.key === " ") spaceRef.current = false;
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up);
    };
  }, []);
  const nameError = editing || created ? null : validateName(name, taken);
  const problem = (() => {
    if (nameError) return nameError;
    if (editor.error) return editor.error;
    if (!editor.fresh) return "solving the sketch…";
    if (editor.doc.output === "wire") {
      if (!editor.wire) {
        const why = editor.result?.unusable?.[0];
        return why ? `no profile for the wire: ${why}` : "draw a chain of lines, arcs or splines (or a closed loop): the wire needs a profile";
      }
    } else if (editor.loops.length === 0) {
      const why = editor.result?.unusable?.[0];
      return why ? `no closed profile: ${why}` : "close a loop of lines or draw a circle: the face needs a profile";
    }
    const status = editor.result?.status;
    if (status === "conflicting" || status === "failed") return "the sketch has a conflict: fix the constraints marked in red";
    return null;
  })();

  const finish = async (thenExtrude = false) => {
    setTouched(true);
    if (problem || busy) return;
    setBusy(true);
    setServerError(null);
    const values = { sketch: docToJson(editor.doc) };
    const target = editing && session.cell ? session.cell : created;
    const command: FeatureCommand = target ? { op: "edit", cell: target, values } : { op: "add", spec: "sketch", ...(name.trim() ? { name: name.trim() } : {}), values };
    try {
      await onSubmit(command, thenExtrude ? { extrude: { distance: defaultExtrudeDistance(sketchShape(editor.doc, editor.result)) } } : undefined);
    } catch (error) {
      if (error instanceof CellFailure && !editing) setCreated(error.cell);
      setServerError(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const shown = serverError ?? (touched ? problem : null);
  const coords = editor.cursor ? `x ${editor.cursor.x.toFixed(2)}  y ${editor.cursor.y.toFixed(2)} mm` : "";

  return (
    <div ref={root} className="pointer-events-none absolute inset-0 z-10 overflow-hidden" data-testid="sketch-mode">
      <div className="pointer-events-auto absolute inset-0">
        <SketchOverlay view={view} plane={plane} editor={editor} spaceRef={spaceRef} />
      </div>
      <SketchToolbar editor={editor} onFit={() => turn.current(true)} onNormal={() => turn.current(false)} />
      {editor.projectOpen && <SketchProject editor={editor} />}
      <SketchDrawer editor={editor} plane={planeLabel(plane)} wide={wide} />
      {/* The bar and its notes take the pointer; the space between them (beside the hint) is the canvas. */}
      <div className="pointer-events-none absolute left-1/2 top-2 z-30 flex -translate-x-1/2 flex-col items-stretch gap-1">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2 border-2 border-primary bg-popover px-2 py-1 shadow-[4px_4px_0_var(--shadow-hard)]">
          <Pencil className="size-3.5 shrink-0" />
          <Input
            aria-label="Sketch name"
            data-testid="sketch-name"
            className="h-7 w-44"
            value={editing ? (session.name || "") : name}
            disabled={editing}
            placeholder={suggestName("sketch", taken)}
            aria-invalid={touched && nameError !== null}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation();
              if (event.key === "Enter") void finish();
            }}
          />
          <span className="whitespace-nowrap text-[10px] uppercase tracking-[0.08em] text-muted-foreground">on {planeLabel(plane)}</span>
          <StatusBadge editor={editor} compact />
          <OutputChoice editor={editor} />
          <Button type="button" size="sm" variant={editing ? "default" : "outline"} className="h-7 gap-1 px-2" data-testid="sketch-finish" aria-label="Finish the sketch" title="Finish: add the sketch to the notebook" disabled={busy} onClick={() => void finish()}>
            <Check /> {busy ? "working…" : "finish"}
          </Button>
          {!editing && editor.doc.output !== "wire" && (
            <Button type="button" size="sm" className="h-7 gap-1 px-2" data-testid="sketch-finish-extrude" aria-label="Finish the sketch and extrude it" title="Finish, then extrude the sketch (the most common next step)" disabled={busy} onClick={() => void finish(true)}>
              <Rocket /> finish and extrude
            </Button>
          )}
          <Button type="button" size="sm" variant="outline" className="h-7 px-2" data-testid="sketch-cancel" aria-label="Cancel the sketch" title="Cancel (Esc twice)" onClick={leave}>
            <X />
          </Button>
        </div>
        {shown && (
          <p role="alert" data-testid="sketch-error" className="pointer-events-auto border-2 border-fail bg-popover px-2 py-1 text-[11px] text-fail">
            {shown}
          </p>
        )}
        {editor.editBusy && <p className="self-center border border-border bg-popover px-2 py-0.5 text-[10px] text-muted-foreground">asking the SDK…</p>}
        {editor.editNote && (
          <p
            role={editor.editNote.tone === "fail" ? "alert" : "status"}
            data-testid="sketch-edit-note"
            data-tone={editor.editNote.tone}
            className={`pointer-events-auto max-w-[460px] self-center border-2 bg-popover px-2 py-1 text-[11px] ${editor.editNote.tone === "fail" ? "border-fail text-fail" : "border-pass text-foreground"}`}
          >
            {editor.editNote.text}
          </p>
        )}
        <p className="pointer-events-none max-w-[420px] self-center border border-border bg-popover/90 px-2 py-1 text-center text-[10px] leading-tight text-muted-foreground">
          {editor.hint} <span className="opacity-80">Orbit: right/middle drag or Alt+drag; pan: Shift+middle or space+drag; zoom: wheel.</span>
          {coords && <span className="ml-2 text-foreground">{coords}</span>}
        </p>
        {confirming && (
          <div className="pointer-events-auto flex items-center gap-2 border-2 border-focus bg-popover px-2 py-1 text-[11px]" data-testid="sketch-confirm">
            <span className="flex-1">Discard the unsaved sketch edits?</span>
            <Button type="button" size="sm" variant="destructive" className="h-6 px-2" onClick={onExit}>
              discard
            </Button>
            <Button type="button" size="sm" variant="outline" className="h-6 px-2" onClick={() => setConfirming(false)}>
              keep sketching
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

/** Face or wire: what the sketch becomes, and for a wire which profile (a closed loop or an open chain, as the SDK lists them;
 * a click inside a loop picks it too). */
function OutputChoice({ editor }: { editor: ReturnType<typeof useSketchEditor> }) {
  const wire = editor.doc.output === "wire";
  const tab = "h-7 px-2 text-[10px] font-bold uppercase tracking-[0.08em] aria-pressed:bg-primary aria-pressed:text-primary-foreground hover:bg-accent aria-pressed:hover:bg-primary";
  return (
    <span className="flex items-center gap-1" data-testid="sketch-output">
      <span className="flex border-2 border-input" role="group" aria-label="What the sketch makes">
        <button type="button" className={tab} aria-pressed={!wire} data-output="face" title="Face (closed profile): what extrude, revolve and cut take" onClick={() => editor.setOutput("face")}>
          face
        </button>
        <button type="button" className={tab} aria-pressed={wire} data-output="wire" title="Wire (path / profile curve): an open chain or a closed loop, for a sweep path or a loft section" onClick={() => editor.setOutput("wire")}>
          wire
        </button>
      </span>
      {wire && editor.wires.length > 0 && (
        <select
          aria-label="Profile of the wire"
          data-testid="sketch-wire-profile"
          className="h-7 max-w-44 border-2 border-input bg-background px-1 text-[11px]"
          value={editor.wire?.key ?? ""}
          onChange={(event) => editor.setWireKey(event.target.value)}
          onKeyDown={(event) => event.stopPropagation()}
        >
          {editor.wires.map((w) => (
            <option key={w.key} value={w.key}>
              {w.index}: {w.closed ? "loop" : "chain"} {w.entities.join(", ")}
            </option>
          ))}
        </select>
      )}
    </span>
  );
}
