"""Translate the captured bracket into a SolidWorks automation script."""

from __future__ import annotations

import simplecadapi as scad

from bracket_package import OUT_DIR, capture_bracket


SCRIPT_PATH = OUT_DIR / "ap242_gmsh_bracket.solidworks.py"
SOLIDWORKS_PATH = OUT_DIR / "ap242_gmsh_bracket.SLDPRT"


def main() -> None:
    package_path = capture_bracket()
    script = scad.translator.solidworks_translator.translate_product_package_to_solidworks_script(
        data=package_path,
        document_name="AP242GmshBracket",
        output_path=str(SOLIDWORKS_PATH),
    )
    SCRIPT_PATH.write_text(script, encoding="utf-8")
    print("solidworks_script", SCRIPT_PATH)
    print("solidworks_output_when_run", SOLIDWORKS_PATH)


if __name__ == "__main__":
    main()
