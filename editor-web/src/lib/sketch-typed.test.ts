import { describe, expect, it } from "vitest";

import { parseTyped, typedFields, typedTarget } from "@/lib/sketch-typed";

const at = (spot: { x: number; y: number; pointId?: string }): [number, number] => (spot.pointId === "p1" ? [10, 10] : [spot.x, spot.y]);

describe("typed entry while drawing", () => {
  it("asks for coordinates first, then what the tool needs next", () => {
    expect(typedFields("line", null)?.map((f) => f.name)).toEqual(["x", "y"]);
    expect(typedFields("line", { tool: "line", from: { x: 0, y: 0 } })?.map((f) => f.name)).toEqual(["length", "angle"]);
    expect(typedFields("circle", { tool: "circle", center: { x: 0, y: 0 } })?.map((f) => f.name)).toEqual(["radius"]);
    expect(typedFields("arc", { tool: "arc", center: { x: 0, y: 0 }, start: { x: 5, y: 0 } })?.map((f) => f.name)).toEqual(["sweep"]);
    expect(typedFields("trim", null)).toBeNull();
  });
  it("parses numbers and refuses text", () => {
    expect(parseTyped(" =12.5 ")).toBe(12.5);
    expect(parseTyped("abc")).toBeNull();
    expect(parseTyped("")).toBeNull();
  });
  it("places a point, a line by length and angle from an existing point, and keeps the length", () => {
    expect(typedTarget("point", null, { x: "3", y: "-4" }, at)).toEqual({ spot: { x: 3, y: -4 }, dims: {} });
    const line = typedTarget("line", { tool: "line", from: { x: 0, y: 0, pointId: "p1" } }, { length: "20", angle: "90" }, at);
    expect("spot" in line && line.spot.x).toBeCloseTo(10);
    expect("spot" in line && line.spot.y).toBeCloseTo(30);
    expect("spot" in line && line.dims).toEqual({ length: 20 });
    expect(typedTarget("line", { tool: "line", from: { x: 0, y: 0 } }, { length: "0" }, at)).toEqual({ error: "Length: must be greater than zero" });
  });
  it("makes a circle by radius and an arc by radius, start angle and sweep", () => {
    expect(typedTarget("circle", { tool: "circle", center: { x: 2, y: 2 } }, { radius: "5" }, at)).toEqual({ spot: { x: 7, y: 2 }, dims: { radius: 5 } });
    const start = typedTarget("arc", { tool: "arc", center: { x: 0, y: 0 } }, { radius: "10", angle: "0" }, at);
    expect(start).toEqual({ spot: { x: 10, y: 0 }, dims: { radius: 10 } });
    const end = typedTarget("arc", { tool: "arc", center: { x: 0, y: 0 }, start: { x: 10, y: 0 } }, { sweep: "90" }, at);
    expect("spot" in end && end.spot.x).toBeCloseTo(0);
    expect("spot" in end && end.spot.y).toBeCloseTo(10);
  });
});
