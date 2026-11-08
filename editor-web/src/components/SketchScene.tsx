import { useEffect, useMemo, useRef } from "react";

import type { SketchSolved } from "@/lib/useSketchShapes";
import type { SketchInfo } from "@/lib/sketch-scene";
import type { Vec3 } from "@/lib/sketch-plane";
import { SketchLayer, type LayerSketch } from "@/scene/sketch-layer";
import type { SceneView } from "@/scene/scene-view";

/** The notebook's sketches drawn in the 3D scene (see scene/sketch-layer.ts), and the hover of the sketch under the pointer.
 * It draws nothing itself: it feeds the layer the solved shapes and the state (hidden, selected, hovered, being edited). */
export function SketchScene({
  viewRef,
  infos,
  shapes,
  hidden,
  editing,
  selected,
  hover,
  arrow,
  theme,
  hoverEnabled,
  onHover,
}: {
  viewRef: React.MutableRefObject<SceneView | null>;
  infos: readonly SketchInfo[];
  shapes: ReadonlyMap<string, SketchSolved>;
  hidden: ReadonlySet<string>;
  /** The slug or name of the sketch being edited in sketch mode (not drawn here). */
  editing: string | null;
  selected: readonly string[];
  hover: string | null;
  arrow: { sketch: string; direction: Vec3; distance: number } | null;
  theme: string;
  /** Sketch picking is on (the sketch selection mode, or a dialog asks for one): the pointer hovers sketches. */
  hoverEnabled: boolean;
  onHover: (name: string | null) => void;
}) {
  const layerRef = useRef<SketchLayer | null>(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  // The layer lives as long as the view; the page's theme sets its ink.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const layer = new SketchLayer(view.engine);
    layerRef.current = layer;
    view.sketchHitter = (event) => layer.hit(event.clientX, event.clientY);
    return () => {
      view.sketchHitter = null;
      layer.dispose();
      layerRef.current = null;
    };
  }, [viewRef]);

  useEffect(() => {
    // read after the page has switched its theme class
    const frame = requestAnimationFrame(() => {
      const style = getComputedStyle(document.documentElement);
      const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
      layerRef.current?.setInk({
        curve: read("--name", "#1a62c4"),
        construction: read("--muted-foreground", "#777777"),
        selected: read("--focus", "#d56a00"),
        hover: read("--focus", "#d56a00"),
        fail: read("--fail", "#d12b3c"),
        halo: read("--background", "#ffffff"),
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [theme]);

  const layerSketches = useMemo<LayerSketch[]>(
    () =>
      infos.flatMap((info) => {
        const solved = shapes.get(info.name);
        return solved ? [{ name: info.name, plane: info.doc.plane, shape: solved.shape, used: info.usedBy.length > 0 }] : [];
      }),
    [infos, shapes],
  );
  useEffect(() => layerRef.current?.setSketches(layerSketches), [layerSketches]);

  const editingName = useMemo(() => infos.find((info) => info.slug === editing || info.name === editing)?.name ?? null, [infos, editing]);
  const selectedKey = selected.join("\u0000");
  useEffect(() => {
    layerRef.current?.setState({ hidden, editing: editingName, selected: new Set(selected), hover, arrow });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hidden, editingName, selectedKey, hover, arrow, layerSketches]);

  // The pointer over a sketch (only while sketches are what a click picks).
  useEffect(() => {
    const view = viewRef.current;
    if (!view || !hoverEnabled) return;
    const element = view.engine.domElement;
    let frame = 0;
    let last: PointerEvent | null = null;
    const run = () => {
      frame = 0;
      if (last) hoverRef.current(layerRef.current?.hit(last.clientX, last.clientY) ?? null);
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
  }, [viewRef, hoverEnabled]);

  return null;
}
