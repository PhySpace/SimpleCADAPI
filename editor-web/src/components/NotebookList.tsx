import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { NotebookRow } from "@/lib/api";

/** Workspace notebook list. Entries are executable models; helpers are
 * listed for orientation but opening one is refused by the server. */
export function NotebookList({
  notebooks,
  onOpen,
}: {
  notebooks: NotebookRow[];
  onOpen: (path: string) => void;
}) {
  if (notebooks.length === 0) {
    return <p className="p-3 text-xs text-muted-foreground">No notebooks in this workspace.</p>;
  }
  return (
    <ScrollArea className="h-full">
      <ul className="p-1.5">
        {notebooks.map((row) => (
          <li key={row.path}>
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-accent",
                row.current && "bg-accent",
              )}
              onClick={() => !row.current && onOpen(row.path)}
              title={row.path}
            >
              <span className="font-mono">{row.name}</span>
              {row.entry ? (
                <Badge variant="default">{row.kind}</Badge>
              ) : (
                <Badge variant="outline" className="text-muted-foreground">
                  helper
                </Badge>
              )}
              {row.current && <span className="ml-auto text-[10px] uppercase text-primary">open</span>}
            </button>
          </li>
        ))}
      </ul>
    </ScrollArea>
  );
}
