import { useEffect, useRef } from "react";
import { Check, SlidersHorizontal, X } from "lucide-react";

import { ParamControl, type ParamMeta, type ParamValue } from "@/components/ParamControl";
import { useViewer } from "@/components/sketch/SketchOverlay";
import { t } from "@/i18n";
import type { Vec3 } from "@/lib/sketch-plane";
import { worldToScreen } from "@/lib/sketch-view";
import type { SceneView } from "@/scene/scene-view";

/** The numbers of an operation in progress, floating by what it works on (see lib/operation-session.ts): every change
 * rebuilds the model at once, a failure shows here, Enter keeps the feature and Esc takes it back. */
export function OperationPanel({
  view,
  anchorMm,
  title,
  params,
  error,
  busy,
  editing,
  onParam,
  onConfirm,
  onCancel,
  onMore,
}: {
  view: SceneView;
  /** Where the panel hangs (mm, world): the selection the operation was started on; null: the top of the viewport. */
  anchorMm: Vec3 | null;
  title: string;
  params: readonly ParamMeta[];
  /** Why the feature does not build with these numbers (the model shows the step before it meanwhile). */
  error: string | null;
  busy: boolean;
  /** The feature existed before (Esc reverts its numbers instead of removing it). */
  editing: boolean;
  onParam: (id: string, value: ParamValue, now?: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  /** Every option of the operation, in its dialog. */
  onMore: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { viewer, size } = useViewer(view, host);
  const at = anchorMm ? worldToScreen(viewer, anchorMm) : null;
  const width = 260;
  const left = at ? Math.min(Math.max(8, at[0] + 24), Math.max(8, size.w - width - 8)) : Math.max(8, size.w / 2 - width / 2);
  const top = at ? Math.min(Math.max(56, at[1] - 20), Math.max(56, size.h - 220)) : 56;

  // Enter keeps, Esc takes back, wherever the focus is (a number box commits on Enter first).
  const keep = useRef(onConfirm);
  keep.current = onConfirm;
  const drop = useRef(onCancel);
  drop.current = onCancel;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        drop.current();
      } else if (event.key === "Enter" && !event.shiftKey && !(event.target instanceof Element && event.target.closest("textarea, .cm-editor"))) {
        event.preventDefault();
        // let a number box commit its value first
        window.setTimeout(() => keep.current(), 0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div ref={host} className="pointer-events-none absolute inset-0 z-20" data-testid="operation-session">
      <div
        role="dialog"
        aria-label={title}
        className="pointer-events-auto absolute flex flex-col gap-2 border-2 border-focus bg-popover p-2 text-[11px] shadow-[4px_4px_0_var(--shadow-hard)]"
        style={{ left, top, width }}
      >
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate font-semibold">{title}</span>
          <button type="button" className="text-muted-foreground hover:text-foreground" title={t("Every option (dialog)")} aria-label={t("Every option (dialog)")} onClick={onMore}>
            <SlidersHorizontal className="size-3.5" />
          </button>
        </div>
        {params.length ? (
          params.map((param) => <ParamControl key={param.id} param={param} forwardParam={onParam} editable />)
        ) : (
          <span className="text-muted-foreground">{busy ? t("adding…") : t("No numbers to tune: keep it, or open every option.")}</span>
        )}
        {error && (
          <p role="alert" className="line-clamp-3 border-l-2 border-fail pl-1.5 text-fail" title={error}>
            {error}
          </p>
        )}
        <div className="flex items-center gap-1.5">
          <button type="button" disabled={busy} className="flex flex-1 items-center justify-center gap-1 border-2 border-primary bg-primary px-2 py-0.5 font-semibold text-primary-foreground disabled:opacity-50" onClick={onConfirm}>
            <Check className="size-3.5" /> {t("OK")} <kbd className="opacity-70">↵</kbd>
          </button>
          <button type="button" className="flex flex-1 items-center justify-center gap-1 border-2 border-border px-2 py-0.5 hover:bg-accent" onClick={onCancel}>
            <X className="size-3.5" /> {editing ? t("Revert") : t("Cancel")} <kbd className="opacity-70">Esc</kbd>
          </button>
        </div>
      </div>
    </div>
  );
}
