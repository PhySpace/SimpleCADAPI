import { Construction, Layers, Maximize, Magnet, Undo2, Redo2, ScanLine, Spline, WandSparkles } from "lucide-react";

import { CONSTRAINT_INFO, isDimensional } from "@/lib/sketch";
import type { SketchEditor } from "@/lib/useSketchEditor";
import { cn } from "@/lib/utils";
import { CONSTRAINT_SHORT, TOOLBAR_ORDER, TOOLS } from "@/components/sketch/sketch-ui";

function Tip({ children }: { children: React.ReactNode }) {
  return <span className="text-[9px] font-bold leading-none text-muted-foreground group-aria-pressed:text-primary-foreground">{children}</span>;
}

/** The floating toolbar on the left edge of the viewport: the drawing tools, the toggles and the constraints
 * (the constraint buttons enable per selection). */
export function SketchToolbar({ editor, onFit, onNormal }: { editor: SketchEditor; onFit: () => void; onNormal: () => void }) {
  const { tool, applicable } = editor;
  const toggle = "group flex h-7 items-center gap-1.5 border-b border-border px-1.5 text-left text-[10px] aria-pressed:bg-primary aria-pressed:text-primary-foreground hover:bg-accent aria-pressed:hover:bg-primary";
  return (
    <div className="pointer-events-auto absolute bottom-10 left-2 top-14 z-20 flex w-[92px] flex-col overflow-y-auto [&>*]:shrink-0 border-2 border-primary bg-popover shadow-[4px_4px_0_var(--shadow-hard)]" role="toolbar" aria-label="Sketch tools">
      {TOOLS.map((t) => {
        // Trim and extend wait for a draft in progress to be finished or cancelled.
        const blocked = (t.id === "trim" || t.id === "extend" || t.id === "fillet" || t.id === "chamfer") && editor.draft !== null;
        return (
        <button key={t.id} type="button" title={blocked ? `${t.label}: finish or cancel the draft first` : `${t.label} (${t.key})`} aria-label={t.label} aria-pressed={tool === t.id} aria-disabled={blocked} disabled={blocked} data-tool={t.id} onClick={() => editor.chooseTool(t.id)} className={cn(toggle, "disabled:opacity-40")}>
          <t.icon className="size-3.5 shrink-0" />
          <span className="flex-1 truncate">{t.id}</span>
          <Tip>{t.key}</Tip>
        </button>
        );
      })}
      <button type="button" title="Project: bring another sketch of this notebook in as fixed reference geometry (J)" aria-label="Project" aria-pressed={editor.projectOpen} data-tool="project" onClick={editor.openProject} className={cn(toggle, "border-t-2")}>
        <Layers className="size-3.5 shrink-0" />
        <span className="flex-1">project</span>
        <Tip>J</Tip>
      </button>
      <button type="button" title="Anchor mode (Shift+A, with a B-spline picked): a click on its curve adds an anchor, a click on an inner anchor removes it (SDK insert/remove_spline_anchor_rsketch); Esc leaves" aria-label="Anchor mode" aria-pressed={editor.anchorMode !== null} data-tool="anchors" onClick={editor.toggleAnchorMode} className={toggle}>
        <Spline className="size-3.5 shrink-0" />
        <span className="flex-1">anchors</span>
        <Tip>⇧A</Tip>
      </button>
      <button type="button" title="Construction geometry (X): toggles the selected lines, or what you draw next" aria-label="Construction" aria-pressed={editor.construction} onClick={editor.toggleConstruction} className={toggle}>
        <Construction className="size-3.5 shrink-0" />
        <span className="flex-1">construct</span>
        <Tip>X</Tip>
      </button>
      <button type="button" title="Auto constraints: near-horizontal and vertical lines are constrained as you draw" aria-label="Auto constraints" aria-pressed={editor.auto} onClick={() => editor.setAuto((v) => !v)} className={toggle}>
        <WandSparkles className="size-3.5 shrink-0" />
        <span className="flex-1">auto h/v</span>
      </button>
      <button type="button" title="Snap to grid, points and the model's vertices (hold Alt to skip once)" aria-label="Snap" aria-pressed={editor.snapOn} onClick={() => editor.setSnapOn((v) => !v)} className={toggle}>
        <Magnet className="size-3.5 shrink-0" />
        <span className="flex-1">snap</span>
      </button>
      <button type="button" title="Turn the view to look straight at the plane (N)" aria-label="Normal to" onClick={onNormal} className={cn(toggle, "border-t-2")}>
        <ScanLine className="size-3.5 shrink-0" />
        <span className="flex-1">normal to</span>
        <Tip>N</Tip>
      </button>
      <button type="button" title="Fit the sketch in the view (F)" aria-label="Fit" onClick={onFit} className={toggle}>
        <Maximize className="size-3.5 shrink-0" />
        <span className="flex-1">fit</span>
        <Tip>F</Tip>
      </button>
      <div className="flex border-b border-border">
        <button type="button" title="Undo the last sketch edit (Ctrl/Cmd+Z)" aria-label="Undo" disabled={editor.edits === 0} onClick={editor.undo} className="flex h-7 flex-1 items-center justify-center hover:bg-accent disabled:opacity-40">
          <Undo2 className="size-3.5" />
        </button>
        <button type="button" title="Redo (Ctrl/Cmd+Shift+Z)" aria-label="Redo" onClick={editor.redo} className="flex h-7 flex-1 items-center justify-center border-l border-border hover:bg-accent">
          <Redo2 className="size-3.5" />
        </button>
      </div>
      <div className="border-b-2 border-border px-2 py-1 text-[9px] font-bold uppercase tracking-[0.12em] text-muted-foreground">constraints</div>
      <div className="grid grid-cols-2 gap-px bg-border p-px" aria-label="Constraints">
        {TOOLBAR_ORDER.map((kind) => {
          const on = applicable.has(kind);
          return (
            <button
              key={kind}
              type="button"
              disabled={!on}
              data-constraint-kind={kind}
              title={`${CONSTRAINT_INFO[kind].label}${isDimensional(kind) ? " (opens a value box)" : ""}`}
              onClick={() => editor.applyConstraint(kind)}
              className={cn(
                "h-6 bg-popover px-0.5 text-[8.5px] font-semibold uppercase tracking-[0.02em] transition-colors",
                on ? "hover:bg-focus hover:text-primary-foreground" : "text-muted-foreground opacity-40",
                isDimensional(kind) && on && "text-name",
              )}
            >
              {CONSTRAINT_SHORT[kind]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
