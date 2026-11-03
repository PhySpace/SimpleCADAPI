import { describe, expect, it } from "vitest";

describe("the header's count of a preview", () => {
  it("counts parts, and the bodies of a multi-body part", async () => {
    const { previewSummary } = await import("@/lib/preview");
    expect(previewSummary([{ nodeId: "node/plate" }])).toBe("1 part");
    expect(previewSummary([{ nodeId: "node/body/body:base" }, { nodeId: "node/body/body:post" }])).toBe("1 part · 2 bodies");
    expect(previewSummary([{ nodeId: "node/a" }, { nodeId: "node/b" }])).toBe("2 parts");
  });
});
