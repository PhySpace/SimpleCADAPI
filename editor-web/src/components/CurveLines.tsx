import { useEffect, useMemo } from "react";
import * as THREE from "three";

import { SceneLabel } from "@/components/scene/SceneLabel";
import type { Vec3 } from "@/lib/sketch-plane";
import { OVERLAY_LAYER } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";

/** A wire or edge value of the notebook, as the kernel sampled it (the server's `curves` envelope): world mm. */
export type CurveSample = { name: string; kind: "wire" | "edge"; edges: Vec3[][] };

const COLOR = "#0ea5e9";

export function parseCurves(raw: unknown): CurveSample[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is CurveSample =>
      !!item && typeof item.name === "string" && Array.isArray(item.edges) && item.edges.every((e: unknown) => Array.isArray(e) && e.length >= 2),
  );
}

/** The ends of the curves' edges: where a new path can join one (snap targets). */
export function curveEnds(curves: readonly CurveSample[]): { at: Vec3; label: string }[] {
  return curves.flatMap((curve) => curve.edges.flatMap((edge, i) => [{ at: edge[0], label: `${curve.name} ${i}` }, { at: edge[edge.length - 1], label: `${curve.name} ${i}` }]));
}

/** The notebook's curves (3D paths, rails, sketches made into wires) drawn in the viewport: they are not solids, so the
 * model preview does not show them.  Display only; the samples are the kernel's (runtime/live_curves.py). */
export function CurveLines({ view, curves }: { view: SceneView; curves: CurveSample[] }) {
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
      const line = child as THREE.Line;
      line.geometry.dispose();
      (line.material as THREE.Material).dispose();
    }
    for (const curve of curves) {
      for (const edge of curve.edges) {
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(edge.map((p) => new THREE.Vector3(p[0] / 1000, p[1] / 1000, p[2] / 1000))),
          new THREE.LineBasicMaterial({ color: COLOR }),
        );
        line.layers.enable(OVERLAY_LAYER);
        line.renderOrder = 12;
        group.add(line);
      }
    }
    view.engine.invalidate();
  }, [curves, group, view]);

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-testid="curve-lines" data-curves={curves.map((c) => c.name).join(",")}>
      {curves.map((curve) => {
        const edge = curve.edges[Math.floor(curve.edges.length / 2)];
        const point = edge[Math.floor(edge.length / 2)];
        return (
          <SceneLabel
            key={curve.name}
            view={view}
            getPoint={() => new THREE.Vector3(point[0] / 1000, point[1] / 1000, point[2] / 1000)}
            offset={[4, -14]}
            className="rounded border border-sky-500 bg-background/85 px-1 font-mono text-[11px] font-bold text-sky-600"
          >
            <span data-curve-label={curve.name}>{curve.name}</span>
          </SceneLabel>
        );
      })}
    </div>
  );
}
