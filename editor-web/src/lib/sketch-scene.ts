/** Sketches as objects of the 3D scene: the sketch features of the notebook, their solved geometry, how they are drawn
 * and hit.  Pure (no three.js, no React): the scene object lives in scene/sketch-layer.ts, the hook in lib/useSketchShapes.ts.
 * The editor adds no geometry of its own here: the solved points and radii come from the SDK (POST /api/sketch/solve);
 * this file only samples them into polylines for drawing. */

import type { FeatureRow } from "@/lib/features";
import {
  splinePath,
  choiceFromDoc,
  circleRadius,
  findLoops,
  normalizeDoc,
  pointInPolygon,
  reconcileChoice,
  sampleArc,
  solvedPoints,
  type SketchDoc,
  type SolveResult,
} from "@/lib/sketch";
import { planeLabel, planeToWorld, type Vec3 } from "@/lib/sketch-plane";

// -- the sketch features of the notebook ---------------------------------------------------------------------------------------

/** The operations that take a sketch as their profile: a sketch they consume is "used". */
export const SKETCH_CONSUMERS = ["extrude_sketch", "revolve_sketch", "cut_sketch", "boss_sketch"] as const;
export const isSketchConsumer = (spec: string | undefined | null): boolean => Boolean(spec) && (SKETCH_CONSUMERS as readonly string[]).includes(spec as string);

export type SketchInfo = {
  /** What a profile slot names (the body the sketch cell makes). */
  name: string;
  slug: string;
  cell: string;
  doc: SketchDoc;
  /** Changes whenever the document does (the solve cache key). */
  key: string;
  /** The features that consume it (extrude, revolve, cut, boss). */
  usedBy: string[];
  /** False while the sketch's cell makes no body (it failed). */
  built: boolean;
  status: string | null;
};

/** The sketch features of the notebook, in order, with the features that consume each. */
export function sketchInfos(features: readonly FeatureRow[]): SketchInfo[] {
  const consumers = features.filter((feature) => isSketchConsumer(feature.gui?.spec));
  const out: SketchInfo[] = [];
  for (const feature of features) {
    if (feature.gui?.spec !== "sketch") continue;
    const name = feature.makes[0] ?? feature.slug;
    const doc = normalizeDoc((feature.gui.values ?? {}).sketch);
    out.push({
      name,
      slug: feature.slug,
      cell: feature.cell,
      doc,
      key: docKey(doc),
      usedBy: consumers.filter((other) => [name, feature.slug].includes(String(other.gui?.values?.profile ?? ""))).map((other) => other.slug),
      built: feature.makes.length > 0,
      status: feature.status,
    });
  }
  return out;
}

// -- the solve cache -----------------------------------------------------------------------------------------------------------

/** JSON with the keys of every object sorted: the same document always gives the same text. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .filter((key) => record[key] !== undefined)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** A short key of a document (FNV-1a of its stable text, with the length): equal documents, equal keys. */
export function docKey(doc: SketchDoc): string {
  const text = stableStringify(doc);
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `${text.length.toString(36)}-${hash.toString(36)}`;
}

export type SolveEntry = { state: "pending" } | { state: "ok"; result: SolveResult } | { state: "failed"; error: string };

/** Solves of sketch documents by their key: a document is sent once, a changed one is solved again, an unchanged one never. */
export class SolveCache {
  private readonly entries = new Map<string, SolveEntry>();
  private readonly listeners = new Set<() => void>();
  /** How many documents were sent to the server (what tests and the status read). */
  sent = 0;

  constructor(
    private readonly fetcher: (doc: SketchDoc) => Promise<SolveResult>,
    private readonly limit = 96,
  ) {}

  get(key: string): SolveEntry | undefined {
    return this.entries.get(key);
  }

