# Reading order for a reviewer

The C++ tree is about 103,000 lines of code, docs and scripts (plus vendored and recorded data), written by AI agents
against the Python SDK 2.2.6. Reading it by directory is slow because the layers lean on a few ideas. Read the
conventions first, then the files below in order, then the per-area map at the end when you need the Python module an area
ports or the tests that hold it to account. File sizes are lines at the time of writing. The partition of the code into
reviewable pull requests is in [LANDING_PLAN.md](LANDING_PLAN.md).

Paths are relative to `src/cpp`.

## Conventions to know first

| Convention | In one paragraph | Where it is written down |
|---|---|---|
| **Error model** | Public operators throw `scad::Error`, which carries what happened, possible causes, how to fix, measurements, evidence; it renders to the same text as the Python `SimpleCADError`. Each operator has one static `ErrorSpec` and wraps its body in `guarded(spec, ...)`. OCCT exceptions are not `std::exception`: raw OCCT code is wrapped in `occt_guard`, which throws `KernelError`. | `include/scad/core/error.hpp`, `src/core/occt_guard.cpp`, CONTRIBUTING section 5 |
| **Handles vs entities** | A `Solid`, `Face`, ... is a cheap value handle (two `shared_ptr`) over a `TopoDS_Shape`. The semantic state (tags, lineage, metadata) lives in a shared *entity*; handles obtained from the same root share it, so a tag set through one handle is seen through the others. Nothing below the handle exists until it is enumerated (`faces()`, `sub(topods_shape)`). `wrapped()` is the escape hatch to the OCCT shape. | `include/scad/topo/shape.hpp`, ARCHITECTURE |
| **Recorder** | After building a result an operator calls `record_operation(OpRecord{...}, {result})`. With no recorder installed that is one thread-local pointer test. The reactive `Session` is a recorder: it turns the records into an operation DAG. | `include/scad/topo/recorder.hpp` |
| **Tags and lineage** | A tag is a `TagBinding` (Semantic Binding Schema 1.0: tag, entity, producer, evidence); the plain tag-name set a shape shows is a cache computed from the bindings. Tags survive modelling because lineage witnesses project source tags onto result entities through a topology delta. Operators never hand-roll this: they finish through the finalize layer. | `include/scad/topo/tagging.hpp`, `include/scad/semantic/finalize.hpp`, `autotag.hpp` |
| **Tracking** | `tracked_*` functions build a result with the OCCT algorithm the Python function used and ask the algorithm's history (Modified / Generated / IsDeleted, section edges) what became of each input sub-shape. The answer is a `TopoDelta` plus per-entity witnesses. A sub-shape is named by its *kernel id* (hash of `TShape` and `Location`); the recorder later rebinds those to stable per-root ids such as `face_3`. | `include/scad/semantic/tracking.hpp`, `src/semantic/tracking_*.cpp` |
| **Reactive graph** | Model parameters are `Var`s; arithmetic on them builds an expression DAG. Operators take `Scalar` (a number that may remember its expression) and the recorder keeps the symbolic arguments. `Session::set_var` then `recompute()` marks the dependent nodes dirty and re-runs only those through per-operator executors, skipping a node whose resolved parameters and input digests did not change. | `include/scad/reactive/expr.hpp`, `session.hpp`, `src/reactive/recompute.cpp` |

## The files, in order

1. **`ARCHITECTURE.md`, `docs/DEVIATIONS.md`.** Layer diagram, the "dependencies point down" rule, and the list of deliberate
   differences from Python ("compact internally, canonical at the boundary"). Look for: whether a difference you see in the
   code is already recorded.

2. **`include/scad/core/error.hpp` (216 lines), `src/core/occt_guard.cpp`.** The error model. Look for: who converts what
   (`guarded`, `raise_harness_error`, `occt_guard`, `rethrow_occt_failure`), the exception to `PyKind` mapping, and that
   `Error` derives from `ValueError`.

3. **`include/scad/core/scalar.hpp`, `value.hpp`, `coordinate_system.hpp`.** `Scalar` (a double plus optional expression),
   `Value` (JSON-like, insertion-ordered because Python dict order is observable), workplanes. Look for: how a symbolic scalar
   travels without being evaluated.

4. **`include/scad/topo/shape.hpp` (303 lines), `src/topo/shape.cpp`, `shape_tags.cpp`.** The handle/entity model. Look for: what
   is shared and what is copied, the "not thread-safe" note, how enumeration creates entities lazily.

5. **`include/scad/topo/tagging.hpp`, `delta.hpp`.** The tag data model and the `TopoDelta` / `SemanticDelta` types. Look for:
   validation in the factory functions (an invalid binding cannot be stored), and the `pending` graph/node ids that the recorder
   binds later.

6. **`include/scad/topo/recorder.hpp` (147 lines).** The hook every operator reports through; `OpRecord`, `RecorderScope`,
   `RecorderSuspend`. Look for: what is recorded (symbolic scalars, inputs, delta) and the `thread_local` current recorder.

