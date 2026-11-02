/** Sketch edits that are SDK operations (`trim_rsketch`, `extend_rsketch`): the editor only says what was clicked and
 * adopts the document the server returns (POST /api/sketch/op).  No geometry of the edit lives here: which piece is
 * cut, where an end stops, is the SDK's decision.  This file builds the request from a click, picks the end of a line
 * that a click is nearer to (a choice of what the person pointed at, not geometry of the result) and describes the answer. */

import { entityMap, normalizeDoc, type SketchDoc } from "@/lib/sketch";

export type EditOp = "trim" | "extend";
export type End = "start" | "end";

export type TrimArgs = { entity: string; at: [number, number] };
export type ExtendArgs = { entity: string; end: End };
export type EditArgs = TrimArgs | ExtendArgs;

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

/** What the person is told after an edit: the SDK's notes, else a one-line account of the diff. */
export function describeEdit(op: EditOp, response: Pick<EditResponse, "created" | "removed" | "changed" | "notes">): string {
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
