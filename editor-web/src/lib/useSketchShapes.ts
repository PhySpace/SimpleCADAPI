import { useEffect, useMemo, useState } from "react";

import { SolveCache, fetchSolve, sketchShape, type SketchInfo, type SketchShape } from "@/lib/sketch-scene";
import type { SolveResult } from "@/lib/sketch";

/** One cache for the page: a sketch document is solved once, and again only when it changes. */
export const solveCache = new SolveCache(fetchSolve);

export type SketchSolved = { shape: SketchShape; solve: SolveResult | null };

/** The solved shape of every sketch feature (the seeds, flagged pending, until the SDK answers). */
export function useSketchShapes(infos: readonly SketchInfo[]): Map<string, SketchSolved> {
  const [version, setVersion] = useState(0);
  useEffect(() => solveCache.subscribe(() => setVersion((n) => n + 1)), []);
  useEffect(() => {
    for (const info of infos) solveCache.request(info.doc, info.key);
  }, [infos]);
  return useMemo(() => {
    const out = new Map<string, SketchSolved>();
    for (const info of infos) {
      const entry = solveCache.get(info.key);
      const solve = entry?.state === "ok" ? entry.result : null;
      out.set(info.name, { solve, shape: sketchShape(info.doc, solve, { failed: entry?.state === "failed", pending: !entry || entry.state === "pending" }) });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [infos, version]);
}
