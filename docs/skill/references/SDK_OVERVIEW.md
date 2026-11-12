# SDK Overview

- Project: `simplecadapi`
- Version: `2.3.0`
- Package distribution: `simplecadapi==2.3.0`

## What this skill bundles

- Task router (`SKILL.md`) with seven workflows (including unattended mode)
- Capability domains (`references/domains/`)
- Modeling discipline (`references/discipline/`)
- Generated API/stdlib/core references (`references/docs/`)

## What this skill does not bundle

- SDK source code (`src/simplecadapi`) is intentionally excluded.
- Environment/bootstrap workflows are intentionally not the focus here.
- Self-evolving or skill-local case packaging is intentionally excluded.

## Main SDK surfaces

- Geometry and modeling operations in `references/docs/api/`.
- Standard parts library in `references/docs/stdlib/`, including `scad.std.gear` gear, ring gear, rack, and cycloidal disc factories plus `scad.std.bearing` bearing assembly factories.
- Core shape/type semantics in `references/docs/core/`.
- Graph/model serialization and replay APIs.
- Expression, parameter, and semantic reference types.
- Functional tagging with `apply_tag(shape=..., tag=...)`, `list_tags(shape=...)`, and QL tag predicates.

## Preferred replayable workflow

- Record modeling steps inside `GraphSession` when you need replayable outputs.
- Export session/model payloads with `export_session_json()` and `export_model_json()`.
- Re-import or replay with `import_model_json()` and `replay_model_json()`.

## Example SDK usage

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json

with GraphSession(graph_id="box") as session:
    shape = scad.make_box_rsolid(width=10.0, height=20.0, depth=30.0)
    session.capture_result(value=shape)
    payload = export_model_json(session=session)

rebuilt = replay_model_json(json_str=payload)
print(len(rebuilt))
```
