import { useEffect, useState } from "react";
import * as THREE from "three";

import { SceneLabel } from "@/components/scene/SceneLabel";
import { useSceneLayer } from "@/components/scene/useSceneLayer";
import { patchCorners, type WorkplaneFrame } from "@/lib/workplanes";
import { connectorSizeMm } from "@/scene/cad-pose";
import { cadPointToGltf } from "@/scene/cad-three";
import { layerHostFor } from "@/scene/layers/layer-host";
import type { SceneView } from "@/scene/scene-view";

const LAYER = "workplanes";
/** The patch is 15 % of the model's largest extent across (half of it each way), clamped to [5, 80] mm half-width. */
const SIZE = { fraction: 0.15, min: 5, max: 80, fallback: 20 };
const COLOR = "#d97706";
const ACTIVE = "#2563eb";

/** One patch: a translucent square in the workplane with its outline and a short normal tick, in layer (glTF) space. */
function patchObject(wp: WorkplaneFrame, half: number, active: boolean): THREE.Group {
  const group = new THREE.Group();
  const corners = patchCorners(wp, half).map(cadPointToGltf);
  const color = active ? ACTIVE : COLOR;
  const fill = new THREE.BufferGeometry().setFromPoints([corners[0], corners[1], corners[2], corners[0], corners[2], corners[3]]);
  group.add(
    new THREE.Mesh(
      fill,
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: active ? 0.22 : 0.12, side: THREE.DoubleSide, depthWrite: false }),
    ),
  );
  const outline = new THREE.BufferGeometry().setFromPoints([...corners, corners[0]]);
  group.add(new THREE.Line(outline, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 })));
  const tip: [number, number, number] = [wp.origin[0] + wp.normal[0] * half * 0.5, wp.origin[1] + wp.normal[1] * half * 0.5, wp.origin[2] + wp.normal[2] * half * 0.5];
  group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([cadPointToGltf(wp.origin), cadPointToGltf(tip)]), new THREE.LineBasicMaterial({ color })));
  return group;
}

/** The notebook's workplanes in the viewport: a small labelled patch per workplane variable, at the frame the kernel reported
 * (the active one in blue).  Display only: the frames come from the runtime, nothing is computed from the model here. */
export function WorkplanePatches({ view, workplanes, active }: { view: SceneView; workplanes: readonly WorkplaneFrame[]; active: string | null }) {
  const layer = useSceneLayer(view, LAYER);
  const [half, setHalf] = useState(SIZE.fallback);

  useEffect(() => {
    const bounds = view.modelBoundsMm();
    setHalf(connectorSizeMm(bounds, SIZE));
  }, [view, workplanes]);

  useEffect(() => {
    if (!layer) return;
    layer.clear();
    for (const wp of workplanes) layer.add({ key: wp.name, object: patchObject(wp, half, wp.name === active) });
    layerHostFor(view).sync(true);
  }, [layer, workplanes, half, active, view]);

  return (
    <div className="pointer-events-none absolute inset-0 z-[5] overflow-hidden" data-testid="workplane-patches" data-workplanes={workplanes.map((wp) => wp.name).join(",")}>
      {layer &&
        workplanes.map((wp) => (
          <SceneLabel
            key={wp.name}
            view={view}
            getPoint={() => {
              const corner = patchCorners(wp, half)[3];
              return new THREE.Vector3(corner[0] / 1000, corner[1] / 1000, corner[2] / 1000);
            }}
            offset={[4, -16]}
            className={`rounded border px-1 font-mono text-[11px] font-bold ${wp.name === active ? "border-blue-500 bg-blue-50/90 text-blue-700" : "border-amber-500 bg-background/85 text-amber-700"}`}
          >
            <span data-workplane-label={wp.name}>{wp.name}</span>
          </SceneLabel>
        ))}
    </div>
  );
}
