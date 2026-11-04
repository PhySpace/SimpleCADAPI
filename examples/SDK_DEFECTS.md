# SDK defects found while migrating the examples to notebooks

Each entry: symptom, trigger, root cause, status, fix direction. The example
that surfaced it is in brackets.

## 1. Expression ids were random, so `content_hash` was not reproducible [flange_plate]

- **Symptom:** two fresh `sca run --no-cache` of the same notebook gave
  different `content_hash` values.
- **Trigger:** any notebook whose geometry takes a `scad.var` (or an `Expr`).
- **Root cause:** `Const`/`Var`/`Expr` defaulted `expr_id` to a `uuid4`; the
  ids land in the feature graph, so the definition bytes changed per process.
- **Status:** fixed. A default id is now a digest of the node's content
  (`params/expr.py`, `_structural_expr_id`); test
  `test_default_expression_ids_derive_from_content`.
- **Fix direction:** done. Any id that ends up in a hashed artifact must be
  derived from content, never from `uuid`/`id()`/a counter.

## 2. A cached body encoded to other BRep bytes than the built one [flange_plate]

- **Symptom:** the second `sca run` (all cells `cached`) gave another
  `content_hash` than the first and the `--no-cache` runs; only the body blob
  differed, by three bytes.
- **Trigger:** a shape with zeros that OCCT reads back as `-0.0`, e.g. a
  radial pattern of 4 or 8 holes (a 90° rotation).
- **Root cause:** BinTools reading is not byte-idempotent (`+0.0` comes back
  `-0.0`). The cell cache pickles a shape as BinTools bytes, so a restored
  body writes different bytes than the body that was built.
- **Status:** fixed. `artifacts/brep.write_brep_bytes` writes the decoded
  shape, which is a fixed point; test
  `test_brep_bytes_are_a_fixed_point_of_decoding`. Not every shape has one
  after a single round; see defect 10.
- **Fix direction:** done. Hash the canonical form (the fixed point of
  decode→encode), never the first encoding of an in-memory object.

## 3. Overriding one variable of a multi-variable cell gave an opaque error [flange_plate]

- **Symptom:** `run_notebook(nb, overrides={"BOLT_PCD": ...})` failed inside
  marimo with `IncompleteRefsError`, listing setup-cell names.
- **Trigger:** a params cell that defines several variables, overriding only
  some of them.
- **Root cause:** an overridden cell does not run, so it cannot supply its
  other variables; the runtime did not check for this.
- **Status:** fixed. `runner._check_overrides` raises a `ValueError` naming
  the variables to override together. The guide and FTC convention now say to
  group parameters into cells by what is overridden together.
- **Fix direction:** done.

## 4. `radial_pattern_rsolidlist(count=...)` does not accept a `Var` [flange_plate]

- **Symptom:** passing `BOLT_COUNT` (a `scad.var`) as `count` fails; the
  notebook writes `count=int(float(BOLT_COUNT))`.
- **Trigger:** any pattern count kept as a parameter.
- **Root cause:** integer-valued operator parameters are typed `int` and are
  not lifted to expressions, unlike lengths and angles.
- **Status:** worked around (`int(float(...))`); the expression link to the
  count is lost in the feature graph.
- **Fix direction:** accept `Var`/`Expr` for integer parameters, checking the
  value is integral, and record the expression like the other parameters.

## 5. A later cell could not tag a shape made by an earlier cell [caplcd_enclosure]

- **Symptom:** `scad.apply_tag(shape=corner_rounds, ...)` in the product cell
  failed with "assignment scope is not produced by the active GraphSession".
- **Trigger:** any tag, selection or role operation on a shape that another
  notebook cell produced.
- **Root cause:** every cell records into a session of its own. Operator
  inputs from earlier cells are adopted (`GraphSession.owned_node`), but
  `_active_graph_node_for_shape`, which the tagging and selection paths use,
  only looked the node up and returned `None` for a foreign one.
- **Status:** fixed. The lookup adopts a node of the same graph when the
  session shares lineage (`operators/_support.py`); test
  `test_a_later_cell_tags_a_shape_from_an_earlier_one`.
- **Fix direction:** done. Every path that turns a shape into a graph node
  must go through `owned_node`, not `graph.get_node`.

## 6. A cut with many tools recorded a run-dependent topology delta [caplcd_enclosure]

- **Symptom:** `sca run --no-cache` gave another `content_hash` on every run;
  only the `topo_delta` of multi-tool `cut_rsolid` nodes differed (extra or
  missing entries, other face ids).
- **Trigger:** `cut_rsolid(body, [tool, tool, ...])` where a later tool
  modifies faces an earlier tool made (overlapping or adjacent tools). The
  same loop is in `intersect_rsolid`.
- **Root cause:** the cut runs one tool at a time and merges the step
  deltas. Step entries name faces by kernel hash, which comes from the
  shape's address. The intermediate results were freed while their entries
  were still pending, so an output face could reuse a freed face's address
  and a stale step entry resolved to it, depending on the heap.
