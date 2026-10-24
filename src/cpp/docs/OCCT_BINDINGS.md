# The OCCT bindings (`simplecadapi._cpp.occt`)

**Why they exist.** Some Python layers of the SDK still talk to OpenCASCADE directly: STEP/BREP inspection
(`inspect/`), drawings and DXF (`dxf_engine/`), the CAD translators, scene meshing, a few exporters, and the tests
that use OCCT as an oracle. They were written against the `OCP` package (cadquery-ocp). The goal is that **nothing needs
OCP**: this module carries its own OpenCASCADE, so those layers call the same classes, bound here, by the same names.

**What they are not.** A copy of OCP. Only what the SDK's Python layers and their tests *call* is bound; the list is
measured (`tools/occt_usage_trace.json`: every `(class, method, argument types)` the test suite and the kept layers
reached on the native backend), plus whatever a `grep` of those layers adds that the tests did not reach.

## Conventions (follow OCP exactly: the callers are written against it)

* A class keeps its OCCT name (`BRepAdaptor_Curve`); it lives in the flat submodule `simplecadapi._cpp._native._occt` and is
  re-exported by the OCP module it belongs to: `from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve`
  (`python/simplecadapi._cpp/_occt_layout.json` maps every bound name to its module; add an entry when binding a class).
* A static method `Foo::Bar` is `Foo.Bar_s(...)` (a `def_static("Bar_s", ...)`).
* An enum value is both `Enum.Name` and a module level `Name` (`export_values()`); `int(enum)` works (pybind enums).
* **Out-parameters are mutated in place**, exactly as OCP does: `BRepAdaptor_Curve.D1(u, pnt, vec)` fills `pnt` and `vec`;
  `BRepGProp.VolumeProperties_s(shape, props)` fills `props`. Take `gp_Pnt&`, never return a new one in their place.
  Where OCP *returns* a tuple for a C++ out-parameter (`BRep_Tool.Range_s(edge, face)` -> `(first, last)`), return a tuple.
* Shapes are `TopoDS_Shape` and its subclasses by value; a `TopoDS_*` handed in must be the right subclass (OCP checks).
* Reference-counted OCCT classes (`Geom_*`, `Poly_Triangulation`, `TDocStd_Document`, `XCAFDoc_*`, ...) use the
  `opencascade::handle<T>` holder (`PYBIND11_DECLARE_HOLDER_TYPE` is in `occt.hpp`): bind them
  `py::class_<Geom_Circle, opencascade::handle<Geom_Circle>, Geom_Conic>`.
* Methods that OCP overloads on argument type must be overloaded here the same way (the trace lists the argument types).
* Python file objects: OCP takes `BytesIO` for `BinTools.Read_s/Write_s`, `STEPControl_Reader.ReadStream`, `BRepTools.Write_s`
  (a Python stream is wrapped with `py::iostream`-style adapters; see how OCP is called in `_native/bridge.py`).
* Do not bind what nobody calls. Do bind every overload and method the callers use, including ones the tests missed.

## Where things go

`bindings/python/occt/`:

| file | area |
|---|---|
| `bind_occt_core.cpp` | `gp_*`, topology enums, `TopLoc_Location`, `TopoDS_*`, `TopExp*`, `TopTools_*`, `Precision`, `BRep_Tool`, `BRep_Builder` (done) |
| `bind_occt_query.cpp` | geometry and measurement: `Geom_*`, `Geom2d_*`, `GeomAbs_*`, `TColgp_*`/`TColStd_*`, `BRepAdaptor_*`, `GProp`, `BRepGProp`, `Bnd_Box`, `BRepBndLib`, classifiers, `BRepExtrema_*`, `BRepLProp_*`, `GCPnts_*`, `GeomAPI_*`, `GeomConvert`, `Poly_*`, `ShapeAnalysis_*`, `BRepTools`, `BRepCheck_*` |
| `bind_occt_algo.cpp` | construction: `BRepAlgoAPI_*`, `BRepBuilderAPI_*`, `BRepPrimAPI_*`, `BRepFilletAPI_*`, `BRepMesh_IncrementalMesh`, `HLR*`, `ShapeUpgrade_*` |
| `bind_occt_step.cpp` | data exchange and documents: `STEPControl_*`, `STEPCAFControl_*`, `IFSelect_*`, `Interface_*`, `XCAF*`, `TDF_*`, `TDocStd_*`, `TDataStd_*`, `TCollection_*`, `Quantity_*`, `Step*`, `BinTools`, `BinTools_FormatVersion` |

Each file exposes `void bind_<area>(py::module_& m)`; `bind_occt.cpp` calls them in the order core, query, algo, step (a class
may name types registered before its own file, never after).

## Developing one area fast

```
cmake -S src/cpp/occt_dev -B src/cpp/build/occt-dev-<area> -G Ninja \
      -DPython_EXECUTABLE=$PWD/.venv/bin/python
cmake --build src/cpp/build/occt-dev-<area>            # seconds: only these sources, no scad libraries
PYTHONPATH=src/cpp/build/occt-dev-<area> .venv/bin/python -c "import _occt_dev as m; m.flat.gp_Pnt(1,2,3)"
```

`_occt_dev.flat` is the same flat module as `simplecadapi._cpp._native._occt`.

## Testing

The bindings are exercised by the SDK's own suites (`test/`: inspection, drawings, export/import, translators, scene
meshing), which run on them with no other OCCT wrapper installed. The differential tests against OCP that were used while
the bindings were written (every method called on both, values and exceptions compared) were removed with OCP itself.
