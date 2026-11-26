# Declarative Constraint Status

Sketch constraints are supported through the isomorphic sketch API surface:

- `make_sketch_rsketch(...)`
- `add_point_rsketch(...)`
- `add_line_rsketch(...)`
- `add_circle_rsketch(...)`
- `constrain_*_rsketch(...)`
- `inspect_sketch_rsketchresult(...)` for non-recording diagnostics
- `make_wire_from_sketch_rwire(...)`
- `make_face_from_sketch_rface(...)`

When the modeling intent is a sketch/profile, use these sketch APIs as the only recommended construction path. Concrete geometry APIs such as `make_line_redge(...)` and `make_wire_from_edges_rwire(...)` remain for paths, pure geometry, and internal lowering targets.

Sketch document construction is functional: `add_*_rsketch(...)` and `constrain_*_rsketch(...)` return an updated `Sketch` instead of mutating the input document. Each sketch entity must have a stable explicit id, and constraints may use those ids directly:

```python
sketch = make_sketch_rsketch("plate_profile")
sketch = add_point_rsketch(sketch, "p0", 0.0, 0.0)
sketch = add_point_rsketch(sketch, "p1", 72.0, 0.0)
sketch = add_line_rsketch(sketch, "bottom", "p0", "p1")
sketch = constrain_horizontal_rsketch(sketch, "bottom")
sketch = constrain_distance_rsketch(sketch, "p0", "p1", 72.0)
```

`solve` is not a first-class modeling graph leaf. `make_wire_from_sketch_rwire(...)` and `make_face_from_sketch_rface(...)` run the sketch solver internally during `Sketch -> Wire/Face` promotion. Promotion graph nodes record `solve_snapshot` and `promotion_map` evidence, and promoted geometry receives `source_sketch`, `sketch_solve`, and sketch entity metadata/tags. `inspect_sketch_rsketchresult(...)` is diagnostic-only and does not record graph nodes.

The default sketch solver backend is `py-slvs` (`py-slvs==1.0.6`). The public sketch document and solve result do not expose native solver handles. Alternative backends implement `SketchSolverBackend.solve(sketch, *, options)`, register with `register_sketch_solver_backend(...)`, and can be selected by name with `Sketch.solve(backend="name")` or process-wide with `set_default_sketch_solver_backend(...)`. `SketchSolveResult` snapshots record `backend`, `backend_version`, and `backend_status_code` so replay evidence identifies the solver that produced it.

```python
class MyBackend:
    name = "my-solver"
    version = "1"

    def solve(self, sketch, *, options):
        return SketchSolveResult(...)

register_sketch_solver_backend(MyBackend())
set_default_sketch_solver_backend("my-solver")
```

# Assembly Constraint Status

Assembly containers, explicit part transforms, and declarative assembly constraints are temporarily removed from the public/support surface while the assembly system is redesigned.

Removed public APIs include:

- `Assembly`
- `PartHandle`
- `PointAnchor`
- `AxisAnchor`
- `AssemblyResult`
- `SolveReport`
- `make_assembly_rassembly`
- `clone_assembly_rassembly`
- `add_part_rassembly`
- `translate_part_rassembly`
- `rotate_part_rassembly`
- `solve_assembly_rresult`
- `constrain_coincident_rassembly`
- `constrain_concentric_rassembly`
- `constrain_offset_rassembly`
- `constrain_distance_rassembly`
- `clear_constraints_rassembly`
- `stack_rassembly`
- `stack`

Current supported workflows should model durable products through explicit boundaries:

- Use `@scad.part` for one physical solid and `@scad.assemble` for a multi-part product.
- Use `scad.capture(result, path)` as the only public `.scadpkg` write boundary.
- Use `union_rsolid(...)`, `cut_rsolid(...)`, and `intersect_rsolid(...)` when a single merged solid is required.

`export_model_json(...)` no longer accepts `assembly=...`, and newly exported model JSON does not include `assembly`, `assembly_registry`, or `constraint_registry` fields.

The next assembly implementation should define a new assembly graph / constraint graph contract before reintroducing public APIs.
