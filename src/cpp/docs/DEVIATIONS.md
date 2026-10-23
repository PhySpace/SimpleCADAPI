# Deliberate deviations from the Python SDK's internal representation

Principle: **compact internally, canonical at the boundary.** A value may be stored differently
from Python as long as the Python-format text is produced wherever it leaves the process or is
compared: `to_value` / `to_dict`, `serialize` / `.scadbrep`, error text, goldens, the Python
binding. Nothing below changes a persisted or hashed byte; every golden and parity test is
unchanged and green. A candidate whose text is persisted or hashed by kept-Python code keeps
its Python format; the table at the end lists every candidate with the decision.

## Measurements

Release build, macOS arm64, `tools/bench/probe` (`-DSCAD_BUILD_BENCH=ON`; retained heap from
`malloc_zone_statistics`, per object, N kept alive; time is CPU time, instructions from
`/usr/bin/time -l`, because other builds share the machine). `bench_memory.py` (RSS, fresh
process) agrees with the probe within 1 KB for box (26.3 vs 26.0) and fillet (113.3 vs 112.6).

| Case | Bare OCCT | Before | After | Target | Reached |
|---|---|---|---|---|---|
| box, retained | 12.1 KB | 75.7 KB | 26.0 KB | <= 30 KB | yes |
| box, heap blocks | 211 | 584 | 360 | | |
| box filleted on all edges, retained | 58.3 KB | 289.7 KB | 112.6 KB | <= 100 KB | **no** (-61%) |
| box cut by a cylinder, retained | 16.5 KB | 92.5 KB | 37.0 KB | | |
| box, peak during the call | 28.2 KB | not measured | 48.8 KB | | |
| fillet, peak during the call | 247.5 KB | not measured | 310.9 KB | | |
| box with a reactive recorder, retained | | | 31.9 KB | | recorder adds 6 KB |
| fillet with a reactive recorder, retained | | | 224.7 KB | | recorder adds 112 KB |
| fillet, all 12 edges, CPU time | 3.8 ms | 7.2 ms | 4.85-4.9 ms | <= 6 ms | yes (bare + 1.1 ms) |
| box cut by a cylinder, wall time | 3.3 ms | 3.6-4.0 ms | 3.8 ms | | unchanged (OCCT-bound) |
| box creation, CPU time | 21 us | 100-105 us | 92 us | <= 60 us | **no** (-9%) |
| box, kilo-instructions | 316 | n/a | 1350 | | |
| box / fillet with a recorder, CPU time | | | 113-120 us / 5.5 ms | | box +25%, fillet +12% |

Cut is measured in wall time: the kernel's boolean runs in parallel mode and its worker threads inflate
CPU time on a loaded machine (bare OCCT without parallel mode: 3.3 ms).

(The "before" fillet figure in `docs/memory.md` of 175 KB had gone stale: the same bench measured
290 KB on the tree this work started from.)

Method: `probe <case> N prof` installs a `malloc_logger` hook and prints live bytes by call
stack, which is how the order below was chosen (the earlier "tag bindings dominate" guess was
half right: bindings were a third; the track payload Values and per-entity bookkeeping the rest).
`probe <case> N peak`, `probe time <case> N`, `probe sizes`, `probe vol`, and `sample <pid>` for
time were used for the rest.

Where the 75.7 KB of a box went (before): 34 KB tracking payload Values + role bindings written by
`apply_tracking_tags`, 13.5 KB OCCT's own box, 13.5 KB `auto_tag_faces` (bindings, wire/edge entities,
`geo` Values), 8 KB `apply_tag`, 7 KB registry maps. `sizeof`: `TagBinding` 440 B (plus a 44-char
id, a 36-char rule id, an evidence Value: about 700 B per binding, 36 bindings per box), `SemanticState`
160 B, `Entity` 120 B, two `std::set<std::string>` per entity.

## What changed, in the order it was done, with the gain of each step (box / fillet, KB retained)