- **Status:** fixed. Both loops keep every intermediate result alive until
  the merged delta is recorded (`operators/boolean.py`); test
  `TestMultiToolCut.test_the_merged_delta_is_the_same_on_every_run`. The
  flange plate's hash changed with it (its 8-hole cut had stale entries).
- **Fix direction:** done for the boolean loops. Longer term, topology ids
  should not be addresses at all; any code that keeps a kernel hash as a
  string must keep the shape alive as long as the string is used.

## 7. The cell cache outlives an SDK change [caplcd_enclosure]

- **Symptom:** after fix 6, cached runs still returned the old
  `content_hash`; only `--no-cache` showed the new one.
- **Trigger:** changing or upgrading `simplecadapi` without changing the
  notebook or its local modules.
- **Root cause:** the cache key covers the notebook's code, its local modules
  and the notebook id, not the library that computes the values.
- **Status:** open. Workaround: delete `__marimo__/simplecad/` (or run with
  `--no-cache`) after changing the SDK.
- **Fix direction:** put the SDK version, and in a source checkout a digest
  of the package sources, into `dependency_digest`.

## 8. An assembly could not be built over several cells [external_reference_gear_train]

- **Symptom:** `ProductNotFoundError: several top-level values have the
  notebook id` for an assembly notebook with a components cell, a
  constraints cell and a solve cell.
- **Trigger:** any assembly split into one cell per step, as the FTC
  "one block per cell" rule asks for.
- **Root cause:** `make_assembly_rassembly` fixes the assembly id, so every
  intermediate assembly has the notebook id, and the product rule demanded
  exactly one such value. (Parts do not hit this: their intermediates are
  solids.)
- **Status:** fixed. Of several values with the notebook id, the ones another
  cell reads are intermediates; the product is the one left
  (`runtime/projection.find_product`); test
  `test_an_assembly_built_over_several_cells_is_the_last_one`.
- **Fix direction:** done.

## 9. A non-primitive override can return another run's cached cells [u_link_motor_mount]

- **Symptom:** `run_notebook(nb, overrides={"P": Spec(a=5.0)})` after a
  default run returned the default run's values; `cache=False` gave the right
  ones.
- **Trigger:** overriding a variable with a value marimo cannot hash by
  content: a dataclass instance, a `scad.var`/`Expr`, any custom object.
  Numbers, strings and containers of them are safe.
- **Root cause:** marimo keys a cell on the content of its primitive refs and
  on the *code of the defining cell* for every other ref. An overridden
  variable has no run of its defining cell, so the key is the one of the
  default value and the cache restores the default run's result.
- **Status:** open. Workaround: override only with numbers and strings (the
  examples look specs up in a plain module by a string key).
- **Fix direction:** `runner._run` should hash every override value itself
  (canonical bytes, or the pickle digest) into the cell-cache key, or turn the
  cache off for the cells downstream of a non-primitive override; at minimum
  reject such overrides with a clear error.

## 10. Decoding a BRep can cycle instead of reaching a fixed point [u_link_motor_mount]

- **Symptom:** the cached run of `u_link.py` gave another `content_hash` than
  the fresh and `--no-cache` runs, with fix 2 in place; only the body blob
  differed.
- **Trigger:** chamfered or filleted bodies (here: chamfered triangular ribs).
  A few doubles move by an ulp on every BinTools read; the encodings settle
  only after two rounds, or alternate between two encodings forever.
- **Root cause:** fix 2 assumed one decode round reaches a fixed point. A
  restored body has been decoded once more than the built one, so on a
  shape whose orbit has a longer lead-in or a 2-cycle the two still wrote
  different bytes.
- **Status:** fixed. `write_brep_bytes` decodes until an encoding repeats and
  returns the smallest encoding of the cycle (bounded to 8 rounds); test
  `test_brep_bytes_settle_when_decoding_cycles`. Content hashes of bodies
  that already settled after one round are unchanged.
- **Fix direction:** done. Longer term, a canonical form that does not depend
  on reader round-trips (e.g. normalising doubles while writing) would be
  cheaper than iterating.

## 11. `ql.and_` was typed to return a plain callable [u_link_motor_mount]

- **Symptom:** `ty check` rejected `ql.faces().where(ql.and_(...))`, the
  documented selector idiom: `where` takes a `SerializablePredicate`, and
  `and_` was annotated `-> Predicate` (`Callable[[Any], bool]`).
- **Trigger:** any type-checked script that combines predicates with
  `and_`/`or_`/`not_` before `ShapeSelector.where`.
- **Root cause:** the combinators return a `SerializablePredicate` when every
  input is one, but the annotation only named the general case.
- **Status:** fixed. `and_`, `or_` and `not_` carry overloads mapping
  serializable inputs to a serializable result (`ql.py`).
- **Fix direction:** done.

