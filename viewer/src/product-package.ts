import { strFromU8, unzipSync } from 'fflate';

export type PackageFiles = Record<string, Uint8Array>;

export type OpenedCadPackage = {
  files: PackageFiles;
  packageContentHash: string;
  schemaVersion: '3.0';
};

type HashRecord = {
  uri?: string;
  path?: string;
  sha256: string;
  byte_length: number;
};

// A record whose payload is one exact ZIP member (definition, occurrence
// graph, member blob, scene projection manifest); v3 always addresses these
// by an explicit path.
type MemberRecord = {
  path: string;
  sha256: string;
  byte_length: number;
};

// A scene asset record addressed by its scene URI.
type AssetRecord = HashRecord & { uri: string };

type DefinitionKind = 'single_solid' | 'assembly';

type DefinitionRecord = MemberRecord & {
  definition_kind: DefinitionKind;
  definition_id: string;
  revision: string;
  content_hash: string;
};

type PackageRoot = {
  path: string;
  definition_kind: DefinitionKind;
  definition_id: string;
  revision: string;
  content_hash: string;
};

type MemberStorage = { kind: 'member'; path: string };

type ArchiveStorage = {
  kind: 'archive';
  manifest_name: string;
  members: { path: string; sha256: string }[];
};

type BlobRecord = {
  sha256: string;
  byte_length: number;
  media_type: string;
  storage: MemberStorage | ArchiveStorage;
};

type SceneAssetSource =
  | { kind: 'definition'; definition_id: string }
  | { kind: 'blob'; sha256: string };

type SceneProjection = {
  manifest: MemberRecord;
  scene_id: string;
  revision: string;
  assets: { uri: string; source: SceneAssetSource }[];
};

type ProductManifest = {
  schema_version: string;
  artifact_kind: string;
  content_hash: string;
  root: PackageRoot;
  definitions: DefinitionRecord[];
  blobs: BlobRecord[];
  occurrence_graph: HashRecord;
  projections: { scene?: SceneProjection };
};

type SceneProductAsset = AssetRecord & {
  definition_id: string;
  definition_kind: DefinitionKind;
  revision: string;
  content_hash: string;
};

type SceneManifest = {
  schema_version: string;
  scene_id: string;
  revision: string;
  geometry_assets: AssetRecord[];
  entity_assets: AssetRecord[];
  product_assets: SceneProductAsset[];
  feature_graph_assets: AssetRecord[];
  source_assets: AssetRecord[];
};

const MAX_PACKAGE_BYTES = 256 * 1024 * 1024;
const MAX_PACKAGE_MEMBERS = 10_000;
const MAX_UNPACKED_BYTES = 512 * 1024 * 1024;
const MAX_MEMBER_BYTES = 256 * 1024 * 1024;
const MAX_MANIFEST_BYTES = 32 * 1024 * 1024;
const MAX_COMPRESSION_RATIO = 100;

const MANIFEST_KEYS = ['artifact_kind', 'blobs', 'content_hash', 'definitions', 'occurrence_graph', 'projections', 'root', 'schema_version'];

const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;

function validateMemberName(name: string): void {
  if (!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,4095}$/.test(name)
    || name.split('/').some((segment) => !segment || segment === '.' || segment === '..')) {
    throw new Error(`invalid package member: ${name}`);
  }
}

function extractArchive(raw: Uint8Array, manifestNames: readonly string[]): PackageFiles {
  if (raw.byteLength > MAX_PACKAGE_BYTES) throw new Error('package exceeds browser size limit');
  let memberCount = 0;
  let unpackedBytes = 0;
  const seenNames = new Set<string>();
  unzipSync(raw, { filter: (entry) => {
    validateMemberName(entry.name);
    const foldedName = entry.name.toLowerCase();
    if (seenNames.has(foldedName)) throw new Error(`duplicate or case-colliding package member: ${entry.name}`);
    seenNames.add(foldedName);
    memberCount += 1;
    unpackedBytes += entry.originalSize;
    if (entry.compression !== 0 && entry.compression !== 8) throw new Error(`unsupported ZIP compression method: ${entry.name}`);
    if (memberCount > MAX_PACKAGE_MEMBERS) throw new Error('package member count exceeds browser limit');
    if (entry.originalSize > MAX_MEMBER_BYTES) throw new Error(`package member exceeds browser size limit: ${entry.name}`);
    if (manifestNames.includes(entry.name) && entry.originalSize > MAX_MANIFEST_BYTES) throw new Error(`${entry.name} is too large`);
    if (unpackedBytes > MAX_UNPACKED_BYTES) throw new Error('package expands beyond browser size limit');
    if (entry.originalSize > MAX_COMPRESSION_RATIO * Math.max(1, entry.size)) throw new Error(`package member compression ratio is too high: ${entry.name}`);
    return false;
  }});
  const presentManifests = manifestNames.filter((name) => seenNames.has(name.toLowerCase()));
  if (presentManifests.length !== 1) throw new Error('package must contain exactly one supported manifest');
  if (unpackedBytes > MAX_COMPRESSION_RATIO * raw.byteLength) throw new Error('package compression ratio is too high');
  const files = unzipSync(raw) as PackageFiles;
  const entries = Object.entries(files);
  if (entries.length !== memberCount) throw new Error('package member count changed during extraction');
  if (entries.reduce((sum, [, value]) => sum + value.byteLength, 0) !== unpackedBytes) {
    throw new Error('package decoded size differs from ZIP metadata');
  }
  return files;
}

