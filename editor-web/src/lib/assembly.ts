/** The assembly document and the part connectors the GUI edits: the contract of src/simplecadapi/editor/assembly_doc.py
 * (components, ground, constraints between connector frames), the pure operations behind the panel, the checks that
 * mirror the server's validation (so a bad document is explained before it is sent; the server stays the authority),
 * the frame of a connector from a picked face, and the REST helpers.  No kinematics here: the solver is the SDK's. */

import type { FeatureCommand, FeatureRow, FeatureState, PickedItem } from "@/lib/features";
import { cross, dot, frameFromEntity, sub, unit, vec3, type Vec3 } from "@/lib/sketch-plane";
import { t } from "@/i18n";

// -- contract -------------------------------------------------------------------------------------------------------

export const AXES = ["+x", "-x", "+y", "-y", "+z", "-z"] as const;
export type AxisName = (typeof AXES)[number];
export const AXIS_VECTOR: Record<AxisName, Vec3> = {
  "+x": [1, 0, 0],
  "-x": [-1, 0, 0],
  "+y": [0, 1, 0],
  "-y": [0, -1, 0],
  "+z": [0, 0, 1],
  "-z": [0, 0, -1],
};

export const KINDS = ["fixed", "revolute", "prismatic", "gear", "belt", "rack_pinion"] as const;
export type ConstraintKind = (typeof KINDS)[number];
export const KIND_LABEL: Record<ConstraintKind, string> = {
  fixed: "fixed (mate)",
  revolute: "revolute (hinge)",
  prismatic: "prismatic (slide)",
  gear: "gear",
  belt: "belt",
  rack_pinion: "rack and pinion",
};

export type ConnectorRef = { component: string; connector: string };
export type Component = { id: string; part: string; origin: [number, number, number]; x_axis: AxisName; y_axis: AxisName };
export type Constraint = {
  id: string;
  kind: ConstraintKind;
  a: ConnectorRef;
  b: ConnectorRef;
  drive?: number;
  limit?: [number, number];
  pitch_radius_a?: number;
  pitch_radius_b?: number;
  pulley_radius_a?: number;
  pulley_radius_b?: number;
  pitch_radius?: number;
  phase?: number;
};
/** The exploded view of the layout: `scad.explode_rassembly(factor, center?, axis?)`. A vector entry that is NaN is an empty
 * box (a half-typed vector is a problem until it is whole, or all empty = absent). */
export type Explode = { factor: number; center?: number[]; axis?: number[] };
export type AssemblyDoc = { components: Component[]; ground: string | null; constraints: Constraint[]; explode?: Explode };

/** A connector frame of a part, mm in the part's own frame. `z_axis` comes with the lists the server computes. */
export type ConnectorFrame = { id: string; origin: Vec3; x_axis: Vec3; y_axis: Vec3; z_axis?: Vec3 };

export const ID_PATTERN = /^[a-z][a-z0-9_]{0,30}$/;
export const CONNECTOR_PATTERN = /^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,60}$/;

export const emptyAssembly = (): AssemblyDoc => ({ components: [], ground: null, constraints: [] });

// -- normalisation --------------------------------------------------------------------------------------------------

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const axisOf = (v: unknown, fallback: AxisName): AxisName => ((AXES as readonly string[]).includes(v as string) ? (v as AxisName) : fallback);

