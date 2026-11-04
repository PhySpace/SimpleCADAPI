# Multi-body parts (several solids in one part, without an assembly)

Status: research and spike on `research/multi-solid` (cut from `dev`). The spike is in the code and in
`test/test_multi_body_part.py`. Everything under "Staged plan" after stage 1 is a proposal. Section 9 records the
owner's decisions and how they are implemented; where it differs from an earlier section, section 9 wins.

## 1. The decision

**A Part holds an ordered set of named bodies. A body is a Solid with an id that is unique within its part.
A one-body Part is the special case that every existing Part already is.**

- `make_part_rpart(part_id=..., bodies={"base": base, "lid": lid})` makes a part with two bodies.
  `make_part_rpart(part_id=..., body=solid)` is unchanged.
- `part.bodies` returns `(Body, ...)` in order. `part.get_body("lid")` returns one body and `part.body_ids()` returns the ids.
- `part.body` keeps returning the Solid of a one-body part. On a multi-body part it raises a `TypeError` that names the
  bodies. It never silently returns the first body: a caller that reads `part.body` would otherwise export, weigh or
  draw only part of the part.
- A Body is product geometry and nothing more. It has no placement, joint, constraint or connector of its own in
  stage 1. Anything that moves relative to something else is a component of an Assembly. This is the line every
  surveyed CAD system draws (see section 3): Fusion says it outright, and SolidWorks says "one part = one BOM line".
- Construction solids, tool solids and "kept for a later boolean" solids are **not bodies**. They stay plain notebook
  values, as they are today. The product is exactly what the product cell puts into the Part. This one rule covers
  "tool bodies that must stay hidden" with no `visible` flag in the data model: hiding is an editor view state, and
  being part of the product is a modelling fact.

