import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import { createAxisTriad } from "@/components/scene/axis-triad";
import { SceneLabel } from "@/components/scene/SceneLabel";
import { useSceneLayer } from "@/components/scene/useSceneLayer";
import { placementDirToWorld, placementToWorld, type Component, type ConnectorFrame } from "@/lib/assembly";
import { cadFramePose, connectorSizeMm, type V3 } from "@/scene/cad-pose";
import { placementMatrix } from "@/scene/cad-three";
import { fitDistance } from "@/scene/camera-fit";
import { applyApparentScale } from "@/scene/layers/apparent-size";
import { layerHostFor, type Anchor } from "@/scene/layers/layer-host";
import type { SceneView } from "@/scene/scene-view";

/** One connector frame to draw: `owner` is the component it belongs to (null for the open part's own connectors). */
export type Gizmo = { key: string; owner: string | null; frame: ConnectorFrame };

const LAYER = "connectors";
/** Gizmo size = 12 % of the model's largest extent, clamped to [3, 120] mm. */
const SIZE = { fraction: 0.12, min: 3, max: 120 };
/** The apparent-size compromise: the size follows the camera distance (roughly constant on screen) between 0.15x and 3x. */
const FACTORS = { minFactor: 0.15, maxFactor: 3 };

const cross = (a: V3, b: V3): [number, number, number] => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

/** The pose (glTF, relative to the layer root) of a component at its document placement: used while the viewer holds no node of it. */
function placementFallback(comp: Component): THREE.Matrix4 {
  const x = placementDirToWorld(comp, [1, 0, 0]);
  const y = placementDirToWorld(comp, [0, 1, 0]);
  return placementMatrix({ origin: placementToWorld(comp, [0, 0, 0]), x_axis: x, y_axis: y, z_axis: cross(x, y) });
}

/** The gizmo's `Gizmo` of a pick, label text of a gizmo. */
const labelOf = (g: Gizmo) => `${g.owner ? `${g.owner}.` : ""}${g.frame.id}`;

/** Connector frames drawn as REAL 3D objects in the viewer's scene (a "connectors" scene layer): X red / Y green / Z blue
 * arrows with cone heads, an origin dot and a contact-plane square, so the camera gives exact perspective and
 * foreshortening, the model hides them (with a faint always-visible second pass), and a solved joint or the exploded
 * view moves them with their part (layer items follow the component's node object).
 *
 * This component renders only the labels (hovered, highlighted or, with `armed`, all) and manages the layer.  A click
 * on a gizmo reports it through `onPick` (and is not seen by the model picker).
 *
 * Size: world-sized from the model (12 % of its largest extent, clamped), with the apparent size kept roughly
 * constant while zooming (scaled by camera distance relative to the model's framing distance, clamped to 0.15x..3x). */