/** A document from whatever the cell stored (missing parts filled in, wrong types dropped). */
export function normalizeAssembly(raw: unknown): AssemblyDoc {
  const source = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? (v as Record<string, unknown>[]) : []);
  const ref = (v: unknown): ConnectorRef => {
    const o = (v && typeof v === "object" ? v : {}) as Record<string, unknown>;
    return { component: String(o.component ?? ""), connector: String(o.connector ?? "") };
  };
  const components: Component[] = list(source.components).map((c) => {
    const origin = Array.isArray(c.origin) && c.origin.length === 3 && c.origin.every(finite) ? ([c.origin[0], c.origin[1], c.origin[2]] as [number, number, number]) : ([0, 0, 0] as [number, number, number]);
    return { id: String(c.id ?? ""), part: String(c.part ?? ""), origin, x_axis: axisOf(c.x_axis, "+x"), y_axis: axisOf(c.y_axis, "+y") };
  });
  const constraints: Constraint[] = list(source.constraints).map((k, i) => {
    const out: Constraint = { id: String(k.id ?? `k${i + 1}`), kind: (KINDS as readonly string[]).includes(k.kind as string) ? (k.kind as ConstraintKind) : "fixed", a: ref(k.a), b: ref(k.b) };
    for (const key of ["drive", "pitch_radius_a", "pitch_radius_b", "pulley_radius_a", "pulley_radius_b", "pitch_radius", "phase"] as const) if (finite(k[key])) out[key] = k[key] as number;
    if (Array.isArray(k.limit) && k.limit.length === 2 && k.limit.every(finite)) out.limit = [k.limit[0], k.limit[1]];
    return out;
  });
  const out: AssemblyDoc = { components, ground: typeof source.ground === "string" ? source.ground : null, constraints };
  const explode = source.explode && typeof source.explode === "object" ? (source.explode as Record<string, unknown>) : null;
  if (explode) {
    const e: Explode = { factor: finite(explode.factor) ? explode.factor : 0 };
    for (const key of ["center", "axis"] as const) {
      const v = explode[key];
      if (Array.isArray(v) && v.length === 3 && v.every(finite)) e[key] = [v[0], v[1], v[2]];
    }
    out.explode = e;
  }
  return out;
}

export const sameDoc = (a: AssemblyDoc, b: AssemblyDoc): boolean => JSON.stringify(a) === JSON.stringify(b);

// -- components ------------------------------------------------------------------------------------------------------

/** The part's file name as a component id: lowercase letters, digits, underscores, starting with a letter. */
export function idFromPart(part: string): string {
  const stem = (part.split("/").pop() ?? part).replace(/\.py$/, "").toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  const base = /^[a-z]/.test(stem) ? stem : `c_${stem}`.replace(/_+$/, "");
  return (base || "part").slice(0, 28);
}

/** `base` if it is free, else base_2, base_3, ... (always a valid id). */
export function uniqueId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) {
    const candidate = `${base}_${n}`;
    if (!used.has(candidate)) return candidate;
  }
}

export function addComponent(doc: AssemblyDoc, part: string, id?: string): { doc: AssemblyDoc; id: string } {
  const made = uniqueId(id && ID_PATTERN.test(id) ? id : idFromPart(part), doc.components.map((c) => c.id));
  const component: Component = { id: made, part, origin: [0, 0, 0], x_axis: "+x", y_axis: "+y" };
  // The first component is the natural ground.
  return { doc: { ...doc, components: [...doc.components, component], ground: doc.ground ?? (doc.components.length === 0 ? made : null) }, id: made };
}

/** The component removed; its constraints go with it, and the ground is cleared when it was the ground. */
export function removeComponent(doc: AssemblyDoc, id: string): AssemblyDoc {
  const components = doc.components.filter((c) => c.id !== id);
  return {
    ...doc,
    components,
    ground: doc.ground === id ? null : doc.ground,
    constraints: doc.constraints.filter((k) => k.a.component !== id && k.b.component !== id),
  };
}

/** A component renamed everywhere it is mentioned. The new id must be valid and free (checked by `idProblem`). */
export function renameComponent(doc: AssemblyDoc, from: string, to: string): AssemblyDoc {
  const swap = (r: ConnectorRef): ConnectorRef => (r.component === from ? { ...r, component: to } : r);
  return {
    ...doc,
    components: doc.components.map((c) => (c.id === from ? { ...c, id: to } : c)),
    ground: doc.ground === from ? to : doc.ground,
    constraints: doc.constraints.map((k) => ({ ...k, a: swap(k.a), b: swap(k.b) })),
  };
}