function parseManifest<T>(files: PackageFiles, name: string): T {
  const payload = files[name];
  if (!payload || payload.byteLength > MAX_MANIFEST_BYTES) throw new Error(`${name} is missing or too large`);
  let value: unknown;
  try {
    value = JSON.parse(strFromU8(payload));
  } catch {
    throw new Error(`${name} is not valid JSON`);
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must contain an object`);
  return value as T;
}

function recordPath(record: HashRecord): string {
  const path = record.uri ?? record.path;
  if (typeof path !== 'string') throw new Error('package record path is missing');
  validateMemberName(path);
  return path;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error('manifest contains a non-finite number');
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) throw new Error('manifest contains an unsafe integer');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (typeof value !== 'object') throw new Error('manifest contains a non-JSON value');
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`).join(',')}}`;
}

async function sha256(payload: Uint8Array): Promise<string> {
  const view = payload.buffer.slice(payload.byteOffset, payload.byteOffset + payload.byteLength) as ArrayBuffer;
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', view));
  return `sha256:${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

async function canonicalHash(value: unknown): Promise<string> {
  return sha256(new TextEncoder().encode(canonicalJson(value)));
}

async function validateRecords(files: PackageFiles, records: HashRecord[], manifestName: string): Promise<void> {
  const referenced = new Set<string>([manifestName]);
  for (const record of records) {
    const path = recordPath(record);
    if (referenced.has(path)) throw new Error(`duplicate package reference: ${path}`);
    referenced.add(path);
    const payload = files[path];
    if (!payload) throw new Error(`package member is missing: ${path}`);
    if (!Number.isSafeInteger(record.byte_length) || record.byte_length < 0 || payload.byteLength !== record.byte_length) {
      throw new Error(`package member length differs: ${path}`);
    }
    if (!SHA256_PATTERN.test(record.sha256) || await sha256(payload) !== record.sha256) {
      throw new Error(`package member hash differs: ${path}`);
    }
  }
  const names = Object.keys(files);
  if (names.length !== referenced.size || names.some((name) => !referenced.has(name))) {
    throw new Error(`${manifestName} references do not match package members`);
  }
}

function requireObject(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error(`${what} must contain an object`);
  return value as Record<string, unknown>;
}

function requireRecordArray(value: unknown, what: string): Record<string, unknown>[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'object' || item === null || Array.isArray(item))) {
    throw new Error(`${what} must be an array of records`);
  }
  return value as Record<string, unknown>[];
}

function requireString(holder: Record<string, unknown>, field: string, what: string): string {
  const value = holder[field];
  if (typeof value !== 'string') throw new Error(`${what} ${field} is missing`);
  return value;
}

function requireSha256(holder: Record<string, unknown>, field: string, what: string): string {
  const value = requireString(holder, field, what);
  if (!SHA256_PATTERN.test(value)) throw new Error(`${what} ${field} is not a sha256 digest`);
  return value;
}

function requireByteLength(holder: Record<string, unknown>, what: string): number {
  const value = holder.byte_length;
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error(`${what} byte_length is invalid`);
  return value;
}

function requireMemberPath(holder: Record<string, unknown>, field: string, what: string): string {
  const value = requireString(holder, field, what);
  validateMemberName(value);
  return value;
}

function requireDefinitionKind(holder: Record<string, unknown>, what: string): DefinitionKind {
  const value = holder.definition_kind;
  if (value !== 'single_solid' && value !== 'assembly') throw new Error(`${what} definition_kind is unsupported`);
  return value;
}

