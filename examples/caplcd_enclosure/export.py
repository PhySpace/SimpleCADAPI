"""Export the 7EP-CAPLCD rear enclosure tray: package, STEP and FreeCAD.

    uv run python examples/caplcd_enclosure/export.py

The model is the ``caplcd_enclosure.py`` notebook; this script only loads its
product and writes the exchange files to ``out/``.
"""

from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run = run_notebook(HERE / "caplcd_enclosure.py")
    package_path = OUT_DIR / "caplcd_enclosure_7ep.scadpkg"
    scad.capture(run.definition, package_path)
    step_report = scad.exporter.export_product_package_to_step(
        package_path, OUT_DIR / "caplcd_enclosure_7ep.step"
    )
    fcstd_path = OUT_DIR / "caplcd_enclosure_7ep.FCStd"
    scad.translator.freecad_translator.translate_product_package_to_fcstd(
        package_path,
        str(fcstd_path),
        document_name="CaplcdEnclosure7EP",
    )
    print("tray volume", round(run.product.body.get_volume(), 1))
    print("content hash", run.definition.content_hash)
    print("geometry interface", run.definition.interface_hashes.geometry)
    print("product package", package_path)
    print("step", step_report.output_path)
    print("fcstd", fcstd_path)


if __name__ == "__main__":
    main()
