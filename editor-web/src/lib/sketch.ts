/** The 2D sketch editor's pure logic: the document model (mirrors src/simplecadapi/editor/sketch_doc.py), ids, which
 * constraints a selection admits, snapping, closed-loop detection and matching against the server's profiles, the
 * temporary fix a drag places, measured values and the solver client (one request in flight, the latest wins). */

// -- contract -------------------------------------------------------------------------------------------------------

import { normalizePlane, planeCoords, type PlaneSpec } from "@/lib/sketch-plane";

export { PLANES, planeCoords, type Frame, type Plane, type PlaneSpec } from "@/lib/sketch-plane";

export type SPoint = { id: string; x: number; y: number };
export type EntityKind = "line" | "circle" | "arc" | "bspline";
/** A B-spline lists its control points (point ids; the first is its start, the last its end) and its degree. */
export type SEntity = { id: string; kind: EntityKind; start?: string; end?: string; center?: string; radius?: number; control_points?: string[]; degree?: number; construction?: boolean };

export type ConstraintKind =
  | "fix" | "coincident" | "point_on" | "horizontal" | "vertical" | "points_horizontal" | "points_vertical"
  | "parallel" | "perpendicular" | "collinear" | "tangent" | "concentric" | "midpoint" | "symmetric"
  | "equal_length" | "equal_radius"
  | "length" | "distance" | "distance_x" | "distance_y" | "line_distance" | "angle" | "radius" | "diameter";

export type SConstraint = {
  id: string;
  kind: ConstraintKind;
  targets: string[];
  value?: number;
  driving?: boolean;
  at_a?: "start" | "end";
  at_b?: "start" | "end";
  mode?: "external" | "internal";
};

export type SketchDoc = {
  /** A named datum plane, or a frame (origin and unit axes, mm) for a sketch on a face. */
  plane: PlaneSpec;
  points: SPoint[];
  entities: SEntity[];
  constraints: SConstraint[];
  profile: number;
  inner: number[];
  fully_constrained: boolean;
};

export type Diagnostic = { constraint_id: string | null; severity: string; code: string; message: string; residual: number | null };
/** One profile of the SDK's ``inspect_sketch_rsketchprofiles``: a free circle, or a loop / chain of edges in walking order. */
export type ServerProfile = { index: number; id: string; kind: string; closed: boolean; entity_ids: string[]; reversed: boolean[] };
export type SolveStatus = "solved" | "underconstrained" | "conflicting" | "failed";
export type SolveResult = {
  ok: boolean;
  status: SolveStatus;
  dof: number;
  residual: number | null;
  points: Record<string, [number, number]>;
  scalars: Record<string, number>;
  entities: Record<string, Record<string, unknown>>;
  diagnostics: Diagnostic[];
  profiles: ServerProfile[];
  /** Each B-spline as the SDK drew it (``sample_curve_rcurvature``): points, normals and curvatures along it, sketch coordinates. */
  curves?: Record<string, { points: [number, number][]; normals: [number, number][]; curvatures: number[] }>;
  /** Why edge sets are no profile (a branch point, say), as the SDK words it. */
  unusable: string[];
  /** Where curves cross away from every point (the SDK's ``inspect_sketch_rsketchcrossings``: the places trim cuts at). */
  crossings?: { at: [number, number]; entities: [string, string] }[];
};

export const ID_PATTERN = /^[a-z][a-z0-9_]{0,30}$/;

type Info = { label: string; unit?: "mm" | "deg"; glyph: string };
export const CONSTRAINT_INFO: Record<ConstraintKind, Info> = {
  fix: { label: "Fix", glyph: "F" },
  coincident: { label: "Coincident", glyph: "C" },
  point_on: { label: "Point on", glyph: "O" },
  horizontal: { label: "Horizontal", glyph: "H" },
  vertical: { label: "Vertical", glyph: "V" },
  points_horizontal: { label: "Align horizontally", glyph: "H" },
  points_vertical: { label: "Align vertically", glyph: "V" },
  parallel: { label: "Parallel", glyph: "//" },
  perpendicular: { label: "Perpendicular", glyph: "L" },
  collinear: { label: "Collinear", glyph: "==" },
  tangent: { label: "Tangent", glyph: "T" },
  concentric: { label: "Concentric", glyph: "@" },
  midpoint: { label: "Midpoint", glyph: "M" },
  symmetric: { label: "Symmetric", glyph: "S" },
  equal_length: { label: "Equal length", glyph: "=" },
  equal_radius: { label: "Equal radius", glyph: "=R" },
  length: { label: "Length", unit: "mm", glyph: "" },
  distance: { label: "Distance", unit: "mm", glyph: "" },
  distance_x: { label: "Distance X", unit: "mm", glyph: "" },
  distance_y: { label: "Distance Y", unit: "mm", glyph: "" },
  line_distance: { label: "Line distance", unit: "mm", glyph: "" },
  angle: { label: "Angle", unit: "deg", glyph: "" },
  radius: { label: "Radius", unit: "mm", glyph: "R" },
  diameter: { label: "Diameter", unit: "mm", glyph: "D" },
};

export const isDimensional = (kind: ConstraintKind) => CONSTRAINT_INFO[kind].unit !== undefined;

// -- document -------------------------------------------------------------------------------------------------------

export function emptyDoc(plane: PlaneSpec = "XY"): SketchDoc {
  return { plane, points: [], entities: [], constraints: [], profile: 0, inner: [], fully_constrained: false };
}

