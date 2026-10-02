"""Translate the captured bracket product package to editable FreeCAD FCStd."""

from __future__ import annotations

import simplecadapi as scad

from bracket_package import OUT_DIR, capture_bracket


FCSTD_PATH = OUT_DIR / "ap242_gmsh_bracket.FCStd"


def main() -> None:
    package_path = capture_bracket()
    output = scad.translator.freecad_translator.translate_product_package_to_fcstd(
        data=package_path,
        output_path=str(FCSTD_PATH),
        document_name="AP242GmshBracket",
    )
    print("fcstd", output)


if __name__ == "__main__":
    main()
