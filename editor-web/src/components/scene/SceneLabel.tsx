import { useEffect, useRef, type ReactNode } from "react";
import * as THREE from "three";

import { layerHostFor, type LayerViewLike } from "@/scene/layers/layer-host";
import { projectPoint } from "./project";

/** An HTML label anchored to a 3D point (dimension values, sketch names, connector names, ...).
 *
 * CONTRACT
 *  - Render it inside an overlay element that is `position: relative|absolute` and covers the 3D canvas exactly.
 *  - `getPoint` returns the anchor in WORLD space (scene units: metres, CAD frame) or null to hide the label.  It is
 *    re-evaluated on every camera or anchor change (layer host `subscribe`); the label's position is written straight to
 *    the DOM, so a camera drag does not re-render React.
 *  - Only the anchor POINT is projected (valid under perspective); the label is hidden when the point is behind the
 *    camera, clipped by the far plane, or off the canvas.
 *  - The element is `pointer-events: none`; give `className` for the look.  `offset` moves it in pixels from the point. */
export function SceneLabel({
  view,
  getPoint,
  children,
  className,
  offset = [10, -10],
}: {
  view: LayerViewLike;
  getPoint: () => THREE.Vector3 | null;
  children: ReactNode;
  className?: string;
  offset?: [number, number];
}) {
  const element = useRef<HTMLDivElement>(null);
  const pointRef = useRef(getPoint);
  const offsetRef = useRef(offset);
  useEffect(() => {
    pointRef.current = getPoint;
    offsetRef.current = offset;
  });

  useEffect(() => {
    const update = () => {
      const el = element.current;
      if (!el) return;
      const point = pointRef.current();
      const { camera, domElement } = view.engine;
      const screen = point ? projectPoint(point, camera, domElement.clientWidth, domElement.clientHeight, 8) : null;
      if (!screen || !screen.visible) {
        el.style.visibility = "hidden";
        return;
      }
      el.style.visibility = "visible";
      el.style.transform = `translate(${Math.round(screen.x + offsetRef.current[0])}px, ${Math.round(screen.y + offsetRef.current[1])}px)`;
    };
    return layerHostFor(view).subscribe(update);
  }, [view]);

  return (
    <div ref={element} className={className} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none", visibility: "hidden", whiteSpace: "nowrap" }}>
      {children}
    </div>
  );
}
