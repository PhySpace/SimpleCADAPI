# Task Domain: Part Modeling

Model one physical mechanical part with the core geometry API: primitives,
profiles, 3D features, booleans, detail features, and transforms. A part is
one solid body: a Part holds exactly one solid (see "One Part, one solid"
below).

**Read when:** the deliverable is one physical part (one solid body), or an
existing part source needs a geometry edit (Role 4 of `workflows/single-part-modeling.md`).

## Use when

- The deliverable is one physical part that will be manufactured or exported as
  one product item: a single solid body.
- The request names brackets, plates, enclosures bodies, shafts, spacers,
    bosses, flanges, blades, or any monolithic part geometry.
- An existing part source needs a geometry edit: new features, dimension
  changes, repaired booleans, or re-selected detail edges.

## Do not use

- Constrained editable profiles as the design intent: use
  `domains/sketch-and-features.md`.
- Multi-part products, connectors, or motion: use
  `domains/assembly-and-product.md`.
- Standard gears, ring gears, racks, cycloidal discs, or bearings: use
  `domains/standard-parts.md` first.
- Reading facts out of an existing STEP file: use
  `domains/step-inspection.md`.

## Inputs

- A refined brief with units (SDK evaluates lengths in millimeters), overall
  dimensions, named parameters, feature list, and validation targets
  (`domains/requirement-refinement.md`).
- A chosen part-local coordinate convention
  (`discipline/datums-and-coordinate-systems.md`).

## Outputs

- A positive-volume, closed `Solid`, or a `Part` via `make_part_rpart` when the
  product boundary is needed (`body=solid`).
- Semantic tags on mating/role surfaces and numeric facts in metadata.
- A replayable `GraphSession` model JSON when the flow must be replayable or
  interchange-exported.

## Required discipline

- `discipline/mechanical-modeling.md` before designing construction strategy.
- `discipline/feature-ordering.md` before composing operation order.
- `discipline/geometric-validation.md` for the validation gates.

## API groups

Read the exact page under `references/docs/api/` for every API used.
Before the first call, extract each page's signature, return type, and
documented failure modes into working notes — a method absent from the
page does not exist, however plausible it looks. Non-SDK dependencies
(Gmsh, CalculiX, VTK, FreeCAD scripting) are outside these pages:
consult their own documentation before the first call.

- Primitives: `make_box_rsolid`, `make_cylinder_rsolid`, `make_sphere_rsolid`,
  `make_cone_rsolid`.
- Profiles: `make_circle_rface`, `make_rectangle_rface`, `make_face_from_wire_rface`,
  `make_face_from_wires_rface`, `make_surface_patch_rface`,
  `make_ruled_surface_rface`, `make_gordon_surface_rface`,
  `make_cylindrical_surface_rface`.
- Editing an existing curve or surface (poles, weights, knots, degree, refit): `domains/curve-surface-editing.md`.
- An `Edge` is taken wherever a `Wire` is (a sweep path, a loft section, a face boundary): it becomes the wire of that
  one edge (recorded as `make_wire_from_edges_rwire`). Several edges make one wire only through an explicit
  `make_wire_from_edges_rwire([a, b, ...])` (in any order: they are chained by their ends). `loft_rshell` of two open
  curves is the surface between them (no end wires); `sew_faces_rshell` takes faces and shells (a shell as its faces).
- Features: `extrude_rsolid`, `revolve_rsolid`, `sweep_rsolid`,
  `twisted_sweep_rsolid` (supports inner-wire profiles), `helical_sweep_rsolid`,
  `loft_rsolid`, `loft_rshell`, `shell_rsolid`.
- Detail: `fillet_rsolid`, `chamfer_rsolid`.
- Face loops: `inset_face_rsolid(solid, face, distance)` imprints a planar face's loops moved inside it (the
  shape is unchanged; the face splits into roles `inset.inner` and `inset.ring`).
  `press_pull_rsolid(solid, face, distance)` pulls a planar face out (positive) or presses it in (negative);
  inset then press/pull builds steps, bosses, pockets and walls without a sketch.

## Boolean discipline

- `union_rsolid`, `cut_rsolid`, and `intersect_rsolid` accept mixed inputs
  (standalone `Solid`, lists, nested sequences) and return exactly one `Solid`.
- `union_rsolid` defaults to `glue=False` with a conservative scale-relative
  internal tolerance. If a union cannot produce exactly one merged solid it
  fails explicitly; do not silently pick one piece.
- If a single merged solid is required and union fails, adjust placement so the
  bodies really overlap (not merely touch), then recompute.
