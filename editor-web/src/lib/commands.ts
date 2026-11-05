/** The command registry behind the command bar: anything a person can start from the viewport.
 * Today it is filled from the feature catalog (/api/features/specs); sketch and assembly commands join it later,
 * each with its own group, so the bar reads groups and commands only from this data. */

import type { LucideIcon } from "lucide-react";

import type { Spec } from "@/lib/features";
import { t } from "@/i18n";

export type Command = {
  id: string;
  label: string;
  /** Category chip it appears under. */
  group: string;
  /** Extra words a person may type (synonyms); id, group and description are searched as well. */
  keywords: string[];
  description?: string;
  icon?: LucideIcon;
  /** Whether the command fits the current selection (a sketch picked: Extrude; edges picked: Fillet).  Commands without it
   * fit nothing in particular and only come first for no selection. */
  when?: (context: SelectionContext) => boolean;
  /** Listed only while it fits the selection (Edit sketch means nothing without a sketch picked). */
  contextOnly?: boolean;
  /** Whether the command is offered at all in this state of the model (the stand-alone Cut means nothing while the part
   * has one body).  Commands without it are always offered.  See visibleCommands. */
  visible?: (state: CommandState) => boolean;
  /** Values of the operation's dialog this command starts with (Extrude (cut) opens Extrude with `operation: "cut"`);
   * `run` applies them. */
  preset?: Record<string, unknown>;
  run: () => void;
};

/** What the model looks like, for the commands that only make sense in some states. */
export type CommandState = { openBodies: number };

/** The commands offered in this state of the model (the bar and the contextual bar read this list). */
export function visibleCommands<T extends Pick<Command, "visible">>(commands: readonly T[], state: CommandState): T[] {
  return commands.filter((command) => command.visible?.(state) ?? true);
}

/** The `visible` of each command id (data, not UI).  A solid now says how it meets the body when it is made (the Operation of
 * its dialog), so the commands that combine two named bodies only matter while several bodies are open (a legacy notebook). */
const VISIBLE: Record<string, (state: CommandState) => boolean> = {
  cut: (s) => s.openBodies > 1,
  union: (s) => s.openBodies > 1,
  intersect: (s) => s.openBodies > 1,
  cut_sketch: (s) => s.openBodies > 1,
  boss_sketch: (s) => s.openBodies > 1,
  extrude_sketch: (s) => s.openBodies === 0, // with a body, Extrude (join) and Extrude (cut) stand in for it
};
export const visibleFor = (id: string): ((state: CommandState) => boolean) | undefined => VISIBLE[id];

/** Presets of one operation: extra commands that open its dialog with some values chosen.  `suffix` makes the command id
 * (`<spec>_<suffix>`). */
export const PRESETS: Record<string, { suffix: string; label: string; description: string; keywords: string[]; preset: Record<string, unknown> }[]> = {
  extrude_sketch: [
    { suffix: "join", label: "Extrude (join)", description: "Push the sketch out and add it to the body.", keywords: ["pad", "boss", "add", "union", "material"], preset: { operation: "join" } },
    { suffix: "cut", label: "Extrude (cut)", description: "Push the sketch through the body and remove what it passes.", keywords: ["pocket", "subtract", "remove", "through", "hole"], preset: { operation: "cut" } },
  ],
  extrude_face: [
    { suffix: "join", label: "Pull face", description: "Push the picked face out along its normal and add it to the body.", keywords: ["pad", "boss", "push", "pull", "extend"], preset: { operation: "join", direction: "normal" } },
    { suffix: "cut", label: "Push face in", description: "Push the picked face into the body and remove what it passes.", keywords: ["pocket", "recess", "press", "subtract"], preset: { operation: "cut", direction: "-normal" } },
  ],
};

// -- what the selection offers ----------------------------------------------------------------------------------------------------

/** What is selected, counted by kind (the model's entities and the notebook's sketches). */
/** `curves`: the notebook's 3D curves picked (wires and edges it holds as values: a path, a rail). */
export type SelectionContext = { sketches: number; curves: number; solids: number; components: number; faces: number; planarFaces: number; edges: number; vertices: number };
export type ContextKind = "sketch" | "curve" | "edge" | "face" | "solid";