## 12. Scripts must narrow `run.product` before using it [u_link_motor_mount]

- **Symptom:** `run_notebook(...).product.body` and
  `.product.component_ids()` fail type checking: `product` is
  `Part | Assembly`.
- **Trigger:** every export or verify script.
- **Root cause:** `NotebookRun.product` has the union type; the script knows
  which kind the notebook makes, the type does not.
- **Status:** open. Workaround: `assert isinstance(run.product, scad.Part)`.
- **Fix direction:** typed accessors on the run (`run.part`, `run.assembly`)
  that raise a clear error on the other kind.

## 13. `build_ball_bearing(fuse_rolling_elements=False)` always failed [compact_two_stage_planetary_reducer]

- **Symptom:** the durable standard bearing with separate balls raised
  `definition_id_mismatch: expected '<id>_ball_00', got '<id>_ball'`; past
  that, `duplicate assembly id in active GraphSession`.
- **Trigger:** any `scad.std.bearing.build_ball_bearing(...,
  fuse_rolling_elements=False)` call. Only the fused default was tested.
- **Root cause:** the ball definition was named after the component
  (`ball_00`) instead of the part the factory makes (`<id>_ball`), and the
  assembly body called the factory again to read the ball layout, which
  added a second assembly with the same id to the build session.
- **Status:** fixed (`std/bearing.py`): the ball definition id is the
  factory's part id, and the layout is computed with the factory's own
  helpers. Test `test_durable_bearing_keeps_separate_balls`.
- **Fix direction:** done.

## 14. `build_ball_bearing(material=...)` rejected a material made in a notebook cell [integrated_bldc_joint_actuator]

- **Symptom:** `assign_material_rpart` failed with `value contains graph
  node '...' from graph 'integrated_50mm_bldc_joint_actuator', active graph
  is 'rear_motor_8x16x5_outer_ring'`.
- **Trigger:** an assembly notebook cell that makes a material and passes it
  to `scad.std.bearing.build_ball_bearing(material=...)`. More generally: any
  material recorded in a `GraphSession`. Planetary passes no material, and
  the old module code made its material outside any session, so neither
  case hit it.
- **Root cause:** the factory builds each ring in its own build graph, but
  the material still carried the caller's graph node, and graph ownership
  checks reject foreign lineage.
- **Status:** fixed (`std/bearing.py`): the factory passes the material by
  value, as a copy without lineage. Test
  `test_durable_bearing_accepts_material_recorded_in_caller_graph`.
- **Fix direction:** in general, any standard-library factory that opens its
  own build graph must take plain semantic inputs (materials, specs) by
  value. A shared helper in `std` would keep the next factory from
  repeating this.

## 15. Shape transforms and `apply_tag` lose the shape kind in their types [planetary, integrated_bldc_joint_actuator]

- **Symptom:** `ty check` on the example modules reports `expected Solid,
  found Vertex | Edge | Wire | ...` wherever a helper returns, or passes to
  `union_rsolid` / `cut_rsolid`, the result of `rotate_shape`,
  `translate_shape`, `mirror_shape` or `apply_tag`.
- **Trigger:** any typed helper `-> scad.Solid` that rotates or tags a solid.
  The code is correct at runtime; only the static types are wrong.
- **Root cause:** these functions are annotated `(shape: AnyShape, ...) ->
  AnyShape`, so the caller's `Solid` widens to the whole shape union.
- **Status:** open (not blocking: examples are not type-check gated).
- **Fix direction:** a `TypeVar` bound to `AnyShape`
  (`def rotate_shape(shape: S, ...) -> S`), so the kind passes through.

## 16. BRep decode orbits can be longer than the settle bound, or never settle [l_link_motor_mount]

- **Symptom:** `sca run l_link.py` failed at projection with `brep_invalid at
  /body: BRep encoding did not settle within 8 decode rounds`. With the bound
  raised, the `center4` adapter plate still failed at 32 rounds.
- **Trigger:** the chamfered cross ribs on the swept L rod need 9 decode
  rounds before they enter their 2-cycle (earlier stages settle in 1–2
  rounds). The `center4` plate (filleted disk plus the star key) never
  settles: three near-zero doubles (~1e-16, ~1e-32) keep drifting, still
  after 200 rounds. The old pre-notebook chains give the same orbits, so this
  is the geometry, not the conversion.
- **Root cause:** fix 10 assumed every orbit reaches a cycle, and bounded the
  search at 8 rounds on the assumption that it does so within two. A restored
  shape only encodes like the built one if both orbits reach the same cycle.
- **Status:** fixed. A wrapper decoded from bytes (cell-cache pickle in
  `_internal/shape_pickle.py`, package blob in `read_brep_solid`) remembers
  them, and `write_brep_bytes` starts the orbit there, so a restored shape
  walks the built shape's orbit. A shape that does not settle within 32
  rounds is written as its first encoding. Re-pickling a restored shape
  stores the remembered bytes. Test
  `test_brep_bytes_agree_when_decoding_never_settles`. Hashes of shapes that
  settled before are unchanged.
