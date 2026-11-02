import { describe, expect, it } from "vitest";

import {
  addComponent,
  addConnectorFromFace,
  addConstraint,
  applyCommand,
  assemblyProblems,
  assemblyStatus,
  axesConflict,
  connectorFrameFromFace,
  connectorProblems,
  connectorsUrl,
  emptyAssembly,
  idFromPart,
  idProblem,
  normalizeAssembly,
  placementToWorld,
  removeComponent,
  removeConnector,
  renameComponent,
  renameConnector,
  setAxis,
  setConnectorsCommand,
  setGround,
  setKind,
  setRef,
  sideName,
  uniqueId,
  updateConstraint,
  type AssemblyDoc,
} from "@/lib/assembly";

const two = (): AssemblyDoc => addComponent(addComponent(emptyAssembly(), "parts/base.py").doc, "parts/arm.py").doc;

describe("components", () => {
  it("derives valid ids from part paths", () => {
    expect(idFromPart("parts/Base Plate-2.py")).toBe("base_plate_2");
    expect(idFromPart("3d_arm.py")).toBe("c_3d_arm");
  });
  it("makes ids unique", () => {
    expect(uniqueId("arm", ["arm", "arm_2"])).toBe("arm_3");
    const doc = addComponent(addComponent(emptyAssembly(), "a/arm.py").doc, "b/arm.py").doc;
    expect(doc.components.map((c) => c.id)).toEqual(["arm", "arm_2"]);
  });
  it("grounds the first component only", () => {
    const doc = two();
    expect(doc.ground).toBe("base");
    expect(doc.components[1].origin).toEqual([0, 0, 0]);
  });
  it("removes a component with its constraints and the ground", () => {
    let doc = two();
    doc = addConstraint(doc).doc;
    expect(doc.constraints).toHaveLength(1);
    const without = removeComponent(doc, "arm");
    expect(without.constraints).toEqual([]);
    expect(removeComponent(without, "base").ground).toBeNull();
  });
  it("renames everywhere", () => {
    let doc = addConstraint(two()).doc;
    doc = renameComponent(doc, "base", "frame");
    expect(doc.ground).toBe("frame");
    expect(doc.constraints[0].a.component).toBe("frame");
    expect(doc.components[0].id).toBe("frame");
  });
  it("explains a bad or taken id", () => {
    const doc = two();
    expect(idProblem(doc, "arm", "Arm")).toMatch(/lowercase/);
    expect(idProblem(doc, "arm", "base")).toMatch(/already/);
    expect(idProblem(doc, "arm", "arm")).toBeNull();
  });
});

describe("axis rule", () => {
  it("treats +x and -x as the same line", () => {
    expect(axesConflict("+x", "-x")).toBe(true);
    expect(axesConflict("+x", "+y")).toBe(false);
  });
  it("moves the other axis off the line instead of leaving an invalid document", () => {
    let doc = two();
    doc = setAxis(doc, "arm", "x_axis", "+y"); // y was +y
    const arm = doc.components.find((c) => c.id === "arm")!;
    expect(arm.x_axis).toBe("+y");
    expect(axesConflict(arm.x_axis, arm.y_axis)).toBe(false);
    expect(assemblyProblems(doc)).toEqual([]);
  });
  it("is reported when a document breaks it", () => {
    const doc = two();
    doc.components[0].y_axis = "-x";
    expect(assemblyProblems(doc).join()).toMatch(/same line/);
  });
});

