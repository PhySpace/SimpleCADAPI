import { describe, expect, it } from "vitest";

import type { Spec } from "@/lib/features";
import type { SelectionItem } from "@/lib/selection";
import { featureParams, quickStart } from "@/lib/operation-session";

const FILLET: Spec = {
  id: "fillet",
  label: "Fillet",
  group: "Features",
  role: "modifier",
  produces: "solid",
  description: "Round the picked edges.",
  slots: [
    { name: "body", label: "Body", kind: "body" },
    { name: "edges", label: "Edges", kind: "select", entity: "edge" },
    { name: "radius", label: "Radius", kind: "length", default: 0.5, unit: "mm", min: 0.001 },
  ],
};

const edge = (key: string, described = true): SelectionItem =>
  ({
    key,
    kind: "edge",
    nodeId: "node/demo",
    entityId: `entity/demo/edge/${key}`,
    definitionId: "demo",
    variable: "selected_edge",
    properties: described ? { length: 10 } : null,
    geometry: described ? { type: "line" } : null,
    pending: !described,
  }) as unknown as SelectionItem;

const state = { defaults: { fillet: { body: "base" } }, taken: ["base", "fillet"] };

describe("an operation started on the selection", () => {
  it("adds a fillet on the picked edges with its small default radius", () => {
    const start = quickStart(FILLET, state, [edge("e1"), edge("e2")]);
    expect(start?.command.spec).toBe("fillet");
    expect(start?.command.values).toEqual({ body: "base", radius: 0.5 });
    expect(start?.command.selections?.edges.map((item) => item.entity_id)).toEqual(["entity/demo/edge/e1", "entity/demo/edge/e2"]);
    expect(start?.name).not.toBe("fillet"); // a free name
  });

  it("needs its dialog when nothing is picked; picks still loading their details do not hold it up", () => {
    expect(quickStart(FILLET, state, [])).toBeNull();
    expect(quickStart(FILLET, state, [edge("e1", false)])?.command.selections?.edges.map((item) => item.entity_id)).toEqual(["entity/demo/edge/e1"]);
  });

  it("keeps the dialog for operations that need a placement", () => {
    expect(quickStart({ ...FILLET, id: "hole" }, state, [edge("e1")])).toBeNull();
  });

  it("finds a feature's parameters by the params cell that declares them", () => {
    const params = [
      { id: "FILLET_RADIUS", group: "fillet" },
      { id: "FILLET_2_RADIUS", group: "fillet_2" },
      { id: "RADIUS", group: "" },
    ];
    expect(featureParams(params, "fillet").map((p) => p.id)).toEqual(["FILLET_RADIUS"]);
  });
});