Why not a `Compound` inside the Part: a Compound is a new shape root and drops the tags of the solids it is built from
(verified: `scad.Compound([a, b])` of two tagged boxes has no face tags; SDK_DEFECTS.md #21). Each body therefore stays
its own Solid root, with its own tags, lineage, graph node and topology snapshot. A Compound appears only as a
geometry view (`scad.part_shape(part)`), for consumers that do not care which body a face belongs to (STEP, STL,
MJCF).

Why not "a part studio of several Parts" (Onshape style): that would make each body a separate product definition
with its own `part_id`, BOM line and package unit. That is a real feature, but it is a different one: it amounts to
"one notebook, several products". This design keeps one product per notebook.

## 2. The data model today (evidence)

| Piece | Where | One-solid assumption |
|---|---|---|
| `Part` (C++) | `src/cpp/include/scad/product/part.hpp:19` (before), `part.cpp` | `Solid body_` field. Header comment: "exactly one Solid" |
| `make_part_rpart` | `bindings/python/bind_product.cpp:81`, `src/product/ops_structure.cpp:105` | `typed<Solid>(body)`. Docstring: "Wrap exactly one Solid" |
| guidance | `src/cpp/src/product/specs.cpp:43` | "Union intended multiple bodies into one Solid before creating the Part." |
| `Solid` | `src/cpp/src/topo/shape.cpp:15` | the kind is checked, so a `Solid` is exactly one `TopoDS_Solid` |
| `Compound` | `include/scad/topo/shape.hpp:290` | `solids()`. A new root, so the tags of its parts are lost (#21) |
| solid lists | `cut_rsolid_list`, `boolean_rsolidlist`, `*_pattern_rsolidlist` | `list[Solid]` values in the notebook. Never a product |
| `cut_rsolid` | `src/cpp/src/ops/features/booleans.cpp:372` | refuses a split result (since bd36d58) |
| assembly flatten | `src/cpp/src/product/ops_projection.cpp:20` | `part->body()` |
| session children | `src/simplecadapi/_glue/session.py:53` | `yield item.body` |
| cell cache | `runtime/cache.py:255` (`_semantic_state`) | "A Part is its body" |
| pickling | `_glue/values.py` `_reduce` | rebuilds `Part(part_id, body, ...)` from attributes (#22) |
| `@part` builder | `build/part_builder.py:43` | "must return exactly one Solid or one Part" (still true: one Part) |
| PartDefinition | `artifacts/part_definition.py:30`, schema `contracts/part-definition-2.schema.json` | "exactly one evaluated Solid": one `solid_cache.body_ref`, one `topology_snapshot_ref` |
| definition build | `build/definition.py:169-225` | BRep, snapshot, geometry hash and validation of `part.body` |
| BRep reader | `artifacts/brep.py:44` `read_brep_solid` | "BRep root must be exactly one Solid" |
| part archive load | `artifacts/part_io.py:93` | `read_brep_solid` |
| materialize | `artifacts/assembly_io.py:762` | `Part(body=read_brep_solid(...))` |
| package blob roles | `product/packages.py:180` | one body and one topology blob per part |
| live preview | `scene/preview.py:271` (`compile_preview`) | one `PreviewNode` per part, `entity/<part>/<kind>/<topo>` |
| package scene | `scene/product_scene.py:322`, `:822` (`_camera`) | one GLB and one entity document per part |
| legacy scene | `scene/compiler.py:330, 339, 697, 928` | `part.body`. "a standalone Compound must contain exactly one solid" |
| prewarm | `scene/prewarm.py:39` | one body per part |
| STEP | `exporter/step.py:76` | `"shape": value.body` |
| STL / surface mesh | `exporter/_surface_mesh.py:45` | `(value.body,)` |
| MJCF | `exporter/mjcf.py:680` | `part.body` |
| definition kind | 20 places | `"single_solid"`. The kind name means "a part" (#23) |
| editor features | `feat/gui-modeling:src/simplecadapi/editor/features.py:677` `_with_combine` | "A part holds one solid": every new solid must join, cut or intersect, or start the body |
| editor product | `feat/gui-modeling:.../gui_features.py:99, 489` | the product cell is `make_part_rpart(..., body=<one slug>)`, re-pointed after each feature |
| editor defaults | `gui_features.py:_defaults` | `operation = "join" if last is not None else "new"` ("do not leave a second") |
| editor-web | `editor-web/src/components/NotebookList.tsx:155` | "a notebook that builds one solid" |

The editor already tracks the "open bodies" of a notebook: solids that no later feature consumed
(`gui_features.py:129`). Today only one of them reaches the product. A multi-body part is the missing link between
"open bodies" and the product.

## 3. Other CAD systems

The research used primary documentation read in a browser. V means read on the page. I means inferred or not
confirmed.

- **Onshape Part Studio.** One feature list "drives the shape of multiple parts" (V,
  cad.onshape.com/help/Content/PartStudio/part_studios.htm). Each part is its own BOM item. Features choose
  New / Add / Remove / Intersect with a merge scope; when several touching parts are ambiguous the user must choose,
  and an empty scope is an error (V, .../extrude.htm). Boolean has "Keep tools", and a merge keeps the name of the
  first-selected part (V, .../boolean.htm). Mass properties are additive, overlaps count twice, and parts without a
  material are left out (V, .../View/mass_properties_tool.htm). Several parts export to one file by default (V,
  .../File/exporting_files.htm). A composite part groups bodies into one BOM line (V, .../composite_part.htm).
- **SolidWorks multibody part.** "Part documents can contain multiple solid bodies", kept in a Solid Bodies folder,
  each with its own name and colour (V, help.solidworks.com/2024 .../c_Multibody_Overview.htm). "One part (multibody
  or not) should represent one part number in a Bill of Materials", and bodies are "not dynamic" (V,
  .../c_Multibody_Parts_Vs_Assemblies.htm). Material is set per part; a per-body material overrides it (V,
  .../c_multibody_materials.htm). Extrude has "Merge result"; without it the feature creates a distinct solid body
  (V, .../r_extrude_propertymanager.htm). Feature Scope limits which bodies a feature touches (V). Combine does
  Add / Subtract / Common (V). Mass properties exclude hidden bodies unless asked (V,
  .../hidd_massproperty_text_dlg.htm). Export offers all bodies or selected bodies (V); Save Bodies writes each body
  to its own part and can build an assembly (V, .../hidd_dve_feat_split.htm).
- **Autodesk Fusion.** "A Body is a single container for a contiguous 3D shape". Components hold bodies, and "you
  cannot create joints or motion between bodies" (V, help.autodesk.com ...GUID-C1AB4941...). Extrude operations are
  Join / Cut / Intersect / New Body / New Component (V, ...SLD-REF-EXTRUDE). Combine has a target, tool bodies and
  "Keep Tools" (V, ...SLD-COMBINE). Per-body material and appearance are inferred (I).
- **FreeCAD.** A PartDesign Body "is intended to hold a single contiguous solid", and 1.0 adds an experimental
  "Allow Compound" (V, wiki.freecad.org/PartDesign_Body). Part Compound groups shapes, and a compound whose members
  touch or intersect "is invalid for Boolean operations", which is not checked (V, .../Part_Compound). PartDesign
  Boolean pulls tool bodies into the active body and hides them (V, .../PartDesign_Boolean).
- **CadQuery / build123d.** `combine=False` keeps a new solid apart. Results are Compounds, and `.Solids()` lists them
  (V, cadquery.readthedocs.io .../workplane.html). build123d modes are ADD / SUBTRACT / INTERSECT / REPLACE / PRIVATE.
  `BuildPart.part` "may contain more than one shape" (V, build123d.readthedocs.io .../build_part.html). STEP export
  carries a label and colour per node, and repeated labels are numbered (V, .../import_export.html).

What this design takes from them:

1. A body is named geometry inside one product item (every system).
2. "New body" is an explicit per-feature choice beside join/cut/intersect, and an ambiguous target is an error, never a
   guess (Onshape, SolidWorks, Fusion).
3. A boolean between bodies says whether it consumes its tools, and the result keeps the name of the target body
   (Onshape, Fusion).
4. Mass is the sum over bodies, with explicit rules for overlaps and missing material (Onshape, SolidWorks).
5. A multi-body part exports as one product holding several solids, with an option to split it (SolidWorks, Onshape).
6. A bare compound is not a body set. It must not quietly become the input of a boolean (FreeCAD).

## 4. Design

### 4.1 Body

```text
Body(body_id: identifier, solid: Solid, name: str | None = None)
```

- **Identity.** `body_id` is unique within its part and has the same rules as a `part_id` (`validate_identifier`). In a
  notebook it is normally the name of the variable or feature slug that produced the solid ("base", "lid"). A one-body
  Part has one Body with the id `"body"` (`kDefaultBodyId`).
- **Order.** Bodies keep the order they are given in, which is the order of the dict. Order is part of the product:
  it decides the STEP solid order and the order of the scene nodes.
- **Names.** `name` is an optional display name.
- **Colour** (implemented, `feat/body-appearance`). Optional `color` (linear RGB in [0, 1]) and `opacity` on Body, an
  appearance only, set with the recorded op `set_body_appearance_rpart(part, body_id="body", *, color=None,
  opacity=None, name=None, reset=False)`. The material colour is the default; a body colour overrides it for display.
  It reaches the preview (node `color`/`opacity`), `scene/compiler.py` (`base_color`), the package scene (node
  `properties.color`/`opacity`), the definition (optional `appearance` block, profiles 2 and 3; absent when unused, so
  bytes are unchanged), STEP (the part colour for a one-body part; a named, coloured XCAF sub-shape per body of a
  multi-body part, with `write.stepcaf.subshapes.name` on), the cell cache and replay.
- **Material** (stage 3). The part material applies to every body. A per-body material override follows
  SolidWorks' rule: the body material wins, and bodies without one inherit the part's. Mass already reads density per
  body (`measure_part_mass_rmassreport`), so stage 3 only changes where the density comes from.
- **Visibility.** None in the product. See section 1: a hidden tool is not a body.

### 4.2 API

Stage 1, implemented:

| Name | Kind | Notes |
|---|---|---|
| `scad.Body(body_id, solid, name=None)` | value | C++ `scad::product::Body`. Pickles |
| `scad.make_part_rpart(part_id, body=None, name=None, *, bodies=None)` | op | exactly one of `body` / `bodies`. `bodies` is `{id: Solid}` or `[Body, ...]`. Recorded with one `body` input per body and `params.bodies = [{body_id, name}]`. Replays |
| `scad.Part(..., bodies=...)` | ctor | same rule. ValueError for no bodies, a duplicate `body_id`, or connectors on several bodies |
| `Part.bodies`, `Part.multi_body`, `Part.body_ids()`, `Part.get_body(id)` | read | |
| `Part.body` | read | the Solid of a one-body part. TypeError on a multi-body part |
| `scad.part_shape(part)` | helper | the Solid, or a Compound of every body (a geometry view, no tags) |
| `scad.measure_part_mass_rmassreport(part, *, density=None, density_unit=None)` | op (diagnostic) | per body: `volume_mm3`, `mass_kg`, `centroid_mm`; plus totals. Density comes from the material or from the arguments |

Stage 2, proposed (each one an SDK op, so agents and the editor call the same thing):

- `add_body_rpart(part, body_id, solid, name=None) -> Part` and `remove_body_rpart(part, body_id) -> Part`: the
  functional edits the editor's bodies list needs, in the style of `add_connector_rpart`.
- `split_rpart(part, body_ids=None) -> Assembly` ("Save Bodies"): one component per body, with identity placements
  and part ids `<part>_<body>`. This is the explicit exit from bodies to an assembly when the bodies need motion.
- `cut_rsolid_list` naming help: pieces come out in kernel order, which is not stable across OCCT versions. A
  `bodies_from_pieces(prefix, pieces)` that orders pieces by centroid (x, then y, then z) gives stable ids
  `piece_1..n` for "a part with disjoint pieces after a cut".

Stage 3, proposed:

- `combine_bodies_rpart(part, target, tools, operation="join"|"cut"|"intersect", keep_tools=False) -> Part`. The
  result keeps the target's `body_id` (Onshape's rule). Consumed tools leave the part. It is needed only when a Part
  arrives without its notebook (an imported multi-solid STEP). In a notebook, bodies are still plain solids before the
  product cell, and `union_rsolid(base, lid)` is already "combine". A part is the end of the pipeline, not a workspace.
- Per-body material and colour (4.1).
- Connectors on multi-body parts: a connector anchor names `body_id` plus the entity within that body. The
  `GeometryRef` and the binding checks in `build/definition.py` then run per body.

### 4.3 Booleans between named bodies

In a notebook, bodies are named before they meet the product, so booleans between them are ordinary operators on
named solids. The rules the editor and the docs follow:

- Join, cut and intersect consume their inputs as they do today. A consumed solid is no longer an "open body", so it
  leaves the product's bodies at the next re-point (4.4).
- "Keep tools" is the default behaviour of a functional SDK anyway: the tool variable still exists. Whether it stays
  a body is the product cell's choice, and the editor offers that choice explicitly.
- `cut_rsolid` keeps refusing a split. `cut_rsolid_list` keeps every piece, and those pieces become bodies through
  `bodies={...}` (stage 2 helper above).
- Overlapping bodies are allowed, as in SolidWorks and Onshape. Mass counts every body whole, which is the Onshape
  rule, and the report says so. A stage-2 diagnostic `check_bodies_disjoint` (pairwise common volume) can warn before
  export. Whether `make_part_rpart` should refuse overlaps is an open question for the owner (section 7).

### 4.4 Editor UX (the editor only adapts SDK ops)

- **Bodies list.** The product cell becomes the list. `make_part_rpart(part_id=..., bodies={"base": base, "lid": lid})`
  is parsed like `_PRODUCT_BODY` today, with one row per entry. A notebook with one body keeps writing `body=...`, so
  existing notebooks are untouched.
- **Operation choice.** Each combinable feature keeps join / cut / intersect / new body. The changes:
  - "New body" becomes a real choice. The feature makes a new open body, and the editor adds it to the product's
    bodies with `add_body_rpart` semantics (an edit of the dict literal in the product cell).
  - The default stays "join" when a body exists (Onshape's default is New only for the first feature, too). The help
    text no longer says "a part holds one solid".
  - "Combine with" stays an explicit body choice. When more than one body exists the target has no default: the form
    asks, which is Onshape's rule for an ambiguous merge.
- **Re-pointing.** `_repoint_product` today swaps the one body name. With bodies it does the same for the dict entry
  whose solid the new feature consumed, and keeps the `body_id`. A body keeps its id while it is joined, cut and
  filleted, the way a SolidWorks body keeps its name through features.
- **Construction solids.** Open solids that are not in the bodies dict are listed under "Construction", drawn ghosted
  and never exported. That covers tool bodies and solids kept for a later boolean, with no flag in the product.
- **Viewer.** Preview nodes are `node/<part>/body:<id>`, and entities are `entity/<part>/body:<id>/<kind>/<topo>`. The
  scene tree shows the part with its bodies as children (`node_kind: "solid"`, which the scene schema and
  `editor-web/src/scene/scene2.ts:27` already accept). Picking a face says which body it belongs to.
- **Assemblies stay separate.** Assembly documents (`assembly_doc.py`) keep placing Parts. A multi-body part is one
  component there. "Make components from bodies" is `split_rpart`.

### 4.5 Export, mass, preview, package

- **Live preview** (`scene/preview.py`, implemented): one node per body, all at the part's placement. The part key
  includes the body id, so two equal-shaped bodies stay two entity namespaces. `entity_info` understands the `body:`
  segment.
- **Package** (`PartDefinition`, implemented):
  - A one-body part writes the same manifest bytes as before, so its content hash is unchanged.
  - A multi-body part adds `solid_cache.bodies = [{body_id, name, body_ref, topology_snapshot_ref}]`, one BRep and
    one snapshot per body, so every body keeps its tags.
  - `solid_cache.body_ref` is then a BRep Compound of every body. That is what a geometry-only reader needs, and what a
    reader that expects exactly one Solid refuses (`read_brep_solid`), so old readers fail closed instead of dropping
    bodies.
  - `topology_snapshot_ref` repeats the first body's snapshot, because the schema requires it.
  - The geometry interface hash covers `[{body_id, geometry}]`.
  - Validation (`validate_artifact_blobs`, package blob roles, `part_io`) covers every body blob and checks that the
    Compound holds as many solids as there are bodies.
- **Package scene** (`scene/product_scene.py`, implemented): the part node has no geometry. Each body is a child node
  of kind `solid` with its own GLB and entity document, `node_id` `node/<part>/body:<id>`. The camera frames every
  body.
- **STEP** (implemented): one PRODUCT whose shape holds every body. The test checks one `PRODUCT(` and two
  `MANIFOLD_SOLID_BREP`. Stage 2 writes the body name and colour on each solid (an XCAF sub-shape label), as
  build123d does.
- **STL / MJCF** (implemented): every body goes into the mesh. In MJCF a multi-body part is one rigid body with one
  mesh, which is correct because bodies never move apart.
- **Mass** (implemented): `measure_part_mass_rmassreport`. Totals are sums; the centroid is volume-weighted.
- **Cell cache** (implemented): `Part` pickles with its bodies (`_glue/values.py` `_ARGUMENTS`), and the
  semantic-state guard watches every body (`runtime/cache.py`).
- **Legacy `scene/compiler.py`** (`compile_scene` / `export_scene`): not converted. A multi-body part raises the
  `Part.body` TypeError there (stage 2).

### 4.6 Boundary with assemblies

| | Bodies of one Part | Components of an Assembly |
|---|---|---|
| Product items / BOM lines | one | one per component |
| Placement | none (bodies share the part frame) | per component |
| Joints / constraints / motion | never | yes |
| Connectors | per part (stage 3: anchored on one body) | per part, public per assembly |
| Material | part (stage 3: per-body override) | per part |
| From one to the other | `split_rpart` (stage 2) | `make_compound_from_assembly_rcompound` flattens (every body of every part) |

## 5. Staged plan

1. **Stage 1, done in this spike:** Body, `Part.bodies`, `make_part_rpart(bodies=...)` with recording and replay,
   pickling and cache, live preview, package format, package scene, STEP, STL and MJCF geometry, assembly flattening,
   and the mass report. One-body parts are unchanged byte for byte.
2. **Stage 2:**
   - Editor: bodies list, a real "New body", construction group, re-pointing by `body_id`.
   - `add_body_rpart`, `remove_body_rpart`, `split_rpart`, ordered piece naming, `check_bodies_disjoint`.
   - STEP body names and colours.
   - `scene/compiler.py`.
   - Body colour.
   - Skill docs: when to use bodies and when to use an assembly.
3. **Stage 3:**
   - Per-body material.
   - Connectors on a body.
   - `combine_bodies_rpart` for parts without a notebook (STEP import with several solids becomes a multi-body Part
     instead of an error).
   - Rename the `single_solid` definition kind at the next package schema bump.

## 6. Risks

- **Silent partial readers.** Any code still reading `part.body` raises on a multi-body part. That is loud, not
  silent, but it is a runtime failure on paths no test covers, e.g. `scene/compiler.py:330` and the translators. The
  `grep '\.body\b'` list in section 2 is the checklist.
- **Package compatibility.** A package with `solid_cache.bodies` validates under the same `part-definition-2` profile.
  An old SDK reading it fails at `read_brep_solid` (Compound root) or at the closed schema (`additionalProperties:
  false` on `solid_cache`), which is the right failure. A profile bump to `part-definition-3` would make the change
  explicit, at the cost of every reader (open question).
- **Body id stability.** The ids come from the notebook. If a person renames a variable, the body is renamed with it.
  Pieces of `cut_rsolid_list` arrive in kernel order (stage-2 helper).
- **Overlaps.** Overlapping bodies make mass and FEM meaningless and STEP ambiguous. The policy is open (section 7).
- **Editor complexity.** Re-pointing a dict entry is more state than swapping one name. The bodies list must stay a
  parse of the product cell, never a second store.

## 7. Open questions for the owner

1. May `make_part_rpart(bodies=...)` refuse overlapping or touching bodies (FreeCAD's warning), or only warn through a
   diagnostic? The spike allows overlaps.
2. Should the package profile move to `part-definition-3`, or does the additive `solid_cache.bodies` under profile 2
   stay (the spike's choice, which keeps one-body hashes)?
3. Should the default body id of a one-body part stay `"body"`, or should it be the notebook variable name? The
   variable name is nicer in the editor, but changing it would change ids that exist today.
4. Does "New body" in the editor need confirmation the first time a notebook gets a second body, given that until now
   a second solid was a mistake?
5. (Decided, section 9: splits are kept as pieces by default.) Should `cut_rsolid` keep refusing splits?

## 8. The spike

- **C++:**
  - `include/scad/product/part.hpp`, `src/product/part.cpp`: Body, the bodies of a Part, the `body()` TypeError.
  - `src/product/ops_structure.cpp`: the `make_part_rpart` overload and its record.
  - `src/product/ops_projection.cpp`: assembly flattening takes every body.
  - Bindings: `bind_product_values.cpp`, `bind_product.cpp`, `bind_product_args.hpp` (`body_list`).
- **Python:**
  - `product/bodies.py`: `part_shape`, `measure_part_mass_rmassreport`.
  - `_glue/values.py`, `_glue/session.py`, `runtime/cache.py`.
  - `artifacts/part_definition.py` (`BodyRef`), `artifacts/part_io.py` (`read_part_bodies`), `artifacts/assembly_io.py`,
    `artifacts/validation.py`, `contracts/part-definition-2.schema.json`.
  - `build/definition.py`, `product/packages.py`.
  - `scene/preview.py`, `scene/product_scene.py`, `scene/prewarm.py`.
  - `exporter/step.py`, `exporter/_surface_mesh.py`, `exporter/mjcf.py`.
  - `recording/serializer.py` (replay and the diagnostic row).
  - Docs, stubs and `docstrings.json` / `modules.json` registration.
- **Tests:** `test/test_multi_body_part.py`, 20 tests:
  - value rules;
  - pickle and deepcopy with tags;
  - connectors refused;
  - assembly flattening;
  - graph replay;
  - mass per body and totals;
  - preview nodes and entity namespaces, including two equal-shaped bodies;
  - a notebook run twice, with every cell after setup cached and the same content hash;
  - a package that round-trips with tags per body;
  - scene solid nodes;
  - STEP with one product and two solids;
  - one-body definitions without `bodies`.

## 9. Owner decisions (implemented)

1. **Overlapping bodies warn, never refuse.**
   - `inspect_body_overlaps_rlist(part)` is a diagnostic op. It lists pairs that share volume: a bounding-box
     prefilter, then the OCCT common volume. Bodies that only touch along a face, an edge or a point are not reported.
   - Building the definition warns once per pair with `BodyOverlapWarning`. That covers a notebook run, `@part` and a
     package. `make_part_rpart` itself never runs the check, so the live editor loop stays cheap.
2. **Multi-body definitions are profile `simplecad-part-definition-3`.**
   - The new schema `contracts/part-definition-3.schema.json` requires `solid_cache.bodies`.
   - `part-definition-2.schema.json` is back to its dev bytes. A profile-2 reader fails schema validation on
     `profile` (`const`), so it refuses the file rather than reading it wrongly. This is tested by validating a profile-3
     manifest against schema 2.
   - One-body parts stay profile 2, so their bytes and content hashes do not change.
   - `validate_manifest` picks the schema by the manifest's profile.
3. **Default body ids.** A one-body part keeps `"body"`; a multi-body part uses the names it was given. This is
   unchanged from the spike.
4. **Choosing "New body" is the confirmation.** The editor asks nothing more.

   **Implicit Part** (the `kind = "part"` rule on `feat/gui-modeling`, `runtime/projection.py`): every open body
   becomes a body of the implicit Part, named by its variable. The drop-in is `simplecadapi.product.bodies.part_from_bodies(part_id, {name: solid_or_pieces})`. It makes a one-body Part
   (id `"body"`) for one open Solid, and otherwise `make_part_rpart(bodies=...)` with the pieces of a split expanded to
   `<name>_1..n`. The exact change on `feat/gui-modeling`:
   - in `open_bodies`, also accept a non-empty `list`/`tuple` of `Solid` (the pieces of a split cut) as a candidate. Use
     the lineage of its first element for the "made from" test, and treat `id()` of each piece as seen;
   - in `_implicit_part`, drop the `len(names) > 1` error and return
     `part_from_bodies(config.id, {name: values[name] for name in names})`;
   - update its docstring and the test that expected the error. Expected: two open bodies give a Part with those two
     body ids.
5. **A cut that splits the body is not refused.**
   - `cut_rsolid(..., on_split="pieces")` is the default. A one-piece result is a `Solid`, exactly as before, with the
     same record, so the hashes of existing notebooks do not change. A split returns every piece as `list[Solid]`,
     ordered by centroid (x, then y, then z). It is recorded as `make_cut_rsolid_list` with
     `params.piece_order = "centroid"`, and both the C++ executor and the Python serializer replay it in that order.
   - `on_split="error"` keeps the strict behaviour.
   - Pieces become bodies directly: `make_part_rpart(body=pieces)` gives `body_1..n`, and `bodies={"bar": pieces}` gives
     `bar_1..n`.
   - **Default: separate bodies, not one solid with several lumps.** OCCT has no valid single solid with several lumps.
     A `TopoDS_Solid` built from the two outer shells of a split bar fails `BRepCheck_Analyzer`, and STEP writes it as
     `BREP_WITH_VOIDS`, with the second lump turned into a void. This was checked with a small OCCT program.
     Fusion ("a body is a single container for a contiguous 3D shape") and FreeCAD ("a single contiguous solid") agree
     that a body is one closed volume.
   - "Keeping the pieces together" is therefore a naming matter: they share the prefix of the value they came from
     (`bar_1`, `bar_2`), and the editor can show them as one row with two bodies.
   - A Body that holds several lumps would be a later, additive extension (`Body.lumps`). It is not needed for valid
     geometry.
   - Downstream single-solid features (a fillet on `bar`) now fail with a clear type error when `bar` is a list. The
     editor should then offer to pick a piece or keep the pieces as bodies (stage 2).

Skill pages updated with these rules: `domains/part-modeling.md` (with a new "Multi-body parts" section),
`domains/assembly-and-product.md`, `discipline/core-rules.md` R5, `discipline/failure-and-repair.md`,
`discipline/mechanical-modeling.md`, `discipline/notebook-cell-design.md` C9, `docs/core/compound.md`,
`docs/guides/notebook-runtime.md`, `workflows/single-part-modeling.md` and `role-4-build.md`, and
`workflows/drawing-reconstruction.md`. The API pages are regenerated. Tags on cut pieces: a plain `cut_rsolid` outside
a recording session carries no input face tags, a behaviour that predates this work. Tag and ref propagation belongs to
`research/stable-geometry-refs`.

