# Task Domain: Export and Translation

**Read when:** a validated `.scadpkg` must be delivered as STEP, STL, OBJ, MJCF or an editable external CAD document.

Export validated product packages to neutral and mesh formats, and translate
them into editable external CAD backends.

## Use when

- The deliverable is a STEP, STL, OBJ, or MJCF file from a validated
  `.scadpkg` product package.
- An external CAD user needs an editable FreeCAD, Fusion 360, or SolidWorks
  document or script.
- A robotics/simulation consumer needs MJCF with the assembled kinematic tree.

## Do not use

- Exporting before geometry and product validation passed: exports are
  deliverables, not validation.
- Hand-editing exported files; fix the source, re-capture, re-export.

## Target selection

Choose the downstream target from the consumer contract:

| Target | Use when | Preserved contract | Boundary |
| --- | --- | --- | --- |
| `.scadpkg` | Rebuild, replay, or further SimpleCAD tooling | Definition closure, occurrence graph, feature graphs, source snapshots, topology, connectors, constraints, materials | SimpleCAD-specific archive |
| `.FCStd` | A FreeCAD user needs an editable native document | Definition-owned dependency-first feature graphs, repeated instances, nested assemblies, names, solved placements, materials, connectors, constraints, grounding, revision, content hashes | Requires FreeCAD/FreeCADCmd |
| AP242 `.step` | Neutral CAD exchange or OpenCASCADE tooling | Evaluated BREP, product hierarchy, shared definitions, occurrence names/placements, materials, colors, density, named property payloads | Feature history is not reconstructed as AP242 features |
| `.obj` | Surface inspection or DCC exchange | Direct OpenCASCADE tessellation, shared vertices, oriented triangles | Evaluated surface mesh only |
| `.stl` | Additive manufacturing or triangle-only consumers | Same direct tessellation | Facet soup; no shared vertices or hierarchy |
| MJCF | MuJoCo simulation | Canonical occurrence graph kinematics, joint sites from explicit constraints, equality/connect constraints for loop-closing joints | Simulation semantics, not manufacturing |

## API groups

Read the exact page under `references/docs/api/` for every API used:

- Exporters (`scad.exporter`): `export_product_package_to_step`,
  `export_product_package_to_stl`, `export_product_package_to_obj`,
  `export_product_package_to_mjcf`.

  Report fields differ per format — read what the report actually carries:
  `ProductSTEPExportReport` (output path, schema, definition ids, occurrence
  count, material ids, metadata item count, limitations),
  `ProductSTLExportReport` / `ProductOBJExportReport` (definition count, solid
  count, vertex/triangle counts, deflection parameters, backend),
  `ProductMJCFExportReport` (mesh/body/joint/equality/closure/grounded/site
  counts, default density, limitations). Never assume mesh counts exist on the
  STEP report or vice versa.
- Translators (`scad.translator.<backend>`):
  `translate_product_package_to_fcstd`,
  `translate_product_package_to_freecad_script`,
  `translate_product_package_to_fusion360_script`,
  `translate_product_package_to_solidworks_script`, plus
  `FreeCADTranslator`, `Fusion360Translator`, `SolidWorksTranslator`.
- Package reading when downstream tools consume packages directly:
  `read_product_package`, `load_product_package`,
  `validate_product_package`.

## Export rules

- Translate only from a validated product package: `capture` the product
  first, then export from the package path. In a one-shot script (below) the
  exporters also take the build result itself and package it in memory, with
  the same validation and without the scene projection nobody reads.
- STL and OBJ share one direct OpenCASCADE tessellation of the evaluated BREP;
  both contain the same oriented triangles. Control curved-surface accuracy
  with `linear_deflection` (chordal deviation in product units) and
  `angular_deflection_degrees`.
- MJCF joint structure comes from explicit assembly constraints: hinge and
  prismatic edges follow the constraint graph, and public connectors expose
  sites/endpoints only — public exposure alone never implies a joint.
  Loop-closing movable revolute/prismatic joints are emitted as
  equality/connect constraints; gear/belt/rack-pinion couplings are emitted
  as fixed-tendon equality constraints.
- Use `validate_step_roundtrip_rdescriptor` when a STEP export must survive
  re-import (roundtrip-sensitive consumers).

## One-shot script (no notebook, no `.scadpkg` on disk)

For a batch or unattended task whose deliverable is "one script, run as
`python model.py --output part.step`" (read-only source directory, no editor),
a plain script is the supported entry. A notebook is still the form for
anything a person will open, edit or reuse (core rule R3). The runtime keeps
no state next to the source when it runs without the cache.

```python
import argparse
from pathlib import Path

import simplecadapi as scad


@scad.part(id="plate", project_root=Path(__file__).parent)
def build_plate() -> scad.Part:
    body = scad.make_box_rsolid(width=120.0, height=120.0, depth=10.0)
    return scad.make_part_rpart("plate", body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = scad.exporter.export_product_package_to_step(build_plate(), args.output)
    print(report.output_path, report.definition_ids)
```

A notebook run unattended in a read-only directory uses
`run_notebook(path, cache=False)`.

## Validation gates

- Read the returned export report and print its actual fields per format
  (see API groups above); never assume success from a missing exception.
- For `.FCStd`, confirm the translation ran against the intended package
  revision (units are deduplicated by definition identity).
- For MJCF, confirm every intended joint appears, loop-closing movable joints
  are equality/connect, and gear/belt/rack-pinion couplings are fixed-tendon
  equalities.

## Failure modes

- Missing FreeCAD/FreeCADCmd: `.FCStd` translation fails; report the missing
  backend instead of falling back to STEP-only silently.
- Over-coarse tessellation on curved parts: tighten `linear_deflection` /
  `angular_deflection_degrees` and re-export.
- Exporting a stale package: re-capture after source changes before export;
  exports are point-in-time deliverables.