/** A document from whatever the recipe stored (missing parts filled in, wrong types dropped). */
export function normalizeDoc(raw: unknown): SketchDoc {
  const source = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const list = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
  const plane = normalizePlane(source.plane);
  const num = (value: unknown, fallback = 0) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
  return {
    plane,
    points: list<SPoint>(source.points).map((p) => ({ id: String(p.id), x: num(p.x), y: num(p.y) })),
    entities: list<SEntity>(source.entities).map((e) => ({ ...e, construction: Boolean(e.construction) })),
    constraints: list<SConstraint>(source.constraints).map((c) => ({ ...c, targets: list<string>(c.targets).map(String) })),
    profile: Number.isInteger(source.profile) && (source.profile as number) >= 0 ? (source.profile as number) : 0,
    inner: list<number>(source.inner).filter((i) => Number.isInteger(i) && i >= 0),
    fully_constrained: Boolean(source.fully_constrained),
  };
}

/** The JSON the server takes (a plain deep copy; the round trip normalizeDoc(docToJson(d)) is the identity). */
export function docToJson(doc: SketchDoc): SketchDoc {
  return JSON.parse(JSON.stringify(doc)) as SketchDoc;
}

export function usedIds(doc: SketchDoc): Set<string> {
  return new Set([...doc.points.map((p) => p.id), ...doc.entities.map((e) => e.id), ...doc.constraints.map((c) => c.id)]);
}

/** The next free id with a prefix: p1, l1, c1, a1 (points, lines, circles, arcs) and k1 (constraints). */
export function nextId(prefix: string, doc: SketchDoc): string {
  const used = usedIds(doc);
  for (let n = 1; ; n++) if (!used.has(`${prefix}${n}`)) return `${prefix}${n}`;
}

const ENTITY_PREFIX: Record<EntityKind, string> = { line: "l", circle: "c", arc: "a", bspline: "s" };
export const entityPrefix = (kind: EntityKind) => ENTITY_PREFIX[kind];

export const pointMap = (doc: SketchDoc) => new Map(doc.points.map((p) => [p.id, p] as const));
export const entityMap = (doc: SketchDoc) => new Map(doc.entities.map((e) => [e.id, e] as const));

export type ItemKind = "point" | EntityKind;
export function itemKind(doc: SketchDoc, id: string): ItemKind | null {
  if (doc.points.some((p) => p.id === id)) return "point";
  return doc.entities.find((e) => e.id === id)?.kind ?? null;
}

export const baseOf = (target: string) => target.split(".")[0];

export function entityPointIds(e: SEntity): string[] {
  const ids = [e.start, e.center, e.end, ...(e.control_points ?? [])].filter((id): id is string => Boolean(id));
  return [...new Set(ids)];
}

/** The path of a B-spline: the SDK's samples of the last solve, else its control polygon (until the solve answers). */
export function splinePath(e: SEntity, pts: Map<string, [number, number]>, solve: SolveResult | null): [number, number][] {
  const drawn = solve?.curves?.[e.id]?.points;
  if (drawn && drawn.length > 1) return drawn;
  return (e.control_points ?? []).map((id) => pts.get(id)).filter((p): p is [number, number] => Boolean(p));
}

function polylineDistance(pos: readonly [number, number], path: readonly [number, number][]): number {
  let best = Infinity;
  for (let i = 0; i + 1 < path.length; i++) best = Math.min(best, segmentDistance(pos, path[i], path[i + 1]));
  return best;
}

/** Points with positions from the last solve laid over the seeds (what the canvas draws). */
export function solvedPoints(doc: SketchDoc, solve: SolveResult | null): Map<string, [number, number]> {
  const out = new Map<string, [number, number]>();
  for (const p of doc.points) out.set(p.id, solve?.points?.[p.id] ?? [p.x, p.y]);
  return out;
}

export function circleRadius(doc: SketchDoc, e: SEntity, pts: Map<string, [number, number]>, solve: SolveResult | null): number {
  if (e.kind === "circle") {
    const solved = solve?.entities?.[e.id]?.radius;
    return typeof solved === "number" ? solved : (e.radius ?? 1);
  }
  const c = pts.get(e.center ?? "");
  const s = pts.get(e.start ?? "");
  return c && s ? Math.hypot(s[0] - c[0], s[1] - c[1]) : 0;
}

// -- editing --------------------------------------------------------------------------------------------------------

/** A B-spline through the control points at `spots` (existing points are reused): degree 3, or less with fewer points.
 * A spline that ends on its first point is closed (one seam point). */
export function addSpline(doc: SketchDoc, spots: readonly Spot[], opts: DrawOptions): { doc: SketchDoc; id: string } | null {
  let next = doc;
  const ids: string[] = [];
  for (const spot of spots) {
    const made = ensurePoint(next, spot);
    next = made.doc;
    if (ids[ids.length - 1] !== made.id) ids.push(made.id);
  }
  if (ids.length < 2) return null;
  const degree = Math.min(3, ids.length - 1);
  const id = nextId("s", next);
  const entity: SEntity = { id, kind: "bspline", start: ids[0], end: ids[ids.length - 1], control_points: ids, degree, construction: opts.construction };
  return { doc: { ...next, entities: [...next.entities, entity] }, id };
}

const round = (v: number) => Math.round(v * 1e4) / 1e4;

export type Spot = { x: number; y: number; pointId?: string };

/** The point a spot names (an existing one) or a new one at its position. */
export function ensurePoint(doc: SketchDoc, spot: Spot): { doc: SketchDoc; id: string; created: boolean } {
  if (spot.pointId && doc.points.some((p) => p.id === spot.pointId)) return { doc, id: spot.pointId, created: false };
  const id = nextId("p", doc);
  return { doc: { ...doc, points: [...doc.points, { id, x: round(spot.x), y: round(spot.y) }] }, id, created: true };
}

export function addConstraint(doc: SketchDoc, c: Omit<SConstraint, "id">): SketchDoc {
  return { ...doc, constraints: [...doc.constraints, { ...c, id: nextId("k", doc) }] };
}

export type DrawOptions = { auto: boolean; construction: boolean; thresholdDeg?: number };

