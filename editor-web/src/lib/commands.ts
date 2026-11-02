/** The command registry behind the command bar: anything a person can start from the viewport.
 * Today it is filled from the feature catalog (/api/features/specs); sketch and assembly commands join it later,
 * each with its own group, so the bar reads groups and commands only from this data. */

import type { LucideIcon } from "lucide-react";

import type { Spec } from "@/lib/features";

export type Command = {
  id: string;
  label: string;
  /** Category chip it appears under. */
  group: string;
  /** Extra words a person may type (synonyms); id, group and description are searched as well. */
  keywords: string[];
  description?: string;
  icon?: LucideIcon;
  run: () => void;
};

/** Synonyms by operation id (data, not UI): what a designer might type instead of the label. */
const SYNONYMS: Record<string, string[]> = {
  box: ["cube", "block", "brick", "rectangle"],
  cylinder: ["rod", "pin", "tube", "round"],
  sphere: ["ball", "globe"],
  cone: ["frustum", "taper", "countersink"],
  extrude_rect: ["pad", "boss", "prism", "square"],
  extrude_circle: ["pad", "boss", "disc", "round"],
  extrude_polygon: ["pad", "boss", "sketch", "outline"],
  revolve: ["lathe", "spin", "turn"],
  loft_circles: ["blend", "transition"],
  loft_rects: ["blend", "transition"],
  sweep_circle: ["pipe", "rail", "path", "tube"],
  cut: ["subtract", "remove", "difference", "pocket"],
  union: ["join", "merge", "add", "combine", "fuse"],
  intersect: ["common", "overlap", "keep"],
  hole: ["drill", "bore", "pocket"],
  fillet: ["round", "rounded", "radius", "edge"],
  chamfer: ["bevel", "edge"],
  shell: ["hollow", "thin", "wall"],
  linear_pattern: ["array", "copies", "repeat", "row"],
  radial_pattern: ["array", "circular", "polar", "copies", "repeat"],
  mirror: ["flip", "symmetry", "reflect"],
  translate: ["move", "offset", "shift"],
  rotate: ["turn", "spin", "angle"],
  scale: ["resize", "grow", "shrink", "size"],
};

/** The commands the feature catalog offers; `open` starts the operation's dialog. */
export function commandsFromSpecs(specs: readonly Spec[], open: (spec: Spec) => void, icons: Record<string, LucideIcon> = {}): Command[] {
  return specs.map((spec) => ({
    id: spec.id,
    label: spec.label,
    group: spec.group,
    keywords: SYNONYMS[spec.id] ?? [],
    description: spec.description,
    icon: icons[spec.id],
    run: () => open(spec),
  }));
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
  if (term.length >= 3 && (isSubsequence(term, label) || isSubsequence(term, id.replace(/ /g, "")))) return 15;
  return 0;
}

/** Commands matching every word of the query, best first: prefix matches before substrings before fuzzy ones,
 * recently used commands ahead among equals (`recent` lists ids, newest first). An empty query lists all, recent first. */
export function searchCommands(commands: readonly Command[], query: string, recent: readonly string[] = []): Command[] {
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
    scored.push({ command, score: score + bonus(command), order });
  });
  return scored.sort((a, b) => b.score - a.score || a.order - b.order).map((item) => item.command);
}

/** `id` moved to the front of the recent list (at most 12 kept). */
export function pushRecent(recent: readonly string[], id: string): string[] {
  return [id, ...recent.filter((other) => other !== id)].slice(0, 12);
}