7. **One whole operator: `src/ops/geometry/box.cpp` (72 lines), then `include/scad/semantic/finalize.hpp`.** The pattern every
   operator follows: `ErrorSpec`, `guarded`, `OutputTags`, a `tracked_*` call, one finalize call. Look for: that the operator
   contains no tag logic of its own.

8. **`include/scad/semantic/tracking.hpp`, `src/semantic/tracking_core.cpp` (508 lines), `tracking_booleans.cpp`,
   `tracking_blends.cpp`.** Where OCCT history becomes a delta. Look for: how lookups are done (the original brief asked for hash-based ones, so check for quadratic scans), what the
   code does when the kernel gives no evidence (the answer stays "unknown": nothing is guessed from geometry), and
   `history_query_count()` which the tests use.

9. **`src/semantic/finalize.cpp` (467 lines), `autotag.cpp`, `role_tags.cpp`.** Order of the finalize pipeline: validate role
   tags, project tracking evidence and source tags, attach the track summary, record, then apply role/result/prefix tags.
   Look for: that the order is the Python order, because error precedence depends on it.

10. **`src/ops/features/blends.cpp` (297 lines), `blend_diagnosis.cpp`, `extrusion.cpp`.** A feature operator with failure
    evidence. Look for: the diagnosis probes (why a fillet failed) and how a failing operator attaches a picture.

11. **`include/scad/reactive/expr.hpp`, `graph.hpp`, `session.hpp` (315 lines), `src/reactive/recompute.cpp`.** The engine. Look
    for: immutability and content-derived `expr_id`s (same ids as Python), the memo key (resolved params + input digests), and
    the `thread_local` active session.

12. **`include/scad/ql/selector.hpp`, `src/ql/resolve.cpp`.** The selector language: immutable values, compiled predicates, the
    resolve pipeline (candidates, predicate, incident-face constraints, order keys, limit, cardinality) and the failure text
    that lists what matched.

13. **`include/scad/io/serialize.hpp`, `docs/io.md`, `src/io/mesh_cache.cpp`.** The persisted byte format (`SCADSHAP` 1.0:
    BinTools bytes plus the semantic state per entity), the canonical JSON/hash pieces, and the process-wide bounded mesh cache.
    Look for: anything that changes persisted or hashed bytes.

14. **`include/scad/sketch/sketch.hpp`, `src/sketch/solver/newton.cpp`, `docs/sketch-solver.md`.** Sketch as a plain value; the
    in-house damped Gauss-Newton solver (analytic Jacobians by forward-mode autodiff, minimum-norm steps from a Jacobi SVD).
    Look for: DOF counting, the equation catalogue, and the documented differences from py-slvs.

15. **`include/scad/product/solver.hpp`, `src/product/solve.cpp`, `assembly.hpp`.** Parts, assemblies and the constraint solver
    (placement propagation from grounded components; couplings set a joint coordinate from another). Look for: strict versus
    best-effort mode and the structured errors that carry the residual inventory.

16. **`bindings/python/module.cpp`, `common.cpp`, `py_lifetime.hpp`, `bind_ops_features.cpp`.** The Python boundary: exception
    translation, `Value` conversion, GIL release (`unlocked`) and re-acquisition, shutdown-safe Python references. Look for:
    every `gil_scoped_release` and what it protects (CONTRIBUTING sections 6 and 7).

17. **`tests/python/ref.py`, `tests/cpp/test_main.cpp`, `tests/cpp/CMakeLists.txt`.** How the parity contract is checked: goldens
    recorded from 2.2.6, `close()` tolerances, one doctest executable per area.

## Per area: C++ source, the Python module it ports, its tests

The first column is a directory under `include/scad/<dir>` and `src/<dir>`. The Python modules are those of SDK 2.2.6; in
this tree they are forwarding modules, and the opening comment of most C++ files names the function it ports
(`// fillet_rsolid (operators/features.py)`; `grep -rn "operators/features.py" src` lists them). "C++ tests" are
`tests/cpp/<dir>/`, built as `test_<dir>`. "Parity tests" are `tests/python/`. "Old tests" are in `test/` and `tests/` at the
repository root and run against the native engine; the match is by subject (and by the briefs in `docs/briefs.md`), not a
generated cross-reference.