/** Why `to` cannot be the id of component `from` (null when it can). */
export function idProblem(doc: AssemblyDoc, from: string, to: string): string | null {
  if (!ID_PATTERN.test(to)) return "lowercase letters, digits and underscores, starting with a letter";
  if (to !== from && doc.components.some((c) => c.id === to)) return `"${to}" is already a component`;
  return null;
}

export const setGround = (doc: AssemblyDoc, id: string | null): AssemblyDoc => ({ ...doc, ground: id });
export const updateComponent = (doc: AssemblyDoc, id: string, patch: Partial<Omit<Component, "id">>): AssemblyDoc => ({
  ...doc,
  components: doc.components.map((c) => (c.id === id ? { ...c, ...patch } : c)),
});

/** The x and y axes of a placement must not lie along the same line (+x with -x is the same line). */
export const axesConflict = (x: AxisName, y: AxisName): boolean => x[1] === y[1];

/** The y axes that may go with an x axis (the other two lines), and vice versa. */
export const compatibleAxes = (other: AxisName): AxisName[] => AXES.filter((a) => !axesConflict(a, other));

/** Set an axis; when it now lies along the other one, the other moves to the first axis that is not (so the document stays valid). */
export function setAxis(doc: AssemblyDoc, id: string, which: "x_axis" | "y_axis", axis: AxisName): AssemblyDoc {
  const c = doc.components.find((item) => item.id === id);
  if (!c) return doc;
  const otherKey = which === "x_axis" ? "y_axis" : "x_axis";
  const other = c[otherKey];
  const fixed = axesConflict(axis, other) ? (compatibleAxes(axis).find((a) => a === (otherKey === "y_axis" ? "+y" : "+x")) ?? compatibleAxes(axis)[0]) : other;
  return updateComponent(doc, id, { [which]: axis, [otherKey]: fixed } as Partial<Component>);
}

// -- constraints -----------------------------------------------------------------------------------------------------

export const needsDrive = (kind: ConstraintKind) => kind === "revolute" || kind === "prismatic";
/** The numeric fields a kind carries (besides drive and limit): what the form shows for it. */
export function radiusFields(kind: ConstraintKind): { key: "pitch_radius_a" | "pitch_radius_b" | "pulley_radius_a" | "pulley_radius_b" | "pitch_radius"; label: string }[] {
  if (kind === "gear") return [{ key: "pitch_radius_a", label: "pitch radius A" }, { key: "pitch_radius_b", label: "pitch radius B" }];
  if (kind === "belt") return [{ key: "pulley_radius_a", label: "pulley radius A" }, { key: "pulley_radius_b", label: "pulley radius B" }];
  if (kind === "rack_pinion") return [{ key: "pitch_radius", label: "pinion pitch radius" }];
  return [];
}
export const hasPhase = (kind: ConstraintKind) => kind === "gear" || kind === "belt" || kind === "rack_pinion";

/** A new constraint of `kind` between two different components (the ground and the first other, when there are any); connectors unchosen. */
export function addConstraint(doc: AssemblyDoc, kind: ConstraintKind = "revolute"): { doc: AssemblyDoc; id: string } {
  const id = uniqueId(`k${doc.constraints.length + 1}`, doc.constraints.map((k) => k.id));
  const first = doc.ground ?? doc.components[0]?.id ?? "";
  const second = doc.components.find((c) => c.id !== first)?.id ?? "";
  const k: Constraint = { id, kind, a: { component: first, connector: "" }, b: { component: second, connector: "" } };
  return { doc: { ...doc, constraints: [...doc.constraints, k] }, id };
}

export const removeConstraint = (doc: AssemblyDoc, id: string): AssemblyDoc => ({ ...doc, constraints: doc.constraints.filter((k) => k.id !== id) });

