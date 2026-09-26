# SimpleCADAPI Examples

Run examples from the repository root with `uv run python <path>`.
Every example writes its generated artifacts to its own `out/` folder
(`examples/<example>/out/`, ignored by git), so an example is a
self-contained folder: sources, verification scripts, and fresh artifacts.

Formal single-script examples emit three synchronized artifacts into `out/`:
the canonical self-contained `.scadpkg`, an AP242 `.step`, and an editable
FreeCAD `.FCStd`. Single-solid products use `@scad.part`; assemblies use
`@scad.assemble` with explicit immutable definitions for every physical part
or nested assembly. Both downstream CAD files are translated from the same
product package, so they retain the same definition closure, evaluated
geometry, assembly instances, names, solved placements, materials, and
available semantic metadata.

## Examples by category

| Example | Category | Run | Key artifacts (`out/`) |
| --- | --- | --- | --- |
| `flange_plate/` | part | `uv run python examples/flange_plate/model.py` | `flange_plate.scadpkg` + `.step` + PNG (quickstart FTC part) |
| `caplcd_enclosure/` | part | `uv run python examples/caplcd_enclosure/model.py` | `caplcd_enclosure_7ep.scadpkg` + `.step` + `.FCStd` |
| `dimension_tolerance_chain/` | part | `uv run python examples/dimension_tolerance_chain/model.py` | `dimension_tolerance_chain.scadpkg` + `.step` + `.FCStd` |
| `constrained_sketch/` | part (sketch) | `uv run python examples/constrained_sketch/model.py` | `constrained_sketch.scadpkg` + `.step` + `.FCStd` |
| `arc_handle/` | part + FEM | `uv run python examples/arc_handle/main.py`, then `uv run --extra fem python examples/arc_handle/fem_analysis.py` | `arc_handle.scadpkg`, `fem/` analysis |
| `compact_two_stage_planetary_reducer/` | assembly | `uv run python examples/compact_two_stage_planetary_reducer/main.py` | `compact_two_stage_planetary_reducer.scadpkg` + MJCF |
| `integrated_bldc_joint_actuator/` | assembly | `uv run python examples/integrated_bldc_joint_actuator/main.py` | `integrated_bldc_joint_actuator.scadpkg` + STEP/FCStd/MJCF |
| `four_bar_linkage/` | assembly (kinematics) | `uv run python examples/four_bar_linkage/main.py` | `four_bar_linkage.scadpkg` + MJCF |
| `hydraulic_rod_assembly/` | assembly | `uv run python examples/hydraulic_rod_assembly/model.py` | `hydraulic_rod_assembly.scadpkg` + `.step` + `.FCStd` |
| `external_reference_gear_train/` | assembly (nested) | `uv run python examples/external_reference_gear_train/model.py` | `nested_external_reference_gear_trains.scadpkg` |
| `u_link_motor_mount/` | assembly | `uv run python examples/u_link_motor_mount/assembly.py` | `u_link_motor_mount.scadpkg` + STEP/STL (`demo/index.html` session replay) |
| `bowl_connector/` | reverse engineering | Re-mode workspace in the unified Web Editor | rebuild artifacts under `re_work/` |
| `ap242_gmsh_volume_mesh/` | FEM / data exchange | see below | AP242 + Gmsh volume mesh + Calculix statics |
| `demo_kit/` | infra | — | shared single-file demo builder (`build_demo.py`) |
| `histcad_demo/` | translation demos | `uv run python examples/histcad_demo/<script>.py` | per-dialect FTC script + render |

`flange_plate/` contains the quickstart FTC part (`model.py` + external
`verify.py`, documented in its README) and the richer showcase pipeline
(`flange_plate.py` → `export.py`/`render_views.py`, session replay under
`demo/`). The two models differ (6-hole quickstart vs 8-hole showcase); the
showcase pipeline is what the demo replays.

## FEM / data exchange workflow (`ap242_gmsh_volume_mesh/`)

Build the canonical package and the AP242 STEP:

```bash
uv run python examples/ap242_gmsh_volume_mesh/model.py
uv run python examples/ap242_gmsh_volume_mesh/export_fcstd.py
uv run python examples/ap242_gmsh_volume_mesh/export_step.py
uv run --extra gmsh python examples/ap242_gmsh_volume_mesh/export_stl.py
uv run --extra gmsh python examples/ap242_gmsh_volume_mesh/export_obj.py
uv run python examples/ap242_gmsh_volume_mesh/translate_freecad_script.py
uv run python examples/ap242_gmsh_volume_mesh/translate_fusion360_script.py
uv run python examples/ap242_gmsh_volume_mesh/translate_solidworks_script.py
```

The outputs are editable FreeCAD `.FCStd`, AP242 `.step`, triangulated `.stl`,
quad-preserving `.obj`, and standalone Python scripts for FreeCAD, Fusion 360,
and SolidWorks. Every command above reads the same `.scadpkg` directly.

FEM meshing consumes the STEP produced by `export_step.py`; the static solve
needs the Calculix solver (`ccx`) on PATH or in `CALCULIX_BIN`:

```bash
uv run --extra gmsh python examples/ap242_gmsh_volume_mesh/export_fem_mesh.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py
```
