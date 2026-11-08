import { describe, expect, it } from "vitest";

import { NAMED_FRAMES, faceFrame, placeValues, placedFrame, type PlaceFrame } from "./workplane-place";

const close = (a: readonly number[], b: readonly number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 9));

describe("placing a workplane", () => {
  it("moves along the base's own axes and turns about them, as the SDK does", () => {
    // the SDK's test: XY moved 20 up and turned 90 about x, then 5 along its normal and 90 about its normal
    const tilted = placedFrame(NAMED_FRAMES.XY, { move: [0, 0, 20], rx: 90, ry: 0, rz: 0 });
    close(tilted.origin, [0, 0, 20]);
    close(tilted.normal, [0, -1, 0]);
    const lid = placedFrame(tilted, { move: [0, 0, 5], rx: 0, ry: 0, rz: 90 });
    close(lid.origin, [0, -5, 20]);
    close(lid.x_axis, [0, 0, 1]);
    close(NAMED_FRAMES.XZ.normal, [0, -1, 0]);
  });

  it("reads back the values that place a frame", () => {
    const base: PlaceFrame = placedFrame(NAMED_FRAMES.YZ, { move: [3, -2, 7], rx: 10, ry: -25, rz: 40 });
    for (const values of [
      { move: [1, 2, 3], rx: 30, ry: 20, rz: -50 },
      { move: [0, 0, -12.5], rx: -170, ry: 45, rz: 5 },
      { move: [0, 0, 0], rx: 0, ry: 0, rz: 0 },
    ] as const) {
      const back = placeValues(base, placedFrame(base, { ...values, move: [...values.move] }));
      close(back.move, values.move);
      close([back.rx, back.ry, back.rz], [values.rx, values.ry, values.rz]);
    }
  });

  it("takes a face's connector frame, its outward normal and x axis", () => {
    const frame = faceFrame({ connector_frame: { origin: [1, 2, 3], x_axis: [1, 0, 0], y_axis: [0, -1, 0], z_axis: [0, 0, -1] } });
    expect(frame).not.toBeNull();
    close(frame!.normal, [0, 0, -1]);
    close(frame!.y_axis, [0, -1, 0]);
    expect(faceFrame({})).toBeNull();
  });
});