/** A constraint changed to another kind: only the fields that kind carries stay. */
export function setKind(doc: AssemblyDoc, id: string, kind: ConstraintKind): AssemblyDoc {
  return {
    ...doc,
    constraints: doc.constraints.map((k) => {
      if (k.id !== id) return k;
      const out: Constraint = { id: k.id, kind, a: k.a, b: k.b };
      if (needsDrive(kind)) {
        if (needsDrive(k.kind)) {
          if (k.drive !== undefined) out.drive = k.drive;
          if (k.limit) out.limit = k.limit;
        }
      }
      if (hasPhase(kind) && hasPhase(k.kind) && k.phase !== undefined) out.phase = k.phase;
      for (const f of radiusFields(kind)) if (k[f.key] !== undefined) out[f.key] = k[f.key];
      return out;
    }),
  };
}

export const updateConstraint = (doc: AssemblyDoc, id: string, patch: Partial<Constraint>): AssemblyDoc => ({
  ...doc,
  constraints: doc.constraints.map((k) => (k.id === id ? { ...k, ...patch } : k)),
});

/** One side of a constraint set to a connector (picking the component resets the connector). */
export function setRef(doc: AssemblyDoc, id: string, side: "a" | "b", ref: Partial<ConnectorRef>): AssemblyDoc {
  return {
    ...doc,
    constraints: doc.constraints.map((k) => {
      if (k.id !== id) return k;
      const current = k[side];
      const component = ref.component ?? current.component;
      return { ...k, [side]: { component, connector: ref.connector ?? (component === current.component ? current.connector : "") } };
    }),
  };
}

// -- exploded view ---------------------------------------------------------------------------------------------------------

export const DEFAULT_EXPLODE_FACTOR = 1.0;

/** The exploded view on (factor 1.0, no centre or axis: components leave the assembly centre). Keeps the settings it had. */
export const enableExplode = (doc: AssemblyDoc): AssemblyDoc => (doc.explode ? doc : { ...doc, explode: { factor: DEFAULT_EXPLODE_FACTOR } });

/** The exploded view off: the key is removed (the notebook then shows the assembly as placed). */
export function disableExplode(doc: AssemblyDoc): AssemblyDoc {
  const { explode: _gone, ...rest } = doc;
  return rest;
}

/** The factor set (NaN when the box is empty and still being typed). */
export const setExplodeFactor = (doc: AssemblyDoc, factor: number): AssemblyDoc => (doc.explode ? { ...doc, explode: { ...doc.explode, factor } } : doc);

/** One entry of the centre or of the axis set; `undefined` empties it, and a vector with every box empty is absent. */
export function setExplodeVector(doc: AssemblyDoc, key: "center" | "axis", index: number, value: number | undefined): AssemblyDoc {
  if (!doc.explode) return doc;
  const next = [...(doc.explode[key] ?? [Number.NaN, Number.NaN, Number.NaN])];
  next[index] = value ?? Number.NaN;
  const { [key]: _old, ...rest } = doc.explode;
  const explode: Explode = next.every((v) => Number.isNaN(v)) ? rest : { ...rest, [key]: next };
  return { ...doc, explode };
}

/** What the server will refuse in the exploded view, one sentence each (the same rules as `assembly_doc.validate`, plus a zero axis, which has no side). */
export function explodeProblems(explode: Explode | undefined): string[] {
  if (!explode) return [];
  const out: string[] = [];
  if (!finite(explode.factor)) out.push(t("explode factor: type a number"));
  for (const key of ["center", "axis"] as const) {
    const v = explode[key];
    if (!v) continue;
    if (v.length !== 3 || !v.every(finite)) out.push(t("explode {{key}}: type all three numbers, or leave all three empty", { key }));
    else if (key === "axis" && v.every((n) => n === 0)) out.push(t("explode axis: a zero vector points nowhere"));
  }
  return out;
}

// -- validity before sending ---------------------------------------------------------------------------------------------

