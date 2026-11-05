import { ArrowRight, Eye, EyeOff, Pencil, Redo2, Trash2, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { plainLabel } from "@/lib/commands";
import { candidateLabel, fetchRefStatus, refState, refTone, type Catalog, type FeatureRow, type FeatureState, type RefStatus, type Spec } from "@/lib/features";
import type { SketchInfo } from "@/lib/sketch-scene";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** Undo and redo with their counts. */
export function UndoRedo({ state, busy, onUndo, onRedo }: { state: Pick<FeatureState, "undo" | "redo">; busy?: boolean; onUndo: () => void; onRedo: () => void }) {
  return (
    <span className="flex items-center gap-1">
      <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={busy || state.undo === 0} title={t("Undo the last feature change (Ctrl/Cmd+Z)")} onClick={onUndo}>
        <Undo2 /> {t("undo")} {state.undo > 0 && <span className="text-muted-foreground">{state.undo}</span>}
      </Button>
      <Button type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={busy || state.redo === 0} title={t("Redo (Ctrl/Cmd+Shift+Z)")} onClick={onRedo}>
        <Redo2 /> {t("redo")} {state.redo > 0 && <span className="text-muted-foreground">{state.redo}</span>}
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

const TONE: Record<"pass" | "warn" | "fail", string> = { pass: "text-pass", warn: "text-amber-600", fail: "text-fail" };

/** The references of a failing feature's selections: their state (green / amber / red) and, for a split or a lost one,
 * the candidates; choosing one asks the server to write it into the reference (`piece=`, or a new reference). */
export function ReferenceHealth({ cell, version, busy, onRepair }: { cell: string; version: string; busy: boolean; onRepair: (slot: string, index: number, choice: number) => void }) {
  const [status, setStatus] = useState<RefStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    fetchRefStatus(cell).then(
      (found) => live && (setStatus(found), setFailure(null)),
      (error: Error) => live && (setStatus(null), setFailure(error.message)),
    );
    return () => void (live = false);
  }, [cell, version]);
  if (failure) return <p className="mt-1 pl-[22px] text-[11px] text-muted-foreground">{t("references:")} {failure}</p>;
  if (!status || status.badge === null) return null;
  return (
    <div className="mt-1 space-y-1 pl-[22px] text-[11px]" data-testid={`refs-${cell}`}>
      {Object.entries(status.slots).flatMap(([slot, rows]) =>
        rows.map((row, index) => {
          const state = refState(row);
          return (
            <div key={`${slot}-${index}`}>
              <span className={cn("font-medium", TONE[refTone(state)])}>{slot} {index + 1}: {state}</span>
              {state === "lost" && row.reason && <span className="text-muted-foreground"> ({row.reason}{row.lost_at ? ` at ${row.lost_at}` : ""})</span>}
              {(state === "split" || state === "lost") && row.candidates.length > 0 && (
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {row.candidates.map((candidate, choice) => (
                    <Button key={choice} type="button" size="sm" variant="outline" className="h-6 px-1.5" disabled={busy}
                      title={state === "split" ? t("Use this piece") : t("Accept this look-alike")} onClick={() => onRepair(slot, index, choice)}>
                      {state === "split" ? `piece ${choice + 1}` : "use"}: {candidateLabel(candidate)}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          );
        }),
      )}
    </div>
  );
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
  onRepairRef,
  sketches,
}: {
  sketches?: TreeSketches;
  /** Write a choice into a reference of a feature's selection (`ref_repair`); without it, no repair buttons. */
  onRepairRef?: (cell: string, slot: string, index: number, choice: number) => void;
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
        <span className="label">{t("features")} {state.features.length > 0 && `(${state.features.length})`}</span>
        <UndoRedo state={state} busy={busy} onUndo={onUndo} onRedo={onRedo} />
      </div>
      {stale && state.tip && (
        <div className="flex items-center gap-2 border-b-2 border-focus bg-accent px-3 py-1.5 text-[11px]">
          <span className="min-w-0 flex-1">
            {t("The product still builds from")} <span className="text-name">{stale.body}</span>.
          </span>
          <Button type="button" size="sm" className="h-6 px-2" disabled={busy} onClick={() => onUseProduct(state.tip as string)}>
            {t("use {{body}}", { body: state.tip })}
          </Button>
        </div>
      )}
      {error && <div className="border-b border-fail px-3 py-1 text-[11px] text-fail">{error}</div>}
      <ScrollArea className="min-h-0 flex-1">
        {state.features.length === 0 ? (
          <p className="px-3 py-3 text-[11px] text-muted-foreground">{t("No features yet. Add a Box or another operation from the command bar; each one becomes an ordinary cell in the notebook.")}</p>
        ) : (
          <ul>
            {state.features.map((feature) => {
              const spec = feature.gui ? catalog?.specs.find((item) => item.id === feature.gui?.spec) : undefined;
              const problem = errorText(feature);
              const productBodies = state.product ? (state.product.bodies ?? [state.product.body]) : [];
              const isProduct = feature.makes.some((name) => productBodies.includes(name));
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
                      <Badge variant="focus" title={state.product?.implicit ? t("The part is this body (made by the runtime, no cell to keep)") : t("The product cell builds from this body")}>
                        {t("product")}
                      </Badge>
                    )}
                    <Badge variant="secondary">{t(feature.role)}</Badge>
                    {sketch && sketch.usedBy.length > 0 && (
                      <Badge variant="secondary" title={t("Used by {{users}}: drawn dimmer in the viewport", { users: sketch.usedBy.join(", ") })}>
                        {t("used")}
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
                        aria-label={hiddenSketch ? t("show {{name}} in the viewport", { name: sketch.name }) : t("hide {{name}} in the viewport", { name: sketch.name })}
                        title={hiddenSketch ? t("Show this sketch in the viewport") : t("Hide this sketch in the viewport")}
                        onClick={() => sketches?.onToggleHidden(sketch.name)}
                      >
                        {hiddenSketch ? <EyeOff className="text-muted-foreground" /> : <Eye />}
                      </Button>
                    )}
                    <span title={canEdit ? t("Edit this feature") : t("Written as code: edit it in the notebook")}>
                      <Button type="button" size="icon" variant="ghost" className="h-6 w-6" disabled={!canEdit || busy} aria-label={t("edit {{name}}", { name: feature.slug })} onClick={() => spec && onEdit(feature, spec)}>
                        <Pencil />
                      </Button>
                    </span>
                    <Button
                      type="button"
                      size="icon"
                      variant={armed === feature.cell ? "destructive" : "ghost"}
                      className="h-6 w-6"
                      disabled={busy}
                      aria-label={armed === feature.cell ? t("confirm delete {{name}}", { name: feature.slug }) : t("delete {{name}}", { name: feature.slug })}
                      title={armed === feature.cell ? t("Click again to delete") : t("Delete this feature")}
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
                  {problem && onRepairRef && spec?.slots.some((slot) => slot.kind === "select") && (
                    <ReferenceHealth cell={feature.cell} version={`${feature.status}:${problem}`} busy={busy} onRepair={(slot, index, choice) => onRepairRef(feature.cell, slot, index, choice)} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}
