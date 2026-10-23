# Area briefs

Condensed work orders for each area. Every one assumes the reader has first read
`ARCHITECTURE.md` and `AGENTS.md`. They are what the first wave of parallel engineers was given;
reuse them verbatim to resume an area, adding "continue from the code already in your area:
read it first, then finish what is missing". Reference Python: `../SimpleCADAPI/src/simplecadapi`
(read-only), tests in `../SimpleCADAPI/test`.

Rules for every area: own only your directories; build only your own targets in your own build
dir (`build/<area>`, `ninja -j4`); no git; no questions (decide, document); end with a report.

## semantic (tags)
Own `include/scad/semantic/` (except `tracking.hpp`), `src/semantic/` (except `tracking_*`),
`bindings/python/bind_semantic.cpp`. May replace internals of `src/topo/shape_tags.cpp` and
`SemanticState` (keep `Shape` signatures). Port: `core.py` TaggedMixin (l.411-910) and
`topology/tagging.py` (binding factories, TagPolicy, lineage policy); `topology/autotag.py`;
the semantic half of `operators/_support.py` (l.~1448-2260: finalize pipeline, role tags,
tag_prefix, `_apply_tag_rselection`) as `finalize.hpp` with one-line call sites for operators;
public tag operators of `operators/selection.py` (+ bindings, tag data classes). Tests: port
`test_graph_lineage.py`, `test_operation_output_roles.py` and the tagging tests.

## tracking (kernel builders)
Own new files in `src/kernel/`, `include/scad/kernel/`, `include/scad/semantic/tracking.hpp`,
`src/semantic/tracking_*.cpp`, `tests/cpp/kernel/`. Port `kernel/ocp_{booleans,builders,curves,
features,transforms,cast}.py` and `topology/tracking.py` in full (history queries -> TopoDelta;
`tracked_box/cylinder/cone/extrude/revolve/fillet/chamfer/shell/loft/sweep/twisted_sweep/
translate/rotate/mirror/cut/union/intersect`, `TrackingPolicy`). Hash-based lookups, no O(n^2).

## sketch
Own `include/scad/sketch/`, `src/sketch/`, `bind_sketch.cpp`. Port `sketch.py`,
`sketch_diagnostics.py`, `sketch_solver/` (backend interface + py-slvs backend), and
`operators/sketch.py` (the 42 sketch operators). Solver decision: native Levenberg-Marquardt
default backend (py-slvs is GPL-3, this repo Apache-2.0); optional libslvs backend behind
`SCAD_WITH_SLVS`. Oracle: `test_sketch*.py`, `test_error_diagnostics_sketch.py`.

## surface
Own `include/scad/surface/`, `src/surface/`, `bind_surface.cpp`. Port the surface half of
`operators/geometry.py` (l.1-1080), `kernel/ocp_surfaces.py`, shell parts of `kernel/ocp_mesh.py`.
Gordon: pip `ocp-gordon` wraps the DLR `gordon` C++ library; use it via FetchContent under
`SCAD_WITH_GORDON` if it builds portably, else implement natively. See
`docs/research/smlib-usd-brep.md` (SMLib is not a default dependency; keep a `SurfaceFitter` seam).

## reactive
Own `include/scad/reactive/`, `src/reactive/`, `bind_reactive.cpp`; may extend `core/scalar.hpp`
additively. Port `params/expr.py`, `params/units.py` (+ `frame.py`; `tolerance.py` last),
`recording/graph.py`, `topology/model.py` l.409-end as `Graph`/`Session` implementing `Recorder`.
New: `Session::set_var` -> dirty marking, `recompute()` re-runs only dirty nodes in topological
order with memoization; operators plug in through an executor registry (name -> function), not
hard-wired. Bind `ExprBase`/`Var`/`Const`/`Expr` so the `Scalar` caster accepts them.

## io
Own `include/scad/io/`, `src/io/`, `bind_io.cpp`. Port `kernel/ocp_export.py`, tessellation of
`ocp_mesh.py`, `ocp_brep_snapshot.py`, `_internal/{mesh,brep_region,shape_pickle}.py`, the STEP/
STL/BREP readers and writers of `exporter/`. Native shape+semantic-state serialization (versioned
format); `to_brep`/`from_brep` bytes for OCP interop; zero-copy numpy mesh API; portable file
paths (UTF-8 -> `std::filesystem::path`, Windows-safe).

## ql
Own `include/scad/ql/`, `src/ql/`, `bind_ql.cpp`. Port `ql.py` (2011 lines): `ShapeSelector`,
predicates/keys (data, serializable), property-path language, traversal, evidence/diagnostic
text, `register_property_resolver`, `Query`/`select`; call `record_selection` where Python
records selection nodes. Bind as `simplecadapi._cpp.ql`. Oracle: `test_ql.py`, `test_graph_ql.py`,
`test_error_diagnostics_blend_ql.py`.

---

## Second wave (not started: needs `semantic` + `tracking` to be finished and tested)

### ops_geometry
Own `include/scad/ops/geometry/`, `src/ops/geometry/`, `bind_ops_geometry.cpp`. Non-surface half
of `operators/geometry.py`: points, lines, segments, circles/ellipses (edge/wire/face),
rectangles, arcs, helix, splines (control-point, interpolated, periodic), polyline, wires/faces
from wires, `load_brep_region_*`, primitives (box, cylinder, cone, sphere) via `tracked_*` and the
finalize pipeline. Every operator: same signature as Python, one doctest + one golden pytest.

### ops_features
Own `include/scad/ops/features/`, `src/ops/features/`, `bind_ops_features.cpp`.
`operators/{features,boolean,transform}.py` + `limited_extrusion`, `section_features`, `draft`:
extrude, revolve, fillet, chamfer, shell, loft, sweep, twisted/helical sweep, offset, draft,
extrude_taper, sweep_multisection, extrude_until, boolean (cut/union/intersect/boolean_rsolidlist),
translate/rotate/mirror/scale/transform, linear/radial patterns. Register each with the reactive
executor registry.

### std
`std/{gear,bearing,fastener,chain}.py` (3.6k lines) on top of the operators.

### product
`operators/product.py`, `product/*`, `build/*` (parts, assemblies, constraints, placements,
materials, connectors) + the assembly constraint solver.

### Integration (lead)
Python package parity (`simplecadapi._cpp` exports the Python names), `bench_native.py` vs
`tools/bench/bench_reference.py`, Linux/Windows CI, static-OCCT wheel build verification.