/** What the server will refuse, found first (the same rules as `assembly_doc.validate`): one sentence per problem, empty when fine. */
export function assemblyProblems(doc: AssemblyDoc): string[] {
  const out: string[] = [];
  const ids = new Set<string>();
  for (const c of doc.components) {
    if (!ID_PATTERN.test(c.id)) out.push(t("component \"{{id}}\": lowercase letters, digits and underscores, starting with a letter", { id: c.id }));
    else if (ids.has(c.id)) out.push(t("the component id \"{{id}}\" is used twice", { id: c.id }));
    ids.add(c.id);
    if (!/^[A-Za-z0-9_][A-Za-z0-9_./-]*\.py$/.test(c.part) || c.part.split("/").includes("..")) out.push(t("{{id}}: \"{{part}}\" is not a notebook path inside the workspace", { id: c.id, part: c.part }));
    if (!c.origin.every(finite)) out.push(t("{{id}}: the origin is three numbers", { id: c.id }));
    if (axesConflict(c.x_axis, c.y_axis)) out.push(t("{{id}}: the x axis and the y axis must not be along the same line", { id: c.id }));
  }
  if (doc.ground !== null && !ids.has(doc.ground)) out.push(t("the grounded component \"{{id}}\" is not in the assembly", { id: doc.ground }));
  const used = new Set<string>();
  for (const k of doc.constraints) {
    const who = k.id;
    if (!ID_PATTERN.test(k.id) || used.has(k.id)) out.push(t("constraint id \"{{id}}\" is invalid or used twice", { id: k.id }));
    used.add(k.id);
    for (const side of ["a", "b"] as const) {
      const r = k[side];
      if (!ids.has(r.component)) out.push(t("{{who}}: pick the component of {{side}}", { who, side: side.toUpperCase() }));
      else if (!r.connector) out.push(t("{{who}}: pick the connector of {{side}}", { who, side: side.toUpperCase() }));
      else if (!CONNECTOR_PATTERN.test(r.connector)) out.push(t("{{who}}: \"{{name}}\" is not a connector name", { who, name: r.connector }));
    }
    if (k.a.component && k.a.component === k.b.component) out.push(t("{{who}}: a constraint joins two different components", { who }));
    if (needsDrive(k.kind)) {
      if (k.drive !== undefined && !finite(k.drive)) out.push(t("{{who}}: the drive is a number", { who }));
      if (k.limit && !(k.limit[0] < k.limit[1])) out.push(t("{{who}}: the lower limit must be below the upper one", { who }));
    }
    for (const f of radiusFields(k.kind)) {
      const v = k[f.key];
      if (!finite(v)) out.push(t("{{who}}: {{field}} is required", { who, field: t(f.label) }));
      else if (v <= 0) out.push(t("{{who}}: {{field}} must be greater than zero", { who, field: t(f.label) }));
    }
  }
  if (doc.constraints.length > 0 && doc.ground === null) out.push(t("constraints need a grounded component: the solver moves everything else relative to it"));
  out.push(...explodeProblems(doc.explode));
  return out;
}

/** The document as it is sent: only the fields each kind carries, no empty extras. */
export function docForServer(doc: AssemblyDoc): AssemblyDoc {
  return normalizeAssembly(JSON.parse(JSON.stringify(doc)));
}

/** The POST /api/features body that applies the document: an edit of the existing assembly feature, else an add. */
export function applyCommand(doc: AssemblyDoc, existing: { cell: string } | null, name?: string): FeatureCommand {
  const values = { assembly: docForServer(doc) };
  return existing ? { op: "edit", cell: existing.cell, values } : { op: "add", spec: "assembly", ...(name?.trim() ? { name: name.trim() } : {}), values };
}

// -- the solver's word -----------------------------------------------------------------------------------------------------

/** The feature rows an assembly is made of (its params/uses/layout cells share the slug), with the errors the solver or a part gave. */
export function assemblyStatus(state: Pick<FeatureState, "features" | "assembly">): { rows: FeatureRow[]; errors: string[]; running: boolean } | null {
  const a = state.assembly;
  if (!a) return null;
  const rows = state.features.filter((f) => f.slug === a.slug || f.slug === `${a.slug}_parts`);
  const errors: string[] = [];
  for (const row of rows) {
    for (const e of row.errors) {
      const text = typeof e === "string" ? e : String((e as Record<string, unknown>).message ?? (e as Record<string, unknown>).error ?? JSON.stringify(e));
      const what = text.split("\n").find((line) => line.startsWith("What happened:"));
      errors.push((what ? what.replace("What happened:", "").trim() : text.split("\n")[0]).slice(0, 400));
    }
    if (!row.errors.length && (row.status === "error" || row.status === "exception")) errors.push(t("{{name}} failed", { name: row.slug }));
  }
  return { rows, errors, running: rows.some((r) => r.status === "running" || r.status === "queued") };
}

