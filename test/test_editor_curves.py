"""A 3D curve drawn in the editor: its document, the cell it becomes, and that the cell runs to one wire that follows the
workplanes and model vertices it was drawn on."""

from __future__ import annotations

import pytest

import simplecadapi as scad
from simplecadapi.editor import curve_doc
from simplecadapi.editor import features as F
from simplecadapi.runtime.live_curves import curve_samples
from simplecadapi.runtime.projection import product_reads


def _doc(vertex: dict | None = None) -> dict:
    first = {"id": "p1", "vertex": vertex, "at": [0, 0, 0]} if vertex else {"id": "p1", "at": [0, 0, 0]}
    return {
        "points": [first, {"id": "p2", "on": "wp", "uv": [10, 0]}, {"id": "p3", "at": [20, 5, 30]}, {"id": "p4", "at": [30, 0, 40]}],
        "curves": [
            {"id": "c1", "kind": "line", "points": ["p1", "p2"]},
            {"id": "c2", "kind": "arc", "points": ["p2", "p3", "p4"]},
        ],
    }


def _run(code: str, **names) -> dict:
    scope = {"scad": scad, **names}
    exec(code, scope)
    return scope


def test_a_curve_is_one_wire_through_a_workplane_and_a_model_vertex():
    with scad.GraphSession():
        base = scad.make_box_rsolid(20.0, 20.0, 10.0)
        corner = scad.ql.vertices().where(scad.ql.prop("geom.center.z", ">=", 9.9)).resolve(base)[0]
        record = scad.ref.of(corner, base).to_dict()
        wp = scad.make_workplane_offset_rworkplane("XY", offset=(0.0, 0.0, 20.0))
        rendered = F.render_feature("curve", "path", {"curve": _doc(record), "body": "base"}, bodies={"base": "solid"})
        assert rendered.produces == "wire" and set(rendered.reads) == {"wp", "base"}
        body = "\n".join(line for line in rendered.feature.splitlines() if not line.startswith("#"))
        assert "wp.point(10.0, 0.0)" in body and "scad.ref.vertex(" in body
        path = _run(body, base=base, wp=wp)["path"]
        start, end = path.get_edges(0).get_start_vertex().get_coordinates(), path.get_edges(1).get_end_vertex().get_coordinates()
        assert start == pytest.approx(tuple(corner.get_coordinates()))
        assert end == pytest.approx((30.0, 0.0, 40.0))
        # the workplane moves: the point drawn on it moves with it
        higher = scad.make_workplane_offset_rworkplane("XY", offset=(0.0, 0.0, 25.0))
        moved = _run(body, base=base, wp=higher)["path"]
        assert moved.get_edges(0).get_end_vertex().get_coordinates() == pytest.approx((10.0, 0.0, 25.0))
        samples = curve_samples({"path": path, "_hidden": path})
        assert [s["name"] for s in samples] == ["path"] and [len(e) for e in samples[0]["edges"]] == [2, 48]


def test_a_curve_document_is_checked():
    with pytest.raises(curve_doc.CurveError, match="must start where"):
        curve_doc.validate({"points": [{"id": "a", "at": [0, 0, 0]}, {"id": "b", "at": [1, 0, 0]}, {"id": "c", "at": [2, 0, 0]}],
                            "curves": [{"id": "c1", "kind": "line", "points": ["a", "b"]}, {"id": "c2", "kind": "line", "points": ["a", "c"]}]})
    with pytest.raises(curve_doc.CurveError, match="an arc takes 3"):
        curve_doc.validate({"points": [{"id": "a", "at": [0, 0, 0]}, {"id": "b", "at": [1, 0, 0]}], "curves": [{"id": "c1", "kind": "arc", "points": ["a", "b"]}]})
    with pytest.raises(F.FeatureError, match="no body yet"):
        F.render_feature("curve", "path", {"curve": _doc({"kind": "vertex", "feature": "", "op": "make_box_rsolid", "topo": "vertex_0"})}, bodies={})


def test_a_cell_that_only_draws_a_curve_through_the_body_leaves_it_the_product():
    class Cell:
        def __init__(self, defs, refs):
            self.defs, self.refs = defs, refs

    with scad.GraphSession():
        base = scad.make_box_rsolid(10.0, 10.0, 10.0)
        path = scad.make_wire_from_edges_rwire([scad.make_segment_redge((0, 0, 0), (0, 0, 20))])
    values = {"base": base, "path": path}
    assert "base" not in product_reads([Cell({"base"}, set()), Cell({"path"}, {"base"})], values)
