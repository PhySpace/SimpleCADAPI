# `.scadpkg` Package Format

The durable product archive written by `capture`. This page is a
consumer's spec: read it once, and you can parse any package and locate
what an addon needs — geometry, tags, assemblies, scene assets — in any
language. The normative sources are the JSON Schemas shipped inside the
`simplecadapi` wheel (`simplecadapi/contracts/`); when prose and schema
disagree, the schema wins.

Authoring and installing addons that consume packages:
`references/domains/addon-development.md`.

## What a package is

A ZIP archive. Everything inside is content-addressed and
integrity-checked; the manifest (`package.json`) is the only map —
never guess members by name or extension, always resolve through it.
Packages are validated against Draft 2020-12 JSON Schemas both when
written and when read; a tampered member produces a named rejection,
not a silent fallback. Units are millimeters throughout.

## Member layout

| Member | Content | Schema |
| --- | --- | --- |
| `package.json` | manifest — the map to every other member | `product-package-3.schema.json` |
| `definitions/part/<hash>.json` | one part definition (units, generator, caches, topology ref, connectors, material) | `part-definition-2.schema.json` |
| `definitions/assembly/<hash>.json` | one assembly definition (instances, relations, solved snapshot, public connectors) | `assembly-definition-2.schema.json` |
| `occurrences/root.json` | occurrence graph (which definitions occur where) | manifest member record |
| `projections/scene/scene.json` | scene projection for rendering (present when captured with scene) | scene contracts |
| `blobs/<sha256>` | content-addressed payloads (BREP cache, topology snapshots, glTF assets, feature graphs) | — |

## Manifest (`package.json`) fields

All top-level fields are required: `schema_version` (`"3.0"`),
`artifact_kind` (`"product_package"`), `root` (path/definition_kind/
definition_id/revision/content_hash), `definitions[]` (one record per
definition: path, definition_kind, definition_id, revision,
content_hash, sha256, byte_length), `blobs[]` (sha256, byte_length,
`media_type`, `storage: {kind: "member", path}`), `occurrence_graph`
(member record), `projections` (scene member record), and `content_hash`
covering the manifest body.

## Resolving references: sha256 is the key, not the path

Every reference into a payload carries
`{path, sha256, byte_length, media_type}`. The `path` is a **logical
name** (`topology/<hash>.json`) — it is not necessarily a ZIP member
path. The payload is stored under `blobs/<sha256-without-prefix>`, and
the manifest's `blobs[]` entry gives the real `storage.path`. Resolve
by `sha256`, always:

```python
def member_bytes(package, ref):
    """ref: a BlobRef (attribute access) or its dict form (subscript)."""
    sha = getattr(ref, "sha256", None) or ref["sha256"]
    digest = str(sha).removeprefix("sha256:")
    for blob in package.manifest["blobs"]:
        if str(blob["sha256"]).removeprefix("sha256:") == digest:
            return package.objects[str(blob["storage"]["path"])]
    raise KeyError(f"member for {digest} not in manifest blobs")
```

`storage.kind` is `"member"` for single payloads; `"archive"` entries
are composites (feature-graph manifests with source snapshots) whose
inner files are themselves `member` blobs — resolving any single file
by its own sha256 through the map above works uniformly.
`media_type` on the record tells you what the payload is
(`application/vnd.simplecad.entities+json` topology snapshots,
`application/vnd.simplecad.feature-graph+zip` feature graphs,
`model/gltf-binary` scene assets) — do not infer from extensions.

## Definitions

Part definitions carry: `units` (`"mm"`), `generator`
(`{ocp_version}`), `solid_cache` (body reference — the BREP payload for
in-process rebuild), `topology_snapshot_ref` (the tag channel, below),
`connectors`, `material_ref`, `metadata`, `profile`
(`simplecad-part-definition-2`), `revision`, and, only when the body has
a display appearance, `appearance`
(`{"bodies": [{"body_id", "color", "opacity", "name"?}]}`, one row at
most: colour as linear RGB in [0, 1] overriding the material colour for
display). A part definition holds exactly one solid: `solid_cache` has
`evaluator_profile` and `body_ref` only (there is no `solid_cache.bodies`
and no profile 3; that existed only in the withdrawn 2.2.8 release).
Assembly definitions carry `definition_refs`, `instances`,
`relations`, `public_connectors`, `solved_snapshot`,
`grounded_instance_ids`, `feature_graph_ref`. Identity is
(`definition_id`, `revision`, `content_hash`).

## The tag channel: `interface.*` only

Only tags in the `interface.*` namespace cross the package boundary;
every other tag stays in the session. The chain:

1. Take a **part** definition's `topology_snapshot_ref` (assemblies
   carry `feature_graph_ref` instead).
2. Resolve it by sha256 (above) into the snapshot JSON
   (`{schema_version, entities[], entity_count, name_index,
   topology_hash, geometry_hash}`).
3. Read `name_index`: `{"interface.<name>": [{"kind", "topo_id",
   "geometry_hash"}, ...]}` — one public name may reference several
   entities of a single kind (a pattern of holes is one name over many
   faces), in deterministic order.
4. `entities[]` entries carry `kind` (`FACE` / `EDGE` / ...),
   `topo_id`, `geometry_hash`, the full `tags` list, and
   `feature_output` provenance (which graph node produced them).

Consumer contract: if an `interface.*` name your tool requires is
absent from `name_index`, fail loudly and name it — never guess by
geometry. Model authors create these names with
`apply_tag(shape=..., tag="interface.xxx")` during modeling; consuming
them requires nothing from the modeling side afterwards.

## Minimal readers

### Path A — in-process SDK (Python addon with its own environment)

```python
import json

from simplecadapi import read_product_package

package = read_product_package(data="bracket.scadpkg")
root = package.root_definition
snapshot = json.loads(member_bytes(package, root.topology_snapshot_ref))
faces_by_name = snapshot["name_index"]  # {"interface.load_surface": [...], ...}
```

`read_product_package` validates the full package (integrity + schema)
before returning; `load_product_package(data=...)` returns the root
definition directly. Builtin exporters
(`export_product_package_to_step/stl/obj/mjcf`) start from the same
validated package.

### Path B — language-agnostic (pure ZIP + JSON)

The same five steps in any language:

1. Open the ZIP; read `package.json`.
2. Check `schema_version` major is `3`; abort loudly otherwise.
3. Walk `manifest["definitions"]`, reading each record's `path`
   (these paths ARE real member paths).
4. Build a sha→path map over `manifest["blobs"]` entries with
   `storage.kind == "member"`; resolve every payload reference's
   `sha256` through it, then read that member.
5. Parse the topology snapshot and read `name_index`.

In Python this is `zipfile` + `json` only — no SDK import, no OCP;
this is the path for non-Python addons and for plugins that must not
share an environment with the SDK.

## Integrity rules

Every member is covered by a sha256 recorded in the manifest; the
manifest body is covered by `content_hash` over canonical JSON
(RFC 8785). Consumers should verify the digest of anything they load;
the SDK read path already does. Hand-editing members is unsupported —
rebuild the package from source instead.
