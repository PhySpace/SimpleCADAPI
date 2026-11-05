import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { Spline, Slash, Waves } from "lucide-react";

import {
  SNAP_PX,
  addSegment,
  dropLast,
  gridStep,
  nextId,
  onGrid,
  pathEnd,
  pickSnap,
  pointAt,
  pointFor,
  rayOnPlane,
  segmentPoints,
  type CurveDoc,
  type CurveKind,
  type DrawPlane,
  type SnapCandidate,
} from "@/lib/curve3d";
import type { Vec3 } from "@/lib/sketch-plane";
import { rayThrough } from "@/scene/camera-projection";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import { pointSprites } from "@/scene/point-sprites";
import type { SceneView } from "@/scene/scene-view";
import { t } from "@/i18n";

const EMPTY: CurveDoc = { points: [], curves: [] };
const PATH = "#2563eb";
const DRAFT = "#f59e0b";
const TOOLS: { kind: CurveKind; key: string; label: string; icon: typeof Slash }[] = [
  { kind: "line", key: "l", label: "line", icon: Slash },
  { kind: "arc", key: "a", label: "arc", icon: Waves },
  { kind: "spline", key: "s", label: "spline", icon: Spline },
];

const world = (p: Vec3) => new THREE.Vector3(p[0] / 1000, p[1] / 1000, p[2] / 1000);

/** The model's vertices and edge midpoints, in world mm, as snap targets (screen positions filled per pointer move). */
function modelTargets(view: SceneView): Omit<SnapCandidate, "screen">[] {
  const out: Omit<SnapCandidate, "screen">[] = [];
  const position = new THREE.Vector3();
  view.engine.modelRoot.updateMatrixWorld(true);
  view.engine.modelRoot.traverse((object) => {
    if (!object.visible) return;
    if (object instanceof THREE.Points && Array.isArray(object.userData.vertexEntityIds)) {
      const ids = object.userData.vertexEntityIds as string[];
      const positions = object.geometry.getAttribute("position");
      for (let i = 0; i < positions.count && i < ids.length; i++) {
        position.fromBufferAttribute(positions, i).applyMatrix4(object.matrixWorld);
        out.push({ kind: "vertex", at: [position.x * 1000, position.y * 1000, position.z * 1000], entityId: ids[i], label: "vertex", priority: 0 });
      }
    } else if (object instanceof THREE.LineSegments && typeof object.userData.nodeId === "string") {
      const node = view.engine.nodes.find((item) => item.node_id === object.userData.nodeId);
      const sidecar = view.sidecarFor(node);
      const positions = object.geometry.getAttribute("position");
      const index = object.geometry.index;
      if (!sidecar || !positions) return;
      for (const group of sidecar.edge_groups) {
        // the midpoint along the edge's polyline
        const segment = (k: number): [THREE.Vector3, THREE.Vector3] => {
          const at = (j: number) => new THREE.Vector3().fromBufferAttribute(positions, index ? index.getX(j) : j).applyMatrix4(object.matrixWorld);
          return [at(group.first_index + k), at(group.first_index + k + 1)];
        };
        const lengths: number[] = [];
        for (let k = 0; k + 1 < group.index_count; k += 2) {
          const [a, b] = segment(k);
          lengths.push(a.distanceTo(b));
        }
        const total = lengths.reduce((s, l) => s + l, 0);
        if (!(total > 0)) continue;
        let left = total / 2;
        for (let s = 0; s < lengths.length; s++) {
          if (left <= lengths[s]) {
            const [a, b] = segment(s * 2);
            const p = a.lerp(b, lengths[s] > 0 ? left / lengths[s] : 0);
            out.push({ kind: "midpoint", at: [p.x * 1000, p.y * 1000, p.z * 1000], label: "midpoint", priority: 1 });
            break;
          }
          left -= lengths[s];
        }
      }
    }
  });
  return out;
}

function line(points: Vec3[], color: string, dashed = false): THREE.Line {
  const geometry = new THREE.BufferGeometry().setFromPoints(points.map(world));
  const material = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.002, gapSize: 0.0015, depthTest: false, transparent: true })
    : new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
  const object = new THREE.Line(geometry, material);
  if (dashed) object.computeLineDistances();
  object.renderOrder = 30;
  object.layers.enable(OVERLAY_LAYER);
  return object;
}

/** Draws a 3D curve in the viewport: lines, arcs and splines, one after another, through points on the drawing plane (a
 * datum plane or a workplane, Tab to change it between points), snapped to the model's vertices and edge midpoints, the
 * workplanes' origins, the path's own points and the plane's grid.  A point drawn on a workplane is kept on it (u, v),
 * one snapped to a vertex is kept at it (its reference), so the path follows both.  Enter makes the `curve` feature. */
