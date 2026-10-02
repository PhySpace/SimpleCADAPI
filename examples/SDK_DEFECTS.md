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