  /** Make sure the document has (or is getting) a solve; returns its key. */
  request(doc: SketchDoc, key: string = docKey(doc)): string {
    if (this.entries.has(key)) return key;
    this.entries.set(key, { state: "pending" });
    if (this.entries.size > this.limit) {
      const oldest = this.entries.keys().next().value;
      if (oldest !== undefined && oldest !== key) this.entries.delete(oldest);
    }
    this.sent += 1;
    this.fetcher(doc).then(
      (result) => this.settle(key, { state: "ok", result }),
      (error: unknown) => this.settle(key, { state: "failed", error: error instanceof Error ? error.message : String(error) }),
    );
    return key;
  }

  private settle(key: string, entry: SolveEntry) {
    if (!this.entries.has(key)) return;
    this.entries.set(key, entry);
    for (const listener of [...this.listeners]) listener();
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => void this.listeners.delete(listener);
  }
}

/** POST /api/sketch/solve: the SDK's solve of a document, without recording anything. */
export async function fetchSolve(doc: SketchDoc): Promise<SolveResult> {
  const response = await fetch("/api/sketch/solve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sketch: doc }) });
  const body = (await response.json().catch(() => null)) as (SolveResult & { error?: string }) | null;
  if (!response.ok || !body || body.ok === false) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return body;
}

// -- the geometry to draw ------------------------------------------------------------------------------------------------------

type UV = [number, number];
export type Curve = { id: string; construction: boolean; uv: UV[] };
export type Region = { outer: UV[]; holes: UV[][] };
export type SketchShape = {
  curves: Curve[];
  /** The profile chosen in the sketch (outer loop minus the holes): what gets lightly filled. */
  regions: Region[];
  loopCount: number;
  /** The solve failed (or has not come yet): the seeds are drawn, in the fail ink when it failed. */
  failed: boolean;
  pending: boolean;
  extent: { min: UV; max: UV } | null;
};

const CIRCLE_STEPS = 96;

/** The polylines of a sketch from the solved points (the seeds when there is no solve), with its loops and chosen profile. */
export function sketchShape(doc: SketchDoc, solve: SolveResult | null, state: { failed?: boolean; pending?: boolean } = {}): SketchShape {
  const usable = solve && solve.status !== "failed" ? solve : null;
  const pts = solvedPoints(doc, usable);
  const curves: Curve[] = [];
  for (const entity of doc.entities) {
    const construction = Boolean(entity.construction);
    if (entity.kind === "circle") {
      const c = pts.get(entity.center ?? "");
      if (!c) continue;
      const r = circleRadius(doc, entity, pts, usable);
      if (!(r > 0)) continue;
      const uv: UV[] = Array.from({ length: CIRCLE_STEPS + 1 }, (_, i) => [c[0] + r * Math.cos((2 * Math.PI * i) / CIRCLE_STEPS), c[1] + r * Math.sin((2 * Math.PI * i) / CIRCLE_STEPS)]);
      curves.push({ id: entity.id, construction, uv });
      continue;
    }
    if (entity.kind === "bspline") {
      const uv = splinePath(entity, pts, usable);
      if (uv.length > 1) curves.push({ id: entity.id, construction, uv });
      continue;
    }
    const s = pts.get(entity.start ?? "");
    const t = pts.get(entity.end ?? "");
    if (!s || !t) continue;
    if (entity.kind === "arc") {
      const c = pts.get(entity.center ?? "");
      if (c) curves.push({ id: entity.id, construction, uv: sampleArc(c, s, t, 40) });
    } else curves.push({ id: entity.id, construction, uv: [s, t] });
  }
  const loops = findLoops(doc, usable);
  let choice = choiceFromDoc(doc, loops);
  if (!choice.outer) choice = reconcileChoice({ outer: null, inner: [], chosen: false }, loops);
  const outer = loops.find((loop) => loop.key === choice.outer);
  const regions: Region[] = outer ? [{ outer: outer.polygon, holes: choice.inner.map((key) => loops.find((loop) => loop.key === key)?.polygon).filter((poly): poly is UV[] => Boolean(poly)) }] : [];
  return { curves, regions, loopCount: loops.length, failed: Boolean(state.failed) || solve?.status === "failed", pending: Boolean(state.pending), extent: extentOf(curves) };
}

function extentOf(curves: readonly Curve[]): SketchShape["extent"] {
  let min: UV = [Infinity, Infinity];
  let max: UV = [-Infinity, -Infinity];
  for (const curve of curves) {
    if (curve.construction) continue;
    for (const [u, v] of curve.uv) {
      min = [Math.min(min[0], u), Math.min(min[1], v)];
      max = [Math.max(max[0], u), Math.max(max[1], v)];
    }
  }
  return Number.isFinite(min[0]) ? { min, max } : null;
}

/** The distance a first extrude of a sketch offers: about a quarter of its largest extent, in a round number
 * (`fallback` when the sketch has no extent yet). */
export function defaultExtrudeDistance(shape: Pick<SketchShape, "extent"> | null, fallback = 10): number {
  const extent = shape?.extent;
  if (!extent) return fallback;
  const largest = Math.max(extent.max[0] - extent.min[0], extent.max[1] - extent.min[1]);
  if (!(largest > 0)) return fallback;
  const raw = largest * 0.25;
  const step = 10 ** Math.floor(Math.log10(raw)) / 2;
  return Math.max(Math.round(raw / step) * step, step);
}

/** "outer: loop 1, holes: 1" for a sketch with several loops (null for a single loop, which needs no words). */
export function profileSummary(doc: Pick<SketchDoc, "profile" | "inner">, loopCount: number): string | null {
  if (loopCount <= 1) return null;
  return `outer: loop ${doc.profile + 1}, holes: ${doc.inner.length}`;
}

/** The centre of the sketch's extent in the world (mm), or the plane's origin. */
export function sketchCentre(doc: Pick<SketchDoc, "plane">, shape: Pick<SketchShape, "extent"> | null): Vec3 {
  const e = shape?.extent;
  return e ? planeToWorld(doc.plane, (e.min[0] + e.max[0]) / 2, (e.min[1] + e.max[1]) / 2) : planeToWorld(doc.plane, 0, 0);
}

/** What the inspector says about a sketch. */
export function describeSketch(info: SketchInfo, shape: SketchShape | null, solve: SolveResult | null): { label: string; value: string }[] {
  const counts = (kind: string) => info.doc.entities.filter((entity) => entity.kind === kind && !entity.construction).length;
  const parts = [`${counts("line")} lines`, `${counts("circle")} circles`, `${counts("arc")} arcs`, `${counts("bspline")} splines`];
  const construction = info.doc.entities.filter((entity) => entity.construction).length;
  const rows = [
    { label: "plane", value: planeLabel(info.doc.plane) },
    { label: "geometry", value: parts.join(", ") + (construction ? `, ${construction} construction` : "") },
    { label: "constraints", value: String(info.doc.constraints.length) },
    { label: "solve", value: solve ? `${solve.status}, ${solve.dof} degrees of freedom` : shape?.failed ? "failed" : "pending" },
    { label: "profile", value: profileSummary(info.doc, shape?.loopCount ?? 0) ?? (shape && shape.loopCount > 0 ? "the closed loop" : "no closed loop yet") },
    { label: "used by", value: info.usedBy.length ? info.usedBy.join(", ") : "nothing yet" },
  ];
  if (shape?.extent) rows.push({ label: "size", value: `${(shape.extent.max[0] - shape.extent.min[0]).toFixed(1)} x ${(shape.extent.max[1] - shape.extent.min[1]).toFixed(1)} mm` });
  return rows;
}

// -- selecting sketches (the viewport and the tree share one rule) ----------------------------------------------------------------

/** The selected sketches after a click on `name` (null: on nothing) from the viewport or the tree: a plain click selects that
 * one, Ctrl/Cmd+click toggles it in the selection, a click on nothing clears (unless Ctrl/Cmd). */
export function nextSketchSelection(previous: readonly string[], name: string | null, additive: boolean): string[] {
  if (name === null) return additive ? [...previous] : [];
  if (!additive) return previous.length === 1 && previous[0] === name ? [...previous] : [name];
  return previous.includes(name) ? previous.filter((other) => other !== name) : [...previous, name];
}

// -- hiding sketches, remembered per notebook ----------------------------------------------------------------------------------

type Store = Pick<Storage, "getItem" | "setItem">;
const hiddenKey = (notebook: string | null) => `sca.sketch.hidden:${notebook ?? ""}`;

function browserStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The names of the sketches a person hid in this notebook. */
export function readHidden(notebook: string | null, store: Store | null = browserStore()): Set<string> {
  try {
    const raw = store?.getItem(hiddenKey(notebook));
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter((name): name is string => typeof name === "string") : []);
  } catch {
    return new Set();
  }
}