- **Fix direction:** the same as for 10: a canonical encoding that does not
  depend on reader round trips would remove the iteration entirely. A cell
  that re-runs on a restored input (a changed override downstream of cached
  cells) still computes from the decoded shape, which can differ by an ulp
  from the built one.

## 17. A cell with branch-local temporaries is silently not cached [l_link_motor_mount]

- **Symptom:** a run logged `Cache save failed for <cell>: ... Cache expected a
  reference to a variable that is not present (_cell_<id>_relief)` and went on;
  the cell re-ran on every run.
- **Trigger:** a cell that binds a `_`-prefixed temporary in only one branch of
  an `if` (here `_relief` only for the `star3` preset), run with the other
  branch taken.
- **Root cause:** marimo's persistent cell cache collects the cell's local
  names statically and expects every one of them when it saves; the runtime
  passes the warning through.
- **Status:** worked around in the example: the branch-only tools moved to
  `@app.function` helpers, so the cell binds the same names on every path.
- **Fix direction:** have the runtime report a cell that could not be cached
  (in the run report and the CLI), and teach the rule in the FTC skill: a
  cell binds the same names on every path.

## 18. `sca run --no-cache` cannot run from a read-only notebook directory [flange_plate]

- **Symptom:** `sca run flange_plate.py --no-cache` in a read-only copy of the
  example fails with `PermissionError: ... __marimo__/simplecad/flange_plate.py/flange-plate/deps.json`
  (exit 2). With a read-only `HOME` and a writable notebook directory the run
  succeeds; marimo and matplotlib only warn and fall back.
- **Trigger:** any run (`cache=False` included) where the notebook directory is
  not writable: a mounted read-only checkout, an installed package, a sandbox.
- **Root cause:** `runtime/runner.py` `_run` calls `write_dependencies(config, ...)`
  unconditionally; `cache=False` skips only the cell cache, not the dependency
  record under `state_dir(config)`.
- **Status:** not fixed (found while answering a runtime question; not blocking).
- **Fix direction:** with `cache=False`, skip writing `deps.json` (nothing reads
  it without the cache), or treat a failed state write as a warning; optionally
  let the state directory be relocated (e.g. an env var or a `--state-dir`).

## 19. The executor raised on any cell that is not in the notebook [editor]

- **Symptom:** in the editor kernel, every scratch snippet (the bridge's
  `execute`) failed with `KeyError: '__scratch__'`.
- **Trigger:** a notebook with `[tool.simplecadapi]` running under marimo's
  editor, then any cell marimo runs that the notebook does not contain.
- **Root cause:** `SimpleCadExecutor` looked the cell's key up in the notebook
  cells without checking that the cell belongs to the notebook.
- **Status:** fixed. `NotebookCells.__contains__`; the executor delegates such
  cells to marimo's default executor. Test:
  `test_scratch_cells_are_not_recorded`.
- **Fix direction:** done. The headless runner only ever runs notebook cells, so
  only the editor kernel could hit it; test in a kernel, not only headlessly.

## 20. `ql.vertices()` found nothing on a solid or a face [editor]

- **Symptom:** `scad.ql.vertices().resolve(solid)` returned no vertices, so a
  selector for a picked vertex raised "expected exactly 1 vertex(s), got 0".
- **Trigger:** resolving `ql.vertices()` against a Solid, Face or Wire; only an
  Edge scope worked.
- **Root cause:** `_resolve_scope_items` looked only at the scope's direct
  children for vertices, and a solid's children are shells.
- **Status:** fixed. It falls back to the vertices of the scope's edges
  (`_boundary_items`); test `test_vertices_resolve_through_a_solid_and_a_face`.
- **Fix direction:** done. Every `ql` factory should resolve against any scope
  that contains its kind; check each (kind, scope) pair when adding a factory.

## 21. Surface points and sketch positions cannot be expressions; the cylinder's U is radians [types-surface-sketch]

- **Symptom:** `make_bezier_surface_rface`, `fit_point_grid_rface` and the `points` of `make_surface_patch_rface` refuse a
  `scad.var` coordinate, and so do the `(x, y)` positions of `trim_rsketch` / `add_bspline_rsketch` control points; the
  origin of `make_cylindrical_surface_rface` and `add_point_rsketch` accept one.  `make_cylindrical_surface_rface`
  takes `u_range` in raw radians, where every other angle of the SDK (`Angle`) is degrees.
- **Trigger:** typing the surface and sketch signatures (`simplecadapi.types.Point3` / `Point2`): the same meaning has
  two loaders, `scad::Vec3` (doubles) and `std::array<Scalar, 3>` (expressions).
- **Root cause:** `PointGrid` / `SurfacePatchOptions::points` are `Vec3`, and `SketchPosition` / `SketchControlPoint`
  hold doubles; the cylinder range is passed to OCCT unconverted.
