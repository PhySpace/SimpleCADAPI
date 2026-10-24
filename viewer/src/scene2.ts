import { strFromU8 } from 'fflate';
import type { PackageFiles } from './product-package';

export type Vec3 = [number, number, number];
export type Transform = { origin: Vec3; x_axis: Vec3; y_axis: Vec3; z_axis: Vec3 };
export type SourceRecord = Record<string, unknown> & {
  kind: string;
  definition_id?: string;
  graph_id?: string;
  node_id?: string;
  output_slot?: number;
  topology_kind?: string;
  topo_id?: string;
};
export type Definition = {
  definition_id: string;
  definition_kind: 'single_solid' | 'assembly';
  revision: string;
  content_hash: string;
  product_asset_id: string;
  feature_graph_asset_id: string;
};
export type SceneNode = {
  node_id: string;
  parent_node_id: string | null;
  display_name: string;
  node_kind: 'part' | 'assembly' | 'solid';
  definition_id: string;
  definition_kind: 'single_solid' | 'assembly';
  component_id: string | null;
  instance_id: string | null;
  transform: Transform;
  geometry_asset_id: string | null;
  entity_asset_id: string | null;
  material_id: string | null;
  properties: Record<string, unknown>;
};
export type Asset = {
  asset_id: string;
  uri: string;
  media_type: string;
  sha256: string;
  byte_length: number;
};
export type Entity = {
  entity_id: string;
  kind: 'solid' | 'face' | 'edge' | 'vertex';
  topo_id: string;
  parent_entity_ids: string[];
  child_entity_ids: string[];
  source: SourceRecord;
  properties: Record<string, unknown>;
  geometry: Record<string, unknown>;
  tags: string[];
};
export type EntitySidecar = {
  schema_version: '2.0';
  definition_id: string;
  geometry_asset_id: string;
  edge_asset_id: string;
  entities: Entity[];
  face_groups: FaceGroup[];
  edge_groups: FaceGroup[];
};
export type FaceGroup = { entity_id: string; first_index: number; index_count: number };
export type SourceAsset = {
  source_asset_id: string;
  uri: string;
  sha256: string;
  byte_length: number;
  media_type: string;
  display_name: string;
};
export type SourceSpan = {
  source_asset_id: string;
  uri: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
};
export type Feature = {
  feature_id: string;
  definition_id: string;
  graph_id: string;
  node_id: string;
  op: string;
  label: string | null;
  parameters: Record<string, unknown>;
  input_feature_ids: string[];
  output_count: number;
  source_spans: SourceSpan[];
};
export type ConnectorSnapshot = {
  connector_snapshot_id: string;
  node_id: string;
  definition_id: string;
  definition_kind: 'single_solid' | 'assembly';
  connector_id: string;
  name: string;
  anchor_kind: 'placement' | 'geometry' | 'forwarded';
  local_frame: Transform;
  binding: Record<string, unknown> | null;
  forwarded_from: Record<string, unknown> | null;
  source_feature_id: string | null;
};
export type ConnectorRef = {
  definition_id: string;
  component_id: string;
  instance_id: string;
  connector_id: string;
  connector_snapshot_id: string;
};
export type Joint = {
  joint_id: string;
  assembly_definition_id: string;
  joint_type: 'fixed' | 'revolute' | 'prismatic' | 'cylindrical' | 'planar' | 'ball' | 'gear' | 'belt' | 'rack_pinion';
  connector_a: ConnectorRef;
  connector_b: ConnectorRef;
  parameters: Record<string, unknown>;
  limits: Record<string, unknown> | null;
  source_feature_id: string | null;
};
export type SceneManifest = {
  schema_version: '2.0';
  scene_id: string;
  revision: string;
  units: 'mm';
  roots: string[];
  definitions: Definition[];
  geometry_assets: Asset[];
  entity_assets: Asset[];
  product_assets: Array<Asset & { definition_id: string }>;
  feature_graph_assets: Array<Asset & { definition_id: string; graph_id: string; graph_revision: string }>;
  source_assets: SourceAsset[];
  nodes: SceneNode[];
  connectors: ConnectorSnapshot[];
  joints: Joint[];
  feature_index: Feature[];
  source_index: Array<{
    source_index_id: string;
    source_asset_id: string;
    uri: string;
    definition_id: string;
    feature_id: string;
    start_line: number;
    end_line: number;
    symbol: string | null;
  }>;
  connector_index: Array<{
    connector_index_id: string;
    definition_id: string;
    node_id: string;
    connector_id: string;
    connector_snapshot_id: string;
    source_feature_id: string | null;
  }>;
  joint_index: Array<{
    joint_index_id: string;
    assembly_definition_id: string;
    joint_id: string;
    source_feature_id: string | null;
  }>;
  camera: { target: Vec3; position: Vec3; up: Vec3; near: number; far: number; fit_mode: string; margin: number };
  extensions: Record<string, unknown>;
};
export type OperationSource = {
  path?: string | null;
  line: number;
  column: number;
  end_line: number;
  end_column: number;
  call_text?: string;
  callsite_id: string;
  assignment_targets: string[];
};
export type ModelNode = {
  node_id: string;
  definition_id: string;
  graph_id: string;
  local_node_id: string;
  op: string;
  params: Record<string, unknown>;
  inputs: string[];
  output_count: number;
  display: { label?: string; category?: string; summary?: string };
  source?: OperationSource;
  sources: OperationSource[];
};
export type ModelDocument = { graph: { graph_id: string; nodes: ModelNode[] }; leaf_ids: string[] };

export function buildFederatedFeatureModel(
  manifest: SceneManifest,
  files: PackageFiles,
): { model: ModelDocument; sources: Map<string, string> } {
  const pathBySourceId = new Map<string, string>();
  const sources = new Map<string, string>();
  for (const asset of manifest.source_assets) {
    let path = asset.display_name;
    const content = strFromU8(files[asset.uri]);
    const existing = sources.get(path);
    if (existing !== undefined && existing !== content) {
      path = `${path} [${asset.source_asset_id.slice(7, 15)}]`;
    }
    sources.set(path, content);
    pathBySourceId.set(asset.source_asset_id, path);
  }

  const nodes: ModelNode[] = manifest.feature_index.map((feature) => {
    const featureSources = feature.source_spans.map((span, index) => {
      const sourcePath = pathBySourceId.get(span.source_asset_id);
      return {
        path: sourcePath ?? null,
        line: span.start_line,
        column: 0,
        end_line: span.end_line,
        end_column: 0,
        callsite_id: `${feature.feature_id}/source/${index}`,
        assignment_targets: span.symbol ? [span.symbol] : [],
      } satisfies OperationSource;
    });
    return {
      node_id: feature.feature_id,
      definition_id: feature.definition_id,
      graph_id: feature.graph_id,
      local_node_id: feature.node_id,
      op: feature.op,
      params: feature.parameters,
      inputs: feature.input_feature_ids,
      output_count: feature.output_count,
      display: {
        label: feature.label ?? undefined,
        category: feature.definition_id,
      },
      source: featureSources[0],
      sources: featureSources,
    };
  });
  const consumed = new Set(nodes.flatMap((node) => node.inputs));
  const leafIds = nodes.filter((node) => !consumed.has(node.node_id)).map((node) => node.node_id);
  return {
    model: { graph: { graph_id: 'federated', nodes }, leaf_ids: leafIds },
    sources,
  };
}
