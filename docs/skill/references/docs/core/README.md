# SimpleCAD API Core Classes Documentation

This directory documents the core public object model for SimpleCADAPI.

SimpleCADAPI is OCP-native at runtime: public geometry objects are thin Python wrappers around OpenCascade/OCP shapes exposed through the `.wrapped` attribute. The package provides functional modeling operations, expression parameters, QL selectors, and replayable model JSON.

## Core Classes Overview

### Coordinate and tagging utilities

#### [CoordinateSystem](coordinate_system.md)
A right-handed 3D coordinate system for local modeling contexts and point/vector transformation.

#### [SimpleWorkplane](simple_workplane.md)
A context manager for temporarily modeling in a local coordinate system.

#### [TaggedMixin](tagged_mixin.md)
Shared tag and metadata behavior for geometry wrappers.

### Geometry wrappers

#### [Vertex](vertex.md)
A 0D topology wrapper with coordinate queries.

#### [Edge](edge.md)
A 1D topology wrapper for lines, arcs, circles, splines, and other curve edges.

#### [Wire](wire.md)
A connected path made from edges. Wires may be open or closed.

#### [Face](face.md)
A bounded surface with an outer wire and optional inner wires.

#### [Shell](shell.md)
A connected set of faces that may be open or closed.

#### [Solid](solid.md)
A closed 3D body with volume, faces, edges, tags, and metadata.

#### [Compound](compound.md)
A collection wrapper for multiple geometry objects.

## Relationship Diagram

```text
TaggedMixin
├── Vertex (0D)
├── Edge (1D)
├── Wire (1D)  ← composed of edges
├── Face (2D)  ← bounded by wires
├── Shell (2D) ← connected set of faces
├── Solid (3D) ← bounded by faces
└── Compound   ← collection of shapes

CoordinateSystem ← independent utility
SimpleWorkplane  ← local modeling context
```

## Design Principles

- **Shape-first API**: users work with `Vertex`, `Edge`, `Wire`, `Face`, `Shell`, and `Solid`, not graph nodes.
- **Functional modeling style**: public operations return new geometry values, e.g. `make_box_rsolid(...)`, `cut_rsolid(...)`, `fillet_rsolid(...)`.
- **OCP-native runtime**: geometry construction, topology traversal, properties, booleans, transforms, and export use OCP/OpenCascade helpers.
- **Replayable graph workflows**: an explicit `GraphSession` records operations, `session.capture_result()` selects canonical output nodes, and `export_model_json()` plus `replay_model_json()` provide interchange and replay.
- **Tags and metadata**: tags are useful for lightweight semantics; structured numeric facts should be stored in metadata such as `metadata["geo"]`.
- **QL-only topology enumeration**: plural getters such as `get_edges(index)` and
  `get_faces(index)` accept ONLY an index — the no-argument list form is forbidden
  and raises. Enumerate, count, or measure topology through QL selectors
  (`ql.edges().resolve(shape)`); an intentional single pick uses the indexed form,
  which is recorded as a graph selection node.

## Basic Usage

```python
import simplecadapi as scad

with scad.SimpleWorkplane(origin=(0, 0, 0)):
    box = scad.make_box_rsolid(width=5, height=3, depth=2)

scad.apply_tag(shape=box, tag="role.bracket")
box.set_metadata("material", "6061-T6")
box.auto_tag_faces("box")

top_faces = scad.ql.faces().where(scad.ql.tag("face.top")).resolve(box)
print(len(top_faces))
```

## Replayable Model JSON

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json

with GraphSession(graph_id="drilled_block") as session:
    body = scad.make_box_rsolid(width=10, height=10, depth=4)
    hole = scad.make_cylinder_rsolid(
        radius=1.5, height=8, bottom_face_center=(0, 0, -2)
    )
    part = scad.cut_rsolid(body, hole)
    session.capture_result(value=part)
    payload = export_model_json(session=session)

rebuilt = replay_model_json(json_str=payload)
print(len(rebuilt))
```

## More Resources

- [API Reference Documentation](../api/)
- [Examples](../../examples/)
- [User Guide](../../README.md)
- [JSON Operation Graph Spec](operation_graph_json_spec.md)
- [Serialization and Replay Operation Guides](serialization/)
