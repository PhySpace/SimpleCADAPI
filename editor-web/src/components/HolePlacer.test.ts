import { describe, expect, it } from "vitest";

import { drillDirection } from "./HolePlacer";

describe("the hole's drilling direction", () => {
  it("follows the surface into the material, an axis, or the vector", () => {
    expect(drillDirection({ direction: "face", vector: null }, [0, 0, 1])).toEqual([-0, -0, -1]);
    expect(drillDirection({ direction: "+x", vector: null }, [0, 0, 1])).toEqual([1, 0, 0]);
    expect(drillDirection({ direction: "vector", vector: [0, 3, 4] }, null)).toEqual([0, 0.6, 0.8]);
    // a placed hole of "face" off the model keeps the direction its form holds
    expect(drillDirection({ direction: "face", vector: [0, -2, 0] }, null)).toEqual([0, -1, 0]);
    expect(drillDirection({ direction: "vector", vector: [0, 0, 0] }, null)).toBeNull();
  });
});
