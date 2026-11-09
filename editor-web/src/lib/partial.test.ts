import { describe, expect, it } from "vitest";

import { describePartial, parsePartial, samePartial } from "./partial";

const ROUNDED = {
  failed: [{ cell: "bkHC", name: "rounded", status: "exception", error: "SimpleCADError: fillet_rsolid: the radius is too large" }],
  skipped: ["lEQa"],
  shown: ["bore"],
};

describe("parsePartial", () => {
  it("reads what the kernel sends and drops what is not a failure", () => {
    expect(parsePartial(ROUNDED)).toEqual(ROUNDED);
    expect(parsePartial(null)).toBeNull();
    expect(parsePartial(undefined)).toBeNull();
    expect(parsePartial({ failed: [], skipped: [], shown: [] })).toBeNull();
    expect(parsePartial({ failed: [{ name: "no cell id" }] })).toBeNull();
    expect(parsePartial({ failed: [{ cell: "x" }] })).toEqual({ failed: [{ cell: "x", name: "x", status: "exception", error: "" }], skipped: [], shown: [] });
  });
});

describe("describePartial", () => {
  it("names the failing step, why, and what did not run", () => {
    const partial = parsePartial(ROUNDED)!;
    expect(describePartial(partial)).toEqual({
      title: "The model before rounded",
      reason: "rounded failed: SimpleCADError: fillet_rsolid: the radius is too large",
      after: "1 later step did not run",
    });
  });

  it("uses the notebook's title for a step without a feature header, and says when it was stopped", () => {
    const partial = parsePartial({ failed: [{ cell: "c1", name: "c1", status: "interrupted", error: "" }], skipped: ["c2", "c3"], shown: [] })!;
    const told = describePartial(partial, new Map([["c1", "slow loft"]]));
    expect(told.title).toBe("The model before slow loft");
    expect(told.reason).toBe("slow loft was stopped");
    expect(told.after).toBe("2 later steps did not run");
  });

  it("keeps a long error to one short line", () => {
    const partial = parsePartial({ failed: [{ cell: "c", name: "c", status: "exception", error: `E: ${"x ".repeat(200)}\nmore` }] })!;
    expect(describePartial(partial).reason.length).toBeLessThan(200);
  });
});

describe("samePartial", () => {
  it("is the same failure when the same cells fail the same way, whatever is shown", () => {
    const a = parsePartial(ROUNDED);
    expect(samePartial(a, parsePartial({ ...ROUNDED, shown: ["other"] }))).toBe(true);
    expect(samePartial(a, parsePartial({ ...ROUNDED, failed: [{ ...ROUNDED.failed[0], error: "another" }] }))).toBe(false);
    expect(samePartial(a, null)).toBe(false);
    expect(samePartial(null, null)).toBe(true);
  });
});
