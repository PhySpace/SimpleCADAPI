import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { SceneLabel } from "@/components/scene/SceneLabel";
import type { CurveEnd } from "@/lib/curve3d";
import type { Vec3 } from "@/lib/sketch-plane";
import { cn } from "@/lib/utils";
import { LineMaterial, LineSegments2, LineSegmentsGeometry } from "@/scene/fat-lines";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";

/** A wire or edge value of the notebook, as the kernel sampled it (the server's `curves` envelope): world mm. */
export type CurveSample = { name: string; kind: "wire" | "edge"; edges: Vec3[][] };

const COLOR = "#0ea5e9";
const HOVER = "#38bdf8";
const SELECTED = "#f59e0b";

export function parseCurves(raw: unknown): CurveSample[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is CurveSample =>
      !!item && typeof item.name === "string" && Array.isArray(item.edges) && item.edges.every((e: unknown) => Array.isArray(e) && e.length >= 2),
  );
}

/** The ends of the curves' edges: where a new path can join one (snap targets).  The two ends of a curve that is one
 * edge say which they are (`endOf`): a point drawn there is kept at it. */
export function curveEnds(curves: readonly CurveSample[]): { at: Vec3; label: string; endOf?: CurveEnd }[] {
  return curves.flatMap((curve) =>
    curve.kind === "edge" && curve.edges.length === 1
      ? [
          { at: curve.edges[0][0], label: `${curve.name} start`, endOf: { curve: curve.name, end: "start" as const } },
          { at: curve.edges[0][curve.edges[0].length - 1], label: `${curve.name} end`, endOf: { curve: curve.name, end: "end" as const } },
        ]
      : curve.edges.flatMap((edge, i) => [{ at: edge[0], label: `${curve.name} ${i}` }, { at: edge[edge.length - 1], label: `${curve.name} ${i}` }]),
  );
}

/** The curve whose drawn line passes within `reach` pixels of a screen point (the nearest), or null. */
export function curveAt(curves: readonly CurveSample[], camera: THREE.Camera, rect: { left: number; top: number; width: number; height: number }, x: number, y: number, reach = 7): string | null {
  const screen = (p: Vec3) => {
    const v = new THREE.Vector3(p[0] / 1000, p[1] / 1000, p[2] / 1000).project(camera);
    return v.z > 1 ? null : [rect.left + ((v.x + 1) / 2) * rect.width, rect.top + ((1 - v.y) / 2) * rect.height];
  };
  let best: { name: string; distance: number } | null = null;
  for (const curve of curves) {
    for (const edge of curve.edges) {
      let previous = screen(edge[0]);
      for (let i = 1; i < edge.length; i += 1) {
        const next = screen(edge[i]);
        if (previous && next) {
          const [ax, ay] = previous;
          const [dx, dy] = [next[0] - ax, next[1] - ay];
          const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy || 1)));
          const distance = Math.hypot(ax + t * dx - x, ay + t * dy - y);
          if (distance <= reach && (!best || distance < best.distance)) best = { name: curve.name, distance };
        }
        previous = next;
      }
    }
  }
  return best?.name ?? null;
}

/** The notebook's curves (3D paths, rails, sketches made into wires) drawn in the viewport: they are not solids, so the
 * model preview does not show them (the samples are the kernel's, runtime/live_curves.py).  They are picked with the
 * sketches (the sketch selection mode): the view asks `curveHitter` which one is under a click, and the pointer hovers
 * them while `hoverEnabled`. */
export function CurveLines({
  view,
  curves,
  selected,
  hover,
  hoverEnabled,
  onHover,
}: {
  view: SceneView;
  curves: CurveSample[];
  selected: readonly string[];
  hover: string | null;
  hoverEnabled: boolean;
  onHover: (name: string | null) => void;
}) {
  const group = useMemo(() => new THREE.Group(), []);
  const curvesRef = useRef(curves);
  curvesRef.current = curves;
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  useEffect(() => {
    view.engine.threeScene.add(group);
    view.curveHitter = (event) => curveAt(curvesRef.current, view.engine.camera, view.engine.domElement.getBoundingClientRect(), event.clientX, event.clientY);
    return () => {
      view.curveHitter = null;
      group.removeFromParent();
      view.engine.invalidate();
    };
  }, [view, group]);
  useEffect(() => {
    for (const child of [...group.children]) {
      child.removeFromParent();
      const line = child as LineSegments2;
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    }
    for (const curve of curves) {
      const on = selected.includes(curve.name);
      const geometry = new LineSegmentsGeometry();
      geometry.setPositions(curve.edges.flatMap((edge) => edge.slice(1).flatMap((p, i) => [...edge[i], ...p].map((v) => v / 1000))));
      const line = new LineSegments2(geometry, new LineMaterial({ color: on ? SELECTED : hover === curve.name ? HOVER : COLOR, linewidth: on ? 3.5 : hover === curve.name ? 3 : 2 }));
      line.layers.enable(OVERLAY_LAYER);
      line.renderOrder = 12;
      line.raycast = () => {};
      group.add(line);
    }
    view.engine.invalidate();
  }, [curves, group, view, selected, hover]);

  // The pointer over a curve (only while curves are what a click picks).
  useEffect(() => {
    if (!hoverEnabled) return;
    const element = view.engine.domElement;
    let frame = 0;
    let last: PointerEvent | null = null;
    const run = () => {
      frame = 0;
      if (last) hoverRef.current(view.curveHitter?.(last) ?? null);
    };
    const move = (event: PointerEvent) => {
      if (event.buttons) return;
      last = event;
      if (!frame) frame = requestAnimationFrame(run);
    };
    const leave = () => hoverRef.current(null);
    element.addEventListener("pointermove", move);
    element.addEventListener("pointerleave", leave);
    return () => {
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerleave", leave);
      if (frame) cancelAnimationFrame(frame);
      hoverRef.current(null);
    };
  }, [view, hoverEnabled]);

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-testid="curve-lines" data-curves={curves.map((c) => c.name).join(",")}>
      {curves.map((curve) => {
        const edge = curve.edges[Math.floor(curve.edges.length / 2)];
        const point = edge[Math.floor(edge.length / 2)];
        const on = selected.includes(curve.name);
        return (
          <SceneLabel
            key={curve.name}
            view={view}
            getPoint={() => new THREE.Vector3(point[0] / 1000, point[1] / 1000, point[2] / 1000)}
            offset={[4, -14]}
            className={cn(
              "rounded border bg-background/85 px-1 font-mono text-[11px] font-bold",
              on ? "border-focus text-focus" : "border-sky-500 text-sky-600",
            )}
          >
            <span data-curve-label={curve.name}>{curve.name}</span>
          </SceneLabel>
        );
      })}
    </div>
  );
}
