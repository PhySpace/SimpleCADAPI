# Stable geometric references and tag propagation: design and staged plan

Status: design + stage-0/1 spike, 2026-11-04, branch `research/stable-geometry-refs` (cut from `dev` @ `093ef71`).
Builds on `design-docs/topo-naming-research.md` (FreeCAD 1.0 ElementMap, Onshape queries), which is not repeated here.

Legend. **[T]** = verified by a test committed on this branch (file named). **[R]** = verified by reading the code or by
a probe run in this session, no committed test. **[I]** = inference / proposal, not verified.

---

## 0. Summary

1. **A reference is a query over recorded history, not a stored entity.** `ElementRef = {anchor, follow, pick, guard,
   last}`: the anchor names where the entity was *born* (a node that is stable across re-execution, plus a
   deterministic entity key: kernel output role, source sub-shape, or tag); resolution walks the `TopoDelta` every
   later node recorded from OCCT history to the entities of the shape being built. This is Onshape's model
   (`qCreatedBy` + `startTracking`/`makeRobustQuery`, `OK`/`SPLIT`/`FAILED_TO_RESOLVE`) on top of the history
   FreeCAD 1.0 uses (Modified / Generated / IsDeleted), with typed records instead of an encoded name string.
2. **Names are generated in the C++ kernel, per operation, from OCCT history.** That data exists today: every tracked
   operation writes witnesses `{ref, event, parent_refs, origin_role, derivation}` into the node's `TopoDelta`
   **[R]** (`src/cpp/src/semantic/tracking_*.cpp`, `src/cpp/src/reactive/session.cpp` `resolve_recorded_delta`). The
   resolver is C++ too (`scad::reactive::resolve_by_history`, `src/cpp/src/reactive/element_ref.cpp`); Python only
   stores and edits reference records.
3. **Outcome is always one of `ok` / `split` / `merged` / `lost`**, with the entities, the hops that got there, and for
   `lost` the node and the reason (`deleted`, `replaced`, `no_history`, `not_downstream`). Geometry is a *guard* and a
   source of ranked candidates for the editor, never a silent fallback ("first, do no harm").
4. **Tags become a view over references.** A tag is a named `ElementRef`; `ql.tag("x")` resolves the tag's anchor
   through history to the queried shape. The per-op tag projection (with its face-source gate and face-channel gap)
   stops being the long-range identity mechanism.
5. The spike proves the resolver on the four known failures on the real kernel **[T]**
   (`test/test_element_ref_history.py`) and on hand-built graphs for every status **[T]**
   (`src/cpp/tests/cpp/reactive/test_element_ref.cpp`). The audit (section 6) shows where kernel history is
   missing today: `transform_rsolid`, `offset_rsolid`, draft, scale, helical sweep record no delta, and a shell's
   kept faces have no successor witness.

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

### 2.2 Stable node identity [R for the problem, I for the fix]

Node ids are `<cell namespace>_node_<ordinal>`, "the ids count from the cell's code" (`runtime/lineage.py` docstring)
**[R]**. Inserting an operation earlier in the same cell shifts every later ordinal. Onshape solves this with
hierarchical feature ids that must cover a contiguous region of operations. Proposal: the anchor names
`(cell id, op name, occurrence index of that op name in the cell)`; for editor feature cells the feature slug is the
cell id. The resolver maps that to the node of the current run and checks `op` matches. Two cache entries of one cell
share node ids with different contents (`runtime/lineage.py` docstring; the known in-process mis-binding variant),
so a resolve against a restored cell must use the node *object* the value carries
(`shape._get_runtime("graph.node")`, which is what the spike does **[T]**), never a global id lookup.

### 2.3 Why the positional `topo_id` is not a name [R]

`face_face_5` is "kind + the root's own topo id", and the root's topo id is the position in the root's
`TopExp::MapShapes` order (`src/cpp/src/topo/internal.hpp`, `Registry`: "Numbering is by position in the root's own
TopExp::MapShapes order"). It is deterministic for one input, so it is fine *inside one run* (that is what the
resolver uses to step from node to node), but after a parameter change the same index can be another face. It is
the analogue of FreeCAD's `Face12`. It may appear in a stored ref only next to a guard.

