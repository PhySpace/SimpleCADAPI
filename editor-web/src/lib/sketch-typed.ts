/** Typed entry while drawing: the next click given as numbers (coordinates, a length and an angle, a radius) instead of a
 * position.  Pure: which fields a tool and its draft ask for, and the spot (plus the dimensions to keep) the numbers make. */

import type { Spot } from "@/lib/sketch";

export type TypedTool = "point" | "line" | "circle" | "arc" | "spline";
export type TypedDraft = { tool: "line"; from: Spot } | { tool: "circle"; center: Spot } | { tool: "arc"; center: Spot; start?: Spot } | { tool: "spline"; points: Spot[] } | null;
export type TypedField = { name: string; label: string; unit: "mm" | "deg" };
/** What a typed click keeps as a driving dimension of the entity it makes (a typed length stays that length). */
export type TypedDims = { length?: number; radius?: number };

const XY: TypedField[] = [
  { name: "x", label: "X", unit: "mm" },
  { name: "y", label: "Y", unit: "mm" },
];

/** The fields the next click of `tool` asks for, given its draft; null when the tool places nothing. */
export function typedFields(tool: string, draft: TypedDraft): TypedField[] | null {
  if (tool === "point" || tool === "spline") return XY;
  if (tool === "line") return draft?.tool === "line" ? [{ name: "length", label: "Length", unit: "mm" }, { name: "angle", label: "Angle", unit: "deg" }] : XY;
  if (tool === "circle") return draft?.tool === "circle" ? [{ name: "radius", label: "Radius", unit: "mm" }] : XY;
  if (tool === "arc") {
    if (draft?.tool !== "arc") return XY;
    if (!draft.start) return [{ name: "radius", label: "Radius", unit: "mm" }, { name: "angle", label: "Start angle", unit: "deg" }];
    return [{ name: "sweep", label: "Sweep", unit: "deg" }];
  }
  return null;
}

/** Parse a field's text: a number (a leading `=` and spaces are allowed); null when it is not one. */
export function parseTyped(text: string): number | null {
  const clean = text.trim().replace(/^=/, "");
  if (!clean) return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

const rad = (deg: number) => (deg * Math.PI) / 180;

/** The spot the typed numbers give (and the dimensions to keep), or an error the person reads.  `at` is where a spot of the draft
 * really is (a spot naming an existing point carries that point's id, not always its position).  An empty angle means 0. */
export function typedTarget(
  tool: string,
  draft: TypedDraft,
  text: Readonly<Record<string, string>>,
  at: (spot: Spot) => [number, number],
): { spot: Spot; dims: TypedDims } | { error: string } {
  const fields = typedFields(tool, draft);
  if (!fields) return { error: "this tool places nothing" };
  const values: Record<string, number> = {};
  for (const field of fields) {
    const raw = text[field.name] ?? "";
    const value = raw.trim() === "" && field.unit === "deg" ? 0 : parseTyped(raw);
    if (value === null) return { error: `${field.label}: a number is required` };
    values[field.name] = value;
  }
  if ("x" in values) return { spot: { x: values.x, y: values.y }, dims: {} };
  if (draft?.tool === "line") {
    if (!(values.length > 0)) return { error: "Length: must be greater than zero" };
    const [x0, y0] = at(draft.from);
    return { spot: { x: x0 + values.length * Math.cos(rad(values.angle)), y: y0 + values.length * Math.sin(rad(values.angle)) }, dims: { length: values.length } };
  }
  if (draft?.tool === "circle") {
    if (!(values.radius > 0)) return { error: "Radius: must be greater than zero" };
    const [cx, cy] = at(draft.center);
    return { spot: { x: cx + values.radius, y: cy }, dims: { radius: values.radius } };
  }
  if (draft?.tool === "arc") {
    const [cx, cy] = at(draft.center);
    if (!draft.start) {
      if (!(values.radius > 0)) return { error: "Radius: must be greater than zero" };
      return { spot: { x: cx + values.radius * Math.cos(rad(values.angle)), y: cy + values.radius * Math.sin(rad(values.angle)) }, dims: { radius: values.radius } };
    }
    if (!(values.sweep > 0 && values.sweep < 360)) return { error: "Sweep: between 0 and 360 degrees (counter-clockwise from the start)" };
    const [sx, sy] = at(draft.start);
    const a = Math.atan2(sy - cy, sx - cx) + rad(values.sweep);
    const r = Math.hypot(sx - cx, sy - cy);
    return { spot: { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) }, dims: {} };
  }
  return { error: "nothing to place" };
}