function requireAssetRecord(raw: Record<string, unknown>, what: string): AssetRecord {
  return {
    uri: requireMemberPath(raw, 'uri', what),
    sha256: requireSha256(raw, 'sha256', what),
    byte_length: requireByteLength(raw, what),
  };
}

// Strictly ascending adjacent pairs prove sortedness and uniqueness in one
// pass; member names and hex digests are pure ASCII, so JS string comparison
// equals the byte-order sort of the canonical writer.
function requireSortedUnique(values: string[], what: string): void {
  if (!values.every((value, index) => index === 0 || values[index - 1] < value)) throw new Error(what);
}

type ParsedPackage = {
  definitionRecords: DefinitionRecord[];
  blobByHash: Map<string, BlobRecord>;
  occurrenceGraph: MemberRecord;
  sceneProjection: SceneProjection | null;
  contentHash: string;
};

// Mirrors the structural invariants of product-package-3.schema.json and
// ProductPackage._validate_manifest without a JSON-Schema engine.
function parseProductManifest(manifest: Record<string, unknown>): ParsedPackage {
  const keys = Object.keys(manifest);
  if (keys.length !== MANIFEST_KEYS.length || MANIFEST_KEYS.some((key) => !(key in manifest))) {
    throw new Error(`product package manifest keys are not canonical: ${keys.sort().join(', ')}`);
  }

  const definitionRecords = requireRecordArray(manifest.definitions, 'package definitions').map((raw) => ({
    path: requireMemberPath(raw, 'path', 'definition record'),
    sha256: requireSha256(raw, 'sha256', 'definition record'),
    byte_length: requireByteLength(raw, 'definition record'),
    definition_kind: requireDefinitionKind(raw, 'definition record'),
    definition_id: requireString(raw, 'definition_id', 'definition record'),
    revision: requireString(raw, 'revision', 'definition record'),
    content_hash: requireSha256(raw, 'content_hash', 'definition record'),
  })) as DefinitionRecord[];
  if (definitionRecords.length === 0) throw new Error('package definitions are empty');
  requireSortedUnique(definitionRecords.map((record) => record.path), 'definition records must be unique and path-sorted');
  const definitionIds = definitionRecords.map((record) => record.definition_id);
  if (new Set(definitionIds).size !== definitionIds.length) throw new Error('definition IDs must be unique');
  const definitionPathSet = new Set(definitionRecords.map((record) => record.path));

  const rootRaw = requireObject(manifest.root, 'package root');
  if (!definitionPathSet.has(requireMemberPath(rootRaw, 'path', 'package root'))) throw new Error('package root does not resolve');

  const blobRecords = requireRecordArray(manifest.blobs, 'package blobs').map((raw) => {
    const sha256 = requireSha256(raw, 'sha256', 'blob record');
    const storageRaw = requireObject(raw.storage, `blob ${sha256} storage`);
    let storage: MemberStorage | ArchiveStorage;
    if (storageRaw.kind === 'member') {
      storage = { kind: 'member', path: requireMemberPath(storageRaw, 'path', 'blob storage') };
    } else if (storageRaw.kind === 'archive') {
      storage = {
        kind: 'archive',
        manifest_name: requireString(storageRaw, 'manifest_name', 'blob storage'),
        members: requireRecordArray(storageRaw.members, 'archive blob members').map((member) => ({
          path: requireMemberPath(member, 'path', 'archive blob member'),
          sha256: requireSha256(member, 'sha256', 'archive blob member'),
        })),
      };
    } else {
      throw new Error(`blob ${sha256} storage kind is unsupported`);
    }
    return { sha256, byte_length: requireByteLength(raw, 'blob record'), media_type: requireString(raw, 'media_type', 'blob record'), storage };
  }) as BlobRecord[];
  requireSortedUnique(blobRecords.map((record) => record.sha256), 'blob records must be unique and hash-sorted');
  const blobByHash = new Map(blobRecords.map((record) => [record.sha256, record]));
  for (const record of blobRecords) {
    if (record.storage.kind === 'member') {
      if (definitionPathSet.has(record.storage.path)) throw new Error('blob member path collides with definition');
    } else {
      const memberPaths = record.storage.members.map((member) => member.path);
      if (new Set(memberPaths).size !== memberPaths.length) throw new Error(`archive blob members are duplicated: ${record.sha256}`);
      if (memberPaths.join('\u0000') !== [...memberPaths].sort().join('\u0000')) throw new Error('archive blob members must be path-sorted');
      for (const member of record.storage.members) {
        if (!blobByHash.has(member.sha256)) throw new Error(`archive blob member is not declared: ${member.path}`);
      }
    }
  }

  const occurrenceRaw = requireObject(manifest.occurrence_graph, 'occurrence graph record');
  const occurrenceGraph: MemberRecord = {
    path: requireMemberPath(occurrenceRaw, 'path', 'occurrence graph record'),
    sha256: requireSha256(occurrenceRaw, 'sha256', 'occurrence graph record'),
    byte_length: requireByteLength(occurrenceRaw, 'occurrence graph record'),
  };

  const projectionsRaw = requireObject(manifest.projections, 'package projections');
  let sceneProjection: SceneProjection | null = null;
  if (projectionsRaw.scene !== undefined) {
    const raw = requireObject(projectionsRaw.scene, 'scene projection');
    const manifestRecord = requireObject(raw.manifest, 'scene projection manifest record');
    sceneProjection = {
      manifest: {
        path: requireMemberPath(manifestRecord, 'path', 'scene projection manifest'),
        sha256: requireSha256(manifestRecord, 'sha256', 'scene projection manifest'),
        byte_length: requireByteLength(manifestRecord, 'scene projection manifest'),
      },      scene_id: requireString(raw, 'scene_id', 'scene projection'),
      revision: requireString(raw, 'revision', 'scene projection'),
      assets: requireRecordArray(raw.assets, 'scene projection assets').map((asset) => {
        const uri = requireString(asset, 'uri', 'scene projection asset');
        const sourceRaw = requireObject(asset.source, `scene projection asset source: ${uri}`);
        if (sourceRaw.kind === 'definition') {
          return { uri, source: { kind: 'definition', definition_id: requireString(sourceRaw, 'definition_id', 'scene projection source') } };
        }
        if (sourceRaw.kind === 'blob') {
          return { uri, source: { kind: 'blob', sha256: requireSha256(sourceRaw, 'sha256', 'scene projection source') } };
        }
        throw new Error(`scene projection asset source kind is unsupported: ${uri}`);
      }),
    };
    const definitionIdSet = new Set(definitionIds);
    const seenUris = new Set<string>();
    for (const asset of sceneProjection.assets) {
      if (seenUris.has(asset.uri)) throw new Error(`scene projection asset URIs must be unique: ${asset.uri}`);
      seenUris.add(asset.uri);
      if (asset.source.kind === 'definition' && !definitionIdSet.has(asset.source.definition_id)) {
        throw new Error(`scene projection definition does not resolve: ${asset.uri}`);
      }
      if (asset.source.kind === 'blob' && !blobByHash.has(asset.source.sha256)) {
        throw new Error(`scene projection blob does not resolve: ${asset.uri}`);
      }
    }
  }

  return { definitionRecords, blobByHash, occurrenceGraph, sceneProjection, contentHash: requireSha256(manifest, 'content_hash', 'product package') };
}