// -- connectors of a part --------------------------------------------------------------------------------------------------

const round9 = (v: number) => Math.round(v * 1e9) / 1e9 + 0;
const r9 = (a: Vec3): Vec3 => [round9(a[0]), round9(a[1]), round9(a[2])];
const r6 = (a: Vec3): Vec3 => [Math.round(a[0] * 1e6) / 1e6 + 0, Math.round(a[1] * 1e6) / 1e6 + 0, Math.round(a[2] * 1e6) / 1e6 + 0];

/** The frame of a connector placed on a picked planar face: origin = the face centroid on its plane (else the geometry
 * origin), z = the outward normal, x = the face's x_direction made square to z (else a stable horizontal), y = z cross x.
 * All axes unit. Null when the face is not planar or reports no usable normal/origin. */
export function connectorFrameFromFace(item: Pick<PickedItem, "geometry" | "properties">): { origin: Vec3; x_axis: Vec3; y_axis: Vec3; z_axis: Vec3 } | null {
  // The kernel describes a face with its own connector frame (outward normal, whatever the face orientation): it wins.
  const given = item.properties?.connector_frame as Record<string, unknown> | undefined;
  const gOrigin = vec3(given?.origin);
  const gx = vec3(given?.x_axis);
  const gz = vec3(given?.z_axis);
  if (gOrigin && gx && gz) {
    const x = unit(r9(gx));
    const z = unit(r9(gz));
    const y = x && z ? unit(r9(cross(z, x))) : null;
    if (x && y && z && Math.abs(dot(x, z)) < 1e-6) return { origin: r6(gOrigin), x_axis: x, y_axis: y, z_axis: z };
  }
  const frame = frameFromEntity(item.geometry, item.properties);
  if (!frame) return null;
  const z = unit(cross(frame.x_axis, frame.y_axis));
  if (!z) return null;
  const x = unit(r9(frame.x_axis));
  if (!x) return null;
  const y = unit(r9(cross(z, x)));
  if (!y) return null;
  return { origin: r6(frame.origin), x_axis: x, y_axis: y, z_axis: z };
}

/** A readable id for a connector on a face with this outward normal: top, bottom, front... (else "face"). */
export function sideName(normal: Vec3): string {
  const n = unit(normal);
  if (!n) return "face";
  const [ax, ay, az] = n.map(Math.abs);
  const largest = Math.max(ax, ay, az);
  if (largest < 0.9) return "face";
  if (az === largest) return n[2] > 0 ? "top" : "bottom";
  if (ax === largest) return n[0] > 0 ? "right" : "left";
  return n[1] > 0 ? "back" : "front";
}

export function addConnectorFromFace(list: readonly ConnectorFrame[], face: Pick<PickedItem, "geometry" | "properties">, name?: string): { list: ConnectorFrame[]; id: string } | { error: string } {
  const frame = connectorFrameFromFace(face);
  if (!frame) return { error: "That face is not planar (or reports no normal): pick a planar face." };
  const wanted = name?.trim();
  if (wanted) {
    if (!CONNECTOR_PATTERN.test(wanted)) return { error: `"${wanted}" is not a connector name: letters, digits, _ . : - (up to 61 characters)` };
    if (list.some((c) => c.id === wanted)) return { error: `"${wanted}" is already a connector of this part` };
  }
  const id = wanted || uniqueId(sideName(frame.z_axis), list.map((c) => c.id));
  return { list: [...list, { id, origin: frame.origin, x_axis: frame.x_axis, y_axis: frame.y_axis, z_axis: frame.z_axis }], id };
}

