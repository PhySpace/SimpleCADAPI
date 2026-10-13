import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { ModuleRow, NotebookRow } from "@/lib/api";

/** The workspace: its SimpleCAD notebooks (assemblies show what they use) and
 * the local modules they import. Editing a module changes every notebook
 * that imports it. */
export function NotebookList({
  notebooks,
  current,
  modules,
  openModule,
  onOpen,
  onOpenModule,
}: {
  notebooks: NotebookRow[];
  /** Workspace-relative path of the open notebook. */
  current: string | null;
  modules: ModuleRow[];
  openModule: string | null;
  onOpen: (path: string) => void;
  onOpenModule: (path: string) => void;
}) {
  if (notebooks.length === 0 && modules.length === 0) {
    return <p className="p-3 text-[11px] text-muted-foreground">No SimpleCAD notebooks in this workspace.</p>;
  }
  return (
    <ScrollArea className="h-full">
      <p className="label border-b border-border px-3 py-1.5">notebooks</p>
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
