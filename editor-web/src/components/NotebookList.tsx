import { Plus } from "lucide-react";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ModuleRow, NotebookRow } from "@/lib/api";

/** Names the template accepts: the notebook's id and its file name. */
const NAME = /^[A-Za-z_][A-Za-z0-9_-]*$/;

/** The workspace: its SimpleCAD notebooks (assemblies show what they use) and
 * the local modules they import. Editing a module changes every notebook
 * that imports it. A new notebook starts from the SDK's template. */
export function NotebookList({
  notebooks,
  current,
  modules,
  openModule,
  onOpen,
  onOpenModule,
  onCreate,
}: {
  notebooks: NotebookRow[];
  /** Workspace-relative path of the open notebook. */
  current: string | null;
  modules: ModuleRow[];
  openModule: string | null;
  onOpen: (path: string) => void;
  onOpenModule: (path: string) => void;
  /** Write a new notebook and open it; rejects with the reason it could not. */
  onCreate: (name: string, kind: "part" | "assembly") => Promise<void>;
}) {
  const [adding, setAdding] = useState(false);
  const empty = notebooks.length === 0;
  return (
    <ScrollArea className="h-full">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="label">notebooks</span>
        <button
          type="button"
          className="label flex items-center gap-1 hover:text-foreground"
          title="Start a new notebook from the template"
          onClick={() => setAdding((open) => !open)}
        >
          <Plus className="h-3 w-3" /> new
        </button>
      </div>
      {(adding || empty) && (
        <NewEntry notebooks={notebooks} first={empty} onCreate={onCreate} onDone={() => setAdding(false)} onCancel={() => setAdding(false)} />
      )}
      <ul>
        {notebooks.map((row) => (
          <li key={row.path} className="border-b border-border">
            <button
              type="button"
              className={cn(
                "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left hover:bg-accent",
                row.path === current ? "border-focus bg-accent" : "border-transparent",
              )}
              onClick={() => row.path !== current && onOpen(row.path)}
              title={row.path}
            >
              <span className="flex items-center gap-2">
                <span className={row.path === current ? "text-focus" : "text-foreground"}>{row.name}</span>
                <Badge variant="secondary">{row.kind}</Badge>
                {row.error && <Badge variant="fail">error</Badge>}
              </span>
              {row.uses && row.uses.length > 0 && (
                <span className="truncate text-[10px] text-muted-foreground">
                  uses {row.uses.map((use) => use.split("/").pop()?.replace(/\.py$/, "")).join(", ")}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
      {modules.length > 0 && (
        <>
          <p className="label border-b border-t border-border px-3 py-1.5">modules</p>
          <ul>
            {modules.map((module) => (
              <li key={module.path} className="border-b border-border">
                <button
                  type="button"
                  className={cn(
                    "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left hover:bg-accent",
                    openModule === module.path ? "border-name bg-accent" : "border-transparent",
                  )}
                  onClick={() => onOpenModule(module.path)}
                  title={module.path}
                >
                  <span className={openModule === module.path ? "text-name" : "text-foreground"}>{module.path}</span>
                  <span className="truncate text-[10px] text-muted-foreground">
                    used by {module.used_by.map((path) => path.replace(/\.py$/, "")).join(", ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </ScrollArea>
  );
}

/** The form for a new notebook: a name and what it is. */
function NewEntry({
  notebooks,
  first,
  onCreate,
  onDone,
  onCancel,
}: {
  notebooks: NotebookRow[];
  /** The workspace has no notebook yet. */
  first: boolean;
  onCreate: (name: string, kind: "part" | "assembly") => Promise<void>;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"part" | "assembly">("part");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const parts = notebooks.filter((row) => row.kind === "part");
  const taken = (value: string) => notebooks.some((row) => row.path === `${value}.py`);

  const submit = async () => {
    const value = name.trim();
    if (!NAME.test(value)) return setError("Use letters, digits, - and _, starting with a letter or _.");
    if (taken(value)) return setError(`${value}.py already exists.`);
    setBusy(true);
    setError(null);
    try {
      await onCreate(value, kind);
      onDone();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the notebook.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="space-y-2 border-b border-border bg-card px-3 py-3"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      {first && <p className="text-[11px] text-muted-foreground">An empty workspace. Start with a part: a notebook that builds one solid.</p>}
      <input
        ref={input}
        autoFocus
        value={name}
        onChange={(event) => {
          setName(event.target.value);
          setError(null);
        }}
        onKeyDown={(event) => event.key === "Escape" && !first && onCancel()}
        placeholder="name, e.g. bracket"
        aria-label="Name of the new notebook"
        spellCheck={false}
        className="w-full border-2 border-input bg-transparent px-2 py-1 focus:border-focus focus:outline-none"
      />
      <div className="flex gap-1">
        {(["part", "assembly"] as const).map((option) => (
          <button
            key={option}
            type="button"
            disabled={option === "assembly" && parts.length === 0}
            title={option === "assembly" && parts.length === 0 ? "An assembly puts parts together: create a part first" : undefined}
            onClick={() => {
              setKind(option);
              input.current?.focus(); // Enter then creates
            }}
            className={cn(
              "border-2 px-2 py-px text-[10px] font-semibold uppercase tracking-[0.1em] transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              kind === option ? "border-primary bg-primary text-primary-foreground" : "border-transparent text-muted-foreground hover:border-input hover:text-foreground",
            )}
          >
            {option}
          </button>
        ))}
      </div>
      {kind === "assembly" && parts.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          Starts with {parts.slice(0, 2).map((row) => row.name).join(" and ")}; change what it uses in its cells.
        </p>
      )}
      {error && <p className="text-[11px] text-fail">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={busy || !name.trim()}>
          create
        </Button>
        {!first && (
          <Button size="sm" type="button" variant="ghost" onClick={onCancel}>
            cancel
          </Button>
        )}
      </div>
    </form>
  );
}