/** The list with a connector at `frame` (placed with the handles), named `name` or after the side its z faces. */
export function addConnectorFrame(
  list: readonly ConnectorFrame[],
  frame: { origin: Vec3; x_axis: Vec3; y_axis: Vec3 },
  name?: string,
): { list: ConnectorFrame[]; id: string } | { error: string } {
  const z = cross(frame.x_axis, frame.y_axis);
  const wanted = name?.trim();
  if (wanted) {
    if (!CONNECTOR_PATTERN.test(wanted)) return { error: `"${wanted}" is not a connector name: letters, digits, _ . : - (up to 61 characters)` };
    if (list.some((c) => c.id === wanted)) return { error: `"${wanted}" is already a connector of this part` };
  }
  const id = wanted || uniqueId(sideName(z), list.map((c) => c.id));
  return { list: [...list, { id, origin: frame.origin, x_axis: frame.x_axis, y_axis: frame.y_axis, z_axis: z }], id };
}

export const removeConnector = (list: readonly ConnectorFrame[], id: string): ConnectorFrame[] => list.filter((c) => c.id !== id);

/** Rotate `v` about the unit axis `k` by `degrees` (Rodrigues). */
function rotateAbout(v: Vec3, k: Vec3, degrees: number): Vec3 {
  const t = (degrees * Math.PI) / 180;
  const c = Math.cos(t);
  const s = Math.sin(t);
  const kxv = cross(k, v);
  const kdv = dot(k, v);
  return [0, 1, 2].map((i) => v[i] * c + kxv[i] * s + k[i] * kdv * (1 - c)) as Vec3;
}

const clean = (v: Vec3): Vec3 => v.map((n) => (Math.abs(n) < 1e-12 ? 0 : Math.round(n * 1e9) / 1e9)) as Vec3;

/** A connector's frame changed by hand: a new origin, a move along its own axes, or a turn about one of them.
 * The axes stay unit and square (the z axis is x cross y), so the server accepts the result. */
export function transformConnector(
  list: readonly ConnectorFrame[],
  id: string,
  change: { origin?: Vec3; move?: Vec3; rotate?: { axis: "x" | "y" | "z"; degrees: number } },
): ConnectorFrame[] {
  return list.map((c) => {
    if (c.id !== id) return c;
    let x = unit(c.x_axis) ?? ([1, 0, 0] as Vec3);
    let y = unit(c.y_axis) ?? ([0, 1, 0] as Vec3);
    let z = unit(cross(x, y)) ?? ([0, 0, 1] as Vec3);
    let origin: Vec3 = change.origin ? [...change.origin] : [...c.origin];
    if (change.move) origin = [0, 1, 2].map((i) => origin[i] + change.move![0] * x[i] + change.move![1] * y[i] + change.move![2] * z[i]) as Vec3;
    if (change.rotate) {
      const k = change.rotate.axis === "x" ? x : change.rotate.axis === "y" ? y : z;
      x = unit(rotateAbout(x, k, change.rotate.degrees)) ?? x;
      y = unit(rotateAbout(y, k, change.rotate.degrees)) ?? y;
      y = unit(sub(y, x.map((v) => v * dot(x, y)) as Vec3)) ?? y; // square again against rounding
      z = unit(cross(x, y)) ?? z;
    }
    return { ...c, origin: clean(origin), x_axis: clean(x), y_axis: clean(y), z_axis: clean(z) };
  });
}

export function renameConnector(list: readonly ConnectorFrame[], from: string, to: string): { list: ConnectorFrame[] } | { error: string } {
  if (!CONNECTOR_PATTERN.test(to)) return { error: `"${to}" is not a connector name` };
  if (to !== from && list.some((c) => c.id === to)) return { error: `"${to}" is already a connector of this part` };
  return { list: list.map((c) => (c.id === from ? { ...c, id: to } : c)) };
}

