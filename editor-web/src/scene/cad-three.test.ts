import { describe, expect, it } from "vitest";

import { DEFAULT_BASE_COLOR, materialFor, nodeColor } from "./cad-three";
import type { SceneNode } from "./scene2";

const node = (properties: Record<string, unknown>, material_id: string | null = null) => ({ material_id, properties }) as SceneNode;

describe("the colour a node is drawn in", () => {
  it("is the node's own colour (a body colour) before the material tint and the default grey", () => {
    expect(nodeColor(node({ color: [0.9, 0.2, 0.1] }, "steel"))).toEqual([0.9, 0.2, 0.1, 1]);
    expect(nodeColor(node({}, "steel"))).toEqual([0.68, 0.78, 0.88, 1]);
    expect(nodeColor(node({}))).toEqual([DEFAULT_BASE_COLOR[0], DEFAULT_BASE_COLOR[1], DEFAULT_BASE_COLOR[2], 1]);
  });

  it("is see-through with an opacity below one, clamped to [0, 1]", () => {
    expect(nodeColor(node({ opacity: 0.4 }))[3]).toBe(0.4);
    expect(nodeColor(node({ opacity: 3 }))[3]).toBe(1);
    const material = materialFor(node({ color: [0.1, 0.3, 0.8], opacity: 0.5 }));
    expect(material.transparent).toBe(true);
    expect(material.opacity).toBe(0.5);
    expect(material.depthWrite).toBe(false);
    expect([material.color.r, material.color.g, material.color.b]).toEqual([0.1, 0.3, 0.8]);
    expect(materialFor(node({})).transparent).toBe(false);
  });

  it("ignores a malformed colour", () => {
    expect(nodeColor(node({ color: [1, "x", 0] }))).toEqual([DEFAULT_BASE_COLOR[0], DEFAULT_BASE_COLOR[1], DEFAULT_BASE_COLOR[2], 1]);
  });
});
