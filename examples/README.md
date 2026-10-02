# SimpleCADAPI Examples

Every example is a self-contained folder: the model notebooks, the plain
modules they import, export and verification scripts, and fresh artifacts in
its own `out/` folder (`examples/<example>/out/`, ignored by git).

## How an example is laid out

- **Part notebooks** (`<part>.py`): one marimo notebook per part, one FTC
  feature block per cell. The PEP 723 header names the product id
  (`[tool.simplecadapi] id = "..."`); the last cell builds the `Part`.
- **Part families**: one notebook used with different parameters. The product
  takes its id from `scad.notebook_id()`, and each use gives its own id:
  `scad.use("link_bar.py", id="crank", CENTER_DISTANCE=40.0)`.
- **Assembly notebooks** (`<product>.py`): `scad.use(...)` cells load the
  child parts and sub-assemblies, later cells add components, constraints and
  the strict solve. Sub-assemblies are notebooks too.
- **Plain modules** (`dimensions.py`, `common.py`, `materials.py`, ...):
  parameters, specs and geometry helpers. Notebooks import them; they never
  import notebooks.
- **Scripts** (`export.py`, `export_*.py`, `verify.py`, ...): load the product
  with `run_notebook(...)`, write the `.scadpkg` with `scad.capture(...)`, then
  export, translate or check. Code is the model; the package is only for
  exchange and publishing.

Work with a notebook from the repository root:

```bash
marimo edit examples/four_bar_linkage/link_bar.py     # interactive, cell-cached
sca run examples/four_bar_linkage/four_bar_linkage.py # headless, prints content_hash
uv run python examples/four_bar_linkage/export.py     # package + exchange files in out/
```

## Examples by category

| Example | Category | Product notebook | Run | Key artifacts (`out/`) |
| --- | --- | --- | --- | --- |
| `flange_plate/` | part | `flange_plate.py` | `export.py`, `render_views.py`, `verify.py` | `flange_plate.scadpkg` + `.step` + PNG (quickstart FTC part, session replay under `demo/`) |
| `caplcd_enclosure/` | part | `caplcd_enclosure.py` | `export.py` | `caplcd_enclosure_7ep.scadpkg` + `.step` + `.FCStd` |
| `dimension_tolerance_chain/` | part (tolerances) | `dimension_tolerance_chain.py` | `report.py` | worst-case / RSS report, `.scadpkg` + `.step` + `.FCStd` |
| `constrained_sketch/` | part (sketch) | `constrained_sketch.py` | `export.py` | `constrained_sketch.scadpkg` + `.step` + `.FCStd` |
| `arc_handle/` | part + FEM | `arc_handle.py` | `export.py`, then `uv run --extra fem python examples/arc_handle/fem_analysis.py` | `arc_handle.scadpkg`, render, `fem/` analysis |
| `hydraulic_rod_assembly/` | assembly | `hydraulic_rod_assembly.py` | `export.py` | `hydraulic_rod_assembly.scadpkg` + `.step` + `.FCStd` |
| `external_reference_gear_train/` | assembly (nested) | `nested_external_reference_gear_trains.py` | `export.py` | `nested_external_reference_gear_trains.scadpkg` + STEP/FCStd |
| `four_bar_linkage/` | assembly (kinematics, part family) | `four_bar_linkage.py` | `export.py`, `export_mjcf.py` | `four_bar_linkage.scadpkg` + STEP + MJCF |
| `u_link_motor_mount/` | assembly | `u_link_motor_mount.py` | `export.py`, `verify/acceptance.py` | `u_link_assembly.scadpkg` + STEP/STL + renders (`demo/index.html` session replay) |
| `l_link_motor_mount/` | assembly (part family) | `l_link_motor_mount.py` (`--id l-link-motor-mount-<preset> --set PRESET=<preset>`) | `export.py`, `verify/acceptance.py`, `verify/export_artifacts.py` | `l_link_assembly_<preset>.scadpkg` + STEP/STL per adapter preset + renders |
| `pcg_attractor_canopy/` | part (procedural) | `attractor_canopy.py` | `export.py`, `verify.py` | `attractor_canopy.scadpkg` + STEP/STL/OBJ + GIF |
| `compact_two_stage_planetary_reducer/` | assembly (part families) | `compact_two_stage_planetary_reducer.py` | `export.py`, `export_mjcf.py` | `compact_two_stage_planetary_reducer.scadpkg` + STEP/FCStd/MJCF |
| `integrated_bldc_joint_actuator/` | product (sub-assembly notebooks) | `integrated_bldc_joint_actuator.py` | `export_all.py`, `render_showcase.py` | `integrated_bldc_joint_actuator.scadpkg` + STEP/FCStd/MJCF + renders |
| `ap242_gmsh_volume_mesh/` | FEM / data exchange | `bracket.py` | see below | AP242 + Gmsh volume mesh + CalculiX statics |
| `bowl_connector/` | reverse engineering | — | Re-mode workspace in the unified Web Editor | rebuild artifacts under `re_work/` |
| `histcad_demo/` | translation demos | — | `uv run python examples/histcad_demo/<script>.py` | per-dialect FTC script + render |
| `demo_kit/` | infra | — | — | shared single-file demo builder (`build_demo.py`) |

Scripts run as `uv run python examples/<example>/<script>`. `histcad_demo/`
is translator output and stays in the translator's library form (plain
`build_*` functions), not notebooks. The design notes of the two large
assemblies (`DESIGN.md`) include a table of every notebook and module.

## FEM / data exchange workflow (`ap242_gmsh_volume_mesh/`)

The model is the `bracket.py` notebook. `bracket_package.py` runs it and writes
`out/ap242_gmsh_bracket.scadpkg`; every script below starts from that package:

```bash
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
and SolidWorks.

FEM meshing consumes the STEP produced by `export_step.py`; the static solve
needs the CalculiX solver (`ccx`) on PATH or in `CALCULIX_BIN`:

```bash
uv run --extra gmsh python examples/ap242_gmsh_volume_mesh/export_fem_mesh.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py
```
