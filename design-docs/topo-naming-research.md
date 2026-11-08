# Topological naming: how FreeCAD does it, and what SimpleCADAPI should do

Status: research note, 2026-11-04. Nothing here is implemented.

Legend. **[V]** = verified by reading the cited source in this session (ego-browser; GitHub raw files fetched from
FreeCAD `main`, wiki pages). **[I]** = inference or recollection, not verified from a source here. Line numbers refer
to the `main` branch as fetched today and will drift.

## 1. The problem

A parametric feature (fillet, sketch-on-face, hole) must say "this face/edge of the upstream body". Kernels expose
sub-shapes only by traversal order or geometry. When an upstream parameter or operation changes, traversal order
reshuffles and geometry moves, so "Face13" or "the face with centroid near (0,0,10)" may now denote a different face,
or none. A stable reference needs an identity for each sub-shape that is (a) derived from the modelling history, not
from position, and (b) re-resolved after every rebuild, with an explicit outcome when the identity is gone.

## 2. How FreeCAD 1.0 does it

### 2.1 Provenance and status

- The algorithm is realthunder's, developed in his Link/LinkStage3 fork; it was integrated into FreeCAD 1.0 over about
  a year (release notes: "Realthunder's algorithm has been carefully implemented... The TNP problem is not completely
  solved") [V]. Sources:
  - Release notes 1.0: https://wiki.freecad.org/Release_notes_1.0 (PR #13705 listed as the finalizing PR).
  - Wiki page: https://wiki.freecad.org/Topological_naming_problem. It states the algorithm has three purposes, in
    order: (1) detect and display broken references, (2) propose a likely fix (e.g. fillet/chamfer edge selection),
    (3) auto-repair only when confident ("First, do no harm") [V]. It explicitly says the algorithm "is not intended
    to fix every failure"; datum planes and body-origin-based sketches remain best practice [V].
  - realthunder's design notes: https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming (framework,
    tags, hasher, versioning) and https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming-Algorithm
    (the naming algorithm with pseudo-code) [V].

### 2.2 Data structures [V]

- `Data::IndexedName` = type + index (`Face12`). `Data::MappedName` = a byte string (the stable name). Source:
  https://github.com/FreeCAD/FreeCAD/blob/main/src/App/MappedName.h and
  https://github.com/FreeCAD/FreeCAD/blob/main/src/App/IndexedName.h