1. **TagBinding made compact** (75.7 / 289.7 -> 58.2 / 234.2). `tag` is an interned `Symbol`
   (`core/symbol.hpp`); `binding_id` is a 128-bit `BindingId` (`topo/binding_id.hpp`, text
   "tag_binding_<32 hex>", any other text is interned and round-trips exactly); producer, scope,
   target, propagation and schema version are one `Cow<TagBindingPolicy>` shared by all bindings
   made by the same rule (internal annotations, operation roles and projections build theirs once);
   evidence is a `Cow<TagEvidence>`, shared for internal annotations. 440 B -> 64 B inline. Reading is
   `b.producer()`, `b.evidence->data`; writing `b.policy.mut()`. The per-entity `std::set<string>`
   tag-name caches are gone: names are read off the (few) bindings by symbol pointer.
2. **Deferred, packed metadata** (58.2 / 234.2 -> 40.2 / 149.4). The `track` payload and the
   `semantic.lineage.coverage` runtime word of every face and edge, and the `geo` index of every
   edge/wire, are stored packed (`core/packed_value.hpp`: interned keys, numerals as varints) in one
   byte string per entity and expanded, at the position they would have had, the first time the
   dictionary is read (`metadata()`, `get_metadata`, `to_string`, serialization). A write of a new key
   behind pending values is packed too, so an active recorder does not expand them. The expansion is
   exact: key order, int vs double and every string survive; goldens and `.scadbrep` are unchanged.
3. **Entity and registry trimmed** (-> 27.0 / 117.8). `topo_id` is a `Symbol` (the names `face_0`..
   are shared by all roots); `Entity` 120 -> 80 B; `SemanticState` 160 -> 88 B (dictionaries
   allocated on first write); `free_wires` behind a pointer; the registry's per-kind
   `NCollection_IndexedMap` (two 101-slot bucket arrays minimum, a node per entry) replaced by a flat
   `ShapeIndex` with identical explorer-order numbering.
4. **Unknown-track recipe** (-> 26.0 / 112.6): the "unknown" tracking payload (edges an operation
   knew nothing about; a pure function of operation, topo id and kind) is stored as that recipe
   (about 15 bytes) and expanded by the semantic layer on read.
5. **Speed** (not memory): `assert_blend_volume_monotonic` measured 41% of a fillet (two
   `VolumePropertiesGK(1e-9)` calls). A quick estimate (GK 1e-5) now settles the common case where
   the volume dropped by more than 0.1%; the precise volumes are computed unchanged whenever the
   estimate is near a threshold, and always for the error text, so the verdict and every message are
   identical. Fillet 7.2 -> 4.85 ms. Also: the outer wire of a face and the closedness of a wire are
   cached per entity (both cost an OCCT analysis per call), `Solid::edges()` dedups by entity
   instead of by hashing id strings, binding ids are generated as two words (no text round trip),
   SHA-1 for uuid5 runs without copying, symbol lookups hit a per-thread cache.

## Candidates