- **Status:** open. The signatures now say what each parameter means; the loaders are unchanged (no behaviour change).
- **Fix direction:** make the surface grids `std::vector<std::vector<ScalarVec3>>` (evaluate at build time, as the
  cylinder does) and let sketch positions take `Scalar`; give the cylinder a degree `Angle` range (keep `u_range` as a
  deprecated alias).

## 22. `phase_offset` of the gear, belt and rack-pinion constraints is a length, and nothing said so [catalog]

- **Symptom:** next to `drive_angle_degrees`, `phase_offset` reads like an
  angle; a GUI or agent would pass degrees.
- **Trigger:** `add_gear_constraint_rassembly(..., phase_offset=...)` (also
  belt, rack_pinion).
- **Root cause:** the coupling phase is `r_a * theta_a + r_b * theta_b`
  (`coupling.cpp: phase_from_supports`), an arc length on the pitch circle in
  mm; the binding took `py::object` and the docstring did not say.
- **Status:** the signature now says `phase_offset: Length | None`.
- **Fix direction:** say "pitch-circle arc length (mm)" in the docstrings too;
  consider renaming to `phase_offset_length` in a major version.

## 23. The std bindings are registered before the product classes [catalog]

- **Symptom:** `simplecadapi._cpp.std.bearing.make_ball_bearing_rassembly`
  prints its return type as `scad::product::Assembly` (the C++ name); a
  `Material` argument cannot take its name from the registered class.
- **Trigger:** `bind_std(m)` runs before `bind_product(m)` in `module.cpp`; pybind
  writes the signature when the function is defined. Likewise `bind_semantic`
  runs before `bind_ql`, so `apply_tag_rselection` spells out `ShapeSelector`.
- **Root cause:** registration order.
- **Status:** open; the names are written out where needed. The C++
  `std.bearing.make_ball_bearing_rassembly` is also shadowed by the Python one
  in `simplecadapi.std.bearing` (two implementations of one operation).
- **Fix direction:** bind the value classes (product, ql) before any operation
  that uses them; drop one of the two bearing factories.

## 24. `catalog.classify` read a union that starts with `Literal[` as one Literal [catalog]

- **Symptom:** `Literal['auto', ...] | tuple[Angle, Angle]` gave the choices
  `"rear_left'] | tuple[Angle"` and `'Angle'`.
- **Root cause:** the `Literal[...]` / `Sequence[...]` / `Annotated[...]`
  regexes were `fullmatch`ed on the whole union text.
- **Status:** fixed. Unions are split first; a union of bracketed members is
  the members' kinds joined (`enum|numbers`, `query|shape`, `solid` many for
  `Solid | Sequence[Solid]`). Also new: `path`, `scalar_limit`, `<kind>_map`
  for `dict[str, X]`, and str-enum defaults (`<E.X: 'x'>` -> `'x'`).
- **Fix direction:** done.

## 25. Style and view strings are case-insensitive, the signatures list one spelling [catalog]

- **Symptom:** `make_bolt_rsolid(head_style="HEX")`, `render_screenshot_rpath(view="Top")` work, yet the signature
  says `Literal['hex', ...]` / `Literal['top', ...]`.
- **Root cause:** `stdlib::choice` and `view_preset` lower-case the value before matching.
- **Status:** open by choice: the Literal lists the canonical spellings (what a form offers); the runtime still
  accepts any case. `apply_tag_rselection`'s enums are case-sensitive.
- **Fix direction:** pick one rule for every string enum of the SDK.

## 26. Angle units and expression support are not uniform across operations [types]

- **Symptom:** `make_angle_arc_redge` / `_rwire` take `start_angle` and
  `end_angle` in radians, while every other angle (`revolve_rsolid`,
  `rotate_shape`, `chamfer_rsolid(angle=)`, `draft_rsolid`, patterns, sweeps)
  is in degrees. `chamfer_rsolid(angle=)` and `offset_rsolid(tolerance=)`,
  `union_rsolid(tol=)` take a plain float: a `scad.var` is read as its current
  value.
- **Trigger:** passing `90` (meant as degrees) to an angle arc gives a
  different arc; a `scad.var` given as a chamfer angle is recorded as its
  value, not as the expression.
- **Root cause:** the arc follows OCC's `GC_MakeArcOfCircle` parameter
  directly; `ChamferOptions::angle` is `std::optional<double>`.
- **Status:** open. The signatures now say it: the arc angles are a plain
  number (not `Angle`) and the docstring says radians; the chamfer angle
  prints `Angle` but is loaded as a float.
- **Fix direction:** a breaking change for the arc (degrees, with a
  deprecation path), and `Scalar` for the chamfer angle so it records an
  expression like the other parameters.

## 27. `Compound([solids])` silently drops the solids' tags [multi-solid research]

- **Symptom:** `scad.Compound([a, b])` of two tagged boxes has no face tags;
  `compound._copy_semantic_state_from(a)` copies nothing either.
