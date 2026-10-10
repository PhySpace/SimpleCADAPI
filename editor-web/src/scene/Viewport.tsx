import { useEffect, useRef } from "react";
import * as THREE from "three";

import { SceneView, type PickResult, type SelectionMode } from "@/scene/scene-view";

export type { PickResult, SelectionMode };

const SELECTION_COLOR = "#4ade80";

// Module-load marker: distinguishes "stale bundle served" from "effect not
// running" when debugging the imperative scene handle from the console.
if (typeof window !== "undefined") {
  (window as unknown as { __studioViewportLoaded?: boolean }).__studioViewportLoaded = true;
  document.documentElement.dataset.viewportLoaded = "1";
}

/** Mounts the three.js SceneView once; owns the selection highlight and
 * bridges picks to React.
 *
 * The parent owns the SceneView instance (imperative scene loading does not
 * map to React state); this component guarantees mount/dispose, draws the
 * entity highlight for the current pick, and forwards picks after publishing
 * them to the agent-facing selection API.
 */
export function Viewport({
  viewRef,
  selectionMode,
  onPick,
}: {
  viewRef: React.MutableRefObject<SceneView | null>;
  selectionMode: SelectionMode;
  onPick: (pick: PickResult) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  // The highlight overlays attach themselves into the scene graph; keep the
  // handles so the previous highlight can be removed on the next pick.
  const overlayRef = useRef<THREE.Object3D[]>([]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const view = new SceneView(host, {
      onPick: (result) => {
        // Swap the highlight: dispose the previous overlays, build fresh ones.
        for (const object of overlayRef.current) {
          object.parent?.remove(object);
          object.traverse((child) => {
            const mesh = child as THREE.Mesh;
            mesh.geometry?.dispose?.();
            const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
            if (Array.isArray(material)) material.forEach((item) => item.dispose());
            else material?.dispose?.();
          });
        }
        overlayRef.current = result.entityId
          ? view.buildEntityOverlays(result.nodeId, result.entityId, SELECTION_COLOR, 0.8)
          : [];
        // Main-world telemetry mirror: debug probes may run in an isolated
        // JS world, so expose pick/overlay state through the DOM instead.
        document.documentElement.dataset.pickedEntity = result.entityId ?? "";
        document.documentElement.dataset.overlayCount = String(overlayRef.current.length);
        pickRef.current(result);
      },
      selectionMode: "solid",
    });
    viewRef.current = view;
    // Debug/agent affordance: reach the imperative scene from the console.
    (window as unknown as { __studioView?: SceneView }).__studioView = view;
    // The renderer self-observes host resizes; nothing to wire here.
    return () => {
      for (const object of overlayRef.current) object.parent?.remove(object);
      overlayRef.current = [];
      view.dispose();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    viewRef.current?.setSelectionMode(selectionMode);
  }, [selectionMode, viewRef]);

  return <div ref={hostRef} className="h-full w-full" />;
}