/** A line from an existing point to a spot; near horizontal or vertical lines get the constraint when `auto`. */
export function addLine(doc: SketchDoc, startId: string, end: Spot, opts: DrawOptions): { doc: SketchDoc; lineId: string; endId: string; reused: boolean } | null {
  const start = doc.points.find((p) => p.id === startId);
  if (!start) return null;
  const ensured = ensurePoint(doc, end);
  if (ensured.id === startId) return null;
  let next = ensured.doc;
  const lineId = nextId("l", next);
  const entity: SEntity = { id: lineId, kind: "line", start: startId, end: ensured.id, construction: opts.construction };
  next = { ...next, entities: [...next.entities, entity] };
  if (opts.auto) {
    const e = next.points.find((p) => p.id === ensured.id)!;
    const dx = e.x - start.x;
    const dy = e.y - start.y;
    const angle = (Math.atan2(Math.abs(dy), Math.abs(dx)) * 180) / Math.PI;
    const limit = opts.thresholdDeg ?? 3;
    if (angle <= limit && dx !== 0) {
      if (ensured.created) next = { ...next, points: next.points.map((p) => (p.id === ensured.id ? { ...p, y: start.y } : p)) };
      next = addConstraint(next, { kind: "horizontal", targets: [lineId] });
    } else if (90 - angle <= limit && dy !== 0) {
      if (ensured.created) next = { ...next, points: next.points.map((p) => (p.id === ensured.id ? { ...p, x: start.x } : p)) };
      next = addConstraint(next, { kind: "vertical", targets: [lineId] });
    }
  }
  return { doc: next, lineId, endId: ensured.id, reused: !ensured.created };
}

export function addCircle(doc: SketchDoc, center: Spot, rim: { x: number; y: number }, opts: DrawOptions): { doc: SketchDoc; id: string } | null {
  const c0 = doc.points.find((p) => p.id === center.pointId);
  const cx = c0 ? c0.x : center.x;
  const cy = c0 ? c0.y : center.y;
  const radius = round(Math.hypot(rim.x - cx, rim.y - cy));
  if (!(radius > 1e-6)) return null;
  const ensured = ensurePoint(doc, center);
  const id = nextId("c", ensured.doc);
  const entity: SEntity = { id, kind: "circle", center: ensured.id, radius, construction: opts.construction };
  return { doc: { ...ensured.doc, entities: [...ensured.doc.entities, entity] }, id };
}

/** An arc (counter-clockwise from start to end): the start point sets the radius, the end is projected onto the circle. */
export function addArc(doc: SketchDoc, center: Spot, start: Spot, end: { x: number; y: number }, opts: DrawOptions): { doc: SketchDoc; id: string } | null {
  const c0 = doc.points.find((p) => p.id === center.pointId);
  const cx = c0 ? c0.x : center.x;
  const cy = c0 ? c0.y : center.y;
  const radius = Math.hypot(start.x - cx, start.y - cy);
  const along = Math.hypot(end.x - cx, end.y - cy);
  if (!(radius > 1e-6) || !(along > 1e-6)) return null;
  const endSpot: Spot = { x: cx + ((end.x - cx) / along) * radius, y: cy + ((end.y - cy) / along) * radius };
  let step = ensurePoint(doc, center);
  const centerId = step.id;
  const a = ensurePoint(step.doc, start);
  const b = ensurePoint(a.doc, endSpot);
  if (a.id === b.id) return null;
  const id = nextId("a", b.doc);
  const entity: SEntity = { id, kind: "arc", center: centerId, start: a.id, end: b.id, construction: opts.construction };
  return { doc: { ...b.doc, entities: [...b.doc.entities, entity] }, id };
}

/** Does this constraint name the id (as a point or entity, with or without a ".start" suffix)? */
const mentions = (c: SConstraint, ids: ReadonlySet<string>) => c.targets.some((t) => ids.has(baseOf(t)));

function dropOrphanPoints(doc: SketchDoc, candidates: Iterable<string>): SketchDoc {
  const gone = new Set<string>();
  for (const id of candidates) {
    const held = doc.entities.some((e) => entityPointIds(e).includes(id));
    const named = doc.constraints.some((c) => c.targets.some((t) => baseOf(t) === id));
    if (!held && !named) gone.add(id);
  }
  return gone.size ? { ...doc, points: doc.points.filter((p) => !gone.has(p.id)) } : doc;
}

export function removeConstraint(doc: SketchDoc, id: string): SketchDoc {
  return { ...doc, constraints: doc.constraints.filter((c) => c.id !== id) };
}

export function removeEntity(doc: SketchDoc, id: string): SketchDoc {
  const entity = doc.entities.find((e) => e.id === id);
  if (!entity) return doc;
  const next = { ...doc, entities: doc.entities.filter((e) => e.id !== id), constraints: doc.constraints.filter((c) => !mentions(c, new Set([id]))) };
  return dropOrphanPoints(next, entityPointIds(entity));
}

/** A point goes with every entity and constraint that uses it. */
export function removePoint(doc: SketchDoc, id: string): SketchDoc {
  let next = doc;
  for (const e of doc.entities) if (entityPointIds(e).includes(id)) next = removeEntity(next, e.id);
  return { ...next, points: next.points.filter((p) => p.id !== id), constraints: next.constraints.filter((c) => !mentions(c, new Set([id]))) };
}

export function removeItems(doc: SketchDoc, ids: readonly string[]): SketchDoc {
  let next = doc;
  for (const id of ids) {
    const kind = itemKind(next, id);
    if (kind === "point") next = removePoint(next, id);
    else if (kind) next = removeEntity(next, id);
  }
  return next;
}

export function setConstruction(doc: SketchDoc, ids: readonly string[], value: boolean): SketchDoc {
  const set = new Set(ids);
  return { ...doc, entities: doc.entities.map((e) => (set.has(e.id) ? { ...e, construction: value } : e)) };
}

