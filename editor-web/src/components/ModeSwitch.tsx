import { cn } from "@/lib/utils";
import { t } from "@/i18n";

export type EditorMode = "manual" | "code";

const OPTIONS: { value: EditorMode; label: string; hint: string }[] = [
  { value: "manual", label: "Manual mode", hint: "Model with buttons and dialogs: features, sketches, assemblies" },
  { value: "code", label: "Code mode", hint: "The notebook behind the model: cells, parameters, the workspace" },
];

/** The big two-position switch of the top bar: manual mode on the left, code mode on the right. */
export function ModeSwitch({ mode, onChange, disabled }: { mode: EditorMode; onChange: (mode: EditorMode) => void; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label={t("Editor mode")} data-testid="mode-switch" className={cn("relative grid h-8 grid-cols-2 border-2 border-primary", disabled && "opacity-50")}>
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-0 left-0 w-1/2 bg-primary transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)]"
        style={{ transform: mode === "code" ? "translateX(100%)" : "translateX(0)" }}
      />
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={mode === option.value}
          title={t(option.hint)}
          disabled={disabled}
          data-mode={option.value}
          onClick={() => option.value !== mode && onChange(option.value)}
          className={cn(
            "relative z-10 px-4 text-[11px] font-bold uppercase tracking-[0.12em] transition-colors duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus",
            mode === option.value ? "text-primary-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(option.label)}
        </button>
      ))}
    </div>
  );
}
