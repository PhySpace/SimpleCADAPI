import type { LucideIcon } from "lucide-react";
import { useRef } from "react";

import { cn } from "@/lib/utils";
import { isEnabled, moveIndex, type SegmentOption } from "@/lib/segmented";

/** A segmented control: one of a few short choices, always visible (a radio group, not a dropdown).
 *
 * Props
 * - `options`   the choices, `{ value, label, hint?, disabled? }` (`disabled` is a reason string or `true`); `icons` maps a
 *               value to a lucide icon shown before the label.
 * - `value`     the selected value.
 * - `onChange`  called with the value the person picked (click, Enter/Space, or an arrow key, which moves and selects).
 * - `label`     the accessible name of the group.
 * - `note`      one line under the control that stays whatever is selected (why a choice is the only one); the hint of the
 *               selected option is shown under it when there is no note.
 * - `testId`    `data-testid` of the group; each segment is `<testId>-<value>`.
 *
 * Keyboard: Left/Up and Right/Down move to the previous / next enabled option (wrapping), Home / End go to the first /
 * last; only the selected segment is in the tab order.  The selected segment is filled (the same look as the selection mode
 * tabs), colour stays reserved for meaning.  Hints are also the segments' tooltips. */
export function OperationChooser({
  options,
  value,
  onChange,
  icons = {},
  label,
  note,
  testId = "operation",
  className,
}: {
  options: readonly SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  icons?: Readonly<Record<string, LucideIcon>>;
  label: string;
  note?: string | null;
  testId?: string;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const selected = options.findIndex((option) => option.value === value);
  const tabbable = selected >= 0 ? selected : Math.max(0, options.findIndex(isEnabled));
  const hint = options[selected]?.hint;

  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    const to = moveIndex(options, index, event.key);
    if (to === null) return;
    event.preventDefault();
    if (to !== index) {
      onChange(options[to].value);
      refs.current[to]?.focus();
    }
  };

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div role="radiogroup" aria-label={label} data-testid={testId} data-value={value} className="flex border-2 border-input">
        {options.map((option, index) => {
          const Icon = icons[option.value];
          const on = option.value === value;
          const reason = typeof option.disabled === "string" ? option.disabled : undefined;
          return (
            <button
              key={option.value}
              ref={(element) => {
                refs.current[index] = element;
              }}
              type="button"
              role="radio"
              aria-checked={on}
              disabled={Boolean(option.disabled)}
              tabIndex={index === tabbable ? 0 : -1}
              title={reason ?? option.hint}
              data-testid={`${testId}-${option.value}`}
              className={cn(
                "flex flex-1 items-center justify-center gap-1 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-40",
                index > 0 && "border-l-2 border-input",
                on ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
              onClick={() => onChange(option.value)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              {Icon && <Icon className="size-3.5 shrink-0" aria-hidden />}
              {option.label}
            </button>
          );
        })}
      </div>
      {(note || hint) && (
        <span className="text-[11px] text-muted-foreground" data-testid={`${testId}-hint`}>
          {note ?? `${options[selected]?.label ?? ""} ${hint}.`}
        </span>
      )}
    </div>
  );
}
