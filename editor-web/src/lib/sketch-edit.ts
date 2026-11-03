/** Sketch edits that are SDK operations (`trim_rsketch`, `extend_rsketch`): the editor only says what was clicked and
 * adopts the document the server returns (POST /api/sketch/op).  No geometry of the edit lives here: which piece is
 * cut, where an end stops, is the SDK's decision.  This file builds the request from a click, picks the end of a line
 * that a click is nearer to (a choice of what the person pointed at, not geometry of the result) and describes the answer. */

import { entityMap, normalizeDoc, type Choice, type Loop, type SketchDoc } from "@/lib/sketch";
import type { FeatureRow } from "@/lib/features";

export type EditOp = "trim" | "extend" | "fillet_corner" | "chamfer_corner" | "project";
export type End = "start" | "end";

export type TrimArgs = { entity: string; at: [number, number] };
export type ExtendArgs = { entity: string; end: End };
export type FilletArgs = { a: string; b: string; radius: number };
export type ChamferArgs = { a: string; b: string; distance: number };
export type ProjectArgs = { from_sketch: string };
export type EditArgs = TrimArgs | ExtendArgs | FilletArgs | ChamferArgs | ProjectArgs;

/** The server's answer to a sketch edit (the fields the editor uses). */
export type EditResponse = {
  ok: true;
  sketch: SketchDoc;
  created: string[];
  removed: string[];
  changed: string[];
  created_constraints: string[];
  removed_constraints: string[];
  changed_constraints: string[];
  notes: string[];
};

export type EditRequest = { sketch: SketchDoc; op: EditOp; args: EditArgs };

/** The request of a trim click: the entity and the click in sketch coordinates (the SDK finds the piece). */
export function trimRequest(doc: SketchDoc, entity: string, at: readonly [number, number]): EditRequest {
  return { sketch: doc, op: "trim", args: { entity, at: [at[0], at[1]] } };
}

/** The end of a line or arc a click is nearer to (the start on a tie). `pts` are the solved points. */
export function nearerEnd(doc: SketchDoc, pts: ReadonlyMap<string, [number, number]>, entity: string, click: readonly [number, number]): End | null {
  const e = entityMap(doc).get(entity);
  if (!e || (e.kind !== "line" && e.kind !== "arc")) return null;
  const a = pts.get(e.start ?? "");
  const b = pts.get(e.end ?? "");
  if (!a || !b) return null;
  return Math.hypot(click[0] - b[0], click[1] - b[1]) < Math.hypot(click[0] - a[0], click[1] - a[1]) ? "end" : "start";
}

/** The request of an extend click on a line: the end nearer to the click. Null when the entity cannot be extended. */
export function extendRequest(doc: SketchDoc, pts: ReadonlyMap<string, [number, number]>, entity: string, click: readonly [number, number]): EditRequest | null {
  const end = nearerEnd(doc, pts, entity, click);
  return end ? { sketch: doc, op: "extend", args: { entity, end } } : null;
}

// -- corners (fillet_corner / chamfer_corner) ---------------------------------------------------------------------------

/** A corner: a point shared by exactly two lines (`a` and `b` are the line ids). */
export type Corner = { point: string; a: string; b: string };
export type CornerOp = "fillet_corner" | "chamfer_corner";
export const CORNER_WORD: Record<CornerOp, { label: string; arg: "radius" | "distance" }> = {
  fillet_corner: { label: "Fillet radius", arg: "radius" },
  chamfer_corner: { label: "Chamfer distance", arg: "distance" },
};

const isLine = (e: { kind: string }) => e.kind === "line";

/** The lines that end at a point. */
function linesAt(doc: SketchDoc, point: string): string[] {
  return doc.entities.filter((e) => isLine(e) && (e.start === point || e.end === point)).map((e) => e.id);
}

/** The corner at a point, or null when it is not shared by exactly two lines (a pick of what the person pointed at:
 * whether the SDK can round it is its decision). */
export function cornerAt(doc: SketchDoc, point: string): Corner | null {
  const lines = linesAt(doc, point);
  return lines.length === 2 ? { point, a: lines[0], b: lines[1] } : null;
}

/** The corner two picked lines make (the point they share, when it is a corner), or null when they do not meet. */
export function cornerOfLines(doc: SketchDoc, a: string, b: string): Corner | null {
  if (a === b) return null;
  const map = entityMap(doc);
  const ea = map.get(a);
  const eb = map.get(b);
  if (!ea || !eb || !isLine(ea) || !isLine(eb)) return null;
  const shared = [ea.start, ea.end].filter((id): id is string => Boolean(id) && (id === eb.start || id === eb.end));
  for (const point of shared) {
    const corner = cornerAt(doc, point);
    if (corner && ((corner.a === a && corner.b === b) || (corner.a === b && corner.b === a))) return { point, a, b };
  }
  return null;
}

/** The offered value of a corner: a tenth of the shorter of its two lines (two decimals), 0 when a line is unknown. */
export function defaultCornerValue(doc: SketchDoc, pts: ReadonlyMap<string, [number, number]>, corner: Corner): number {
  const map = entityMap(doc);
  const length = (id: string): number => {
    const e = map.get(id);
    const s = pts.get(e?.start ?? "");
    const t = pts.get(e?.end ?? "");
    return s && t ? Math.hypot(s[0] - t[0], s[1] - t[1]) : 0;
  };
  const shorter = Math.min(length(corner.a), length(corner.b));
  return Math.round(shorter * 10) / 100;
}