export const EMPTY_CONTEXT: SelectionContext = { sketches: 0, curves: 0, solids: 0, components: 0, faces: 0, planarFaces: 0, edges: 0, vertices: 0 };

/** Count a selection; a face whose details are not known yet counts as planar (the click that uses it checks again). */
export function selectionContext(
  items: readonly { kind: string; geometry?: Record<string, unknown> | null }[],
  sketches: readonly string[] = [],
  curves: readonly string[] = [],
): SelectionContext {
  const out = { ...EMPTY_CONTEXT, sketches: sketches.length, curves: curves.length };
  for (const item of items) {
    if (item.kind === "solid") out.solids += 1;
    else if (item.kind === "component") out.components += 1;
    else if (item.kind === "edge") out.edges += 1;
    else if (item.kind === "vertex") out.vertices += 1;
    else if (item.kind === "face") {
      out.faces += 1;
      const type = typeof item.geometry?.type === "string" ? item.geometry.type.toLowerCase() : null;
      if (type === null || type === "plane") out.planarFaces += 1;
    }
  }
  return out;
}

/** Which kind of thing the selection mainly is (sketches first, then curves, edges, faces, bodies); null for nothing. */
export function contextKind(context: SelectionContext): ContextKind | null {
  if (context.sketches > 0) return "sketch";
  if (context.curves > 0) return "curve";
  if (context.edges > 0) return "edge";
  if (context.faces > 0) return "face";
  if (context.solids > 0 || context.components > 0) return "solid";
  return null;
}

/** The contextual actions of each kind, in order: the command id and the short word shown on the button. */
export const CONTEXT_ACTIONS: Record<ContextKind, { id: string; label: string }[]> = {
  face: [
    { id: "press_pull", label: "Press / pull" },
    { id: "inset_face", label: "Inset" },
    { id: "sketch_on_face", label: "Sketch on this face" },
    { id: "workplane_place", label: "Workplane" },
    { id: "hole", label: "Hole here" },
    { id: "connector_place", label: "Connector" },
    { id: "shell", label: "Shell" },
  ],
  edge: [
    { id: "fillet", label: "Fillet" },
    { id: "chamfer", label: "Chamfer" },
    { id: "workplane_from_selection", label: "Workplane" },
  ],
  sketch: [
    { id: "extrude_sketch", label: "Extrude" },
    { id: "extrude_sketch_join", label: "Extrude (join)" },
    { id: "extrude_sketch_cut", label: "Extrude (cut)" },
    { id: "revolve_sketch", label: "Revolve" },
    { id: "cut_sketch", label: "Cut" },
    { id: "boss_sketch", label: "Boss" },
    { id: "edit_sketch", label: "Edit sketch" },
    { id: "sweep_along", label: "Sweep along the curve" },
  ],
  curve: [{ id: "sweep_along", label: "Sweep" }],
  solid: [
    { id: "translate", label: "Move" },
    { id: "rotate", label: "Rotate" },
    { id: "mirror", label: "Mirror" },
    { id: "linear_pattern", label: "Pattern" },
  ],
};

