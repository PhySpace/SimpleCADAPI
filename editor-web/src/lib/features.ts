/** GUI-made features: the contract of /api/features (see src/simplecadapi/editor/features.py and gui_features.py),
 * its REST helpers, and the pure functions behind the form (defaults, text <-> values, validation, selection filtering). */

import type { SelectionItem } from "@/lib/selection";
import { axisName } from "@/lib/sketch-plane";

// -- contract -------------------------------------------------------------------------------------------------------

export type SlotKind = "length" | "angle" | "float" | "count" | "bool" | "enum" | "point" | "body" | "select" | "points2d" | "points3d" | "profile" | "sketch" | "value" | "text" | "grid";

export type SlotOption = { value: string; label: string };

export type Slot = {
  name: string;
  label: string;
  kind: SlotKind;
  default?: unknown;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: SlotOption[];
  entity?: "face" | "edge";
  /** A selection slot that takes exactly one item. */
  single?: boolean;
  /** kind "value": the kinds of named values that fit (solid, wire, face ...: what the SDK operation takes). */
  accepts?: string[];
  /** kind "value": a list of them (the sections of a loft, say). */
  many?: boolean;
  help?: string;
  optional?: boolean;
  /** The slot is shown, validated and sent only while every listed slot holds one of the listed values
   * (e.g. `{operation: ["join","cut"]}`); see isSlotVisible. */
  show_when?: Record<string, string[]>;
};

export type Spec = {
  id: string;
  label: string;
  group: string;
  role: string;
  produces: string;
  description: string;
  slots: Slot[];
  /** The operation makes a solid that is joined to, cut from or intersected with the body so far (see lib/combine.ts). */
  combinable?: boolean;
};

export type Catalog = { version: number; groups: { id: string; label: string }[]; specs: Spec[] };

export type FeatureRow = {
  cell: string;
  index: number;
  slug: string;
  role: string;
  gui: { spec: string; values: Record<string, unknown>; picked: Record<string, unknown> } | null;
  makes: string[];
  reads: string[];
  status: string | null;
  errors: unknown[];
  params_cell: string | null;
};

export type FeatureState = {
  features: FeatureRow[];
  bodies: { name: string; produces: string }[];
  open: string[];
  tip: string | null;
  /** The body the notebook's Part is built from: by a product cell, or (`implicit`, no cell) by the runtime from the open body. */
  product: { cell: string | null; body: string; implicit?: boolean } | null;
  defaults: Record<string, Record<string, string>>;
  /** The face-making sketches of the notebook (what a `profile` slot chooses from). */
  profiles?: { name: string; plane: string | { origin: number[]; x_axis: number[]; y_axis: number[] }; normal: string; normal_vec?: [number, number, number] }[];
  /** The assembly feature of the notebook (its document is the whole layout), or null. */
  assembly?: { cell: string; slug: string; doc: unknown } | null;
  /** The connectors the part notebook's product declares ([] without a product). */
  connectors?: { id: string; origin: number[]; x_axis: number[]; y_axis: number[] }[];
  taken: string[];
  undo: number;
  redo: number;
};

export type PickedItem = {
  kind: string;
  entity_id: string | null;
  node_id: string;
  definition_id: string | null;
  properties: Record<string, unknown> | null;
  geometry: Record<string, unknown> | null;
  tags?: string[];
};

export type FeatureCommand =
  | { op: "add"; spec: string; name?: string; values: Record<string, unknown>; selections?: Record<string, PickedItem[]>; after?: string }
  | { op: "edit"; cell: string; values: Record<string, unknown>; selections?: Record<string, PickedItem[]> }
  | { op: "delete"; cell: string }
  | { op: "use_as_product"; body: string }
  | { op: "set_connectors"; connectors: { id: string; origin: number[]; x_axis: number[]; y_axis: number[] }[] }
  | { op: "undo" }
  | { op: "redo" };

export type CommandResult = { ok: true; name: string; cell: { id: string; status?: string; errors?: unknown[] } | null; state: FeatureState };

// -- REST -----------------------------------------------------------------------------------------------------------

