/** An operation in progress: picked, added at once with small defaults, its numbers tuned in a panel by the selection
 * while the model previews every change, until it is confirmed (the numbers are written into the notebook) or cancelled
 * (the feature is taken back).  Pure helpers; the panel is components/OperationPanel.tsx, the state machine lives in App.
 *
 *   idle --pick an operation (the selection is all it needs)--> adding --added--> tuning --Enter--> idle (committed)
 *                                                                          \--Esc--> idle (undone, or reverted when editing)
 *   idle --edit a feature of the tree--> tuning (its own numbers)
 *
 * An operation that needs more than the selection and defaults (a sketch profile, a hole's position, a list of points)
 * opens its dialog instead. */

import { formDefaults } from "@/lib/combine";
import { filterSelection, formToValues, initialForm, pickedPayload, suggestName, type FeatureCommand, type FeatureState, type Spec } from "@/lib/features";
import type { SelectionItem } from "@/lib/selection";

/** Slot kinds that need nothing but their default (numbers become the feature's parameters, tuned in the panel). */
const DIRECT = new Set(["length", "angle", "float", "count", "bool", "enum", "point", "body"]);

/** Operations that keep their dialog: they need a placement or a profile the selection does not give. */
const DIALOG_ONLY = new Set(["hole", "extrude_sketch", "revolve_sketch", "cut_sketch", "boss_sketch", "sketch", "curve", "workplane"]);

export type QuickStart = { command: Extract<FeatureCommand, { op: "add" }>; name: string };

/** The `add` command that starts `spec` on `selection` with its defaults (and `prefill`), or null when it needs its
 * dialog: a slot the defaults cannot fill, or a selection slot with nothing picked. */
export function quickStart(
  spec: Spec,
  state: Pick<FeatureState, "defaults" | "taken">,
  selection: readonly SelectionItem[],
  prefill: Record<string, unknown> = {},
): QuickStart | null {
  if (DIALOG_ONLY.has(spec.id)) return null;
  const selections: Record<string, ReturnType<typeof pickedPayload>[]> = {};
  for (const slot of spec.slots) {
    if (slot.kind === "select") {
      const picks = filterSelection(selection, slot.entity ?? "face");
      // a pick travels by its entity id: the server has the kernel name it (its details need not have come yet)
      if (!picks.length || (slot.single && picks.length !== 1)) return null;
      selections[slot.name] = picks.map(pickedPayload);
    } else if (!DIRECT.has(slot.kind)) return null;
  }
  const form = initialForm(spec, formDefaults(spec, state.defaults[spec.id] ?? {}, false), prefill);
  const { values, errors } = formToValues(spec, form);
  if (Object.keys(errors).length) return null;
  const name = suggestName(spec.id, state.taken);
  return { command: { op: "add", spec: spec.id, name, values, ...(Object.keys(selections).length ? { selections } : {}) }, name };
}

/** The parameters of the feature `slug` among the notebook's: the ones its `# ---- params: <slug> ----` cell declares. */
export function featureParams<P extends { group: string }>(params: readonly P[], slug: string): P[] {
  return params.filter((param) => param.group === slug);
}