/** Write solved coordinates (and radii) back into the seeds, so the document is visually consistent. */
export function applySolved(doc: SketchDoc, solve: SolveResult): SketchDoc {
  return {
    ...doc,
    points: doc.points.map((p) => {
      const s = solve.points?.[p.id];
      return s ? { ...p, x: round(s[0]), y: round(s[1]) } : p;
    }),
    entities: doc.entities.map((e) => {
      const r = e.kind === "circle" ? solve.entities?.[e.id]?.radius : undefined;
      return typeof r === "number" && r > 0 ? { ...e, radius: round(r) } : e;
    }),
  };
}

/** Largest change a solve makes to the seeds (to know when writing back is worth a re-render). */
export function seedDelta(doc: SketchDoc, solve: SolveResult): number {
  let worst = 0;
  for (const p of doc.points) {
    const s = solve.points?.[p.id];
    if (s) worst = Math.max(worst, Math.abs(s[0] - p.x), Math.abs(s[1] - p.y));
  }
  for (const e of doc.entities) {
    const r = e.kind === "circle" ? solve.entities?.[e.id]?.radius : undefined;
    if (typeof r === "number") worst = Math.max(worst, Math.abs(r - (e.radius ?? r)));
  }
  return worst;
}

export const writable = (solve: SolveResult | null) => Boolean(solve && (solve.status === "solved" || solve.status === "underconstrained"));

// -- constraints for a selection --------------------------------------------------------------------------------------

export const CONSTRAINT_ORDER: ConstraintKind[] = [
  "horizontal", "vertical", "points_horizontal", "points_vertical", "coincident", "point_on", "midpoint", "parallel", "perpendicular",
  "collinear", "tangent", "concentric", "equal_length", "equal_radius", "symmetric", "fix",
  "length", "distance", "distance_x", "distance_y", "line_distance", "angle", "radius", "diameter",
];

type Sel = { id: string; kind: ItemKind };
function classify(selection: readonly string[], doc: SketchDoc): Sel[] | null {
  const out: Sel[] = [];
  for (const id of selection) {
    const kind = itemKind(doc, id);
    if (!kind) return null;
    out.push({ id, kind });
  }
  return out;
}

const isRound = (s: Sel) => s.kind === "circle" || s.kind === "arc";

/** The constraint kinds that apply to the selection (ids of points and entities), in toolbar order. */
export function applicableConstraints(selection: readonly string[], doc: SketchDoc): ConstraintKind[] {
  const sel = classify(selection, doc);
  if (!sel || sel.length === 0) return [];
  const points = sel.filter((s) => s.kind === "point");
  const lines = sel.filter((s) => s.kind === "line");
  const rounds = sel.filter(isRound);
  const out = new Set<ConstraintKind>();
  if (points.length >= 1) out.add("fix");
  if (sel.length === 1) {
    if (lines.length) ["horizontal", "vertical", "length"].forEach((k) => out.add(k as ConstraintKind));
    if (rounds.length) ["radius", "diameter"].forEach((k) => out.add(k as ConstraintKind));
  } else if (sel.length === 2) {
    if (points.length === 2) ["coincident", "distance", "distance_x", "distance_y", "points_horizontal", "points_vertical"].forEach((k) => out.add(k as ConstraintKind));
    if (lines.length === 2) ["parallel", "perpendicular", "equal_length", "collinear", "angle", "line_distance"].forEach((k) => out.add(k as ConstraintKind));
    if (points.length === 1 && lines.length === 1) ["point_on", "midpoint"].forEach((k) => out.add(k as ConstraintKind));
    if (points.length === 1 && rounds.length === 1) out.add("point_on");
    if (rounds.length === 2) ["equal_radius", "concentric", "tangent"].forEach((k) => out.add(k as ConstraintKind));
    if (lines.length === 1 && rounds.length === 1) out.add("tangent");
  } else if (sel.length === 3 && points.length === 2 && lines.length === 1) out.add("symmetric");
  // lines and arcs alone: join them end to end (a chain, or a closed outline)
  if (sel.length >= 2 && sel.every((s) => s.kind === "line" || s.kind === "arc")) out.add("coincident");
  return CONSTRAINT_ORDER.filter((k) => out.has(k));
}

/** The targets (positional, as the server wants them) for one application of `kind` to the selection; fix makes one per point. */
export function constraintTargets(kind: ConstraintKind, selection: readonly string[], doc: SketchDoc): string[][] {
  if (!applicableConstraints(selection, doc).includes(kind)) return [];
  const sel = classify(selection, doc)!;
  const ofKind = (...kinds: ItemKind[]) => sel.filter((s) => kinds.includes(s.kind)).map((s) => s.id);
  const points = ofKind("point");
  const lines = ofKind("line");
  const rounds = ofKind("circle", "arc");
  switch (kind) {
    case "fix":
      return points.map((p) => [p]);
    case "horizontal":
    case "vertical":
    case "length":
      return [[lines[0]]];
    case "radius":
    case "diameter":
      return [[rounds[0]]];
    case "point_on":
      return [[points[0], lines[0] ?? rounds[0]]];
    case "midpoint":
      return [[points[0], lines[0]]];
    case "tangent":
      return [lines.length ? [lines[0], rounds[0]] : [rounds[0], rounds[1]]];
    case "symmetric":
      return [[points[0], points[1], lines[0]]];
    case "coincident":
      if (points.length === 0) return chainCoincidences(sel.map((s) => s.id), doc);
      return [sel.map((s) => s.id)];
    default:
      return [sel.map((s) => s.id)];
  }
}

/** Join lines and arcs end to end: a coincidence for every neighbouring pair of a chain, by where the ends are.
 *
 * The chain starts at the first selected entity and goes on with the entity whose end lies nearest to the chain's open end (so
 * the order of the clicks does not matter); each link joins that pair of ends.  The two open ends of the finished chain are joined
 * too when they are close compared to the shortest member (an outline that was drawn open).  A link that is already one point is skipped. */
