import { describe, expect, it } from "vitest";

import { closedLoop, gordonFamilies, loopNormal, type NetCurve } from "@/lib/curve-net";
import type { Vec3 } from "@/lib/sketch-plane";

const line = (name: string, a: Vec3, b: Vec3): NetCurve => ({ name, edges: [[a, b]] });

// the four sides of a 10 x 10 square in the XY plane, out of order and one of them reversed
const square = [line("a", [0, 0, 0], [10, 0, 0]), line("c", [10, 10, 0], [0, 10, 0]), line("b", [10, 10, 0], [10, 0, 0]), line("d", [0, 10, 0], [0, 0, 0])];

describe("a closed loop of curves", () => {
  it("is found in any order and direction, and is flat with its normal", () => {
    const loop = closedLoop(square);
    expect(loop?.map((c) => c.name)).toEqual(["a", "b", "c", "d"]);
    const normal = loopNormal(loop!);
    expect(normal && Math.abs(normal[2])).toBeCloseTo(1);
  });

  it("is not a loop when a side is missing, and not flat when a corner is lifted", () => {
    expect(closedLoop(square.slice(0, 3))).toBeNull();
    const lifted = [line("a", [0, 0, 0], [10, 0, 0]), line("b", [10, 0, 0], [10, 10, 5]), line("c", [10, 10, 5], [0, 10, 0]), line("d", [0, 10, 0], [0, 0, 0])];
    expect(closedLoop(lifted)).not.toBeNull();
    expect(loopNormal(closedLoop(lifted)!)).toBeNull();
  });
});

describe("a Gordon network", () => {
  it("splits crossing curves into two families", () => {
    const net = [
      line("p1", [0, 0, 0], [10, 0, 0]),
      line("g1", [0, -1, 0], [0, 11, 0]),
      line("p2", [0, 10, 0], [10, 10, 0]),
      line("g2", [10, -1, 0], [10, 11, 0]),
    ];
    expect(gordonFamilies(net)).toEqual({ profiles: ["p1", "p2"], guides: ["g1", "g2"] });
  });

  it("is no network when two curves of a family cross or one crosses nothing", () => {
    expect(gordonFamilies(square.slice(0, 3))).toBeNull();
    const stray = [...square.slice(0, 3), line("far", [50, 50, 0], [60, 50, 0])];
    expect(gordonFamilies(stray)).toBeNull();
  });
});
