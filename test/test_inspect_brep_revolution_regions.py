"""Whole-body and local revolution-style geometric candidates."""

from __future__ import annotations

import math

from OCP.BRep import BRep_Builder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopoDS import TopoDS_Compound
import pytest

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.feature_hints import revolutions


def _meridian_face(*, inner: float, outer: float, start: float, end: float):
    wire = scad.make_polyline_rwire(
        points=[
            (inner, 0.0, start),
            (outer, 0.0, start),
            (outer, 0.0, end),
            (inner, 0.0, end),
        ],
        closed=True,
    )
    return scad.make_face_from_wire_rface(wire=wire, normal=(0.0, 1.0, 0.0))


def _revolve(*, inner: float = 2.0, outer: float = 4.0, angle: float = 360.0):
    return scad.revolve_rsolid(
        _meridian_face(inner=inner, outer=outer, start=-2.0, end=2.0),
        axis=(0.0, 0.0, 1.0),
        angle=angle,
        origin=(0.0, 0.0, 0.0),
    )


def _shaft(*, radius: float = 4.0):
    return scad.make_cylinder_rsolid(
        radius=radius,
        height=12.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )


def _full_boss():
    flange = scad.revolve_rsolid(
        _meridian_face(inner=4.0, outer=6.0, start=4.0, end=7.0),
        axis=(0.0, 0.0, 1.0),
        angle=360.0,
        origin=(0.0, 0.0, 0.0),
    )
    return scad.union_rsolid(_shaft(), flange, clean=False)


def _full_groove():
    cutter = scad.revolve_rsolid(
        _meridian_face(inner=4.0, outer=7.0, start=4.0, end=7.0),
        axis=(0.0, 0.0, 1.0),
        angle=360.0,
        origin=(0.0, 0.0, 0.0),
    )
    return scad.cut_rsolid(_shaft(radius=6.0), cutter, skip_non_intersecting=False)


def _partial_local(*, additive: bool):
    feature = scad.revolve_rsolid(
        _meridian_face(
            inner=4.0,
            outer=6.0 if additive else 7.0,
            start=4.0,
            end=7.0,
        ),
        axis=(0.0, 0.0, 1.0),
        angle=90.0,
        origin=(0.0, 0.0, 0.0),
    )
    if additive:
        return scad.union_rsolid(_shaft(), feature, clean=False)
    return scad.cut_rsolid(_shaft(radius=6.0), feature, skip_non_intersecting=False)


def _hints(shape):
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=shape.wrapped if hasattr(shape, "wrapped") else shape,
        feature_kinds=("revolution",),
        max_hints=100,
    )
    return [
        item
        for item in report["hints"]
        if item["kind"] == "revolution_region_candidate"
    ]


@pytest.mark.parametrize(
    ("shape", "subtype", "angle"),
    [
        (_revolve(), "whole_body_full_revolution", 360.0),
        (_revolve(angle=120.0), "whole_body_partial_revolution", 120.0),
        (_full_boss(), "local_full_revolved_boss", 360.0),
        (_full_groove(), "local_full_revolved_groove", 360.0),
        (_partial_local(additive=True), "local_partial_revolved_boss", 90.0),
        (_partial_local(additive=False), "local_partial_revolved_cut", 90.0),
    ],
)
def test_six_revolution_subtypes_report_axis_angle_profile_and_evidence(
    shape, subtype, angle
):
    hint = next(item for item in _hints(shape) if item["geometry"]["form"] == subtype)
    geometry = hint["geometry"]

    assert geometry["axis"]["direction"] == pytest.approx([0.0, 0.0, 1.0])
    assert geometry["sweep_angle_degrees"] == pytest.approx(angle, abs=1.0e-4)
    assert geometry["maximum_radius"] > geometry["minimum_radius"] >= 0.0
    assert geometry["axial_span"] > 0.0
    assert geometry["profile"]["kind"] == "meridian"
    consistency = geometry["angular_section_consistency"]
    assert consistency["stations"]
    assert consistency["passed"] is True
    assert all(
        measurement["source"] == "actual_brep_section"
        for measurement in consistency["measurements"]
    )
    assert {
        "revolution.axis_cluster",
        "revolution.angular_domain",
        "revolution.meridian_correspondence",
        "revolution.region_boundary_and_material_side",
    } <= {item["code"] for item in hint["evidence"]}


def test_revolution_results_are_repeatable_and_step_roundtrip_preserves_classification(
    tmp_path,
):
    shape = _revolve(angle=120.0)
    first = _hints(shape)
    second = _hints(shape)
    path = tmp_path / "partial-revolution.step"
    writer = STEPControl_Writer()
    assert writer.Transfer(shape.wrapped, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(path)) == IFSelect_RetDone
    loaded = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=path,
        feature_kinds=("revolution",),
    )

    assert first == second
    assert any(
        item["geometry"]["form"] == "whole_body_partial_revolution"
        and item["geometry"]["sweep_angle_degrees"] == pytest.approx(120.0, abs=1.0e-4)
        for item in loaded["hints"]
    )


def test_noncoaxial_bodies_are_not_merged_into_one_revolution_feature():
    first = _shaft()
    second = scad.make_cylinder_rsolid(
        radius=4.0,
        height=12.0,
        bottom_face_center=(20.0, 0.0, 0.0),
    )
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, first.wrapped)
    builder.Add(compound, second.wrapped)
    hints = _hints(compound)

    axes = {
        tuple(round(value, 6) for value in hint["geometry"]["axis"]["point"])
        for hint in hints
        if hint["geometry"]["form"] == "whole_body_full_revolution"
    }
    assert len(axes) == 2


def test_isolated_sphere_has_no_arbitrarily_selected_revolution_axis():
    sphere = scad.make_sphere_rsolid(radius=5.0)
    report = brep.inspect_manufacturing_hints_rdescriptor(
        model_or_path=sphere.wrapped,
        feature_kinds=("revolution",),
    )

    assert not any(
        item["kind"] == "revolution_region_candidate" for item in report["hints"]
    )
    assert any(
        item["code"] == "revolution.axis_not_unique" for item in report["diagnostics"]
    )


def test_twisted_loft_is_not_a_strong_revolution_candidate():
    first = scad.make_rectangle_rwire(width=4.0, height=2.0, center=(4.0, 0.0, -2.0))
    second = scad.make_rectangle_rwire(width=4.0, height=2.0, center=(4.0, 0.0, 2.0))
    loft = scad.loft_rsolid([first, second])

    assert not any(item["confidence"]["level"] == "strong" for item in _hints(loft))


def test_empty_angular_section_rejects_candidate_without_aborting_analysis(monkeypatch):
    monkeypatch.setattr(
        revolutions,
        "inspect_section_rdescriptor",
        lambda **_: {"edges": []},
    )

    assert _hints(_partial_local(additive=False)) == []
