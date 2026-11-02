import { useRef } from "react";
import * as THREE from "three";

import { useViewer } from "@/components/sketch/SketchOverlay";
import { placementDirToWorld, placementToWorld, type Component, type ConnectorFrame } from "@/lib/assembly";
import type { Vec3 } from "@/lib/sketch-plane";
import { worldToScreen } from "@/lib/sketch-view";
import type { SceneView } from "@/scene/scene-view";

/** One connector frame to draw: `owner` is the component it belongs to (null for the open part's own connectors). */
export type Gizmo = { key: string; owner: string | null; frame: ConnectorFrame };

const AXIS_INK = ["var(--fail)", "var(--pass)", "var(--focus)"];
const LENGTH_PX = 28;

/** The matrix that takes a part-frame point (metres in the scene) into the world, from the viewer's own node of the
 * component when it holds one (so a solved joint moves the gizmo with the part); null when it holds none. */
function nodeMatrix(view: SceneView, owner: string | null): THREE.Matrix4 | null {
  if (owner === null) return null; // the open part sits at the world origin
  const node = view.nodes.find((n) => n.component_id === owner);
  const object = node ? view.nodeObject(node.node_id) : undefined;
  if (!object) return null;
  object.updateWorldMatrix(true, false);
  return object.matrixWorld;
}

/** Connector frames drawn as small coordinate gizmos (x red, y green, z blue) over the 3D view, projected with the live
 * camera.  A click on one reports it: the assembly panel's picker takes it.  Frames of a component follow the viewer's own
 * node of that component (the solved pose); without one they are drawn at the component's placement in the document. */
export function ConnectorGizmos({
  view,
  gizmos,
  components,
  highlighted,
  onPick,
}: {
  view: SceneView;
  gizmos: Gizmo[];
  components: Component[];
  highlighted: ReadonlySet<string>;
  onPick?: (gizmo: Gizmo) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { viewer, size } = useViewer(view, host);

  const items = gizmos.map((g) => {
    const m = nodeMatrix(view, g.owner);
    const comp = g.owner ? components.find((c) => c.id === g.owner) : undefined;
    const point = (p: Vec3): Vec3 => {
      if (m) {
        const v = new THREE.Vector3(p[0] / 1000, p[1] / 1000, p[2] / 1000).applyMatrix4(m);
        return [v.x * 1000, v.y * 1000, v.z * 1000];
      }
      return comp ? placementToWorld(comp, p) : p;
    };
    const dir = (d: Vec3): Vec3 => {
      if (m) {
        const v = new THREE.Vector3(d[0], d[1], d[2]).transformDirection(m);
        return [v.x, v.y, v.z];
      }
      return comp ? placementDirToWorld(comp, d) : d;
    };
    const f = g.frame;
    const z: Vec3 = f.z_axis ?? [f.x_axis[1] * f.y_axis[2] - f.x_axis[2] * f.y_axis[1], f.x_axis[2] * f.y_axis[0] - f.x_axis[0] * f.y_axis[2], f.x_axis[0] * f.y_axis[1] - f.x_axis[1] * f.y_axis[0]];
    const origin = point(f.origin);
    const o = worldToScreen(viewer, origin);
    const axes = [f.x_axis, f.y_axis, z].map((a) => {
      const d = dir(a);
      const tip = worldToScreen(viewer, [origin[0] + d[0], origin[1] + d[1], origin[2] + d[2]]);
      if (!o || !tip) return null;
      const len = Math.hypot(tip[0] - o[0], tip[1] - o[1]);
      // An axis seen end-on has no direction on screen: it is drawn as a short tick.
      if (len < 1e-6) return [o[0], o[1] - 0] as [number, number];
      return [o[0] + ((tip[0] - o[0]) / len) * LENGTH_PX, o[1] + ((tip[1] - o[1]) / len) * LENGTH_PX] as [number, number];
    });
    return { g, o, axes };
  });

  return (
    <div ref={host} className="pointer-events-none absolute inset-0 z-[5]" data-testid="connector-gizmos">
      <svg width={size.w} height={size.h} className="pointer-events-none absolute inset-0 block select-none">
        {items.map(({ g, o, axes }) => {
          if (!o) return null;
          const on = highlighted.has(g.key);
          return (
            <g key={g.key} data-gizmo={g.key} style={{ pointerEvents: onPick ? "all" : "none", cursor: onPick ? "pointer" : "default" }} onClick={() => onPick?.(g)}>
              <title>{`${g.owner ? `${g.owner}.` : ""}${g.frame.id}`}</title>
              {axes.map((tip, i) =>
                tip ? (
                  <g key={i}>
                    <line x1={o[0]} y1={o[1]} x2={tip[0]} y2={tip[1]} stroke="var(--background)" strokeWidth={on ? 6 : 5} strokeLinecap="round" />
                    <line x1={o[0]} y1={o[1]} x2={tip[0]} y2={tip[1]} stroke={AXIS_INK[i]} strokeWidth={on ? 3.2 : 2.2} strokeLinecap="round" />
                  </g>
                ) : null,
              )}
              <circle cx={o[0]} cy={o[1]} r={on ? 8 : 6} fill="var(--background)" stroke={on ? "var(--focus)" : "var(--foreground)"} strokeWidth={on ? 3 : 2} />
              <text x={o[0] + 10} y={o[1] - 8} fontSize={11} fontWeight={700} fill={on ? "var(--focus)" : "var(--foreground)"} stroke="var(--background)" strokeWidth={4} paintOrder="stroke" style={{ fontFamily: "var(--mono)" }}>
                {g.owner ? `${g.owner}.` : ""}
                {g.frame.id}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
