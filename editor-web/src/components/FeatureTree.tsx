import { ArrowRight, Eye, EyeOff, Pencil, Redo2, Trash2, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { plainLabel } from "@/lib/commands";
import type { Catalog, FeatureRow, FeatureState, Spec } from "@/lib/features";
import type { SketchInfo } from "@/lib/sketch-scene";
import { cn } from "@/lib/utils";

/** Undo and redo with their counts. */
export function UndoRedo({ state, busy, onUndo, onRedo }: { state: Pick<FeatureState, "undo" | "redo">; busy?: boolean; onUndo: () => void; onRedo: () => void }) {
  return (
    <span className="flex items-center gap-1">
      <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={busy || state.undo === 0} title="Undo the last feature change (Ctrl/Cmd+Z)" onClick={onUndo}>
        <Undo2 /> undo {state.undo > 0 && <span className="text-muted-foreground">{state.undo}</span>}
      </Button>
      <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={busy || state.redo === 0} title="Redo (Ctrl/Cmd+Shift+Z)" onClick={onRedo}>
        <Redo2 /> redo {state.redo > 0 && <span className="text-muted-foreground">{state.redo}</span>}
      </Button>
    </span>
  );
}

function errorText(feature: FeatureRow): string | null {
  const first = feature.errors[0];
  if (first !== undefined) {
    const text =
      typeof first === "string"
        ? first
        : String((first as Record<string, unknown>).message ?? (first as Record<string, unknown>).error ?? JSON.stringify(first));
    // The SDK's errors lead with the operation and signature: the line that says what happened is the one to show.
    const what = text.split("\n").find((line) => line.startsWith("What happened:"));
    return (what ? what.replace("What happened:", "").trim() : text.split("\n")[0]).slice(0, 300);
  }
  return feature.status === "error" || feature.status === "exception" ? "this step failed" : null;
}

function statusColor(feature: FeatureRow): string {
  if (errorText(feature)) return "bg-fail";
  if (feature.status === "running" || feature.status === "queued") return "bg-focus";
  if (feature.status === "done" || feature.status === "ok" || feature.status === "idle") return "bg-pass";
  return "bg-muted-foreground";
}

/** The sketches of the notebook as the tree shows them: visibility (an eye), selection and the hover shared with the viewport. */
export type TreeSketches = {
  infos: readonly SketchInfo[];
  hidden: ReadonlySet<string>;
  selected: readonly string[];
  hover: string | null;
  onToggleHidden: (name: string) => void;
  onSelect: (name: string, additive: boolean) => void;
  onHover: (name: string | null) => void;
};

/** The features of the notebook in order, with edit, delete (arm, then click), and the product marker.
 * A sketch row has an eye (show or hide it in the viewport), selects on click and highlights with the viewport. */
export function FeatureTree({
  catalog,
  state,
  busy,
  error,
  onEdit,
  onDelete,
  onUseProduct,
  onUndo,
  onRedo,
  sketches,
}: {
  sketches?: TreeSketches;
  catalog: Catalog | null;
  state: FeatureState;
  busy: boolean;
  error: string | null;
  onEdit: (feature: FeatureRow, spec: Spec) => void;
  onDelete: (feature: FeatureRow) => void;
  onUseProduct: (body: string) => void;
  onUndo: () => void;
  onRedo: () => void;
}) {
  const [armed, setArmed] = useState<string | null>(null);
  const armTimer = useRef<number | null>(null);
  useEffect(() => () => void (armTimer.current !== null && window.clearTimeout(armTimer.current)), []);
  const arm = (cell: string) => {
    setArmed(cell);
    if (armTimer.current !== null) window.clearTimeout(armTimer.current);
    armTimer.current = window.setTimeout(() => setArmed(null), 3000);
  };

  const stale = state.product && state.tip && state.product.body !== state.tip ? state.product : null;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
        <span className="label">features {state.features.length > 0 && `(${state.features.length})`}</span>
        <UndoRedo state={state} busy={busy} onUndo={onUndo} onRedo={onRedo} />
      </div>
      {stale && state.tip && (
        <div className="flex items-center gap-2 border-b-2 border-focus bg-accent px-3 py-1.5 text-[11px]">
          <span className="min-w-0 flex-1">
            The product still builds from <span className="text-name">{stale.body}</span>.
          </span>
          <Button type="button" size="sm" className="h-6 px-2" disabled={busy} onClick={() => onUseProduct(state.tip as string)}>
            use {state.tip}
          </Button>
        </div>
      )}
      {error && <div className="border-b border-fail px-3 py-1 text-[11px] text-fail">{error}</div>}
      <ScrollArea className="min-h-0 flex-1">
        {state.features.length === 0 ? (
          <p className="px-3 py-3 text-[11px] text-muted-foreground">No features yet. Add a Box or another operation above; each one becomes an ordinary cell in the notebook.</p>
        ) : (
          <ul>
            {state.features.map((feature) => {
              const spec = feature.gui ? catalog?.specs.find((item) => item.id === feature.gui?.spec) : undefined;
              const problem = errorText(feature);
              const isProduct = state.product !== null && feature.makes.includes(state.product.body);
              const canEdit = Boolean(feature.gui && spec);
              const sketch = sketches?.infos.find((info) => info.cell === feature.cell);
              const hiddenSketch = sketch ? sketches?.hidden.has(sketch.name) : false;
              const selectedSketch = sketch ? sketches?.selected.includes(sketch.name) : false;
              const hoveredSketch = sketch ? sketches?.hover === sketch.name : false;
              return (
                <li
                  key={feature.cell}
                  data-sketch={sketch?.name}
                  data-selected={selectedSketch || undefined}
                  data-hover={hoveredSketch || undefined}
                  className={cn("border-b border-border px-3 py-2", sketch && "cursor-pointer", hoveredSketch && "bg-accent", selectedSketch && "border-l-4 border-l-focus bg-accent")}
                  onMouseEnter={sketch ? () => sketches?.onHover(sketch.name) : undefined}
                  onMouseLeave={sketch ? () => sketches?.onHover(null) : undefined}
                  onClick={sketch ? (event) => {
                    if ((event.target as HTMLElement).closest("button")) return;
                    sketches?.onSelect(sketch.name, event.ctrlKey || event.metaKey);
                  } : undefined}
                >
                  <div className="flex items-center gap-2">
                    <span className={cn("inline-block h-2 w-2 shrink-0", statusColor(feature))} title={feature.status ?? "unknown"} />
                    <span className="w-5 shrink-0 text-[10px] text-muted-foreground">{feature.index}</span>
                    <span className="min-w-0 flex-1 truncate text-name">{feature.slug}</span>
                    {isProduct && (
                      <Badge variant="focus" title="The product cell builds from this body">
                        product
                      </Badge>
                    )}
                    <Badge variant="secondary">{feature.role}</Badge>
                    {sketch && sketch.usedBy.length > 0 && (
                      <Badge variant="secondary" title={`Used by ${sketch.usedBy.join(", ")}: drawn dimmer in the viewport`}>
                        used
                      </Badge>
                    )}
                    <Badge variant={feature.gui ? "outline" : "name"}>{spec ? plainLabel(spec.id, spec.label) : feature.gui ? feature.gui.spec.replace(/_/g, " ") : "code"}</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 pl-[22px]">
                    <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground" title={`${feature.reads.join(", ")} -> ${feature.makes.join(", ")}`}>
                      {feature.reads.length > 0 ? feature.reads.join(", ") : "start"} <ArrowRight className="inline size-3" /> {feature.makes.length > 0 ? feature.makes.join(", ") : "no body"}
                    </span>
                    {sketch && (
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6"
                        data-testid={`sketch-eye-${sketch.name}`}
                        aria-pressed={!hiddenSketch}
                        aria-label={hiddenSketch ? `show ${sketch.name} in the viewport` : `hide ${sketch.name} in the viewport`}
                        title={hiddenSketch ? "Show this sketch in the viewport" : "Hide this sketch in the viewport"}
                        onClick={() => sketches?.onToggleHidden(sketch.name)}
                      >
                        {hiddenSketch ? <EyeOff className="text-muted-foreground" /> : <Eye />}
                      </Button>
                    )}
                    <span title={canEdit ? "Edit this feature" : "Written as code: edit it in the notebook"}>
                      <Button type="button" size="icon" variant="ghost" className="h-6 w-6" disabled={!canEdit || busy} aria-label={`edit ${feature.slug}`} onClick={() => spec && onEdit(feature, spec)}>
                        <Pencil />
                      </Button>
                    </span>
                    <Button
                      type="button"
                      size="icon"
                      variant={armed === feature.cell ? "destructive" : "ghost"}
                      className="h-6 w-6"
                      disabled={busy}
                      aria-label={armed === feature.cell ? `confirm delete ${feature.slug}` : `delete ${feature.slug}`}
                      title={armed === feature.cell ? "Click again to delete" : "Delete this feature"}
                      onClick={() => {
                        if (armed === feature.cell) {
                          setArmed(null);
                          onDelete(feature);
                        } else arm(feature.cell);
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                  {problem && <p className="mt-1 whitespace-pre-wrap break-words pl-[22px] text-[11px] text-fail">{problem}</p>}
                </li>
              );
            })}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}
