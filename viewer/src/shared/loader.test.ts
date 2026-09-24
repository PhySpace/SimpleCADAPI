import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { unzipSync, zipSync } from 'fflate';
import { openCadPackage, type PackageFiles } from './product-package';

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = join(here, '../../examples/out/hydraulic_rod_assembly/hydraulic_rod_assembly.scadpkg');
const fixture = new Uint8Array(readFileSync(fixturePath));

type SceneManifestFixture = {
  schema_version: string;
  geometry_assets: { uri: string }[];
  entity_assets: { uri: string }[];
  source_assets: { uri: string }[];
};

function unzipPackage(raw: Uint8Array): PackageFiles {
  return unzipSync(raw) as PackageFiles;
}

test('opens a canonical v3 product package', async () => {
  const opened = await openCadPackage(fixture);
  assert.equal(opened.schemaVersion, '3.0');
  assert.match(opened.packageContentHash, /^sha256:[0-9a-f]{64}$/);
  const scene = JSON.parse(new TextDecoder().decode(opened.files['scene.json'])) as SceneManifestFixture;
  assert.equal(scene.schema_version, '2.0');
  const expected = new Set(['scene.json']);
  for (const collection of [scene.geometry_assets, scene.entity_assets, scene.source_assets]) {
    for (const asset of collection) {
      expected.add(asset.uri);
      assert.ok(opened.files[asset.uri], `asset bytes are missing: ${asset.uri}`);
    }
  }
  // Product definition ZIPs and feature-graph archives are never materialized.
  assert.deepEqual([...Object.keys(opened.files)].sort(), [...expected].sort());
});

test('rejects a tampered blob member by hash', async () => {
  const files = unzipPackage(fixture);
  const blobMember = Object.keys(files).find((name) => name.startsWith('blobs/'));
  assert.ok(blobMember, 'fixture must contain blob members');
  const payload = files[blobMember];
  payload[payload.byteLength - 1] ^= 0xff;
  await assert.rejects(() => openCadPackage(zipSync(files)), /package member hash differs/);
});

test('rejects an extra unreferenced member', async () => {
  const files = unzipPackage(fixture);
  files['smuggled.txt'] = new Uint8Array([1]);
  await assert.rejects(() => openCadPackage(zipSync(files)), /references do not match package members/);
});

test('rejects a v2 product package', async () => {
  const manifest = JSON.stringify({
    schema_version: '2.0',
    artifact_kind: 'product_package',
    content_hash: 'sha256:' + '0'.repeat(64),
    root: 'scene/scene.zip',
    objects: [],
    scene: null,
  });
  await assert.rejects(
    () => openCadPackage(zipSync({ 'package.json': new TextEncoder().encode(manifest) })),
    /unsupported product package schema/,
  );
});

test('rejects a wrong content_hash', async () => {
  const files = unzipPackage(fixture);
  const manifest = JSON.parse(new TextDecoder().decode(files['package.json'])) as { content_hash: string };
  const hex = manifest.content_hash.slice('sha256:'.length);
  manifest.content_hash = 'sha256:' + (hex[0] === '0' ? '1' : '0') + hex.slice(1);
  files['package.json'] = new TextEncoder().encode(JSON.stringify(manifest));
  await assert.rejects(() => openCadPackage(zipSync(files)), /product package content_hash is invalid/);
});