export function chainCoincidences(ids: readonly string[], doc: SketchDoc): string[][] {
  const ents = entityMap(doc);
  const at = (pid: string | undefined): [number, number] | null => {
    const p = doc.points.find((q) => q.id === pid);
    return p ? [p.x, p.y] : null;
  };
  type Member = { id: string; ends: [string, string] };
  const members: Member[] = [];
  for (const id of ids) {
    const e = ents.get(id);
    if (e && (e.kind === "line" || e.kind === "arc") && e.start && e.end) members.push({ id, ends: [e.start, e.end] });
  }
  if (members.length < 2) return [];
  const dist = (a: string, b: string) => {
    if (a === b) return 0;
    const p = at(a);
    const q = at(b);
    return p && q ? Math.hypot(p[0] - q[0], p[1] - q[1]) : Infinity;
  };
  const out: string[][] = [];
  const link = (a: string, b: string) => {
    if (a !== b) out.push([a, b]);
  };
  const placed = [members[0]];
  let open: [string, string] = members[0].ends; // [tail, head] of the chain
  const rest = members.slice(1);
  while (rest.length) {
    let best: { index: number; at: 0 | 1; from: 0 | 1; gap: number } | null = null;
    rest.forEach((m, index) => {
      for (const from of [0, 1] as const)
        for (const to of [0, 1] as const) {
          const gap = dist(open[from], m.ends[to]);
          if (!best || gap < best.gap) best = { index, at: to, from, gap };
        }
    });
    const pick = best!;
    const next = rest.splice(pick.index, 1)[0];
    link(open[pick.from], next.ends[pick.at]);
    const far = next.ends[pick.at === 0 ? 1 : 0];
    open = pick.from === 1 ? [open[0], far] : [far, open[1]];
    placed.push(next);
  }
  if (placed.length >= 3) {
    const shortest = Math.min(...placed.map((m) => dist(m.ends[0], m.ends[1])));
    const gap = dist(open[0], open[1]);
    if (gap > 0 && gap <= 0.5 * shortest) link(open[0], open[1]);
  }
  return out;
}

// -- measured values ----------------------------------------------------------------------------------------------------

/** The current measured value of a dimension (mm or deg) from the solved geometry, or null when it cannot be measured. */
export function measure(kind: ConstraintKind, targets: readonly string[], doc: SketchDoc, solve: SolveResult | null): number | null {
  const pts = solvedPoints(doc, solve);
  const ents = entityMap(doc);
  const lineEnds = (id: string): [[number, number], [number, number]] | null => {
    const e = ents.get(baseOf(id));
    const a = pts.get(e?.start ?? "");
    const b = pts.get(e?.end ?? "");
    return e?.kind === "line" && a && b ? [a, b] : null;
  };
  const pointAt = (t: string) => pts.get(baseOf(t)) ?? null;
  switch (kind) {
    case "length": {
      const l = lineEnds(targets[0]);
      return l ? Math.hypot(l[1][0] - l[0][0], l[1][1] - l[0][1]) : null;
    }
    case "radius":
    case "diameter": {
      const e = ents.get(targets[0]);
      if (!e) return null;
      const r = circleRadius(doc, e, pts, solve);
      return kind === "radius" ? r : 2 * r;
    }
    case "distance":
    case "distance_x":
    case "distance_y": {
      const a = pointAt(targets[0]);
      const b = pointAt(targets[1]);
      if (!a || !b) return null;
      if (kind === "distance_x") return b[0] - a[0];
      if (kind === "distance_y") return b[1] - a[1];
      return Math.hypot(b[0] - a[0], b[1] - a[1]);
    }
    case "line_distance": {
      const a = lineEnds(targets[0]);
      const b = lineEnds(targets[1]);
      if (!a || !b) return null;
      const dx = a[1][0] - a[0][0];
      const dy = a[1][1] - a[0][1];
      const len = Math.hypot(dx, dy);
      if (!(len > 1e-12)) return null;
      const mx = (b[0][0] + b[1][0]) / 2 - a[0][0];
      const my = (b[0][1] + b[1][1]) / 2 - a[0][1];
      return Math.abs(dx * my - dy * mx) / len;
    }
    case "angle": {
      const a = lineEnds(targets[0]);
      const b = lineEnds(targets[1]);
      if (!a || !b) return null;
      const ax = a[1][0] - a[0][0];
      const ay = a[1][1] - a[0][1];
      const bx = b[1][0] - b[0][0];
      const by = b[1][1] - b[0][1];
      return (Math.abs(Math.atan2(ax * by - ay * bx, ax * bx + ay * by)) * 180) / Math.PI;
    }
    default:
      return null;
  }
}

/** The value a reference or driving dimension displays: for reference dimensions the solver reports it as a scalar. */
export function dimensionValue(c: SConstraint, doc: SketchDoc, solve: SolveResult | null): number | null {
  if (c.driving === false) {
    const scalar = solve?.scalars?.[`constraint:${c.id}:value`];
    if (typeof scalar === "number") return scalar;
    return measure(c.kind, c.targets, doc, solve);
  }
  return c.value ?? null;
}

export function formatValue(value: number | null, kind: ConstraintKind): string {
  if (value === null) return "?";
  const text = String(Math.round(value * 100) / 100);
  return kind === "angle" ? `${text}°` : text;
}

/** Parse the value box text: a finite number, positive unless the kind allows a sign. */
export function parseDimension(text: string, kind: ConstraintKind): number | null {
  const trimmed = text.trim().replace(/°|mm$/g, "").trim();
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  if (value <= 0 && kind !== "distance_x" && kind !== "distance_y") return null;
  return value;
}

// -- view, snapping ------------------------------------------------------------------------------------------------------

export type View = { scale: number; ox: number; oy: number };
export const worldToScreen = (v: View, x: number, y: number): [number, number] => [v.ox + x * v.scale, v.oy - y * v.scale];
export const screenToWorld = (v: View, sx: number, sy: number): [number, number] => [(sx - v.ox) / v.scale, (v.oy - sy) / v.scale];

