import { useEffect, useMemo, useState } from "react";
import { Scissors } from "lucide-react";

import type { SceneView } from "@/scene/scene-view";
import { t } from "@/i18n";

/** A tagged entity an operation split (the server's `tag_splits`, from `scad.list_tag_splits`): the pieces carry
 * `<tag>.split<i>`, and `pieces` lists the scene entities of each. */
export type TagSplit = {
  tag: string;
  into: string[];
  op: string;
  pieces: { piece: number; node_id: string; entity_id: string }[];
};

/** One colour per piece, told apart at a glance on any body colour. */
export const PIECE_COLORS = ["#e4572e", "#17a3b8", "#e8b10c", "#5fa83a", "#8a5cc2", "#d9479a"];

export function parseTagSplits(value: unknown): TagSplit[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (row): row is TagSplit =>
      !!row && typeof row.tag === "string" && Array.isArray(row.into) && typeof row.op === "string" && Array.isArray(row.pieces),
  );
}

/** Highlights the pieces of every split tag in the viewport, each piece its own colour, and says what was split, so the
 * person (or an agent reading the viewport image) can judge whether the split was meant.  Dismissed until the splits
 * change; the highlight can be turned off while the notice stays. */
export function TagSplits({ view, splits, sceneVersion, docked = false }: { view: SceneView; splits: TagSplit[]; sceneVersion: number; docked?: boolean }) {
  const signature = useMemo(() => JSON.stringify(splits.map((row) => [row.tag, row.into, row.op])), [splits]);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [shown, setShown] = useState(true);
  const open = splits.length > 0 && dismissed !== signature;
  const highlight = open && shown;

  useEffect(() => {
    if (!highlight) return;
    const keys: string[] = [];
    for (const row of splits) {
      for (const piece of row.pieces) {
        view.addMark(piece.node_id, piece.entity_id, PIECE_COLORS[piece.piece % PIECE_COLORS.length]);
        keys.push(`${piece.node_id}::${piece.entity_id}`);
      }
    }
    return () => keys.forEach((key) => view.removeMark(key));
  }, [view, splits, highlight, sceneVersion]);

  if (!open) return null;
  return (
    <div className={`pointer-events-auto ${docked ? "relative min-h-0 max-h-[360px]" : "absolute left-3 top-3 z-20 max-h-[min(50%,360px)] max-w-[min(420px,80%)]"} flex flex-col gap-1.5 border-2 border-[var(--focus)] bg-popover px-3 py-2 text-[11px] shadow-[4px_4px_0_var(--shadow-hard)]`} data-testid="tag-splits">
      <div className="flex items-center gap-2 font-semibold">
        <Scissors className="size-3.5 text-[var(--focus)]" />
        <span>{splits.length === 1 ? t("A tagged entity was split") : t("{{count}} tagged entities were split", { count: splits.length })}</span>
      </div>
      <div className="flex min-h-0 flex-col gap-1.5 overflow-y-auto pr-1">
      {splits.map((row) => (
        <div key={`${row.op}:${row.tag}:${row.into.join(",")}`} className="flex flex-col gap-1">
          <span className="text-muted-foreground">
            {t("{{op}} split {{tag}} into {{count}}; the tag names none of them:", { op: row.op, tag: row.tag, count: row.into.length })}
          </span>
          <span className="flex flex-wrap gap-1">
            {row.into.map((name, index) => (
              <span key={name} className="flex items-center gap-1 border border-border px-1.5 py-0.5 font-mono">
                <span className="inline-block size-2.5" style={{ background: PIECE_COLORS[index % PIECE_COLORS.length] }} />
                {name}
              </span>
            ))}
          </span>
        </div>
      ))}
      </div>
      <div className="flex shrink-0 gap-2 pt-0.5">
        <button type="button" className="border border-border px-2 py-0.5 hover:bg-accent" onClick={() => setShown((value) => !value)}>
          {shown ? t("Hide highlight") : t("Show highlight")}
        </button>
        <button type="button" className="border border-border px-2 py-0.5 hover:bg-accent" onClick={() => setDismissed(signature)}>
          {t("Dismiss")}
        </button>
      </div>
    </div>
  );
}
