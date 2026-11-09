/** B-splines in anchor form, as a pen tool draws and edits them.  A spline in anchor form is the SDK's cubic B-spline whose
 * inner knots have multiplicity 3: control points [A0, out0, in1, A1, out1, in2, A2, ...], every span a cubic Bezier from one
 * anchor (on the curve) to the next, each anchor with an in-handle and an out-handle.  Anchors and handles are plain sketch
 * points, so moving them is document editing; inserting and removing an anchor are SDK edits (`insert_spline_anchor_rsketch`,
 * `remove_spline_anchor_rsketch`, see sketch-edit.ts).  This file reads the structure, builds a drawn path and keeps a smooth
 * anchor smooth while one of its handles is dragged.  A B-spline in another form (control points, an old file) has no anchors
 * here: it shows its control polygon and offers `convert_spline_to_anchors_rsketch`. */

import { ensurePoint, nextId, solvedPoints, splinePath, type DrawOptions, type SEntity, type SketchDoc, type SolveResult, type Spot } from "@/lib/sketch";
import { t } from "@/i18n";

type P = [number, number];

/** Is the B-spline in anchor form (degree 3, clamped, every inner knot of multiplicity 3)? */
export function isAnchorSpline(e: SEntity): boolean {
  if (e.kind !== "bspline" || e.degree !== 3) return false;
  const poles = e.control_points ?? [];
  const mults = e.multiplicities;
  if (!mults) return poles.length === 4; // one span: the uniform knots the document leaves out
  if (mults.length < 2 || mults[0] !== 4 || mults[mults.length - 1] !== 4 || mults.slice(1, -1).some((m) => m !== 3)) return false;
  return poles.length === 3 * (mults.length - 1) + 1;
}

/** Where a point sits in an anchor-form spline: an anchor (with its handles) or a handle (with its anchor and the opposite
 * handle of that anchor).  `end` marks the first and last anchor (they have one handle, unless the spline is closed). */
export type AnchorRole = { spline: string; kind: "anchor" | "handle"; index: number; anchor: string; handles: string[]; other?: string; end: boolean };

/** The role of every point of every anchor-form spline, by point id (a point two splines share keeps the first role). */
export function anchorRoles(doc: SketchDoc): Map<string, AnchorRole> {
  const out = new Map<string, AnchorRole>();
  for (const e of doc.entities) {
    if (!isAnchorSpline(e)) continue;
    const poles = e.control_points!;
    const last = poles.length - 1;
    const closed = poles[0] === poles[last];
    const handlesOf = (i: number): string[] => {
      const list: string[] = [];
      if (i > 0) list.push(poles[i - 1]);
      else if (closed) list.push(poles[last - 1]);
      if (i < last) list.push(poles[i + 1]);
      else if (closed) list.push(poles[1]);
      return list;
    };
    for (let i = 0; i <= last; i += 3) {
      if (!out.has(poles[i])) out.set(poles[i], { spline: e.id, kind: "anchor", index: i, anchor: poles[i], handles: handlesOf(i), end: !closed && (i === 0 || i === last) });
    }
    for (let i = 0; i <= last; i++) {
      if (i % 3 === 0 || out.has(poles[i])) continue;
      const anchorIndex = i % 3 === 1 ? i - 1 : i + 1;
      const sibling = i % 3 === 1 ? (anchorIndex > 0 ? anchorIndex - 1 : closed ? last - 1 : -1) : anchorIndex < last ? anchorIndex + 1 : closed ? 1 : -1;
      out.set(poles[i], { spline: e.id, kind: "handle", index: i, anchor: poles[anchorIndex], handles: [], other: sibling >= 0 ? poles[sibling] : undefined, end: false });
    }
  }
  return out;
}

/** The handles to show: those of the anchor-form splines that are picked (the spline itself, or one of its points). */
export function shownHandles(doc: SketchDoc, selection: readonly string[], roles: Map<string, AnchorRole> = anchorRoles(doc)): Set<string> {
  const active = new Set<string>();
  for (const id of selection) {
    const role = roles.get(id);
    if (role) active.add(role.spline);
    else if (doc.entities.some((e) => e.id === id && isAnchorSpline(e))) active.add(id);
  }
  const out = new Set<string>();
  for (const [id, role] of roles) if (role.kind === "handle" && active.has(role.spline)) out.add(id);
  return out;
}

/** Every handle point of every anchor-form spline (hidden ones are not picked or snapped to). */
export function handlePoints(roles: Map<string, AnchorRole>): Set<string> {
  return new Set([...roles].filter(([, r]) => r.kind === "handle").map(([id]) => id));
}

/** The place on an anchor-form spline's curve nearest `pos`, within `tol` (sketch units): where a click adds an anchor.  The
 * curve is the SDK's samples of the last solve; the SDK puts the anchor at the curve point nearest the click. */
