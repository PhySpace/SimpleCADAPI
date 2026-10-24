# Architecture

SimpleCADAPI-cpp is the Python SDK `simplecadapi` (../SimpleCADAPI) re-implemented below the
Python boundary: everything from the OCCT calls up to and including the operator layer is C++20
on OpenCASCADE, shipped as one pybind11 extension (`simplecadapi._cpp._native`) with a thin
pure-Python package around it. Behaviour is aligned with the current Python version.

## Why

The Python SDK is a heavy wrapper over OCCT. Constructing any `Solid` eagerly builds the whole
Solid -> Face -> Wire -> Edge -> Vertex wrapper tree; every operator threads tag/lineage/graph
bookkeeping through interpreted code. The C++ port keeps the *semantics* (tags that survive
modelling, structured errors, symbolic parameters) and drops the *cost*:

- Topology is lazy. A `Solid` is two shared_ptrs and a `TopoDS_Shape`; faces/edges become
  entities only when enumerated, and entities are shared per root so a tag set through one handle
  is seen through every other (`include/scad/topo/shape.hpp`).
- Semantic state is allocated on first write.
- Kernel calls can release the GIL (the Python port could not: its own workaround for this,
  worker processes and a shape-restoring cache, is deliberately **not** ported).

What is ported deliberately: the reactive parametric graph (`scad::reactive`), because it is a
user-experience feature, not a speed workaround.

## Layers (dependencies point down)

```
bindings/python        pybind11: casters, exception translator, one bind_<area>.cpp per area
------------------------------------------------------------------------------------------
product  std                       parts, assemblies, constraints; gears, bearings, fasteners
ops_features  ops_geometry         the operators (extrude, fillet, boolean ... / primitives, curves)
sketch  surface  io  reactive      constrained sketches; surface ops; import/export/mesh; expr+graph
semantic                           tags, lineage, tracking (history -> delta), finalize pipeline
------------------------------------------------------------------------------------------
topo      Shape handles, Registry, tag data model, TopoDelta, Recorder hook
kernel    OCCT-only helpers on TopoDS_Shape: no semantic state, no Python concepts
core      Error model, Vec3, CoordinateSystem/Workplane, Scalar, Value
```

Each box is one static library `scad_<area>`, one doctest executable `test_<area>`
(`tests/cpp/<area>/*.cpp`) and one `bindings/python/bind_<area>.cpp`. An area never includes
a header from an area above it. Sources are globbed per area (no CMake edit to add a file).

## Conventions

**Errors.** Public operators fail with `scad::Error` (the `SimpleCADError` analogue): operation,
what happened, possible causes, how to fix, technical details, rendered exactly like the Python
text. Write the static half once per operator:

```cpp
static const ErrorSpec kSpec{"make_box_rsolid", "Failed to create a box solid.",
                             {"Width, height, or depth is not a positive finite scalar."},
                             {"Use width, height, and depth values greater than zero."}};
return guarded(kSpec, [&] { ... });
```

Wrap raw OCCT call sequences in `occt_guard` so `Standard_Failure` becomes `KernelError`
(OCCT exceptions do not derive from `std::exception`). Use `ValueError`/`TypeError`/`IndexError`
for the same cases the Python code raises them.

**Scalars.** Operators take `Scalar` wherever Python takes `ScalarLike`; call
`evaluate_scalar(s, "width")`. Keep the original `Scalar` for the recorder.

**Coordinate systems.** Operators read `current_cs()` and place results through it, like Python.

**Shapes.** Take and return typed handles (`Solid`, `Face`, ...). `wrapped()` is the escape hatch
to `TopoDS_Shape`. Never keep a `TopoDS_Shape` where a handle would do: handles carry the tags.
To reach the semantic state of an input's sub-shape while walking an OCCT history, use
`input.sub(topods_shape)`.

**Recording.** After building a result call `record_operation(OpRecord{...}, {result})`
(`include/scad/topo/recorder.hpp`). With no recorder installed it costs one pointer test.

**Tags.** Operators finish through the semantic layer (`include/scad/semantic/`): finalize
helpers apply role tags, `result_tag`, `tag_prefix`, and project input tags through the topology
delta. Do not hand-roll tag logic in an operator.

**Portable C++.** Standard C++20 only: no compiler extensions, no `std::format` (libstdc++ 12),
no `M_PI` (use `scad::kPi`), no POSIX-only calls outside `#ifdef`s in `src/io`. Code must build
with MSVC 2022, GCC 11+, Clang 14+. Warnings are errors in CI (`SCAD_WARNINGS_AS_ERRORS`).
Targets: Windows x64, macOS arm64, Linux x86_64, Linux aarch64.

**Python names.** The pybind11 module exports the Python SDK's names and signatures
(`make_box_rsolid(width, height, depth, bottom_face_center=(0, 0, 0), *, tag_prefix=None, ...)`).
Plural enumerators (`faces()`) are port extensions; the Python-compatible `get_faces(index)`
stays strict.

## Verifying against the Python SDK

`tests/python/ref.py::golden(name, snippet)` runs `snippet` in the reference interpreter
(`SCAD_REF_PYTHON`), caches the JSON answer in `tests/golden/<name>.json`, and every platform
compares to that file. Golden files are committed; they are the behavioural contract. A port is
"aligned" when the golden comparisons for its operators pass, not when the symbol exists.

## Reference code map (Python -> C++)

| Python | C++ |
|---|---|
| `core.py` (shapes, TaggedMixin, CoordinateSystem) | `topo/`, `core/` |
| `kernel/ocp_*.py` | `kernel/` (+ `io/`, `surface/` for exports/meshes/surfaces) |
| `topology/{tagging,autotag,tracking,model}.py`, `operators/_support.py` | `semantic/` |
| `operators/geometry.py` | `ops/geometry/` (surface functions -> `surface/`) |
| `operators/{features,boolean,transform}.py` + `limited_extrusion`, `section_features`, `draft` | `ops/features/` |
| `operators/sketch.py`, `sketch*.py`, `sketch_solver/` | `sketch/` |
| `ql.py` | `ql/` |
| `params/expr.py`, `params/units.py`, `recording/graph.py` | `reactive/` |
| `std/` | `std/` |
| `operators/product.py`, `product/`, `build/` | `product/` |

Out of scope for this port (stay Python, on top): `translator/`, `inspect/`, `scene/`, `editor/`,
`artifacts/`, `recording/serializer.py`, `runtime/` (notebook cache, prefetch workers).
