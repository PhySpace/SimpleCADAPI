# Stable geometric references and tag propagation: design and staged plan

Status: design + stage-0/1 spike, 2026-11-04, branch `research/stable-geometry-refs` (cut from `dev` @ `093ef71`).
Builds on `design-docs/topo-naming-research.md` (FreeCAD 1.0 ElementMap, Onshape queries), which is not repeated here.

Legend. **[T]** = verified by a test committed on this branch (file named). **[R]** = verified by reading the code or by
a probe run in this session, no committed test. **[I]** = inference / proposal, not verified.

---

## 0. Summary

1. **A reference is a query over recorded history, not a stored entity.** The anchor names where the entity was
   *born* (a stable node key: feature, op, occurrence among ancestors, plus a kernel role or topo id); resolution
   walks the `TopoDelta` every later node recorded from OCCT history to the entities of the shape being built.
   Onshape's model (`qCreatedBy` + `startTracking`, `OK`/`SPLIT`/`FAILED_TO_RESOLVE`) on FreeCAD 1.0's history
   (Modified / Generated / IsDeleted), with typed records instead of an encoded name string. **[T]**
2. **Names are generated in the C++ kernel, per operation, from OCCT history** (`semantic/tracking_*.cpp`); the
   resolver, the stable keys, the backward trace and the tag view are C++ too (`reactive/element_ref.cpp`,
   `reactive/tag_view.cpp`). Python only stores references (`simplecadapi.topology.element_ref`). **[T]**
3. **Outcome is always `ok` / `split` / `merged` / `lost`**, with entities, hops, bodies, and for `lost` the node and
   reason. A split is an error carrying the candidates (owner decision); a lost reference offers guard-ranked
   look-alikes; nothing is chosen silently. **[T]**
4. **Tags are a view over the recorded history** (owner decision, switched directly): a tag assignment is a graph
   node, and `ql.tag` sees every entity its targets became. Plain and op-kwarg face tags now survive every operation
   family with history. **[T]**
5. **Every solid modelling op records history now:** `transform_rsolid`, `scale_rsolid`, `offset_rsolid` and
   `draft_rsolid` gained it; a shell's kept faces are preserved (option a); N-ary booleans compose their steps.
   **[T]**
6. Persistence: tags and references resolve on values restored from the cell cache (nodes and deltas travel in the
   lineage records) and after pickling **[T]**; references carry a naming version **[T]**.

---

## 1. Why tags-then-geometry is not enough (what the probes showed)

| Channel today | Survives boolean | Survives fillet/chamfer | Survives translate/mirror/pattern | Evidence |
|---|---|---|---|---|
| plain `apply_tag_rselection` face tag | no | no | no | **[T]** audit, `user.top` = 0 everywhere |
| op-kwarg face tag (`top_face_tag=`) | yes | **no** | **no** | **[T]** audit, `kw.top`: cut/union/intersect 1, fillet/chamfer/translate/mirror/pattern 0 |
| editor recipe: tag if count matches, else a geometric window `.exactly(n)` | -- | -- | -- | **[R]** `feat/gui-modeling:src/simplecadapi/editor/features.py` `selection_recipe` |

The geometric window is the dangerous part: after an upstream edit it can match a *different* face of the same size
and position class and the feature proceeds. The history resolver has none of these gaps where the kernel records
history: the same top face resolves after cut, union, intersect, fillet, chamfer, translate, mirror and pattern
**[T]**, including the cases where both tag channels are dead.

Note the surprise in the table: the op-kwarg tag dies at `translate_shape`/`mirror_shape`/patterns even though these
record a `Modified`/continuation witness for every face **[T]**. The data is there; the projection drops it.

---

## 2. The reference format

### 2.1 Record (JSON, versioned) [I]