export function writeHidden(notebook: string | null, hidden: ReadonlySet<string>, store: Store | null = browserStore()): void {
  try {
    store?.setItem(hiddenKey(notebook), JSON.stringify([...hidden].sort()));
  } catch {
    /* private window or blocked storage: the choice just is not remembered */
  }
}

/** A copy of the hidden set with `name` hidden when it was shown and shown when it was hidden. */
export function toggleHidden(hidden: ReadonlySet<string>, name: string): Set<string> {
  const next = new Set(hidden);
  if (!next.delete(name)) next.add(name);
  return next;
}

// -- picking in the viewport ---------------------------------------------------------------------------------------------------

export type Pickable = { name: string; curves: Vec3[][]; regions: { outer: Vec3[]; holes: Vec3[][] }[] };
export type Hit = { name: string; kind: "curve" | "region"; distance: number };

function segmentDistance(px: number, py: number, a: readonly [number, number], b: readonly [number, number]): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const squared = dx * dx + dy * dy;
  const t = squared < 1e-12 ? 0 : Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / squared));
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}

/** The sketch under a screen position: the nearest curve within `tolerance` pixels, else a sketch whose filled region
 * contains the position (the smallest such region first).  `project` maps a world point to the screen (null: behind the camera). */
export function hitSketches(items: readonly Pickable[], project: (p: Vec3) => [number, number] | null, x: number, y: number, tolerance = 7): Hit | null {
  let curveHit: Hit | null = null;
  let regionHit: (Hit & { area: number }) | null = null;
  for (const item of items) {
    for (const curve of item.curves) {
      let previous: [number, number] | null = null;
      for (const point of curve) {
        const screen = project(point);
        if (screen && previous) {
          const distance = segmentDistance(x, y, previous, screen);
          if (distance <= tolerance && (!curveHit || distance < curveHit.distance)) curveHit = { name: item.name, kind: "curve", distance };
        }
        previous = screen;
      }
    }
    for (const region of item.regions) {
      const outer = region.outer.map(project);
      if (outer.some((p) => !p)) continue;
      const poly = outer as [number, number][];
      if (!pointInPolygon([x, y], poly)) continue;
      const inHole = region.holes.some((hole) => {
        const screen = hole.map(project);
        return screen.every(Boolean) && pointInPolygon([x, y], screen as [number, number][]);
      });
      if (inHole) continue;
      const area = Math.abs(poly.reduce((sum, p, i) => sum + (p[0] * poly[(i + 1) % poly.length][1] - poly[(i + 1) % poly.length][0] * p[1]), 0) / 2);
      if (!regionHit || area < regionHit.area) regionHit = { name: item.name, kind: "region", distance: 0, area };
    }
  }
  if (curveHit) return curveHit;
  return regionHit ? { name: regionHit.name, kind: "region", distance: 0 } : null;
}