export function ConnectorGizmos({
  view,
  gizmos,
  components,
  highlighted,
  onPick,
  armed = false,
}: {
  view: SceneView;
  gizmos: Gizmo[];
  components: Component[];
  highlighted: ReadonlySet<string>;
  onPick?: (gizmo: Gizmo) => void;
  /** A connector picker is armed: every frame is emphasised and labelled. */
  armed?: boolean;
}) {
  const layer = useSceneLayer(view, LAYER);
  const [hover, setHover] = useState<string | null>(null);
  const byKey = useRef(new Map<string, Gizmo>());
  const pickRef = useRef(onPick);
  useEffect(() => {
    pickRef.current = onPick;
  });

  // The frames: rebuilt when the list (or the components' placements) change.
  useEffect(() => {
    if (!layer) return;
    layer.clear();
    byKey.current = new Map(gizmos.map((g) => [g.key, g]));
    const sizing = { nodes: null as unknown, count: -1, baseM: 0.01, referenceDistance: 0 };
    const refresh = () => {
      const { engine } = view;
      const count = engine.modelRoot.children.length;
      if (sizing.nodes === view.nodes && sizing.count === count) return;
      sizing.nodes = view.nodes;
      sizing.count = count;
      const bounds = view.modelBoundsMm();
      sizing.baseM = connectorSizeMm(bounds, SIZE) / 1000;
      const radiusM = bounds ? Math.hypot(bounds.max[0] - bounds.min[0], bounds.max[1] - bounds.min[1], bounds.max[2] - bounds.min[2]) / 2000 : 0;
      sizing.referenceDistance = radiusM > 0 ? fitDistance(radiusM, THREE.MathUtils.degToRad(engine.camera.fov), engine.camera.aspect) : engine.camera.position.distanceTo(engine.controls.target);
    };
    for (const g of gizmos) {
      const pose = cadFramePose(g.frame);
      if (!pose) continue;
      const triad = createAxisTriad();
      triad.object.position.copy(pose.position);
      triad.object.quaternion.copy(pose.quaternion);
      const comp = g.owner ? components.find((c) => c.id === g.owner) : undefined;
      const anchor: Anchor | null = g.owner ? { componentId: g.owner } : null;
      layer.add({
        key: g.key,
        object: triad.object,
        anchor,
        fallback: comp ? placementFallback(comp) : undefined,
        onState: (state) => triad.setState(state),
        onFrame: ({ camera }) => {
          refresh();
          // The pose (position) is in metres already; the scale carries the world size.
          applyApparentScale(triad.object, camera, sizing.baseM, { referenceDistance: sizing.referenceDistance, ...FACTORS });
        },
      });
    }
    layerHostFor(view).sync(true);
  }, [layer, gizmos, components, view]);

  // Emphasis: highlighted = selected, armed = active for every frame, hover from the pointer.
  useEffect(() => {
    if (!layer) return;
    layer.setSelected(highlighted);
    layer.setActive(armed ? gizmos.map((g) => g.key) : []);
  }, [layer, highlighted, armed, gizmos]);
  useEffect(() => {
    layer?.setHover(hover);
  }, [layer, hover]);

  // Pointer: hover feedback and click picking on the 3D frames (capture phase: a hit never reaches the model picker).
  useEffect(() => {
    if (!layer) return;
    const element = view.engine.domElement;
    const previousCursor = element.style.cursor;
    let down: { x: number; y: number } | null = null;
    let frame = 0;
    let last: { x: number; y: number } | null = null;
    const onMove = (event: PointerEvent) => {
      if (event.buttons !== 0) return;
      last = { x: event.clientX, y: event.clientY };
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const hit = last ? layer.pick(last.x, last.y) : null;
        setHover(hit ? hit.key : null);
        element.style.cursor = hit && pickRef.current ? "pointer" : previousCursor;
      });
    };
    const onLeave = () => {
      setHover(null);
      element.style.cursor = previousCursor;
    };
    const onDown = (event: PointerEvent) => {
      down = event.button === 0 ? { x: event.clientX, y: event.clientY } : null;
    };
    const onUp = (event: PointerEvent) => {
      const start = down;
      down = null;
      if (!start || event.button !== 0 || !pickRef.current) return;
      if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4) return;
      const hit = layer.pick(event.clientX, event.clientY);
      const gizmo = hit ? byKey.current.get(hit.key) : undefined;
      if (!gizmo) return;
      event.stopImmediatePropagation();
      event.preventDefault();
      pickRef.current(gizmo);
    };
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerleave", onLeave);
    element.addEventListener("pointerdown", onDown, true);
    element.addEventListener("pointerup", onUp, true);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerleave", onLeave);
      element.removeEventListener("pointerdown", onDown, true);
      element.removeEventListener("pointerup", onUp, true);
      element.style.cursor = previousCursor;
      setHover(null);
    };
  }, [layer, view]);

  const labelled = useMemo(() => gizmos.filter((g) => armed || g.key === hover || highlighted.has(g.key)), [gizmos, armed, hover, highlighted]);

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-testid="connector-gizmos" data-gizmos={gizmos.length}>
      {layer &&
        labelled.map((g) => (
          <SceneLabel
            key={g.key}
            view={view}
            getPoint={() => layer.get(g.key)?.worldPosition() ?? null}
            className="rounded border border-border bg-background/85 px-1 font-mono text-[11px] font-bold text-foreground"
          >
            <span data-gizmo-label={g.key}>{labelOf(g)}</span>
          </SceneLabel>
        ))}
    </div>
  );
}
