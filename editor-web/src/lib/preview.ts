/** The preview a kernel makes of its model (`simplecadapi.scene.preview`):
 * the arrays a viewer draws, the index range of every face and edge, each part
 * once and where each of its instances stands.
 *
 * Layout: `SCAPREV1`, a u32 header length, 4 bytes of padding, the JSON header
 * (padded to 8 bytes), then the little-endian arrays the header points into.
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

export type PreviewData = { parts: Map<string, PreviewPart>; nodes: PreviewNode[] };

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

export function parsePreview(buffer: ArrayBuffer): PreviewData {
  const bytes = new Uint8Array(buffer);
  if (new TextDecoder().decode(bytes.subarray(0, MAGIC.length)) !== MAGIC) throw new Error("not a preview");
  const view = new DataView(buffer);
  const headerLength = view.getUint32(MAGIC.length, true);
  const headerStart = MAGIC.length + 8;
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(headerStart, headerStart + headerLength))) as Header;
  if (header.schema !== "sca-preview-1") throw new Error(`unsupported preview schema: ${header.schema}`);
  const base = headerStart + headerLength;
  const floats = (ref: ArrayRef) => new Float32Array(buffer, base + ref.offset, ref.count);
  const uints = (ref: ArrayRef) => new Uint32Array(buffer, base + ref.offset, ref.count);
  const parts = new Map<string, PreviewPart>();
  for (const part of header.parts) {
    parts.set(part.key, {
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
  return { parts, nodes };
}
