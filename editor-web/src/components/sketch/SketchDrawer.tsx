import { ChevronsLeft, ChevronsRight, Trash2 } from "lucide-react";
import { useState } from "react";

import { Switch } from "@/components/ui/switch";
import { CONSTRAINT_INFO, dimensionValue, formatValue, isDimensional, removeConstraint } from "@/lib/sketch";
import type { SketchEditor } from "@/lib/useSketchEditor";
import { cn } from "@/lib/utils";
import { CONSTRAINT_SHORT } from "@/components/sketch/sketch-ui";

export function StatusBadge({ editor, compact = false }: { editor: SketchEditor; compact?: boolean }) {
  const { badge, result } = editor;
  const label = compact && badge.label.startsWith("under-constrained") ? `${result?.dof ?? "?"} dof` : badge.label;
  return (
    <span
      data-testid="sketch-status"
      className={cn(
        "whitespace-nowrap border-2 bg-popover px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.1em]",
        badge.tone === "pass" && "border-pass text-pass",
        badge.tone === "fail" && "border-fail text-fail",
        badge.tone === "focus" && "border-focus text-focus",
        badge.tone === "muted" && "border-input text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

const HEAD = "border-y-2 border-border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em]";

/** The collapsible drawer on the right of the viewport: status, the require-fully-constrained switch, the constraint
 * list (delete, driving/reference), the diagnostics and the profile. */
export function SketchDrawer({ editor, plane, wide }: { editor: SketchEditor; plane: string; wide: boolean }) {
  // Open by default only when the viewport is wide enough to leave room for the sketch; the person's choice wins.
  const [chosen, setOpen] = useState<boolean | null>(null);
  const open = chosen ?? wide;
  const { doc, result, error, blamed, highlight, loops } = editor;
  if (!open) {
    return (
      <div className="pointer-events-auto absolute right-2 top-2 z-20 flex items-center gap-1">
        <button type="button" aria-label="Open the sketch drawer" title="Show constraints and diagnostics" onClick={() => setOpen(true)} className="flex size-7 items-center justify-center border-2 border-primary bg-popover hover:bg-accent">
          <ChevronsLeft className="size-3.5" />
        </button>
      </div>
    );
  }
  return (
    <aside className="pointer-events-auto absolute bottom-10 right-2 top-14 z-20 flex w-56 flex-col overflow-hidden border-2 border-primary bg-popover shadow-[4px_4px_0_var(--shadow-hard)]" aria-label="Sketch drawer">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <StatusBadge editor={editor} />
        <span className="flex-1 truncate text-[10px] uppercase tracking-[0.08em] text-muted-foreground" title="The sketch plane">on {plane}</span>
        <button type="button" aria-label="Collapse the sketch drawer" title="Collapse" onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground">
          <ChevronsRight className="size-3.5" />
        </button>
      </div>
      <label className="flex items-center gap-1.5 px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        require fully constrained
        <Switch checked={doc.fully_constrained} onCheckedChange={(v) => editor.commit({ ...doc, fully_constrained: v })} aria-label="Require fully constrained" />
      </label>
      {doc.fully_constrained && !editor.solved && result && <div className="px-2 pb-1 text-[10px] uppercase tracking-[0.08em] text-fail">needs dof 0 to finish</div>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={HEAD}>constraints ({doc.constraints.length})</div>
        <ul data-testid="constraint-list">
          {doc.constraints.length === 0 && <li className="px-2 py-1.5 text-[11px] text-muted-foreground">Select geometry, then pick a constraint on the left.</li>}
          {doc.constraints.map((c) => (
            <li
              key={c.id}
              data-constraint={c.id}
              onClick={() => editor.setHighlight((h) => (h === c.id ? null : c.id))}
              className={cn("flex cursor-pointer items-center gap-1 border-b border-border px-2 py-1 text-[11px]", highlight === c.id && "bg-accent", blamed.has(c.id) && "text-fail")}
            >
              <span className="min-w-0 flex-1 truncate" title={CONSTRAINT_INFO[c.kind].label}>
                <b className="uppercase">{CONSTRAINT_SHORT[c.kind]}</b> <span className="text-muted-foreground">{c.targets.join(", ")}</span>
                {isDimensional(c.kind) && <span className="text-name"> {formatValue(dimensionValue(c, doc, result), c.kind)}</span>}
              </span>
              {isDimensional(c.kind) && (
                <button
                  type="button"
                  title={c.driving === false ? "Reference dimension: click to make it driving" : "Driving dimension: click to make it a reference"}
                  onClick={(e) => {
                    e.stopPropagation();
                    editor.commit({ ...doc, constraints: doc.constraints.map((k) => (k.id === c.id ? { ...k, driving: k.driving === false } : k)) });
                  }}
                  className="border border-input px-1 text-[9px] font-bold uppercase hover:border-primary"
                >
                  {c.driving === false ? "ref" : "drv"}
                </button>
              )}
              <button
                type="button"
                aria-label={`Delete ${c.id}`}
                title="Delete constraint"
                onClick={(e) => {
                  e.stopPropagation();
                  editor.commit(removeConstraint(doc, c.id));
                }}
                className="text-muted-foreground hover:text-fail"
              >
                <Trash2 className="size-3" />
              </button>
            </li>
          ))}
        </ul>
        <div className={HEAD}>diagnostics</div>
        <ul data-testid="diagnostics">
          {editor.diagnostics.length === 0 && <li className="px-2 py-1.5 text-[11px] text-muted-foreground">{error ?? "none"}</li>}
          {editor.diagnostics.map((d, i) => (
            <li
              key={i}
              onClick={() => d.constraint_id && editor.setHighlight(d.constraint_id)}
              className={cn("border-b border-border px-2 py-1 text-[11px]", d.severity === "error" ? "text-fail" : "text-muted-foreground", d.constraint_id && "cursor-pointer")}
            >
              {d.constraint_id && <b>{d.constraint_id} </b>}
              {d.message}
            </li>
          ))}
        </ul>
        <div className={HEAD}>profile</div>
        <div className="px-2 py-1.5 text-[11px] text-muted-foreground" data-testid="profile-info">
          {loops.length === 0 ? (
            "Close a loop of lines, or draw a circle."
          ) : (
            <>
              {loops.length} loop{loops.length === 1 ? "" : "s"}; outer <span className="text-focus">{doc.profile}</span>
              {doc.inner.length > 0 && (
                <>
                  , holes <span className="text-name">{doc.inner.join(", ")}</span>
                </>
              )}
              . Click a loop for the outer profile; shift-click toggles a hole.
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
