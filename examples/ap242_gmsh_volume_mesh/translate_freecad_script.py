"""Translate the captured bracket into a standalone FreeCAD Python script."""

from __future__ import annotations

import simplecadapi as scad

from bracket_package import OUT_DIR, capture_bracket


SCRIPT_PATH = OUT_DIR / "ap242_gmsh_bracket.freecad.py"


def main() -> None:
    package_path = capture_bracket()
    script = (
        scad.translator.freecad_translator.translate_product_package_to_freecad_script(
            data=package_path,
            document_name="AP242GmshBracket",
        )
    )
    SCRIPT_PATH.write_text(script, encoding="utf-8")
    print("freecad_script", SCRIPT_PATH)


if __name__ == "__main__":
    main()
