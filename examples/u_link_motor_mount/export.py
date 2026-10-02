"""Export the U-link motor mount: package, STEP, STL and evidence renders.

    uv run python examples/u_link_motor_mount/export.py

The model is the ``u_link_motor_mount.py`` assembly notebook (body + shell);
this script only loads its product and writes the exchange files to ``out/``:

  u_link_assembly.scadpkg    exchange package of the assembly
  u_link_assembly.step/.stl  external formats
  render_front/iso.png       body with the named mounting faces highlighted
  render_assembly.png        body and shell installed
  render_shell.png           shell alone
  export_facts.json          facts read by verify/export_artifacts.py
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
sys.path.insert(0, str(HERE))

from dimensions import TAG_BACK, TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT  # noqa: E402


def render(shapes, name: str, view: tuple[float, float], tags: list[str] | None = None) -> None:
    """Render *shapes* to ``out/<name>`` without axes, callouts or legend."""
    scad.render_screenshot_rpath(
        shapes=shapes, output_path=str(OUT_DIR / name), highlight_tags=tags, view=view,
        show_axes=False, show_callouts=False, show_legend=False)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "u_link_motor_mount.py")
    assembly = run.product
    assert isinstance(assembly, scad.Assembly)
    body = run.values["body"].body
    shell = run.values["shell"].body
    report = scad.inspect_assembly_constraints_rconstraintreport(assembly=assembly)
    print(f"assembly: components={assembly.component_ids()} solved={report.solved} "
          f"residuals_ok={all(r.within_tolerance for r in report.residuals)}")

    tag_hits = {
        tag: len(ql.faces().where(ql.tag(tag)).resolve(body))
        for tag in (TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT, TAG_BACK)
    }
    print(f"body: volume={body.get_volume():.3f} mount/back tag hits={tag_hits}")

    package_path = OUT_DIR / "u_link_assembly.scadpkg"
    scad.capture(run.definition, package_path)
    print(f"captured: {package_path.name} bytes={package_path.stat().st_size}")

    step_report = scad.exporter.step.export_product_package_to_step(
        data=package_path, output_path=OUT_DIR / "u_link_assembly.step")
    stl_report = scad.exporter.stl.export_product_package_to_stl(
        data=package_path, output_path=OUT_DIR / "u_link_assembly.stl",
        linear_deflection=0.05, angular_deflection_degrees=10.0)
    print(f"step defs={step_report.definition_ids} occ={step_report.occurrence_count}")
    print(f"stl solids={stl_report.solid_count} tri={stl_report.triangle_count}")

    # 安装面法向 = 部件 +Y；渲染相机方位角绕 +Z 度量 → 正对安装面须 azim=90
    render(body, "render_front.png", (0.0, 90.0), [TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT])
    render(body, "render_iso.png", (35.0, 30.0), [TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT, TAG_BACK])
    render([body, shell], "render_assembly.png", (35.0, 30.0))
    render(shell, "render_shell.png", (35.0, 30.0))

    (OUT_DIR / "export_facts.json").write_text(json.dumps({
        "content_hash": run.definition.content_hash,
        "stl": asdict(stl_report), "step": step_report.to_dict(),
        "mount_tag_hits": tag_hits,
        "assembly_components": list(assembly.component_ids()),
        "constraint_report": report.to_dict(),
    }, indent=2, default=str))
    print("export done")


if __name__ == "__main__":
    main()
