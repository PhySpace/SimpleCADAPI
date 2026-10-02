# Serialization and Replay Operation Guides

This directory documents how SimpleCADAPI serializes replayable modeling operations into the canonical low-level `model.json` operation graph.

The long-form schema reference remains [`../operation_graph_json_spec.md`](../operation_graph_json_spec.md). These files are more practical, operation-by-operation guides intended for people comparing source code with exported JSON.

## Recommended workflow

```python
import json
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json

with GraphSession(graph_id="drilled_block") as session:
    body = scad.make_box_rsolid(width=10, height=6, depth=2)
    hole = scad.make_cylinder_rsolid(
        radius=1, height=4, bottom_face_center=(0, 0, -1)
    )
    result = scad.cut_rsolid(body, hole)
    session.capture_result(value=result)
    model_json = export_model_json(session=session)

payload = json.loads(model_json)
rebuilt = replay_model_json(json_str=model_json)
```

Inspect these fields:

- `payload["graph"]["nodes"]`: canonical operation nodes in topological order.
- `node["op"]`: stable replay operation name.
- `node["params"]`: numeric / JSON-compatible parameter snapshot.
- `node["param_exprs"]`: optional expression links into `expression_graph`.
- `node["inputs"]`: upstream node ids used by replay.
- `payload["leaf_ids"]`: explicit final result node ids.
- `payload["expression_graph"]`: expression DAG used by expression-backed parameters.
- `payload["tolerance_graph"]`: dimension-chain requirements and validation evidence.

Use `session.capture_result(...)` when the final output should not be inferred
from all graph leaves, and treat `export_model_json(session=...)` as the
interchange boundary for direct graph workflows. Durable CAD/viewer products use
`@scad.part` or `@scad.assemble`, then `scad.capture(result, "out/product.scadpkg")`
to build and write one canonical self-contained package. No files are written
unless an export API is called.

## Important rule: source API is not always graph API

Many user-facing functions are convenience APIs. During an active `GraphSession`, they lower to canonical low-level nodes:

| Source call | Serialized graph result |
| --- | --- |
| `make_box_rsolid(...)` | rectangle profile + `make_extrude_rsolid` |
| `make_cylinder_rsolid(...)` | circle face + `make_extrude_rsolid` |
| `make_sphere_rsolid(...)` | profile + `make_revolve_rsolid` |
| `make_cone_rsolid(...)` | profile + `make_revolve_rsolid` |
| `make_rectangle_rwire(...)` | line edges + `make_wire_from_edges_rwire` |
| `make_circle_rface(...)` | circle edge + wire + face |
| `make_polyline_rwire(...)` | line edges + wire |
| `linear_pattern_rsolidlist(...)` | explicit `make_translate_rshape` nodes |
| `radial_pattern_rsolidlist(...)` | explicit `make_rotate_rshape` nodes |
| `helical_sweep_rsolid(...)` | helix wire + profile face + `make_sweep_rsolid` |

## Guides

- [Primitive and profile operations](primitives-and-profiles.md)
- [Features, booleans, transforms, patterns, and selectors](features-booleans-transforms.md)
- [Expressions and replay behavior](expressions-and-replay.md)
- [Physical units and dimension inference](../physical-units.md)
- [Dimension tolerance chains](../dimension-tolerance-chains.md)

## Examples

The retained examples use the current replay and durable product contracts. See
[`../../../examples/constrained_sketch/constrained_sketch.py`](../../../examples/constrained_sketch/constrained_sketch.py)
for sketch promotion and replay, and
[`../../../examples/external_reference_gear_train/nested_external_reference_gear_trains.py`](../../../examples/external_reference_gear_train/nested_external_reference_gear_trains.py)
for library parts, explicit external definitions, repeated/nested assemblies, and independent definition export.
