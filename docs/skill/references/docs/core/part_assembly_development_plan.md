# Part and Assembly Development Plan

This document records the SimpleCADAPI Part and Assembly direction after
reviewing the current topology/geometry model, operation graph philosophy,
sketch constraint implementation, QL surface, and the Boiling Lake completeness
principle.

The MVP APIs described in the Part, Material, Placement, Assembly, and projection
sections are implemented as public APIs. Connector and mate-solver concepts are
future work and remain explicitly marked as out of scope.

## Completeness Principle - Boil The Lake

The Part/Assembly MVP is treated as a boilable lake, not an ocean. When choosing
between a complete implementation and a shortcut that saves modest effort, the
complete implementation is the recommended path.

This principle applies to:

- API validation.
- Error messages and error paths.
- Graph recording.
- Replay and strict replay behavior.
- Model JSON serialization.
- Translator behavior.
- Examples.
- Generated API docs.
- Negative and edge-case tests.

Do not defer tests, docs, validation, or replay support to save a small amount of
code. If the remaining work is inside the Part/Assembly MVP lake, boil it in the
same implementation pass.

The ocean boundary is different: full assembly mate solving, full physical
simulation, multi-body part authoring, editable feature trees, or rewriting the
kernel around XCAF/OCAF are out of scope for this MVP and should be handled as
separate future lakes.

## Current Design Baseline

SimpleCADAPI is currently centered on two stable ideas:

- Topology/geometry values: `Vertex`, `Edge`, `Wire`, `Face`, `Solid`, and `Compound`.
- Typed functional operations: `make_*`, `extrude_rsolid`, `cut_rsolid`, `fillet_rsolid`, `loft_rsolid`, transforms, selectors, serialization, and translators.

Sketches now form a symbolic construction layer:

- A `Sketch` contains symbolic entities and declarative constraints.
- A `Sketch` is not BREP geometry by itself.
- `make_wire_from_sketch_rwire(...)` and `make_face_from_sketch_rface(...)` promote solved sketch geometry into the topology/geometry layer.
- Solve evidence belongs to promotion metadata and replay validation, not to a standalone modeling object.

This same philosophy should guide Part and Assembly support:

- A `Feature` is not a public object.
- Feature-like behavior remains a typed operation graph node.
- A `Body` is not a new public abstraction for the MVP.
- In the MVP, body-level geometry is exactly a `Solid`.

## Layer Model

```text
Sketch
  symbolic constrained construction
  becomes topology/geometry only through explicit promotion

Shape / TopoGeo
  Vertex / Edge / Wire / Face / Solid / Compound
  Solid is the MVP body-level geometry

Operation
  typed functional graph node
  examples: extrude, cut, union, fillet, chamfer, loft, transform

Part
  semantic wrapper over exactly one Solid
  owns part-local coordinates, product identity, and assigned material

Assembly
  product structure over Part or subassembly component instances
  owns instance placement and product tree identity
```

## Non-Goals For The MVP

The following remain intentionally out of the MVP lake:

- Multi-body parts.
- Public `Body` objects.
- Public `Feature` objects.
- Physical properties APIs.
- Generic part reference APIs.
- Assembly mate/constraint solver.
- Connector/datums for assembly constraints.
- Automatically treating arbitrary `Solid` values as `Part` values inside assemblies.

These are not all permanently rejected. They are deferred because the first
boilable lake is explicit single-body parts, materials, component instances,
placement, serialization, and export/projection behavior.

## Coordinate Model

For the MVP, a `Part` has one correct coordinate rule:

```text
Part-local coordinates = the wrapped Solid's modeling coordinates.
```

If a user wants a different part origin, the correct approach is to build the
`Solid` in that coordinate system before wrapping it as a `Part`.

Assembly component placement maps child-local coordinates into parent assembly
coordinates:

```text
p_assembly = T_component * p_part
```

Nested assembly placement composes transforms:

```text
p_root = T_parent_component * T_child_component * p_part
```

Moving a part inside an assembly must not transform the part's internal solid.
Only the component placement changes.

## Canonical Placement Representation

Only one public placement representation should be exposed in the MVP:

```python
make_placement_rplacement(
    origin: tuple[float, float, float],
    *,
    x_axis: tuple[float, float, float] = (1.0, 0.0, 0.0),
    y_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
) -> Placement
```

Rules:

- `origin` is the child origin expressed in parent coordinates.
- `x_axis` and `y_axis` define the child basis expressed in parent coordinates.
- Axes are normalized by the implementation.
- Axes must be non-zero and orthogonal within a documented tolerance.
- The frame must be right-handed.
- `z_axis = x_axis cross y_axis`.
- Public placement APIs do not also accept Euler angles, quaternions, or axis-angle forms.

Identity placement:

