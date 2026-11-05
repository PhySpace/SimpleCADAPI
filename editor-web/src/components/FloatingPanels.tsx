import { useState, type ReactNode } from "react";
import { ChevronsRight, ScanSearch } from "lucide-react";

import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** Whether a card is open, remembered in this browser (a convenience: it reads as open when storage is unavailable). */
function useRemembered(key: string): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem(key) !== "closed";
    } catch {
      return true;
    }
  });
  return [
    open,
    (next) => {
      setOpen(next);
      try {
        window.localStorage.setItem(key, next ? "open" : "closed");
      } catch {
        // storage blocked: the choice lasts until the page reloads
      }
    },
  ];
}

const CARD = "pointer-events-auto border-2 border-primary bg-popover/95 shadow-[4px_4px_0_var(--shadow-hard)] backdrop-blur-sm";
const PILL = "pointer-events-auto flex items-center gap-1.5 border-2 border-primary bg-popover/95 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] shadow-[4px_4px_0_var(--shadow-hard)] hover:bg-accent";

/** What floats over the viewport in both modes (the panels are the left column):
 *
 * - right, under the axis gizmo: the inspector of the selection, collapsible, with the partial-model notice under it;
 * - top centre: the selection kinds and "fit" (a command bar docked at the top sits under them);
 * - top left: the notice of split tags. */
export function FloatingPanels({
  inspector,
  chips,
  selectionCount,
  task,
  locked,
  leftNotice,
  rightNotice,
}: {
  inspector: ReactNode;
  chips: ReactNode;
  selectionCount: number;
  task: boolean;
  locked: boolean;
  leftNotice: ReactNode;
  rightNotice: ReactNode;
}) {
  const [inspectorOpen, setInspectorOpen] = useRemembered("sca.floating.inspector");
  return (
    <div inert={locked} className={cn("pointer-events-none absolute inset-0 z-[5]", locked && "opacity-40")} data-testid="floating-panels">
      {!task && leftNotice && <div className="pointer-events-none absolute left-2 top-14 flex w-[min(420px,45%)] flex-col">{leftNotice}</div>}
      <div className="pointer-events-none absolute bottom-16 right-2 top-[132px] flex w-[min(300px,34%)] flex-col items-end gap-2">
        {inspectorOpen ? (
          <div className={cn(CARD, "relative flex max-h-[70%] w-full flex-col overflow-hidden")} data-testid="floating-inspector">
            <div className="min-h-0 overflow-y-auto">{inspector}</div>
            <button
              type="button"
              className="absolute right-0 top-0 z-10 flex h-9 w-8 items-center justify-center border-l-2 border-border bg-popover text-muted-foreground hover:text-foreground"
              aria-label={t("Collapse the inspector")}
              title={t("Collapse the inspector")}
              onClick={() => setInspectorOpen(false)}
            >
              <ChevronsRight className="size-3.5" />
            </button>
          </div>
        ) : (
          <button type="button" className={PILL} onClick={() => setInspectorOpen(true)} aria-label={t("Open the inspector")}>
            <ScanSearch className="size-3.5" />
            {t("inspector")}{selectionCount > 0 ? ` · ${selectionCount}` : ""}
          </button>
        )}
        {rightNotice && <div className="w-full">{rightNotice}</div>}
      </div>
      {!task && (
        <div className={cn(CARD, "scroll-row absolute left-1/2 top-2 max-w-[calc(100%-1rem)] -translate-x-1/2 items-center gap-1 px-1 py-1")} data-testid="selection-kinds">
          {chips}
        </div>
      )}
    </div>
  );
}
