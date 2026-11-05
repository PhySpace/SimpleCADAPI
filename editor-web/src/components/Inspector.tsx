import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { JsonTree } from "@/components/JsonTree";
import type { SelectionItem } from "@/lib/selection";
import { t } from "@/i18n";

/** Right-hand inspector: what is selected in the viewport, each item with
 * the variable the selection cell assigns it to and its data as a tree. */
export function Inspector({ selection, sketches = [] }: { selection: SelectionItem[]; sketches?: { name: string; rows: { label: string; value: string }[] }[] }) {
  const count = selection.length + sketches.length;
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center justify-between border-b-2 border-border pl-3 pr-10">
        <span className="label text-foreground">{t("selection")}</span>
        {count > 0 && <span className="label">{count}</span>}
      </div>
      <ScrollArea className="min-h-0 flex-1">
        {count === 0 ? (
          <p className="p-3 text-[11px] text-muted-foreground">
            {t("Click a solid, face, edge, vertex or sketch in the viewport (pick the kind with the chips). Ctrl/Cmd+click adds to the selection; picked model items are written to the notebook as")}{" "}
            <span className="text-name">selected_item</span>.
          </p>
        ) : (
          <ul>
            {sketches.map((sketch) => (
              <li key={`sketch:${sketch.name}`} className="border-b-2 border-border" data-testid="inspector-sketch">
                <div className="flex items-center gap-2 px-3 py-2">
                  <Badge variant="focus">sketch</Badge>
                  <span className="min-w-0 flex-1 truncate text-name" title={sketch.name}>
                    {sketch.name}
                  </span>
                </div>
                <dl className="space-y-0.5 px-3 pb-2 text-[11px]">
                  {sketch.rows.map((row) => (
                    <Line key={row.label} label={row.label} value={row.value} />
                  ))}
                </dl>
              </li>
            ))}
            {selection.map((item) => (
              <li key={item.key} className="border-b-2 border-border">
                <div className="flex items-center gap-2 px-3 py-2">
                  <Badge variant="focus">{item.kind}</Badge>
                  <span className="min-w-0 flex-1 truncate text-name" title={item.variable}>
                    {item.variable}
                  </span>
                </div>
                <dl className="space-y-0.5 px-3 pb-2 text-[11px]">
                  <Line label={t("entity")} value={item.entityId ?? "—"} />
                  <Line label={t("node")} value={item.nodeId} />
                  {item.definitionId && <Line label={t("definition")} value={item.definitionId} />}
                </dl>
                {item.pending && <p className="label px-3 pb-2">{t("loading details…")}</p>}
                {(item.properties || item.geometry) && (
                  <div className="space-y-2 border-t border-border px-3 py-2">
                    {item.properties && <Group title={t("properties")} value={item.properties} />}
                    {item.geometry && <Group title={t("geometry")} value={item.geometry} />}
                    {item.tags && item.tags.length > 0 && <Group title={t("tags")} value={item.tags} />}
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
      <dt className="w-[5.5rem] shrink-0 text-muted-foreground">{label}</dt>
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
