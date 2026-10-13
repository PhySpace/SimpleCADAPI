import { useEffect, useRef } from "react";
import * as THREE from "three";

import { SceneView, type PickResult, type SelectionMode } from "@/scene/scene-view";
import { PALETTES, type SceneTheme } from "@/scene/theme";

export type { PickResult, SelectionMode };


/** What the viewport highlights: the picked entities. */
export type Highlight = { nodeId: string; entityId: string | null };

/** Mounts the three.js SceneView once and draws the selection highlight.
 *
 * The parent owns the SceneView instance (imperative scene loading does not
 * map to React state) and the selection; this component guarantees
 * mount/dispose and keeps the highlight overlays in step with `selection`.
 * `sceneVersion` changes whenever a scene was (re)loaded, which discards the
 * old overlays with the old geometry.
 */
export function Viewport({
  viewRef,
  selectionMode,
  selection,
  sceneVersion,
  theme,
  onPick,
  onClear,
}: {
  viewRef: React.MutableRefObject<SceneView | null>;
  selectionMode: SelectionMode;
  selection: Highlight[];
  sceneVersion: number;
  theme: SceneTheme;
  onPick: (pick: PickResult) => void;
  onClear: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const clearRef = useRef(onClear);
  clearRef.current = onClear;
  const overlayRef = useRef<THREE.Object3D[]>([]);
  // The theme the view was created with; later changes go through setTheme.
  const themeRef = useRef(theme);
  themeRef.current = theme;

  const dropOverlays = () => {
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
    overlayRef.current = [];
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const view = new SceneView(host, {
      onPick: (result) => pickRef.current(result),
      onClear: () => clearRef.current(),
      selectionMode: "solid",
      theme: themeRef.current,
    });
    viewRef.current = view;
    // Debug/agent affordance: reach the imperative scene from the console.
    (window as unknown as { __studioView?: SceneView }).__studioView = view;
    return () => {
      dropOverlays();
      view.dispose();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    viewRef.current?.setSelectionMode(selectionMode);
  }, [selectionMode, viewRef]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    dropOverlays();
    for (const item of selection) {
      overlayRef.current.push(...view.buildEntityOverlays(item.nodeId, item.entityId, PALETTES[theme].selection, 0.8));
    }
    view.engine.invalidate();
    document.documentElement.dataset.overlayCount = String(overlayRef.current.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, sceneVersion, theme]);

  // Another theme: recolor in place (camera, model and selection stay).
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.setTheme(theme);
    view.engine.invalidate();
  }, [theme, viewRef]);

  return <div ref={hostRef} className="h-full w-full" />;
}
