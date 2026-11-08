import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A banner at the top of a viewport saying what to do next (a title, a hint line) with room for controls and a message
 * of refusal under it.  Presentational: the mode that shows it owns what it says. */
export function HintBanner({
  icon,
  title,
  hint,
  controls,
  notice,
  testId,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  hint?: ReactNode;
  controls?: ReactNode;
  notice?: string | null;
  testId?: string;
  className?: string;
}) {
  return (
    <div className={cn("pointer-events-none absolute left-1/2 top-3 z-30 flex max-w-[96%] -translate-x-1/2 flex-col items-center gap-1", className)} data-testid={testId}>
      <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-3 border-2 border-primary bg-popover px-3 py-1.5 shadow-[4px_4px_0_var(--shadow-hard)]">
        {icon}
        <span className="flex flex-col leading-tight">
          <span className="whitespace-nowrap text-[12px] font-semibold">{title}</span>
          {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
        </span>
        {controls}
      </div>
      {notice && (
        <div role="alert" className="border-2 border-fail bg-popover px-3 py-1 text-[11px] text-fail">
          {notice}
        </div>
      )}
    </div>
  );
}
