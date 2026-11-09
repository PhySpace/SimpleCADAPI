/** Pure parts of the contextual action bar: where it sits near what is selected, which key runs its first action,
 * and where on the selection to anchor it.  No React, no three.js. */

export type Size = { w: number; h: number };

/** The top left corner of a bar of `bar` size near an anchor (container pixels), kept inside `bounds`.
 * It sits below and to the right of the anchor, and flips to the other side when that would leave the container.
 * Without an anchor it docks at the top centre.  `docked` says which. */
export function placeBar(anchor: readonly [number, number] | null, bar: Size, bounds: Size, gap = 16, margin = 8): { x: number; y: number; docked: boolean } {
  const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(value, Math.max(low, high)));
  if (!anchor) return { x: clamp((bounds.w - bar.w) / 2, margin, bounds.w - bar.w - margin), y: margin, docked: true };
  let x = anchor[0] + gap;
  if (x + bar.w > bounds.w - margin) x = anchor[0] - gap - bar.w;
  let y = anchor[1] + gap;
  if (y + bar.h > bounds.h - margin) y = anchor[1] - gap - bar.h;
  return { x: clamp(x, margin, bounds.w - bar.w - margin), y: clamp(y, margin, bounds.h - bar.h - margin), docked: false };
}

/** Whether an Enter keypress should run the bar's first action: nothing typed into, no button or list item of its own focused,
 * no modifier held. */
export function enterRunsFirst(event: { key: string; target: unknown; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; shiftKey?: boolean; defaultPrevented?: boolean }): boolean {
  if (event.key !== "Enter" || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey || event.defaultPrevented) return false;
  const target = event.target as { closest?: (selector: string) => unknown } | null;
  return !(target?.closest && target.closest("input, textarea, select, button, a, [role=option], [role=combobox], [contenteditable=true], .cm-editor, [role=dialog]"));
}

type Vec3 = [number, number, number];
const triple = (value: unknown): Vec3 | null =>
  Array.isArray(value) && value.length === 3 && value.every((c) => typeof c === "number" && Number.isFinite(c)) ? (value as Vec3) : null;

/** A point (mm, world) to hang the bar on for a picked entity, from its properties (a face's centroid, an edge's midpoint or
 * centre); null when the details name none (the caller may use the body's bounds). */
export function anchorOfEntity(item: { kind: string; properties: Record<string, unknown> | null }): Vec3 | null {
  const p = item.properties ?? {};
  const keys = item.kind === "edge" ? ["midpoint", "center", "centroid"] : ["centroid", "center", "midpoint"];
  for (const key of keys) {
    const found = triple(p[key]);
    if (found) return found;
  }
  return null;
}

/** The mean of several anchors (a selection of several things gets one bar), or null for none. */
export function meanPoint(points: readonly Vec3[]): Vec3 | null {
  if (points.length === 0) return null;
  const sum = points.reduce<Vec3>((acc, p) => [acc[0] + p[0], acc[1] + p[1], acc[2] + p[2]], [0, 0, 0]);
  return [sum[0] / points.length, sum[1] / points.length, sum[2] / points.length];
}
