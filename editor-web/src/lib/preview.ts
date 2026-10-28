/** The preview a kernel makes of its model (`simplecadapi.scene.preview`):
 * the arrays a viewer draws, the index range of every face and edge, each part
 * once and where each of its instances stands.
 *
 * Layout: `SCAPREV1`, a u32 header length, 4 bytes of padding, the JSON header
 * (padded to 8 bytes), then the little-endian arrays the header points into.
 * A frame carries only the parts the page does not have; every node names its part.
 */

export type PreviewGroup = { entity_id: string; first_index: number; index_count: number };
export type PreviewTransform = {
  origin: [number, number, number];
  x_axis: [number, number, number];
  y_axis: [number, number, number];
  z_axis: [number, number, number];
};

export type PreviewPart = {
  key: string;
  definitionId: string;
  /** glTF metres (+Y up), as in the package's GLB assets. */
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint32Array;
  edgePositions: Float32Array;
  edgeIndices: Uint32Array;
  vertexPositions: Float32Array;
  vertexIds: string[];
  faceGroups: PreviewGroup[];
  edgeGroups: PreviewGroup[];
  solidEntityId: string;
};

export type PreviewNode = {
  nodeId: string;
  partKey: string;
  definitionId: string;
  displayName: string;
  transform: PreviewTransform;
};

/** `parts` holds exactly the parts the nodes draw; `missing` names the ones the frame left out that the cache lacks. */
export type PreviewData = { parts: Map<string, PreviewPart>; nodes: PreviewNode[]; missing: string[] };

type ArrayRef = { offset: number; count: number };
type HeaderPart = {
  key: string;
  definition_id: string;
  positions: ArrayRef;
  normals: ArrayRef;
  indices: ArrayRef;
  edge_positions: ArrayRef;
  edge_indices: ArrayRef;
  vertex_positions: ArrayRef;
  vertex_ids: string[];
  face_groups: PreviewGroup[];
  edge_groups: PreviewGroup[];
  solid_entity_id: string;
};
type Header = {
  schema: string;
  parts: HeaderPart[];
  nodes: { node_id: string; part: string; definition_id: string; display_name: string; transform: PreviewTransform }[];
};

const MAGIC = "SCAPREV1";

/** Parse a preview.  A frame may leave out the parts the page already holds: they are taken from *cache* (the parts of
 * the preview on screen, by key), and the result holds exactly the parts the nodes draw. */
export function parsePreview(buffer: ArrayBuffer, cache: ReadonlyMap<string, PreviewPart> = new Map()): PreviewData {
  const bytes = new Uint8Array(buffer);
  if (new TextDecoder().decode(bytes.subarray(0, MAGIC.length)) !== MAGIC) throw new Error("not a preview");
  const view = new DataView(buffer);
  const headerLength = view.getUint32(MAGIC.length, true);
  const headerStart = MAGIC.length + 8;
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(headerStart, headerStart + headerLength))) as Header;
  if (header.schema !== "sca-preview-1") throw new Error(`unsupported preview schema: ${header.schema}`);
  const base = headerStart + headerLength;
  const floats = (ref: ArrayRef) => new Float32Array(buffer, base + ref.offset, ref.count).slice(); // a copy: a kept part must not pin the whole frame it came in
  const uints = (ref: ArrayRef) => new Uint32Array(buffer, base + ref.offset, ref.count).slice();
  const carried = new Map<string, PreviewPart>();
  for (const part of header.parts) {
    carried.set(part.key, {
      key: part.key,
      definitionId: part.definition_id,
      positions: floats(part.positions),
      normals: floats(part.normals),
      indices: uints(part.indices),
      edgePositions: floats(part.edge_positions),
      edgeIndices: uints(part.edge_indices),
      vertexPositions: floats(part.vertex_positions),
      vertexIds: part.vertex_ids,
      faceGroups: part.face_groups,
      edgeGroups: part.edge_groups,
      solidEntityId: part.solid_entity_id,
    });
  }
  const nodes: PreviewNode[] = header.nodes.map((node) => ({
    nodeId: node.node_id,
    partKey: node.part,
    definitionId: node.definition_id,
    displayName: node.display_name,
    transform: node.transform,
  }));
  const parts = new Map<string, PreviewPart>();
  const missing: string[] = [];
  for (const node of nodes) {
    if (parts.has(node.partKey)) continue;
    const part = carried.get(node.partKey) ?? cache.get(node.partKey);
    if (part) parts.set(node.partKey, part);
    else if (!missing.includes(node.partKey)) missing.push(node.partKey);
  }
  return { parts, nodes, missing };
}
