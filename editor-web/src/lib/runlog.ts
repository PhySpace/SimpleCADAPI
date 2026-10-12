import { useCallback, useRef, useState } from "react";

export type LogLevel = "info" | "run" | "ok" | "error";

export interface LogEntry {
  id: number;
  at: number;
  level: LogLevel;
  text: string;
}

/** Cells being re-evaluated together: a parameter change, a run, a reload. */
export interface RunBatch {
  total: number;
  done: number;
  /** Title of the cell running now, if one is. */
  current: string | null;
  startedAt: number;
}

const MAX_ENTRIES = 400;
/** The gap between two rounds of one run is shorter than this; a longer quiet ends the batch. */
const BATCH_QUIET_MS = 700;

const ACTIVE = new Set(["queued", "running"]);
const FAILED = new Set(["exception", "error", "marimo-error"]);
/** Not run because a cell it depends on failed: counted, but the cause is what is logged. */
const BLOCKED = "cancelled";

const seconds = (ms: number) => `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;

/** The editor's log (what happened, what failed) and the progress of the cells
 * being re-evaluated, both fed by the kernel's cell states.  Errors belong here,
 * not in the header: they stay, with the time and the cell they came from. */
export function useRunLog() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [batch, setBatch] = useState<RunBatch | null>(null);
  const [unseenErrors, setUnseenErrors] = useState(0);
  const counter = useRef(0);
  // Per cell: when it began running, and the batch's bookkeeping.
  const began = useRef(new Map<string, number>());
  const members = useRef(new Map<string, "pending" | "done">());
  const batchStart = useRef(0);
  const quiet = useRef<number | null>(null);
  const titles = useRef(new Map<string, string>());
  const failures = useRef(0);
  const reported = useRef(new Set<string>());

  const push = useCallback((level: LogLevel, text: string) => {
    counter.current += 1;
    const entry: LogEntry = { id: counter.current, at: Date.now(), level, text };
    setEntries((previous) => [...previous.slice(-(MAX_ENTRIES - 1)), entry]);
    if (level === "error") setUnseenErrors((count) => count + 1);
  }, []);

  const clear = useCallback(() => {
    setEntries([]);
    setUnseenErrors(0);
  }, []);
  const markSeen = useCallback(() => setUnseenErrors(0), []);

  const refresh = useCallback((current: string | null) => {
    const all = [...members.current.values()];
    setBatch({
      total: all.length,
      done: all.filter((state) => state === "done").length,
      current,
      startedAt: batchStart.current,
    });
  }, []);

  const finishBatch = useCallback(() => {
    quiet.current = null;
    const total = members.current.size;
    if (total > 0) {
      const text = `${total} ${total === 1 ? "cell" : "cells"} re-evaluated in ${seconds(Date.now() - batchStart.current)}`;
      if (failures.current > 0) push("error", `${text}; ${failures.current} did not complete`);
      else push("ok", text);
    }
    members.current.clear();
    failures.current = 0;
    setBatch(null);
  }, [push]);

  /** Keep the cells' titles to name them in the log, and log each error a cell has newly. */
  const knowCells = useCallback(
    (cells: { id: string; title?: string; name?: string; errors?: string[] | null }[]) => {
      titles.current = new Map(cells.map((cell, index) => [cell.id, cell.title || cell.name || `cell ${index + 1}`]));
      const seen = new Set<string>();
      for (const cell of cells) {
        for (const message of cell.errors ?? []) {
          const key = `${cell.id}:${message}`;
          seen.add(key);
          if (!reported.current.has(key)) push("error", `${titles.current.get(cell.id)}: ${message}`);
        }
      }
      reported.current = seen;
    },
    [push],
  );

  /** A cell's state changed in the kernel. */
  const cellStatus = useCallback(
    (id: string, status: string, hint?: string | null) => {
      const title = titles.current.get(id) ?? hint ?? id;
      const now = Date.now();
      if (ACTIVE.has(status)) {
        if (quiet.current !== null) {
          window.clearTimeout(quiet.current);
          quiet.current = null;
        }
        if (members.current.size === 0) {
          batchStart.current = now;
          push("run", "re-evaluating…");
        }
        members.current.set(id, "pending");
        if (status === "running") began.current.set(id, now);
        refresh(status === "running" ? title : null);
        return;
      }
      const started = began.current.get(id);
      began.current.delete(id);
      if (!members.current.has(id)) {
        return;
      }
      members.current.set(id, "done");
      if (status === BLOCKED) {
        failures.current += 1;
      } else if (FAILED.has(status)) {
        failures.current += 1;
        push("error", `${title} failed${started ? ` after ${seconds(now - started)}` : ""}`);
      } else if (started !== undefined && now - started >= 300) {
        push("info", `${title}  ${seconds(now - started)}`);
      }
      const pending = [...members.current.values()].includes("pending");
      refresh(null);
      if (!pending) {
        quiet.current = window.setTimeout(finishBatch, BATCH_QUIET_MS);
      }
    },
    [finishBatch, push, refresh],
  );

  /** The model of the run arrived: the batch is over if every cell in it is. */
  const modelShown = useCallback(() => {
    if (members.current.size > 0 && ![...members.current.values()].includes("pending")) {
      if (quiet.current !== null) window.clearTimeout(quiet.current);
      finishBatch();
    }
  }, [finishBatch]);

  /** The run was stopped or the notebook changed: nothing is in flight any more. */
  const resetBatch = useCallback(() => {
    if (quiet.current !== null) window.clearTimeout(quiet.current);
    quiet.current = null;
    members.current.clear();
    began.current.clear();
    failures.current = 0;
    setBatch(null);
  }, []);

  return { entries, batch, unseenErrors, push, clear, markSeen, knowCells, cellStatus, modelShown, resetBatch };
}
