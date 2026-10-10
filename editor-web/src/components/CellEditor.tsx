import { useEffect, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import { Loader2, Play, Plus, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

export type NotebookCell = {
  id: string;
  name: string;
  code: string;
  status?: string | null;
  errors?: string[] | null;
  output?: string | null;
  console?: string[];
  /** Slug of the cell's `# ---- feature: ... ----` header, if it has one. */
  feature?: string | null;
};
/** One feature header; `cell` is the id of the cell it opens. */
export type NotebookFeature = { cell: string; label: string; kind?: string };
export type ParamValue = number | boolean;
/** A parameter the notebook declares (see `sca params`); `cell` is the id of
 * the declaring cell. `modified`: the value differs from the source. */
export type ParamMeta = {
  id: string;
  label: string;
  cell: string;
  group: string;
  kind: "float" | "int" | "bool";
  control: "slider" | "number" | "toggle";
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string | null;
  default: ParamValue;
  value: ParamValue;
  modified?: boolean;
  comment?: string | null;
  issues?: string[];
};

type SocketLike = { send: (message: Record<string, unknown>) => void } | null;

/** The notebook document, laid out like marimo's own webui:
 *
 *   [① gutter] [ code editor            ]
 *   [    ]      [ output / ui elements  ]   ← params sliders live here
 *   [    ]      [ console (dimmer)      ]
 *
 * Hovering the gap between cells reveals a "+" (insert cell). The gutter
 * circle is the run control; the smaller circle below it is the two-stage
 * rollback (delete the cell and restore the state before it). Ctrl+Enter or
 * the gutter runs the cell via `code.edit`; the package event refreshes
 * everything else.
 */
export function CellEditor({
  cells,
  features,
  params,
  socket,
}: {
  cells: NotebookCell[];
  features: NotebookFeature[];
  params: ParamMeta[];
  socket: SocketLike;
}) {
  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [running, setRunning] = useState<string | null>(null);
  // Two-stage rollback: arm on the first gutter click (button red, cell
  // dimmed), confirm on the second; any click elsewhere disarms.
  const [armedRollback, setArmedRollback] = useState<string | null>(null);

  const featureByCell = new Map(features.map((feature) => [feature.cell, feature]));

  // Differential semantics: the server rolls the runtime back to cell-1,
  // runs this cell, and leaves the suffix stale.
  const run = (cell: NotebookCell) => {
    const code = drafts.get(cell.id) ?? cell.code;
    setRunning(cell.id);
    socket?.send({ type: "code.edit", cell: cell.id, code });
    window.setTimeout(() => setRunning((current) => (current === cell.id ? null : current)), 2500);
  };

  const rollback = (cell: NotebookCell) => {
    setArmedRollback(null);
    socket?.send({ type: "rollback.request", cell: cell.id });
  };

  const insert = (after: string | null) => {
    socket?.send({ type: "insert.request", after });
  };

  // Forward slider bursts; the server coalesces (latest-wins rebuild).
  const pendingParams = useRef(new Map<string, ParamValue>());
  const paramTimer = useRef<number | null>(null);
  const forwardParam = (id: string, value: ParamValue) => {
    pendingParams.current.set(id, value);
    if (paramTimer.current !== null) return;
    paramTimer.current = window.setTimeout(() => {
      paramTimer.current = null;
      socket?.send({ type: "param.set", values: Object.fromEntries(pendingParams.current) });
      pendingParams.current.clear();
    }, 60);
  };

  // Disarm rollback when clicking anywhere outside the armed button.
  useEffect(() => {
    if (!armedRollback) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest(`[data-rollback-armed="${CSS.escape(armedRollback)}"]`)) {
        setArmedRollback(null);
      }
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => window.removeEventListener("pointerdown", onPointerDown, true);
  }, [armedRollback]);

  if (cells.length === 0) {
    return <p className="p-3 text-xs text-muted-foreground">Waiting for the kernel to publish cells…</p>;
  }
  // marimo-style insertion affordance: hover the gap between cells.
  const gaps: (string | null)[] = [null, ...cells.map((c) => c.id)];
  return (
    <ScrollArea className="h-full">
      <div className="px-2 py-2">
        {cells.map((cell, index) => (
          <div key={cell.id}>
            <CellGap after={gaps[index]} onInsert={insert} />
            <CellCard
              cell={cell}
              index={index}
              feature={featureByCell.get(cell.id)}
              params={params.filter((param) => param.cell === cell.id)}
              draft={drafts.get(cell.id)}
              dirty={drafts.get(cell.id) !== undefined && drafts.get(cell.id) !== cell.code}
              runningName={running}
              socket={socket}
              forwardParam={forwardParam}
              onRun={run}
              onRollback={rollback}
              onDraftChange={(value) =>
                setDrafts((previous) => {
                  const next = new Map(previous);
                  next.set(cell.id, value);
                  return next;
                })
              }
              armed={armedRollback === cell.id}
              onArm={() => setArmedRollback((current) => (current === cell.id ? null : cell.id))}
            />
          </div>
        ))}
        <CellGap after={cells[cells.length - 1].id} onInsert={insert} />
      </div>
    </ScrollArea>
  );
}

/** Hover divider between cells with a "+" insertion button. */
function CellGap({ after, onInsert }: { after: string | null; onInsert: (after: string | null) => void }) {
  return (
    <div className="group/gap relative flex h-4 items-center justify-start">
      <div className="absolute inset-x-4 h-px bg-transparent transition-colors group-hover/gap:bg-border" />
      <button
        type="button"
        title="Insert cell here"
        className="z-10 ml-10 flex h-5 w-5 items-center justify-center rounded-full border bg-card text-muted-foreground opacity-0 shadow-sm transition-opacity hover:border-primary/50 hover:text-foreground group-hover/gap:opacity-100"
        onClick={(event) => {
          event.stopPropagation();
          onInsert(after);
        }}
      >
        <Plus className="h-3 w-3" />
      </button>
    </div>
  );
}

/** One cell document: gutter controls + code + output + console. */
function CellCard({
  cell,
  index,
  feature,
  params,
  draft,
  dirty,
  runningName,
  socket,
  forwardParam,
  onRun,
  onRollback,
  onDraftChange,
  armed,
  onArm,
}: {
  cell: NotebookCell;
  index: number;
  feature?: NotebookFeature;
  params: ParamMeta[];
  draft: string | undefined;
  dirty: boolean;
  runningName: string | null;
  socket: SocketLike;
  forwardParam: (id: string, value: ParamValue) => void;
  onRun: (cell: NotebookCell) => void;
  onRollback: (cell: NotebookCell) => void;
  onDraftChange: (value: string) => void;
  armed: boolean;
  onArm: () => void;
}) {
  const failed = cell.status === "exception" || cell.status === "error";
  const stale = cell.status === "stale";
  const isRunning = runningName === cell.id || cell.status === "running";
  const hasOutput =
    Boolean(cell.output) || (cell.console?.length ?? 0) > 0 || params.length > 0;
  return (
    // marimo cells are open documents: spacing + hover outline, not cards.
    <section
      className={cn(
        "group relative flex gap-1 rounded-md py-0.5 transition-colors hover:bg-white/[0.02]",
        stale && "opacity-55",
      )}
    >
      {/* gutter: run control + state, rollback below it */}
      <div className="flex shrink-0 flex-col items-center gap-1 pt-1">
        <button
          type="button"
          title={failed ? "cell failed — click to rerun" : `run ${cell.feature ?? cell.name}`}
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold",
            isRunning
              ? "border-primary/40 text-primary"
              : failed
                ? "border-destructive/60 bg-destructive/15 text-destructive"
                : dirty
                  ? "border-amber-500/50 text-amber-400 hover:bg-accent"
                  : "border-transparent text-muted-foreground/60 group-hover:border-border group-hover:text-muted-foreground",
          )}
          onClick={() => onRun(cell)}
        >
          {isRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : failed ? (
            <span className="h-2 w-2 rounded-full bg-destructive" />
          ) : dirty ? (
            <span className="h-2 w-2 rounded-full bg-amber-400" />
          ) : (
            <>
              <span className="group-hover:hidden">{index + 1}</span>
              <Play className="hidden h-3 w-3 group-hover:block" />
            </>
          )}
        </button>
        {/* rollback: first click arms (button turns solid red, content
            dims); second click on it confirms; any click elsewhere disarms. */}
        <button
          type="button"
          data-rollback-armed={cell.id}
          title={
            armed
              ? "Click again to delete this cell and roll back"
              : "Rollback: delete this cell and restore the state before it"
          }
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold",
            armed
              ? "border-destructive bg-destructive text-destructive-foreground opacity-100"
              : "border-transparent text-muted-foreground/60 opacity-0 group-hover:border-border group-hover:text-muted-foreground group-hover:opacity-100",
          )}
          onClick={() => {
            if (armed) {
              onArm();
              onRollback(cell);
            } else {
              onArm();
            }
          }}
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      </div>
      <div className={cn("min-w-0 flex-1", armed && "opacity-40 grayscale")}>
        <div className="relative">
          <CodeMirror
            value={draft ?? cell.code}
            height="auto"
            extensions={[python()]}
            theme={oneDark}
            basicSetup={{ lineNumbers: false, foldGutter: false, highlightActiveLine: false }}
            onChange={onDraftChange}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                onRun(cell);
              }
            }}
          />
          {/* identity chips float over the editor's top-right corner */}
          <span className="pointer-events-none absolute right-2 top-1 z-10 flex items-center gap-1.5">
            {feature && (
              <Badge variant="secondary" className="normal-case">
                {feature.label}
                {feature.kind ? ` · ${feature.kind}` : ""}
              </Badge>
            )}
            {stale && (
              <Badge variant="outline" className="text-amber-400">
                stale
              </Badge>
            )}
            <span className="font-mono text-[10px] text-muted-foreground">{cell.name === "_" ? "" : cell.name}</span>
          </span>
        </div>
        {/* errors: marimo puts the exception box under the code */}
        {(cell.errors?.length ?? 0) > 0 && (
          <div className="mx-2 my-1 rounded border border-destructive/40 bg-destructive/10 px-2 py-1">
            {cell.errors?.map((message, errorIndex) => (
              <pre key={errorIndex} className="whitespace-pre-wrap text-[11px] text-destructive">
                {message}
              </pre>
            ))}
          </div>
        )}
        {/* output zone: ui elements (params) first, then rich output */}
        {hasOutput && (
          <div className="px-2 py-1">
            {params.length > 0 && (
              <div className="pb-1">
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                  {params.map((param) => (
                    <ParamControl key={param.id} param={param} forwardParam={forwardParam} />
                  ))}
                </div>
                {params.some((param) => param.modified) && (
                  <div className="flex justify-end gap-2 pt-1 text-[10px] uppercase">
                    <button
                      type="button"
                      className="text-muted-foreground hover:text-foreground"
                      title="Drop the edited values; back to what the source says"
                      onClick={() => socket?.send({ type: "param.revert", names: params.filter((p) => p.modified).map((p) => p.id) })}
                    >
                      revert
                    </button>
                    <button
                      type="button"
                      className="text-primary hover:text-primary/80"
                      title="Write the edited values into the notebook source"
                      onClick={() => socket?.send({ type: "param.commit", names: params.filter((p) => p.modified).map((p) => p.id) })}
                    >
                      write to source
                    </button>
                  </div>
                )}
              </div>
            )}
            {cell.output && (
              <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs text-foreground/90">{cell.output}</pre>
            )}
          </div>
        )}
        {/* console: stdout/stderr under the output, marimo-style */}
        {(cell.console?.length ?? 0) > 0 && (
          <div className="max-h-44 overflow-auto border-l-2 border-border px-2 py-0.5">
            {cell.console?.map((line, lineIndex) => (
              <pre
                key={lineIndex}
                className={cn(
                  "whitespace-pre-wrap text-[11px]",
                  /error|traceback|failed/i.test(line) ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {line}
              </pre>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** One parameter: a slider, a number box or a toggle, by its `# ui:` comment. */
function ParamControl({
  param,
  forwardParam,
}: {
  param: ParamMeta;
  forwardParam: (id: string, value: ParamValue) => void;
}) {
  const label = param.label || param.id;
  const title = [param.comment, ...(param.issues ?? [])].filter(Boolean).join("\n") || undefined;
  if (param.control === "toggle") {
    return (
      <label className="flex items-center justify-between text-[11px]" title={title}>
        <span className={cn("text-muted-foreground", param.modified && "text-amber-400")}>{label}</span>
        <input
          type="checkbox"
          checked={Boolean(param.value)}
          onChange={(event) => forwardParam(param.id, event.target.checked)}
        />
      </label>
    );
  }
  const value = Number(param.value);
  return (
    <div title={title}>
      <div className="mb-0.5 flex items-baseline justify-between text-[11px]">
        <label className={cn("text-muted-foreground", param.modified && "text-amber-400")}>{label}</label>
        {param.control === "number" ? (
          <input
            type="number"
            className="w-20 rounded border bg-transparent px-1 text-right font-mono"
            value={value}
            min={param.min ?? undefined}
            max={param.max ?? undefined}
            step={param.step ?? (param.kind === "int" ? 1 : "any")}
            onChange={(event) => {
              const next = event.target.valueAsNumber;
              if (Number.isFinite(next)) forwardParam(param.id, next);
            }}
          />
        ) : (
          <span className="font-mono">{value}</span>
        )}
        {param.unit && <span className="ml-1 text-muted-foreground">{param.unit}</span>}
      </div>
      {param.control === "slider" && param.min !== null && param.max !== null && (
        <Slider
          value={[value]}
          min={param.min}
          max={param.max}
          step={param.step ?? (param.kind === "int" ? 1 : (param.max - param.min) / 200)}
          onValueChange={([next]) => forwardParam(param.id, next)}
        />
      )}
    </div>
  );
}
