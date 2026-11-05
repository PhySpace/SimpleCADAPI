import { useEffect, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";

import { t } from "@/i18n";
import { cn } from "@/lib/utils";
import { GIZMO_MARGIN, GIZMO_SIDE, type GizmoHandle } from "@/scene/renderer/brep-renderer";
import type { SceneView } from "@/scene/scene-view";

const PROJECTION_KEY = "sca.view.orthographic";

function rememberedOrthographic(): boolean {
  try {
    return window.localStorage.getItem(PROJECTION_KEY) === "1";
  } catch {
    return false;
  }
}

const ARROW = "absolute flex size-3.5 items-center justify-center text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground focus-visible:opacity-100";

/** The axis gizmo's controls, over the square the renderer draws it in: a click on an end of an axis looks from that
 * side, the arrows at its edges turn the view by 45° about the screen's axes, and the button beside it switches between
 * perspective and parallel (orthographic) projection; the choice is remembered in this browser. */
export function ViewGizmo({ view, sketching }: { view: SceneView; sketching: boolean }) {
  const [orthographic, setOrthographic] = useState(rememberedOrthographic);
  // the end of an axis under the pointer: it wins over an arrow drawn on top of it
  const [handle, setHandle] = useState<GizmoHandle | null>(null);

  useEffect(() => {
    view.engine.preferProjection(orthographic, !view.rig.manual);
    try {
      window.localStorage.setItem(PROJECTION_KEY, orthographic ? "1" : "0");
    } catch {
      // storage blocked: the choice lasts until the page reloads
    }
  }, [view, orthographic]);

  const handleAt = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return view.engine.gizmoHandleAt(event.clientX - box.left, event.clientY - box.top);
  };
  const arrow = (place: string) => cn(ARROW, place, handle && "pointer-events-none group-hover:opacity-0");
  const turn = (about: "yaw" | "pitch", sign: 1 | -1) => (event: React.MouseEvent) => {
    event.stopPropagation();
    void view.rig.step(about, sign);
  };

  return (
    <>
      <div
        className="group absolute"
        style={{ right: GIZMO_MARGIN, top: GIZMO_MARGIN, width: GIZMO_SIDE, height: GIZMO_SIDE, cursor: handle ? "pointer" : "default" }}
        data-testid="view-gizmo"
        onPointerMove={(event) => {
          const under = handleAt(event);
          view.engine.setGizmoHover(under);
          setHandle(under);
        }}
        onPointerLeave={() => {
          view.engine.setGizmoHover(null);
          setHandle(null);
        }}
        onClick={(event) => {
          const under = handleAt(event);
          if (under) void view.rig.lookFrom(under);
        }}
      >
        <button type="button" className={arrow("left-1/2 top-0 -translate-x-1/2")} title={t("Turn the view up 45°")} aria-label={t("Turn the view up 45°")} onClick={turn("pitch", 1)}>
          <ChevronUp className="size-3.5" />
        </button>
        <button type="button" className={arrow("bottom-0 left-1/2 -translate-x-1/2")} title={t("Turn the view down 45°")} aria-label={t("Turn the view down 45°")} onClick={turn("pitch", -1)}>
          <ChevronDown className="size-3.5" />
        </button>
        <button type="button" className={arrow("left-0 top-1/2 -translate-y-1/2")} title={t("Turn the view left 45°")} aria-label={t("Turn the view left 45°")} onClick={turn("yaw", -1)}>
          <ChevronLeft className="size-3.5" />
        </button>
        <button type="button" className={arrow("right-0 top-1/2 -translate-y-1/2")} title={t("Turn the view right 45°")} aria-label={t("Turn the view right 45°")} onClick={turn("yaw", 1)}>
          <ChevronRight className="size-3.5" />
        </button>
      </div>
      {!sketching && (
        <button
          type="button"
          className="absolute border-2 border-primary bg-popover/95 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] shadow-[2px_2px_0_var(--shadow-hard)] hover:bg-accent"
          style={{ right: GIZMO_MARGIN + GIZMO_SIDE + 4, top: GIZMO_MARGIN }}
          data-testid="projection-toggle"
          aria-pressed={orthographic}
          title={orthographic ? t("Parallel projection: click for perspective") : t("Perspective: click for parallel projection")}
          onClick={() => setOrthographic((value) => !value)}
        >
          {orthographic ? t("ortho") : t("persp")}
        </button>
      )}
    </>
  );
}