export async function fetchSpecs(): Promise<Catalog> {
  const response = await fetch("/api/features/specs");
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as Catalog;
}

export async function fetchFeatureState(): Promise<FeatureState> {
  const response = await fetch("/api/features");
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return (await response.json()) as FeatureState;
}

/** Run one command. Rejects with the server's message for the person (a 400/409 body `{ok:false,error}`). */
export async function featureCommand(command: FeatureCommand): Promise<CommandResult> {
  const response = await fetch("/api/features", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(command),
  });
  const body = (await response.json().catch(() => null)) as { ok?: boolean; error?: string } | null;
  if (!response.ok || !body || body.ok === false) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return body as CommandResult;
}

/** The line a person reads from one cell error: its "What happened" line, else the first line (the error may be a
 * string or an object with `message`/`error`). */
export function errorLine(error: unknown): string {
  const record = (error && typeof error === "object" ? error : {}) as Record<string, unknown>;
  const text = typeof error === "string" ? error : String(record.message ?? record.error ?? record.text ?? JSON.stringify(error));
  const what = text.split("\n").find((line) => line.trim().startsWith("What happened:"));
  return (what ? what.replace(/^\s*What happened:\s*/, "").trim() : (text.split("\n").find((l) => l.trim()) ?? text).trim()).slice(0, 400);
}

/** The command was accepted but its cell failed to run: what the person reads, or null when the cell ran. */
export function cellFailure(result: Pick<CommandResult, "cell">): string | null {
  const cell = result.cell;
  if (!cell) return null;
  const failed = cell.status === "exception" || cell.status === "error" || (cell.errors?.length ?? 0) > 0;
  if (!failed) return null;
  const first = cell.errors?.[0];
  return first === undefined ? `the cell ended with status ${cell.status}` : errorLine(first);
}

/** The error of a command whose cell failed: the feature exists (`cell`), so the form that sent it can edit it. */
export class CellFailure extends Error {
  readonly cell: string;
  constructor(message: string, cell: string) {
    super(message);
    this.name = "CellFailure";
    this.cell = cell;
  }
}

/** Commands whose answer carries the cell that ran (add, edit, set_connectors). */
export const isCellCommand = (command: FeatureCommand): boolean => command.op === "add" || command.op === "edit" || command.op === "set_connectors";

/** Throws a CellFailure when the command's cell failed; returns the result otherwise. */
export function assertCellRan<T extends Pick<CommandResult, "cell">>(result: T): T {
  const message = cellFailure(result);
  if (message && result.cell) throw new CellFailure(message, result.cell.id);
  return result;
}

// -- form state: raw text in, typed values out ----------------------------------------------------------------------

/** What a field holds while being typed: text for numbers and point lists, three texts for a point. */
export type RawValue = string | boolean | string[];
export type RawForm = Record<string, RawValue>;

const SLUG = /^[a-z][a-z0-9_]{0,40}$/;

export function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

/** The text a point list is edited as: one point per line. */
export function pointListText(points: unknown): string {
  if (!Array.isArray(points)) return "";
  return points.map((point) => (Array.isArray(point) ? point.map((c) => numberText(c)).join(", ") : "")).join("\n");
}

/** Parse "x, y" / "x, y, z" lines (commas, semicolons or spaces between numbers; blank lines ignored). */
export function parsePointList(text: string, dims: 2 | 3): { ok: true; points: number[][] } | { ok: false; error: string } {
  const points: number[][] = [];
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim();
    if (!line) continue;
    const parts = line.split(/[\s,;]+/).filter(Boolean);
    if (parts.length !== dims) {
      return { ok: false, error: `line ${index + 1}: expected ${dims} numbers (${dims === 2 ? "x, y" : "x, y, z"}), found ${parts.length}` };
    }
    const numbers = parts.map((part) => (/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(part) ? Number(part) : NaN));
    const bad = numbers.findIndex((n) => !Number.isFinite(n));
    if (bad >= 0) return { ok: false, error: `line ${index + 1}: "${parts[bad]}" is not a number` };
    points.push(numbers);
  }
  return { ok: true, points };
}