/** The `when` of each command id (data, not UI): what it needs selected. */
const WHEN: Record<string, (context: SelectionContext) => boolean> = {
  sketch_on_face: (c) => c.faces === 1 && c.edges === 0 && c.sketches === 0,
  workplane_place: (c) => c.edges + c.vertices + c.sketches === 0 && (c.faces === 0 || (c.faces === 1 && c.planarFaces === 1)),
  connector_place: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  // what workplaneRequest (lib/workplanes.ts) reads: one face (+ an edge), two faces, three vertices, or one edge
  workplane_from_selection: (c) =>
    c.sketches + c.solids + c.components === 0 &&
    ((c.faces === 1 && c.planarFaces === 1 && c.edges <= 1 && c.vertices === 0) ||
      (c.faces === 2 && c.planarFaces === 2 && c.edges === 0 && c.vertices === 0) ||
      (c.vertices === 3 && c.faces + c.edges === 0) ||
      (c.edges === 1 && c.faces + c.vertices === 0)),
  hole: (c) => c.faces === 1 && c.edges === 0 && c.sketches === 0,
  extrude_face: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  extrude_face_join: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  extrude_face_cut: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  shell: (c) => c.faces >= 1 && c.edges === 0 && c.sketches === 0,
  press_pull: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  inset_face: (c) => c.faces === 1 && c.planarFaces === 1 && c.edges === 0 && c.sketches === 0,
  fillet: (c) => c.edges >= 1 && c.sketches === 0,
  chamfer: (c) => c.edges >= 1 && c.sketches === 0,
  extrude_sketch: (c) => c.sketches === 1,
  extrude_sketch_join: (c) => c.sketches === 1,
  extrude_sketch_cut: (c) => c.sketches === 1,
  revolve_sketch: (c) => c.sketches === 1,
  cut_sketch: (c) => c.sketches === 1,
  boss_sketch: (c) => c.sketches === 1,
  edit_sketch: (c) => c.sketches === 1,
  // a profile swept along a path: the curve, and the sketch as the profile when one is picked with it
  sweep_along: (c) => c.curves === 1 && c.sketches <= 1 && c.solids + c.components + c.faces + c.edges + c.vertices === 0,
  translate: (c) => (c.solids >= 1 || c.components >= 1) && c.faces + c.edges + c.sketches === 0,
  rotate: (c) => (c.solids >= 1 || c.components >= 1) && c.faces + c.edges + c.sketches === 0,
  mirror: (c) => (c.solids >= 1 || c.components >= 1) && c.faces + c.edges + c.sketches === 0,
  linear_pattern: (c) => (c.solids >= 1 || c.components >= 1) && c.faces + c.edges + c.sketches === 0,
};
export const whenFor = (id: string): ((context: SelectionContext) => boolean) | undefined => WHEN[id];

/** The buttons of the contextual action bar for a selection: the registry commands whose `when` holds, in the order of
 * CONTEXT_ACTIONS, each with its short label. */
export function contextualActions(commands: readonly Command[], context: SelectionContext): { command: Command; label: string }[] {
  const kind = contextKind(context);
  if (!kind) return [];
  const out: { command: Command; label: string }[] = [];
  for (const action of CONTEXT_ACTIONS[kind]) {
    const command = commands.find((item) => item.id === action.id);
    if (command && (command.when?.(context) ?? false)) out.push({ command, label: action.label });
  }
  return out;
}

/** How much a command fits the selection, for ranking (0: not at all): the contextual ones in the order of their buttons first,
 * then any other command whose `when` holds. */
export function fitScore(context: SelectionContext): (command: Command) => number {
  const kind = contextKind(context);
  const order = kind ? CONTEXT_ACTIONS[kind].map((action) => action.id) : [];
  return (command) => {
    if (!kind || !command.when?.(context)) return 0;
    const at = order.indexOf(command.id);
    return at >= 0 ? 1000 - at : 500;
  };
}

/** One line saying what the selection can do (shown in the command bar), or null for an empty selection. */
export function selectionHint(context: SelectionContext, commands: readonly Command[] = []): string | null {
  const kind = contextKind(context);
  if (!kind) return null;
  const labels = contextualActions(commands, context).map((item) => item.label.toLowerCase());
  const list = labels.length > 1 ? `${labels.slice(0, -1).join(", ")} or ${labels[labels.length - 1]}` : (labels[0] ?? "");
  const noun = {
    sketch: `${context.sketches} sketch${context.sketches === 1 ? "" : "es"}`,
    edge: `${context.edges} edge${context.edges === 1 ? "" : "s"}`,
    face: `${context.faces} face${context.faces === 1 ? "" : "s"}`,
    curve: `${context.curves} curve${context.curves === 1 ? "" : "s"}`,
    solid: `${context.solids + context.components} body`,
  }[kind];
  return `${noun} selected${list ? `: ${list}` : ""}.`;
}