export function CurveDrawer({
  view,
  planes,
  others = [],
  plane: initialPlane,
  busy,
  error,
  onCommit,
  onCancel,
}: {
  view: SceneView;
  planes: DrawPlane[];
  /** The points of the notebook's other 3D curves (snap targets: a new path can start where one ends). */
  others?: { at: Vec3; label: string }[];
  plane: string;
  busy: boolean;
  error: string | null;
  onCommit: (doc: CurveDoc, name: string) => void;
  onCancel: () => void;
}) {
  const [doc, setDoc] = useState<CurveDoc>(EMPTY);
  const [tool, setTool] = useState<CurveKind>("line");
  const [planeName, setPlaneName] = useState(initialPlane);
  const [pending, setPending] = useState<string[]>([]); // an arc's middle point, a spline's points so far
  const [hover, setHover] = useState<{ at: Vec3; snap: SnapCandidate | null; screen: [number, number] } | null>(null);
  const [name, setName] = useState("path");
  const plane = planes.find((p) => p.name === planeName) ?? planes[0];
  const state = useRef({ doc, tool, plane, pending });
  state.current = { doc, tool, plane, pending };

  // -- what the pointer is over -------------------------------------------------------------------------------------
  const targets = useMemo(() => modelTargets(view), [view]);
  const toScreen = useCallback(
    (p: Vec3): [number, number] | null => {
      const rect = view.engine.domElement.getBoundingClientRect();
      const v = world(p).project(view.engine.camera);
      if (v.z > 1 || v.z < -1) return null;
      return [((v.x + 1) / 2) * rect.width, ((1 - v.y) / 2) * rect.height];
    },
    [view],
  );
  const locate = useCallback(
    (clientX: number, clientY: number): { at: Vec3; snap: SnapCandidate | null; screen: [number, number] } | null => {
      const { engine } = view;
      const rect = engine.domElement.getBoundingClientRect();
      const pointer: [number, number] = [clientX - rect.left, clientY - rect.top];
      const { doc: current, plane: drawOn } = state.current;
      const candidates: SnapCandidate[] = [];
      const offer = (c: Omit<SnapCandidate, "screen">) => {
        const screen = toScreen(c.at);
        if (screen) candidates.push({ ...c, screen });
      };
      targets.forEach(offer);
      for (const point of current.points) offer({ kind: "point", at: point.at, pointId: point.id, label: point.id, priority: 0 });
      for (const p of planes) if (p.workplane) offer({ kind: "origin", at: p.origin, label: `${p.name} origin`, priority: 1, workplane: p.name });
      for (const other of others) offer({ kind: "point", at: other.at, label: other.label, priority: 1 });
      const raycaster = new THREE.Raycaster();
      rayThrough(raycaster, new THREE.Vector2((pointer[0] / rect.width) * 2 - 1, -(pointer[1] / rect.height) * 2 + 1), engine.camera);
      const o = raycaster.ray.origin;
      const d = raycaster.ray.direction;
      const hit = rayOnPlane([o.x * 1000, o.y * 1000, o.z * 1000], [d.x, d.y, d.z], drawOn);
      if (hit) {
        // a grid of about 24 px on screen where the pointer is
        const mmPerPx = (engine.camera.position.distanceTo(world(hit)) * 1000 * 2 * Math.tan(THREE.MathUtils.degToRad(engine.camera.fov) / 2)) / rect.height;
        const step = gridStep(mmPerPx * 24);
        offer({ kind: "grid", at: onGrid(drawOn, hit, step), label: `grid ${step} mm`, priority: 3 });
      }
      const snap = pickSnap(candidates, pointer, SNAP_PX);
      const at = snap ? snap.at : hit;
      return at ? { at, snap, screen: snap ? snap.screen : pointer } : null;
    },
    [view, targets, planes, others, toScreen],
  );

  // -- clicks make points; Enter, Backspace, Esc, Tab and the tool keys ---------------------------------------------
  const place = useCallback((spot: { at: Vec3; snap: SnapCandidate | null }) => {
    const { doc: current, tool: kind, plane: drawOn, pending: waiting } = state.current;
    const start = pathEnd(current) ?? current.points[0]?.id ?? null; // where the next segment starts
    const made = pointFor(current, drawOn, spot.at, spot.snap);
    let next = made.doc;
    if (start === null) {
      setDoc(next); // the path's first point
      return;
    }
    if (kind === "line") {
      if (made.id === start) return;
      next = addSegment(next, "line", [start, made.id]);
      setPending([]);
    } else if (kind === "arc") {
      if (waiting.length === 0) {
        setDoc(next);
        setPending([made.id]); // the point the arc passes through
        return;
      }
      next = addSegment(next, "arc", [start, waiting[0], made.id]);
      setPending([]);
    } else {
      setDoc(next);
      setPending([...waiting, made.id]);
      return;
    }
    setDoc(next);
  }, []);

  /** The spline drawn so far becomes a segment (a spline ends when another tool or Enter takes over). */
  const settleSpline = useCallback((current: CurveDoc, waiting: string[]): CurveDoc => {
    if (state.current.tool !== "spline" || waiting.length === 0) return current;
    const start = pathEnd(current) ?? current.points[0]?.id;
    return start ? addSegment(current, "spline", [start, ...waiting]) : current;
  }, []);

  const finish = useCallback(() => {
    const settled = settleSpline(state.current.doc, state.current.pending);
    if (settled.curves.length === 0) return;
    const used = new Set(settled.curves.flatMap((c) => c.points));
    onCommit({ ...settled, points: settled.points.filter((p) => used.has(p.id)) }, name);
  }, [onCommit, name, settleSpline]);

  const switchTool = useCallback(
    (kind: CurveKind) => {
      const settled = settleSpline(state.current.doc, state.current.pending);
      const used = new Set([...settled.curves.flatMap((c) => c.points), settled.points[0]?.id]);
      setDoc({ ...settled, points: settled.points.filter((p) => used.has(p.id)) });
      setPending([]);
      setTool(kind);
    },
    [settleSpline],
  );

  useEffect(() => {
    const element = view.engine.domElement;
    let down: { x: number; y: number } | null = null;
    const onMove = (event: PointerEvent) => {
      if (event.buttons !== 0) return;
      setHover(locate(event.clientX, event.clientY));
    };
    const onDown = (event: PointerEvent) => {
      down = event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
    };
    const onUp = (event: PointerEvent) => {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) return; // a drag turns the view
      down = null;
      const spot = locate(event.clientX, event.clientY);
      if (spot) place(spot);
    };
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable=true], .cm-editor")) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      const tool = TOOLS.find((t) => t.key === key);
      if (tool) {
        event.preventDefault();
        switchTool(tool.kind);
      } else if (event.key === "Enter") {
        event.preventDefault();
        finish();
      } else if (event.key === "Tab") {
        event.preventDefault();
        setPlaneName((current) => {
          const at = planes.findIndex((p) => p.name === current);
          return planes[(at + (event.shiftKey ? planes.length - 1 : 1)) % planes.length].name;
        });
      } else if (event.key === "Backspace") {
        event.preventDefault();
        const { doc: current, pending: waiting } = state.current;
        if (waiting.length) {
          const kept = waiting.slice(0, -1);
          const used = new Set([...current.curves.flatMap((c) => c.points), current.points[0]?.id, ...kept]);
          setPending(kept);
          setDoc({ ...current, points: current.points.filter((p) => used.has(p.id)) });
        } else if (current.curves.length) setDoc(dropLast(current));
        else setDoc(EMPTY);
      } else if (event.key === "Escape") {
        event.preventDefault();
        if (state.current.pending.length) setPending([]);
        else onCancel();
      }
    };
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey);
    element.style.cursor = "crosshair";
    return () => {
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKey);
      element.style.cursor = "";
    };
  }, [view, locate, place, finish, switchTool, planes, onCancel]);

  // -- what is drawn: the path, the segment being drawn, the points, the plane's grid --------------------------------
  const group = useMemo(() => new THREE.Group(), []);
  useEffect(() => {
    view.engine.threeScene.add(group);
    return () => {
      group.removeFromParent();
      view.engine.invalidate();
    };
  }, [view, group]);
  useEffect(() => {
    for (const child of [...group.children]) {
      child.removeFromParent();
      child.traverse((o) => {
        const mesh = o as THREE.Mesh;
        mesh.geometry?.dispose();
        (mesh.material as THREE.Material | undefined)?.dispose?.();
      });
    }
    const at = (id: string) => pointAt(doc, id)!;
    for (const curve of doc.curves) group.add(line(segmentPoints(curve.kind, curve.points.map(at)), PATH));
    const start = pathEnd(doc) ?? doc.points[0]?.id;
    if (start && hover) {
      const draft = [at(start), ...pending.map(at), hover.at];
      group.add(line(segmentPoints(tool === "arc" && draft.length === 3 ? "arc" : tool === "spline" ? "spline" : "line", draft), DRAFT, true));
    }
    if (doc.points.length) {
      const positions = new THREE.BufferAttribute(new Float32Array(doc.points.flatMap((p) => world(p.at).toArray())), 3);
      const marks = pointSprites(positions, { color: PATH, size: 7, depthTest: false });
      marks.renderOrder = 31;
      marks.layers.enable(OVERLAY_LAYER);
      group.add(marks);
    }
    if (plane) {
      // the drawing plane: a grid around its origin, about the model's size
      const bounds = view.modelBoundsMm();
      const extent = bounds ? Math.max(...bounds.max.map((v, i) => v - bounds.min[i]), 20) : 100;
      const size = extent * 1.6;
      const grid = new THREE.GridHelper(size / 1000, 16, 0x2563eb, 0x64748b);
      const material = grid.material as THREE.Material;
      material.transparent = true;
      material.opacity = 0.25;
      material.depthWrite = false;
      const basis = new THREE.Matrix4().makeBasis(new THREE.Vector3(...plane.x_axis), new THREE.Vector3(...plane.normal), new THREE.Vector3(...plane.y_axis).negate());
      grid.quaternion.setFromRotationMatrix(basis);
      grid.position.copy(world(plane.origin));
      grid.layers.enable(OVERLAY_LAYER);
      group.add(grid);
    }
    view.engine.invalidate();
  }, [doc, pending, hover, tool, plane, group, view]);

  const hint =
    doc.points.length === 0
      ? t("Click the first point.")
      : tool === "arc"
        ? pending.length === 0
          ? t("Click a point the arc passes through.")
          : t("Click where the arc ends.")
        : tool === "spline"
          ? t("Click the points the spline passes through; another tool or Enter ends it.")
          : t("Click where the line ends.");

  return (
    <>
      {hover?.snap && (
        <div className="pointer-events-none absolute z-20" style={{ left: hover.screen[0] - 9, top: hover.screen[1] - 9 }}>
          <div className="size-[18px] rounded-full border-2 border-amber-500" />
          <span className="absolute left-5 top-0 whitespace-nowrap bg-popover/90 px-1 font-mono text-[10px] text-amber-600">{hover.snap.label}</span>
        </div>
      )}
      <div className="pointer-events-auto absolute left-3 top-3 z-30 flex max-w-[min(460px,90%)] flex-col gap-2 border-2 border-primary bg-popover px-3 py-2 text-[11px] shadow-[4px_4px_0_var(--shadow-hard)]" data-testid="curve-drawer">
        <div className="scroll-row items-center gap-2">
          <span className="font-semibold">{t("3D curve")}</span>
          <input id="curve-name" aria-label={t("name")} className="w-20 border border-input bg-background px-1 font-mono" value={name} onChange={(event) => setName(event.target.value)} />
          <span className="flex border border-input">
            {TOOLS.map((item) => (
              <button
                key={item.kind}
                type="button"
                title={`${t(item.label)} (${item.key.toUpperCase()})`}
                className={`flex items-center gap-1 px-1.5 ${tool === item.kind ? "bg-primary text-primary-foreground" : ""}`}
                onClick={() => switchTool(item.kind)}
              >
                <item.icon className="size-3" /> {t(item.label)}
              </button>
            ))}
          </span>
          <span className="text-muted-foreground">{t("on")}</span>
          <select id="curve-plane" aria-label={t("drawing plane")} className="border border-input bg-background px-1" value={plane?.name} onChange={(event) => setPlaneName(event.target.value)}>
            {planes.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <span className="text-muted-foreground">
          {hint} {t("Snaps to vertices, edge midpoints, workplane origins, its own points and the grid. Tab: next plane · ⌫: back")}
        </span>
        <div className="flex items-center gap-2">
          <button type="button" disabled={busy || doc.curves.length + (pending.length && tool === "spline" ? 1 : 0) === 0} className="border-2 border-primary bg-primary px-2 py-0.5 font-semibold text-primary-foreground disabled:opacity-50" onClick={finish}>
            {t("Finish")} (Enter)
          </button>
          <button type="button" className="border border-border px-2 py-0.5 hover:bg-accent" onClick={onCancel}>
            {t("Cancel")} (Esc)
          </button>
          <span className="font-mono text-muted-foreground">
            {doc.curves.length === 1 ? t("1 segment") : t("{{count}} segments", { count: doc.curves.length })} · {nextId(doc.points.map((p) => p.id), "p")}
          </span>
        </div>
        {error && (
          <div role="alert" className="text-fail">
            {error}
          </div>
        )}
      </div>
    </>
  );
}