function parseNumber(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed || !/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(trimmed)) return null;
  return Number(trimmed);
}

/** Whether a slot is in play for these values (raw form text or typed values): a slot without `show_when` always is, one with
 * it only while each named slot holds one of the listed values.  A hidden slot is not rendered, not validated, not sent. */
export function isSlotVisible(slot: Pick<Slot, "show_when">, values: Readonly<Record<string, unknown>>): boolean {
  const rules = slot.show_when;
  if (!rules) return true;
  return Object.entries(rules).every(([name, allowed]) => {
    const value = values[name];
    return typeof value === "string" && allowed.includes(value);
  });
}

/** The raw form a spec opens with: the slot defaults, bodies from `defaults`, the recipe's values in edit mode. */
export function initialForm(spec: Spec, bodyDefaults: Record<string, string> = {}, values: Record<string, unknown> = {}): RawForm {
  const form: RawForm = {};
  for (const slot of spec.slots) {
    const given = slot.name in values ? values[slot.name] : slot.default;
    switch (slot.kind) {
      case "bool":
        form[slot.name] = Boolean(given);
        break;
      case "point": {
        const point = Array.isArray(given) ? given : [0, 0, 0];
        form[slot.name] = [0, 1, 2].map((i) => numberText(point[i] ?? 0));
        break;
      }
      case "sketch":
        break;
      case "profile":
      case "body":
        form[slot.name] = typeof values[slot.name] === "string" ? (values[slot.name] as string) : (bodyDefaults[slot.name] ?? "");
        break;
      case "enum": {
        // the server's defaults (the operation of a new solid: join when a body exists) come before the slot's own default
        const chosen = slot.name in values ? values[slot.name] : (bodyDefaults[slot.name] ?? given);
        form[slot.name] = typeof chosen === "string" ? chosen : (slot.options?.[0]?.value ?? "");
        break;
      }
      case "points2d":
      case "points3d":
        form[slot.name] = pointListText(given);
        break;
      case "select":
        break;
      case "value": {
        const chosen = slot.name in values ? values[slot.name] : bodyDefaults[slot.name];
        form[slot.name] = slot.many ? (Array.isArray(chosen) ? chosen.map(String) : []) : typeof chosen === "string" ? chosen : "";
        break;
      }
      case "text":
        form[slot.name] = typeof given === "string" ? given : "";
        break;
      case "grid":
        form[slot.name] = gridText(given);
        break;
      default:
        form[slot.name] = numberText(given);
    }
  }
  return form;
}

function rangeError(slot: Slot, value: number): string | null {
  if (slot.min !== undefined && value < slot.min) return `at least ${slot.min}${slot.unit ? ` ${slot.unit}` : ""}`;
  if (slot.max !== undefined && value > slot.max) return `at most ${slot.max}${slot.unit ? ` ${slot.unit}` : ""}`;
  return null;
}

/** Turn the raw form into the values the server takes, with one error text per slot that is not valid.
 * A `select` slot is not in the values (it travels as `selections`); its count is checked by the dialog. */
