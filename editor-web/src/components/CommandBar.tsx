import { ChevronsDownUp, ChevronsUpDown, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { commandGroups, pushRecent, searchCommands, type Command } from "@/lib/commands";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

const RECENT_KEY = "sca.commandbar.recent";
const VISIBLE_ROWS = 6;

function readStore<T>(key: string, fallback: T, parse: (raw: string) => T | null): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : (parse(raw) ?? fallback);
  } catch {
    return fallback;
  }
}
function writeStore(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private window or blocked storage: the bar still works */
  }
}

/** A floating command bar over the viewport: category chips, a search box, a short result list.
 * `/` or Ctrl/Cmd+K focuses the search; Up/Down move, Enter runs, Esc closes the list.
 * It sits at the bottom of the viewport and collapses to a pill; `shown` slides it in from below (manual mode) or out. */
export function CommandBar({ commands, fit, hint, shown: onScreen = true }: { commands: Command[]; /** How much a command fits the selection (see fitScore): the fitting ones come first. */ fit?: (command: Command) => number; /** One line saying what the selection can do. */ hint?: string | null; /** In view (it slides in from the bottom edge and back out). */ shown?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => readStore<string[]>(RECENT_KEY, [], (raw) => (Array.isArray(JSON.parse(raw)) ? (JSON.parse(raw) as string[]) : null)));
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [focusAsked, setFocusAsked] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const groups = useMemo(() => commandGroups(commands), [commands]);
  const results = useMemo(() => {
    const listed = commands.filter((command) => !command.contextOnly || (fit?.(command) ?? 0) > 0);
    const pool = group && !query.trim() ? listed.filter((command) => command.group === group) : listed;
    return searchCommands(pool, query, recent, fit);
  }, [commands, group, query, recent, fit]);
  const shown = open ? results : [];
  const at = Math.min(highlight, Math.max(shown.length - 1, 0));

  const run = useCallback(
    (command: Command) => {
      const next = pushRecent(recent, command.id);
      setRecent(next);
      writeStore(RECENT_KEY, JSON.stringify(next));
      setOpen(false);
      setQuery("");
      setGroup(null);
      input.current?.blur();
      command.run();
    },
    [recent],
  );

  // `/` and Ctrl/Cmd+K focus the search (`/` only when no text field has the focus).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = Boolean(target?.closest("input, textarea, select, [contenteditable=true], .cm-editor"));
      const palette = (event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k";
      const slash = event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey && !typing;
      if (!palette && !slash) return;
      event.preventDefault();
      setCollapsed(false);
      setFocusAsked((count) => count + 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (focusAsked > 0 && !collapsed) {
      input.current?.focus();
      input.current?.select();
      setOpen(true);
      setHighlight(0);
    }
  }, [focusAsked, collapsed]);

  // A click outside closes the list.
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>("[data-active=true]")?.scrollIntoView({ block: "nearest" });
  }, [at, shown.length]);

  const onInputKey = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((at + step + shown.length) % Math.max(shown.length, 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const command = shown[at];
      if (command) run(command);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (open) setOpen(false);
      else input.current?.blur();
    }
  };

  // out of view: below the viewport's bottom edge, and nothing in it takes the pointer or the keyboard
  const slide = {
    style: { transform: onScreen ? "translateY(0)" : "translateY(calc(100% + 1.5rem))", transition: "transform 300ms cubic-bezier(0.12, 0.85, 0.25, 1)" },
    inert: !onScreen,
  };

  if (collapsed) {
    return (
      <div className="pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center" {...slide}>
        <button
          type="button"
          className="pointer-events-auto flex items-center gap-1.5 border-2 border-primary bg-background px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] shadow-[4px_4px_0_var(--shadow-hard)] hover:border-focus"
          title={t("Show the command bar (/ or Ctrl/Cmd+K)")}
          aria-label={t("Show the command bar")}
          onClick={() => setCollapsed(false)}
        >
          <ChevronsUpDown className="size-3.5" /> {t("add feature")}
        </button>
      </div>
    );
  }

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 z-20 flex justify-center px-3" {...slide}>
      <div ref={root} role="toolbar" aria-label={t("Command bar")} className="pointer-events-auto relative w-full max-w-[720px]">
        {shown.length > 0 && (
          <ul
            ref={listRef}
            role="listbox"
            aria-label={t("Operations")}
            className={cn(
              "absolute inset-x-0 overflow-y-auto border-2 border-primary bg-popover shadow-[4px_4px_0_var(--shadow-hard)]",
              "bottom-full mb-1",
            )}
            style={{ maxHeight: `${VISIBLE_ROWS * 34}px` }}
          >
            {shown.map((command, index) => {
              const Icon = command.icon;
              return (
                <li
                  key={command.id}
                  role="option"
                  aria-selected={index === at}
                  data-active={index === at}
                  className={cn("flex h-[34px] cursor-pointer items-center gap-2 px-2 text-[12px]", index === at ? "bg-primary text-primary-foreground" : "hover:bg-accent")}
                  onMouseMove={() => setHighlight(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => run(command)}
                >
                  {Icon ? <Icon className="size-3.5 shrink-0" /> : <span className="size-3.5 shrink-0" />}
                  <span className="shrink-0 font-semibold">{t(command.label)}</span>
                  <span className={cn("min-w-0 flex-1 truncate text-[11px]", index === at ? "opacity-80" : "text-muted-foreground")}>{command.description ? t(command.description) : null}</span>
                  <span className={cn("shrink-0 text-[10px] uppercase tracking-[0.08em]", fit && fit(command) > 0 ? "font-bold" : "opacity-70")}>{fit && fit(command) > 0 ? t("fits selection") : t(command.group)}</span>
                </li>
              );
            })}
          </ul>
        )}
        {hint && (
          <p data-testid="command-hint" className={cn("absolute inset-x-0 border-2 border-focus bg-popover px-2 py-0.5 text-[11px]", shown.length > 0 ? "hidden" : "bottom-full mb-1")}>
            {hint}
          </p>
        )}
        <div className="flex flex-col gap-1 border-2 border-primary bg-background p-1 shadow-[4px_4px_0_var(--shadow-hard)]">
          <div className="scroll-row items-center gap-0.5">
            {groups.map((name) => (
              <button
                key={name}
                type="button"
                aria-pressed={group === name}
                className={cn(
                  "border-2 px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.08em] transition-colors",
                  group === name ? "border-primary bg-primary text-primary-foreground" : "border-transparent text-muted-foreground hover:border-input hover:text-foreground",
                )}
                onClick={() => {
                  const same = group === name && open;
                  setGroup(same ? null : name);
                  setQuery("");
                  setHighlight(0);
                  setOpen(!same);
                }}
              >
                {t(name)}
              </button>
            ))}
          </div>
          <div className="flex min-w-[220px] flex-1 items-center gap-0.5">
          <label className="relative min-w-[120px] flex-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={input}
              value={query}
              role="combobox"
              aria-expanded={open}
              aria-label={t("Search operations")}
              placeholder={t("Search operations")}
              spellCheck={false}
              className="h-6 w-full border-2 border-input bg-background pl-6 pr-[78px] text-[12px] placeholder:text-muted-foreground focus-visible:border-focus focus-visible:outline-none"
              onChange={(event) => {
                setQuery(event.target.value);
                setGroup(null);
                setHighlight(0);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onKeyDown={onInputKey}
            />
            {!query && (
              <kbd className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 border border-input px-1 text-[9px] uppercase text-muted-foreground">{t("/ or Ctrl+K")}</kbd>
            )}
          </label>
          <button type="button" className="p-1 text-muted-foreground hover:text-foreground" aria-label={t("Collapse the command bar")} title={t("Collapse to a pill")} onClick={() => { setOpen(false); setCollapsed(true); }}>
            <ChevronsDownUp className="size-3.5" />
          </button>
          </div>
        </div>
      </div>
    </div>
  );
}