/** Zoom by `factor` keeping the world point under the cursor fixed. */
export function zoomAt(v: View, sx: number, sy: number, factor: number): View {
  const scale = Math.min(Math.max(v.scale * factor, 0.05), 4000);
  const [wx, wy] = screenToWorld(v, sx, sy);
  return { scale, ox: sx - wx * scale, oy: sy + wy * scale };
}

/** A "nice" grid step (mm) that is at least `minPx` wide on screen. */
export function gridStep(scale: number, minPx = 14): number {
  for (let decade = 0.01; decade < 1e6; decade *= 10) {
    for (const m of [1, 2, 5]) if (decade * m * scale >= minPx) return decade * m;
  }
  return 1e6;
}

export type Snap = { x: number; y: number; pointId?: string; kind: "point" | "grid" | "free" };

/** Snap a world position to a nearby point (within `tol` world units) or to the grid; points beat the grid. */
export function snap(pos: readonly [number, number], points: ReadonlyMap<string, [number, number]>, opts: { grid: number | null; tol: number; skip?: ReadonlySet<string> }): Snap {
  let best: { id: string; d: number } | null = null;
  for (const [id, p] of points) {
    if (opts.skip?.has(id)) continue;
    const d = Math.hypot(p[0] - pos[0], p[1] - pos[1]);
    if (d <= opts.tol && (!best || d < best.d)) best = { id, d };
  }
  if (best) {
    const p = points.get(best.id)!;
    return { x: p[0], y: p[1], pointId: best.id, kind: "point" };
  }
  if (opts.grid) return { x: round(Math.round(pos[0] / opts.grid) * opts.grid), y: round(Math.round(pos[1] / opts.grid) * opts.grid), kind: "grid" };
  return { x: pos[0], y: pos[1], kind: "free" };
}

// -- hit testing ----------------------------------------------------------------------------------------------------------

function segmentDistance(p: readonly [number, number], a: readonly [number, number], b: readonly [number, number]): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 > 0 ? Math.min(1, Math.max(0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0;
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** The arc's sweep angle counter-clockwise from start to end, in (0, 2pi]. */
export function arcSweep(c: readonly [number, number], s: readonly [number, number], e: readonly [number, number]): number {
  const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
  const a1 = Math.atan2(e[1] - c[1], e[0] - c[0]);
  let d = a1 - a0;
  while (d <= 1e-9) d += 2 * Math.PI;
  return d;
}

export function sampleArc(c: readonly [number, number], s: readonly [number, number], e: readonly [number, number], steps = 24): [number, number][] {
  const r = Math.hypot(s[0] - c[0], s[1] - c[1]);
  const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
  const sweep = arcSweep(c, s, e);
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) out.push([c[0] + r * Math.cos(a0 + (sweep * i) / steps), c[1] + r * Math.sin(a0 + (sweep * i) / steps)]);
  out[0] = [s[0], s[1]];
  out[steps] = [e[0], e[1]];
  return out;
}

/** Distance (world units) from a position to an entity. */
export function entityDistance(doc: SketchDoc, e: SEntity, pos: readonly [number, number], pts: Map<string, [number, number]>, solve: SolveResult | null): number {
  if (e.kind === "bspline") return polylineDistance(pos, splinePath(e, pts, solve));
  if (e.kind === "line") {
    const a = pts.get(e.start ?? "");
    const b = pts.get(e.end ?? "");
    return a && b ? segmentDistance(pos, a, b) : Infinity;
  }
  const c = pts.get(e.center ?? "");
  if (!c) return Infinity;
  const r = circleRadius(doc, e, pts, solve);
  const d = Math.hypot(pos[0] - c[0], pos[1] - c[1]);
  if (e.kind === "circle") return Math.abs(d - r);
  const s = pts.get(e.start ?? "");
  const en = pts.get(e.end ?? "");
  if (!s || !en) return Infinity;
  const a0 = Math.atan2(s[1] - c[1], s[0] - c[0]);
  const sweep = arcSweep(c, s, en);
  let da = Math.atan2(pos[1] - c[1], pos[0] - c[0]) - a0;
  while (da < 0) da += 2 * Math.PI;
  if (da <= sweep) return Math.abs(d - r);
  return Math.min(Math.hypot(pos[0] - s[0], pos[1] - s[1]), Math.hypot(pos[0] - en[0], pos[1] - en[1]));
}

export type Hit = { kind: "point" | "entity"; id: string };

/** What is under a position: points first, then the nearest entity within `tol` (world units). */
export function hitTest(doc: SketchDoc, solve: SolveResult | null, pos: readonly [number, number], tol: number): Hit | null {
  const pts = solvedPoints(doc, solve);
  let best: { id: string; d: number } | null = null;
  for (const [id, p] of pts) {
    const d = Math.hypot(p[0] - pos[0], p[1] - pos[1]);
    if (d <= tol && (!best || d < best.d)) best = { id, d };
  }
  if (best) return { kind: "point", id: best.id };
  let hit: { id: string; d: number } | null = null;
  for (const e of doc.entities) {
    const d = entityDistance(doc, e, pos, pts, solve);
    if (d <= tol && (!hit || d < hit.d)) hit = { id: e.id, d };
  }
  return hit ? { kind: "entity", id: hit.id } : null;
}

/** The nearest entity within `tol` of a position (never a point): what a trim or extend click points at. */
export function entityHit(doc: SketchDoc, solve: SolveResult | null, pos: readonly [number, number], tol: number): Hit | null {
  const pts = solvedPoints(doc, solve);
  let hit: { id: string; d: number } | null = null;
  for (const e of doc.entities) {
    const d = entityDistance(doc, e, pos, pts, solve);
    if (d <= tol && (!hit || d < hit.d)) hit = { id: e.id, d };
  }
  return hit ? { kind: "entity", id: hit.id } : null;
}

// -- drag: the temporary fix ----------------------------------------------------------------------------------------------

export const TEMP_PREFIX = "tmp";

/** The points a drag of an item moves: a point itself, a line's ends, a circle's centre, an arc's three points. */
export function dragPoints(doc: SketchDoc, id: string): string[] {
  const e = doc.entities.find((x) => x.id === id);
  if (e) return entityPointIds(e);
  return doc.points.some((p) => p.id === id) ? [id] : [];
}

export function isFixed(doc: SketchDoc, pointId: string): boolean {
  return doc.constraints.some((c) => c.kind === "fix" && baseOf(c.targets[0]) === pointId);
}

/** The document the solver sees during a drag: the dragged points moved to `positions` and each held by a temporary fix. */
export function dragDoc(doc: SketchDoc, positions: Readonly<Record<string, [number, number]>>): SketchDoc {
  const ids = Object.keys(positions);
  return {
    ...doc,
    points: doc.points.map((p) => (positions[p.id] ? { ...p, x: positions[p.id][0], y: positions[p.id][1] } : p)),
    constraints: [...doc.constraints, ...ids.map((id, i) => ({ id: `${TEMP_PREFIX}${i + 1}`, kind: "fix" as const, targets: [id] }))],
  };
}

export const stripTemp = (doc: SketchDoc): SketchDoc => ({ ...doc, constraints: doc.constraints.filter((c) => !c.id.startsWith(TEMP_PREFIX) || !/^tmp\d+$/.test(c.id)) });

// -- loops and profiles ---------------------------------------------------------------------------------------------------

export type Loop = {
  /** Stable identity: the sorted ids of its entities. */
  key: string;
  entities: string[];
  polygon: [number, number][];
  area: number;
  centroid: [number, number];
  /** The index of its SDK profile: what the face is made with. */
  index: number | null;
};

export function polygonArea(poly: readonly [number, number][]): { area: number; centroid: [number, number] } {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % poly.length];
    const cross = x0 * y1 - x1 * y0;
    a += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  if (Math.abs(a) < 1e-12) return { area: 0, centroid: poly[0] ?? [0, 0] };
  return { area: a / 2, centroid: [cx / (3 * a), cy / (3 * a)] };
}

