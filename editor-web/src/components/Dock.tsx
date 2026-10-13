import { ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { LogEntry, LogLevel, RunBatch } from "@/lib/runlog";

const INK: Record<LogLevel, string> = {
  info: "text-muted-foreground",
  run: "text-focus",
  ok: "text-pass",
  error: "text-fail",
};

const TAG: Record<LogLevel, string> = { info: "   ", run: "RUN", ok: "OK ", error: "ERR" };

const clock = (at: number) => new Date(at).toLocaleTimeString([], { hour12: false });

/** The bottom dock: while cells are being re-evaluated, which ones and how far
 * along; the log of what happened and what failed.  Opens itself on an error. */
export function Dock({
  entries,
  batch,
  status,
  unseenErrors,
  onClear,
  onSeen,
}: {
  entries: LogEntry[];
  batch: RunBatch | null;
  status: string;
  unseenErrors: number;
  onClear: () => void;
  onSeen: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const tick = batch ? Date.now() : now;
  const list = useRef<HTMLDivElement>(null);

  // An error opens the log; the person closes it again.
  useEffect(() => {
    if (unseenErrors > 0) setOpen(true);
  }, [unseenErrors]);

  useEffect(() => {
    if (open) onSeen();
  }, [open, entries.length, onSeen]);

  useEffect(() => {
    if (open && list.current) list.current.scrollTop = list.current.scrollHeight;
  }, [open, entries.length]);

  useEffect(() => {
    if (!batch) return;
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, [batch]);

  const last = entries[entries.length - 1];
  const errors = entries.filter((entry) => entry.level === "error").length;
  const percent = batch && batch.total > 0 ? Math.round((batch.done / batch.total) * 100) : 0;

  return (
    <section className="shrink-0 border-t-2 border-border bg-background" aria-label="log">
      {open && (
        <div ref={list} className="h-44 overflow-y-auto border-b-2 border-border px-3 py-1.5 text-[11px] leading-5">
          {entries.length === 0 ? (
            <p className="text-muted-foreground">Nothing yet. Runs, reloads and errors are listed here.</p>
          ) : (
            entries.map((entry) => (
              <p key={entry.id} className={cn("flex gap-3 whitespace-pre-wrap break-words", INK[entry.level])}>
                <span className="shrink-0 text-muted-foreground">{clock(entry.at)}</span>
                <span className="w-7 shrink-0 font-semibold">{TAG[entry.level]}</span>
                <span className="min-w-0">{entry.text}</span>
              </p>
            ))
          )}
        </div>
      )}
      <div className="flex h-8 items-center gap-3 px-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 self-stretch text-left"
          onClick={() => setOpen((value) => !value)}
          title={open ? "Close the log" : "Open the log"}
        >
          {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronUp className="h-3.5 w-3.5 shrink-0" />}
          <span className="label shrink-0">log</span>
          {batch ? (
            <>
              <span className="shrink-0 text-focus">
                re-evaluating {batch.done}/{batch.total}
              </span>
              <span className="relative h-2 w-28 shrink-0 border border-focus">
                <span className="absolute inset-y-0 left-0 bg-focus" style={{ width: `${percent}%` }} />
              </span>
              <span className="min-w-0 truncate text-muted-foreground">
                {batch.current ? `${batch.current} · ` : batch.done >= batch.total ? "building the model · " : ""}
                {(Math.max(0, tick - batch.startedAt) / 1000).toFixed(1)} s
              </span>
            </>
          ) : (
            <span className={cn("min-w-0 truncate", last ? INK[last.level] : "text-muted-foreground")}>
              {last ? last.text : status}
            </span>
          )}
        </button>
        {errors > 0 && (
          <span className="shrink-0 border border-fail px-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-fail">
            {errors} {errors === 1 ? "error" : "errors"}
          </span>
        )}
        <button
          type="button"
          title="Clear the log"
          className="flex h-6 w-6 shrink-0 items-center justify-center border-2 border-transparent text-muted-foreground hover:border-input hover:text-foreground"
          onClick={onClear}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </section>
  );
}