- **Trigger:** any code that bundles solids into a Compound and later selects
  by tag (the first multi-body spike stored a part's bodies as one Compound).
- **Root cause:** a Compound is a new shape root with its own entity registry;
  the semantic state of the input roots is not carried over, and the copy
  helper only works within one root.
- **Status:** open. Multi-body parts keep their bodies as separate Solid roots
  (`Part.bodies`), so they are not affected; `product.bodies.part_shape`
  documents that its Compound is a geometry view without tags.
- **Fix direction:** either carry tags into a Compound built from tagged
  roots (sub-shapes are shared, so the mapping is exact), or refuse
  `_copy_semantic_state_from` across roots instead of doing nothing.

## 28. Value pickling reads constructor arguments back by attribute name [multi-solid research]

- **Symptom:** adding `Part(bodies=...)` broke pickling of multi-body parts:
  the reducer called `part.body`, which (rightly) raises for several bodies.
- **Trigger:** any product value whose constructor parameter is not a plain
  readable attribute of the same name.
- **Root cause:** `_glue/values.py` parses the parameter names out of the
  pybind11 `__init__` docstring and reads each back with `getattr`.
- **Status:** worked around: `_ARGUMENTS` maps a class to per-parameter
  readers (Part: `body`/`bodies`).
- **Fix direction:** give the C++ values an explicit `__getstate__`/
  `py::pickle` (as `ql` selectors have) instead of docstring parsing.

## 29. "One solid per definition" is spelled into ids and kinds [multi-solid research]

- **Symptom:** a second body of a part has nowhere to live in the existing
  names: entity ids are `entity/<definition>/<kind>/<topo>` with root-local
  topo ids (every body has a `face_0`), preview nodes are one per part, and
  the definition kind is called `single_solid` (about 20 places in Python).
- **Trigger:** any part with more than one solid.
- **Root cause:** "is a part" and "has one solid" were the same fact until
  now.
- **Status:** worked around: bodies get an id segment `body:<body_id>`
  (`entity/<part>/body:<id>/...`, `node/<part>/body:<id>`), one-body parts
  keep their old ids byte for byte; the kind stays `single_solid`.
- **Fix direction:** treat `single_solid` as the name of the part kind (rename
  at the next package schema bump) and keep the `body:` segment the only
  way to address a body.

## 30. Error guidance is frozen by parity goldens [multi-solid research]

- **Symptom:** the `make_part_rpart` guidance still says "Union intended multiple bodies into one Solid before
  creating the Part.", which is wrong now that `bodies=` exists; changing it fails
  `src/cpp/tests/python/test_product_values.py::test_part_creation_and_errors`.
- **Root cause:** the C++ port compares every error's `what_happened` / `possible_causes` / `how_to_fix` with goldens
  captured from the old Python SDK (`tests/golden/product_*.json`), so guidance cannot follow the API.
- **Status:** open; the old text is kept.
- **Fix direction:** compare error *codes* and kinds against the goldens, and let guidance text change with the API
  (or regenerate the goldens on a deliberate API change).

## 31. Face tags died at the next operation, op-kwarg ones at blends and copies [stable-refs research]

- **Symptom:** a plain `apply_tag_rselection` face tag was gone after any later operation; an op-kwarg face tag
  (`top_face_tag=`) survived booleans but not fillet, chamfer, translate, mirror or patterns, although those nodes
  record a witness for every face.
- **Root cause:** tags were copied forward per operation (`autotag.cpp`) through channel-specific gates (the
  face-source gate, the face channel of blends), and the effective scope excluded lineage.
- **Status:** fixed. Tags are a view over the recorded history (`scad/reactive/tag_view.hpp`): a recorded tag
  assignment reaches every entity its targets became, per lineage policy, and effective includes lineage.
  Audit: `test_element_ref_history.py::test_audit_tag_channels_and_history_per_family` (every family 1/1).

## 32. `OperationGraph::from_value` header said deltas are not restored; they are [stable-refs research]

- **Symptom:** `include/scad/reactive/graph.hpp` commented "topology/semantic deltas are not restored" while
  `graph.cpp` `from_value` parses `topo_delta` and `semantic_delta`.
- **Status:** fixed (comment), and pinned: `test_tags_and_references_resolve_on_values_restored_from_the_cell_cache`
  restores a cell's lineage record in a fresh process and resolves a tag and a reference through its deltas.

## 33. A shell's kept faces had no successor witness [stable-refs research]

- **Symptom:** after `shell_rsolid(box, [bottom], t)`, the untouched top face had only a `generated` witness (its
  offset face); history could not say the top face was still there, and `body_faces_tag` always raised.
- **Root cause:** `tracking::query_history` emitted `preserved` only when an input had neither `Modified` nor
  `Generated` images; a kept shell face generates its offset face.
- **Status:** fixed (owner decision, option a): `preserved` is also emitted when the input is still in the result.
  Goldens and assertions reviewed one by one (design 7.2): shell kept faces and rim edges, and the profile edges
  that bound an extrude / loft start cap, gain a preserved witness.

## 34. `transform_rsolid`, `offset_rsolid`, draft and scale recorded no topology delta [stable-refs research]

- **Symptom:** a face reference or tag through these ops could not be followed (`lost(no_history)` in the
  resolver).
- **Root cause:** they finish through `finish_solid`, which recorded no delta, although the OCCT makers behind them
  (`BRepBuilderAPI_Transform` / `GTransform` after a `Copy`, `BRepOffsetAPI_MakeThickSolid`,
  `BRepOffsetAPI_DraftAngle`) expose `Modified` / `Generated`.
- **Status:** fixed. `modification_delta` (`src/semantic/tracking_modify.cpp`) turns the retained OCCT history into
  face and edge witnesses (copy and transform merged into one history; an offset or drafted face, which OCCT reports
  as generated, continues its source); `finish_solid` records it. Tests: `test_modification_delta.cpp`,
  `test_element_ref_history.py::test_history_through_operations_that_had_none` and the draft test. The helical
  sweep was never a gap: inside a session it records its helix, face and sweep nodes, and the sweep is tracked
  (`test_a_helical_sweep_cap_is_anchored_by_the_sweep_it_records`).

## 35. Two spellings of one topo id [stable-refs research]

- **Symptom:** a recorded delta names a face `face_face_5`; the entity's own `topo_id` is `face_5`; `get_metadata(
  "topo_ref")` re-prefixes on the fly (`bind_topo.cpp`) and `index_output_entities` builds the long form.
- **Root cause:** the Python SDK's text form was kept for parity.
- **Status:** open, harmless but every consumer must know which form it holds (`subshapes_by_recorded_id` takes the
  recorded form).
- **Fix direction:** one canonical form at the next graph schema version.

## 36. A reference into a face, shell or edge body could not resolve [nurbs editing]

- **Symptom:** `element_ref.resolve(anchor, face)` on a bare Face (a surface body, not a solid) raised
  `TypeError: cannot resolve QL selector scope for target_kind=solid`.
- **Root cause:** `_bodies_of` (`topology/element_ref.py`) asked `ql.solids()` of every non-Solid shape to find the
  body of each resolved entity; a Face or Shell has no solid scope at all.
- **Status:** fixed: only a Solid or a Compound is searched for bodies; the entities of a Face / Shell / Wire / Edge
  report body `None`. Test: `test_surface_editing.py::test_tags_and_references_follow_a_face_and_its_edges_through_edits`.

## 37. Curve / surface edits existed only as unrecorded in-place mutation [nurbs editing]

- **Symptom:** a control-point edit had to go through `simplecadapi._cpp.occt` (`Geom_BSplineSurface.SetPole` ...)
  on the handle the shape shares, mutating it in place: not recorded, not replayable, and every other shape sharing
  that geometry changed with it (design-docs/nurbs-editing-capability.md).
- **Status:** fixed for the core edits: `set/move_*_poles`, `set_*_weights`, `insert_*_knot`, `elevate_*_degree`,
  `convert_to_bspline_*`, `rebuild_*` are recorded operations returning a new shape on an edited copy of the geometry
  (`src/cpp/src/surface/editing`). The private OCCT setters are still reachable and still mutate shared geometry;
  they should be hidden from the compat layer once nothing internal uses them.
- **Open:** a face that is part of a shell or solid is edited alone (the result is a free face); propagating an edit to
  the neighbouring faces of a body (keeping the shell closed) needs a whole-body rebuild op.

## 38. A colour's colour space was never written down [body appearance]

- **Symptom:** `Material.color=(0.9, 0.2, 0.1)` came out of STEP as `COLOUR_RGB(0.955, 0.485, 0.349)`, and the old
  editor ignored material colours (a fixed tint per `material_id`).
- **Root cause:** the STEP writer hands the numbers to OCCT as `Quantity_TOC_RGB` (linear RGB), which STEP stores as
  sRGB; nothing said which space the SDK means, and the reader (`import_step`) gives linear values back, so a round trip
  is consistent while a person who typed sRGB numbers sees a lighter colour.
- **Status:** documented, not changed: an SDK colour (`simplecadapi.types.Color`, `Material.color`, a body colour) is
  linear RGB in [0, 1], as OCCT and three.js (its working space) read it. The editor's picker converts its sRGB
  `#rrggbb`. Changing to sRGB would move every existing STEP colour.
