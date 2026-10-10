import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { JsonTree } from "@/components/JsonTree";
import type { SelectionItem } from "@/lib/selection";

/** Right-hand inspector: what is selected in the viewport, each item with
 * the variable the selection cell assigns it to and its data as a tree. */
export function Inspector({ selection }: { selection: SelectionItem[] }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center justify-between border-b-2 border-border px-3">
        <span className="label text-foreground">selection</span>
        {selection.length > 0 && <span className="label">{selection.length}</span>}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {selection.length === 0 ? (
          <p className="p-3 text-[11px] text-muted-foreground">
            Click a solid, face, edge or vertex in the viewport. Ctrl/Cmd+click adds to the selection; the selection
            is written to the notebook as <span className="text-name">selected_item</span>.
          </p>
        ) : (
          <ul>
            {selection.map((item) => (
              <li key={item.key} className="border-b-2 border-border">
                <div className="flex items-center gap-2 px-3 py-2">
                  <Badge variant="focus">{item.kind}</Badge>
                  <span className="min-w-0 flex-1 truncate text-name" title={item.variable}>
                    {item.variable}
                  </span>
                </div>
                <dl className="space-y-0.5 px-3 pb-2 text-[11px]">
                  <Line label="entity" value={item.entityId ?? "—"} />
                  <Line label="node" value={item.nodeId} />
                  {item.definitionId && <Line label="definition" value={item.definitionId} />}
                </dl>
                {(item.properties || item.geometry) && (
                  <div className="space-y-2 border-t border-border px-3 py-2">
                    {item.properties && <Group title="properties" value={item.properties} />}
                    {item.geometry && <Group title="geometry" value={item.geometry} />}
                    {item.tags && item.tags.length > 0 && <Group title="tags" value={item.tags} />}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-16 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1 break-all" title={value}>
        {value}
      </dd>
    </div>
  );
}

function Group({ title, value }: { title: string; value: unknown }) {
  return (
    <div>
      <p className="label mb-1">{title}</p>
      <JsonTree value={value} openDepth={2} />
    </div>
  );
}
