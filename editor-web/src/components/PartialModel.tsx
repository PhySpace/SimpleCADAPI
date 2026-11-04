import { useMemo } from "react";
import { TriangleAlert } from "lucide-react";

import { describePartial, type PartialModel } from "@/lib/partial";

/** Says that the model in the viewport is the one before a failing step (a cell failed, so the product was not made): which
 * step failed and why, and that the steps after it did not run.  It stays while the model is partial and goes when the
 * whole model replaces it; the failing step is marked in the feature tree as well. */
export function PartialNotice({ partial, titles }: { partial: PartialModel; titles: ReadonlyMap<string, string> }) {
  const { title, reason, after } = useMemo(() => describePartial(partial, titles), [partial, titles]);
  const full = partial.failed.map((cell) => cell.error).filter(Boolean).join("\n");
  return (
    <div
      role="status"
      className="pointer-events-auto absolute right-3 top-3 z-20 flex max-w-[min(380px,60%)] flex-col gap-0.5 border-2 border-fail bg-popover px-3 py-1.5 text-[11px] shadow-[4px_4px_0_var(--shadow-hard)]"
      data-testid="partial-model"
      title={full || undefined}
    >
      <div className="flex items-center gap-2 font-semibold">
        <TriangleAlert className="size-3.5 shrink-0 text-fail" />
        <span>{title}</span>
      </div>
      <span className="line-clamp-2 text-fail">{reason}</span>
      <span className="text-muted-foreground">{after ? `${after}; the` : "The"} whole model comes back once it is fixed.</span>
    </div>
  );
}
