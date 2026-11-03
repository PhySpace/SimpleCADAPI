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
    expect(holeFromFace({ properties: { centroid: [1, 2, 3] }, geometry: { plane: { normal: [0, 1, 0] } } })).toEqual({ point: [1, 2, 3], direction: "-y" });
    expect(holeFromFace({ properties: { centroid: [1, 2, 3] }, geometry: {} })).toEqual({ point: [1, 2, 3], direction: null });
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