function parseSceneManifest(value: unknown, name: string): SceneManifest {
  const manifest = requireObject(value, name);
  const scene: SceneManifest = {
    schema_version: requireString(manifest, 'schema_version', name),
    scene_id: requireString(manifest, 'scene_id', name),
    revision: requireString(manifest, 'revision', name),
    geometry_assets: requireRecordArray(manifest.geometry_assets, 'scene geometry_assets').map((raw) => requireAssetRecord(raw, 'scene geometry asset')),
    entity_assets: requireRecordArray(manifest.entity_assets, 'scene entity_assets').map((raw) => requireAssetRecord(raw, 'scene entity asset')),
    product_assets: requireRecordArray(manifest.product_assets, 'scene product_assets').map((raw) => ({
      ...requireAssetRecord(raw, 'scene product asset'),
      definition_id: requireString(raw, 'definition_id', 'scene product asset'),
      definition_kind: requireDefinitionKind(raw, 'scene product asset'),
      revision: requireString(raw, 'revision', 'scene product asset'),
      content_hash: requireSha256(raw, 'content_hash', 'scene product asset'),
    })),
    feature_graph_assets: requireRecordArray(manifest.feature_graph_assets, 'scene feature_graph_assets').map((raw) => requireAssetRecord(raw, 'scene feature graph asset')),
    source_assets: requireRecordArray(manifest.source_assets, 'scene source_assets').map((raw) => requireAssetRecord(raw, 'scene source asset')),
  };
  if (scene.schema_version !== '2.0') throw new Error(`unsupported scene schema: ${scene.schema_version}`);
  return scene;
}