- **Fix direction:** if sRGB is wanted (what people type), switch the writer and reader to `Quantity_TOC_sRGB` together
  and say so in the type.

## 39. `apply_tag_rselection` returned an untyped `object` [body appearance]

- **Symptom:** the only operation in `sca ops` whose result kind was `object`; the editor could not tell what the
  "name a face" form makes.
- **Status:** fixed: the binding names the result `AnyShape`.

## 40. The generic op form dropped picked selections [body appearance]

- **Symptom:** `op.fillet_rsolid` (and every `op.*` with a `select` slot) wrote the call without its edges/faces.
- **Root cause:** the builder skipped every slot without a value; a selection is picked, not a value.
- **Status:** fixed (`editor/op_specs.py`); `test_a_picked_selection_is_passed_to_the_operation` covers every such op.

## 41. Person-facing face names and package names are two tiers of one tag system [body appearance]

- **Symptom:** a face named `lid_seat` in the editor is kept on its entity in the package, but only `interface.*` tags
  enter the package's public `name_index`.
- **Status:** by design (no second naming system); the skill says to name a face other tools read `interface.<name>`.
- **Fix direction:** if people need public names without the prefix, a `public=True` on the tag op rather than a new
  naming scheme.

## 42. A one-body Part pickles its default body as a bare Solid [body appearance]

