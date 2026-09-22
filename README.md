<p align="center">
  <img src="img/repocover.png" alt="SimpleCADAPI repository cover">
</p>

# SimpleCADAPI

[中文说明](README.zh-CN.md)

## What Can It Do

Four capability pillars. Every case below is a **real, reproducible session**:
the replay demos are single-file offline HTML pages that faithfully replay the
full recorded conversation (user turns, agent thinking, every tool call and
patch, role switches) next to the exported 3D model — open them directly in a
browser.

### 1 · Single-Part Modeling

Parametric parts authored as readable [Feature Tree
Convention](docs/skill/references/discipline/feature-tree-convention.md)
feature blocks — named parameters with units, verifier-first staged modeling,
deterministic face tags that survive re-parameterization, and synchronized
`.scadpkg` / STEP AP242 / STL / editable FreeCAD exports.

<table>
<tr>
<th width="18%">Case</th>
<th width="40%">First-turn requirement (excerpt)</th>
<th width="42%">Delivered model · BRep turntable</th>
</tr>
<tr>
<td><b>Robotic-arm U-link + motor mount</b><br/>15 user turns · 601 tool calls<br/><a href="examples/u_link_motor_mount/demo/index.html">▶ Full session replay</a></td>
<td>"Build a parametric robotic-arm link that adapts to length changes and mounts motors generically: sweep a circular profile down D → right L → up D into a U; cut motor sockets with spheres; the mounting face must carry a deterministic name indexable by the query language; split the bottom cylinder into a half cylinder; then fillet everything."</td>
<td><img src="img/capability/ulink_turntable.gif" width="420" alt="u_link turntable"></td>
</tr>
<tr>
<td><b>Parametric flange plate</b><br/>2 user turns · 66 tool calls<br/><a href="examples/flange_plate/demo/index.html">▶ Full session replay</a></td>
<td>"Parametric flange: OD 100, thickness 10, hub ⌀55 top +30, bore ⌀30, 6×⌀11 bolt holes on PCD 78, hub-root R3 / rim R2 fillets; every dimension a named parameter; edge-selection cards printed before each fillet; parameter-feasibility guards; one feature per block."<br/><br/><i>GIF shows the final 8-hole @PCD 84.5 state: turn 2 re-parameterized 6→8 holes; PCD 88 was rejected live by the guards and 85 excluded for fillet tangency.</i></td>
<td><img src="img/capability/flange_turntable.gif" width="420" alt="flange turntable"></td>
</tr>
<tr>
<td><b>Ribbed L-bracket (FEM main model)</b><br/>2 user turns · 49 tool calls<br/><a href="examples/ap242_gmsh_volume_mesh/demo/index.html">▶ Full session replay</a></td>
<td>"Formalize the existing legacy L-bracket script through the single-part workflow: rebuild with FTC feature blocks and named parameters; geometric equivalence to the legacy model (volume delta < 0.1%); the <code>interface.*</code> FEM boundary tags must survive untouched — the downstream Gmsh/CalculiX pipeline selects faces by them."</td>
<td><img src="img/capability/bracket_turntable.gif" width="420" alt="bracket turntable"></td>
</tr>
Turntables are rendered by the in-repo [Scene Viewer](viewer/)'s BRep renderer
(face shading + wide edges); one full turn = 48 deterministic azimuth steps
driven through `viewer/gif-harness.html`.

</table>

### 2 · Assembly Modeling

Nested durable assemblies with explicit kinematics: gear meshes, revolute
joints, and bearing interfaces are solved constraints, not eyeballed
positions. Standard parts — involute gears, ball bearings (as subassemblies
with individual balls), roller-chain sprockets, metric fasteners with real
thread profiles — come from `scad.std.*` and compose into mechanisms that
export to STEP, editable FreeCAD projects, and MJCF for physics engines.