export async function openCadPackage(raw: Uint8Array): Promise<OpenedCadPackage> {
  const files = extractArchive(raw, ['package.json']);
  const manifest = parseManifest<ProductManifest>(files, 'package.json');
  if (manifest.schema_version !== '3.0' || manifest.artifact_kind !== 'product_package') throw new Error('unsupported product package schema');
  const parsed = parseProductManifest(manifest as unknown as Record<string, unknown>);
  const draft = { ...(manifest as unknown as Record<string, unknown>) };
  delete draft.content_hash;
  if (parsed.contentHash !== await canonicalHash(draft)) throw new Error('product package content_hash is invalid');

  // Member closure: every record above maps 1:1 onto a ZIP member and the
  // archive may hold nothing else. Archive-kind blobs contribute no direct
  // member; their inner payloads appear separately as member-kind blobs.
  const memberBlobs = [...parsed.blobByHash.values()]
    .filter((record) => record.storage.kind === 'member')
    .map((record) => ({ path: (record.storage as MemberStorage).path, sha256: record.sha256, byte_length: record.byte_length }));
  await validateRecords(files, [
    ...parsed.definitionRecords,
    parsed.occurrenceGraph,
    ...memberBlobs,
    ...(parsed.sceneProjection ? [parsed.sceneProjection.manifest] : []),
  ], 'package.json');

  // The occurrence graph and the product/feature-graph ZIP payloads are never
  // consumed by the viewer, so they are integrity-checked as members above but
  // neither re-derived from definitions nor re-packed into canonical archives.
  if (!parsed.sceneProjection) throw new Error('product package does not embed a scene projection');
  const projection = parsed.sceneProjection;
  const sceneValue = parseManifest(files, projection.manifest.path);
  const scene = parseSceneManifest(sceneValue, 'scene manifest');
  const sceneDraft = { ...(sceneValue as Record<string, unknown>) };
  delete sceneDraft.revision;
  if (scene.revision !== await canonicalHash(sceneDraft)) throw new Error('scene revision is invalid');
  if (scene.scene_id !== projection.scene_id || scene.revision !== projection.revision) {
    throw new Error('embedded scene identity differs from package projection');
  }

  const sourceByUri = new Map(projection.assets.map((asset) => [asset.uri, asset.source]));
  const outFiles: PackageFiles = { 'scene.json': files[projection.manifest.path] };
  const materialize = (records: HashRecord[], collection: string): void => {
    for (const record of records) {
      const uri = recordPath(record);
      const source = sourceByUri.get(uri);
      if (!source) throw new Error(`scene ${collection} asset is not covered by the package projection: ${uri}`);
      if (source.kind !== 'blob') throw new Error(`scene ${collection} asset must resolve to a package blob: ${uri}`);
      const blob = parsed.blobByHash.get(source.sha256);
      if (!blob || blob.storage.kind !== 'member') throw new Error(`scene ${collection} asset resolves to an archive blob: ${uri}`);
      if (record.sha256 !== blob.sha256 || record.byte_length !== blob.byte_length) {
        throw new Error(`scene ${collection} asset identity differs from package blob: ${uri}`);
      }
      outFiles[uri] = files[blob.storage.path];
    }
  };
  materialize(scene.geometry_assets, 'geometry');
  materialize(scene.entity_assets, 'entity');
  materialize(scene.source_assets, 'source');

  for (const record of scene.product_assets) {
    const uri = recordPath(record);
    const source = sourceByUri.get(uri);
    if (!source) throw new Error(`scene product asset is not covered by the package projection: ${uri}`);
    if (source.kind !== 'definition') throw new Error(`scene product asset must resolve to a package definition: ${uri}`);
  }
  for (const record of scene.feature_graph_assets) {
    const uri = recordPath(record);
    const source = sourceByUri.get(uri);
    if (!source) throw new Error(`scene feature graph asset is not covered by the package projection: ${uri}`);
    if (source.kind !== 'blob') throw new Error(`scene feature graph asset must resolve to a package blob: ${uri}`);
  }

  const identity = (record: { definition_kind: string; definition_id: string; revision: string; content_hash: string }): string =>
    [record.definition_kind, record.definition_id, record.revision, record.content_hash].join('\u0000');
  const packageIdentities = parsed.definitionRecords.map(identity).sort();
  const sceneIdentities = scene.product_assets.map(identity).sort();
  if (packageIdentities.length !== sceneIdentities.length
    || packageIdentities.some((item, index) => item !== sceneIdentities[index])) {
    throw new Error('product package definitions differ from embedded scene product assets');
  }

  return { files: outFiles, packageContentHash: parsed.contentHash, schemaVersion: '3.0' };
}
