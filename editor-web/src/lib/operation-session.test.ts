import { describe, expect, it } from "vitest";

import type { Spec } from "@/lib/features";
import type { SelectionItem } from "@/lib/selection";
import { addPick, featureParams, pickSlot, quickStart, refLabel, removePick } from "@/lib/operation-session";

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

describe("picks added and taken out while tuning", () => {
  const top = { kind: "face", feature: "base", op: "make_box_rsolid", role: "box.top", ordinal: 0 };
  const side = { kind: "face", feature: "base", op: "make_box_rsolid", role: "box.front", ordinal: 0 };

  it("adds to the one slot that takes several picks", () => {
    expect(pickSlot(FILLET)).toEqual({ slot: "edges", entity: "edge", label: "Edges" });
    const single: Spec = { ...FILLET, slots: [{ name: "face", label: "Face", kind: "select", entity: "face", single: true }] };
    expect(pickSlot(single)).toBeNull();
  });

  it("sends back what the feature holds as references, then the new pick", () => {
    const added = addPick([top], edge("e1"));
    expect(added[0]).toEqual({ kind: "face", ref: top });
    expect(added[1]).toMatchObject({ kind: "edge", entity_id: "entity/demo/edge/e1" });
    expect(removePick([top, side], 0)).toEqual([{ kind: "face", ref: side }]);
  });

  it("names a reference by its feature and role", () => {
    expect(refLabel(top)).toBe("base · box.top");
    expect(refLabel({ kind: "edge", op: "make_fillet_rsolid", ordinal: 2, piece: 1 })).toBe("fillet · #3 (2)");
  });
});
