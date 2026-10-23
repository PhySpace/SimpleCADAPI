"""The sketch API through the Python module: ports of test_sketch_api.py,
test_sketch_histcad_constraints.py (serialization), test_sketch_ellipse.py and
test_error_diagnostics_sketch.py from the reference SDK."""

import json
import math

import pytest

import simplecadapi._cpp as scad


def _rectangle():
    sketch = scad.make_sketch_rsketch("rect")
    for pid, (x, y) in {"p0": (0.0, 0.0), "p1": (2.0, 0.0), "p2": (2.0, 1.0), "p3": (0.0, 1.0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    for entity, (a, b) in {"bottom": ("p0", "p1"), "right": ("p1", "p2"), "top": ("p2", "p3"), "left": ("p3", "p0")}.items():
        sketch = scad.add_line_rsketch(sketch, entity, a, b)
    sketch = scad.constrain_horizontal_rsketch(sketch, "bottom")
    sketch = scad.constrain_vertical_rsketch(sketch, "right")
    sketch = scad.constrain_parallel_rsketch(sketch, "bottom", "top")
    sketch = scad.constrain_parallel_rsketch(sketch, "left", "right")
    sketch = scad.constrain_perpendicular_rsketch(sketch, "bottom", "right")
    sketch = scad.constrain_equal_length_rsketch(sketch, "bottom", "top")
    sketch = scad.constrain_equal_length_rsketch(sketch, "left", "right")
    sketch = scad.constrain_distance_rsketch(sketch, "p0", "p1", 2.0)
    sketch = scad.constrain_distance_rsketch(sketch, "p0", "p3", 1.0)
    return scad.constrain_fix_rsketch(sketch, "p0")


def test_updates_are_functional():
    original = scad.make_sketch_rsketch("functional")
    with_point = scad.add_point_rsketch(original, "p0", 0.0, 0.0)
    assert "p0" not in original.entities and "p0" in with_point.entities
    assert original is not with_point


def test_rectangle_solves_and_promotes_with_identity_tags():
    sketch = _rectangle()
    result = scad.inspect_sketch_rsketchresult(sketch, require_fully_constrained=True)
    assert (result.status, result.dof) == ("solved", 0)
    assert result.residual_norm == pytest.approx(0.0, abs=1e-7)
    assert result.backend == scad.get_default_sketch_solver_backend().name == "scad-native"
    assert result.backend_status_code == 5  # redundant but consistent, like libslvs

    face = scad.make_face_from_sketch_rface(sketch, require_fully_constrained=True)
    assert face.get_area() == pytest.approx(2.0)
    assert face.get_metadata("sketch_solve")["status"] == "solved"
    assert face.get_metadata("source_sketch")["name"] == "rect"
    assert "sketch.rect" in face._list_tags(scope="local")
    edge_tags = {t for e in face.edges() for t in e._list_tags(scope="local")}
    for entity in ("bottom", "right", "top", "left"):
        assert f"sketch_entity.{entity}" in edge_tags
        assert f"sketch.rect.entity.{entity}" in edge_tags
    evidence = next(e for e in face.edges() if e._has_tag("sketch.rect.entity.bottom", scope="local"))
    binding = evidence._explain_tag("sketch.rect.entity.bottom", scope="local")[0]["binding"]["evidence"]
    assert binding["evidence_method"] == "SketchPromotionMap"
    assert binding["sketch_promotion"]["entity_id"] == "bottom"
    assert binding["topology_name"]["kind"] == "edge"


def test_wire_promotion_has_identity_tags():
    wire = scad.make_wire_from_sketch_rwire(_rectangle(), require_fully_constrained=True)
    assert wire.is_closed() and len(wire.edges()) == 4
    assert "sketch.rect.profile.bottom" in wire._list_tags(scope="local")


def test_underconstrained_and_conflicting_diagnostics():
    sketch = scad.make_sketch_rsketch("open")
    sketch = scad.add_point_rsketch(sketch, "p0", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "p1", 1.0, 0.0)
    sketch = scad.add_line_rsketch(sketch, "line", "p0", "p1")
    result = scad.inspect_sketch_rsketchresult(sketch, strict=False)
    assert result.status == "underconstrained" and result.dof == 4

    bad = scad.make_sketch_rsketch("bad")
    bad = scad.add_point_rsketch(bad, "a", 0.0, 0.0)
    bad = scad.add_point_rsketch(bad, "b", 1.0, 0.0)
    bad = scad.add_line_rsketch(bad, "line", "a", "b")
    bad = scad.constrain_distance_rsketch(bad, "a", "b", 1.0)
    bad = scad.constrain_distance_rsketch(bad, "a", "b", 2.0)
    bad = scad.constrain_fix_rsketch(bad, "a")
    bad_result = scad.inspect_sketch_rsketchresult(bad, strict=False)
    assert bad_result.status == "conflicting"
    assert any(d.code == "residual_too_large" for d in bad_result.diagnostics)


def _conflict():
    sketch = scad.make_sketch_rsketch("conflict fixture")
    sketch = scad.add_point_rsketch(sketch, "p1", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "p2", 10.0, 0.0)
    sketch = scad.add_line_rsketch(sketch, "l1", "p1", "p2")
    sketch = scad.constrain_distance_rsketch(sketch, "p1", "p2", 20.0, constraint_id="c_far")
    return scad.constrain_distance_rsketch(sketch, "p1", "p2", 5.0, constraint_id="c_near")


def test_conflicting_constraints_raise_structured_diagnosis():
    with pytest.raises(scad.SimpleCADError) as info:
        scad.inspect_sketch_rsketchresult(_conflict())
    error = info.value
    assert error.operation == "sketch_solve"
    text = str(error)
    assert "c_near" in text and "c_far" in text and "distance(p1, p2 = 5)" in text
    assert "[failed]" in text and "[near miss]" in text
    assert "Delete or relax c_near" in text
    assert isinstance(error, ValueError)
    with pytest.raises(ValueError):
        _conflict().solve()


def test_wire_promotion_surfaces_the_solve_diagnosis():
    with pytest.raises(scad.SimpleCADError) as info:
        scad.make_wire_from_sketch_rwire(_conflict())
    assert info.value.operation == "sketch_solve"


def test_underconstrained_error_lists_free_entities():
    sketch = scad.make_sketch_rsketch("loose fixture")
    sketch = scad.add_point_rsketch(sketch, "a", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "b", 8.0, 0.0)
    sketch = scad.add_line_rsketch(sketch, "seg", "a", "b")
    with pytest.raises(scad.SimpleCADError) as info:
        scad.inspect_sketch_rsketchresult(sketch, require_fully_constrained=True)
    text = str(info.value)
    assert "remaining DOF: 4" in text
    for symbol in ("a", "b", "seg"):
        assert f"- {symbol} [unconstrained]" in text
    assert "constrain_fix_rsketch" in text


def test_refs_are_scoped_to_their_sketch():
    first = scad.add_point_rsketch(scad.make_sketch_rsketch("first"), "p0", 0.0, 0.0)
    second = scad.add_point_rsketch(scad.make_sketch_rsketch("second"), "p1", 1.0, 0.0)
    with pytest.raises(Exception):
        scad.add_line_rsketch(first, "bad", scad.get_sketch_point_rsketchref(first, "p0"),
                              scad.get_sketch_point_rsketchref(second, "p1"))


def test_circle_hole_and_plane_handling():
    sketch = scad.make_sketch_rsketch("plate")
    for name, (x, y), r in (("outer", (0.0, 0.0), 5.0), ("left_hole", (-2.0, 0.0), 1.0), ("right_hole", (2.0, 0.0), 1.0)):
        sketch = scad.add_point_rsketch(sketch, f"{name}_c", x, y)
        sketch = scad.add_circle_rsketch(sketch, name, f"{name}_c", r)
    face = scad.make_face_from_sketch_rface(sketch, profile="outer", inner_profiles=("left_hole", "right_hole"))
    assert len(face.wires()) == 3
    assert face.get_area() == pytest.approx(23.0 * math.pi, rel=1e-6)
    assert [loop["role"] for loop in face.get_metadata("sketch_promotion")["loops"]] == ["outer", "inner", "inner"]

    with pytest.raises(Exception):
        scad.make_sketch_rsketch(plane={"origin": (0, 0, 0), "x_axis": (1, 0, 0), "y_axis": (2, 0, 0)})

    with scad.SimpleWorkplane(origin=(3.0, 4.0, 5.0), normal=(0.0, 1.0, 0.0), x_dir=(1.0, 0.0, 0.0)):
        ring = scad.add_point_rsketch(scad.make_sketch_rsketch("ring"), "c", 0.0, 0.0)
        ring = scad.add_circle_rsketch(ring, "outer", "c", 2.0)
        ring = scad.add_point_rsketch(ring, "ic", 0.0, 0.0)
        ring = scad.add_circle_rsketch(ring, "inner", "ic", 1.0)
        ring_face = scad.make_face_from_sketch_rface(ring, profile="outer", inner_profiles=("inner",))
    normal, center = ring_face.get_normal_at(), ring_face.get_center()
    assert (normal.x, normal.y, normal.z) == pytest.approx((0.0, 1.0, 0.0), abs=1e-6)
    assert (center.x, center.y, center.z) == pytest.approx((3.0, 4.0, 5.0), abs=1e-6)


def test_open_chain_and_branch_errors():
    sketch = scad.make_sketch_rsketch("chain")
    for pid, (x, y) in {"p0": (0.0, 0.0), "p1": (10.0, 0.0), "p2": (10.0, 8.0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    sketch = scad.add_line_rsketch(sketch, "run", "p0", "p1")
    sketch = scad.add_line_rsketch(sketch, "rise", "p1", "p2")
    wire = scad.make_wire_from_sketch_rwire(sketch)
    assert not wire.is_closed() and len(wire.edges()) == 2
    with pytest.raises(ValueError, match="open chain"):
        scad.make_face_from_sketch_rface(sketch)

    branchy = scad.make_sketch_rsketch("branchy")
    for pid, (x, y) in {"c": (0.0, 0.0), "a": (5.0, 0.0), "b": (0.0, 5.0), "d": (-5.0, 0.0)}.items():
        branchy = scad.add_point_rsketch(branchy, pid, x, y)
    for entity, end in (("e1", "a"), ("e2", "b"), ("e3", "d")):
        branchy = scad.add_line_rsketch(branchy, entity, "c", end)
    with pytest.raises(ValueError) as info:
        scad.make_wire_from_sketch_rwire(branchy)
    assert "branch" in str(info.value) and "'c'" in str(info.value)


def test_arc_bspline_profile_on_an_arbitrary_plane():
    plane = {"origin": (10.0, 20.0, 30.0), "x_axis": (0.0, 1.0, 0.0), "y_axis": (0.0, 0.0, 1.0)}
    sketch = scad.make_sketch_rsketch("mixed_yz", plane=plane)
    for pid, (x, y) in {"left": (-2.0, 0.0), "right": (2.0, 0.0), "center": (0.0, 0.0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    sketch = scad.add_arc_rsketch(sketch, "upper", "right", "left", "center")
    sketch = scad.add_bspline_rsketch(sketch, "lower", "left", "right",
                                      control_points=["left", (-1.0, -1.5), (1.0, -1.5), "right"],
                                      knots=(0.0, 1.0), multiplicities=(4, 4))
    normal = scad.make_face_from_sketch_rface(sketch).get_normal_at()
    assert (normal.x, normal.y, normal.z) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert sketch.entities["lower"].data["control_points"][0] == {"point_id": "left"}


def test_serialization_round_trip_and_constraint_kinds():
    sketch = scad.make_sketch_rsketch("serial")
    for pid, (x, y) in {"p0": (0.0, 0.0), "p1": (4.0, 0.0), "p2": (1.0, 2.0)}.items():
        sketch = scad.add_point_rsketch(sketch, pid, x, y)
    sketch = scad.add_line_rsketch(sketch, "a", "p0", "p1")
    sketch = scad.add_line_rsketch(sketch, "b", "p1", "p2")
    sketch = scad.constrain_points_horizontal_rsketch(sketch, "p0", "p1")
    sketch = scad.constrain_line_distance_rsketch(sketch, "b", "a", 2.0)
    sketch = scad.constrain_angle_rsketch(sketch, "a", "b", 116.565)
    sketch = scad.constrain_mirror_rsketch(sketch, "a", "b", "a")
    sketch = scad.constrain_normal_rsketch(sketch, "a", "b")
    sketch = scad.constrain_midpoint_points_rsketch(sketch, "p0", "p1", "p2")
    restored = scad.Sketch.from_dict(json.loads(json.dumps(sketch.to_dict())))
    assert sorted(f"{c.kind}:{len(c.targets)}" for c in restored.constraints) == [
        "angle:2", "line_distance:2", "midpoint_points:3", "mirror:3", "normal:2", "points_horizontal:2"]
    assert restored.to_dict() == sketch.to_dict()


def test_tangent_modes_are_serializable_and_validated():
    sketch = scad.make_sketch_rsketch("tangent_modes")
    sketch = scad.add_point_rsketch(sketch, "a", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "b", 5.0, 0.0)
    sketch = scad.add_circle_rsketch(sketch, "left", "a", 2.0)
    sketch = scad.add_circle_rsketch(sketch, "right", "b", 1.0)
    sketch = scad.constrain_tangent_rsketch(sketch, "left", "right", mode="internal", constraint_id="internal")
    assert sketch.constraints[-1].metadata["mode"] == "internal"
    assert sketch.to_dict()["constraints"][-1]["metadata"]["mode"] == "internal"
    with pytest.raises(ValueError):
        scad.constrain_tangent_rsketch(sketch, "left", "right", mode="sideways")
    with pytest.raises(ValueError):
        scad.constrain_tangent_rsketch(sketch, "left", "right", at_a="middle")


def test_duck_typed_python_backend_can_be_selected():
    class OffsetBackend:
        name = "test-offset"
        version = "1"

        def solve(self, sketch, *, options):
            self.options = options
            return scad.SketchSolveResult(sketch_id=sketch.sketch_id, status="underconstrained", dof=2, residual_norm=0.0,
                                          iterations=0, solved_points={"p": (3.0, 4.0)}, solved_scalars={},
                                          backend=self.name, backend_version=self.version)

    sketch = scad.add_point_rsketch(scad.make_sketch_rsketch("custom"), "p", 0.0, 0.0)
    backend = OffsetBackend()
    scad.register_sketch_solver_backend(backend)
    result = sketch.solve(backend="test-offset", strict=False)
    assert result.solved_points["p"] == (3.0, 4.0) and result.backend == "test-offset"
    assert backend.options.tolerance == 1e-7
    assert sketch.entities["p"].data == {"x": 0.0, "y": 0.0}
    with scad.sketch_solver_backend("test-offset") as active:
        assert active.name == "test-offset"
    assert scad.get_default_sketch_solver_backend().name == "scad-native"
    with pytest.raises(ValueError, match="Unknown sketch solver backend"):
        scad.get_sketch_solver_backend("py-slvs")


def test_reference_dimensions_and_curve_measurements():
    sketch = scad.make_sketch_rsketch("reference")
    sketch = scad.add_point_rsketch(sketch, "a", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "b", 3.0, 4.0)
    sketch = scad.constrain_fix_rsketch(sketch, "a")
    sketch = scad.constrain_fix_rsketch(sketch, "b")
    sketch = scad.constrain_distance_rsketch(sketch, "a", "b", 99.0, constraint_id="measured", driving=False)
    result = scad.inspect_sketch_rsketchresult(sketch, require_fully_constrained=True)
    assert result.status == "solved"
    assert result.solved_scalars["constraint:measured:value"] == 5.0

    arcs = scad.make_sketch_rsketch("arc_driving_length")
    for pid, xy in {"center": (0.0, 0.0), "start": (1.0, 0.0), "end": (0.0, 1.0)}.items():
        arcs = scad.add_point_rsketch(arcs, pid, *xy)
    arcs = scad.add_arc_rsketch(arcs, "arc", "start", "end", "center")
    arcs = scad.constrain_length_rsketch(arcs, "arc", 2.0)
    with pytest.raises(ValueError, match="Driving length constraints.*only for lines"):
        scad.inspect_sketch_rsketchresult(arcs)


def test_closed_rational_bspline_promotes_to_the_exact_circle():
    poles = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0)]
    weights = [1, math.sqrt(0.5), 1, math.sqrt(0.5), 1, math.sqrt(0.5), 1, math.sqrt(0.5), 1]
    sketch = scad.add_point_rsketch(scad.make_sketch_rsketch(name="closed-rational"), "seam", 1, 0)
    sketch = scad.add_bspline_rsketch(sketch, "boundary", "seam", "seam", poles, degree=2,
                                      knots=[0, 0.25, 0.5, 0.75, 1], multiplicities=[3, 2, 2, 2, 3], weights=weights)
    face = scad.make_face_from_sketch_rface(sketch=sketch)
    assert face.get_area() == pytest.approx(math.pi, rel=1e-3)


def test_ellipse_sketch_tier():
    theta = math.radians(30.0)
    sketch = scad.make_sketch_rsketch("oval")
    sketch = scad.add_point_rsketch(sketch, "c", 0.0, 0.0)
    sketch = scad.add_point_rsketch(sketch, "M", 4 * math.cos(theta), 4 * math.sin(theta))
    sketch = scad.add_point_rsketch(sketch, "m", -2 * math.sin(theta), 2 * math.cos(theta))
    sketch = scad.add_ellipse_rsketch(sketch, "oval", "c", "M", "m")
    result = scad.inspect_sketch_rsketchresult(sketch)
    assert result.solved_entities["oval"]["angle"] == pytest.approx(30.0, abs=1e-6)
    restored = scad.Sketch.from_dict(json.loads(json.dumps(sketch.to_dict())))
    assert restored.point_ref("oval.major").subentity == "major"
    assert scad.make_face_from_sketch_rface(sketch).get_area() == pytest.approx(math.pi * 8.0, rel=1e-6)

    sketch = scad.constrain_fix_rsketch(sketch, "c")
    sketch = scad.constrain_major_radius_rsketch(sketch, "oval", 4.0)
    sketch = scad.constrain_minor_radius_rsketch(sketch, "oval", 2.0)
    assert scad.inspect_sketch_rsketchresult(sketch).status == "underconstrained"  # orientation is free

    bad = scad.make_sketch_rsketch("bad")
    for pid, xy in {"c": (0.0, 0.0), "M": (0.0, 0.0), "m": (0.0, 1.0)}.items():
        bad = scad.add_point_rsketch(bad, pid, *xy)
    with pytest.raises(Exception):
        scad.add_ellipse_rsketch(bad, "oval", "c", "M", "m")
