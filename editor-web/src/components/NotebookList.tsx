import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { NotebookRow } from "@/lib/api";

/** The SimpleCAD notebooks of the workspace; assemblies show what they use. */
export function NotebookList({
  notebooks,
  onOpen,
}: {
  notebooks: NotebookRow[];
  onOpen: (path: string) => void;
}) {
  if (notebooks.length === 0) {
    return <p className="p-3 text-[11px] text-muted-foreground">No SimpleCAD notebooks in this workspace.</p>;
  }
  return (
    <ScrollArea className="h-full">
      <ul>
        {notebooks.map((row) => (
          <li key={row.path} className="border-b border-border">
            <button
              type="button"
              className={cn(
                "flex w-full flex-col gap-0.5 border-l-2 px-3 py-2 text-left hover:bg-accent",
                row.current ? "border-focus bg-accent" : "border-transparent",
              )}
              onClick={() => !row.current && onOpen(row.path)}
              title={row.path}
            >
              <span className="flex items-center gap-2">
                <span className={row.current ? "text-focus" : "text-foreground"}>{row.name}</span>
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
    </ScrollArea>
  );
}
