import { describe, expect, it } from "vitest";

import {
  CellFailure,
  assertCellRan,
  cellFailure,
  errorLine,
  bodyChoices,
  directionOptions,
  resolveDirection,
  filterSelection,
  formToValues,
  holeFromFace,
  initialForm,
  inwardAxis,
  isSlotVisible,
  parsePointList,
  profilePlaneLabel,
  pointListText,
  validateName,
  type Spec,
} from "./features";

const spec: Spec = {
  id: "demo",
  label: "Demo",
  group: "Primitives",
  role: "build",
  produces: "solid",
  description: "",
  slots: [
    { name: "width", label: "Width", kind: "length", default: 10, unit: "mm", min: 0.1 },
    { name: "count", label: "Count", kind: "count", default: 3, min: 2, max: 10 },
    { name: "origin", label: "Origin", kind: "point", default: [0, 1, 2], unit: "mm" },
    { name: "flag", label: "Flag", kind: "bool", default: true },
    { name: "dir", label: "Dir", kind: "enum", default: "+x", options: [{ value: "+x", label: "+x" }, { value: "-z", label: "-z" }] },
    { name: "base", label: "Base", kind: "body" },
    { name: "outline", label: "Outline", kind: "points2d" },
  ],
};

describe("parsePointList", () => {
  it("reads one point per line, tolerating separators and blank lines", () => {
    expect(parsePointList("0, 0\n10 0;\n\n10,5\n", 2)).toEqual({ ok: true, points: [[0, 0], [10, 0], [10, 5]] });
  });
  it("names the line and the problem", () => {
    expect(parsePointList("0, 0\n1, 2, 3", 2)).toEqual({ ok: false, error: "line 2: expected 2 numbers (x, y), found 3" });
    expect(parsePointList("1, a", 2)).toEqual({ ok: false, error: 'line 1: "a" is not a number' });
    expect(parsePointList("1, 2", 3)).toMatchObject({ ok: false });
  });
  it("round-trips through pointListText", () => {
    const points = [[0, 0.5], [3, -4]];
    expect(parsePointList(pointListText(points), 2)).toEqual({ ok: true, points });
  });
});

describe("initialForm", () => {
  it("takes defaults, and the default body of the state", () => {
    const form = initialForm(spec, { base: "box" });
    expect(form).toMatchObject({ width: "10", count: "3", origin: ["0", "1", "2"], flag: true, dir: "+x", base: "box", outline: "" });
  });
  it("prefers the recipe's values in edit mode", () => {
    const form = initialForm(spec, { base: "box" }, { width: 4, base: "other", origin: [1, 2, 3] });
    expect(form).toMatchObject({ width: "4", base: "other", origin: ["1", "2", "3"] });
  });
});

describe("formToValues", () => {
  const valid = { ...initialForm(spec, { base: "box" }), outline: "0,0\n1,0\n1,1" };
  it("converts a valid form", () => {
    const { values, errors } = formToValues(spec, valid);
    expect(errors).toEqual({});
    expect(values).toMatchObject({ width: 10, count: 3, origin: [0, 1, 2], flag: true, dir: "+x", base: "box" });
    expect(values.outline).toEqual([[0, 0], [1, 0], [1, 1]]);
  });
  it("checks ranges, integers and numbers", () => {
    const { errors } = formToValues(spec, { ...valid, width: "0", count: "2.5", origin: ["a", "0", "0"] });
    expect(errors.width).toBe("at least 0.1 mm");
    expect(errors.count).toBe("must be a whole number");
    expect(errors.origin).toBe("x, y and z must all be numbers");
    expect(formToValues(spec, { ...valid, count: "11" }).errors.count).toBe("at most 10");
    expect(formToValues(spec, { ...valid, width: "" }).errors.width).toBe("enter a number");
  });
  it("needs a body and enough points", () => {
    expect(formToValues(spec, { ...valid, base: "" }).errors.base).toMatch(/add a solid/);
    expect(formToValues(spec, { ...valid, outline: "0,0\n1,1" }).errors.outline).toBe("at least 3 points, one per line");
  });
});