/** The typed value of the corner box: a number above zero, or null. */
export function parseCornerValue(text: string): number | null {
  const t = text.trim();
  if (!/^[+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** The request of a corner: the two line ids and the value (radius for a fillet, distance for a chamfer). */
export function cornerRequest(op: CornerOp, doc: SketchDoc, corner: Pick<Corner, "a" | "b">, value: number): EditRequest {
  const args: FilletArgs | ChamferArgs = op === "fillet_corner" ? { a: corner.a, b: corner.b, radius: value } : { a: corner.a, b: corner.b, distance: value };
  return { sketch: doc, op, args };
}

// -- project ---------------------------------------------------------------------------------------------------------------

/** The sketch features of the notebook a sketch can take geometry from: every sketch feature but the one being edited. */
export function projectSources(features: readonly Pick<FeatureRow, "slug" | "gui">[], editing: string | null): string[] {
  return features.filter((f) => f.gui?.spec === "sketch" && f.slug !== editing).map((f) => f.slug);
}

export const projectRequest = (doc: SketchDoc, fromSketch: string): EditRequest => ({ sketch: doc, op: "project", args: { from_sketch: fromSketch } });

/** Projected geometry (reference copies of another sketch's entities) has ids `proj_...`. */
export const isProjected = (id: string): boolean => id.startsWith("proj_");

/** How many projected entities and points an answer created (`created` lists the new ids of both kinds). */
export function projectedCount(doc: SketchDoc, created: readonly string[]): { entities: number; points: number } {
  const made = new Set(created);
  return { entities: doc.entities.filter((e) => made.has(e.id) && isProjected(e.id)).length, points: doc.points.filter((p) => made.has(p.id) && isProjected(p.id)).length };
}

/** The choice of outer profile and holes carried over an edit: a loop of the new document takes the place of the chosen
 * loop it shares most entities with (same key first), when it shares more than half of them. */
export function remapChoice(previous: readonly Loop[], choice: Choice, next: readonly Loop[]): Choice {
  const carry = (key: string | null): string | null => {
    if (!key) return null;
    if (next.some((l) => l.key === key)) return key;
    const old = previous.find((l) => l.key === key);
    if (!old) return null;
    let best: { key: string; score: number } | null = null;
    for (const loop of next) {
      const shared = loop.entities.filter((id) => old.entities.includes(id)).length;
      const score = shared / new Set([...loop.entities, ...old.entities]).size;
      if (shared > 0 && score > 0.5 && (!best || score > best.score)) best = { key: loop.key, score };
    }
    return best?.key ?? null;
  };
  const outer = carry(choice.outer);
  const inner = choice.inner.map(carry).filter((k): k is string => k !== null && k !== outer);
  return { ...choice, outer, inner: [...new Set(inner)] };
}

/** What the person is told after an edit: the SDK's notes, else a one-line account of the diff. */
export function describeEdit(op: EditOp, response: Pick<EditResponse, "created" | "removed" | "changed" | "notes">, projected?: { entities: number; points: number; from: string }): string {
  if (op === "project" && projected) {
    const head = `project: ${projected.entities} entit${projected.entities === 1 ? "y" : "ies"} and ${projected.points} point${projected.points === 1 ? "" : "s"} from ${projected.from} (construction, fixed)`;
    return response.notes.length ? `${head}. ${response.notes.join(" ")}` : head;
  }
  const parts: string[] = [];
  if (response.created.length) parts.push(`created ${response.created.join(", ")}`);
  if (response.removed.length) parts.push(`removed ${response.removed.join(", ")}`);
  if (response.changed.length) parts.push(`changed ${response.changed.join(", ")}`);
  const head = `${op}: ${parts.length ? parts.join("; ") : "nothing changed"}`;
  return response.notes.length ? `${head}. ${response.notes.join(" ")}` : head;
}

/** The document the editor adopts from an answer, and the ids to flash (the entities and points the SDK created). */
export function applyEdit(response: Pick<EditResponse, "sketch" | "created">): { doc: SketchDoc; flash: string[] } {
  return { doc: normalizeDoc(response.sketch), flash: [...response.created] };
}

/** The document after an edit and the history that undoes it: the previous document is pushed, redo is cleared. */
export function pushHistory(history: readonly SketchDoc[], previous: SketchDoc, limit = 80): SketchDoc[] {
  return [...history.slice(-limit), previous];
}

/** POST /api/sketch/op. Rejects with the server's message (it names the ids involved). */
export async function fetchSketchOp(request: EditRequest): Promise<EditResponse> {
  const response = await fetch("/api/sketch/op", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
  const body = (await response.json().catch(() => null)) as (Partial<Omit<EditResponse, "ok">> & { ok?: boolean; error?: string }) | null;
  if (!response.ok || !body || body.ok === false || !body.sketch) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return {
    ok: true,
    sketch: body.sketch,
    created: body.created ?? [],
    removed: body.removed ?? [],
    changed: body.changed ?? [],
    created_constraints: body.created_constraints ?? [],
    removed_constraints: body.removed_constraints ?? [],
    changed_constraints: body.changed_constraints ?? [],
    notes: body.notes ?? [],
  };
}