```python
identity_placement_rplacement() -> Placement
```

## Material API

Material has a single correct entry point and is not passed to
`make_part_rpart(...)`.

```python
make_material_rmaterial(
    material_id: str,
    *,
    name: str | None = None,
    density: float | None = None,
    density_unit: str | None = None,
    color: tuple[float, float, float] | None = None,
) -> Material
```

Validation requirements:

- `material_id` must be a stable non-empty identifier.
- `density`, when provided, must be finite and positive.
- `density_unit`, when provided, must be explicit.
- `color`, when provided, must be a 3-tuple of finite values in `[0.0, 1.0]`.
- Unknown physical semantics do not get hidden in generic physical property APIs.

Material assignment:

```python
assign_material_rpart(part: Part, material: Material) -> Part
```

This keeps one correct workflow:

```text
make material -> make part -> assign material
```

## Part API MVP

The implemented MVP supports single-body parts only.

```python
make_part_rpart(
    part_id: str,
    body: Solid,
    *,
    name: str | None = None,
) -> Part
```

Semantics:

- `part_id` is stable product identity.
- `part_id` replaces ambiguous names such as `part_number`.
- `body` must be a `Solid`.
- `Compound` is not accepted in the single-body MVP.
- Material is assigned only through `assign_material_rpart(...)`.
- Physical properties are not part of the MVP.
- The part-local coordinate system is the body's modeling coordinate system.

Validation requirements:

- Reject empty `part_id`.
- Reject duplicate part IDs inside one model context where uniqueness is required.
- Reject non-`Solid` bodies.
- Preserve graph identity and replay behavior.
- Preserve part identity in model JSON.

## Assembly API MVP

An `Assembly` contains component instances. A component references a `Part` or a
subassembly and owns an instance placement.

```python
make_assembly_rassembly(
    assembly_id: str,
    *,
    name: str | None = None,
) -> Assembly
```

```python
add_component_rassembly(
    assembly: Assembly,
    item: Part | Assembly,
    *,
    component_id: str,
    placement: Placement,
    name: str | None = None,
) -> Assembly
```

```python
place_component_rassembly(
    assembly: Assembly,
    component_id: str,
    placement: Placement,
) -> Assembly
```

Semantics:

- `component_id` is stable only within its parent assembly.
- The same `Part` can be instantiated multiple times.
- Moving a component changes placement only; it does not transform the referenced `Part` body.
- Subassemblies are allowed as component items after the base Part path is complete.
- Assembly is not a `Compound`.

Validation requirements:

- Reject empty `assembly_id`.
- Reject empty `component_id`.
- Reject duplicate `component_id` in the same assembly.
- Reject cycles in subassembly references.
- Reject invalid placements.
- Reject arbitrary `Solid` items. Users must explicitly wrap solids as parts.

## Assembly Geometry Projection

Assembly semantic structure must not be flattened implicitly.

For preview, export fallback, bounding boxes, and geometry-only workflows, expose
an explicit projection operation:

```python
make_compound_from_assembly_rcompound(assembly: Assembly) -> Compound
```

Semantics:

- Applies component placements to referenced part bodies.
- Produces a flattened geometry projection.
- Does not replace the assembly product tree.
- Records enough graph evidence to replay the projection deterministically.

## FreeCAD Translation

The FreeCAD translator preserves the product tree instead of exporting only a
fixed geometry result.

Current FCStd mapping:

- `Part` is emitted as an `App::Part` containing the wrapped body object.
- `Assembly` is emitted as a native `Assembly::AssemblyObject`.
- Part components are emitted as `App::Link` objects under the owning assembly.
- Subassembly components are emitted as `Assembly::AssemblyLink` objects under the owning assembly.
- Component placements are written to the link placement.
- Material assignment is stored on the part container as `SimpleCADMaterial`.
- `make_compound_from_assembly_rcompound(...)` still emits an explicit flattened projection for geometry workflows, but the projection is hidden when it is the result leaf so the visible FCStd result remains the editable assembly tree.

Assembly constraints, mates, solving, and connector/datum references are still
out of scope for the MVP. The FreeCAD output is therefore a placed product
structure, not a solved constraint model.

## Part References And Connectors

The MVP does not include a generic part reference API.

The rejected MVP shape is:

```python
add_part_reference_rpart(part, name, selection)
```

Reasons:

- It mixes product semantics with raw topology selection.
- It does not clarify whether the selected entity is a face, edge, axis, point, datum, or connector.
- Topology selections alone are not the right abstraction for future assembly constraints.
- Assembly constraints are not in the MVP, so generic references would be premature.

When assembly constraints are introduced later, the preferred direction is an
explicit connector/datum interface, not a generic reference bag:

```python
add_connector_rpart(
    part: Part,
    connector_id: str,
    placement: Placement,
) -> Part
```