describe("validateName", () => {
  it("accepts empty (the suggestion) and good names", () => {
    expect(validateName("", ["a"])).toBeNull();
    expect(validateName("base_plate", ["a"])).toBeNull();
  });
  it("rejects bad characters and taken names", () => {
    expect(validateName("Base", [])).not.toBeNull();
    expect(validateName("1abc", [])).not.toBeNull();
    expect(validateName("box", ["box"])).toMatch(/already used/);
    expect(validateName("box", ["BOX"])).toMatch(/already used/);
  });
});

describe("bodies and selection", () => {
  it("lists open bodies first", () => {
    const state = { bodies: [{ name: "a", produces: "solid" }, { name: "b", produces: "solid" }, { name: "c", produces: "solid" }], open: ["c", "a"] };
    expect(bodyChoices(state)).toEqual([{ name: "a", open: true }, { name: "c", open: true }, { name: "b", open: false }]);
  });
  it("filters picked items by entity kind", () => {
    const items = [{ kind: "edge" }, { kind: "face" }, { kind: "edge" }];
    expect(filterSelection(items, "edge")).toHaveLength(2);
    expect(filterSelection(items, "face")).toHaveLength(1);
  });
});

describe("hole from a face", () => {
  it("points into the material, against the outward normal", () => {
    expect(inwardAxis([0, 0, 1])).toBe("-z");
    expect(inwardAxis([-1, 0.1, 0])).toBe("+x");
    expect(inwardAxis([0, 0, 0])).toBeNull();
  });
  it("reads the centroid and the normal", () => {
    expect(holeFromFace({ properties: { centroid: [1, 2, 3] }, geometry: { plane: { normal: [0, 1, 0] } } })).toEqual({ point: [1, 2, 3], direction: "-y", vector: [-0, -1, -0] });
    expect(holeFromFace({ properties: { centroid: [1, 2, 3] }, geometry: {} })).toEqual({ point: [1, 2, 3], direction: null, vector: null });
  });
});

describe("profile and sketch slots", () => {
  const spec = {
    id: "extrude_sketch",
    label: "Extrude sketch",
    group: "Sketch",
    role: "build",
    produces: "solid",
    description: "",
    slots: [
      { name: "profile", label: "Sketch profile", kind: "profile" as const },
      { name: "direction", label: "Direction", kind: "enum" as const, options: [{ value: "+z", label: "+z" }, { value: "-y", label: "-y" }] },
    ],
  };
  const state = { profiles: [{ name: "sk", plane: "XZ", normal: "-y" }] };
  it("a profile slot takes the default sketch and needs a value", () => {
    expect(initialForm(spec, { profile: "sk" }).profile).toBe("sk");
    expect(formToValues(spec, initialForm(spec, {})).errors.profile).toMatch(/sketch/);
    expect(formToValues(spec, initialForm(spec, { profile: "sk" })).values.profile).toBe("sk");
  });
  it("the direction follows the profile's normal", async () => {
    const { directionForProfile, findProfile } = await import("@/lib/features");
    expect(directionForProfile(state, "sk")).toBe("-y");
    expect(directionForProfile(state, "other")).toBeNull();
    expect(findProfile({}, "sk")).toBeUndefined();
  });
});

describe("the opposite of a sketch plane's normal", () => {
  const options = [{ value: "+x", label: "+x" }, { value: "+z", label: "+z" }, { value: "-z", label: "-z" }, { value: "normal", label: "normal of the sketch plane" }];
  const top = { profiles: [{ name: "top", plane: "frame", normal: "normal", normal_vec: [0, 0, 1] as [number, number, number] }] };
  const slanted = { profiles: [{ name: "slant", plane: "frame", normal: "normal", normal_vec: [0.6, 0, 0.8] as [number, number, number] }] };
  const xy = { profiles: [{ name: "base", plane: "XY", normal: "+z" }] };

  it("is offered right after 'normal' and resolves to the opposite axis", () => {
    const list = directionOptions(options, top, "top");
    expect(list.map((o) => o.value)).toEqual(["+x", "+z", "-z", "normal", "-normal"]);
    expect(resolveDirection("-normal", top, "top")).toBe("-z");
    expect(resolveDirection("-normal", xy, "base")).toBe("-z");
    expect(resolveDirection("+x", top, "top")).toBe("+x");
  });
  it("is not offered for a slanted normal or without a sketch", () => {
    expect(directionOptions(options, slanted, "slant")).toEqual(options);
    expect(directionOptions(options, top, null)).toEqual(options);
    expect(resolveDirection("-normal", slanted, "slant")).toBe("normal");
  });
});