<table>
<tr>
<td width="44%" align="center" valign="top">
<img src="img/capability/bldc_assembly.png" alt="BLDC joint actuator assembled"><br/>
<b>Integrated BLDC joint actuator</b> — assembled, studio render<br/>
29 components · 51 constraints, all solved · 20:1 two-stage planetary
</td>
<td width="56%" align="center" valign="top">
<img src="img/capability/bldc_exploded.gif" width="430" alt="BLDC joint actuator exploded turntable"><br/>
<b>Same model, exploding turntable</b> — four modules (ESC · motor ·<br/>
two-stage reducer · output shaft) separate along the axis while<br/>
concentric parts peel into radius bands; camera circles on an inclined orbit
</td>
</tr>
</table>

Reproduce it: `uv run python examples/integrated_bldc_joint_actuator/main.py`
builds the package from scratch; `render_showcase.py` renders the views above;
`export_all.py` emits STEP / editable FCStd / MJCF.

### 3 · Reverse Engineering

Import a STEP, inspect its BREP in the browser, and click the geometric
entities you care about — each pick lands as a tag in an annotation composer
next to operation intents (sketch · boolean · fillet · pattern …) and a free
note. Your reverse-engineering hunches ride on concrete face tags, so the
agent receives a narrowed search space instead of guessing from scratch —
and the whole human-agent session is recorded and replayable.

<table>
<tr>
<td width="50%" align="center" valign="top">
<img src="img/capability/reverse_studio_mvp.gif" alt="re-studio: click faces, annotate intent, agent rebuilds"><br/>
<b>re-studio MVP</b> — click faces on the STEP target, stack operation
chips and notes per pick, submit; the agent classifies all 37 faces of a
link rod and starts rebuilding from your context ·
<a href="img/capability/reverse_studio_mvp.mp4">▶ full video</a>
</td>
</tr>
</table>

### 4 · Simulation Plugins

The same parametric package feeds downstream solvers without manual rework:
AP242 STEP into Gmsh for volume meshing and CalculiX for static FEM (boundary
faces are selected by preserved `interface.*` tags, so simulation survives
model revisions), and MJCF into MuJoCo for mechanism dynamics — where a
virtual-collision pass catches assembly interference and drives the correction
before the mechanism runs clean.

<table>
<tr>
<td width="34%" align="center" valign="top" rowspan="2">
<img src="img/capability/ap242_gmsh_bracket_static_von_mises.png" alt="Bracket FEM von Mises"><br/>
<b>L-bracket static FEM</b> — CalculiX von Mises<br/>
meshed via Gmsh OpenCASCADE kernel from the AP242 export
</td>
<td width="33%" align="center" valign="top">
<img src="img/capability/fourbar_collision_before.gif" alt="Four-bar assembly with links crashing into each other in MuJoCo"><br/>
<b>Four-bar linkage + MuJoCo</b> — first assembly pass:<br/>
the links crash through each other mid-cycle; the assembly is wrong ·
<a href="img/capability/fourbar_collision_before.mp4">▶ full video</a>
</td>
</tr>
<tr>
<td width="33%" align="center" valign="top">
<img src="img/capability/fourbar_collision_after.gif" alt="Corrected four-bar assembly articulating clean in MuJoCo"><br/>
<b>After the virtual-collision correction</b> — corrected assembly:<br/>
the full crank cycle sweeps clean in the same sim ·
<a href="img/capability/fourbar_collision_after.mp4">▶ full video</a>
</td>
</tr>
</table>

---

## Update Notes (2.1.3b1)

> **Release notice:** Pre-release (beta). Validate generated definitions,
> assembly constraints, and manufacturing geometry before production use.

