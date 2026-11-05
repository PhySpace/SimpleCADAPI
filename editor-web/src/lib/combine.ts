/** How a new solid meets the body so far (the Operation field of a CAD extrude): Join, Cut or Intersect, and "New body" only
 * to start the first body.  The server marks the specs that do this `combinable` and gives them the slots `operation` and
 * `target` (see Slot.show_when); this file holds the rules the form applies to them, all pure. */

import { isSlotVisible, type FeatureRow, type FeatureState, type Slot, type SlotOption, type Spec } from "@/lib/features";
import type { SegmentOption } from "@/lib/segmented";
import { t } from "@/i18n";

export const OPERATION_SLOT = "operation";
export const TARGET_SLOT = "target";

/** What each way of meeting the body does, in plain words (the hint under the control and the tooltip). */
export const OPERATION_HINTS: Readonly<Record<string, string>> = {
  join: "adds this solid to the body",
  cut: "removes this solid from the body",
  intersect: "keeps only what both share",
  new: "starts the part with this solid",
};

/** The line shown while "New body" is the only choice. */
export const STARTS_PART = "A part holds one solid: this one starts the part.";

export type CombineState = Pick<FeatureState, "open">;

/** The operation a feature being edited was made with ("new" when its recipe has none), or null when not editing. */
export function storedOperation(edit: Pick<FeatureRow, "gui"> | undefined): string | null {
  if (!edit) return null;
  const value = edit.gui?.values?.operation;
  return typeof value === "string" ? value : "new";
}

/** Open bodies other than those the edited feature made itself. */
function otherOpen(state: CombineState, edit?: Pick<FeatureRow, "makes">): string[] {
  const own = new Set(edit?.makes ?? []);
  return state.open.filter((name) => !own.has(name));
}

/** Whether there is a body for this solid to meet: an open body, or (editing) a feature that already combined with one. */
export function hasBodyToCombine(state: CombineState, edit?: Pick<FeatureRow, "makes" | "gui">): boolean {
  if (!edit) return state.open.length > 0;
  return storedOperation(edit) !== "new" || otherOpen(state, edit).length > 0;
}

/** The choices of the Operation control and the line that explains a lone "New body".
 * Without a body only "New body" is offered (a join, cut or intersect would be refused); with one, Join, Cut and Intersect, plus
 * "New body" only for a feature that already is one (a legacy notebook with a second body). */
export function operationOptions(
  options: readonly SlotOption[],
  state: CombineState,
  edit?: Pick<FeatureRow, "makes" | "gui">,
): { options: SegmentOption[]; note: string | null } {
  const withBody = hasBodyToCombine(state, edit);
  const keepNew = !withBody || storedOperation(edit) === "new";
  const chosen = options.filter((option) => (option.value === "new" ? keepNew : withBody));
  const list = chosen.map((option) => ({ value: option.value, label: option.label, hint: OPERATION_HINTS[option.value] }));
  return { options: list, note: !withBody ? STARTS_PART : null };
}

/** What the target slot shows: nothing, one line naming the only body, or a choice (several open bodies: a legacy notebook). */
export type TargetDisplay = { kind: "hidden" } | { kind: "fixed"; name: string; text: string } | { kind: "choose" };

/** The "Combined with" rule.  `current` is the form's target.  A new solid shows the one open body as a line, several as a
 * choice; an edited one shows the body its recipe names (or says it is the body before it when the recipe names none). */
export function targetDisplay(state: CombineState, edit: Pick<FeatureRow, "makes" | "gui"> | undefined, current: string): TargetDisplay {
  const open = otherOpen(state, edit);
  if (edit) {
    if (open.length > 1) return { kind: "choose" };
    const name = current || "the body before it";
    return { kind: "fixed", name, text: `${t("Combined with:")} ${name}` };
  }
  if (open.length === 0) return { kind: "hidden" };
  if (open.length === 1) return { kind: "fixed", name: open[0], text: `${t("Combined with:")} ${open[0]}` };
  return { kind: "choose" };
}

/** The server's defaults for a form.  An edited feature keeps what its recipe says: the defaults for the operation and the
 * target (join, the body so far) would change a feature that was made another way. */
export function formDefaults(spec: Pick<Spec, "combinable">, defaults: Record<string, string>, editing: boolean): Record<string, string> {
  if (!spec.combinable || !editing) return defaults;
  const rest = { ...defaults };
  delete rest[OPERATION_SLOT];
  delete rest[TARGET_SLOT];
  return rest;
}

/** The slots a form lists, in order: for a combinable spec the operation and its target come first (the decision that
 * matters), then the rest.  Hidden slots (see isSlotVisible) are dropped. */
export function visibleSlots(spec: Pick<Spec, "slots" | "combinable">, values: Readonly<Record<string, unknown>>): Slot[] {
  const shown = spec.slots.filter((slot) => isSlotVisible(slot, values));
  if (!spec.combinable) return shown;
  const first = shown.filter((slot) => slot.name === OPERATION_SLOT || slot.name === TARGET_SLOT);
  return [...first, ...shown.filter((slot) => !first.includes(slot))];
}
