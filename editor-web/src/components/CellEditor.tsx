import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { EditorView } from "@codemirror/view";
import {
  ChevronRight,
  ChevronsDownUp,
  ChevronsUp,
  ChevronsUpDown,
  Check,
  Copy,
  Loader2,
  Play,
  Plus,
  Square,
  Trash2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ParamControl, type ParamMeta, type ParamValue } from "@/components/ParamControl";
import { createSettler, SETTLE_MS } from "@/lib/settle";
import { cadTheme } from "@/lib/cm-theme";
import { sdkCompletion } from "@/lib/sdk-complete";
import { cn } from "@/lib/utils";

export type NotebookCell = {
  id: string;
  name: string;
  code: string;
  status?: string | null;
  errors?: string[] | null;
  /** Not run: a cell it depends on (or the setup) failed. */
  blocked?: boolean;
  output?: string | null;
  console?: string[];
  /** Slug of the cell's `# ---- feature: ... ----` header, if it has one. */
  feature?: string | null;
  /** The step's name: feature slug, params header, or the first variable it defines. */
  title?: string;
  /** An @app.function cell: edited in the file, not here. */
  readonly?: boolean;
  /** Where the cell is in the notebook file, for pasting to a coding agent:
   * `<path>:L<first>-L<last> (cell 03 \`name\`)`. */
  ref?: string;
};
/** One feature header; `cell` is the id of the cell it opens. */
export type NotebookFeature = { cell: string; label: string; kind?: string };
export type { ParamMeta, ParamValue };

type SocketLike = { send: (message: Record<string, unknown>) => void } | null;

const AUTOSAVE_MS = 700;
const EXTENSIONS = [python(), EditorView.lineWrapping, sdkCompletion];
/** a constant: a new object each render makes the editor wrapper rebuild its configuration, which drops a snippet in progress */
const BASIC_SETUP = { lineNumbers: false, foldGutter: false, highlightActiveLine: false };

