/** GUI-made features: the contract of /api/features (see src/simplecadapi/editor/features.py and gui_features.py),
 * its REST helpers, and the pure functions behind the form (defaults, text <-> values, validation, selection filtering). */

import type { SelectionItem } from "@/lib/selection";

// -- contract -------------------------------------------------------------------------------------------------------

export type SlotKind = "length" | "angle" | "float" | "count" | "bool" | "enum" | "point" | "body" | "select" | "points2d" | "points3d" | "profile" | "sketch";

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
  help?: string;
  optional?: boolean;
};

export type Spec = {
  id: string;
  label: string;
  group: string;
  role: string;
  produces: string;
  description: string;
  slots: Slot[];
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
  product: { cell: string; body: string } | null;
  defaults: Record<string, Record<string, string>>;
  /** The face-making sketches of the notebook (what a `profile` slot chooses from). */
  profiles?: { name: string; plane: string; normal: string }[];
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
      case "enum":
        form[slot.name] = typeof given === "string" ? given : (slot.options?.[0]?.value ?? "");
        break;
      case "points2d":
      case "points3d":
        form[slot.name] = pointListText(given);
        break;
      case "select":
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

/** Bodies for a body select: the open ones (not yet used by another feature) first, then the rest. */
export function bodyChoices(state: Pick<FeatureState, "bodies" | "open">): { name: string; open: boolean }[] {
  const open = new Set(state.open);
  return [
    ...state.bodies.filter((b) => open.has(b.name)).map((b) => ({ name: b.name, open: true })),
    ...state.bodies.filter((b) => !open.has(b.name)).map((b) => ({ name: b.name, open: false })),
  ];
}

// -- sketch profiles --------------------------------------------------------------------------------------------------

/** The sketch (profile) named, or undefined. */
export function findProfile(state: Pick<FeatureState, "profiles">, name: string) {
  return (state.profiles ?? []).find((profile) => profile.name === name);
}

/** The direction ("+z", "-y"...) a feature on this profile pushes along by default: the plane's normal. */
export function directionForProfile(state: Pick<FeatureState, "profiles">, name: string): string | null {
  return findProfile(state, name)?.normal ?? null;
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
} {
  const point = vector3(item.properties?.centroid);
  const normal = faceNormal(item);
  return { point, direction: normal ? inwardAxis(normal) : null };
}

const NAME_BASE: Record<string, string> = { extrude_rect: "block", extrude_circle: "disc", extrude_polygon: "profile_solid" };

/** The name the server will give a feature when none is typed (mirrors default_slug in features.py; a hint, the server decides). */
export function suggestName(specId: string, taken: readonly string[]): string {
  const base = NAME_BASE[specId] ?? specId;
  const used = new Set(taken);
  let candidate = base;
  for (let number = 1; used.has(candidate) || used.has(candidate.toUpperCase()); ) candidate = `${base}_${++number}`;
  return candidate;
}