/** What the server refuses in a connector list (same rules as `validate_connectors`). */
export function connectorProblems(list: readonly ConnectorFrame[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const c of list) {
    if (!CONNECTOR_PATTERN.test(c.id) || seen.has(c.id)) out.push(`connector id "${c.id}" is invalid or used twice`);
    seen.add(c.id);
    const nx = Math.hypot(...c.x_axis);
    const ny = Math.hypot(...c.y_axis);
    if (Math.abs(nx - 1) > 1e-6 || Math.abs(ny - 1) > 1e-6) out.push(`${c.id}: the axes must be unit vectors`);
    else if (Math.abs(dot(c.x_axis, c.y_axis)) > 1e-6) out.push(`${c.id}: the x axis and the y axis must be square to each other`);
  }
  return out;
}

/** The set_connectors command: the list replaces the whole set (the z axis is the server's to compute). */
export function setConnectorsCommand(list: readonly ConnectorFrame[]): FeatureCommand {
  return { op: "set_connectors", connectors: list.map((c) => ({ id: c.id, origin: c.origin, x_axis: c.x_axis, y_axis: c.y_axis })) };
}

/** The connectors a state says the part has, as editable frames (z axis computed). */
export function connectorsOfState(state: Pick<FeatureState, "connectors">): ConnectorFrame[] {
  return (state.connectors ?? []).map((c) => {
    const x = vec3(c.x_axis) ?? [1, 0, 0];
    const y = vec3(c.y_axis) ?? [0, 1, 0];
    return { id: c.id, origin: vec3(c.origin) ?? [0, 0, 0], x_axis: x, y_axis: y, z_axis: cross(x, y) };
  });
}

// -- placing frames in the world -------------------------------------------------------------------------------------------------

/** Where a point given in a component's part frame is in the world when the component sits at its document placement
 * (origin + the axes x, y and z = x cross y).  The fallback of the gizmos when the viewer holds no transform for the component. */
export function placementToWorld(c: Pick<Component, "origin" | "x_axis" | "y_axis">, p: Vec3): Vec3 {
  const x = AXIS_VECTOR[c.x_axis];
  const y = AXIS_VECTOR[c.y_axis];
  const z = cross(x, y);
  return [c.origin[0] + x[0] * p[0] + y[0] * p[1] + z[0] * p[2], c.origin[1] + x[1] * p[0] + y[1] * p[1] + z[1] * p[2], c.origin[2] + x[2] * p[0] + y[2] * p[1] + z[2] * p[2]];
}

/** The same for a direction (no origin). */
export function placementDirToWorld(c: Pick<Component, "x_axis" | "y_axis">, d: Vec3): Vec3 {
  return sub(placementToWorld({ origin: [0, 0, 0], x_axis: c.x_axis, y_axis: c.y_axis }, d), [0, 0, 0]);
}

// -- REST ------------------------------------------------------------------------------------------------------------------

export type PartRow = { path: string; name: string; kind: string };

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const body = (await response.json().catch(() => null)) as (T & { ok?: boolean; error?: string }) | null;
  if (!response.ok || !body || body.ok === false) throw new Error(body?.error ?? `${response.status} ${response.statusText}`);
  return body;
}

/** GET /api/assembly/parts: the part notebooks of the workspace. */
export const fetchParts = async (): Promise<PartRow[]> => (await getJson<{ parts: PartRow[] }>("/api/assembly/parts")).parts;

export const connectorsUrl = (path: string): string => `/api/assembly/parts?path=${encodeURIComponent(path)}`;

/** GET /api/assembly/parts?path=: the connectors a part declares (the server runs the part; slow the first time). */
export async function fetchConnectors(path: string): Promise<ConnectorFrame[]> {
  const body = await getJson<{ connectors: Record<string, unknown>[] }>(connectorsUrl(path));
  return body.connectors.map((c) => {
    const x = vec3(c.x_axis) ?? [1, 0, 0];
    const y = vec3(c.y_axis) ?? [0, 1, 0];
    return { id: String(c.id), origin: vec3(c.origin) ?? [0, 0, 0], x_axis: x, y_axis: y, z_axis: vec3(c.z_axis) ?? cross(x, y) };
  });
}
