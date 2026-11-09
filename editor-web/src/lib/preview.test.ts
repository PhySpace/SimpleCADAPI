import { describe, expect, it } from "vitest";

describe("the header's count of a preview", () => {
  it("counts parts, and the open solids of a notebook that has no Part yet (a Part holds one solid)", async () => {
    const { previewSummary } = await import("@/lib/preview");
    expect(previewSummary([{ nodeId: "node/plate" }])).toBe("1 part");
    expect(previewSummary([{ nodeId: "node/body/body:base" }, { nodeId: "node/body/body:tool" }])).toBe("2 open solids");
    expect(previewSummary([{ nodeId: "node/body/body:base" }])).toBe("1 open solid");
    expect(previewSummary([{ nodeId: "node/a" }, { nodeId: "node/b" }])).toBe("2 parts");
  });
});

/** A frame with no parts (the parts come from the cache) and the given nodes. */
function frame(nodes: object[]): ArrayBuffer {
  const header = new TextEncoder().encode(JSON.stringify({ schema: "sca-preview-1", parts: [], nodes }));
  const padded = Math.ceil(header.length / 8) * 8;
  const buffer = new ArrayBuffer(8 + 8 + padded);
  const bytes = new Uint8Array(buffer);
  bytes.set(new TextEncoder().encode("SCAPREV1"), 0);
  new DataView(buffer).setUint32(8, padded, true);
  bytes.fill(32, 16, 16 + padded);
  bytes.set(header, 16);
  return buffer;
}

describe("a preview's display colours", () => {
  const transform = { origin: [0, 0, 0], x_axis: [1, 0, 0], y_axis: [0, 1, 0], z_axis: [0, 0, 1] };
  it("reads a node's colour and opacity, and leaves them out when the kernel sends none", async () => {
    const { parsePreview } = await import("@/lib/preview");
    const data = parsePreview(
      frame([
        { node_id: "node/case/body:lid", part: "k1", definition_id: "case", display_name: "case / Lid", transform, color: [0.9, 0.2, 0.1], opacity: 0.5 },
        { node_id: "node/case/body:base", part: "k1", definition_id: "case", display_name: "case / base", transform },
      ]),
    );
    expect(data.nodes[0].color).toEqual([0.9, 0.2, 0.1]);
    expect(data.nodes[0].opacity).toBe(0.5);
    expect("color" in data.nodes[1]).toBe(false);
    expect("opacity" in data.nodes[1]).toBe(false);
  });
});