SimpleCADAPI 2.1.3b1 ships the addon ecosystem: a `sca` CLI that installs
third-party skill+tooling repositories (`sca addon init/add/update/remove/list`),
a strict `sca-addon.toml` descriptor with platform and `[compat] sca` gates, and
a consumer-facing `.scadpkg` format spec written so an agent given the document
alone can produce a correct parser or exporter. See the
[full English update notes](docs/updates/2.1.3b1.md) for the CLI contract, the
two legal integration modes, and the tag channel; 2.1.2's script-anchored part
cache is described in [docs/updates/2.1.2.md](docs/updates/2.1.2.md).

All formal single-script examples emit a synchronized `.scadpkg`, AP242
`.step`, and editable `.FCStd` from the same product package. The
split AP242/Gmsh example under `examples/ap242_gmsh_volume_mesh/` exposes
each build and export stage as a separate directly runnable script.

---

<div align="center">
  <h2>SimpleCADAPI Research Artifact</h2>
  <p>This repository is an artifact of</p>
  <p>
    <strong><a href="https://arxiv.org/abs/2608.00891">CADIR: A Cross-Backend Editable Intermediate Representation for Agentic CAD Generation</a></strong>
  </p>
</div>

---

SimpleCADAPI is an OCP-native Python SDK for building CAD models with clear,
functional operations and replayable model graphs. It wraps OpenCascade geometry
in a compact public API for creating solids, applying features, tagging semantic
intent, querying topology, exporting manufacturing files, and translating recorded
models into FreeCAD workflows.

Current release: `simplecadapi==2.1.3`.

## What It Provides

- OCP-native shape types: `Vertex`, `Edge`, `Wire`, `Face`, and `Solid`.
- Functional modeling operations for primitives, profiles, extrude, revolve,
  loft, sweep, booleans, transforms, patterns, fillets, chamfers, and shells.
- Replayable operation graphs with explicit `GraphSession`,
  `export_model_json(...)`, `import_model_json(...)`, and `replay_model_json(...)`.
- Expression parameters with `var(...)`, arithmetic expressions, and serialized
  expression graphs.
- Physical units with automatic dimension inference, canonical CAD conversion,
  and manufacturing tolerance-chain validation.
- QL selectors for geometry grounding, topology queries, and stable feature
  selections.
- Semantic tags through `apply_tag(shape=..., tag=...)` and `list_tags(shape=...)`.
- STEP/STL export, editable FreeCAD product-package translation, and AP242
  product-structure export with material and named metadata properties.
- Agent-oriented STEP/BREP reconstruction with stable entity IDs, focused local
  diagnostics, highlighted region renders, and measured acceptance gates.
- Replayable open and periodic interpolated B-spline Edges/Wires for freeform
  profiles and Loft sections.
- Durable `@part`/`@assemble` definitions, incremental assembly solving, and a
  persistent content-addressed cache with corruption quarantine and JSON diagnostics.

## Install

```bash
pip install simplecadapi
```

With `uv`:

```bash
uv add simplecadapi
```

For local development from this repository:

```bash
uv sync --group dev
```

### Agent Skill

After installing with pip above, install the bundled skill for your agent
harness:

```bash
sca skill targets
# Default location (~/.agents/skills), or select ZCode's explicitly:
sca skill install --target zcode --skills-dir ~/.zcode/skills
```

`targets` lists the available harness targets. `install` compiles the bundled
source and writes it to `<skills-dir>/simplecadapi`; without `--skills-dir`,
it uses the existing addon configuration/environment resolution, falling back
to `~/.agents/skills`; `sca init` is not required. The wheel includes the
uncompiled `docs/skill/` source tree and `skillproj.toml` as package
resources — compilation happens on install, no repository checkout needed.
With `uv`, prefix these commands with `uv run`.

`install` fails if the destination already exists. Add `--force` to replace it
only if it is a directory whose `SKILL.md` declares the matching skill name
(`simplecadapi`); unrelated directories cannot be overwritten.

## Quick Start