```jsonc
{
  "v": 1,                                // record version
  "naming": "scad-naming/1",             // resolver + tracker algorithm version (section 5)
  "anchor": {
    "feature": "cell:3f9a/extrude#1",    // stable node identity (2.2), not the raw node id
    "op": "make_extrude_rsolid",          // checked on resolve: a different op at that id = lost/anchor_mismatch
    "slot": 0,
    "entity": {"kind": "face", "by": "role", "role": "extrusion.end", "ordinal": 0}
    //  or {"by": "source", "source": <ElementRef of the profile edge>, "event": "generated"}
    //  or {"by": "tag", "tag": "mount.face"}
    //  or {"by": "topo", "topo_id": "face_face_5"}        // positional: only valid with a matching guard
  },
  "chain": [ {"feature": "cell:7c21/cut#1", "event": "modified", "piece": {"rank": 0, "of": 2}} ],
  "follow": "identity",                  // or "derived" (edge -> its fillet patch, Onshape startTracking)
  "pick": "fail",                        // split policy: "fail" | "all" | "piece" (use chain[].piece)
  "guard": {"kind": "face", "geom_type": "PLANE", "area": 771.73, "center": [0, 0, 10], "normal": [0, 0, 1]},
  "last": {"node_id": "c3_node_00000007", "targets": ["face_face_2"], "status": "ok"}  // FreeCAD ShadowSub: cache only
}
```