describe("constraints and validity before sending", () => {
  it("a new constraint joins the ground and another component with the connectors still to choose", () => {
    const { doc, id } = addConstraint(two());
    const k = doc.constraints.find((c) => c.id === id)!;
    expect([k.a.component, k.b.component]).toEqual(["base", "arm"]);
    expect(assemblyProblems(doc).join()).toMatch(/pick the connector of A/);
  });
  it("is valid once both connectors are chosen", () => {
    let doc = addConstraint(two()).doc;
    doc = setRef(doc, "k1", "a", { connector: "top" });
    doc = setRef(doc, "k1", "b", { connector: "root" });
    expect(assemblyProblems(doc)).toEqual([]);
  });
  it("picking another component resets the connector", () => {
    let doc = addConstraint(two()).doc;
    doc = setRef(doc, "k1", "a", { connector: "top" });
    doc = setRef(doc, "k1", "a", { component: "arm" });
    expect(doc.constraints[0].a).toEqual({ component: "arm", connector: "" });
  });
  it("refuses one component joined to itself, constraints without ground, and unordered limits", () => {
    let doc = addConstraint(two()).doc;
    doc = setRef(setRef(doc, "k1", "a", { connector: "x" }), "k1", "b", { connector: "y" });
    expect(assemblyProblems(updateConstraint(doc, "k1", { b: { component: "base", connector: "y" } })).join()).toMatch(/two different components/);
    expect(assemblyProblems(setGround(doc, null)).join()).toMatch(/grounded component/);
    expect(assemblyProblems(updateConstraint(doc, "k1", { limit: [10, -10] })).join()).toMatch(/lower limit/);
  });
  it("requires positive radii for gear, belt and rack-pinion", () => {
    let doc = addConstraint(two(), "gear").doc;
    doc = setRef(setRef(doc, "k1", "a", { connector: "x" }), "k1", "b", { connector: "y" });
    expect(assemblyProblems(doc).join()).toMatch(/pitch radius A is required/);
    doc = updateConstraint(doc, "k1", { pitch_radius_a: 10, pitch_radius_b: 0 });
    expect(assemblyProblems(doc).join()).toMatch(/pitch radius B must be greater than zero/);
    doc = updateConstraint(doc, "k1", { pitch_radius_b: 5 });
    expect(assemblyProblems(doc)).toEqual([]);
    expect(assemblyProblems(setKind(doc, "k1", "belt")).join()).toMatch(/pulley radius A is required/);
  });
  it("changing the kind keeps only the fields the kind carries", () => {
    let doc = addConstraint(two(), "revolute").doc;
    doc = updateConstraint(doc, "k1", { drive: 30, limit: [-90, 90] });
    const prismatic = setKind(doc, "k1", "prismatic").constraints[0];
    expect(prismatic.drive).toBe(30);
    const fixed = setKind(doc, "k1", "fixed").constraints[0];
    expect(fixed.drive).toBeUndefined();
    expect(fixed.limit).toBeUndefined();
  });
});

describe("request bodies", () => {
  it("adds when there is no assembly yet, edits the cell when there is", () => {
    const doc = two();
    expect(applyCommand(doc, null, " rig ")).toEqual({ op: "add", spec: "assembly", name: "rig", values: { assembly: doc } });
    expect(applyCommand(doc, null)).toEqual({ op: "add", spec: "assembly", values: { assembly: doc } });
    expect(applyCommand(doc, { cell: "c4" })).toEqual({ op: "edit", cell: "c4", values: { assembly: doc } });
  });
  it("normalizes what a cell stored", () => {
    const doc = normalizeAssembly({ components: [{ id: "a", part: "a.py", origin: [1, 2, 3], x_axis: "bad" }], ground: 3, constraints: [{ kind: "nope", a: { component: "a" }, limit: [1] }] });
    expect(doc.components[0]).toEqual({ id: "a", part: "a.py", origin: [1, 2, 3], x_axis: "+x", y_axis: "+y" });
    expect(doc.ground).toBeNull();
    expect(doc.constraints[0].kind).toBe("fixed");
    expect(doc.constraints[0].limit).toBeUndefined();
  });
  it("encodes the part path in the connectors URL", () => expect(connectorsUrl("parts/a b.py")).toBe("/api/assembly/parts?path=parts%2Fa%20b.py"));
});

describe("solver status from feature errors", () => {
  const row = (slug: string, errors: unknown[], status = "done") => ({ cell: slug, index: 1, slug, role: "add", gui: null, makes: [], reads: [], status, errors, params_cell: null });
  it("collects the errors of the layout and the uses cells", () => {
    const status = assemblyStatus({
      assembly: { cell: "c3", slug: "rig", doc: {} },
      features: [row("rig", ["Technical details: x\nWhat happened: the constraints conflict"]), row("rig_parts", [{ message: "no such part" }]), row("other", ["unrelated"])],
    });
    expect(status?.errors).toEqual(["the constraints conflict", "no such part"]);
  });
  it("is null without an assembly", () => expect(assemblyStatus({ assembly: null, features: [] })).toBeNull());
});