/** The word a person reads for an operation (the catalog's labels lead with the internal name: "Extrude sketch"). */
const PLAIN_LABEL: Record<string, string> = {
  extrude_sketch: "Extrude",
  revolve_sketch: "Revolve",
  cut_sketch: "Cut with sketch",
  boss_sketch: "Boss from sketch",
  translate: "Move",
};
export const plainLabel = (id: string, label: string): string => PLAIN_LABEL[id] ?? label;

const PLAIN_DESCRIPTION: Record<string, string> = {
  extrude_sketch: "Push a sketch out into a solid.",
  revolve_sketch: "Turn a sketch around an axis into a solid.",
  cut_sketch: "Cut a pocket or a through cut along a sketch.",
  boss_sketch: "Add material along a sketch to a body.",
};
export const plainDescription = (id: string, description: string): string => PLAIN_DESCRIPTION[id] ?? description;

/** Synonyms by operation id (data, not UI): what a designer might type instead of the label. */
const SYNONYMS: Record<string, string[]> = {
  box: ["cube", "block", "brick", "rectangle"],
  cylinder: ["rod", "pin", "tube", "round"],
  sphere: ["ball", "globe"],
  cone: ["frustum", "taper", "countersink"],
  cut: ["subtract", "remove", "difference", "pocket"],
  union: ["join", "merge", "add", "combine", "fuse"],
  intersect: ["common", "overlap", "keep"],
  hole: ["drill", "bore", "pocket"],
  extrude_face: ["pull", "push", "pad", "face", "offset"],
  fillet: ["round", "rounded", "radius", "edge"],
  chamfer: ["bevel", "edge"],
  shell: ["hollow", "thin", "wall"],
  inset_face: ["offset", "outline", "loop", "imprint", "step", "boss", "inset"],
  press_pull: ["pull", "push", "press", "extrude", "pad", "pocket", "drag"],
  linear_pattern: ["array", "copies", "repeat", "row"],
  radial_pattern: ["array", "circular", "polar", "copies", "repeat"],
  mirror: ["flip", "symmetry", "reflect"],
  translate: ["move", "offset", "shift"],
  rotate: ["turn", "spin", "angle"],
  scale: ["resize", "grow", "shrink", "size"],
  sketch: ["draw", "profile", "2d", "outline"],
  extrude_sketch: ["pad", "pull", "push", "extrusion"],
  revolve_sketch: ["lathe", "spin", "turn"],
  cut_sketch: ["pocket", "subtract", "remove", "through"],
  boss_sketch: ["pad", "add", "material"],
};

/** The commands the feature catalog offers; `open` starts the operation's dialog (with the values of a preset, if any).
 * An operation with PRESETS is followed by its preset commands. */
export function commandsFromSpecs(specs: readonly Spec[], open: (spec: Spec, preset?: Record<string, unknown>) => void, icons: Record<string, LucideIcon> = {}): Command[] {
  return specs.flatMap((spec) => {
    // a preset only exists for a spec that has the slot it presets (an older server without `operation` has none)
    const presets = (PRESETS[spec.id] ?? [])
      .filter((item) => Object.keys(item.preset).every((name) => spec.slots.some((slot) => slot.name === name)))
      .map((item): Command => {
        const id = `${spec.id}_${item.suffix}`;
        return {
          id,
          label: item.label,
          group: spec.group,
          keywords: [...(SYNONYMS[spec.id] ?? []), ...item.keywords],
          description: item.description,
          icon: icons[spec.id],
          when: whenFor(id),
          visible: (state) => state.openBodies >= 1,
          preset: item.preset,
          run: () => open(spec, item.preset),
        };
      });
    const base: Command = {
      id: spec.id,
      label: plainLabel(spec.id, spec.label),
      group: spec.group,
      keywords: SYNONYMS[spec.id] ?? [],
      description: plainDescription(spec.id, spec.description),
      icon: icons[spec.id],
      when: whenFor(spec.id),
      // without its presets (a server that has no operation slot) the plain command stays
      visible: PRESETS[spec.id] && presets.length === 0 ? undefined : visibleFor(spec.id),
      run: () => open(spec),
    };
    return [base, ...presets];
  });
}