### 2.4 Pick-time naming: backward trace [I, stage 1]

When the user picks an entity of node N's output, the SDK walks N's delta *backwards* (entry with `ref` = the pick ->
its `parent_refs` -> the parent node's entry ...) to a root: a node where the entity has a kernel role, or was
`Generated` from a source sub-shape (recurse into the source), or has no parent (a primitive without roles). Each hop
records `{feature, event, piece}` where `piece` is the rank of this entity among the siblings that share its parent
at that hop, sorted by a deterministic key **computed in the kernel** (role, origin role, then a geometric key at
fixed tolerance: centroid lexicographic, area), never OCCT's `Modified()` order. A merge yields several roots;
the record keeps all (it resolves to `merged` if they still meet).

At resolve time the forward walk runs from the root; at a hop where the chain recorded a `piece` and the current
history splits the same way, the piece is chosen by rank with the guard as a check; if the sibling count changed,
the result is `split` with candidates (never a guess).

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
| Shell | shell | removed face -> its rim `modified` (`shell.closing_descendant`); offset faces `generated`; **kept faces: no preserved witness** | opened face: `ok` (the rim); kept face: `lost(replaced)` | **[T]**; fix in 7.2 |
| Rigid copies | translate, rotate, mirror, linear/radial pattern | every face `modified`/continuation; a pattern is one translate/rotate node per instance | `ok`; an instance is addressed by its own node | **[T]** translate, rotate, mirror, linear and radial pattern |
| Affine / offset / draft | transform_rsolid, scale, offset_rsolid, draft, helical sweep | **no delta** | `lost(no_history)`: refuses instead of guessing | **[T]** transform, scale, offset; draft **[R]** probe; helical **[R]** no tracker |
| Identity ops | apply_tag*, make_select_* | no delta; outputs keep the source's topo ids | aliased by topo id (selection: only its `target_kind`) | **[T]** C++ and kernel (fillet through edge selections) |
| Section / split | section, split | not probed | -- | **[I]** |
| Sketch | sketch solve -> wire/face | no deltas on edge/wire/face construction nodes | a profile edge's identity is its sketch geometry id (FreeCAD's `g1;SKT`) | **[I]**, stage 2 |

### 3.1 Tag propagation, production-grade [I]

Today a tag is projected *forward* by every operation through `apply_tracking_tags` with per-channel lineage policies
(`LineagePolicy`, `lineage_policy_allows`) **[R]**, which is where the gates and gaps live. Proposal:

- A tag binding stores an `ElementRef` (anchor at the node where the tag was applied, `follow` and `pick` from the
  tag's lineage policy: `continuation_fragment` ~ identity with `pick: all`, an edge-source tag ~ derived).
- `ql.tag("x")` on shape S = resolve the binding's refs to S's node. Split -> all pieces carry the tag (status kept
  so `.exactly(n)` can explain itself); merged -> the merged face carries it; lost -> the tag is absent and
  `explain_tag` says where it died and why.
- Resolution is lazy (at query time) and memoised per (binding, node): no per-op projection cost, and old tags keep
  working on values restored from the cell cache because the deltas travel with the nodes (2.2, 4.3).
- Stage it behind the existing API: keep the projection for one release, compare both on the test corpus, then make
  the projection a cache of the resolver.

---

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

### 4.2 Editor states [I]

| Status | Badge | Feature behaviour | Editor offers |
|---|---|---|---|
| `ok` | green | runs | -- |
| `merged` | green with note | runs on the merged entity | "now also includes face of <feature>" |
| `split` | amber | runs only if `pick: all` (tags) or a recorded `piece` still resolves; otherwise error | the pieces, highlighted, with "use all / use this one" (writes `pick` back) |
| `lost` | red | the feature fails with `ElementRefLost(lost_at, reason, candidates)` | candidates ranked by guard distance (same kind and geom type first, then normal, area, centroid); accepting one writes a new ref; a unique match within tolerance may be pre-selected but is never applied without the user |

`lost` because of `no_history` is reported differently from `deleted`: the first is a kernel gap ("this operation
does not track faces yet"), the second is a modelling fact ("the cut removed this face").

### 4.3 Persistence

- **Notebook cells.** The editor's `selection_recipe` emits `scad.ref.faces([<ElementRef JSON>...], source={BODY})`
  instead of tag-or-window code; `extract_recipe` round-trips the literal; a repair rewrites the literal and `last`.
  The tag and geometry lines move into `guard` (evidence, not mechanism). [I]
- **Cell cache.** `runtime/lineage.py` saves each cell's nodes with `graph.to_dict()`, which includes `topo_delta`,
  and `OperationGraph.from_value` restores it **[R]** (`graph.cpp` `from_value` parses `topo_delta`; the header
  comment "topology/semantic deltas are not restored" is stale, see SDK_DEFECTS 22). So a reference resolves through
  restored cells as long as the value carries its node object. Pinned by a test in stage 1 [I].
- **Model JSON / packages.** `recording/serializer.py` writes deltas per node already (`"delta"`), so the resolver
  can run on a deserialised graph; refs are data in the feature params. [R for deltas, I for refs]

---

## 5. Versioning [I]

`naming = "scad-naming/<n>"` changes whenever a tracker's witnesses or the resolver's rules change (e.g. the shell fix
in 7.2), plus the OCCT version (history changes between OCCT releases; FreeCAD versions its element map the same
way). On mismatch: resolve anyway, compare against `guard` and `last`; if they agree, rewrite the version silently;
if not, report `lost(version_changed)` with candidates. Refs never need a migration step of their own because they
store anchors and policies, not resolved names.

## 6. Audit: does tag/history propagation work per family today

All rows **[T]** in `test/test_element_ref_history.py` (`test_audit_tag_channels_and_history_per_family` and the
status tests) unless marked; **[R]** cells were seen in a probe run but are not asserted.
Probe: box 40x20x10 with the top face tagged by kwarg (`kw.top`) and by `apply_tag_rselection` (`user.top`).

| Family | plain tag | kwarg tag | history resolver | Missing |
|---|---|---|---|---|
| cut | dies | survives | ok (trimmed top) | plain tag gate |
| cut through the face | dies **[R]** | survives on both pieces **[R]** | **split** (2 pieces) | -- (statuses are new) |
| cut removing the face | dies **[R]** | dies **[R]** | lost(deleted) | -- |
| union (disjoint top) | dies | survives | ok | plain tag gate |
| union (coplanar) | dies **[R]** | survives **[R]** | **merged** | merge not visible to tags |
| intersect | dies | survives | ok | plain tag gate |
| fillet / chamfer | dies | **dies** | ok | face-channel gap in tag projection |
| shell, face kept | dies | dies | **lost(replaced)** | kernel: no preserved witness for kept faces |
| shell, face removed | dies | survives (on the rim) | ok (the rim) | -- |
| translate / rotate / mirror | dies | **dies** | ok | tag projection ignores continuation witnesses |
| linear pattern (instance 3) / radial pattern (instance 2) | dies | dies | ok | same |
| transform_rsolid, scale_rsolid | dies | dies | lost(no_history) | kernel: no tracker |
| offset_rsolid | dies | dies | lost(no_history) | kernel: no tracker |
| draft, helical sweep | -- | -- | no delta **[R]** (draft probe; no `tracked_*` in `semantic/tracking.hpp`) | kernel: no tracker |
| edge -> fillet patch | (edge-source tags survive, playbook) | -- | lost(deleted) identity; the patch in derived mode | -- |
| extrude cap -> fillet | -- | **dies** | ok | face-channel gap |
| extrude / revolve / loft / sweep end cap -> union -> translate | -- | -- | ok (same area) | -- |
| loft sides | -- | -- | not probed; playbook says kernel-matched | section naming |

---

## 7. Staged plan

### Stage 0/1 (this branch, done)
- `scad::reactive::resolve_by_history`, `anchors_for_role`, `subshapes_by_recorded_id` (C++), private bindings
  `_native._resolve_by_history` / `_anchors_for_role` / `_subshapes_by_recorded_id`, Python wrapper
  `simplecadapi.topology.element_ref` (private, not exported). Doctest: 6 cases over hand-built graphs. Pytest:
  known failures, statuses, parameter sweep, creator caps, audit (30 tests, `test/test_element_ref_history.py`).

### Stage 1: names and pick-time trace (next)
1. Backward trace (2.4) in C++: `name_of(node, entity) -> ElementRef` with deterministic sibling ranks computed in
   the tracker (add a `piece` rank to witnesses that share a parent, sorted by a kernel geometric key).
2. Stable node identity (2.2): `(cell, op, occurrence)` <-> node id map kept by the session; anchor check of `op`.
3. Cache test: a reference resolved through a cell restored from the cache equals the live one.
4. Kernel gaps, in order of user impact: `transform_rsolid` (GTransform has `Modified`), shell kept faces (see
   7.2), offset, draft, scale, helical sweep. Each with a doctest and an audit row flipped.

### Stage 2: SDK and editor
5. Public `scad.ref` API (`faces`/`edges`, `ElementRefLost` with candidates), docstrings/modules.json/serializer
   row/API page per the SDK checklist.
6. Editor: `selection_recipe` emits refs; reference health badges (4.2); "use all / this piece / candidate" actions
   writing the ref back; ws message for statuses.
7. Sketch roots: sketch geometry ids as anchors for profile edges, so side faces are named by sketch entities.

### Stage 3: tags as a view
8. Tag bindings hold refs; `ql.tag` resolves lazily with memoisation; projection kept as a cache and compared on the
   corpus; then retire the gates.
9. Corpus: parameter sweeps of the examples (insert a feature mid-cell, change widths, add an upstream fillet),
   asserting zero wrong picks and the resolved-by-history rate.

### 7.1 Performance budget
Measured **[R]** (ad-hoc probe, Release build, Apple silicon; one top face of a 400x20x10 plate through N
successive hole cuts; the resolved face area matched 8000 - N*pi/4 at every N):

| N cuts | model build | resolve (C++ walk) | resolve + face lookup |
|---|---|---|---|
| 10 | 0.08 s | 0.08 ms | 0.10 ms |
| 50 | 0.65 s | 0.56 ms | 0.59 ms |
| 150 | 4.75 s | 3.0 ms | 3.1 ms |

The cost is the scan of each consuming node's delta, whose size grows with the model (O(N) entries per cut, so
O(N^2) overall). Stage 1: a per-node index parent -> entries, built once per node and memoised, makes a resolve
O(hops). Budget [I]: < 1 ms per reference for 200-node histories, memoised per (ref, target node), nothing added at
recording time (the deltas are recorded already). Resolution is already negligible next to modelling (0.06 % of
build time at N = 150).

### 7.2 The shell kept-face gap needs an owner decision
`query_history` (`src/cpp/src/semantic/tracking_core.cpp`) emits `preserved` only when an input has neither
`Modified` nor `Generated` images. A shell's kept outer face is unchanged *and* generates its offset face, so it gets
only the `generated` witness. Emitting `preserved` as well when the input is still in the result is a one-line fix,
but it changes the Python-parity goldens (`tests/cpp/semantic/test_tracking_golden.cpp`: extrude/revolve profile
edges, shell, loft/sweep) and an explicit assertion (`test_tracking_behaviour.cpp:386`,
`count_role(.., "shell.body_face") == 0`) **[R]** (tried and reverted on this branch). Options: (a) accept the new
witnesses and regenerate goldens (changes tag projection: profile edges and kept shell faces gain continuation), or
(b) add a separate `survivors` list to `TopoDelta` read only by the resolver (no projection change).

## 8. Risks and non-goals
- OCCT history quality bounds everything; a tracker that omits a witness makes a reference `lost`, which is the
  right failure but a regression in perceived robustness until the gaps in section 6 are closed.
- `generated` follow mode can fan out (an edge generates faces and vertices); the record keeps `kind` so the SDK
  filters.
- Not addressed: assemblies (references across part instances), drawings, imported STEP bodies (no history: anchors
  there are geometric only, guard-only refs with `lost` on any change).
