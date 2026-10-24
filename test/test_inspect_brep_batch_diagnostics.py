from __future__ import annotations

import math
import pytest
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeWire,
)
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi._cpp.occt.gp import gp_Pnt

from simplecadapi.inspect import brep


def _compound(*shapes):
    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def _face(x_min, x_max):
    points = (
        gp_Pnt(x_min, 0.0, 0.0),
        gp_Pnt(x_max, 0.0, 0.0),
        gp_Pnt(x_max, 1.0, 0.0),
        gp_Pnt(x_min, 1.0, 0.0),
    )
    wire = BRepBuilderAPI_MakeWire()
    for first, last in zip(points, (*points[1:], points[0])):
        wire.Add(BRepBuilderAPI_MakeEdge(first, last).Edge())
    return BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()


def test_compare_sections_batch_preserves_order_and_reports_worst_section():
    target = BRepPrimAPI_MakeBox(4.0, 3.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(4.0, 2.5, 2.0).Shape()
    sections = [
        {"section_id": "middle", "origin": [0.0, 0.0, 1.0], "normal": [0, 0, 1]},
        {"section_id": "outside", "origin": [0.0, 0.0, 3.0], "normal": [0, 0, 1]},
    ]

    report = brep.compare_sections_batch_rdescriptor(
        target, current, sections=sections
    )

    assert [item["section_id"] for item in report["sections"]] == [
        "middle",
        "outside",
    ]
    assert report["sections"][0]["comparison"]["area_delta"] == pytest.approx(-2.0)
    assert report["sections"][1]["comparison"]["empty_section_mismatch"] is False
    assert report["aggregate"]["worst_hausdorff_section_id"] == "middle"
    assert report["aggregate"]["max_absolute_area_delta"] == pytest.approx(2.0)


def test_compare_sections_batch_rejects_duplicate_ids_and_zero_normal():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    duplicate = [
        {"section_id": "same", "origin": [0, 0, 0.5], "normal": [0, 0, 1]},
        {"section_id": "same", "origin": [0, 0, 0.6], "normal": [0, 0, 1]},
    ]
    with pytest.raises(ValueError, match="section_id values must be unique"):
        brep.compare_sections_batch_rdescriptor(box, box, sections=duplicate)
    with pytest.raises(ValueError, match="normal must be non-zero"):
        brep.compare_sections_batch_rdescriptor(
            box,
            box,
            sections=[{"section_id": "bad", "origin": [0, 0, 0], "normal": [0, 0, 0]}],
        )


def test_compare_sections_batch_prioritizes_empty_mismatch_as_worst():
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 1.0).Shape()
    current = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()

    report = brep.compare_sections_batch_rdescriptor(
        target,
        current,
        sections=[
            {"section_id": "both", "origin": [0, 0, 0.5], "normal": [0, 0, 1]},
            {"section_id": "mismatch", "origin": [0, 0, 1.5], "normal": [0, 0, 1]},
        ],
    )

    assert report["aggregate"]["worst_hausdorff_section_id"] == "mismatch"
    assert report["aggregate"]["max_hausdorff"] is None


def test_compare_sections_batch_rejects_non_finite_tolerance():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    with pytest.raises(ValueError, match="tolerance must be finite"):
        brep.compare_sections_batch_rdescriptor(
            box,
            box,
            sections=[
                {"section_id": "one", "origin": [0, 0, 0.5], "normal": [0, 0, 1]}
            ],
            tolerance=math.nan,
        )


def test_compare_sections_batch_rejects_unbounded_section_id():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    with pytest.raises(ValueError, match="at most 128 characters"):
        brep.compare_sections_batch_rdescriptor(
            box,
            box,
            sections=[
                {
                    "section_id": "x" * 129,
                    "origin": [0, 0, 0.5],
                    "normal": [0, 0, 1],
                }
            ],
        )


def test_compare_sections_batch_does_not_claim_equal_when_sections_fail():
    target = BRepPrimAPI_MakeBox(1.0e-6, 1.0e-6, 1.0e-6).Shape()
    current = BRepPrimAPI_MakeBox(2.0e-6, 1.0e-6, 1.0e-6).Shape()

    report = brep.compare_sections_batch_rdescriptor(
        target,
        current,
        sections=[
            {
                "section_id": "tiny",
                "origin": [0.0, 0.0, 0.5e-6],
                "normal": [0.0, 0.0, 1.0],
            }
        ],
    )

    comparison = report["sections"][0]["comparison"]
    assert comparison["section_generation_unresolved"] is True
    assert comparison["hausdorff_approximation"] is None
    assert report["aggregate"]["max_hausdorff"] is None


def test_compare_sections_batch_accepts_identical_empty_multi_body_gap():
    model = _compound(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(3.0, 0.0, 0.0), 1.0, 1.0, 1.0).Shape(),
    )

    report = brep.compare_sections_batch_rdescriptor(
        model,
        model,
        sections=[
            {
                "section_id": "gap",
                "origin": [2.0, 0.0, 0.0],
                "normal": [1.0, 0.0, 0.0],
            }
        ],
    )

    comparison = report["sections"][0]["comparison"]
    assert comparison["section_generation_unresolved"] is False
    assert comparison["empty_section_mismatch"] is False
    assert comparison["hausdorff_approximation"] == pytest.approx(0.0)


def test_compare_sections_batch_accepts_identical_empty_bodyless_gap():
    model = _compound(_face(0.0, 1.0), _face(3.0, 4.0))

    report = brep.compare_sections_batch_rdescriptor(
        model,
        model,
        sections=[
            {
                "section_id": "gap",
                "origin": [2.0, 0.0, 0.0],
                "normal": [1.0, 0.0, 0.0],
            }
        ],
    )

    comparison = report["sections"][0]["comparison"]
    assert comparison["section_generation_unresolved"] is False
    assert comparison["empty_section_mismatch"] is False
    assert comparison["hausdorff_approximation"] == pytest.approx(0.0)


def test_compare_sections_batch_accepts_plane_through_sphere_bounds_but_not_sphere():
    sphere = BRepPrimAPI_MakeSphere(1.0).Shape()
    offset = 1.2 / math.sqrt(3.0)

    report = brep.compare_sections_batch_rdescriptor(
        sphere,
        sphere,
        sections=[
            {
                "section_id": "oblique-empty",
                "origin": [offset, offset, offset],
                "normal": [1.0, 1.0, 1.0],
            }
        ],
    )

    comparison = report["sections"][0]["comparison"]
    assert report["sections"][0]["target"]["edge_count"] == 0
    assert comparison["section_generation_unresolved"] is False
    assert comparison["empty_section_mismatch"] is False
    assert comparison["hausdorff_approximation"] == pytest.approx(0.0)


def test_compare_sections_batch_does_not_claim_equal_at_oblique_tangency():
    target = BRepPrimAPI_MakeSphere(1.0).Shape()
    current = BRepPrimAPI_MakeSphere(0.5).Shape()
    offset = 1.0 / math.sqrt(3.0)

    report = brep.compare_sections_batch_rdescriptor(
        target,
        current,
        sections=[
            {
                "section_id": "oblique-tangent",
                "origin": [offset, offset, offset],
                "normal": [1.0, 1.0, 1.0],
            }
        ],
    )

    comparison = report["sections"][0]["comparison"]
    assert comparison["section_generation_unresolved"] is True
    assert comparison["hausdorff_approximation"] is None
