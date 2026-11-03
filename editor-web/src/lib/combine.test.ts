import { describe, expect, it } from "vitest";

import { OPERATION_HINTS, STARTS_PART, formDefaults, hasBodyToCombine, operationOptions, storedOperation, targetDisplay, visibleSlots } from "./combine";
import type { FeatureRow, Slot, SlotOption, Spec } from "./features";

const OPTIONS: SlotOption[] = [
  { value: "join", label: "Join" },
  { value: "cut", label: "Cut" },
  { value: "intersect", label: "Intersect" },
  { value: "new", label: "New body" },
];
const values = (list: { value: string }[]) => list.map((o) => o.value);

const feature = (operation: string | undefined, makes: string[]): Pick<FeatureRow, "makes" | "gui"> => ({
  makes,
  gui: { spec: "box", values: operation === undefined ? {} : { operation }, picked: {} },
});

describe("operationOptions", () => {
  it("offers only New body, explained, when there is no body", () => {
    const { options, note } = operationOptions(OPTIONS, { open: [] });
    expect(values(options)).toEqual(["new"]);
    expect(note).toBe(STARTS_PART);
  });
  it("offers Join, Cut and Intersect with one body, with a plain hint each, and no New body", () => {
    const { options, note } = operationOptions(OPTIONS, { open: ["base"] });
    expect(values(options)).toEqual(["join", "cut", "intersect"]);
    expect(options.map((o) => o.hint)).toEqual([OPERATION_HINTS.join, OPERATION_HINTS.cut, OPERATION_HINTS.intersect]);
    expect(OPERATION_HINTS.join).toBe("adds this solid to the body");
    expect(OPERATION_HINTS.cut).toBe("removes this solid from the body");
    expect(OPERATION_HINTS.intersect).toBe("keeps only what both share");
    expect(note).toBeNull();
  });
  it("offers the same with several open bodies (a legacy notebook)", () => {
    expect(values(operationOptions(OPTIONS, { open: ["a", "b"] }).options)).toEqual(["join", "cut", "intersect"]);
  });
  it("keeps New body for a feature being edited that already is one", () => {
    // the first box of a part whose product is open again: it is the body itself, nothing to combine with
    expect(values(operationOptions(OPTIONS, { open: ["box"] }, feature("new", ["box"])).options)).toEqual(["new"]);
    expect(operationOptions(OPTIONS, { open: ["box"] }, feature("new", ["box"])).note).toBe(STARTS_PART);
    // a legacy second body that was left alone: all four
    expect(values(operationOptions(OPTIONS, { open: ["a", "b"] }, feature("new", ["b"])).options)).toEqual(["join", "cut", "intersect", "new"]);
  });
  it("does not offer New body for an edited feature that joined a body", () => {
    expect(values(operationOptions(OPTIONS, { open: ["tool"] }, feature("join", ["tool"])).options)).toEqual(["join", "cut", "intersect"]);
  });
});

describe("hasBodyToCombine / storedOperation", () => {
  it("reads the body from the open list, or the recipe when editing", () => {
    expect(hasBodyToCombine({ open: [] })).toBe(false);
    expect(hasBodyToCombine({ open: ["a"] })).toBe(true);
    expect(hasBodyToCombine({ open: ["x"] }, feature("cut", ["x"]))).toBe(true);
    expect(hasBodyToCombine({ open: ["x"] }, feature("new", ["x"]))).toBe(false);
  });
  it("treats a recipe without an operation as a new body", () => {
    expect(storedOperation(feature(undefined, []))).toBe("new");
    expect(storedOperation(undefined)).toBeNull();
  });
});

describe("targetDisplay (the Combined with rule)", () => {
  it("is hidden without a body", () => expect(targetDisplay({ open: [] }, undefined, "")).toEqual({ kind: "hidden" }));
  it("is one line naming the body when exactly one is open", () => {
    expect(targetDisplay({ open: ["base"] }, undefined, "base")).toEqual({ kind: "fixed", name: "base", text: "Combined with: base" });
  });
  it("is a choice when several are open", () => expect(targetDisplay({ open: ["a", "b"] }, undefined, "b")).toEqual({ kind: "choose" }));
  it("names what the recipe says when editing, ignoring the feature's own product", () => {
    expect(targetDisplay({ open: ["pin_2"] }, feature("join", ["pin_2"]), "base")).toEqual({ kind: "fixed", name: "base", text: "Combined with: base" });
    expect(targetDisplay({ open: ["pin_2"] }, feature("join", ["pin_2"]), "").text).toBe("Combined with: the body before it");
    expect(targetDisplay({ open: ["a", "b", "own"] }, feature("join", ["own"]), "a")).toEqual({ kind: "choose" });
  });
});

describe("formDefaults and visibleSlots", () => {
  const slot = (name: string, extra: Partial<Slot> = {}): Slot => ({ name, label: name, kind: "length", ...extra });
  const spec: Pick<Spec, "slots" | "combinable"> = {
    combinable: true,
    slots: [
      slot("width"),
      slot("operation", { kind: "enum", options: OPTIONS }),
      slot("target", { kind: "body", optional: true, show_when: { operation: ["join", "cut", "intersect"] } }),
      slot("height"),
    ],
  };
  it("lets an edited feature keep its recipe: no join/target defaults", () => {
    const defaults = { operation: "join", target: "base", other: "x" };
    expect(formDefaults(spec, defaults, false)).toEqual(defaults);
    expect(formDefaults(spec, defaults, true)).toEqual({ other: "x" });
    expect(formDefaults({ combinable: false }, defaults, true)).toEqual(defaults);
  });
  it("lists the operation and target first and drops a hidden target", () => {
    expect(visibleSlots(spec, { operation: "cut" }).map((s) => s.name)).toEqual(["operation", "target", "width", "height"]);
    expect(visibleSlots(spec, { operation: "new" }).map((s) => s.name)).toEqual(["operation", "width", "height"]);
    expect(visibleSlots({ ...spec, combinable: false }, { operation: "new" }).map((s) => s.name)).toEqual(["width", "operation", "height"]);
  });
});