- Overshoot through-cut tools past the faces they enter and exit; coincident
  tool/target faces are a classic kernel failure.
- `cut_rsolid` skips non-intersecting tools by default
  (`skip_non_intersecting=True`); pass `skip_non_intersecting=False` for strict
  diagnostics — a skipped cut is never a completed feature.
- A cut can split a body (a slot through a bar leaves two parts) or consume it
  (a tool that encloses the whole body). `cut_rsolid` returns a `Solid` when
  one piece is left and, when the cut splits the body, every piece as a
  `list[Solid]` ordered by centroid (x, then y, then z); it never drops a piece.
  Pass `on_split="error"` where exactly one Solid is required. A tool that
  consumes the body still raises. `cut_rsolid_list(base, tools)` always returns
  a list (empty when nothing is left). The pieces are notebook values: a Part holds one solid, so
  `make_part_rpart(part_id=..., body=pieces)` with several pieces is an error;
  make one Part per piece in an Assembly, or union the pieces if they are one
  body. A solid is one closed volume: OCCT and STEP have no valid "one solid
  with several lumps".
- The pieces are a `scad.Pieces` (a list) and keep flowing: an operation that
  takes one shape (`translate_shape`, `shell_rsolid`, a further `cut_rsolid(pieces, tool)`,
  fillet, chamfer ...) runs on every piece and returns `Pieces` in the same order.
  A selector is resolved per piece without its cardinality; a piece it finds
  nothing on is kept unchanged, and `.exactly(n)` is checked over all pieces.
  `union_rsolid(pieces)` joins them. A plain list passed to `cut_rsolid` is still
  base-then-tools.

## One Part, one solid

- `make_part_rpart(part_id=scad.notebook_id(), body=bracket)`. A Part is the unit
  an assembly places, mates and gives connectors to, so it holds exactly one
  solid. Several solids (`bodies=`, a list of several pieces) are refused with a
  ValueError: make one Part per solid and put them in an Assembly (identity
  placements when they only sit together), or union / cut them into one solid.
- `part.body` is the Solid; `part.bodies` is that body as a one-element tuple
  (`Body.body_id` is `"body"`, `Body.solid`, `Body.name`).
- Solids that sit side by side while the model is built (a tool next to the body
  it cuts, the tools of a pattern before the cut, the pieces of a split cut) are
  ordinary notebook values, not a Part. A part notebook that ends with one open
  solid needs no product cell; with several open solids and no cell making the
  Part there is no product (`SeveralOpenBodiesError` names them): make the Part
  from the solid that is the part. The editor draws the open solids side by side
  ("N open solids") and its `use_as_product` makes the Part from the chosen one.
- Mass: `measure_part_mass_rmassreport(part)` (density from the part's material,
  or `density=`).

## Colours and names for people

- A part's display colour, opacity and name are one recorded operation:
  `part = scad.set_body_appearance_rpart(part, color=(0.9, 0.3, 0.2), opacity=0.6, name="Lid")`
  (the body id is `"body"`, the default). Colours are RGB floats
  in [0, 1], linear like `Material.color`. `None` keeps a value, `reset=True`
  clears all three first. Read back with `part.bodies[0].color` / `.opacity` / `.name`.
- The material colour is the default; the body colour overrides it for display
  only (preview, package scene, STEP surface colour of that solid). Mass and
  density never read it. STEP writes the colour and the body name, not the opacity.
- Name a face, an edge or a vertex with a tag; there is no second naming system:
  `block = scad.apply_tag_rselection(block, scad.ql.faces().where(...), "lid_seat")`
  (or `tag_prefix=` / `*_tag=` arguments of the operation that makes it). The
  name follows the face through later features (tags resolve through the
  recorded history) and is selected with `scad.ql.tag("lid_seat")`. The package
  keeps every tag on its entity; only `interface.*` tags are public names that
  consumers may rely on (`scadpkg-format.md`), so name a face other tools read
  `interface.<name>`.

## Validation gates

- After each major step print small QL-derived facts: selected face count, top
  face center, edge count, volume, bounding box.
- Validity is not positive volume, and `Solid` exposes no public
  `is_valid`/closure predicate: run BREP validity/closure diagnostics with
  `inspect_shape_rbrepinspection` / `inspect_step_rbrepinspection` from
  `simplecadapi.inspect.brep` (outside `GraphSession`), and check
  `Solid.get_volume() > 0` yourself. `Shell.is_closed` exists for shells.
- Verify every user-specified dimension with a targeted measurement, not only
  aggregate properties.