export function curveAt(doc: SketchDoc, solve: SolveResult | null, pos: readonly [number, number], tol: number): { spline: string; at: P } | null {
  const pts = solvedPoints(doc, solve);
  let best: { spline: string; at: P; d: number } | null = null;
  for (const e of doc.entities) {
    if (!isAnchorSpline(e)) continue;
    const path = splinePath(e, pts, solve);
    for (let i = 0; i + 1 < path.length; i++) {
      const [a, b] = [path[i], path[i + 1]];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const len2 = dx * dx + dy * dy;
      const t = len2 > 0 ? Math.min(1, Math.max(0, ((pos[0] - a[0]) * dx + (pos[1] - a[1]) * dy) / len2)) : 0;
      const at: P = [a[0] + t * dx, a[1] + t * dy];
      const d = Math.hypot(pos[0] - at[0], pos[1] - at[1]);
      if (d <= tol && (!best || d < best.d)) best = { spline: e.id, at, d };
    }
  }
  return best ? { spline: best.spline, at: best.at } : null;
}

/** What a click in anchor mode does where it lands: remove the inner anchor under it (`hit`: a point id within reach), else add
 * an anchor on the curve under it, else nothing.  End anchors and handles are not removed (the reason is the `refuse` text). */
export type AnchorAction = { kind: "add"; spline: string; at: P } | { kind: "remove"; spline: string; anchor: string } | { kind: "refuse"; text: string } | null;

export function anchorAction(doc: SketchDoc, solve: SolveResult | null, pos: readonly [number, number], tol: number, hit: string | null, roles: Map<string, AnchorRole> = anchorRoles(doc)): AnchorAction {
  const role = hit ? roles.get(hit) : undefined;
  if (hit && role?.kind === "anchor" && !role.end) {
    const e = doc.entities.find((x) => x.id === role.spline);
    const closedSeam = e?.start === hit; // the seam of a closed spline is its start and end
    if (!closedSeam) return { kind: "remove", spline: role.spline, anchor: hit };
    return { kind: "refuse", text: t("{{point}} is where {{spline}} starts and ends: it cannot be removed", { point: hit, spline: role.spline }) };
  }
  if (hit && role?.kind === "anchor") return { kind: "refuse", text: t("{{point}} is an end of {{spline}}: an end anchor cannot be removed (trim the spline instead)", { point: hit, spline: role.spline }) };
  const on = curveAt(doc, solve, pos, tol);
  if (on) return { kind: "add", spline: on.spline, at: on.at };
  if (hit && role?.kind === "handle") return { kind: "refuse", text: t("{{point}} is a handle of {{spline}}: click its anchor {{anchor}} to remove the anchor", { point: hit, spline: role.spline, anchor: role.anchor }) };
  return null;
}

// -- the drawn path -------------------------------------------------------------------------------------------------------

/** Points along a chain of cubic Bezier spans given by their control points [A0, out0, in1, A1, ...]. */
export function bezierPath(poles: readonly P[], steps = 24): P[] {
  const out: P[] = [];
  for (let s = 0; s + 3 < poles.length; s += 3) {
    const [p0, p1, p2, p3] = [poles[s], poles[s + 1], poles[s + 2], poles[s + 3]];
    for (let k = s === 0 ? 0 : 1; k <= steps; k++) {
      const t = k / steps;
      const a = (1 - t) ** 3;
      const b = 3 * (1 - t) ** 2 * t;
      const c = 3 * (1 - t) * t * t;
      const d = t ** 3;
      out.push([a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]]);
    }
  }
  return out;
}

// -- the pen tool ---------------------------------------------------------------------------------------------------------

/** An anchor of the pen draft: where it is and, when the click was dragged, its out-handle as an offset (the in-handle is the
 * mirror image).  Without a drag the handles follow the neighbours (a smooth curve through the clicks). */
export type PenNode = { spot: Spot; handle?: P | null };

/** The control points of a pen path through `at` (the anchors' positions): a node's own handle when it has one, else a third
 * of the way towards its neighbours along the line from the previous to the next anchor (Catmull-Rom tangents). */
export function penPoles(at: readonly P[], handles: readonly (P | null | undefined)[], closed: boolean): P[] {
  const n = at.length;
  const tangent = (i: number): P => {
    const own = handles[i];
    if (own) return own;
    const prev = i > 0 ? at[i - 1] : closed ? at[n - 1] : at[i];
    const next = i < n - 1 ? at[i + 1] : closed ? at[0] : at[i];
    return [(next[0] - prev[0]) / 6, (next[1] - prev[1]) / 6];
  };
  const poles: P[] = [];
  const spans = closed ? n : n - 1;
  for (let s = 0; s < spans; s++) {
    const a = at[s];
    const b = at[(s + 1) % n];
    const ta = tangent(s);
    const tb = tangent((s + 1) % n);
    if (s === 0) poles.push(a);
    poles.push([a[0] + ta[0], a[1] + ta[1]], [b[0] - tb[0], b[1] - tb[1]], b);
  }
  return poles;
}

