# Product Package Export and Downstream Targets

**Read when:** a notebook's product must be written as a `.scadpkg` or delivered to FreeCAD, STEP, STL, OBJ or a mesher. Running a notebook and parameters are in `notebook-runtime.md`.

## Product package export

A notebook's product, or a builder's result, is written as one canonical
product package:

```python
scad.capture(run.definition, "out/bracket.scadpkg")
scad.capture(build_plate(), "out/plate.scadpkg")

root = scad.load_product_package("out/bracket.scadpkg")
rebuilt = scad.materialize_definition(root)
```

Use `build_product_package(...)`, `encode_product_package(...)`,
`read_product_package(...)`, and `load_product_package(...)` only for explicit
in-memory package handling. `validate_product_package(...)` verifies every object
hash and size, the complete recursive definition graph, cycle/depth limits, and
rejects missing or unreferenced objects. Use `export_part_definition(...)` or
`export_assembly_definition(...)` only for low-level definition exchange or
inspection; neither is the product delivery format.

## Downstream CAD and mesh targets

Keep `.scadpkg` as the canonical SimpleCAD delivery artifact. Choose a
downstream target from the consumer contract:

| Target | Use when | Preserved contract | Boundary |
| --- | --- | --- | --- |
| `.scadpkg` | Rebuild, replay, or further SimpleCAD tooling is required | Complete durable definition closure, feature graphs, source snapshots, topology, connectors, constraints, and materials | SimpleCAD-specific archive |
| `.FCStd` | A FreeCAD user needs an editable native document | Definition-owned, dependency-first native feature graphs; final body links; repeated instances; nested assemblies; names; solved placements; materials; connectors; constraints; grounding; revision; and content hashes | Requires FreeCADCmd/FreeCAD |
| AP242 `.step` | Neutral CAD exchange or downstream OpenCASCADE tooling is required | Evaluated BREP, product hierarchy, shared definitions, occurrence names/placements, materials, colors, density, and named SimpleCAD property payloads | Canonical feature history is not reconstructed as AP242 features |
| Triangle `.obj` | Surface inspection or DCC exchange needs an indexed mesh | Direct OpenCASCADE tessellation of evaluated BREP with shared vertices and oriented triangles | Evaluated surface mesh only; no CAD hierarchy, feature semantics, quads, or materials |
| Binary `.stl` | Additive manufacturing or triangle-only consumers | The same direct OpenCASCADE BREP triangles | Facet soup only; no shared vertices, CAD hierarchy, feature semantics, or materials |

```python
package_path = "out/product.scadpkg"
scad.capture(run.definition, package_path)

fcstd_path = scad.translator.freecad_translator.translate_product_package_to_fcstd(
    package_path,
    "out/product.FCStd",
)
step_report = scad.exporter.export_product_package_to_step(
    package_path,
    "out/product.step",
)
stl_report = scad.exporter.export_product_package_to_stl(
    package_path,
    "out/product.stl",
)
obj_report = scad.exporter.export_product_package_to_obj(
    package_path,
    "out/product.obj",
)
print(step_report.definition_ids, step_report.occurrence_count)
print(stl_report.solid_count, stl_report.triangle_count)
print(obj_report.vertex_count, obj_report.triangle_count)
```

STL and OBJ use the same direct OpenCASCADE tessellation and parameters. Set
`linear_deflection` to the maximum chordal deviation in product units and
`angular_deflection_degrees` to the curved-surface angular limit. Both formats
contain oriented triangles; OBJ preserves shared vertex indices while binary STL
stores each facet independently. No remeshing or optional dependency is involved.

AP242 definition and occurrence metadata is stored in one standard
`PROPERTY_DEFINITION_REPRESENTATION`. Its named
`DESCRIPTIVE_REPRESENTATION_ITEM` records use
`SimpleCAD:definition:<kind>:<definition_id>` and
`SimpleCAD:occurrence:<parent_definition_id>:<component_id>`. Each description
is canonical sorted JSON containing durable IDs, revision, content hash,
connectors, constraints, grounding, name, and solved placement.
`ProductSTEPExportReport` reports the schema, definition IDs, occurrence
count, material IDs, metadata item count, and explicit limitations.

For tetrahedral meshing, run the split example directly in dependency order:
the model is the `bracket.py` notebook, `export_step.py` captures its product
to `.scadpkg` (through `bracket_package.py`) and exports AP242 STEP, and
`export_fem_mesh.py` imports that STEP with Gmsh's OpenCASCADE kernel. The FEM
stage rejects imports with no 3D volumes, generates a dimension-3 mesh, writes
`.msh`, and always finalizes Gmsh. Install and invoke the optional dependency
with `uv run --extra gmsh python
examples/ap242_gmsh_volume_mesh/export_fem_mesh.py`; Gmsh is never imported
by the core SDK or product exporters.