export function formToValues(spec: Spec, form: RawForm): { values: Record<string, unknown>; errors: Record<string, string> } {
  const values: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const slot of spec.slots) {
    if (!isSlotVisible(slot, form)) continue; // a hidden slot is neither checked nor sent
    const raw = form[slot.name];
    switch (slot.kind) {
      case "select":
      case "sketch":
        break;
      case "bool":
        values[slot.name] = Boolean(raw);
        break;
      case "enum":
      case "profile":
      case "body":
        if (typeof raw !== "string" || !raw) {
          if (!slot.optional) errors[slot.name] = slot.kind === "body" ? "no body to use yet: add a solid first" : slot.kind === "profile" ? "no sketch yet: add a sketch first" : "choose a value";
        } else values[slot.name] = raw;
        break;
      case "value":
        if (slot.many) {
          const names = Array.isArray(raw) ? raw.filter((n): n is string => typeof n === "string" && !!n) : [];
          if (names.length) values[slot.name] = names;
          else if (!slot.optional) errors[slot.name] = "choose at least one";
        } else if (typeof raw === "string" && raw) values[slot.name] = raw;
        else if (!slot.optional) errors[slot.name] = `no ${(slot.accepts ?? ["value"]).join(" or ")} in this notebook yet`;
        break;
      case "grid": {
        const parsed = parseGrid(typeof raw === "string" ? raw : "");
        if ("error" in parsed) errors[slot.name] = parsed.error;
        else values[slot.name] = parsed.grid;
        break;
      }
      case "text":
        if (typeof raw === "string" && raw.trim()) values[slot.name] = raw;
        else if (!slot.optional) errors[slot.name] = "enter a value";
        break;
      case "point": {
        const parts = Array.isArray(raw) ? raw : [];
        const numbers = parts.map(parseNumber);
        const bad = numbers.findIndex((n) => n === null);
        if (numbers.length !== 3 || bad >= 0) errors[slot.name] = "x, y and z must all be numbers";
        else {
          const out = numbers as number[];
          const range = out.map((n) => rangeError(slot, n)).find(Boolean);
          if (range) errors[slot.name] = range;
          else values[slot.name] = out;
        }
        break;
      }
      case "points2d":
      case "points3d": {
        const parsed = parsePointList(typeof raw === "string" ? raw : "", slot.kind === "points2d" ? 2 : 3);
        const least = slot.kind === "points2d" ? 3 : 2;
        if (!parsed.ok) errors[slot.name] = parsed.error;
        else if (parsed.points.length < least) errors[slot.name] = `at least ${least} points, one per line`;
        else values[slot.name] = parsed.points;
        break;
      }
      default: {
        const number = parseNumber(typeof raw === "string" ? raw : "");
        if (number === null) {
          if (!slot.optional || (typeof raw === "string" && raw.trim())) errors[slot.name] = "enter a number";
        } else if (slot.kind === "count" && !Number.isInteger(number)) errors[slot.name] = "must be a whole number";
        else {
          const range = rangeError(slot, number);
          if (range) errors[slot.name] = range;
          else values[slot.name] = number;
        }
      }
    }
  }
  return { values, errors };
}

/** The name a person typed, or null when it is acceptable (empty means "use the suggestion"). */
export function validateName(name: string, taken: readonly string[]): string | null {
  const text = name.trim();
  if (!text) return null;
  if (!SLUG.test(text)) return "lowercase letters, digits and underscores, starting with a letter";
  if (taken.includes(text) || taken.includes(text.toUpperCase())) return `"${text}" is already used in this notebook`;
  return null;
}

// -- bodies ---------------------------------------------------------------------------------------------------------

/** A grid of points as text: one row per line, the points of a row separated by ";" (``x, y, z; x, y, z``). */
export function gridText(grid: unknown): string {
  if (!Array.isArray(grid)) return "";
  return grid.map((row) => (Array.isArray(row) ? row.map((p) => (Array.isArray(p) ? p.map((v) => numberText(v)).join(", ") : "")).join("; ") : "")).join("\n");
}

/** Parse a grid typed as {@link gridText} writes it: every row the same length, every point three numbers. */
export function parseGrid(text: string): { grid: number[][][] } | { error: string } {
  const rows = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (rows.length < 2) return { error: "at least two rows, one per line" };
  const grid: number[][][] = [];
  for (const [r, line] of rows.entries()) {
    const points = line.split(";").map((part) => part.trim()).filter(Boolean);
    if (points.length < 2) return { error: `row ${r + 1}: at least two points, separated by ";"` };
    const row: number[][] = [];
    for (const point of points) {
      const numbers = point.split(/[\s,]+/).filter(Boolean).map(Number);
      if (numbers.length !== 3 || numbers.some((n) => !Number.isFinite(n))) return { error: `row ${r + 1}: "${point}" is not x, y, z` };
      row.push(numbers);
    }
    if (grid.length && row.length !== grid[0].length) return { error: `row ${r + 1} has ${row.length} points, row 1 has ${grid[0].length}` };
    grid.push(row);
  }
  return { grid };
}