- `Data::ElementMap` (https://github.com/FreeCAD/FreeCAD/blob/main/src/App/ElementMap.h): a bidirectional map
  MappedName <-> IndexedName, owned by `Data::ComplexGeoData` (base of `Part::TopoShape`). Documented as
  `indexedNames` (type -> queue of children) plus `mappedNames` (name -> IndexedName); children can carry a recursive
  child map (for compounds). `find(MappedName)`, `find(IndexedName)`, `findAll(IndexedName)` exist; one element can
  have several names, a name maps to exactly one element (realthunder notes, "setElementName").
- `Part::TopoShape` additionally carries an integer `Tag` identifying the owner document object (unique per document,
  not a UUID). Tag 0 disables automatic mapping [V, realthunder notes "Object Identification"]. The tag is appended to
  names whose source comes from a different shape so that two operands do not collide.
- `App::StringHasher` (per document): long names are replaced by `#<hex id>`, with the original strings stored in a
  reference-counted table and persisted with the document; only strings actually used are saved by default [V,
  realthunder notes "String Hasher"].
- Element map version string, `GeoFeature::getElementMapVersion()`: concatenates the TopoShape algorithm version, OCCT
  version, ComplexGeoData version and hasher threshold. On document load, a mismatch marks the feature for recompute
  and resets link shadow copies, because any change in OCCT history behaviour changes generated names [V, realthunder
  notes "Element Map Versioning"; `GeoFeature.cpp` line ~264 reads the version].

### 2.3 How names are generated per operation [V]

All "make element" operations in
https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Part/App/TopoShapeExpansion.cpp
(`makeElementBoolean` ~l.6069, `makeElementFillet` ~l.4148, `makeElementChamfer` ~l.4180, `makeElementPrism` ~l.4644,
`makeElementPrismUntil`, `makeElementShape`, loft/pipe/offset variants, `makeShapeWithElementMap` ~l.1420) build the
result with an OCCT `BRepBuilderAPI_MakeShape` derivative (or `BRepAlgoAPI_*` / `BRepTools_History`) and then hand
it to `TopoShape::makeShapeWithElementMap(shape, mapper, inputShapes, op)`. The `Mapper` abstraction (`MapperMaker`
at ~l.5745-5840) forwards to the OCCT history calls `Modified(s)`, `Generated(s)`, and for histories also
`IsDeleted`, each wrapped in try/catch because "OCCT being OCCT" not all makers honour the interface.
`BRepBuilderAPI_Sewing` and `BRepOffsetAPI_ThruSections` need special handling (algorithm page).

The core algorithm (algorithm page, `makESHAPE` in the pseudo-code), four passes:

1. Unchanged elements: copy the input names onto the identical sub-shapes of the result (`mapSubElement`).
2. Modified / Generated: for each input vertex, edge, face, ask the mapper for `Modified` and `Generated` new
   sub-shapes; each new element gets a name built from the source's mapped name plus a marker, an op code, the source
   tag and the source name length. If several sources map to one element, the first is the "main" source and the rest
   go in a bracket group.
3. Upper-element naming: still-unnamed edges/vertices get `<upper name>;:U<n>`, possibly several names (one per
   adjacent named face), "to improve stability of the next step".
4. Lower-element naming: still-unnamed faces/edges are named from the sorted set of their named lower elements,
   `(edge1,edge2,...);:L`.

Name grammar (examples from the algorithm page, verbatim shapes):
`Face6;:M2;FUS;:T1:5:F`: source `Face...` (5 chars, tag 1), `;:M2` = modified, 2nd modification index, `FUS` = fuse op
code, `;:T1:5:F` = trailing tag 1, source-name length 5, element type F. `;:G` = generated, `;:MG` = both, `;:U` =
upper-derived, `;:L` = lower-derived. A name nests: the source's whole mapped name is the prefix, so a name encodes
the history chain and can be traced back (`traceElement`, `isElementGenerated`, ~l.6344). The selection prefix `;`
marks a mapped name in the GUI (`;:M...`); a missing reference is displayed with `?` (`Data::MISSING_PREFIX`,
`GeoFeature::hasMissingElement`) [V for the existence of the missing prefix; the exact characters I did not
confirm].

Primitives (`Part::Box` etc.) have no map: their elements are considered fixed (`Face1`...). Sketcher names its edges
by geometry id: `g1;SKT` -> `Edge1`, `g1v1;SKT` -> `Vertex1` [V, realthunder notes], i.e. the sketch's own geometry
ids are the roots of every name derived from it. That is why sketch -> pad faces are stable.

### 2.4 How a reference is stored and re-resolved [V]

- A feature stores references in `App::PropertyLinkSub` / `PropertyLinkSubList` / `PropertyXLink`
  (https://github.com/FreeCAD/FreeCAD/blob/main/src/App/PropertyLinks.h): object + sub-name list. Each sub-name has a
  `ShadowSub = ElementNamePair {newName, oldName}`: the mapped (stable) name and the plain indexed name, both kept
  current. Saves still write the indexed name, so older FreeCAD can open the file (realthunder notes "Property Link").
- When the owner shape changes, `GeoFeature` signals dependents, and `PropertyLinkBase::_updateElementReference`
  (https://github.com/FreeCAD/FreeCAD/blob/main/src/App/PropertyLinks.cpp ~l.449-600) looks up the mapped name in the
  new `ElementMap` and rewrites the stored indexed name if it moved (`Face13 -> Face14`).
- If the mapped name is missing: first a geometry search, `GeoFeature::searchElementCache(oldElement,
  CheckGeometry)`, then with plain tolerance, then `rescueDriftedElement`. Before the shape changes, GeoFeature
  snapshots the geometry of every referenced element; after the change it searches the new shape for an element with
  the same geometry (`SearchOption::CheckGeometry | SingleResult | AdaptiveTolerance`, which "widens the tolerance
  stepwise and accepts only a unique match", `ComplexGeoData.h` l.60-65). Only if all that fails the reference is
  marked missing (`?` prefix) and the feature errors. So the order is: name first, geometry as repair, error last.
- Dress-ups (`FeatureDressUp.cpp`, https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureDressUp.cpp)
  read `ShadowSub` (`newName` else `oldName`, ~l.290) and can relink to matching sub-elements when the base feature is
  replaced (`relinkToMatchingSubelements`, ~l.384): this is the "propose a candidate fix" behaviour.

### 2.5 What still breaks [V unless marked]

- The project itself says TNP is "not completely solved" (release notes) and the algorithm is a heuristic that
  "is not intended to fix every failure" (wiki). Inserting/removing features mid-tree makes auto-repair less likely.
- Names depend on OCCT history. Any OCCT change, hasher on/off, threshold, or algorithm change alters names, hence the
  version string and forced recompute (above). Names are therefore not stable across kernel upgrades; this is handled
  by recomputing, not by keeping the old names.
- Splits/merges: one old face becoming two (e.g. a cut through a face) yields two elements whose names share the
  source and differ by the `M<index>` number; which one the reference follows depends on OCCT's ordering of
  `Modified()` [I, consequence of the grammar].
- Not every operation is naming-aware; shapes built by non-`makeElement*` code get no map (`ElementMapPolicy::Drop`
  exists in `makeShapeWithElementMap`) [V for the policy; which workbenches still drop is I].

### 2.6 Cost and size [V qualitatively, no numbers measured]

Names grow with history depth (each name embeds its source name); realthunder introduced the StringHasher for
exactly this and warns names "will quickly go out of control" without it. Cost per operation: building per-type
ancestry caches (`ShapeInfo`, `_cache->getAncestry`) and iterating every input sub-shape through the mapper
(passes 1-4 above are O(sub-shapes) with hash maps). The element map is saved with each shape-bearing object. I did
not find benchmark numbers; the 1.0 integration discussion mentions performance work but I did not read it.

## 3. Other systems (all from recollection unless noted; none were fetched, one Onshape docs fetch was blocked)

| System | Mechanism [I] | Stable across upstream edit? | Failure behaviour |
|---|---|---|---|
| Onshape | Each topological entity gets a deterministic ID derived from the feature that created it and its role (e.g. "the cap of this extrude"), computed from the feature's own history. FeatureScript queries (`qCreatedBy`, `qOwnerBody`, `qAdjacent`, `qGeometry`...) are stored; persistent IDs are resolved at rebuild | Yes for most; the design intent is the query, not a single ID | Reference can become empty/ambiguous; feature errors, user re-selects. |
| SolidWorks | Feature tree + internal persistent references (per-face/edge ids that are carried through the feature history) plus geometry heuristics | Mostly; known failures ("dangling" references) | Rebuild error / "lost reference" until user re-attaches. |
| Fusion 360 | Entity tokens (opaque strings) for B-Rep entities, valid for the same design state; plus a "temp ID" per session | Tokens survive many edits within a design; not guaranteed across all | Token lookup fails -> null entity. |
| CadQuery / build123d | No persistent naming; selectors by geometry/orientation (`faces(">Z")`), tags on workplane stack only within one script | n/a: re-run whole script, selector re-evaluates on new geometry | Selector returns 0 or wrong set; user script handles it. (This is where we are today.) |

Common point [I]: all commercial kernels give the *kernel* the job of reporting per-operation history (Parasolid/ACIS
have it; OCCT has `Modified`/`Generated`/`IsDeleted`), and store a query or lineage, not a position.

## 4. What our kernel already records (read from src/cpp, [V])

Good news: the C++ kernel already captures OCCT history per operation, and tag lineage is already projected through
it. What is missing is a persistent, resolvable *name* built from that history.

- OCCT history capture: `src/cpp/include/scad/semantic/tracking.hpp` ("OCCT algorithm history -> TopoDelta").
  `src/cpp/src/semantic/tracking_detail.hpp` defines `HistorySource` with `BuilderHistory` (wraps a finished
  `BRepBuilderAPI_MakeShape`: `IsDeleted`/`Modified`/`Generated`) and `RetainedHistory` (wraps `BRepTools_History`).
  Per-operation trackers: `tracking_blends.cpp` (`track_blend` for fillet/chamfer, uses `op.Contour`/`op.Edge` to find
  the edges actually blended and marks generated faces as blend patches; shell likewise), `tracking_booleans.cpp`,
  `tracking_sweeps.cpp`, `tracking_lofts.cpp`, `tracking_transforms.cpp`, `tracking_primitives.cpp`. Booleans fill
  history via `kernel::booleans.cpp` (`SetToFillHistory`, `fuse_shapes_with_history` merging the unify history).
  `TrackingPolicy::Graph` turns face/edge history queries off (used for standard-part factories) [V, header comment].
- Result of tracking: `TopoDelta` in `src/cpp/include/scad/topo/delta.hpp`: per output/deleted sub-shape a `TopoEntry`
  {`TopoRef`, `TopoEvent` Preserved/Modified/Generated/Deleted, `origin_role`, `parent_refs`}, plus kernel-native
  `TopoRoleEntry` roles ("extrude.first_cap"). It is stored on every graph node: `std::optional<TopoDelta> topo_delta`
  in `src/cpp/include/scad/reactive/graph.hpp` (node and node-spec).
- Identity: `kernel_topo_id()` = hash of (TShape, Location), orientation ignored; it is valid only while the shape is
  alive and "the recorder resolves kernel ids to stable per-root ids" such as `face_3` (`topo_index` in
  `src/reactive/internal.hpp`, "face_3 -> 3") [V]. A `face_N` id is an *index* into the root's face list, i.e.
  positional: the same weakness as FreeCAD's `Face12`. [I] it is stable within one executed graph run but not across
  re-execution after a parameter change.
- Semantic layer on top: tags (`include/scad/topo/tagging.hpp`, `TagBinding` with 128-bit id, evidence, certainty,
  lifecycle; `tag_factories.hpp` with `LineagePolicy`, `lineage_policy_allows(policy, LineageDerivation)`;
  `shape.hpp` `add_tag_lineage`) projected through the delta. This is why kwarg tags survive booleans and source-edge
  tags project to fillet patches (docs/skill/references/ql-playbook.md rows at l.58-62).
- Editor side: `src/simplecadapi/editor/features.py` `selection_recipe()` (l.~798) emits `scad.ql.tag(...)` first when
  every picked item carries a tag with a known feature slug, else geometry (`selector_conditions` in
  `selection.py`), with `.exactly(n)` as the count check; `extract_recipe` keeps it on edit.

What is missing:

1. No persistent identity for a *picked* sub-shape: the editor stores tags/geometry, not "this sub-shape of node N".
2. Deltas are recorded per node but there is no resolver "(node, sub-shape name) -> sub-shape of the re-executed
   result", and no name that is stable across re-execution. `face_N` is an index.
3. Plain user tags on faces are blocked by a "face-source gate", and face-channel gaps exist for kwarg tags through
   fillet/chamfer (playbook rows). The delta has the data (`Modified`/`Generated`) but the projection stops.
4. No fallback ranking (history, then geometry with uniqueness) and no "candidate fix" output. Geometry fallback is
   in the notebook cell source and is a hard windowed match, not tolerance-widening-until-unique.
5. History is skipped under `TrackingPolicy::Graph`, and some ops (loft section correspondence, per playbook l.185)
   are explicitly "kernel-matched, not stable".

## 5. Recommendation

### 5.1 What the stable reference should be

A **history path**, not a tag and not a position: the reference is
`(origin node id, origin entity role, derivation chain)` where each link is
`{node id, event ∈ {Preserved, Modified, Generated}, source ref, ordinal}`. Concretely, store a small record in the
feature (not a string-encoded blob like FreeCAD's `;:M2;FUS;:T1:5:F`; we have a typed `TopoDelta`, so use it):

```
ElementRef = {
  anchor: {node_id, kind, role?, index?},   # the "root name": where this entity was born
  chain:  [ {node_id, event, ord} ... ],    # Modified/Generated hops up to the node the feature consumes
  guard:  {kind, area, centroid, normal/length}  # geometric fingerprint used only to verify/repair
}
```

Roots (anchors) should be the things already deterministic in our kernel: a primitive's named faces, an extrude's
`first_cap`/`last_cap`/side-per-profile-edge (sketch geometry ids, as FreeCAD uses `g1;SKT`), revolve caps, and
user-pinned semantic tags. Everything else is derived by following `Modified`/`Generated` through `topo_delta`.
This is exactly FreeCAD's model (stable roots + history hops) with typed fields instead of string grammar.

### 5.2 Where history capture belongs

The C++ kernel, per operation, via the OCCT make-shape history; it is already there (section 4). The work is not
new capture but (a) making the kernel emit, for each result sub-shape, a **name** (root + hops) rather than only a
per-run index, and (b) a deterministic ordinal when several result sub-shapes descend from one source (sort by a
stable key: tag/role first, then a geometric key such as centroid lexicographic order at fixed tolerance, never
OCCT iteration order), because `Modified()` ordering is not a promise [I]. Use the same fall-through order FreeCAD
uses for unnamed elements (upper-derived, then lower-derived names) only where history yields nothing.
Ops that skip history (`TrackingPolicy::Graph`) are fine: the user does not reference faces of standard-part
internals; but the *consumed* body of any feature a user picks from must run with history on.

### 5.3 How a GUI feature stores it

The picked item's `ElementRef` (JSON, short) goes in the feature cell as a kwarg-style literal or a structured cell
comment that the editor already round-trips (`extract_recipe`), e.g.
`_edges = scad.ref.edges([ElementRef(...), ...], source={BODY})`, resolved by the SDK, not by recipe text. Keep the
current tag and geometry lines as *secondary* evidence inside the same ref (`guard`), not as the main mechanism.
Per FreeCAD's `ShadowSub`, also keep the last resolved positional name only as a cache/hint.

### 5.4 Resolution and failure behaviour

Resolver order (mirrors FreeCAD 2.4):

1. Follow the chain through the new run's recorded deltas to a set of result sub-shapes.
2. If exactly one: done. If several (split): pick by ordinal; if the picked count differs from what the feature
   needs, fail with the candidate list.
3. If none (deleted or chain broken): geometry search with `guard`, widening tolerance stepwise and accepting only a
   **unique** match (FreeCAD's `AdaptiveTolerance`); mark the result `repaired_by_geometry` in the output.
4. Else raise a typed error `ElementRefLost` on the feature, carrying the last known name, the guard, and up to N
   candidates ranked by geometric distance for the editor to offer ("propose fix", FreeCAD purpose 2). Never silently
   pick another entity ("First, do no harm"); this is already our rule ("an error on the feature, never another
   face"), keep it.
5. Whenever a repair happens (step 3 or user-accepted candidate), write the new name back into the cell.

Always run the check that the resolved kind and count match, as today.

### 5.5 Staged plan, smallest first

1. **Spike (smallest): resolve through existing deltas, no new storage.** In the Python/C++ boundary add
   `resolve_by_history(body_value, node_id, topo_id) -> [faces]` that walks `topo_delta` entries
   (`parent_refs`, event) from the picked entity's birth node to the current result. Use only for fillet/chamfer
   after boolean/extrude; compare against the geometric recipe on the failing cases found so far (face tags dying
   after later ops; kwarg tags lost through fillet). Success = those cases resolve with zero geometry fallback.
   Needs no format change.
2. **Persistent names.** Replace the per-run `face_N` with root+chain names as in 5.1; add deterministic ordinals
   (5.2). Add the `ElementRef` literal and make `selection_recipe` emit it; keep tag/geometry as `guard`.
3. **Resolver with repair and errors** (5.4), including `ElementRefLost` with candidates; editor UI shows them.
4. **Close the gaps in projection:** lift the face-source gate for user tags and the fillet/chamfer face-channel gap
   by feeding them from the same chain, so tags become a *view* over the names instead of a parallel system.
5. **Versioning and tests.** An element-map version string like FreeCAD's (our naming algorithm version + OCCT
   version); on mismatch, force full recompute and re-resolve with guard. Regression: reuse the existing editor
   selection tests and add a corpus (parameter sweep of a bracket: change widths, add a fillet upstream, insert a
   feature mid-tree) asserting resolved-by-history rate and zero wrong picks. Measure delta size and resolve time
   on the arm6 benchmark before enabling history on large graphs.

### 5.6 Risks and non-goals

- Cannot be perfect: FreeCAD, with years of work, still documents failures. Target "never silently wrong, mostly
  automatic", not "never fails".
- OCCT history is imperfect for some algorithms (sewing, thru-sections, offsets, `BOPAlgo` fuzzy cases); keep per-op
  coverage explicit and fall back to guard for those, as FreeCAD does with `ElementMapPolicy::Drop`/special mappers.
- Lofts: per-section correspondence is kernel-matched; do not promise stable side-face names until sections are
  named by input wire edges.
- Avoid FreeCAD's string-encoded grammar and its hasher; typed records plus an interned table are simpler for us, but
  record growth with chain depth still needs a cap (collapse a chain to its nearest durable anchor, e.g. a tag or a
  primitive root).

## Source list

- https://wiki.freecad.org/Topological_naming_problem
- https://wiki.freecad.org/Release_notes_1.0
- https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming
- https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming-Algorithm
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/ElementMap.h
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/MappedName.h
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/IndexedName.h
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/ComplexGeoData.h
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/GeoFeature.cpp
- https://github.com/FreeCAD/FreeCAD/blob/main/src/App/PropertyLinks.h and PropertyLinks.cpp
- https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/Part/App/TopoShapeExpansion.cpp
- https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureDressUp.cpp
- Not read: PR #13705 itself (only its mention in the release notes), the forum thread "Topological Naming, My Take",
  and any Onshape/SolidWorks/Fusion documentation.

---

## Addendum: Onshape, read from primary sources (ego-browser, 2026-11-04)

This replaces the Onshape row above, which was written from memory (the first fetch was stopped by a login wall on `cad.onshape.com/FsDoc/queries.html`;
the FeatureScript standard-library reference is readable at `formlabs.onshape.com/FsDoc/library.html`, and the REST guide at
`onshape-public.github.io/docs/api-adv/associativity/`).

**Verified**

- **A reference is a query evaluated against the current history, never a stored entity id.** Features pass `Query` values; a feature's `id` is a
  hierarchical path (`id + "extrude1"`) and `qCreatedBy(id + "extrude1", EntityType.FACE)` resolves to whatever that operation created in the
  *current* regeneration. Rule from the library docs: "the full id hierarchy must reflect creation history", each Id (and every parent) must cover a
  contiguous region of operations, so an id is a position in the operation sequence, not a number on the geometry.
- **Tracking through later operations is explicit and history-based:** `startTracking(context, subquery)` returns a query that evaluates to the entities
  that *derive from* the subquery's result (the docs' example: a sketch line `line0` extruded yields a face and two edges); `startTrackingIdentity`
  returns the entities that inherit the identity; `makeRobustQuery(context, subquery)` produces "a query robust to identity-preserving changes";
  `makeRobustQueriesBatched(..., followSplitMerge)` does it per entity, optionally through splits and merges. This is the same idea as FreeCAD's mapped
  names (derivation recorded by the kernel's operation history), exposed as an API instead of an encoded string.
- **Unstable ids are handled by disambiguation:** `setExternalDisambiguation(context, id, query)` for operations whose id has an unstable component
  (sketches, planes, points that track no dependency); a pattern instance takes an `identity` entity so it follows its source, not its index.
- **Failure is loud:** `verifyNonemptyQuery` raises a regen error and marks the parameter faulty when a query "no longer resolves to anything"
  (the face is not silently replaced by another).
- **Externally there is no persistent id at all.** The REST guide: "Onshape does not expose a persistent ID for any of these entities. When the model
  changes, the ID may change", so it offers `POST .../idtranslations` from a source microversion: each id maps to `OK`, `SPLIT` (several targets) or
  `FAILED_TO_RESOLVE` (none); the guide stresses "a face may become zero, one or multiple faces". A rollback translates back to the original ids.

**What it means for us**

1. Onshape's answer and FreeCAD's agree in substance: the reference is *derivation through recorded history*, with a three-way outcome (same / split or
   merged into several / gone) and no silent retargeting. Geometry matching is a repair step at best.
2. The shape worth copying is Onshape's API: a **reference = (anchor operation id, entity kind, optional tracking)**, resolved by walking the
   per-operation history we already store (`TopoDelta`), returning *a list* with a status (`ok` / `split` / `lost`), and a `follow_split_merge` choice.
   Our graph node ids are already deterministic positions in the operation sequence, which is what Onshape's hierarchical ids are.
3. The status vocabulary (`OK`, `SPLIT`, `FAILED_TO_RESOLVE`) should be the editor's reference health: green, amber with the candidates, red.
4. Still not read: Onshape's internal algorithm (not public), Parasolid's own attribute mechanism, and the FreeCAD PR threads; the Fusion and
   SolidWorks rows stay unverified.
