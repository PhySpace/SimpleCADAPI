"""Feature tracing regressions, independent of the SimpleCAD runtime."""
from pathlib import Path
import copy
import json
import sys

import pytest

b = pytest.importorskip("build123d")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/research/build123dftc"))
from b3ftc.geometry import edge as transcribe_edge
from b3ftc.geometry import fingerprint
from b3ftc.tracer import trace_source


def checked(source):
    trace = trace_source(source)
    assert trace["b3d_status"] == "ok", trace["error"]
    assert trace["unsupported"] == []
    known = set()
    for step in trace["steps"]:
        assert set(step["inputs"]) <= known
        known.add(step["id"])
    assert set(trace["result_refs"]) <= known
    json.dumps(trace, allow_nan=False)
    return trace


def test_builder_profile_is_actual_placed_face_with_hole():
    trace = checked("""from build123d import *
with BuildPart() as bp:
    with BuildSketch(Plane.XY.offset(7)):
        Rectangle(10, 8)
        Circle(2, mode=Mode.SUBTRACT)
    extrude(amount=3)
result = bp.part
""")
    feature = next(s for s in trace["steps"] if s["op"] == "extrude")
    assert len(feature["profile"]["wires"]) == 2
    assert feature["profile"]["origin"][2] == pytest.approx(7)
    assert trace["b3d_bbox"][2::3] == pytest.approx([7, 10])
    assert trace["b3d_volume"] == pytest.approx((80 - 4 * 3.141592653589793) * 3)


def test_algebra_has_boolean_dependencies_and_transform_snapshots():
    trace = checked("""from build123d import *
base = Box(10, 10, 10)
base.move(Location((3, 0, 0)))
result = base - Pos(3, 0, 0) * Cylinder(2, 20)
""")
    assert trace["steps"][-1]["op"] == "cut"
    assert len(trace["steps"][-1]["inputs"]) == 2
    transform = [s for s in trace["steps"] if s["op"] == "transform"]
    assert transform[0]["result"]["bbox"][0] == -5
    assert transform[1]["result"]["bbox"][0] == -2
    assert trace["b3d_volume"] == pytest.approx(1000 - 40 * 3.141592653589793)


def test_nested_builder_publication_is_captured_once():
    trace = checked("""from build123d import *
with BuildPart(Plane.XY.offset(10)) as bp:
    with Locations((4, 0, 0)):
        Box(2, 2, 2)
result = bp.part
""")
    assert len([s for s in trace["steps"] if s["op"] == "box"]) == 1
    assert trace["b3d_bbox"] == pytest.approx([3, -1, 9, 5, 1, 11])


def test_deepcopy_mirror_preserves_feature_reference():
    trace = checked("""from build123d import *
import copy
original = Solid.make_box(2, 3, 4)
result = copy.deepcopy(original).mirror(Plane.YZ)
""")
    assert [s["op"] for s in trace["steps"]] == ["box", "transform"]
    assert trace["b3d_bbox"] == pytest.approx([-2, 0, 0, 0, 3, 4])


def test_multiple_solid_components_and_union_groups():
    trace = checked("""from build123d import *
a = Solid.make_box(1, 1, 1)
b = Solid.make_box(1, 1, 1).moved(Location((3, 0, 0)))
group = a.fuse(b).moved(Location((0, 0, 2)))
result = group.solids()[0].moved(Location((0, 2, 0)))
""")
    union = next(s for s in trace["steps"] if s["op"] == "union")
    assert union["result"]["solid_count"] == 2
    assert len(union["result_groups"]) == 2
    assert all(group for group in union["result_groups"])
    assert any(s["op"] == "component" for s in trace["steps"])
    assert trace["b3d_volume"] == pytest.approx(1)


def test_selection_fingerprints_for_fillet_and_shell():
    trace = checked("""from build123d import *
with BuildPart() as bp:
    Box(10, 10, 10)
    fillet(bp.edges().filter_by(Axis.Z), 1)
    offset(amount=-.5, openings=bp.faces().sort_by(Axis.Z)[-1])
result=bp.part
""")
    fillet = next(s for s in trace["steps"] if s["op"] == "fillet")
    shell = next(s for s in trace["steps"] if s["op"] == "offset")
    assert len(fillet["selection"]) == 4
    assert shell["selection"][0]["kind"] == "face"
    assert "normal" in shell["selection"][0]


def test_trimmed_spline_retains_exact_control_points():
    original = b.Edge.make_spline([(0, 0), (1, 2), (3, 1), (4, 0)])
    trimmed = original.trim(.2, .8)
    encoded = transcribe_edge(trimmed)
    assert encoded["kind"] == "bspline"
    assert encoded["start"] == pytest.approx(tuple(trimmed.position_at(0)))
    assert encoded["end"] == pytest.approx(tuple(trimmed.position_at(1)))
    assert encoded["poles"][0] == pytest.approx(encoded["end"] if encoded["reversed"] else encoded["start"])


