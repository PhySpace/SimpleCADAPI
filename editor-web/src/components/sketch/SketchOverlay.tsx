import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

import {
  CONSTRAINT_INFO,
  arcSweep,
  circleRadius,
  constraintAnchor,
  dimensionValue,
  formatValue,
  gridStep,
  isDimensional,
  sampleArc,
  type SketchDoc,
} from "@/lib/sketch";
import { planeToWorld, rayPlane, type PlaneSpec } from "@/lib/sketch-plane";
import { cameraSignature, planeToScreen, scaleAt, screenRay, screenToPlane, type Viewer } from "@/lib/sketch-view";
import { CORNER_WORD, isProjected } from "@/lib/sketch-edit";
import type { PointerInfo, SketchEditor } from "@/lib/useSketchEditor";
import type { SceneView } from "@/scene/scene-view";

const INK = "var(--foreground)";
const MUTED = "var(--muted-foreground)";
const PASS = "var(--pass)";
const FAIL = "var(--fail)";
const FOCUS = "var(--focus)";
const NAME = "var(--name)";
const HALO = "var(--background)";

type P = [number, number];

/** Re-renders its caller whenever the camera or the canvas size changes, and gives the live viewer. */
export function useViewer(view: SceneView, host: React.RefObject<HTMLElement | null>): { viewer: Viewer; size: { w: number; h: number } } {
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [, setSignature] = useState("");
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const measure = () => setSize({ w: Math.max(el.clientWidth, 100), h: Math.max(el.clientHeight, 100) });
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, [host]);
  const viewer: Viewer = { camera: view.engine.camera, width: size.w, height: size.h };
  const latest = useRef(viewer);
  latest.current = viewer;
  useEffect(() => {
    let frame = 0;
    const loop = () => {
      const next = cameraSignature(latest.current);
      setSignature((previous) => (previous === next ? previous : next));
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, []);
  return { viewer, size };
}

/** The sketch drawn over the 3D canvas: the plane's grid patch and axes, the geometry, constraints and dimensions,
 * the draft of the active tool.  Plane positions are projected with the live camera; pointer positions come back through
 * a ray-plane intersection.  Left button = the active tool; middle or right drag (or Alt+left) orbits, shift+middle pans,
 * space+left pans, the wheel dollies toward the cursor. */
export function SketchOverlay({
  view,
  plane,
  editor,
  spaceRef,
}: {
  view: SceneView;
  plane: PlaneSpec;
  editor: SketchEditor;
  spaceRef: React.MutableRefObject<boolean>;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const { viewer, size } = useViewer(view, wrap);
  const camera = useRef<{ mode: "orbit" | "pan"; x: number; y: number } | null>(null);
  const [moving, setMoving] = useState(false);
  const { doc, result, pts, loops, choice, selection, hover, draft, cursor, tool, highlight, box, setBox } = editor;

  const project = (u: number, v: number): P | null => planeToScreen(viewer, plane, u, v);
  const polyline = (list: readonly P[], close = false): string => {
    let d = "";
    let pen = false;
    for (const [u, v] of list) {
      const s = project(u, v);
      if (!s) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${s[0].toFixed(1)} ${s[1].toFixed(1)}`;
      pen = true;
    }
    return close && d ? `${d}Z` : d;
  };

  // -- pointer ------------------------------------------------------------------------------------------------------
  const focusPlane = (): P => screenToPlane(viewer, plane, size.w / 2, size.h / 2) ?? [0, 0];
  const infoOf = (event: { clientX: number; clientY: number; shiftKey: boolean; altKey: boolean }): PointerInfo => {
    const rect = svg.current!.getBoundingClientRect();
    const sx = event.clientX - rect.left;
    const sy = event.clientY - rect.top;
    const world = screenToPlane(viewer, plane, sx, sy);
    const at = world ?? focusPlane();
    return { sx, sy, world, scale: scaleAt(viewer, plane, at[0], at[1]), shift: event.shiftKey, alt: event.altKey };
  };

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    wrap.current?.focus({ preventScroll: true });
    const target = event.target as Element;
    const labelOf = target.closest("[data-cid]")?.getAttribute("data-cid");
    const orbit = event.button === 2 || (event.button === 1 && !event.shiftKey) || (event.button === 0 && event.altKey);
    const pan = (event.button === 1 && event.shiftKey) || (event.button === 0 && spaceRef.current);
    if (orbit || pan) {
      event.preventDefault();
      view.rig.cancelAnimation();
      camera.current = { mode: pan ? "pan" : "orbit", x: event.clientX, y: event.clientY };
      setMoving(true);
      svg.current?.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0) return;
    if (labelOf) {
      editor.setHighlight((h) => (h === labelOf ? null : labelOf));
      return;
    }
    if (editor.pointerDown(infoOf(event)) === "press") svg.current?.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const drag = camera.current;
    if (drag) {
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      camera.current = { ...drag, x: event.clientX, y: event.clientY };
      if (drag.mode === "pan") view.rig.pan(dx, dy, size.h);
      else view.rig.orbit(dx * 0.006, dy * 0.006);
      return;
    }
    editor.pointerMove(infoOf(event));
  };

  const onPointerUp = (event: React.PointerEvent<SVGSVGElement>) => {
    if (svg.current?.hasPointerCapture(event.pointerId)) svg.current.releasePointerCapture(event.pointerId);
    if (camera.current) {
      camera.current = null;
      setMoving(false);
      return;
    }
    void editor.pointerUp();
  };

  const viewerRef = useRef(viewer);
  viewerRef.current = viewer;
  const planeRef = useRef(plane);
  planeRef.current = plane;
  // Debug/agent affordance (like `__studioView`): where a plane position is on the page, in client pixels.
  useEffect(() => {
    const w = window as unknown as { __sketchProject?: (u: number, v: number) => [number, number] | null };
    w.__sketchProject = (u, v) => {
      const s = planeToScreen(viewerRef.current, planeRef.current, u, v);
      const rect = svg.current?.getBoundingClientRect();
      return s && rect ? [s[0] + rect.left, s[1] + rect.top] : null;
    };
    return () => {
      delete w.__sketchProject;
    };
  }, []);
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      const ray = screenRay(viewerRef.current, event.clientX - rect.left, event.clientY - rect.top);
      const hit = rayPlane(ray.origin, ray.dir, planeRef.current);
      const world = hit ? planeToWorld(planeRef.current, hit[0], hit[1]) : null;
      view.rig.cancelAnimation();
      view.rig.dolly(Math.exp(event.deltaY * 0.0015), world ? new THREE.Vector3(world[0] / 1000, world[1] / 1000, world[2] / 1000) : null);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [view]);

  // -- the plane's grid patch and axes ----------------------------------------------------------------------------------------
  const patch = (() => {
    const centre = focusPlane();
    const step = gridStep(scaleAt(viewer, plane, centre[0], centre[1]), 16);
    const reach = step * 20;
    const u0 = Math.round(centre[0] / step) * step;
    const v0 = Math.round(centre[1] / step) * step;
    const minor: string[] = [];
    const major: string[] = [];
    for (let i = -20; i <= 20; i++) {
      const u = u0 + i * step;
      const v = v0 + i * step;
      const isMajor = Math.round(u / step) % 5 === 0;
      const isMajorV = Math.round(v / step) % 5 === 0;
      (isMajor ? major : minor).push(polyline([[u, v0 - reach], [u, v0 + reach]]));
      (isMajorV ? major : minor).push(polyline([[u0 - reach, v], [u0 + reach, v]]));
    }
    const axisReach = Math.max(reach, Math.abs(u0) + reach, Math.abs(v0) + reach);
    return {
      minor: minor.join(""),
      major: major.join(""),
      outline: polyline([[u0 - reach, v0 - reach], [u0 + reach, v0 - reach], [u0 + reach, v0 + reach], [u0 - reach, v0 + reach]], true),
      uAxis: polyline([[-axisReach, 0], [axisReach, 0]]),
      vAxis: polyline([[0, -axisReach], [0, axisReach]]),
      tip: { u: project(Math.min(u0 + reach, axisReach) * 0.96, 0), v: project(0, Math.min(v0 + reach, axisReach) * 0.96) },
    };
  })();

  // -- geometry -----------------------------------------------------------------------------------------------------------------
  const solved = editor.solved;
  const cutting = tool === "trim"; // the piece under the cursor is shown in the warning colour: it is what a click removes
  // Fillet and chamfer: the corner under the cursor (or the one being valued) shows its point and both lines.
  const corner = editor.cornerBox?.corner ?? editor.cornerHover;
  const cornerLines = new Set<string>(corner ? [corner.a, corner.b] : editor.pendingLine ? [editor.pendingLine] : []);
  const strokeOf = (id: string, construct?: boolean) => {
    if (editor.flash.has(id)) return NAME;
    if (cutting && hover?.id === id) return FAIL;
    if (cornerLines.has(id)) return FOCUS;
    if (editor.failing.has(id)) return FAIL;
    if (editor.highlighted.has(id)) return NAME;
    if (selection.includes(id)) return FOCUS;
    if (hover?.id === id) return FOCUS;
    if (construct) return MUTED;
    return solved ? PASS : INK;
  };

  const entityPath = (e: SketchDoc["entities"][number]): string => {
    if (e.kind === "line") {
      const a = pts.get(e.start ?? "");
      const b = pts.get(e.end ?? "");
      return a && b ? polyline([a, b]) : "";
    }
    const c = pts.get(e.center ?? "");
    if (!c) return "";
    if (e.kind === "circle") {
      const r = circleRadius(doc, e, pts, result);
      return polyline(Array.from({ length: 72 }, (_, i) => [c[0] + r * Math.cos((2 * Math.PI * i) / 72), c[1] + r * Math.sin((2 * Math.PI * i) / 72)] as P), true);
    }
    const s = pts.get(e.start ?? "");
    const en = pts.get(e.end ?? "");
    if (!s || !en) return "";
    const r = Math.hypot(s[0] - c[0], s[1] - c[1]);
    const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
    const sweep = arcSweep(c, s, en);
    return polyline(sampleArc(c, s, [c[0] + r * Math.cos(a0 + sweep), c[1] + r * Math.sin(a0 + sweep)], 40));
  };

  const screenDir = (u: number, v: number, nx: number, ny: number): P => {
    const a = project(u, v);
    const b = project(u + nx * 0.5, v + ny * 0.5);
    if (!a || !b) return [nx, -ny];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    return [(b[0] - a[0]) / len, (b[1] - a[1]) / len];
  };

  const stacks = new Map<string, number>();
  const labelNodes = doc.constraints.map((c) => {
    const anchor = constraintAnchor(c, doc, result);
    if (!anchor) return null;
    const a = project(anchor.x, anchor.y);
    if (!a) return null;
    const key = `${Math.round(a[0] / 12)}:${Math.round(a[1] / 12)}`;
    const n = stacks.get(key) ?? 0;
    stacks.set(key, n + 1);
    const dir = screenDir(anchor.x, anchor.y, anchor.nx, anchor.ny);
    const sx = a[0] + dir[0] * anchor.offset - dir[1] * 13 * n;
    const sy = a[1] + dir[1] * anchor.offset + dir[0] * 13 * n;
    const dimensional = isDimensional(c.kind);
    const color = editor.blamed.has(c.id) ? FAIL : highlight === c.id ? NAME : dimensional ? (c.driving === false ? MUTED : NAME) : MUTED;
    const text = dimensional
      ? `${c.kind === "radius" || c.kind === "diameter" ? CONSTRAINT_INFO[c.kind].glyph : ""}${formatValue(dimensionValue(c, doc, result), c.kind)}`
      : CONSTRAINT_INFO[c.kind].glyph;
    if (!text || c.kind === "coincident") return null;
    return (
      <text
        key={c.id}
        data-cid={c.id}
        data-kind={c.kind}
        x={sx}
        y={sy}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={dimensional ? 12 : 10}
        fontWeight={dimensional ? 700 : 600}
        fill={color}
        stroke={HALO}
        strokeWidth={4}
        paintOrder="stroke"
        style={{ cursor: "pointer", fontFamily: "var(--mono)" }}
        onDoubleClick={() => dimensional && editor.openBox(c.kind, c.targets, c)}
      >
        {c.driving === false ? `(${text})` : text}
      </text>
    );
  });

  // -- the draft of the active tool --------------------------------------------------------------------------------------------
  const spotPos = (spot: { x: number; y: number; pointId?: string }): P => (spot.pointId ? (pts.get(spot.pointId) ?? [spot.x, spot.y]) : [spot.x, spot.y]);
  const preview = (() => {
    if (!draft || !cursor) return null;
    const props = { fill: "none", strokeLinecap: "round" as const };
    const dash = "6 4";
    const line = (a: P, b: P) => polyline([a, b]);
    const both = (d: string, extra?: { opacity?: number }) => (
      <g {...props}>
        <path d={d} stroke={HALO} strokeWidth={4.5} opacity={0.8 * (extra?.opacity ?? 1)} />
        <path d={d} stroke={FOCUS} strokeWidth={1.8} strokeDasharray={dash} opacity={extra?.opacity} />
      </g>
    );
    const cur: P = [cursor.x, cursor.y];
    if (draft.tool === "line") return both(line(spotPos(draft.from), cur));
    const centre = spotPos(draft.center);
    if (draft.tool === "circle") {
      const r = Math.hypot(cur[0] - centre[0], cur[1] - centre[1]);
      return (
        <>
          {both(polyline(Array.from({ length: 72 }, (_, i) => [centre[0] + r * Math.cos((2 * Math.PI * i) / 72), centre[1] + r * Math.sin((2 * Math.PI * i) / 72)] as P), true))}
          {both(line(centre, cur), { opacity: 0.6 })}
        </>
      );
    }
    if (!draft.start) return both(line(centre, cur));
    const start = spotPos(draft.start);
    const r = Math.hypot(start[0] - centre[0], start[1] - centre[1]);
    const a0 = Math.atan2(start[1] - centre[1], start[0] - centre[0]);
    const sweep = arcSweep(centre, start, cur);
    const end: P = [centre[0] + r * Math.cos(a0 + sweep), centre[1] + r * Math.sin(a0 + sweep)];
    return (
      <>
        {both(polyline(sampleArc(centre, start, end, 40)))}
        {both(polyline([centre, start, centre, end]), { opacity: 0.5 })}
      </>
    );
  })();

  // -- the dimension value box, at the dimension on screen -----------------------------------------------------------------------
  const boxNode = (() => {
    if (!box) return null;
    const a = constraintAnchor({ id: "tmp_box", kind: box.kind, targets: box.targets }, doc, result);
    const s = a ? project(a.x, a.y) : null;
    const dir = a ? screenDir(a.x, a.y, a.nx, a.ny) : [0, 0];
    const x = s ? s[0] + dir[0] * (a?.offset ?? 0) * 1.5 : size.w / 2;
    const y = s ? s[1] + dir[1] * (a?.offset ?? 0) * 1.5 : 80;
    const left = Math.min(Math.max(x, 80), size.w - 120);
    const top = Math.min(Math.max(y, 30), size.h - 30);
    return (
      <div
        className="absolute z-20 flex items-center gap-1 border-2 border-primary bg-popover p-1 shadow-[4px_4px_0_var(--shadow-hard)]"
        style={{ left: left - 50, top: top - 14 }}
        data-testid="sketch-value-box"
      >
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{CONSTRAINT_INFO[box.kind].label}</span>
        <input
          autoFocus
          data-testid="sketch-value"
          aria-label="Dimension value"
          aria-invalid={box.bad}
          value={box.text}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => setBox({ ...box, text: e.target.value, bad: false })}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") {
              e.preventDefault();
              editor.submitBox();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setBox(null);
              wrap.current?.focus();
            }
          }}
          className="h-6 w-16 border-2 border-input bg-background px-1 text-[12px] focus-visible:border-focus focus-visible:outline-none aria-[invalid=true]:border-fail"
        />
        <span className="text-[10px] uppercase text-muted-foreground">{CONSTRAINT_INFO[box.kind].unit}</span>
      </div>
    );
  })();

  // Extend: the end of the hovered line the click would extend.
  const hoverMark = (() => {
    if (tool !== "extend" || !editor.hoverEnd || hover?.kind !== "entity") return null;
    const e = doc.entities.find((item) => item.id === hover.id);
    const at = pts.get((editor.hoverEnd === "start" ? e?.start : e?.end) ?? "");
    const s = at ? project(at[0], at[1]) : null;
    return s ? <circle cx={s[0]} cy={s[1]} r={9} fill="none" stroke={PASS} strokeWidth={2.5} data-testid="extend-end" data-end={editor.hoverEnd} /> : null;
  })();

  // The value box of a corner, beside the corner point.
  const cornerBoxNode = (() => {
    const cb = editor.cornerBox;
    if (!cb) return null;
    const at = pts.get(cb.corner.point);
    const s = at ? project(at[0], at[1]) : null;
    const left = Math.min(Math.max((s ? s[0] : size.w / 2) + 14, 8), size.w - 190);
    const top = Math.min(Math.max((s ? s[1] : 80) - 34, 8), size.h - 40);
    const word = CORNER_WORD[cb.op];
    return (
      <div className="absolute z-20 flex items-center gap-1 border-2 border-primary bg-popover p-1 shadow-[4px_4px_0_var(--shadow-hard)]" style={{ left, top }} data-testid="sketch-corner-box" data-op={cb.op}>
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{word.label}</span>
        <input
          autoFocus
          data-testid="sketch-corner-value"
          aria-label={word.label}
          aria-invalid={cb.bad}
          value={cb.text}
          onFocus={(e) => e.currentTarget.select()}
          onChange={(e) => editor.setCornerBox({ ...cb, text: e.target.value, bad: false })}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Enter") {
              e.preventDefault();
              editor.submitCorner();
            } else if (e.key === "Escape") {
              e.preventDefault();
              editor.setCornerBox(null);
              wrap.current?.focus();
            }
          }}
          className="h-6 w-16 border-2 border-input bg-background px-1 text-[12px] focus-visible:border-focus focus-visible:outline-none aria-[invalid=true]:border-fail"
        />
        <span className="text-[10px] uppercase text-muted-foreground">mm</span>
      </div>
    );
  })();

  // The corner under the cursor: a ring on its point.
  const cornerMark = (() => {
    if (!corner) return null;
    const at = pts.get(corner.point);
    const s = at ? project(at[0], at[1]) : null;
    return s ? <circle cx={s[0]} cy={s[1]} r={10} fill="none" stroke={FOCUS} strokeWidth={2.5} data-testid="corner-mark" data-corner={corner.point} /> : null;
  })();

  const cursorMark = (() => {
    if (!cursor || tool === "select" || tool === "delete" || tool === "trim" || tool === "extend" || tool === "fillet" || tool === "chamfer") return null;
    const s = project(cursor.x, cursor.y);
    if (!s) return null;
    return cursor.pointId ? (
      <circle cx={s[0]} cy={s[1]} r={8} fill="none" stroke={FOCUS} strokeWidth={2} />
    ) : (
      <path d={`M${s[0] - 6} ${s[1]}H${s[0] + 6}M${s[0]} ${s[1] - 6}V${s[1] + 6}`} stroke={FOCUS} strokeWidth={1.5} />
    );
  })();

  const dragging = editor.drag !== null;
  const cursorStyle = moving ? "grabbing" : tool === "select" || tool === "trim" || tool === "extend" || tool === "fillet" || tool === "chamfer" ? (dragging ? "grabbing" : hover ? "pointer" : "default") : "crosshair";

  return (
    <div ref={wrap} className="absolute inset-0 overflow-hidden outline-none" data-testid="sketch-canvas" tabIndex={-1}>
      <svg
        ref={svg}
        width={size.w}
        height={size.h}
        className="block touch-none select-none"
        style={{ cursor: cursorStyle }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={editor.pointerLeave}
        onContextMenu={(e) => e.preventDefault()}
      >
        <rect width={size.w} height={size.h} fill={HALO} opacity={0.3} />
        <path d={patch.minor} stroke={MUTED} strokeWidth={0.5} opacity={0.35} fill="none" />
        <path d={patch.major} stroke={MUTED} strokeWidth={1} opacity={0.55} fill="none" />
        <path d={patch.outline} stroke={MUTED} strokeWidth={1} opacity={0.6} fill={HALO} fillOpacity={0.12} />
        <path d={patch.uAxis} stroke={FAIL} strokeWidth={1.6} opacity={0.8} />
        <path d={patch.vAxis} stroke={PASS} strokeWidth={1.6} opacity={0.8} />
        {patch.tip.u && (
          <text x={patch.tip.u[0]} y={patch.tip.u[1] - 8} fill={FAIL} fontSize={11} fontWeight={700} textAnchor="middle" stroke={HALO} strokeWidth={3} paintOrder="stroke">
            x
          </text>
        )}
        {patch.tip.v && (
          <text x={patch.tip.v[0] + 10} y={patch.tip.v[1]} fill={PASS} fontSize={11} fontWeight={700} textAnchor="middle" stroke={HALO} strokeWidth={3} paintOrder="stroke">
            y
          </text>
        )}
        {loops.map((loop) => {
          const isOuter = loop.key === choice.outer;
          const isInner = choice.inner.includes(loop.key);
          return (
            <path
              key={loop.key}
              d={polyline(loop.polygon, true)}
              fill={isOuter ? FOCUS : isInner ? NAME : MUTED}
              fillOpacity={isOuter ? 0.28 : isInner ? 0.36 : 0.1}
              stroke="none"
              data-loop={loop.key}
              data-role={isOuter ? "outer" : isInner ? "hole" : "loop"}
              pointerEvents="none"
            />
          );
        })}
        {doc.entities.map((e) => {
          const d = entityPath(e);
          if (!d) return null;
          const picked = selection.includes(e.id) || hover?.id === e.id || editor.flash.has(e.id) || cornerLines.has(e.id);
          const projected = isProjected(e.id); // fixed reference copies of another sketch: muted, dotted
          const dash = projected ? "1.5 4" : e.construction ? "6 4" : undefined;
          return (
            <g key={e.id} fill="none" strokeLinecap="round" strokeLinejoin="round" data-entity={e.id} data-projected={projected || undefined} data-flash={editor.flash.has(e.id) || undefined}>
              <path d={d} stroke={HALO} strokeWidth={picked ? 6.5 : 5} opacity={0.85} strokeDasharray={dash} />
              <path d={d} stroke={strokeOf(e.id, e.construction)} strokeWidth={picked ? 3 : projected ? 2.6 : 2.2} strokeDasharray={dash} />
            </g>
          );
        })}
        {doc.points.map((p) => {
          const at = pts.get(p.id) ?? [p.x, p.y];
          const s = project(at[0], at[1]);
          if (!s) return null;
          const fixed = editor.fixedPoints.has(p.id);
          const picked = selection.includes(p.id) || hover?.id === p.id;
          const projected = isProjected(p.id);
          const color = editor.flash.has(p.id) ? NAME : editor.failing.has(p.id) ? FAIL : editor.highlighted.has(p.id) ? NAME : picked || corner?.point === p.id ? FOCUS : projected ? MUTED : fixed || solved ? PASS : INK;
          if (projected) {
            return <rect key={p.id} x={s[0] - 4} y={s[1] - 4} width={8} height={8} transform={`rotate(45 ${s[0]} ${s[1]})`} fill={HALO} stroke={color} strokeWidth={2} data-point={p.id} data-projected />;
          }
          return fixed ? (
            <rect key={p.id} x={s[0] - 4.5} y={s[1] - 4.5} width={9} height={9} fill={color} stroke={HALO} strokeWidth={1.5} data-point={p.id} />
          ) : (
            <circle key={p.id} cx={s[0]} cy={s[1]} r={picked ? 5.5 : 4.5} fill={color} stroke={HALO} strokeWidth={1.5} data-point={p.id} />
          );
        })}
        {hoverMark}
        {cornerMark}
        {labelNodes}
        {preview}
        {cursorMark}
      </svg>
      {boxNode}
      {cornerBoxNode}
    </div>
  );
}
