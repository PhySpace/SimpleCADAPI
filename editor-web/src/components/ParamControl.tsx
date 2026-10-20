import { useEffect, useRef, useState } from "react";

import { Slider } from "@/components/ui/slider";
import { cn } from "@/lib/utils";

export type ParamValue = number | boolean;
/** A parameter the notebook declares (see `sca params`); `cell` is the id of
 * the declaring cell. `modified`: the value differs from the source. */
export type ParamMeta = {
  id: string;
  label: string;
  cell: string;
  group: string;
  kind: "float" | "int" | "bool";
  control: "slider" | "number" | "toggle";
  min: number | null;
  max: number | null;
  step: number | null;
  unit: string | null;
  default: ParamValue;
  value: ParamValue;
  modified?: boolean;
  comment?: string | null;
  issues?: string[];
};

/** One parameter: a slider, a number box or a toggle, by its `# ui:` comment. */
export function ParamControl({
  param,
  forwardParam,
}: {
  param: ParamMeta;
  /** `now`: send at once (a click, a release) instead of when the changes settle. */
  forwardParam: (id: string, value: ParamValue, now?: boolean) => void;
}) {
  // A drag shows its own value: the server only hears of it when it settles,
  // so the value it echoes back cannot move the thumb meanwhile.
  const [drag, setDrag] = useState<number | null>(null);
  const dragging = useRef(false);
  useEffect(() => {
    if (!dragging.current) setDrag(null);
  }, [param.value]);
  const label = param.label || param.id;
  const title = [param.comment, ...(param.issues ?? [])].filter(Boolean).join("\n") || undefined;
  const ink = param.modified ? "text-focus" : "text-name";
  if (param.control === "toggle") {
    const on = Boolean(param.value);
    return (
      <button
        type="button"
        className="flex items-center justify-between gap-2 text-left text-[11px]"
        title={title}
        onClick={() => forwardParam(param.id, !on, true)}
      >
        <span className={ink}>{label}</span>
        <span className={cn("border-2 px-1.5 text-[10px] font-bold uppercase", on ? "border-primary bg-primary text-primary-foreground" : "border-input text-muted-foreground")}>
          {on ? "on" : "off"}
        </span>
      </button>
    );
  }
  const value = drag ?? Number(param.value);
  return (
    <div title={title}>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px]">
        <span className={cn("truncate", ink)}>{label}</span>
        <span className="flex shrink-0 items-baseline gap-1">
          {param.control === "number" ? (
            <NumberField
              value={value}
              min={param.min}
              max={param.max}
              step={param.step ?? (param.kind === "int" ? 1 : null)}
              onCommit={(next) => forwardParam(param.id, next, true)}
            />
          ) : (
            <span>{value}</span>
          )}
          {param.unit && <span className="text-[10px] text-muted-foreground">{param.unit}</span>}
        </span>
      </div>
      {param.control === "slider" && param.min !== null && param.max !== null && (
        <Slider
          value={[value]}
          min={param.min}
          max={param.max}
          modified={param.modified}
          step={param.step ?? (param.kind === "int" ? 1 : (param.max - param.min) / 200)}
          onValueChange={([next]) => {
            dragging.current = true;
            setDrag(next);
            forwardParam(param.id, next);
          }}
          onValueCommit={([next]) => {
            dragging.current = false;
            forwardParam(param.id, next, true);
          }}
        />
      )}
    </div>
  );
}

/** A number box that keeps what is being typed: the text is a local draft,
 * committed when typing pauses, on Enter, or on blur. (A controlled box that
 * sends every keystroke gets the server's echo of the first digit back while
 * the second is being typed.) */
function NumberField({
  value,
  min,
  max,
  step,
  onCommit,
}: {
  value: number;
  min: number | null;
  max: number | null;
  step: number | null;
  onCommit: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const editing = useRef(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (!editing.current) setText(String(value));
  }, [value]);

  const commit = (raw: string) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    const next = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(next) && next !== value) onCommit(next);
  };

  return (
    <input
      type="number"
      className="w-16 border-b-2 border-input bg-transparent text-right focus:border-focus focus:outline-none"
      value={text}
      min={min ?? undefined}
      max={max ?? undefined}
      step={step ?? "any"}
      onFocus={() => {
        editing.current = true;
      }}
      onChange={(event) => {
        setText(event.target.value);
        if (timer.current !== null) window.clearTimeout(timer.current);
        const raw = event.target.value;
        timer.current = window.setTimeout(() => commit(raw), 700);
      }}
      onBlur={(event) => {
        editing.current = false;
        commit(event.target.value);
        setText(String(value));
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          commit((event.target as HTMLInputElement).value);
          (event.target as HTMLInputElement).blur();
        }
      }}
    />
  );
}