export function pointInPolygon(p: readonly [number, number], poly: readonly [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** The closed loops of the sketch: the SDK's own closed profiles (``inspect_sketch_rsketchprofiles``), drawn from the solved
 * geometry. There is no second opinion on what a loop is: a loop exists when the SDK offers it as a profile, and its `index` is
 * the one the face is made with. */
export function findLoops(doc: SketchDoc, solve: SolveResult | null): Loop[] {
  const pts = solvedPoints(doc, solve);
  const byId = new Map(doc.entities.map((e) => [e.id, e]));
  const loops: Loop[] = [];
  for (const profile of solve?.profiles ?? []) {
    if (!profile.closed || profile.entity_ids.length === 0) continue;
    const entities = profile.entity_ids.map((id) => byId.get(id));
    if (entities.some((e) => !e)) continue; // a result older than the document
    let polygon: [number, number][] = [];
    let area = 0;
    let centroid: [number, number] = [0, 0];
    if (profile.kind === "circle") {
      const e = entities[0]!;
      const c = pts.get(e.center ?? "");
      const r = circleRadius(doc, e, pts, solve);
      if (!c || !(r > 0)) continue;
      polygon = Array.from({ length: 48 }, (_, i) => [c[0] + r * Math.cos((2 * Math.PI * i) / 48), c[1] + r * Math.sin((2 * Math.PI * i) / 48)]);
      area = Math.PI * r * r;
      centroid = [c[0], c[1]];
    } else if (profile.kind === "edge_loop") {
      let broken = false;
      profile.entity_ids.forEach((_, i) => {
        const e = entities[i]!;
        const s = pts.get(e.start ?? "");
        const t = pts.get(e.end ?? "");
        const c = e.kind === "arc" ? pts.get(e.center ?? "") : undefined;
        if (e.kind === "bspline") {
          let path = splinePath(e, pts, solve);
          if (profile.reversed[i]) path = [...path].reverse();
          if (path.length < 2) broken = true;
          else polygon.push(...path.slice(0, -1));
          return;
        }
        if (!s || !t || (e.kind === "arc" && !c)) {
          broken = true;
          return;
        }
        let path: [number, number][] = e.kind === "arc" ? sampleArc(c!, s, t) : [s, t];
        if (profile.reversed[i]) path = [...path].reverse();
        polygon.push(...path.slice(0, -1));
      });
      if (broken || polygon.length < 3) continue;
      ({ area, centroid } = polygonArea(polygon));
      area = Math.abs(area);
    } else continue;
    loops.push({ key: [...profile.entity_ids].sort().join("+"), entities: profile.entity_ids, polygon, area, centroid, index: profile.index });
  }
  return loops;
}

/** The loop under a position: the smallest one containing it. */
export function loopAt(loops: readonly Loop[], pos: readonly [number, number]): Loop | null {
  let best: Loop | null = null;
  for (const loop of loops) if (pointInPolygon(pos, loop.polygon) && (!best || loop.area < best.area)) best = loop;
  return best;
}

export type Choice = { outer: string | null; inner: string[]; chosen: boolean };

/** The loops chosen as outer profile and holes, kept across edits by identity; an unchosen outer defaults to the largest loop. */
export function reconcileChoice(choice: Choice, loops: readonly Loop[]): Choice {
  const keys = new Set(loops.map((l) => l.key));
  let outer = choice.outer && keys.has(choice.outer) ? choice.outer : null;
  if (!outer && !choice.chosen && loops.length) outer = [...loops].sort((a, b) => b.area - a.area)[0].key;
  const inner = choice.inner.filter((k) => keys.has(k) && k !== outer);
  return outer === choice.outer && inner.length === choice.inner.length ? choice : { ...choice, outer, inner };
}

/** The initial choice of an existing document: its profile and inner indices resolved to loops. */
export function choiceFromDoc(doc: SketchDoc, loops: readonly Loop[]): Choice {
  const byIndex = (i: number) => loops.find((l) => l.index === i)?.key ?? null;
  return { outer: byIndex(doc.profile), inner: doc.inner.map(byIndex).filter((k): k is string => Boolean(k)), chosen: doc.points.length > 0 };
}

/** The profile / inner indices a choice means, for the loops the server listed. */
export function choiceToIndices(choice: Choice, loops: readonly Loop[]): { profile: number; inner: number[] } {
  const index = (key: string | null) => loops.find((l) => l.key === key)?.index ?? null;
  const profile = index(choice.outer);
  return {
    profile: profile ?? 0,
    inner: choice.inner.map(index).filter((i): i is number => i !== null),
  };
}

/** Click or shift-click on a loop: a click makes it the outer profile, shift toggles it as a hole. */
export function pickLoop(choice: Choice, key: string, shift: boolean): Choice {
  if (shift) {
    if (key === choice.outer) return choice;
    const inner = choice.inner.includes(key) ? choice.inner.filter((k) => k !== key) : [...choice.inner, key];
    return { ...choice, inner, chosen: true };
  }
  return { outer: key, inner: choice.inner.filter((k) => k !== key), chosen: true };
}

// -- constraint anchors --------------------------------------------------------------------------------------------------

export type Anchor = { x: number; y: number; nx: number; ny: number; offset: number };

/** Where a constraint's glyph or dimension text sits: a world position and a unit normal to push it away along (px). */
export function constraintAnchor(c: SConstraint, doc: SketchDoc, solve: SolveResult | null): Anchor | null {
  const pts = solvedPoints(doc, solve);
  const ents = entityMap(doc);
  const spot = (t: string): [number, number] | null => {
    const base = baseOf(t);
    const p = pts.get(base);
    if (p) return p;
    const e = ents.get(base);
    if (!e) return null;
    if (e.kind === "line") {
      const a = pts.get(e.start ?? "");
      const b = pts.get(e.end ?? "");
      return a && b ? [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] : null;
    }
    const centre = pts.get(e.center ?? "");
    if (!centre) return null;
    if (e.kind === "circle") return [centre[0] + circleRadius(doc, e, pts, solve) * Math.SQRT1_2, centre[1] + circleRadius(doc, e, pts, solve) * Math.SQRT1_2];
    const s = pts.get(e.start ?? "");
    const en = pts.get(e.end ?? "");
    if (!s || !en) return centre;
    const mid = sampleArc(centre, s, en, 2)[1];
    return mid;
  };
  const first = spot(c.targets[0]);
  if (!first) return null;
  const second = c.targets[1] ? spot(c.targets[1]) : null;
  const e0 = ents.get(baseOf(c.targets[0]));
  let normal: [number, number] = [0, 1];
  if (e0?.kind === "line") {
    const a = pts.get(e0.start ?? "");
    const b = pts.get(e0.end ?? "");
    if (a && b) {
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      normal = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];
      if (normal[1] < -1e-9 || (Math.abs(normal[1]) < 1e-9 && normal[0] < 0)) normal = [-normal[0], -normal[1]];
    }
  } else if (e0) normal = [Math.SQRT1_2, Math.SQRT1_2];
  const at: [number, number] = second && (c.kind === "distance" || c.kind === "distance_x" || c.kind === "distance_y" || c.kind === "line_distance" || c.kind === "angle" || c.kind === "symmetric") ? [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2] : first;
  return { x: at[0], y: at[1], nx: normal[0], ny: normal[1], offset: isDimensional(c.kind) ? 16 : 11 };
}

// -- solver client ----------------------------------------------------------------------------------------------------------

export type SolveFetcher = (doc: SketchDoc) => Promise<SolveResult | null>;

/** One request in flight at a time, the latest wins: `request` resolves with its own result, or null when a newer request
 * replaced it before it was sent. */
export class LatestSolver {
  private busy = false;
  private pending: { doc: SketchDoc; resolve: (r: SolveResult | null) => void } | null = null;
  constructor(private readonly fetcher: SolveFetcher) {}

  request(doc: SketchDoc): Promise<SolveResult | null> {
    return new Promise((resolve) => {
      if (this.pending) this.pending.resolve(null);
      this.pending = { doc, resolve };
      void this.pump();
    });
  }

  private async pump(): Promise<void> {
    if (this.busy) return;
    this.busy = true;
    try {
      while (this.pending) {
        const job = this.pending;
        this.pending = null;
        let result: SolveResult | null = null;
        try {
          result = await this.fetcher(job.doc);
        } catch {
          result = null;
        }
        job.resolve(result);
      }
    } finally {
      this.busy = false;
    }
  }
}

export async function fetchSolve(doc: SketchDoc): Promise<SolveResult | null> {
  const response = await fetch("/api/sketch/solve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sketch: doc }) });
  const body = (await response.json().catch(() => null)) as (SolveResult & { error?: string }) | null;
  if (!response.ok || !body || body.ok === false) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return body;
}

export type Badge = { label: string; tone: "pass" | "fail" | "focus" | "muted" };

export function statusBadge(solve: SolveResult | null, error?: string | null): Badge {
  if (error) return { label: "invalid", tone: "fail" };
  if (!solve) return { label: "solving", tone: "muted" };
  switch (solve.status) {
    case "solved":
      return { label: "solved", tone: "pass" };
    case "underconstrained":
      return { label: `under-constrained ${solve.dof} dof`, tone: "focus" };
    case "conflicting":
      return { label: "conflict", tone: "fail" };
    default:
      return { label: "failed", tone: "fail" };
  }
}

/** Constraint ids the diagnostics blame (errors only). */
export function blamedConstraints(solve: SolveResult | null): Set<string> {
  return new Set((solve?.diagnostics ?? []).filter((d) => d.constraint_id && d.severity === "error").map((d) => d.constraint_id as string));
}
