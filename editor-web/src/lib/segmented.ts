/** Pure helpers of a segmented control (components/OperationChooser.tsx): which option an arrow key moves to.
 * Kept apart from the component so the keyboard rules are tested without a DOM. */

export type SegmentOption = {
  value: string;
  label: string;
  /** Shown as the tooltip and as the one-line hint under the control while this option is selected. */
  hint?: string;
  /** Not selectable: a string is the reason (read as a tooltip), `true` has none. */
  disabled?: string | boolean;
};

export const isEnabled = (option: Pick<SegmentOption, "disabled">): boolean => !option.disabled;

/** The index the arrow keys / Home / End lead to from `from`, skipping disabled options and wrapping around;
 * `from` itself when nothing else can be chosen, null for a key that does not move. */
export function moveIndex(options: readonly Pick<SegmentOption, "disabled">[], from: number, key: string): number | null {
  const count = options.length;
  if (count === 0) return null;
  const step = key === "ArrowRight" || key === "ArrowDown" ? 1 : key === "ArrowLeft" || key === "ArrowUp" ? -1 : 0;
  if (step === 0) {
    if (key === "Home") return options.findIndex(isEnabled) >= 0 ? options.findIndex(isEnabled) : null;
    if (key === "End") {
      for (let i = count - 1; i >= 0; i--) if (isEnabled(options[i])) return i;
    }
    return null;
  }
  for (let n = 1; n <= count; n++) {
    const at = (((from + step * n) % count) + count) % count;
    if (isEnabled(options[at])) return at;
  }
  return from;
}