| Candidate | Where used (kept-Python, from `SimpleCADAPI-native`) | Decision | Gain |
|---|---|---|---|
| `TagBinding.binding_id` | `artifacts/topology_snapshot.py`, `recording/serializer.py`, `scene/compiler.py`, `scene/validation.py`, `ql.py`: persisted | **Compact inside** (128-bit), **canonical text at every boundary** (`to_value`, serialize, binding, error text, goldens). Imported ids that are not `tag_binding_<32 lowercase hex>` are kept verbatim as symbols. Python text unchanged | box ~ -8 KB with the rest of the binding |
| `rule_id`, `rule_version` | `topology/tagging.py`, `scene/validation.py`: persisted inside the binding | Kept as strings in the shared producer record (one copy per rule, not per binding). Text unchanged | in item 1 |
| tag name | everywhere | `Symbol` inside, text at boundary | in item 1 |
| `topo_id` ("face_12") | persisted widely (`recording/serializer.py`, snapshots, scene) | `Symbol` inside (shared name table), same text. Not turned into an integer: it is returned by reference (`const std::string&`) to hundreds of call sites and its text is the id | 24 B per entity |
| `expr_id` | `params/expr.py`, translators: persisted | **Left as is**: not on the memory path (no expression is created per shape) | none measured |
| `OperationNode.node_id`, `graph_id` (`g_xxxx`, `n_xxxx`) | `recording/graph.py`, serializer, scene: persisted, parsed (`is_temporary_tracking_ref` tests the prefix) | **Left as is**: random per operation, unbounded, so not internable; the recorder's own structures are the remaining cost (see below) | none |
| semantic ids (`make_box_rsolid:0`) | recorded semantic deltas: persisted | **Left as is** | none |
| `SemanticState` per entity | internal | Allocated on first write (already), now 88 B; dictionaries allocated on first write; names derived from bindings | item 3 |
| `shared_ptr` control blocks | internal | Kept (`make_shared`: one allocation with the entity). An intrusive pointer would save 16 B per entity (~2 KB per fillet): not worth a custom type | none |
| `Value` object overhead (32 B variant, 56 B per member) | everywhere | **Not changed** (it is the public currency of metadata); the bulky, rarely read users of it were packed instead (item 2) | item 2 |
| `geo` on every edge/wire at construction | `geo.edge_index`, `geo.inner_wire_index` | Made lazy: written packed at the first enumeration (the tag `edge.boundary` is still applied then), expanded at the first metadata read; observably identical | in item 2 |

## What is left, and where

* **Fillet 112.6 KB vs the 100 KB target.** Of it 58.3 KB is OCCT's own result. Ours is 54 KB:
  entities (80 B + control block each; 108 of them for a filleted box: ~11 KB), their semantic
  states and binding vectors (~12 KB), one operation-role binding per face with its own evidence
  Value (4 KB), packed payloads (7 KB), `Entity::parents` links (3 KB), lineage witnesses. The next
  steps that would get under 100 KB: create entities and apply the first-enumeration tags only when
  an entity is first reached instead of enumerating the whole result in `apply_tracking_tags`
  (a change of the tagging model, so out of scope here), and make operation-role evidence a recipe
  like the unknown payload.
* **Box 92 us vs the 60 us target** (OCCT is 21 us). 50% of the remainder is
  `apply_tracking_tags`: building the Value trees of three generations (delta entries, normalized
  witnesses, payload) for six faces and packing them (~20 us), and re-enumerating the faces,
  wires and edges that `auto_tag_faces` just enumerated (~15 us; OCCT's `BRep_Tool::IsClosed` and
  `BRepTools::OuterWire` per wire are now cached, the rest is entity lookup and tag checks).
  Getting to 60 us means producing the payload straight from the `Witness` structs instead of
  through Values: a rewrite of `autotag.cpp` that must be proven equal on every operator, not
  a representation change.
* **An active recorder** costs 6 KB per box and 112 KB per all-edges fillet, retained by the
  reactive graph itself: `bind_topo_delta` copies every `TopoEntry` (with metadata Values), one
  selection node per picked edge is recorded (12 for a full fillet), parameters are canonicalized
  per node. Packing `TopoEntry::metadata` and recording a multi-pick as one node would cut it
  by about half. Time with a recorder: box +25%, fillet +12%.
* **Peak memory** during a fillet is 311 KB against OCCT's own 248 KB: the transient maps of
  `apply_tracking_tags` (witness lists, `DeltaEntries`) are the 63 KB difference.

## Canonical hashing and geometry-interface bounds (2026-10-22, see PERF.md)

* `canonical_bytes` / `canonical_hash` are byte-identical to `rfc8785` + the SDK validator for everything they
  answer, and answer `None` (the SDK then raises its own error) for everything else.
* The geometry-interface bounds of solids, shells and wires are the union of their faces' / edges' boxes
  (bitwise equal to `AddOptimal` on the whole shape on every arm6 shape); the fingerprint is memoised per OCCT
  shape identity. Neither changes a hash.