const round = (v: number) => Math.round(v * 1e4) / 1e4;

/** The anchor-form B-spline of a pen draft: a point per anchor (existing points are reused) and per handle, knots 0..n with
 * the inner ones of multiplicity 3.  `closed`: the last span returns to the first anchor. */
export function addPenSpline(doc: SketchDoc, nodes: readonly PenNode[], closed: boolean, opts: DrawOptions, at: (spot: Spot) => P): { doc: SketchDoc; id: string } | null {
  if (nodes.length < 2) return null;
  const positions = nodes.map((node) => at(node.spot));
  const poles = penPoles(positions, nodes.map((node) => node.handle), closed);
  let next = doc;
  const anchors: string[] = [];
  for (const node of nodes) {
    const made = ensurePoint(next, node.spot);
    next = made.doc;
    anchors.push(made.id);
  }
  if (new Set(anchors).size !== anchors.length) return null; // two clicks on one point
  const ids: string[] = [];
  for (let i = 0; i < poles.length; i++) {
    if (i % 3 === 0) {
      ids.push(anchors[(i / 3) % anchors.length]);
      continue;
    }
    const id = nextId("p", next);
    next = { ...next, points: [...next.points, { id, x: round(poles[i][0]), y: round(poles[i][1]) }] };
    ids.push(id);
  }
  const spans = (ids.length - 1) / 3;
  const id = nextId("s", next);
  const entity: SEntity = {
    id,
    kind: "bspline",
    start: ids[0],
    end: ids[ids.length - 1],
    control_points: ids,
    degree: 3,
    knots: Array.from({ length: spans + 1 }, (_, i) => i),
    multiplicities: Array.from({ length: spans + 1 }, (_, i) => (i === 0 || i === spans ? 4 : 3)),
    construction: opts.construction,
  };
  return { doc: { ...next, entities: [...next.entities, entity] }, id };
}

// -- smooth and corner anchors ----------------------------------------------------------------------------------------------

/** Do the two handles of an anchor point in opposite directions (within `deg` degrees)?  A zero-length handle counts as smooth. */
export function isSmooth(anchor: P, a: P, b: P, deg = 2): boolean {
  const ax = a[0] - anchor[0];
  const ay = a[1] - anchor[1];
  const bx = b[0] - anchor[0];
  const by = b[1] - anchor[1];
  const la = Math.hypot(ax, ay);
  const lb = Math.hypot(bx, by);
  if (la < 1e-9 || lb < 1e-9) return true;
  return (ax * bx + ay * by) / (la * lb) <= -Math.cos((deg * Math.PI) / 180);
}

/** Where the opposite handle goes when `handle` is dragged at a smooth anchor: on the other side of the anchor, keeping its own
 * length (so the two sides keep their own pull).  Null when the dragged handle sits on the anchor (no direction). */
export function mirrorHandle(anchor: P, handle: P, length: number): P | null {
  const dx = handle[0] - anchor[0];
  const dy = handle[1] - anchor[1];
  const l = Math.hypot(dx, dy);
  if (l < 1e-9) return null;
  return [anchor[0] - (dx / l) * length, anchor[1] - (dy / l) * length];
}

/** Make anchors smooth: each one's two handles turn to the mean direction (opposite each other), keeping their lengths.  Returns
 * the new positions of the handles that turn (sketch coordinates). */
export function smoothAnchors(doc: SketchDoc, anchors: readonly string[], pts: ReadonlyMap<string, P>, roles: Map<string, AnchorRole> = anchorRoles(doc)): Record<string, P> {
  const out: Record<string, P> = {};
  for (const id of anchors) {
    const role = roles.get(id);
    if (!role || role.kind !== "anchor" || role.handles.length !== 2) continue;
    const at = pts.get(id);
    const a = pts.get(role.handles[0]);
    const b = pts.get(role.handles[1]);
    if (!at || !a || !b) continue;
    const la = Math.hypot(a[0] - at[0], a[1] - at[1]);
    const lb = Math.hypot(b[0] - at[0], b[1] - at[1]);
    if (la < 1e-9 || lb < 1e-9) continue;
    // the direction from the in-handle through the anchor to the out-handle, averaged over both sides
    let dx = (at[0] - a[0]) / la + (b[0] - at[0]) / lb;
    let dy = (at[1] - a[1]) / la + (b[1] - at[1]) / lb;
    const l = Math.hypot(dx, dy);
    if (l < 1e-9) continue; // the handles lie on top of each other: no direction to agree on
    dx /= l;
    dy /= l;
    out[role.handles[0]] = [round(at[0] - dx * la), round(at[1] - dy * la)];
    out[role.handles[1]] = [round(at[0] + dx * lb), round(at[1] + dy * lb)];
  }
  return out;
}