/** The named values of the notebook that fit a value slot (its accepted kinds), in the order they were made. */
export function valueChoices(state: Pick<FeatureState, "bodies">, accepts: readonly string[] | undefined): { name: string; produces: string }[] {
  const fits = new Set(accepts ?? []);
  return state.bodies.filter((b) => fits.has(b.produces));
}

/** Bodies for a body select: the open ones (not yet used by another feature) first, then the rest. */
export function bodyChoices(state: Pick<FeatureState, "bodies" | "open">): { name: string; open: boolean }[] {
  const open = new Set(state.open);
  return [
    ...state.bodies.filter((b) => open.has(b.name)).map((b) => ({ name: b.name, open: true })),
    ...state.bodies.filter((b) => !open.has(b.name)).map((b) => ({ name: b.name, open: false })),
  ];
}

// -- sketch profiles --------------------------------------------------------------------------------------------------

/** How a sketch's plane reads: the datum plane's name, or "face" for a frame (a sketch drawn on a face). */
export function profilePlaneLabel(profile: { plane: unknown }): string {
  return typeof profile.plane === "string" ? profile.plane : "face";
}

/** The sketch (profile) named, or undefined. */
export function findProfile(state: Pick<FeatureState, "profiles">, name: string) {
  return (state.profiles ?? []).find((profile) => profile.name === name);
}

/** The direction ("+z", "-y"...) a feature on this profile pushes along by default: the plane's normal. */
export function directionForProfile(state: Pick<FeatureState, "profiles">, name: string): string | null {
  return findProfile(state, name)?.normal ?? null;
}

/** The value of the "opposite of the sketch plane's normal" choice. */
export const FLIP_NORMAL = "-normal";

/** The axis option ("+z") opposite to the profile's plane normal, or null when that normal is not along an axis
 * (the server's direction options are the six axes and "normal", so a slanted normal has no opposite to offer). */
export function oppositeNormal(state: Pick<FeatureState, "profiles">, profile: string | null): string | null {
  const found = profile ? findProfile(state, profile) : undefined;
  if (!found) return null;
  const axis = found.normal_vec ? axisName(found.normal_vec.map((c) => -c)) : null;
  if (axis) return axis;
  const named = /^([+-])([xyz])$/.exec(found.normal);
  return named ? `${named[1] === "+" ? "-" : "+"}${named[2]}` : null;
}

/** The options of a sketch operation's direction: the server's, plus "-normal" when the profile has an axis-aligned normal
 * (a server that lists "-normal" itself is used as it is). */
export function directionOptions(options: readonly SlotOption[], state: Pick<FeatureState, "profiles">, profile: string | null): SlotOption[] {
  if (options.some((option) => option.value === FLIP_NORMAL)) return [...options]; // the server offers the opposite itself
  const opposite = oppositeNormal(state, profile);
  const at = options.findIndex((option) => option.value === "normal");
  if (!opposite || at < 0) return [...options];
  return [...options.slice(0, at + 1), { value: FLIP_NORMAL, label: `-normal (opposite, ${opposite})` }, ...options.slice(at + 1)];
}

/** What the server is sent for a direction choice: "-normal" becomes the opposite axis. */
export function resolveDirection(value: string, state: Pick<FeatureState, "profiles">, profile: string | null, serverFlips = false): string {
  if (serverFlips) return value; // the server turns "-normal" into the opposite of any normal, slanted ones too
  return value === FLIP_NORMAL ? (oppositeNormal(state, profile) ?? "normal") : value;
}

// -- selection ------------------------------------------------------------------------------------------------------

/** The picked items of one entity kind (a slot's `entity`). */
export function filterSelection<T extends { kind: string }>(items: readonly T[], entity: "face" | "edge"): T[] {
  return items.filter((item) => item.kind === entity);
}

/** An item is usable once the kernel described it (a preview carries no properties/geometry). */
export function isDescribed(item: { entityId: string | null; properties: Record<string, unknown> | null; pending?: boolean }): boolean {
  return !item.pending && (item.entityId === null || Object.keys(item.properties ?? {}).length > 0);
}

