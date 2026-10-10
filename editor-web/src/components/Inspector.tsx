import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { PickResult } from "@/scene/Viewport";

export type FederatedNode = { id: string; label: string; kind: string };

/** Right-hand inspector: current selection, feature DAG, package meta. */
export function Inspector({
  pick,
  features,
  packageInfo,
}: {
  pick: PickResult | null;
  features: FederatedNode[];
  packageInfo: { name: string | null; revision: number; occurrences: number; assets: number; exported: string | null } | null;
}) {
  return (
    <Tabs defaultValue="selection" className="h-full">
      <TabsList className="mx-2 mt-2">
        <TabsTrigger value="selection">selection</TabsTrigger>
        <TabsTrigger value="features">features</TabsTrigger>
        <TabsTrigger value="package">package</TabsTrigger>
      </TabsList>
      <TabsContent value="selection" className="h-[calc(100%-3rem)]">
        <ScrollArea className="h-full px-3">
          {pick ? (
            <div className="space-y-2 text-xs">
              <dl className="space-y-1.5">
                <Row label="mode" value={pick.mode} />
                <Row label="node" value={pick.nodeId} mono />
                <Row label="entity" value={pick.entityId ?? "—"} mono />
                {pick.entity?.kind && <Row label="entity kind" value={String(pick.entity.kind)} />}
              </dl>
              <Separator className="my-2" />
              {pick.entity?.properties && (
                <Section title="properties" body={pretty(pick.entity.properties)} />
              )}
              {pick.entity?.geometry && (
                <Section title="geometry" body={pretty(pick.entity.geometry)} />
              )}
              <p className="pt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                Agents read this via GET /api/studio/selected
              </p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Click a solid, face, or edge in the viewport.</p>
          )}
        </ScrollArea>
      </TabsContent>
      <TabsContent value="features" className="h-[calc(100%-3rem)]">
        <ScrollArea className="h-full px-3">
          <ul className="space-y-1 text-xs">
            {features.map((feature) => (
              <li key={feature.id} className="flex items-center gap-2">
                <span className="font-mono text-muted-foreground">{feature.kind}</span>
                <span>{feature.label}</span>
              </li>
            ))}
            {features.length === 0 && (
              <li className="text-xs text-muted-foreground">No features yet — run the notebook.</li>
            )}
          </ul>
        </ScrollArea>
      </TabsContent>
      <TabsContent value="package" className="h-[calc(100%-3rem)]">
        <ScrollArea className="h-full px-3">
          {packageInfo ? (
            <dl className="space-y-1.5 text-xs">
              <Row label="entry" value={packageInfo.name ?? "—"} mono />
              <Row label="revision" value={`#${packageInfo.revision}`} mono />
              <Row label="occurrences" value={String(packageInfo.occurrences)} />
              <Row label="geometry assets" value={String(packageInfo.assets)} />
              <Row label="exported to" value={packageInfo.exported ?? "not exported"} mono />
            </dl>
          ) : (
            <p className="text-xs text-muted-foreground">No package received yet.</p>
          )}
        </ScrollArea>
      </TabsContent>
    </Tabs>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={mono ? "truncate font-mono" : "truncate"} title={value}>
        {value}
      </dd>
    </div>
  );
}

/** Compact JSON for inspector readouts (objects only; scalars inlined). */
function pretty(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value, (_key, item) => (typeof item === "number" ? Number(item.toFixed(3)) : item), 1);
  } catch {
    return String(value);
  }
}

function Section({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      <pre className="max-h-48 overflow-auto rounded bg-background/60 p-1.5 font-mono text-[10px] leading-relaxed text-foreground/85">
        {body}
      </pre>
    </div>
  );
}