Connectors are part-local coordinate frames. Future constraints can refer to
`(component_id, connector_id)` instead of raw topology.

This is a separate lake and should not be mixed into the single-body
Part/Assembly MVP.

## Current QL Surface Used In Examples

The current QL APIs that are safe to use in examples include:

```python
ql.faces()
ql.edges()
ql.tag("face.top")
ql.prop("geom.normal.z", ">", 0.9)
ql.key("geom.center.z")
ql.center_axis("z")
selector.take(1).exactly(1).resolve(shape)
selector.boundary("wire").boundary("edge")
```

Do not document fake selectors such as `select_cylinder_axis(...)` unless those
APIs are actually implemented.

## Example: Hydraulic Rod Assembly

`examples/hydraulic_rod_assembly/` builds a hydraulic rod/cylinder assembly that uses
implemented geometry, QL, Part, Material, Placement, Assembly, projection, STEP,
and FCStd translation APIs. Each part is a notebook (`outer_sleeve.py`,
`piston_rod.py`); the `hydraulic_rod_assembly.py` notebook composes them with
`scad.use`, and `export.py` loads the product with `run_notebook`.

The example intentionally keeps product structure separate from geometry
projection:

- The outer sleeve is one single-body `Part` with a barrel, gland flange, bolt-hole details, rear eye, and pin hole.
- The inner piston rod is another single-body `Part` with piston lands, a seal groove, chrome rod, rod-eye neck, and rod-eye pin hole.
- The assembly notebook instantiates both parts with component placement.
- `make_compound_from_assembly_rcompound(...)` produces the flattened preview projection; `scad.exporter.export_product_package_to_step(...)` writes the package STEP projection.
- `scad.translator.freecad_translator.translate_product_package_to_fcstd(...)` writes a native FreeCAD Assembly Workbench document where the assembly tree remains visible and editable.

Run it from the source checkout:

```bash
uv run python examples/hydraulic_rod_assembly/export.py
```

## Boiling Lake Implementation Plan

The MVP is a boilable lake. It is not an ocean-scale rewrite.

Complete means:

- Public dataclasses/types for `Material`, `Placement`, `Part`, `Component`, and `Assembly`.
- Complete validation and error paths.
- Functional APIs with typed return suffixes.
- Graph recording and replay.
- Model JSON serialization.
- Strict replay behavior.
- Deterministic component ordering.
- Explicit assembly-to-compound projection.
- STEP/FCStd translator behavior that preserves identity when supported and clearly documents fallback projection behavior.
- API docs generated and reviewed.
- Core design docs updated.
- Examples using only implemented public APIs.
- Unit tests for each API and edge case.
- Translator/regression tests for identity and placement.
- Negative tests for invalid IDs, duplicate components, invalid placements, non-solid part bodies, and assembly cycles.

Suggested implementation order:

1. Add core immutable data types and validation helpers.
2. Add material and placement APIs with exhaustive tests.
3. Add single-body Part APIs with graph/model JSON tests.
4. Add Assembly and Component APIs with placement and duplicate/cycle validation.
5. Add `make_compound_from_assembly_rcompound(...)` projection with replay tests.
6. Add translator support for Part/Assembly identity and projection fallback.
7. Add example script and docs.
8. Run full tests, compile, whitespace checks, examples, and FreeCAD translator regressions.

## Effort Estimate

Both human-team and Codex-scale estimates are shown per the Boiling Lake rule.

| Task | Human team | Codex | Compression |
| --- | --- | --- | --- |
| Core dataclasses and validation | 2 days | 15 min | ~100x |
| Material and placement APIs/tests | 1 day | 15 min | ~50x |
| Part APIs, graph, replay, model JSON | 3 days | 30 min | ~30x |
| Assembly/component APIs and validation | 3 days | 30 min | ~30x |
| Projection to Compound and tests | 1 day | 15 min | ~50x |
| FreeCAD/STEP translator support | 1 week | 30-60 min | ~20-30x |
| Docs, examples, generated API refresh | 1 day | 15 min | ~50x |
| Architecture review and edge-case pass | 2 days | 4 hours | ~5x |

Recommended scope is the complete MVP lake, not a shortcut that skips tests,
validation, docs, or translator behavior.

## Out Of Scope Oceans

The following are ocean-scale for this phase and should not be smuggled into the
MVP:

- Full assembly mate solver.
- Constraint-driven connector/datum system.
- Full physical simulation or mass-property subsystem.
- Multi-body Part authoring environment.
- Editable feature tree or feature suppression/reordering.
- Rewriting the kernel around XCAF/OCAF directly.
- Adding features to OCP/OCCT itself.

These can become future lakes once the single-body Part and explicit-placement
Assembly foundation is complete.