/** What goes over the wire for a picked item: exactly the `selection.set` fields plus the tags, when it has any. */
export function pickedPayload(item: SelectionItem): PickedItem {
  const out: PickedItem = {
    kind: item.kind,
    entity_id: item.entityId,
    node_id: item.nodeId,
    definition_id: item.definitionId,
    properties: item.properties,
    geometry: item.geometry,
  };
  if (item.tags && item.tags.length) out.tags = item.tags;
  return out;
}

function vector3(value: unknown): [number, number, number] | null {
  if (Array.isArray(value) && value.length === 3 && value.every((c) => typeof c === "number" && Number.isFinite(c))) {
    return value as [number, number, number];
  }
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (typeof o.x === "number" && typeof o.y === "number" && typeof o.z === "number") return [o.x, o.y, o.z];
  }
  return null;
}

/** A face normal from its entity info: the first 3-vector under a key named normal (searched two levels deep). */
export function faceNormal(item: { properties: Record<string, unknown> | null; geometry: Record<string, unknown> | null }): [number, number, number] | null {
  const search = (source: Record<string, unknown> | null, depth: number): [number, number, number] | null => {
    if (!source) return null;
    for (const [key, value] of Object.entries(source)) {
      if (/normal/i.test(key)) {
        const found = vector3(value);
        if (found) return found;
      }
    }
    if (depth > 0) {
      for (const value of Object.values(source)) {
        if (value && typeof value === "object" && !Array.isArray(value)) {
          const found = search(value as Record<string, unknown>, depth - 1);
          if (found) return found;
        }
      }
    }
    return null;
  };
  return search(item.geometry, 2) ?? search(item.properties, 2);
}

/** The axis option ("+x" .. "-z") that points most nearly into the material: against the face's outward normal. */
export function inwardAxis(normal: readonly [number, number, number]): string | null {
  const abs = normal.map(Math.abs);
  const largest = Math.max(...abs);
  if (!(largest > 1e-9)) return null;
  const index = abs.indexOf(largest);
  const inward = -normal[index];
  return `${inward >= 0 ? "+" : "-"}${"xyz"[index]}`;
}

/** What "Use picked face" fills: the start point from the centroid, the direction from the normal when known. */
export function holeFromFace(item: { properties: Record<string, unknown> | null; geometry: Record<string, unknown> | null }): {
  point: [number, number, number] | null;
  direction: string | null;
  /** The unit vector into the material (against the outward normal): what "along the face's normal" drills along. */
  vector: [number, number, number] | null;
} {
  const point = vector3(item.properties?.centroid);
  const normal = faceNormal(item);
  const length = normal ? Math.hypot(...normal) : 0;
  const vector = normal && length > 1e-9 ? ([-normal[0] / length, -normal[1] / length, -normal[2] / length] as [number, number, number]) : null;
  return { point, direction: normal ? inwardAxis(normal) : null, vector };
}

const NAME_BASE: Record<string, string> = {
  extrude_rect: "block",
  extrude_circle: "disc",
  extrude_polygon: "profile_solid",
  extrude_sketch: "extrusion",
  revolve_sketch: "revolution",
  cut_sketch: "pocket",
  boss_sketch: "boss",
};

/** Operations whose default name is chosen here (a plain word) instead of by the server (the operation's internal id). */
export const FRIENDLY_NAMES: ReadonlySet<string> = new Set(["extrude_sketch", "revolve_sketch", "cut_sketch", "boss_sketch"]);

/** The name the server will give a feature when none is typed (mirrors default_slug in features.py; a hint, the server decides). */
export function suggestName(specId: string, taken: readonly string[]): string {
  // an SDK operation names what it makes: op.make_spur_gear_rsolid -> spur_gear (the server suggests the same)
  const base = NAME_BASE[specId] ?? (specId.startsWith("op.") ? specId.slice(3).replace(/_r[a-z]+$/, "").replace(/^(make|add|create)_/, "") || "shape" : specId);
  const used = new Set(taken);
  let candidate = base;
  for (let number = 1; used.has(candidate) || used.has(candidate.toUpperCase()); ) candidate = `${base}_${++number}`;
  return candidate;
}