/** The assembly commands: the layout panel, and the connectors of the open part.  `open` shows the panel (the left
 * column's assembly tab); the layout is one GUI feature, so there is no per-command dialog. */
export function assemblyCommands(open: (section: "assembly" | "connectors") => void, icons: { assembly?: LucideIcon; connectors?: LucideIcon } = {}): Command[] {
  return [
    {
      id: "assembly",
      label: "Assembly",
      group: "Assembly",
      keywords: ["layout", "joint", "revolute", "prismatic", "gear", "belt", "mate", "constraint", "components", "ground"],
      description: "Place parts, ground one, and join connector frames with joints and mates.",
      icon: icons.assembly,
      run: () => open("assembly"),
    },
    {
      id: "connectors",
      label: "Part connectors",
      group: "Assembly",
      keywords: ["connector", "frame", "mount", "hinge", "face"],
      description: "Declare the frames of this part (from picked faces) that an assembly joins by.",
      icon: icons.connectors,
      run: () => open("connectors"),
    },
  ];
}

/** Categories in the order their commands first appear (so a source that adds a group adds a chip). */
export function commandGroups(commands: readonly Command[]): string[] {
  const groups: string[] = [];
  for (const command of commands) if (!groups.includes(command.group)) groups.push(command.group);
  return groups;
}

function isSubsequence(needle: string, haystack: string): boolean {
  let at = 0;
  for (const ch of haystack) if (ch === needle[at] && ++at === needle.length) return true;
  return false;
}

function termScore(term: string, command: Command): number {
  const label = command.label.toLowerCase();
  const id = command.id.toLowerCase().replace(/_/g, " ");
  const words = label.split(/[\s/]+/);
  if (label.startsWith(term)) return 100;
  if (words.some((word) => word.startsWith(term))) return 80;
  if (id.startsWith(term) || id.split(" ").some((word) => word.startsWith(term))) return 70;
  if (command.keywords.some((word) => word.toLowerCase().startsWith(term))) return 60;
  if (label.includes(term) || id.includes(term)) return 50;
  if (command.group.toLowerCase().startsWith(term)) return 40;
  if (command.keywords.some((word) => word.toLowerCase().includes(term))) return 35;
  if (command.group.toLowerCase().includes(term) || (command.description ?? "").toLowerCase().includes(term)) return 30;
  // the names shown in the person's language (a Chinese query finds 拉伸)
  const shown = t(command.label).toLowerCase();
  if (shown !== label) {
    if (shown.startsWith(term)) return 85;
    if (shown.includes(term)) return 55;
  }
  if (t(command.group).toLowerCase().includes(term)) return 30;
  if (term.length >= 3 && (isSubsequence(term, label) || isSubsequence(term, id.replace(/ /g, "")))) return 15;
  return 0;
}

/** Commands matching every word of the query, best first: prefix matches before substrings before fuzzy ones,
 * recently used commands ahead among equals (`recent` lists ids, newest first). An empty query lists all, recent first.
 * `fit` (see fitScore) puts the commands that fit the current selection ahead of everything else. */
export function searchCommands(commands: readonly Command[], query: string, recent: readonly string[] = [], fit?: (command: Command) => number): Command[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const bonus = (command: Command) => {
    const at = recent.indexOf(command.id);
    return at < 0 ? 0 : 20 - Math.min(at, 19);
  };
  const scored: { command: Command; score: number; order: number }[] = [];
  commands.forEach((command, order) => {
    let score = 0;
    for (const term of terms) {
      const part = termScore(term, command);
      if (part === 0) return;
      score += part;
    }
    scored.push({ command, score: score + bonus(command) + (fit ? fit(command) : 0), order });
  });
  return scored.sort((a, b) => b.score - a.score || a.order - b.order).map((item) => item.command);
}

/** `id` moved to the front of the recent list (at most 12 kept). */
export function pushRecent(recent: readonly string[], id: string): string[] {
  return [id, ...recent.filter((other) => other !== id)].slice(0, 12);
}
