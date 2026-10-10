import { useState } from "react";
import { Download, ExternalLink, Plus, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** Top bar: workspace identity, runtime state, and global actions. */
export function Header({
  notebook,
  kind,
  kernelAlive,
  status,
  onExport,
  onRerun,
  onNewNotebook,
  marimoUrl,
}: {
  notebook: string | null;
  kind: string | null;
  kernelAlive: boolean;
  status: string;
  onExport: () => void;
  onRerun: () => void;
  onNewNotebook: (name: string, kind: "part" | "assembly") => void;
  marimoUrl: string | null;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [kindChoice, setKindChoice] = useState<"part" | "assembly">("part");

  const submit = async () => {
    if (!name.trim()) return;
    onNewNotebook(name.trim(), kindChoice);
    setName("");
    setCreating(false);
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3">
      <span className="text-sm font-semibold tracking-tight">SimpleCAD Studio</span>
      {notebook && (
        <span className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="font-mono text-foreground">{notebook}</span>
          {kind && kind !== "helper" && <Badge variant={kind === "entry" ? "default" : "secondary"}>{kind}</Badge>}
        </span>
      )}
      <span className={`ml-1 inline-block h-2 w-2 rounded-full ${kernelAlive ? "bg-primary" : "bg-destructive"}`} />
      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={status}>
        {status}
      </span>
      {creating ? (
        <span className="flex items-center gap-1.5">
          <input
            autoFocus
            value={name}
            placeholder="name"
            className="h-7 w-32 rounded-md border bg-background px-2 font-mono text-xs"
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && void submit()}
          />
          <select
            value={kindChoice}
            className="h-7 rounded-md border bg-background px-1 text-xs"
            onChange={(event) => setKindChoice(event.target.value as "part" | "assembly")}
          >
            <option value="part">part</option>
            <option value="assembly">assembly</option>
          </select>
          <Button size="sm" onClick={() => void submit()}>
            create
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>
            cancel
          </Button>
        </span>
      ) : (
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          <Plus /> new
        </Button>
      )}
      <Button size="sm" variant="outline" onClick={onRerun} title="Re-run the entry cell">
        <RefreshCw /> rerun
      </Button>
      <Button size="sm" onClick={onExport} title="Persist <entry>.scadpkg next to the entry script">
        <Download /> export
      </Button>
      {marimoUrl && (
        <Button size="sm" variant="ghost" asChild>
          <a href={marimoUrl} target="_blank" rel="noreferrer" title="Open the raw marimo editor">
            <ExternalLink /> marimo
          </a>
        </Button>
      )}
    </header>
  );
}