| Area | Ports (2.2.6 Python) | C++ tests | Parity tests | Old tests |
|---|---|---|---|---|
| `core` | `core.py` (CoordinateSystem), `errors.py`; `Scalar`/`Value` are new | `core/test_core.cpp` | `test_smoke.py` | `test_error_harness.py`, `test_math_helpers.py` |
| `topo` | `core.py` (shape wrappers, `TaggedMixin`), `topology/tagging.py`, `topology/model.py` (delta types) | `topo/` (3 files) | `test_smoke.py` | `test_rearchitecture_2_0_contract.py`, `test_topology_getter_contract.py`, `tests/test_topology_identity.py` |
| `kernel` | `kernel/ocp_{booleans,builders,cast,curves,features,transforms}.py` | `kernel/` (4 files) | - | `test_rearchitecture_2_0_kernel_builders.py`, `test_rearchitecture_2_0_kernel_transforms.py` |
| `semantic` | `topology/{tagging,autotag,tracking}.py`, `operators/_support.py`, `operators/selection.py` | `semantic/` (tagging, tracking behaviour, tracking golden, finalize, selection) | `test_semantic_tagging.py` | `test_tagging_refactor.py`, `test_operation_output_roles.py`, `test_tracking_data_models.py`, `test_graph_lineage.py` |
| `reactive` | `params/{expr,units,frame}.py`, graph half of `topology/model.py`, `recording/graph.py`, `runtime/params.py`, `math.py` | `reactive/` (expr, units, session, param ui, bspline fit) | `test_reactive_{expr,graph,math,params,session,units}.py` | `test_expr_graph.py`, `test_graph_model_api.py`, `test_model_json.py`, `test_notebook_params.py`, `test_tolerance.py` (tolerance stays Python) |
| `io` | `kernel/ocp_{mesh,export,brep_snapshot}.py`, `exporter/step.py`, `_internal/{shape_pickle,mesh,brep_region}.py` | `io/` (8 files) | `test_io_*.py` | `test_serialization.py`, `test_internal_mesh.py`, `test_brep_region_snapshot.py`, `test_native_canonical.py`, `test_product_exporter.py` |
| `ql` | `ql.py` | `ql/` (7 files) | `test_ql_{api,diagnostics,golden}.py` | `test_ql.py`, `test_error_diagnostics_blend_ql.py` |
| `render` | the VTK renderer of `inspect/brep` (`render.py`) | `render/test_render.cpp` | `test_render_soft.py`, `test_render_screenshot_routing.py` | `test_render_screenshot_multiview.py` (partly removed, see DEVIATIONS), `test_failure_evidence.py` |
| `sketch` | `sketch.py`, `sketch_solver/backend.py`, `sketch_diagnostics.py`, `operators/sketch.py` | `sketch/` (operators, solver) | `test_sketch_api.py`, `test_sketch_parity.py` | `test_sketch_api.py`, `test_sketch_closed_bspline.py`, `test_sketch_ellipse.py`, `test_sketch_histcad_constraints.py`, `test_error_diagnostics_sketch.py` |
| `surface` | surface functions of `operators/geometry.py`, `kernel/ocp_surfaces.py` | `surface/` (faces, shells, trim) | `test_surface_{errors,faces,shells,trim}.py` | `test_surface_api.py`, `test_periodic_loft_api.py` |
| `ops/geometry` | `operators/geometry.py`, `_support.py`, `_diagnostics.py` | `ops_geometry/` (7 files) | `test_ops_geometry_*.py` | `test_all_features.py`, `test_original_api_integration.py`, `test_helix_handedness.py`, `test_rational_volume_precision.py`, `test_rearchitecture_2_0_ops.py` |
| `ops/features` | `operators/{features,boolean,transform,limited_extrusion,section_features,draft}.py`, `_diagnostics.py` | `ops_features/` (6 files) | `test_ops_features_*.py`, `test_cut_rsolid_list.py` | `test_chamfer_angle.py`, `test_draft.py`, `test_limited_extrusion.py`, `test_section_features.py`, `test_deformation_features.py`, `test_shell_integration.py`, `test_error_diagnostics_{boolean,sweep_loft}.py`, `test_rearchitecture_2_0_{remaining_ops,structural_remaining,todo_ops}.py` |
| `std` | `std/{gear,bearing,chain,fastener}.py` | `std/` (3 files) | `test_std_*.py` | `test_stdlib_{bearing,chain,fastener,gear}.py` |
| `product` | `operators/product.py`, `product/{part,assembly,connector,constraint,material,placement,solver}.py`, `_internal/semantic.py` | `product/` (5 files) | `test_product_*.py` | `test_product_assembly.py`, `test_part_interface.py`, `test_part_builder.py`, `test_assembly_builder.py`, `test_error_diagnostics_assembly.py`, `tests/test_placement_stability.py` |
| `bindings/python` | the public names of `simplecadapi` (`operators`, `ql`, `std`, ...) | - | all of `tests/python` | the whole old suite; `test_public_api_surface.py`, `test_native_without_ocp.py` |
| `bindings/python/occt` | the `OCP` classes the kept Python layers call | - | `tests/wheel_smoke.py` | `test_wrapped_ocp.py`, `test_inspect_brep*.py` |

Not ported on purpose (stay Python): `translator/`, `inspect/`, `scene/`, `editor/`, `artifacts/`, `runtime/`, `build/`,
`params/tolerance.py`, `recording/serializer.py`. See ARCHITECTURE.
