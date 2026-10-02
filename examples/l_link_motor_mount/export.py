"""Export the l_link motor mount: packages, STEP, STL and evidence renders.

    uv run python examples/l_link_motor_mount/export.py

The models are the notebooks (``l_link.py``, ``shell.py``, ``adapter_plate.py`` per preset and the
``l_link_motor_mount.py`` assembly per preset); this script only loads their products with
``run_notebook`` and writes the exchange files to ``out/``:

  l_link_assembly_<preset>.scadpkg / .step / .stl   solved body + shell + plate assembly, one per PlatePreset
  adapter_plate_<preset>.scadpkg / .step / .stl     motor-2 adapter plate part, one per PlatePreset
  l_link_body.* / l_link_shell.*                    upper body / shell parts (print one file per part)
  render_assembly_<preset>.png, render_parts.png    delivered-state views
  export_facts.json                                 reference volumes + export reports (read by verify/export_artifacts.py)

STEP / STL are written from the captured package (never from live solids) -- export-and-translation.md.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
sys.path.insert(0, str(HERE))

from dimensions import PlatePreset, assembly_id, params, plate_part_id  # noqa: E402

STL_DEFLECTION = {"linear_deflection": 0.02, "angular_deflection_degrees": 8.0}  # rim fillets 1.2, pilot ⌀1.6


def export(run, stem: str, bodies: dict) -> dict:
    """capture -> STEP + STL from the package; bodies = {name: Solid} reference volumes for the reopen check.

    A capture failure is recorded as {"blocked": ...} (and the remaining products still export) so
    verify/export_artifacts.py reports it instead of the whole run dying on the first product."""
    pkg = OUT_DIR / f"{stem}.scadpkg"
    for stale in OUT_DIR.glob(f"{stem}.*"):
        stale.unlink()
    try:
        scad.capture(run.definition, pkg)
    except Exception as exc:  # noqa: BLE001 -- SDK capture/validation error, surfaced in export_facts.json
        print(f"{stem}: BLOCKED {type(exc).__name__}: {exc}")
        return {"blocked": f"{type(exc).__name__}: {exc}"}
    step = scad.exporter.step.export_product_package_to_step(data=pkg, output_path=OUT_DIR / f"{stem}.step")
    stl = scad.exporter.stl.export_product_package_to_stl(
        data=pkg, output_path=OUT_DIR / f"{stem}.stl", linear_deflection=STL_DEFLECTION["linear_deflection"],
        angular_deflection_degrees=STL_DEFLECTION["angular_deflection_degrees"])
    print(f"{stem}: pkg={pkg.stat().st_size}B step defs={step.definition_ids} occ={step.occurrence_count} "
          f"stl solids={stl.solid_count} tri={stl.triangle_count}")
    return {"package": pkg.name, "content_hash": run.definition.content_hash, "step": step.to_dict(),
            "stl": asdict(stl), "volumes": {k: v.get_volume() for k, v in bodies.items()}}


def part_body(run) -> scad.Solid:
    assert isinstance(run.product, scad.Part), f"{run.config.id}: product is not a Part"
    return run.product.body


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    facts = {"params": params(), "stl_deflection": STL_DEFLECTION, "products": {}}
    body_run, shell_run = run_notebook(HERE / "l_link.py"), run_notebook(HERE / "shell.py")
    body, shell = part_body(body_run), part_body(shell_run)
    facts["products"]["l_link_body"] = export(body_run, "l_link_body", {"body": body})
    facts["products"]["l_link_shell"] = export(shell_run, "l_link_shell", {"shell": shell})

    plates = {}
    for preset in PlatePreset:
        plate_run = run_notebook(HERE / "adapter_plate.py", id=plate_part_id(preset),
                                 overrides={"PRESET": preset.value})
        plates[preset] = plate = part_body(plate_run)
        facts["products"][f"adapter_plate_{preset.value}"] = export(
            plate_run, f"adapter_plate_{preset.value}", {"plate": plate})
        asm_run = run_notebook(HERE / "l_link_motor_mount.py", id=assembly_id(preset),
                               overrides={"PRESET": preset.value})
        assembly = asm_run.product
        assert isinstance(assembly, scad.Assembly)
        report = scad.inspect_assembly_constraints_rconstraintreport(assembly=assembly)
        entry = export(asm_run, f"l_link_assembly_{preset.value}", {"body": body, "shell": shell, "plate": plate})
        if "blocked" not in entry:
            entry["components"] = list(assembly.component_ids())
            entry["residuals_ok"] = report.solved and all(r.within_tolerance for r in report.residuals)
        facts["products"][f"l_link_assembly_{preset.value}"] = entry
        scad.render_screenshot_rpath(
            shapes=[body, shell, plate], output_path=str(OUT_DIR / f"render_assembly_{preset.value}.png"),
            views=[(25, 35, "iso"), (90, 0, "front (XY, from +Z)"), (0, 0, "right (along -X)"), (-30, 215, "underside")],
            view_up=(0.0, 1.0, 0.0), show_callouts=False)

    scad.render_screenshot_rpath(
        shapes=[body, scad.translate_shape(shape=shell, vector=(0.0, -16.0, 0.0)),
                scad.translate_shape(shape=plates[PlatePreset.STAR3], vector=(24.0, 0.0, 0.0)),
                scad.translate_shape(shape=plates[PlatePreset.CENTER4], vector=(24.0, 0.0, 32.0))],
        output_path=str(OUT_DIR / "render_parts.png"),
        views=[(25, 35, "exploded iso"), (-30, 215, "exploded underside")], view_up=(0.0, 1.0, 0.0),
        show_callouts=False)

    (OUT_DIR / "export_facts.json").write_text(json.dumps(facts, indent=2, default=str, ensure_ascii=False))
    print("export done")


if __name__ == "__main__":
    main()
