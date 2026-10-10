/** One picked entity, as the editor tracks it and sends it to the server. */
export type SelectionItem = {
  /** `nodeId::entityId`, unique per picked thing. */
  key: string;
  /** `component` (an occurrence), or the entity's own kind. */
  kind: "component" | "solid" | "face" | "edge" | "vertex";
  nodeId: string;
  entityId: string | null;
  definitionId: string | null;
  properties: Record<string, unknown> | null;
  geometry: Record<string, unknown> | null;
  tags: string[] | null;
  /** The `selected_*` variable the notebook assigns it to (set by the server). */
  variable: string;
};

/** The names the server gives the items, mirrored for the inspector:
 * `selected_<kind>`, or `selected_<kind>_<i>` per kind when there are several. */
export function variableNames(items: { kind: string }[]): string[] {
  const totals = new Map<string, number>();
  for (const item of items) totals.set(item.kind, (totals.get(item.kind) ?? 0) + 1);
  const seen = new Map<string, number>();
  return items.map((item) => {
    const index = (seen.get(item.kind) ?? 0) + 1;
    seen.set(item.kind, index);
    return totals.get(item.kind) === 1 ? `selected_${item.kind}` : `selected_${item.kind}_${index}`;
  });
}

/** What goes over the wire (`selection.set`). */
export function selectionPayload(items: SelectionItem[]): Record<string, unknown>[] {
  return items.map((item) => ({
    kind: item.kind,
    entity_id: item.entityId,
    node_id: item.nodeId,
    definition_id: item.definitionId,
    properties: item.properties,
    geometry: item.geometry,
  }));
}
