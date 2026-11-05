import { useState } from "react";
import { FilePlus2, X } from "lucide-react";

/** Shown over the viewport when an operation or a drawing is started with no notebook open: everything the editor does
 * is written into a notebook, so one has to exist first.  Creates it here (a part, empty) or sends the person away. */
export function NewNotebookPrompt({ onCreate, onClose }: { onCreate: (name: string) => Promise<void>; onClose: () => void }) {
  const [name, setName] = useState("part");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await onCreate(name.trim());
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="pointer-events-auto absolute inset-0 z-30 flex items-center justify-center bg-background/40" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Create a notebook first"
        className="flex w-[min(380px,90%)] flex-col gap-3 border-2 border-[var(--focus)] bg-popover p-4 text-xs shadow-[4px_4px_0_var(--shadow-hard)]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 font-semibold">
          <FilePlus2 className="size-4 text-[var(--focus)]" />
          <span className="flex-1">No notebook is open</span>
          <button type="button" aria-label="Close" className="hover:text-foreground text-muted-foreground" onClick={onClose}>
            <X className="size-3.5" />
          </button>
        </div>
        <p className="text-muted-foreground">Every operation and drawing is written into a notebook. Create one first (it starts empty).</p>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void create();
          }}
        >
          <input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="min-w-0 flex-1 border border-border bg-background px-2 py-1 font-mono"
            aria-label="Notebook name"
          />
          <button type="submit" disabled={busy || !name.trim()} className="border-2 border-foreground bg-foreground px-3 py-1 font-semibold text-background disabled:opacity-50">
            Create
          </button>
        </form>
        {error && <p className="text-destructive">{error}</p>}
      </div>
    </div>
  );
}