function loadCollapsed(notebook: string | null): Set<string> {
  try {
    const raw = window.localStorage.getItem(`sca-collapsed:${notebook}`);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

/** The notebook: one block per cell. A block's header is its handle — the
 * step's name — and folds the cell away; the buttons run it, run everything
 * above it, or delete it. Every edit is autosaved to the notebook file, so a
 * coding agent reading the file sees what is on screen. */
export function CellEditor({
  cells,
  features,
  params,
  socket,
  notebook,
  onInterrupt,
  onConflict,
}: {
  cells: NotebookCell[];
  features: NotebookFeature[];
  params: ParamMeta[];
  socket: SocketLike;
  notebook: string | null;
  onInterrupt: () => void;
  /** A cell changed on disk while it had an unsaved edit here: the file's version was kept. */
  onConflict: (cell: NotebookCell, mine: string) => void;
}) {
  const [drafts, setDrafts] = useState<Map<string, string>>(new Map());
  const [running, setRunning] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => loadCollapsed(notebook));
  // Two-stage delete: arm on the first click (button turns red), confirm on
  // the second; any click elsewhere disarms.
  const [armed, setArmed] = useState<string | null>(null);
  const saveTimers = useRef(new Map<string, number>());
  // What each edited cell's draft started from, and the last text sent to be saved:
  // a cell that arrives as something else was changed by someone else (an agent).
  const bases = useRef(new Map<string, string>());
  const sent = useRef(new Map<string, string>());

  const featureByCell = useMemo(() => new Map(features.map((feature) => [feature.cell, feature])), [features]);

  useEffect(() => {
    setCollapsed(loadCollapsed(notebook));
    setDrafts(new Map());
    bases.current.clear();
    sent.current.clear();
  }, [notebook]);

  // The cells arrive again after every save and every change on disk: settle each draft
  // against them.  Saved (equal) -> done; confirms our last save -> keep editing from it;
  // anything else -> the file's version wins, the person is told.
  const onConflictRef = useRef(onConflict);
  onConflictRef.current = onConflict;
  useEffect(() => {
    const same = (a: string, b: string) => a.trim() === b.trim();
    const lost: [NotebookCell, string][] = [];
    setDrafts((previous) => {
      let next: Map<string, string> | null = null;
      const drop = (id: string) => {
        next ??= new Map(previous);
        next.delete(id);
        bases.current.delete(id);
        sent.current.delete(id);
      };
      for (const [id, draft] of previous) {
        const cell = cells.find((candidate) => candidate.id === id);
        if (!cell) {
          drop(id);
          continue;
        }
        const base = bases.current.get(id);
        const last = sent.current.get(id);
        if (same(cell.code, draft)) drop(id);
        else if (last !== undefined && same(cell.code, last)) bases.current.set(id, cell.code);
        else if (base !== undefined && !same(cell.code, base)) {
          lost.push([cell, draft]);
          drop(id);
        }
      }
      return next ?? previous;
    });
    for (const [cell, mine] of lost) {
      cancelSave(cell.id);
      onConflictRef.current(cell, mine);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cells]);

  const remember = (next: Set<string>) => {
    setCollapsed(next);
    try {
      window.localStorage.setItem(`sca-collapsed:${notebook}`, JSON.stringify([...next]));
    } catch {
      /* private mode: folding just does not persist */
    }
  };
  const toggle = (id: string) => {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    remember(next);
  };

  const cancelSave = (id: string) => {
    const timer = saveTimers.current.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    saveTimers.current.delete(id);
  };

  const run = (cell: NotebookCell) => {
    cancelSave(cell.id);
    const code = drafts.get(cell.id) ?? cell.code;
    setRunning(cell.id);
    sent.current.set(cell.id, code);
    socket?.send({ type: "code.edit", cell: cell.id, code, base: bases.current.get(cell.id) });
    window.setTimeout(() => setRunning((current) => (current === cell.id ? null : current)), 2500);
  };

  const runAbove = (cell: NotebookCell) => {
    setRunning(cell.id);
    socket?.send({ type: "rerun.request", cell: cell.id, above: true });
    window.setTimeout(() => setRunning((current) => (current === cell.id ? null : current)), 2500);
  };

  const remove = (cell: NotebookCell) => {
    setArmed(null);
    cancelSave(cell.id);
    socket?.send({ type: "rollback.request", cell: cell.id });
  };

  const insert = (after: string | null) => socket?.send({ type: "insert.request", after });

  const edit = (cell: NotebookCell, value: string) => {
    if (!bases.current.has(cell.id)) bases.current.set(cell.id, cell.code);
    setDrafts((previous) => new Map(previous).set(cell.id, value));
    if (cell.readonly) return;
    cancelSave(cell.id);
    saveTimers.current.set(
      cell.id,
      window.setTimeout(() => {
        saveTimers.current.delete(cell.id);
        sent.current.set(cell.id, value);
        socket?.send({ type: "cell.save", cell: cell.id, code: value, base: bases.current.get(cell.id) });
      }, AUTOSAVE_MS),
    );
  };

  // A drag is sent when it pauses or ends, not step by step: every value the
  // server gets is a rebuild.
  const socketRef = useRef(socket);
  socketRef.current = socket;
  const settler = useRef(
    createSettler<ParamValue>(SETTLE_MS, (values) => socketRef.current?.send({ type: "param.set", values })),
  );
  const forwardParam = (id: string, value: ParamValue, now = false) => {
    settler.current.push(id, value);
    if (now) settler.current.flush();
  };

  // Disarm delete when clicking anywhere outside the armed button.
  useEffect(() => {
    if (!armed) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest(`[data-delete-armed="${CSS.escape(armed)}"]`)) setArmed(null);
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => window.removeEventListener("pointerdown", onPointerDown, true);
  }, [armed]);

  if (cells.length === 0) {
    return <p className="p-3 text-[11px] text-muted-foreground">Waiting for the kernel to publish cells…</p>;
  }

  const allCollapsed = cells.every((cell) => collapsed.has(cell.id));
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="label">{cells.length} cells</span>
        <button
          type="button"
          className="label flex items-center gap-1 hover:text-foreground"
          title={allCollapsed ? "Unfold every cell" : "Fold every cell to its name"}
          onClick={() => remember(allCollapsed ? new Set() : new Set(cells.map((cell) => cell.id)))}
        >
          {allCollapsed ? <ChevronsUpDown className="h-3 w-3" /> : <ChevronsDownUp className="h-3 w-3" />}
          {allCollapsed ? "unfold all" : "fold all"}
        </button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="px-2 pb-6">
          <CellGap after={null} onInsert={insert} />
          {cells.map((cell, index) => (
            <div key={cell.id}>
              <CellBlock
                cell={cell}
                index={index}
                role={featureByCell.get(cell.id)?.kind}
                params={params.filter((param) => param.cell === cell.id)}
                draft={drafts.get(cell.id)}
                folded={collapsed.has(cell.id)}
                pending={running === cell.id}
                live={cell.status === "running" || cell.status === "queued"}
                armed={armed === cell.id}
                socket={socket}
                forwardParam={forwardParam}
                onToggle={() => toggle(cell.id)}
                onRun={() => run(cell)}
                onInterrupt={onInterrupt}
                onRunAbove={() => runAbove(cell)}
                onDelete={() => (armed === cell.id ? remove(cell) : setArmed(cell.id))}
                onEdit={(value) => edit(cell, value)}
              />
              <CellGap after={cell.id} onInsert={insert} />
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}

/** Hover divider between cells with a "+" insertion button. */
function CellGap({ after, onInsert }: { after: string | null; onInsert: (after: string | null) => void }) {
  return (
    <div className="group/gap relative flex h-3 items-center justify-center">
      <div className="absolute inset-x-0 h-[2px] bg-transparent transition-colors group-hover/gap:bg-border" />
      <button
        type="button"
        title="Insert a cell here"
        className="z-10 flex h-4 w-4 items-center justify-center border-2 border-input bg-background text-muted-foreground opacity-0 transition-opacity hover:border-focus hover:text-focus group-hover/gap:opacity-100"
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

function IconButton({
  title,
  onClick,
  disabled,
  className,
  children,
  ...rest
}: {
  title: string;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
  children: React.ReactNode;
} & Record<string, unknown>) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      className={cn(
        "flex h-6 w-6 shrink-0 items-center justify-center border-2 border-transparent text-muted-foreground transition-colors hover:border-input hover:text-foreground disabled:pointer-events-none disabled:opacity-30",
        className,
      )}
      onClick={onClick}
      {...rest}
    >
      {children}
    </button>
  );
}

/** One cell: header handle + (when open) code, errors, output, console. */
function CellBlock({
  cell,
  index,
  role,
  params,
  draft,
  folded,
  pending,
  live,
  armed,
  socket,
  forwardParam,
  onToggle,
  onRun,
  onInterrupt,
  onRunAbove,
  onDelete,
  onEdit,
}: {
  cell: NotebookCell;
  index: number;
  role?: string;
  params: ParamMeta[];
  draft: string | undefined;
  folded: boolean;
  /** Run was just asked for; the kernel has not said anything yet. */
  pending: boolean;
  /** The kernel is running or has queued the cell. */
  live: boolean;
  armed: boolean;
  socket: SocketLike;
  forwardParam: (id: string, value: ParamValue, now?: boolean) => void;
  onToggle: () => void;
  onRun: () => void;
  onInterrupt: () => void;
  onRunAbove: () => void;
  onDelete: () => void;
  onEdit: (value: string) => void;
}) {
  // the editor takes this once: a new function each render would rebuild its configuration
  const onEditRef = useRef(onEdit);
  onEditRef.current = onEdit;
  const handleChange = useCallback((value: string) => onEditRef.current(value), []);
  const failed = cell.status === "exception" || cell.status === "error" || (cell.errors?.length ?? 0) > 0;
  const stale = cell.status === "stale";
  const dirty = draft !== undefined && draft !== cell.code;
  const isSelection = cell.title === "selection";
  const title = cell.title || cell.name;
  const hasOutput = Boolean(cell.output) || params.length > 0;
  const [copied, setCopied] = useState(false);
  // Click: a reference an agent can find in the file. Alt/Shift+click: the
  // reference and the cell's code.
  const copyReference = (withCode: boolean) => {
    const reference = cell.ref ?? title;
    const text = withCode ? `${reference}\n\`\`\`python\n${draft ?? cell.code}\n\`\`\`` : reference;
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <section
      className={cn(
        "border-2 bg-background transition-colors",
        isSelection ? "border-focus/60" : failed ? "border-fail/70" : "border-border",
        stale && !failed && "border-dashed",
        armed && "border-fail",
      )}
    >
      <header className="flex h-8 items-center gap-1 pr-1">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 self-stretch pl-1.5 text-left"
          onClick={onToggle}
          title={folded ? "Unfold" : "Fold to its name"}
        >
          <ChevronRight className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", !folded && "rotate-90")} />
          <span className="w-5 shrink-0 text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
          <span className={cn("truncate font-semibold", isSelection ? "text-focus" : "text-name")}>{title}</span>
          {role && <span className="label shrink-0">{role}</span>}
        </button>
        {dirty && <span className="h-2 w-2 shrink-0 bg-focus" title="saving…" />}
        {cell.status === "running" && <Badge variant="focus" className="animate-pulse">running</Badge>}
        {cell.status === "queued" && <Badge variant="secondary">queued</Badge>}
        {failed && <Badge variant="fail">failed</Badge>}
        {cell.blocked && !failed && <Badge variant="secondary">blocked</Badge>}
        {stale && !failed && <Badge variant="focus">stale</Badge>}
        {cell.readonly && <Badge variant="secondary">function</Badge>}
        <button
          type="button"
          title="Copy a reference to this cell for a coding agent (Alt/Shift+click: with its code)"
          className="flex h-6 w-6 shrink-0 items-center justify-center border-2 border-transparent text-muted-foreground transition-colors hover:border-input hover:text-foreground"
          onClick={(event) => copyReference(event.altKey || event.shiftKey)}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-pass" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
        <IconButton title="Run every cell above this one" onClick={onRunAbove} disabled={index === 0}>
          <ChevronsUp className="h-3.5 w-3.5" />
        </IconButton>
        {/* One button, two states: run, and while the kernel is running the cell, stop. */}
        <IconButton
          title={
            live
              ? "Stop the run (interrupt the kernel)"
              : failed
                ? "Cell failed — run again (Ctrl+Enter)"
                : "Run this cell (Ctrl+Enter)"
          }
          onClick={live ? onInterrupt : onRun}
          className={live ? "border-fail text-fail hover:border-fail hover:text-fail" : undefined}
        >
          {live ? (
            <Square className="h-3 w-3 fill-current" />
          ) : pending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-focus" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
        </IconButton>
        <IconButton
          title={armed ? "Click again to delete this cell" : "Delete this cell"}
          onClick={onDelete}
          data-delete-armed={cell.id}
          className={armed ? "border-fail bg-fail text-primary-foreground hover:border-fail hover:text-primary-foreground" : "hover:text-fail"}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </IconButton>
      </header>
      {live && <div className="cell-running h-[2px] w-full" />}
      {!folded && (
        <div className="border-t-2 border-border">
          <CodeMirror
            value={draft ?? cell.code}
            height="auto"
            extensions={EXTENSIONS}
            theme={cadTheme}
            editable={!cell.readonly}
            basicSetup={BASIC_SETUP}
            onChange={handleChange}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                onRun();
              }
            }}
          />
          {(cell.errors?.length ?? 0) > 0 && (
            <div className="border-t-2 border-fail/60 bg-fail/10 px-2.5 py-1.5">
              {cell.errors?.map((message, errorIndex) => (
                <pre key={errorIndex} className="whitespace-pre-wrap text-[11px] text-fail">
                  {message}
                </pre>
              ))}
            </div>
          )}
          {hasOutput && (
            <div className="border-t-2 border-border px-2.5 py-2">
              {params.length > 0 && (
                <div>
                  <div className="grid grid-cols-2 gap-x-5 gap-y-2.5">
                    {params.map((param) => (
                      <ParamControl key={param.id} param={param} forwardParam={forwardParam} />
                    ))}
                  </div>
                  {params.some((param) => param.modified) && (
                    <div className="flex justify-end gap-3 pt-2">
                      <button
                        type="button"
                        className="label hover:text-foreground"
                        title="Drop the edited values; back to what the source says"
                        onClick={() =>
                          socket?.send({ type: "param.revert", names: params.filter((p) => p.modified).map((p) => p.id) })
                        }
                      >
                        revert
                      </button>
                      <button
                        type="button"
                        className="label text-focus hover:text-foreground"
                        title="Write the edited values into the notebook source"
                        onClick={() =>
                          socket?.send({ type: "param.commit", names: params.filter((p) => p.modified).map((p) => p.id) })
                        }
                      >
                        write to source
                      </button>
                    </div>
                  )}
                </div>
              )}
              {cell.output && (
                <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-[11px] text-foreground/90">{cell.output}</pre>
              )}
            </div>
          )}
          {(cell.console?.length ?? 0) > 0 && (
            <div className="max-h-44 overflow-auto border-t-2 border-border px-2.5 py-1">
              {cell.console?.map((line, lineIndex) => (
                <pre
                  key={lineIndex}
                  className={cn(
                    "whitespace-pre-wrap text-[11px]",
                    /error|traceback|failed/i.test(line) ? "text-fail" : "text-muted-foreground",
                  )}
                >
                  {line}
                </pre>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