describe("connector frame from a face", () => {
  const top = { geometry: { type: "plane", origin: [0, 0, 10], normal: [0, 0, 1], x_direction: [1, 0, 0] }, properties: { centroid: [20, 15, 10] } };
  it("has unit axes, z = outward normal, origin at the centroid", () => {
    const f = connectorFrameFromFace(top)!;
    expect(f.origin).toEqual([20, 15, 10]);
    expect(f.x_axis).toEqual([1, 0, 0]);
    expect(f.y_axis).toEqual([0, 1, 0]);
    expect(f.z_axis).toEqual([0, 0, 1]);
  });
  it("takes a stable horizontal x for a wall without x_direction and keeps y = z cross x", () => {
    const f = connectorFrameFromFace({ geometry: { type: "plane", origin: [0, 0, 0], normal: [0, -1, 0] }, properties: { centroid: [5, 0, 5] } })!;
    expect(f.z_axis).toEqual([0, -1, 0]);
    expect(Math.hypot(...f.x_axis)).toBeCloseTo(1, 9);
    expect(Math.abs(f.x_axis[0] * f.z_axis[0] + f.x_axis[1] * f.z_axis[1] + f.x_axis[2] * f.z_axis[2])).toBeLessThan(1e-9);
    // y = z cross x
    const [zx, zy, zz] = f.z_axis;
    const [xx, xy, xz] = f.x_axis;
    expect(f.y_axis.map((v, i) => Math.abs(v - [zy * xz - zz * xy, zz * xx - zx * xz, zx * xy - zy * xx][i]) < 1e-9)).toEqual([true, true, true]);
  });
  it("passes the server's frame check", () => {
    const list = addConnectorFromFace([], { geometry: { type: "plane", origin: [0, 0, 0], normal: [1, 1, 0], x_direction: [0, 0, 1] }, properties: { centroid: [1, 2, 3] } }, "slant");
    expect("list" in list && connectorProblems(list.list)).toEqual([]);
  });
  it("prefers the kernel's connector_frame (outward normal even on a reversed face)", () => {
    const wall = { geometry: { type: "plane", origin: [0, -15, 10], normal: [0, 1, 0] }, properties: { centroid: [0, -15, 10], connector_frame: { origin: [0, -15, 10], x_axis: [1, 0, 0], y_axis: [0, 0, 1], z_axis: [0, -1, 0] } } };
    const f = connectorFrameFromFace(wall)!;
    expect(f.z_axis).toEqual([0, -1, 0]);
    expect(f.y_axis).toEqual([0, 0, 1]);
  });
  it("refuses a curved face", () => expect(connectorFrameFromFace({ geometry: { type: "cylinder" }, properties: {} })).toBeNull());
  it("names sides", () => {
    expect(sideName([0, 0, 1])).toBe("top");
    expect(sideName([0, 0, -1])).toBe("bottom");
    expect(sideName([1, 0, 0])).toBe("right");
    expect(sideName([0, -1, 0])).toBe("front");
    expect(sideName([1, 1, 1])).toBe("face");
  });
});

describe("the connector list", () => {
  it("adds with a suggested unique id, or a typed one, and refuses duplicates and bad names", () => {
    const face = { geometry: { type: "plane", origin: [0, 0, 10], normal: [0, 0, 1] }, properties: { centroid: [0, 0, 10] } };
    const a = addConnectorFromFace([], face) as { list: ReturnType<typeof removeConnector>; id: string };
    expect(a.id).toBe("top");
    const b = addConnectorFromFace(a.list, face) as { id: string; list: unknown[] };
    expect(b.id).toBe("top_2");
    expect(addConnectorFromFace(a.list, face, "top")).toEqual({ error: expect.stringMatching(/already/) });
    expect(addConnectorFromFace(a.list, face, "a b")).toEqual({ error: expect.stringMatching(/not a connector name/) });
    expect(addConnectorFromFace([], { geometry: { type: "cylinder" }, properties: {} })).toEqual({ error: expect.stringMatching(/not planar/) });
  });
  it("removes and renames", () => {
    const face = { geometry: { type: "plane", origin: [0, 0, 0], normal: [0, 0, 1] }, properties: { centroid: [0, 0, 0] } };
    const list = (addConnectorFromFace([], face, "a") as { list: ReturnType<typeof removeConnector> }).list;
    expect(removeConnector(list, "a")).toEqual([]);
    expect((renameConnector(list, "a", "b") as { list: { id: string }[] }).list[0].id).toBe("b");
    expect(renameConnector(list, "a", "b c")).toHaveProperty("error");
  });
  it("sends the whole list without z axes", () => {
    const face = { geometry: { type: "plane", origin: [0, 0, 0], normal: [0, 0, 1] }, properties: { centroid: [1, 2, 0] } };
    const list = (addConnectorFromFace([], face, "a") as { list: ReturnType<typeof removeConnector> }).list;
    const command = setConnectorsCommand(list);
    expect(command).toEqual({ op: "set_connectors", connectors: [{ id: "a", origin: [1, 2, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0] }] });
  });
});

describe("placementToWorld", () => {
  it("applies origin and axes (z = x cross y)", () => {
    expect(placementToWorld({ origin: [10, 0, 0], x_axis: "+y", y_axis: "+z" }, [1, 2, 3])).toEqual([13, 1, 2]);
    expect(placementToWorld({ origin: [0, 0, 5], x_axis: "+x", y_axis: "+y" }, [1, 2, 3])).toEqual([1, 2, 8]);
  });
});