describe("a server that lists '-normal' itself", () => {
  const withFlip = [{ value: "+x", label: "+x" }, { value: "normal", label: "normal" }, { value: "-normal", label: "against the normal" }];
  const slanted = { profiles: [{ name: "slant", plane: "frame", normal: "normal", normal_vec: [0.6, 0, 0.8] as [number, number, number] }] };
  it("is used as it is: no second '-normal', and the value goes to the server unchanged (slanted normals too)", () => {
    expect(directionOptions(withFlip, slanted, "slant").map((o) => o.value)).toEqual(["+x", "normal", "-normal"]);
    expect(resolveDirection("-normal", slanted, "slant", true)).toBe("-normal");
  });
});

describe("profile plane labels", () => {
  it("names a datum plane and calls a frame a face", () => {
    expect(profilePlaneLabel({ plane: "XZ" })).toBe("XZ");
    expect(profilePlaneLabel({ plane: { origin: [0, 0, 40], x_axis: [1, 0, 0], y_axis: [0, 1, 0] } })).toBe("face");
  });
});

describe("a command whose cell failed", () => {
  const error = "ValueError: boom\nWhat happened: the radius is larger than the line\nWhy: ...";
  it("reads the What-happened line of the first error", () => {
    expect(cellFailure({ cell: { id: "c3", status: "exception", errors: [error, "other"] } })).toBe("the radius is larger than the line");
  });
  it("reads an error object, and the first line when there is no What-happened line", () => {
    expect(errorLine({ message: "NameError: x\nmore" })).toBe("NameError: x");
    expect(errorLine("\n  \nplain")).toBe("plain");
  });
  it("is null when the cell ran, or there is no cell", () => {
    expect(cellFailure({ cell: { id: "c3", status: "done", errors: [] } })).toBeNull();
    expect(cellFailure({ cell: null })).toBeNull();
  });
  it("counts errors even when the status says done, and a bare exception status", () => {
    expect(cellFailure({ cell: { id: "c3", status: "done", errors: ["bad"] } })).toBe("bad");
    expect(cellFailure({ cell: { id: "c3", status: "exception" } })).toContain("exception");
  });
  it("throws a CellFailure carrying the cell, else returns the result", () => {
    const failed = { cell: { id: "c3", status: "exception", errors: [error] } };
    expect(() => assertCellRan(failed)).toThrowError(CellFailure);
    try {
      assertCellRan(failed);
    } catch (e) {
      expect((e as CellFailure).cell).toBe("c3");
      expect((e as CellFailure).message).toBe("the radius is larger than the line");
    }
    const ok = { cell: { id: "c3", status: "done", errors: [] } };
    expect(assertCellRan(ok)).toBe(ok);
  });
});