- `anchor.entity.by` priority, most to least stable: **role** (kernel output roles are deterministic per op:
  `extrusion.end`, `box.top`, `fillet.patch`, `shell.offset_face` **[R]**), **source** (a side face is the
  `Generated` image of a profile edge, itself an `ElementRef` into the sketch; this is FreeCAD's `g1;SKT` root),
  **tag** (a user name, itself stored as an `ElementRef`), **topo** (positional index; see 2.3).
- `chain` is what the backward trace saw at pick time (2.4). It is not needed to resolve a reference whose anchor
  is unambiguous, only to say *which piece* when the entity was already split when it was picked.
- `guard` is never used to choose between history results except inside one split (2.4) and to rank candidates for
  a lost reference (4.2).

### 2.2 Stable node identity (owner decision; implemented) [T]

Node ids are `<cell namespace>_node_<counter>`, "the ids count from the cell's code" (`runtime/lineage.py`)
**[R]**, so an operation inserted earlier in the cell shifts every later id, and a stored id then names *another*
operation: `test_an_operation_inserted_earlier_in_the_cell_does_not_shift_a_stable_anchor` shows the raw anchor
resolving to the wrong face (the inserted stand's top) after such an edit **[T]**.

A stable anchor names the node by **(feature, op, occurrence)** (`StableNodeKey`, `element_ref.hpp`):

- `feature` = the graph namespace of the node, i.e. the cell key (the editor's feature slug for a feature cell);
- `op` = the op name;
- `occurrence` = how many nodes of the same feature and op are **ancestors of this node** (upstream of it in the
  graph), not how many were recorded before it.

Why ancestry and not recording order (the "even more stable" choice): with recording order, *any* same-op
operation inserted earlier in the cell shifts the anchor, including one that has nothing to do with the referenced
body (a second sketch, a fixture box). Counting ancestors only, an inserted operation shifts the anchor only when
it is the same op **and** feeds the anchored node itself, which is the case where the person really changed what
the anchor is built from. Ops of another kind never shift it. **[T]** (doctest "a stable anchor names the node by
feature, op and occurrence upstream of it"; pytest insertion, parameter-edit and ambiguity tests).

Two nodes can then share a key without either feeding the other (two primitive boxes of one cell). The key carries
the digest of the node's own parameters (refs, picks and node ids left out) as a tie-break: the candidate with
unchanged parameters wins; when none or several match, the reference is `lost(anchor_ambiguous)`, never a guess
**[T]**. (A parameter edit of one of two same-key siblings is the one case that needs the person.)

The entity inside the node is named by its **kernel role** (the most specific role: fewest entities, then name)
plus an ordinal among the node's entities with that role; by the positional topo id only when it has no role.
Multi-entity roles (`extrusion.side`) are ordinal-positional until sketch geometry ids name profile edges (stage 2).

A resolve against a restored cell uses the node *object* the value carries (`shape._get_runtime("graph.node")`),
never a global id lookup, so the cache mis-binding variant (two cache entries of one cell share node ids) cannot
redirect it **[T]** for live values, **[I]** for restored ones (stage: cache test).

### 2.3 Why the positional `topo_id` is not a name [R]

`face_face_5` is "kind + the root's own topo id", and the root's topo id is the position in the root's
`TopExp::MapShapes` order (`src/cpp/src/topo/internal.hpp`, `Registry`: "Numbering is by position in the root's own
TopExp::MapShapes order"). It is deterministic for one input, so it is fine *inside one run* (that is what the
resolver uses to step from node to node), but after a parameter change the same index can be another face. It is
the analogue of FreeCAD's `Face12`. It may appear in a stored ref only next to a guard.

### 2.4 Pick-time naming: backward trace (implemented) [T]

`trace_to_birth` (C++): from the picked entity, follow its single same-kind parent back through every node that
only preserved or modified it (a selection is crossed to its source), stopping at a creator, at the node that
generated it, at a merge (several parents), or at a split (the parent has several same-kind successors: the piece
is named at the node that made it). `stable_anchor_of(face, part)` on the finished part therefore anchors at
`make_box_rsolid` / `box.top`, not at the fillet that last touched the face **[T]**.

A piece of a face that was already split when it was picked is anchored at the splitting node by its topo id
(positional). Naming pieces by a kernel-computed geometric rank among siblings is stage 2.

---

## 3. Where names come from: per operation family

The kernel records one `TopoDelta` per node: witnesses with event `preserved`/`modified`/`generated`/`deleted`,
`parent_refs` naming input entities by the node that made them (a tag node keeps the producer as topology owner,
`keep_topology_owner` **[R]**), `origin_role` (`body`/`tool`/`contour_edge`/`profile`...), `derivation`
(`continuation`/`fragment`/`boundary`/`replacement`), and kernel roles. The resolver follows `preserved` and
`modified` of the anchor's kind (identity mode) or also `generated` and kind changes (derived mode).

| Family | Ops | What the delta says (today) | Resolver behaviour | Status |
|---|---|---|---|---|
| Primitives | box, cylinder, cone, sphere | roles only (`box.top`, `cylinder.side`, ...) | anchors by role | **[T]** box top anchor; roles **[R]** |
| Extrude-like creators | extrude, revolve, sweep, loft, twisted sweep | roles (`extrusion.*`, `revolution.*`, `loft.*`, `sweep.*` start/end/side); side faces `Generated` from profile edges | anchor by role; sides by source edge (derived) | **[T]** end caps of all four through a union and a translate, extrude cap through a fillet; loft side correspondence is kernel-matched, not named **[R]** (playbook) |
| Booleans | cut, union, intersect, boolean list | `modified` fragments, `preserved`, `deleted`; merged faces get one entry per parent | `ok` / `split` (several fragments) / `merged` (fragment also descends from a foreign face) / `lost(deleted)` | **[T]** all four outcomes |
| Blends | fillet, chamfer | trimmed faces `modified`; blended edges `deleted` + patch `generated` (role `fillet.patch`) | face: `ok`; edge: `lost(deleted)` in identity, patch in derived | **[T]** face and edge->patch |
| Shell | shell | removed face -> its rim `modified` (`shell.closing_descendant`); offset faces `generated`; kept faces `preserved` (+ their offset face generated) | opened face: `ok` (the rim); kept face: `ok` | **[T]** (kept faces fixed, 7.2) |
| Rigid copies | translate, rotate, mirror, linear/radial pattern | every face `modified`/continuation; a pattern is one translate/rotate node per instance | `ok`; an instance is addressed by its own node | **[T]** translate, rotate, mirror, linear and radial pattern |
| Affine / offset / draft | transform_rsolid (rigid and affine), scale (uniform and per axis), offset_rsolid, draft | face and edge witnesses from the retained OCCT history (`modification_delta`): `modified`/continuation; an offset or drafted face (OCCT: generated) continues its source face | `ok` | **[T]** every op, `test_history_through_operations_that_had_none`, the draft test, `test_modification_delta.cpp` (was `no delta` before this branch) |
| Helical sweep | helical_sweep_rsolid | in a session it records helix + face + sweep nodes; the sweep is tracked | anchor by `sweep.*` roles | **[T]** |
| Identity ops | apply_tag*, make_select_* | no delta; outputs keep the source's topo ids | aliased by topo id (selection: only its `target_kind`) | **[T]** C++ and kernel (fillet through edge selections) |
| Section / split | section, split | not probed | -- | **[I]** |
| Sketch | sketch solve -> wire/face | no deltas on edge/wire/face construction nodes | a profile edge's identity is its sketch geometry id (FreeCAD's `g1;SKT`) | **[I]**, stage 2 |

### 3.1 Tags are a view over recorded history (owner decision: switch directly)

**Model.** A tag assignment is already a graph node: `apply_tag_rselection` and every op-kwarg tag
(`top_face_tag=`) record an `apply_tag_*` node whose `tag_binding` parameter holds the binding and its target
anchors (`explicit_refs`, or `selection_query` with `evidence.selected_refs`) **[R]**. So a tag needs no copy on
every later shape: the tags of an entity of node N's output are *computed* from N's upstream graph:

```
tags(N, e) = own bindings of e (the op's kernel roles; bindings set on N's own output)
           + every binding B of a tag node upstream of N whose anchors reach e through the deltas,
             step by step, as B's lineage policy allows
```

Per step (node M with a delta, for every witness whose parent carries B):

| witness | carried when |
|---|---|
| `preserved` / `modified`, same kind | `lineage_policy_allows(B, derivation)`: continuation (`continuation`), continuation + fragment (`continuation_fragment`, the default: a split face tags *all* its pieces), explicit list |
| `generated` | never by continuation: a face a feature generates from a tagged source (fillet / chamfer patch from its edge, extrude / loft side from its profile edge) is *named* by that operation after its source when it runs (the projected binding, `semantic/autotag.cpp`), an op-local fact like a kernel role |
| `deleted`, not mentioned, or a node without history | not carried: the tag ends there, and `explain_tag` says where |

Identity ops (tag assignments, selections) pass everything on under their own node. The view is computed
**incrementally per node** from its inputs' views and its own delta (O(delta entries) per node), memoised per node
object (nodes are immutable), so a query costs a lookup after the first one. It lives in the C++ kernel
(`scad::reactive` tag view, `src/cpp/src/reactive/tag_view.cpp`) and is installed as the topo layer's
history-witness provider, so `Shape::has_tag` / `list_tags` / `list_tag_bindings` / `explain_tag` and therefore
every `ql.tag(...)` call site see it without any API change **[T]** (`test_tag_view.cpp`, the audit).

**One path per binding, chosen by where the binding lives.** A binding a *recorded* tag assignment made
(producer `user_operation` with a node id, on a value that is part of a recorded graph) is carried only by the view:
the per-operation copy (`carry_source_lineage`, `project_source_bindings` in `semantic/autotag.cpp`) skips it. What
only the shapes know keeps the copy: imported sidecar facts (`provenance.*` of a `.scadbrep`), sketch topology names,
tags assigned outside a session, values replayed without a recording session, and the projected names above. There
is no binding that both paths carry, so nothing is duplicated, and no compatibility switch. **[T]** (full suite: the
brep provenance, sketch exact-source-identity and replayed-connector tests exercise the shape path.)

**Scopes.** `local` = bindings stored on the entity; `inherited` = from containing entities (downward
propagation); `lineage` = the history view; `effective` (the default of `ql.tag`) = local + inherited + lineage.
This is the visible change: a plain user face tag now survives booleans, blends, shells, copies and patterns
(it used to stop at the face-source gate), and an op-kwarg tag survives fillets and copies.

**Persistence and versioning.** The tag lives in its graph node, so it travels with the cell cache (the lineage
record of a cell holds its nodes, deltas and `tag_binding` params) and with model JSON; nothing is pickled on
shapes. The binding has its schema version; the view algorithm is versioned with the naming version (section 5).

**Bodies.** A view entry is keyed by (output slot, kind, topo id) of the node's output, so a multi-body node
(several slots, or one compound of bodies) keeps the body apart; references report which body (slot / solid) each
target lies in.

### 3.2 Target API: queries, references, tags (production-grade)

```python
# selection: a query is data (serialisable), resolution is explicit, cardinality is asserted
q = ql.faces().where(ql.tag("mount.face"))           # tags through history (3.1)
faces = q.exactly(2).resolve(part)                   # error lists per-predicate counts and near misses
report = q.explain(part)                             # the same, as data: counts per predicate, candidates

# references: stable anchors resolved through history (section 2, 4)
ref = scad.ref.of(face, part)                        # ElementRef: stable anchor + guard, JSON
ref.resolve(part)  -> Resolution(status, entities, candidates, lost_at, reason, hops, bodies)
ref.one(part) / ref.all(part)                        # ElementRefError(status, candidates) unless exactly one / ok
ql.faces().where(ql.ref(ref))                        # a reference as a predicate

# tags: names over references
scad.apply_tag_rselection(part, faces, "mount.face") # unchanged; recorded as a tag node
scad.explain_tag(face, "mount.face")                 # binding, anchors, hops, where it stopped and why
ql.tag("mount.face", follow="derived")               # also generated descendants (edge tag -> its patch)
ql.faces().where(ql.body("left"))                    # with research/multi-solid: per-body scoping
```

Stages: the view and the scopes (3.1) and the resolver (`simplecadapi.topology.element_ref`: `resolve`,
`require`, `stable_anchor_of`, `guard_of`) are on this branch; `scad.ref` as a public module, `ql.ref`,
`ql.body`, `Query.explain` follow (section 7).

## 4. Resolution, failure statuses, and what the editor shows

### 4.1 Algorithm (implemented, `element_ref.cpp`) [T]

1. Take the target node's upstream closure (inputs first; works for a value restored without its session).
2. Seed the lineage with the anchor. For each later node that consumes a lineage member (a member is an entity of
   one of the node's inputs):
   - identity op (tag, selection) without history: alias the members under the node (same topo id);
   - op without history: the member dies, reason `no_history`;
   - otherwise: every witness whose `parent_refs` meet the consumed members continues the lineage (identity mode:
     same kind, not `generated`); a `deleted` witness ends it (`deleted`); a member mentioned only by `generated`
     witnesses ends it (`replaced`); a member not mentioned at all ends it (`no_history`, a coverage gap). A
     successor that also descends from a same-kind entity outside the lineage marks the hop `merged`.
3. Targets = lineage members of the target node's slot. Only hops on the way to the targets are reported (a branch
   that leads elsewhere is not this reference's history).
4. Status: none -> `lost` (latest death: node + reason); several -> `split`; one with a merged hop -> `merged`;
   else `ok`.

### 4.2 Editor states and the split rule (owner decision; implemented in the spike API) [T]

A reference that splits is an **error the person resolves**, never "all pieces": `element_ref.require(anchor,
shape)` raises `ElementRefError(status="split", candidates=[...])`; the candidates are in a geometric order (centre,
then size), not OCCT's numbering; `require(..., piece=i)` is how the editor applies the person's choice, and the
choice is written back into the reference. `ResolvedRef.describe()` is the editor payload: status, `lost_at`,
reason, candidates (`topo_id`, kind, geometry type, centre, size, score). A lost reference with a `guard`
(`guard_of(entity)` at pick time) carries up to five look-alikes ranked by guard distance; they are offered,
never applied **[T]**. (A boolean that leaves a *body* in several pieces is not an error: that is a body split,
which the multi-body work turns into several bodies; only a *reference* that no longer names one entity is.)

| Status | Badge | Feature behaviour | Editor offers |
|---|---|---|---|
| `ok` | green | runs | -- |
| `merged` | green with note | runs on the merged entity | "now also includes face of <feature>" |
| `split` | amber | fails with the candidates | the pieces, highlighted; picking one writes `piece` |
| `lost` | red | fails with `lost_at`, reason, look-alikes | accept a look-alike (writes a new anchor) or re-pick |

`lost` because of `no_history` is reported differently from `deleted`: the first is a kernel gap, the second a
modelling fact. `anchor_missing` / `anchor_ambiguous` mean the anchored node itself is gone or not unique (2.2).

### 4.3 Persistence

- **Notebook cells.** The editor's `selection_recipe` emits `scad.ref.faces([<ElementRef JSON>...], source={BODY})`
  instead of tag-or-window code; `extract_recipe` round-trips the literal; a repair rewrites the literal and `last`.
  The tag and geometry lines move into `guard` (evidence, not mechanism). [I]
- **Cell cache.** `runtime/lineage.py` saves each cell's nodes with `graph.to_dict()`, which includes `topo_delta`,
  and `OperationGraph.from_value` restores it **[R]** (`graph.cpp` `from_value` parses `topo_delta`; the header
  comment "topology/semantic deltas are not restored" is stale, see SDK_DEFECTS 22). So a reference resolves through
  restored cells as long as the value carries its node object **[T]** (`test_tags_and_references_resolve_on_values_restored_from_the_cell_cache`, fresh process).
- **Model JSON / packages.** `recording/serializer.py` writes deltas per node already (`"delta"`), so the resolver
  can run on a deserialised graph; refs are data in the feature params. [R for deltas, I for refs]

---

## 5. Versioning (implemented in the spike) [T]

`kNamingVersion = "scad-naming/1"` (`element_ref.hpp`, `element_ref.NAMING_VERSION`) is stamped into every stable
anchor. It changes whenever a tracker's witnesses or the resolver's rules change (the shell fix of 7.2 would have
been a bump had references been persisted before it), and should be combined with the OCCT version when OCCT is
upgraded (FreeCAD versions its element map the same way). A reference made under another version is still resolved,
and the result says `version_changed`; the caller (editor) compares it against its guard: agreement rewrites the
version silently, disagreement shows the reference as `lost(version_changed)` with candidates [I]. References need no
migration of their own because they store anchors and policies, not resolved names. Tags need none either: they are
recomputed from the graph on every read.

## 6. Audit: tag and history propagation per family (before -> now)

All rows **[T]** in `test/test_element_ref_history.py` (`test_audit_tag_channels_and_history_per_family` and the
status tests) unless marked; **[R]** = seen in a probe, not asserted. Probe: box 40x20x10 with the top face tagged
by kwarg (`kw.top`) and by `apply_tag_rselection` (`user.top`). "Before" is `dev` @ `093ef71`.

| Family | plain tag before -> now | kwarg tag before -> now | history resolver before -> now |
|---|---|---|---|
| cut | dies -> survives | survives -> survives | ok |
| cut through the face | dies -> both pieces **[R]** | both pieces **[R]** | split (2 pieces) |
| cut removing the face | dies | dies | lost(deleted) |
| N-ary cut (3 tools) | dies -> both pieces | -- | lost(replaced) -> split (composed steps, 7) |
| union (disjoint / coplanar) | dies -> survives | survives | ok / merged |
| intersect | dies -> survives | survives | ok |
| fillet / chamfer | dies -> survives | dies -> survives | ok |
| shell, face kept | dies -> survives | dies -> survives | lost(replaced) -> ok (7.2) |
| shell, face removed | dies -> survives (the rim) | survives | ok (the rim) |
| translate / rotate / mirror | dies -> survives | dies -> survives | ok |
| linear / radial pattern instance | dies -> survives | dies -> survives | ok |
| transform_rsolid, scale_rsolid, offset_rsolid | dies -> survives | dies -> survives | lost(no_history) -> ok |
| draft | -- | -- | lost(no_history) -> ok (drafted face and neighbours) |
| helical sweep | -- | -- | ok through its sweep node (never a gap) |
| edge -> fillet patch | the fillet names the patch after the edge (projection, unchanged) | -- | lost(deleted) identity; the patch in derived mode |
| extrude cap -> fillet | -- | dies -> survives | ok |
| creator end caps (extrude / revolve / loft / sweep) -> union -> translate | -- | -- | ok |
| tag after pickling the value | -- | -- | survives (`test_a_tag_survives_pickling_with_its_history`) |
| loft sides | -- | -- | not probed; kernel-matched (section naming, stage 2) |

---

## 7. Staged plan

### Done on this branch
- Resolver (`resolve_by_history`), role anchors, recorded-id lookup; statuses ok / split / merged / lost.
- History for transform / scale / offset / draft (`modification_delta`); shell kept faces preserved (7.2); N-ary
  boolean steps composed (`merge_topo_deltas`).
- Stable anchors (feature, op, occurrence-among-ancestors, params tie-break, role) and the backward trace to birth.
- Splits as errors with candidates; lost references with guard-ranked look-alikes; bodies; naming version.
- Tags as a view over history (3.1), effective includes lineage, one path per binding.
- Tests: `test/test_element_ref_history.py` (48), `test_element_ref.cpp`, `test_tag_view.cpp`,
  `test_modification_delta.cpp`; goldens reviewed one by one (commits `df38241`, `facccaa`).

### Next
1. Public `scad.ref` (`of`, `resolve`, `one`, `all`) and `ql.ref(ref)` as a predicate, with the SDK checklist
   (docstrings, modules.json, serializer row, API page); `ElementRefError` exported.
2. Editor (`feat/gui-modeling`): `selection_recipe` emits `scad.ref.faces([...])` instead of tag-or-window code;
   health badges and "this piece / this candidate" actions write the reference back (4.2).
3. Sketch roots: sketch geometry ids as anchors for profile edges, so side faces have names that survive profile
   edits; a kernel-computed geometric rank for pieces of a split (2.4).
4. Per-node parent index for the resolver (7.1); `Query.explain(shape)` as data (the cardinality errors already
   carry the per-predicate counts and near-miss inventory).
5. Multi-body (`research/multi-solid`): `ql.body(name)` once named bodies land; references already resolve per
   output slot and report the body index inside a compound.
6. Corpus: parameter sweeps of the examples (insert a feature mid-cell, change widths, add an upstream fillet),
   asserting zero wrong picks.

### 7.1 Performance budget
Measured **[R]** (ad-hoc probe, Release build, Apple silicon; one top face of a 400x20x10 plate through N
successive hole cuts; the resolved face area matched 8000 - N*pi/4 at every N):

| N cuts | model build | resolve (C++ walk) | resolve + face lookup |
|---|---|---|---|
| 10 | 0.08 s | 0.08 ms | 0.10 ms |
| 50 | 0.65 s | 0.56 ms | 0.59 ms |
| 150 | 4.75 s | 3.0 ms | 3.1 ms |

The cost is the scan of each consuming node's delta, whose size grows with the model (O(N) entries per cut, so
O(N^2) overall). Next: a per-node index parent -> entries, built once per node and memoised, makes a resolve
O(hops). Budget [I]: < 1 ms per reference for 200-node histories, memoised per (ref, target node), nothing added at
recording time (the deltas are recorded already). Resolution is already negligible next to modelling (0.06 % of
build time at N = 150).

### 7.2 The shell kept-face gap: option (a), implemented [T]

`query_history` (`src/cpp/src/semantic/tracking_core.cpp`) emitted `preserved` only when an input had neither
`Modified` nor `Generated` images, so a shell's kept outer face (unchanged *and* the seed of its offset face) had
only the `generated` witness. It now also emits `preserved` when the input is still in the result. Every changed
expectation was reviewed:

| Expectation | Before | After | Why |
|---|---|---|---|
| golden `shell` (C++ tracking) | 0 preserved | 5 kept faces + 4 rim edges preserved, 5 `shell.body_face` roles | the kept faces and the outer rim edges are IsSame in the result |
| golden `extrude_rect`, `extrude_circle`, `loft`, `loft_ruled` | profile edges: generated only | also preserved | the start cap of a prism / loft is bounded by the very profile edges |
| `test_tracking_behaviour.cpp` loft toward a point | 4 entries | 8 | the four base edges stay as the cap boundary |
| `test_tracking_behaviour.cpp` shell roles | `shell.body_face == 0` ("every kept face was re-created": wrong) | 5 | as above |
| goldens `ops_features_shell`, `ops_features_tag_projection` (Python port) | kept faces untagged | `face.shell.body_face` on the 5 kept faces | the role is now proven |
| golden `ops_features_blend_failures.shell_role` | "requires at least one kernel-proven result" | no failure | same |
| `test_operation_output_roles` | asserted `body_faces_tag` raised | asserts it tags the 5 kept faces | same |
| audit `shell_kept_face` | lost(replaced) | ok; the kwarg tag now survives too | same |

## 8. Risks and non-goals
- OCCT history quality bounds everything; a tracker that omits a witness makes a reference `lost`, which is the
  right failure but a regression in perceived robustness until the gaps in section 6 are closed.
- `generated` follow mode can fan out (an edge generates faces and vertices); the record keeps `kind` so the SDK
  filters.
- Not addressed: assemblies (references across part instances), drawings, imported STEP bodies (no history: anchors
  there are geometric only, guard-only refs with `lost` on any change).