- **Symptom:** a one-body Part whose body has a name or colour lost them through pickle (the cell cache).
- **Root cause:** `_glue/values.py` rebuilt a one-body Part from `Part.body` (the Solid), not its `Body`.
- **Status:** fixed: such a Part is rebuilt from `bodies`; a plain one-body Part keeps the old reduction (same bytes).

## 43. Recording a pick re-stamps the picked entity of the value it was picked from [public refs]

- **Symptom:** in the editor, a shell feature picked the top face of `base`; a groove feature cut `base` afterwards, and
  the top face's history through the cut named the *shell's* selection node as its parent, a node not upstream of the
  groove: the reference into `base` was `lost(no_history)` at the cut.
- **Root cause:** `Session::record_geo_selection_nodes` records the selection with the picked handle as its output, and
  the handle shares its entity state with the source value, so the entity's `topo_ref` now names the selection node.
  Every later operation on the source value records that node as the parent.
- **Status:** worked around in the resolver (`element_ref.cpp` `through_foreign_identity`: a parent named by a
  registered selection/tag node outside the walk stands for the entity of its source);
  `test_a_pick_made_by_a_later_cell_does_not_hide_the_history_of_the_value_it_read`.  The tag view
  (`tag_view.cpp`) reads the same parents and is not worked around.
- **Fix direction:** a selection node's output should be a copy of the handle (its own entity state), never the
  source's entity.

## 44. Booleans record no history for the edges of their inputs [public refs]

- **Symptom:** a box edge picked before a cut was `lost(no_history)` at the cut; fillets after any boolean could not
  use an edge reference anchored on the edge itself.
- **Root cause:** `tracking_booleans.cpp` asks OCCT's history for the faces of every input only (edges: only the
  section edges, as generated).
- **Status:** designed around: `scad.ref.of(edge, shape)` names an edge by the two faces it lies between
  (`between=("box.front", "box.top")`), which every operation does track, and it reads better.  Edges of a seam (one
  face) still anchor on themselves.
- **Fix direction:** query edge history in booleans too (goldens of every boolean change; review them one by one).

## 45. A notebook cell's node namespace was the hash of its code [public refs]

- **Symptom:** a stable reference names its node by the feature (the node id's namespace); a notebook cell's namespace
  was `c<sha256(code)[:8]>`, so a GUI edit of the referenced feature (its `# gui:` line changes) moved every node to a
  new namespace and every reference into it was `lost(anchor_missing)`.
- **Status:** fixed: a feature cell's key is `<slug>.c<digest>` (`runtime/cells.py`) and `node_feature` drops what follows
  the dot.  A plain cell (no `# ---- feature:` header) still has a code-hash feature, so references into hand-written
  cells break when the cell's code changes; give such a cell a feature header.

## Heuristics

- Run every notebook three times: fresh, all cached, `--no-cache`. The three
  `content_hash` values must be equal; any difference is a determinism bug.
  Diff the definition blobs to find which artifact moved.
- When a value is cached by serializing it, check that
  `encode(decode(encode(x))) == encode(x)`; floats (signed zeros, NaN
  payloads, printed precision, ulp drift) are the usual culprits. Iterate a
  few rounds: an orbit can need more than one round, or cycle (defect 10).
- Grep for `uuid`, `id(`, `time`, and module-level counters on any path that
  feeds a hashed artifact.
- When a parameter cannot be passed as a `scad.var`, the operator is missing
  expression lifting for that parameter type; note the cast as a defect.
- Run a notebook twice in one process with `cache=False`: heap-dependent
  identities (addresses, `hash()` of kernel shapes) show up as different
  hashes there, where separate fresh processes may happen to agree.
- Override with a non-primitive value once with and once without the
  cache: a different result is a cache-key hole (defect 9).
- After changing the SDK, clear the notebook state before comparing hashes
  (defect 7).
- Use values from one cell in another cell's tags, selections and
  connectors, not only in operators: those paths look up graph nodes too.
