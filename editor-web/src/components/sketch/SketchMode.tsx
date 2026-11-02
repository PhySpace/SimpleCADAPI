import { Check, Pencil, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { SketchDrawer, StatusBadge } from "@/components/sketch/SketchDrawer";
import { SketchOverlay, useViewer } from "@/components/sketch/SketchOverlay";
import { SketchToolbar } from "@/components/sketch/SketchToolbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { FeatureCommand } from "@/lib/features";
import { suggestName, validateName } from "@/lib/features";
import { docToJson, type SketchDoc } from "@/lib/sketch";
import { PLANES, frameOf, planeLabel, projectOnPlane, viewPose, worldToPlane, planeToWorld, type Plane, type PlaneSpec } from "@/lib/sketch-plane";
import { fitDistanceMm, planeToScreen } from "@/lib/sketch-view";
import { useSketchEditor } from "@/lib/useSketchEditor";
import type { SceneView } from "@/scene/scene-view";

/** A sketch being made or edited in the viewport.  `plane` is null while the plane is being chosen. */
export type SketchSession = { id: number; mode: "new" | "edit"; cell?: string; name: string; plane: PlaneSpec | null; doc: SketchDoc };

const isTyping = (event: KeyboardEvent) => Boolean((event.target as HTMLElement | null)?.closest?.("input, textarea, select, [contenteditable=true]"));

/** Sketch mode over the 3D viewport: first the choice of a plane (a datum plane or a planar face), then drawing on it. */
export function SketchMode({
  session,
  view,
  taken,
  notice,
  onPlane,
  onSubmit,
  onExit,
}: {
  session: SketchSession;
  view: SceneView;
  taken: readonly string[];
  notice: string | null;
  onPlane: (plane: PlaneSpec) => void;
  onSubmit: (command: FeatureCommand) => Promise<void>;
  onExit: () => void;
}) {
  if (session.plane === null) return <PlaneChooser view={view} notice={notice} onPlane={onPlane} onExit={onExit} />;
  return <SketchEditorView key={session.id} session={session} plane={session.plane} view={view} taken={taken} onSubmit={onSubmit} onExit={onExit} />;
}

// -- plane choice -------------------------------------------------------------------------------------------------------------

const DATUM_COLOR: Record<Plane, string> = { XY: "var(--name)", XZ: "var(--pass)", YZ: "var(--fail)" };

function PlaneChooser({ view, notice, onPlane, onExit }: { view: SceneView; notice: string | null; onPlane: (plane: PlaneSpec) => void; onExit: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const { viewer, size } = useViewer(view, host);
  const [hover, setHover] = useState<Plane | null>(null);
  const half = useMemo(() => {
    const bounds = view.modelBoundsMm();
    if (!bounds) return 60;
    const extent = Math.max(...bounds.max.map((v, i) => v - bounds.min[i]), ...bounds.max.map(Math.abs), ...bounds.min.map(Math.abs));
    return Math.max(25, Math.round(extent * 0.6));
  }, [view]);

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

  return (
    <div ref={host} className="pointer-events-none absolute inset-0 z-10" data-testid="plane-chooser">
      <svg width={size.w} height={size.h} className="pointer-events-none absolute inset-0 block select-none">
        {PLANES.map((plane) => {
          const corners: [number, number][] = [[-half, -half], [half, -half], [half, half], [-half, half]];
          const screen = corners.map(([u, v]) => planeToScreen(viewer, plane, u, v));
          if (screen.some((s) => !s)) return null;
          const label = planeToScreen(viewer, plane, half * 0.72, half * 0.88);
          const on = hover === plane;
          return (
            <g key={plane} data-plane={plane} style={{ pointerEvents: "all", cursor: "pointer" }} onPointerEnter={() => setHover(plane)} onPointerLeave={() => setHover(null)} onClick={() => onPlane(plane)}>
              <polygon points={screen.map((s) => s!.join(",")).join(" ")} fill={DATUM_COLOR[plane]} fillOpacity={on ? 0.34 : 0.14} stroke={DATUM_COLOR[plane]} strokeWidth={on ? 2.5 : 1.5} />
              {label && (
                <text x={label[0]} y={label[1]} textAnchor="middle" dominantBaseline="middle" fontSize={13} fontWeight={800} fill={DATUM_COLOR[plane]} stroke="var(--background)" strokeWidth={4} paintOrder="stroke" style={{ fontFamily: "var(--mono)" }}>
                  {plane}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="pointer-events-auto absolute left-1/2 top-3 z-30 flex max-w-[96%] -translate-x-1/2 items-center gap-3 border-2 border-primary bg-popover px-3 py-1.5 shadow-[4px_4px_0_var(--shadow-hard)]">
        <Pencil className="size-3.5 shrink-0" />
        <span className="flex flex-col leading-tight">
          <span className="whitespace-nowrap text-[12px] font-semibold">Choose the sketch plane</span>
          <span className="text-[11px] text-muted-foreground">click XY, XZ or YZ, or a planar face of the model</span>
        </span>
        <Button type="button" size="sm" variant="ghost" className="h-6 px-2" aria-label="Cancel the sketch" onClick={onExit}>
          <X /> esc
        </Button>
      </div>
      {notice && (
        <div role="alert" className="pointer-events-none absolute left-1/2 top-14 z-30 -translate-x-1/2 border-2 border-fail bg-popover px-3 py-1 text-[11px] text-fail">
          {notice}
        </div>
      )}
    </div>
  );
}

// -- drawing --------------------------------------------------------------------------------------------------------------------

function SketchEditorView({
  session,
  plane,
  view,
  taken,
  onSubmit,
  onExit,
}: {
  session: SketchSession;
  plane: PlaneSpec;
  view: SceneView;
  taken: readonly string[];
  onSubmit: (command: FeatureCommand) => Promise<void>;
  onExit: () => void;
}) {
  const editing = session.mode === "edit";
  const modelPoints = useMemo(() => view.modelVertices().map((p) => worldToPlane(plane, p)), [view, plane]);
  const editor = useSketchEditor(session.doc, modelPoints);
  const editorRef = useRef(editor);
  editorRef.current = editor;
  const spaceRef = useRef(false);
  const [name, setName] = useState(session.name);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
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
  const nameError = editing ? null : validateName(name, taken);
  const problem = (() => {
    if (nameError) return nameError;
    if (editor.loops.length === 0) return "close a loop of lines or draw a circle: the face needs a profile";
    const status = editor.result?.status;
    if (editor.error) return editor.error;
    if (status === "conflicting" || status === "failed") return "the sketch has a conflict: fix the constraints marked in red";
    if (editor.outer && editor.outer.index === null) return "the profile is still being matched: try again in a moment";
    return null;
  })();

  const finish = async () => {
    setTouched(true);
    if (problem || busy) return;
    setBusy(true);
    setServerError(null);
    const values = { sketch: docToJson(editor.doc) };
    const command: FeatureCommand = editing && session.cell ? { op: "edit", cell: session.cell, values } : { op: "add", spec: "sketch", ...(name.trim() ? { name: name.trim() } : {}), values };
    try {
      await onSubmit(command);
    } catch (error) {
      setServerError(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const shown = serverError ?? (touched ? problem : null);
  const coords = editor.cursor ? `x ${editor.cursor.x.toFixed(2)}  y ${editor.cursor.y.toFixed(2)} mm` : "";

  return (
    <div ref={root} className="pointer-events-none absolute inset-0 z-10" data-testid="sketch-mode">
      <div className="pointer-events-auto absolute inset-0">
        <SketchOverlay view={view} plane={plane} editor={editor} spaceRef={spaceRef} />
      </div>
      <SketchToolbar editor={editor} onFit={() => turn.current(true)} onNormal={() => turn.current(false)} />
      <SketchDrawer editor={editor} plane={planeLabel(plane)} wide={wide} />
      <div className="pointer-events-auto absolute left-1/2 top-2 z-30 flex -translate-x-1/2 flex-col items-stretch gap-1">
        <div className="flex items-center gap-2 border-2 border-primary bg-popover px-2 py-1 shadow-[4px_4px_0_var(--shadow-hard)]">
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
          <Button type="button" size="sm" className="h-7 gap-1 px-2" data-testid="sketch-finish" aria-label="Finish the sketch" title="Finish: add the sketch to the notebook" disabled={busy} onClick={() => void finish()}>
            <Check /> {busy ? "working…" : "finish"}
          </Button>
          <Button type="button" size="sm" variant="outline" className="h-7 px-2" data-testid="sketch-cancel" aria-label="Cancel the sketch" title="Cancel (Esc twice)" onClick={leave}>
            <X />
          </Button>
        </div>
        {shown && (
          <p role="alert" data-testid="sketch-error" className="border-2 border-fail bg-popover px-2 py-1 text-[11px] text-fail">
            {shown}
          </p>
        )}
        {editor.editBusy && <p className="self-center border border-border bg-popover px-2 py-0.5 text-[10px] text-muted-foreground">asking the SDK…</p>}
        {editor.editNote && (
          <p
            role={editor.editNote.tone === "fail" ? "alert" : "status"}
            data-testid="sketch-edit-note"
            data-tone={editor.editNote.tone}
            className={`max-w-[460px] self-center border-2 bg-popover px-2 py-1 text-[11px] ${editor.editNote.tone === "fail" ? "border-fail text-fail" : "border-pass text-foreground"}`}
          >
            {editor.editNote.text}
          </p>
        )}
        <p className="pointer-events-none max-w-[420px] self-center border border-border bg-popover/90 px-2 py-1 text-center text-[10px] leading-tight text-muted-foreground">
          {editor.hint} <span className="opacity-80">Orbit: right/middle drag or Alt+drag; pan: Shift+middle or space+drag; zoom: wheel.</span>
          {coords && <span className="ml-2 text-foreground">{coords}</span>}
        </p>
        {confirming && (
          <div className="flex items-center gap-2 border-2 border-focus bg-popover px-2 py-1 text-[11px]" data-testid="sketch-confirm">
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