```python
from pathlib import Path

import simplecadapi as scad

out = Path("out")

@scad.part(id="bracket")
def build_bracket() -> scad.Solid:
    base = scad.make_box_rsolid(
        width=60.0, height=36.0, depth=8.0, bottom_face_center=(0.0, 0.0, 0.0)
    )
    hole = scad.make_cylinder_rsolid(
        radius=5.0, height=14.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    slot = scad.make_box_rsolid(
        width=18.0, height=8.0, depth=14.0, bottom_face_center=(14.0, 0.0, -3.0)
    )
    body = scad.cut_rsolid(base, hole, slot)
    boss = scad.make_cylinder_rsolid(
        radius=8.0, height=7.0, bottom_face_center=(-18.0, 0.0, 8.0)
    )
    return scad.apply_tag(
        shape=scad.union_rsolid(body, boss),
        tag="role.demo.bracket",
    )

result = build_bracket()
package_path = out / "bracket.scadpkg"
scad.capture(result, package_path)
print("volume", round(result.part.body.get_volume(), 3))
print("tags", scad.list_tags(shape=result.part.body))
scad.exporter.export_product_package_to_step(package_path, out / "bracket.step")
scad.exporter.export_product_package_to_stl(package_path, out / "bracket.stl")
scad.exporter.export_product_package_to_obj(package_path, out / "bracket.obj")
```

## Replayable Operation Graphs

Use an explicit `GraphSession` when a geometry flow should be inspectable,
serializable, replayable, or translated into another CAD environment.

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json
from simplecadapi import ql as Q