describe("isSlotVisible and hidden slots", () => {
  const combine: Spec = {
    id: "box",
    label: "Box",
    group: "Primitives",
    role: "build",
    produces: "solid",
    description: "",
    combinable: true,
    slots: [
      { name: "width", label: "Width", kind: "length", default: 10, min: 0.1 },
      {
        name: "operation",
        label: "Operation",
        kind: "enum",
        default: "new",
        options: [{ value: "join", label: "Join" }, { value: "cut", label: "Cut" }, { value: "intersect", label: "Intersect" }, { value: "new", label: "New body" }],
      },
      { name: "target", label: "Combine with", kind: "body", optional: true, show_when: { operation: ["join", "cut", "intersect"] } },
    ],
  };
  const target = combine.slots[2];

  it("shows a slot without a rule always, one with a rule only for the listed values", () => {
    expect(isSlotVisible(combine.slots[0], {})).toBe(true);
    expect(isSlotVisible(target, { operation: "cut" })).toBe(true);
    expect(isSlotVisible(target, { operation: "join" })).toBe(true);
    expect(isSlotVisible(target, { operation: "new" })).toBe(false);
    expect(isSlotVisible(target, {})).toBe(false);
    expect(isSlotVisible(target, { operation: ["cut"] })).toBe(false);
  });
  it("needs every rule to hold", () => {
    const slot = { show_when: { a: ["1"], b: ["x", "y"] } };
    expect(isSlotVisible(slot, { a: "1", b: "y" })).toBe(true);
    expect(isSlotVisible(slot, { a: "1", b: "z" })).toBe(false);
  });
  it("omits a hidden slot from the request values and does not validate it", () => {
    const required: Spec = { ...combine, slots: [combine.slots[0], combine.slots[1], { ...target, optional: false }] };
    const hidden = formToValues(required, { width: "5", operation: "new", target: "" });
    expect(hidden.errors).toEqual({});
    expect(hidden.values).toEqual({ width: 5, operation: "new" });
    const shown = formToValues(required, { width: "5", operation: "join", target: "" });
    expect(shown.errors.target).toBeDefined();
    expect(formToValues(combine, { width: "5", operation: "cut", target: "base" }).values).toEqual({ width: 5, operation: "cut", target: "base" });
    // an invalid hidden value is no error either
    expect(formToValues(combine, { width: "5", operation: "new", target: "stale" }).values).toEqual({ width: 5, operation: "new" });
  });
  it("opens the operation from the server defaults (join with a body, new without), the recipe winning when editing", () => {
    expect(initialForm(combine, { operation: "join", target: "base" }).operation).toBe("join");
    expect(initialForm(combine, { operation: "join", target: "base" }).target).toBe("base");
    expect(initialForm(combine, { operation: "new" }).operation).toBe("new");
    expect(initialForm(combine, {}).operation).toBe("new"); // the slot's own default
    expect(initialForm(combine, { operation: "join" }, { operation: "cut" }).operation).toBe("cut");
  });
});

describe("a grid of points (a control net)", () => {
  it("reads one row per line, points separated by semicolons, and writes it back the same", async () => {
    const { gridText, parseGrid } = await import("@/lib/features");
    const grid = [[[0, 0, 0], [10, 0, 0]], [[0, 10, 1], [10, 10, 2]]];
    const text = gridText(grid);
    expect(text).toBe("0, 0, 0; 10, 0, 0\n0, 10, 1; 10, 10, 2");
    expect(parseGrid(text)).toEqual({ grid });
    expect(parseGrid("0,0,0; 1,0,0\n0,1,0")).toEqual({ error: "row 2: at least two points, separated by \";\"" });
    expect(parseGrid("0,0,0; 1,0,0\n0,1,0; 1,1,0; 2,1,0")).toEqual({ error: "row 2 has 3 points, row 1 has 2" });
  });
});

describe("a colour slot", () => {
  it("shows an SDK colour (linear RGB) as #rrggbb and reads it back", async () => {
    const { colorHex, hexColor } = await import("@/lib/features");
    expect(colorHex([1, 0, 0])).toBe("#ff0000");
    expect(colorHex(null)).toBe("");
    expect(colorHex([0.5, 0.5])).toBe("");
    expect(hexColor("#ff0000")).toEqual([1, 0, 0]);
    expect(hexColor("#808080")?.[0]).toBeCloseTo(0.2159, 4); // sRGB 128 is linear 0.2159
    expect(hexColor("red")).toBeNull();
    const back = hexColor(colorHex([0.9, 0.2, 0.1]))!;
    back.forEach((c, i) => expect(c).toBeCloseTo([0.9, 0.2, 0.1][i], 2));
  });

  it("sends a picked colour, leaves out an empty optional one and refuses bad text", async () => {
    const { formToValues, initialForm } = await import("@/lib/features");
    const spec = {
      id: "op.set_body_appearance_rpart", label: "Set body appearance", group: "Product", role: "build", produces: "part", description: "",
      slots: [{ name: "color", label: "Color", kind: "color" as const, optional: true }],
    } as unknown as Parameters<typeof formToValues>[0];
    expect(initialForm(spec)).toEqual({ color: "" });
    expect(formToValues(spec, { color: "" })).toEqual({ values: {}, errors: {} });
    expect(formToValues(spec, { color: "#ff0000" }).values).toEqual({ color: [1, 0, 0] });
    expect(formToValues(spec, { color: "nope" }).errors.color).toBe("a colour as #rrggbb");
  });
});