def test_absolute_location_assignment_and_exact_conic_trim():
    trace = checked("""from build123d import *
result = Solid.make_box(2,3,4).moved(Location((2,0,0)))
result.location = Location((5,0,0))
""")
    assert trace["b3d_bbox"][0] == pytest.approx(5)
    assert trace["steps"][-1]["parameters"]["matrix"][0][3] == pytest.approx(3)
    conic = b.Edge.make_ellipse(3, 2, start_angle=10, end_angle=150)
    data = transcribe_edge(conic)
    assert data["kind"] == "bspline"
    assert data["degree"] == 2
    assert any(weight != 1 for weight in data["weights"])


def test_curved_selection_center_is_mass_center_and_no_arbitrary_surface_normal():
    arc = b.Edge.make_three_point_arc((1, 0), (0, 1), (-1, 0))
    data = fingerprint(arc)
    assert data["center"] == pytest.approx(tuple(arc.center(b.CenterOf.MASS)))
    assert data["center"] != pytest.approx(tuple(arc.center()))
    sphere = b.Solid.make_sphere(2)
    curved = fingerprint(sphere.faces()[0])
    assert "normal" not in curved


def test_scaling_resolves_actual_default_location_center():
    trace = checked("""from build123d import *
placed = Solid.make_box(2,3,4).moved(Location((10,0,0)))
result = placed.scale(2)
""")
    assert trace["steps"][-1]["parameters"]["about"] == pytest.approx([10, 0, 0])
    assert trace["b3d_bbox"] == pytest.approx([10, 0, 0, 14, 6, 8])


def test_factory_parameters_partial_angles_and_generator_inputs_are_preserved():
    trace = checked("""from build123d import *
a = Solid.make_cylinder(2,3,angle=120)
b = Solid.make_cone(3,1,4,angle=180).moved(Location((10,0,0)))
c = Solid.make_torus(5,1,start_angle=-30,end_angle=80,major_angle=140).moved(Location((20,0,0)))
result = a.fuse(b,c)
""")
    assert next(s for s in trace["steps"] if s["op"] == "cylinder")["parameters"]["angle"] == 120
    torus = next(s for s in trace["steps"] if s["op"] == "torus")
    assert torus["parameters"]["major_angle"] == 140
    trace = checked("""from build123d import *
wires = (Wire.make_circle(r, plane=Plane.XY.offset(z)) for r,z in [(2,0),(3,5)])
result = Solid.make_loft(wires)
""")
    assert len(trace["steps"][-1]["profiles"]) == 2


def test_draft_is_transcribed_and_nonplanar_thicken_reports_surface_boundary():
    trace = checked("""from build123d import *
body = Solid.make_box(5,5,5)
side = body.faces().filter_by(Plane.YZ)[-1]
result = body.draft([side], Plane.XY, 5)
""")
    draft = trace["steps"][-1]
    assert draft["op"] == "draft"
    assert len(draft["selection"]) == 1
    assert draft["parameters"]["neutral_plane"]["normal"] == [0, 0, 1]
    trace = trace_source("""from build123d import *
face = Solid.make_sphere(2).faces()[0]
result = Solid.thicken(face, .2)
""")
    assert trace["unsupported"]
    assert any(s["op"] == "thicken" and "geometry_error" in s for s in trace["steps"])


def test_unknown_kernel_solid_is_reported_and_errors_restore_patches():
    original = b.Solid.make_box.__func__
    owned_attributes = set(b.Solid.__dict__)
    trace = trace_source("""from build123d import Solid
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
result = Solid(BRepPrimAPI_MakeBox(2, 3, 4).Solid())
""")
    assert trace["unsupported"]
    assert trace["steps"][-1]["op"] == "unsupported"
    assert b.Solid.make_box.__func__ is original
    trace = trace_source("from build123d import *\nresult=Box(1,2,3)\nraise RuntimeError('expected')")
    assert trace["b3d_status"] == "error"
    assert "expected" in trace["error"]
    assert b.Solid.make_box.__func__ is original
    assert set(b.Solid.__dict__) == owned_attributes


def test_rational_circle_volume_uses_span_aware_adaptive_integration():
    trace = checked("""from build123d import *
from math import sqrt
points = [(1,0),(1,1),(0,1),(-1,1),(-1,0),(-1,-1),(0,-1),(1,-1),(1,0)]
weights = [1,sqrt(.5),1,sqrt(.5),1,sqrt(.5),1,sqrt(.5),1]
curve = Edge.make_bspline(points,[0,0,0,1,1,2,2,3,3,4,4,4],2,weights)
result = Solid.extrude(Face(Wire([curve])), (0,0,1))
""")
    assert trace["b3d_volume"] == pytest.approx(3.141592653589793, rel=1e-9)
    assert trace["b3d_area"] == pytest.approx(4 * 3.141592653589793, rel=1e-9)
    assert "b3d_default_volume" in trace
    assert trace["steps"][-1]["profile"]["wires"][0]["edges"][0]["kind"] == "bspline"


def test_multiple_intersection_results_reference_individual_components():
    trace = checked("""from build123d import *
base = Solid.make_box(10,2,2)
left = Solid.make_box(2,4,4)
right = Solid.make_box(2,4,4).moved(Location((8,0,0)))
intersection = base.intersect(left.fuse(right))
result = intersection[0].moved(Location((0,10,0)))
""")
    assert any(s["op"] == "component" for s in trace["steps"])
    assert trace["solid_count"] == 1
    assert trace["b3d_volume"] == pytest.approx(8)