with GraphSession(graph_id="chamfered_block") as session:
    body = scad.make_box_rsolid(
        width=40.0, height=24.0, depth=10.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    cutter = scad.make_cylinder_rsolid(
        radius=4.0, height=16.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    drilled = scad.cut_rsolid(body, cutter)

    bottom_circle = (
        Q.edges()
        .where(Q.curve_type(kind="circle"))
        .order_by(Q.center_axis(axis="z"))
        .take(1)
        .exactly(1)
    )
    final = scad.chamfer_rsolid(solid=drilled, edges=bottom_circle, distance=0.6)
    session.capture_result(value=final)
    model_json = export_model_json(session=session)
    recorded_nodes = session.graph.node_count

rebuilt = replay_model_json(json_str=model_json)
print("recorded_nodes", recorded_nodes)
print("replayed_outputs", len(rebuilt))
```

An explicit `GraphSession` remains in memory until an export API is called.
For a durable CAD/viewer deliverable, define one physical single-solid part with
`@scad.part` or an assembly with `@scad.assemble`, then capture and write it in one call:

```python
scad.capture(result, "out/product.scadpkg")
```

The package embeds the definition closure, evaluated scene, feature graphs,
source snapshots, topology, and render/selection assets. STEP, STL, FCStd, and
low-level JSON remain explicit exports.

## Persistent Product Builds And Cache

Use `@scad.part` for one physical single-solid part and `@scad.assemble` for an
assembly with explicit external definitions. Both use the unified `CachePolicy`;
same-key part calls reuse the runtime PRT in process, while durable part bundles
persist unchanged PRTs across later runs.

```python
@scad.part(id="mounting_plate", cache="auto")
def build_plate(width: float = 30.0) -> scad.Part:
    body = scad.make_box_rsolid(width=width, height=20.0, depth=3.0)
    return scad.make_part_rpart(part_id="mounting_plate", body=body)

cold = build_plate()
warm = build_plate()
print(cold.cache_report.hit, warm.cache_report.hit)
```

Inspect or maintain the cache with stable JSON output:

```bash
sca cache status
sca cache verify
sca cache prune
```

See the [persistent cache and product build workflow](docs/skill/references/docs/guides/cache-build-workflow.md)
for cache modes, configuration precedence, PRT reuse, incremental invalidation,
corruption repair, and destructive-command confirmation.

```python
scad.capture(warm, "out/mounting_plate.scadpkg")
scad.translator.freecad_translator.translate_product_package_to_fcstd(
    "out/mounting_plate.scadpkg", "out/mounting_plate.FCStd"
)
scad.exporter.export_product_package_to_step(
    "out/mounting_plate.scadpkg", "out/mounting_plate.step"
)
scad.exporter.export_product_package_to_stl(
    "out/mounting_plate.scadpkg", "out/mounting_plate.stl"
)
scad.exporter.export_product_package_to_obj(
    "out/mounting_plate.scadpkg", "out/mounting_plate.obj"
)
```

### Command-line product export

Export the standard delivery set (AP242 STEP, binary STL, and OBJ) from a
validated product package with no wrapper script:

```bash
uv run sca export out/mounting_plate.scadpkg --output-dir out/exports
```

Request additional targets explicitly.  FCStd requires `FreeCADCmd` (or an
explicit `--freecad-cmd` path); `--check` validates the package, output paths,
and selected target prerequisites without writing files.

```bash
uv run sca export out/mounting_plate.scadpkg \
  --format fcstd --format mjcf --output-dir out/exports --check
uv run sca export out/mounting_plate.scadpkg \
  --format fcstd --freecad-cmd /path/to/FreeCADCmd --output-dir out/exports
```
STL and OBJ share one direct OpenCASCADE tessellation of the evaluated BREP.
Both outputs contain the same oriented triangles and require no optional
remeshing dependency. Control curved-surface accuracy with `linear_deflection`
and `angular_deflection_degrees`.

The AP242/Gmsh example also includes an optional CalculiX FEM workflow. Install
the Python-side FEM dependencies with `uv sync --extra fem`, and install the
external CalculiX solver separately (on macOS: `brew install
costerwi/homebrew-calculix/calculix-ccx`). The example uses consistent `mm`,
`N`, and `MPa` units:

```bash
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py \
  --ccx "$(brew --prefix calculix-ccx)/bin/ccx_2.23"
uv run --extra fem python examples/ap242_gmsh_volume_mesh/visualize_calculix.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/study_mesh_convergence.py \
  --ccx "$(brew --prefix calculix-ccx)/bin/ccx_2.23" \
  --linear-solver "ITERATIVE CHOLESKY" --solver-timeout 2400
```

The analysis writes CalculiX `.inp`, `.dat`, `.frd`, solver-log, summary JSON,
ParaView `.vtu`, and displaced von-Mises PNG artifacts. The preview shows the
load physical group's yellow boundary and red `-Z` force arrows without
covering the stress heatmap. The convergence study supports `--resume`; failed
solver levels are reported separately and never enter the numerical sequence.

The checked-in `-1000 N` study evaluates eleven mesh sizes from `h=3.0 mm` to
`h=0.25 mm`. A platform requires three consecutive refinement pairs below `5%`
maximum-displacement change and `10%` peak integration-point von-Mises change.
The verification level N is `h=0.25 mm` (`0.0331843 mm`, `98.6392 MPa`), so the
recommended production level N-1 is `h=0.27 mm`. Fine levels use iterative
Cholesky after a same-mesh comparison at `h=0.375 mm` matched SPOOLES within
`0.005%`; this avoids the direct solver's in-memory capacity limit.

## STEP/BREP Inspection

Install the optional rendering dependency when synchronized STEP views,
highlighted regions, or slice overlays are needed:

```bash
pip install "simplecadapi[inspect]"
```

Inspection lives under `simplecadapi.inspect.brep`. These APIs are diagnostic
tools, not modeling operations: they do not enter the graph and are rejected
inside `GraphSession`. Export or obtain the geometry first, then
inspect it outside the modeling script.

Choose calls from the evidence required by the case instead of following a
fixed reverse-engineering pipeline. Start with bounded global and local facts;
add sections, component renders, boundary distance, material difference, or
strict topology comparison only when those facts answer the current question.

```python
from simplecadapi.inspect import brep

summary = brep.inspect_step_rsummary(
    path="target.step",
    include_parameter_groups=True,
)
face = brep.inspect_step_entity_rdescriptor(
    path="target.step",
    entity_id="face:0",
)

print("faces", summary["face_count"])
print("carrier", face["geometry"]["type"])
```

Use the [Reconstruction Agent test specification](docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md)
for controlled runs and the [STEP BREP reverse-engineering guide](docs/skill/references/workflows/reverse-engineering-studio.md)
for the inspection primitives, modeling loop, replay checks, and acceptance gates.

## Physical Units And Tolerances

Declare nominal and manufacturing-tolerance units at the variable boundary.
SimpleCAD evaluates lengths in millimeters and angles in degrees while preserving
the declaration units in model JSON:

```python
import simplecadapi as scad

width = scad.var(
    "width",
    1.0,
    unit="in",
    tolerance=0.1,
    tolerance_unit="mm",
)
height = scad.var("height", 40.0, unit="mm", tolerance=0.2)
diagonal = scad.sqrt(width**2 + height**2)

analysis = scad.analyze_tolerance(diagonal)
check = scad.check_tolerance(diagonal, 0.3, tolerance_unit="mm")

print(analysis.dimension.name, analysis.unit.symbol)
print(analysis.nominal, analysis.lower_bound, analysis.upper_bound)
print("passes", check.passed)
```

Addition and subtraction require matching dimensions. Multiplication, division,
integer powers, and square root derive dimensions. Trigonometric functions require
angle or dimensionless inputs as appropriate. Legacy variables without `unit`
remain supported, but cannot be mixed with unit-declared variables in one
expression.

## Modeling Mental Model

- Start from design intent: reference axes, critical profiles, and the features
  that produce the final solid.
- Build from lower-dimensional geometry to higher-dimensional geometry: profile
  wires/faces first, then solid features such as extrude, revolve, loft, and
  sweep.
- Keep operations functional. Create new values with public functions such as
  `make_rectangle_rface(...)`, `extrude_rsolid(...)`, `cut_rsolid(...)`, and
  `fillet_rsolid(...)`.
- Use tags for semantic intent and selection anchors, for example
  `role.mounting.surface`, `anchor.datum.primary`, or `group.fasteners`.
- Store numeric and geometric facts in metadata or graph payloads, not in tags.
- Use QL to ground selections by geometry facts rather than relying on topology
  iteration order.
- When an indexed topology pick is intentional, pass the index to the plural
  child-geometry getter, such as `get_edges(index)`, `get_faces(index)`,
  `get_wires(index)`, or `get_vertices(index)`, so replayable graph workflows
  preserve the pick as a geo select node.
Use model JSON only for graph replay and inspection. External CAD translation and
file export consume the validated `.scadpkg` closure:

```python
script = scad.translator.freecad_translator.translate_product_package_to_freecad_script(
    package_path
)
scad.translator.freecad_translator.translate_product_package_to_fcstd(
    package_path, "bracket.FCStd"
)
```

Part/Assembly models are written as editable FreeCAD assembly structure: parts are
`App::Part`, assemblies are `Assembly::AssemblyObject`, and components are links.
The exporter namespace owns neutral STEP and STL file output.

## Examples

Every example is a self-contained folder: sources, verification scripts, and
fresh artifacts under `examples/<name>/out/`. The set covers part modeling,
assemblies, reverse engineering, and FEM — see the category index in
[`examples/README.md`](examples/README.md).

```bash
# part (quickstart FTC example, external verification script included)
uv run python examples/flange_plate/model.py

# assembly (two-stage planetary reducer, MJCF export)
uv run python examples/compact_two_stage_planetary_reducer/main.py

# FEM (AP242 STEP -> Gmsh volume mesh -> Calculix statics)
uv run python examples/ap242_gmsh_volume_mesh/model.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py
```

Reverse engineering runs through the browser studio in `viewer/re.html`
against a target STEP (see `examples/bowl_connector/`).

## Documentation

- 2.1.3b1 update notes: [`docs/updates/2.1.3b1.md`](docs/updates/2.1.3b1.md)
- 2.1.2 update notes: [`docs/updates/2.1.2.md`](docs/updates/2.1.2.md)
- 2.1.1 update notes: [`docs/updates/2.1.1.md`](docs/updates/2.1.1.md)
- 2.1.0 update notes: [`docs/updates/2.1.0.md`](docs/updates/2.1.0.md)
- Reconstruction Agent test specification:
  [`docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md`](docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md)
- Reverse-engineering studio workflow:
  [`docs/skill/references/workflows/reverse-engineering-studio.md`](docs/skill/references/workflows/reverse-engineering-studio.md)
- Persistent cache and product build workflow:
  [`docs/skill/references/docs/guides/cache-build-workflow.md`](docs/skill/references/docs/guides/cache-build-workflow.md)
- Public API reference: [`docs/skill/references/docs/api/`](docs/skill/references/docs/api/)
- Core type and modeling notes: [`docs/skill/references/docs/core/`](docs/skill/references/docs/core/)
- Serialization and replay details:
  [`docs/skill/references/docs/core/serialization/README.md`](docs/skill/references/docs/core/serialization/README.md)
- Dimension tolerance chains:
  [`docs/core/dimension-tolerance-chains.md`](docs/skill/references/docs/core/dimension-tolerance-chains.md)
- Physical units and dimension inference:
  [`docs/core/physical-units.md`](docs/skill/references/docs/core/physical-units.md)
- Operation graph JSON spec:
  [`docs/core/operation_graph_json_spec.md`](docs/skill/references/docs/core/operation_graph_json_spec.md)
  `.scadpkg` 产品包规范（中文）：[`design-docs/scadpkg-spec.md`](design-docs/scadpkg-spec.md)

## Releasing the Agent Skill

The skill source tree lives under `docs/skill/` and stays harness-neutral.
`tools/skillbuild.py` wraps the same compiler the `sca skill` CLI uses, for
maintainer builds in this repository: it compiles per harness target (targets
and default output directories are configured in `skillproj.toml`; the outputs
under `skills/simplecadapi-*/` are regenerable build artifacts and are not
committed). Harness-specific text, when it is ever needed, is marked with
`<!-- skill:if ... -->` conditional blocks that compile per target. The wheel
itself never contains precompiled targets — end users install from the
bundled source with `sca skill install`.

From a clean checkout, update the project version and documentation, then
build and validate the release artifacts:

```bash
uv sync --group dev
uv run python tools/auto_docs_gen.py --quiet
uv run python tools/skillbuild.py --target omp
uv run pytest test/test_skill_build.py
tar -C skills -czf skills/simplecadapi.tar.gz simplecadapi-omp
```

The commands regenerate the API references inside the skill tree, recompile
the omp target, and create `skills/simplecadapi.tar.gz`. Review the source
tree and the compiled output before release:

```bash
git diff -- docs/skill
tar -tzf skills/simplecadapi.tar.gz | head
```

Commit only the `docs/skill/` source tree; the release workflow builds the
harness outputs and uploads the archive to the GitHub release. Prefer
`sca skill` for installation from a pip-installed package.

## Development

```bash
uv sync --group dev
uv run python -m pytest test tests
python3 -m compileall src/simplecadapi
```

## License

Apache-2.0, see [`LICENSE`](LICENSE).

## Community

The group chat currently has too many members for direct QR-code joining. Scan the QR code below to add Teacher Du Peng on WeChat, then ask him for an invitation to the CADDesigner technical community:

<p align="center">
  <img src="img/dp个人账号.png.jpg" alt="Teacher Du Peng's personal WeChat QR code" width="420">
</p>

## Star History

<a href="https://www.star-history.com/?repos=PhySpace%2FSimpleCADAPI&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&legend=top-left" />
 </picture>
</a>
