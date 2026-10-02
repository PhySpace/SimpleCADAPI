"""Check and export the hydraulic rod assembly: package, STEP and FreeCAD.

    uv run python examples/hydraulic_rod_assembly/export.py

The model is the ``hydraulic_rod_assembly.py`` notebook and its two part
notebooks; this script checks the parts' face naming, then writes the
exchange files to ``out/``.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"


def check_face_naming(solid: scad.Solid, prefix: str) -> None:
    """Every face of *solid* carries a tag starting with *prefix*."""
    unnamed = [
        index
        for index, face in enumerate(ql.faces().resolve(solid))
        if not any(tag.startswith(prefix) for tag in scad.list_tags(face, scope="local"))
    ]
    if unnamed:
        raise RuntimeError(f"{prefix} face naming is incomplete at indices {unnamed}")


def check_shared_edge(solid: scad.Solid, first_face_tag: str, second_face_tag: str) -> None:
    """The two tagged faces meet in one edge, found the same by both queries."""
    first = ql.faces().where(ql.tag(first_face_tag)).exactly(1)
    second = ql.faces().where(ql.tag(second_face_tag)).exactly(1)
    shared = first.shared_boundary(second).incident_face_count(exactly=2)
    incident = (
        ql.edges().incident_to(first, second, distinct=True).incident_face_count(exactly=2)
    )
    if shared.exactly(1).resolve(solid)[0].topo_id != incident.exactly(1).resolve(solid)[0].topo_id:
        raise RuntimeError(
            f"faces {first_face_tag!r} and {second_face_tag!r} did not resolve one shared edge"
        )


def main() -> None:
    sleeve = run_notebook(HERE / "outer_sleeve.py").product.body
    rod = run_notebook(HERE / "piston_rod.py").product.body
    check_face_naming(sleeve, "sleeve.")
    check_face_naming(rod, "rod.")
    for first, second in (
        ("sleeve.gland.face.mount", "sleeve.gland.face.outer"),
        ("sleeve.gland.nose.face.front", "sleeve.barrel.bore.face.wall"),
        ("sleeve.gland.face.mount", "sleeve.gland.bolt.zplus.face.wall"),
        ("sleeve.gland.face.mount", "sleeve.gland.bolt.yplus.face.wall"),
    ):
        check_shared_edge(sleeve, first, second)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "hydraulic_rod_assembly.py")
    assembly = run.product
    preview = scad.make_compound_from_assembly_rcompound(assembly=assembly)
    package_path = OUT_DIR / "hydraulic_rod_assembly.scadpkg"
    scad.capture(run.definition, package_path)
    step_report = scad.exporter.export_product_package_to_step(
        package_path, OUT_DIR / "hydraulic_rod_assembly.step"
    )
    fcstd_path = OUT_DIR / "hydraulic_rod_assembly.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        package_path,
        str(fcstd_path),
        document_name="HydraulicRodAssembly",
    )
    print("assembly", assembly.assembly_id)
    print("components", assembly.component_ids())
    print("preview_solids", len(ql.solids().resolve(preview)))
    print("preview_faces", len(ql.faces().resolve(preview)))
    print("preview_volume", round(preview.get_volume(), 3))
    print("content hash", run.definition.content_hash)
    print("product package", package_path)
    print("step", step_report.output_path)
    print("fcstd", fcstd_path)


if __name__ == "__main__":
    main()
