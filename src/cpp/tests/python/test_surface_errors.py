"""The public error contract of the surface operators: same operation, same guidance text."""

import math

import pytest

import simplecadapi._cpp as scad
from ref import golden
from surface_support import REF_PRELUDE, line, rectangle

SQUARE = [[(0, 0, 0), (0, 1, 0)], [(1, 0, 0), (1, 1, 0)]]

CASES = {
    "bezier_grid": "scad.make_bezier_surface_rface([[(0, 0, 0)]])",
    "bezier_weights": f"scad.make_bezier_surface_rface({SQUARE!r}, [[1, 1]])",
    "cylinder_u_span": "scad.make_cylindrical_surface_rface(2.0, (0.0, 1.0001e-12), (0.0, 2.0))",
    "cylinder_v_span": "scad.make_cylindrical_surface_rface(2.0, (0.0, 1.0), (0.0, 1.0e-8))",
    "cylinder_radius": "scad.make_cylindrical_surface_rface(-1.0, (0.0, 1.0), (0.0, 1.0))",
    "fit_tolerance": f"scad.fit_point_grid_rface({SQUARE!r}, tolerance=0.0)",
    "fit_degrees": f"scad.fit_point_grid_rface({SQUARE!r}, degree_min=5, degree_max=3)",
    "sew_empty": "scad.sew_faces_rshell([])",
    "sew_tolerance": f"scad.sew_faces_rshell([scad.make_bezier_surface_rface({SQUARE!r})], tolerance=-1.0)",
    "solid_open_shell": f"scad.make_solid_from_shell_rsolid(scad.sew_faces_rshell([scad.make_bezier_surface_rface({SQUARE!r})]))",
    "free_boundaries_tolerance": f"scad.free_boundaries_rwirelist(scad.sew_faces_rshell([scad.make_bezier_surface_rface({SQUARE!r})]), tolerance=0.0)",
    "gordon_small": "scad.make_gordon_surface_rface([line((0, 0, 0), (1, 0, 0))], [line((0, 0, 0), (0, 1, 0))])",
    "patch_empty": "scad.make_surface_patch_rface([])",
}


def normalized(text):
    lines = [ln for ln in text.splitlines() if not ln.startswith("Signature:")]
    return "\n".join(lines).replace("simplecadapi._cpp", "simplecadapi")


def native_error(call_source):
    scope = {"scad": scad, "line": line, "rectangle": rectangle, "math": math}
    with pytest.raises(scad.SimpleCADError) as info:
        eval(call_source, scope)
    return normalized(str(info.value)), info.value.operation


def test_error_text_matches_the_reference():
    ref_body = "\nresult = {}\n"
    for name, source in CASES.items():
        ref_body += f"""
try:
    {source}
    result[{name!r}] = None
except Exception as e:
    result[{name!r}] = [str(e), getattr(e, "operation", None)]
"""
    expected = golden("surface_error_text", REF_PRELUDE + ref_body)
    for name, source in CASES.items():
        text, operation = native_error(source)
        ref_text, ref_operation = expected[name]
        assert operation == ref_operation, name
        assert text == normalized(ref_text), f"{name}:\n{text}\n---\n{normalized(ref_text)}"


def test_value_types_validate_like_their_dataclasses():
    edge = line((0, 0, 0), (1, 0, 0))
    assert scad.SurfaceBoundary(edge, "g1").continuity == "G1"
    assert scad.SurfaceBoundary(edge).as_dict() == {"continuity": "C0", "has_support": False}
    with pytest.raises(ValueError, match="C0, G1, or G2"):
        scad.SurfaceBoundary(edge, "C3")
    assert scad.SurfaceFillingSettings().as_dict()["max_segments"] == 9
    with pytest.raises(ValueError, match="positive finite"):
        scad.SurfaceFillingSettings(tolerance_3d=-1.0)
    with pytest.raises(ValueError, match="max_degree must cover degree"):
        scad.SurfaceFillingSettings(degree=5, max_degree=3)


def test_surface_namespace_exports_the_same_objects():
    for name in ("make_bezier_surface_rface", "make_solid_from_shell_rsolid", "SurfaceBoundary", "loft_rshell",
                 "fill_holes_rshell", "trim_surface_rface"):
        assert getattr(scad.surface, name) is getattr(scad, name)


def test_cylindrical_surface_uses_radians_and_model_length_units():
    # tests/test_surface_api.py of the reference.
    carrier = scad.make_cylindrical_surface_rface(
        scad.var("radius", 0.2, unit="cm"),
        (0.0, scad.var("u_max", math.pi, unit="1")),
        (scad.var("v_min", 0.0, unit="cm"), scad.var("v_max", 0.2, unit="cm")),
        tolerance=scad.var("surface_tol", 0.001, unit="mm"),
    )
    assert carrier.get_area() == pytest.approx(4.0 * math.pi, abs=1e-6)
    with pytest.raises(scad.SimpleCADError, match="unitless raw radians"):
        scad.make_cylindrical_surface_rface(2.0, (0.0, scad.var("u_max", math.pi, unit="rad")), (0.0, 2.0))
    with pytest.raises(scad.SimpleCADError, match="tolerance must use model length"):
        scad.make_cylindrical_surface_rface(
            2.0, (0.0, math.pi), (0.0, 2.0), tolerance=scad.var("angular_tol", 0.001, unit="rad")
        )
