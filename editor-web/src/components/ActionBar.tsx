import type { LucideIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { enterRunsFirst, placeBar, type Size } from "@/lib/action-bar";
import { cn } from "@/lib/utils";

export type BarAction = {
  id: string;
  label: string;
  icon?: LucideIcon;
  /** Shown as the tooltip. */
  hint?: string;
  /** Why the action cannot be used right now (it stays visible, greyed, with the reason). */
  disabled?: string | null;
  run: () => void;
};

/** A small floating bar of actions hung near a point of its container (what is selected), the way CAD packages show the
 * operations that fit the selection.  The first action also answers Enter while the bar is shown (`enter`), so the most
 * common next step is one key.  `anchor` is in the container's pixels (null docks the bar at the top centre).
 * `notice` is a one-line message under the bar (a refusal, for instance). */
export function ActionBar({
  actions,
  anchor,
  bounds,
  title,
  notice,
  enter = true,
  className,
}: {
  actions: readonly BarAction[];
  anchor: readonly [number, number] | null;
  bounds: Size;
  title?: string;
  notice?: string | null;
  enter?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ w: 260, h: 34 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && (Math.abs(el.offsetWidth - size.w) > 1 || Math.abs(el.offsetHeight - size.h) > 1)) setSize({ w: el.offsetWidth, h: el.offsetHeight });
  });

  // Clicking an action that cannot run says why, under the bar, until the actions change.
  const [why, setWhy] = useState<{ id: string; text: string } | null>(null);
  const signature = actions.map((action) => `${action.id}:${action.disabled ?? ""}`).join("|");
  useEffect(() => setWhy(null), [signature]);

  const first = actions.find((action) => !action.disabled);
  const firstRef = useRef(first);
  firstRef.current = first;
  useEffect(() => {
    if (!enter || actions.length === 0) return;
    const onKey = (event: KeyboardEvent) => {
      if (!enterRunsFirst(event)) return;
      const action = firstRef.current;
      if (!action) return;
      event.preventDefault();
      action.run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enter, actions.length]);

  if (actions.length === 0) return null;
  const at = placeBar(anchor, size, bounds);
  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label={title ?? "Actions for the selection"}
      data-testid="action-bar"
      data-docked={at.docked}
      className={cn("pointer-events-auto absolute z-20 flex max-w-[92%] flex-col gap-1", className)}
      style={{ left: at.x, top: at.y }}
    >
      <div className="flex flex-wrap items-center gap-1 border-2 border-primary bg-popover p-1 shadow-[4px_4px_0_var(--shadow-hard)]">
        {title && <span className="px-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</span>}
        {actions.map((action) => {
          const Icon = action.icon;
          const isFirst = action === first;
          return (
            <Button
              key={action.id}
              type="button"
              size="sm"
              variant={isFirst ? "default" : "outline"}
              className="h-7 px-2"
              data-action={action.id}
              aria-disabled={Boolean(action.disabled)}
              title={action.disabled ?? action.hint ?? action.label}
              onClick={() => (action.disabled ? setWhy({ id: action.id, text: action.disabled }) : action.run())}
              style={action.disabled ? { opacity: 0.45 } : undefined}
            >
              {Icon && <Icon />}
              {action.label}
              {isFirst && enter && <kbd className="ml-0.5 border border-current px-1 text-[9px] opacity-70">enter</kbd>}
            </Button>
          );
        })}
      </div>
      {(notice ?? why?.text) && (
        <p role="alert" data-testid="action-bar-notice" className="border-2 border-fail bg-popover px-2 py-1 text-[11px] text-fail">
          {notice ?? why?.text}
        </p>
      )}
    </div>
  );
}
