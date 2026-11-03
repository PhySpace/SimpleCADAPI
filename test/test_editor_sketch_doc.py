"""The sketch document: validation, the code it becomes, and the solve a canvas asks for."""

from __future__ import annotations

import inspect

import pytest

import simplecadapi as scad
from simplecadapi.editor import sketch_doc as S
from test_editor_features import HOLE_SKETCH, RECT_SKETCH


def test_every_constraint_matches_the_sdk_function_it_renders_to():
    """The drift test for the sketch layer: the target names and the extras are the real keyword parameters."""
    for kind, (targets, unit, extras) in S.CONSTRAINTS.items():
        names = set(inspect.signature(getattr(scad, f"constrain_{kind}_rsketch")).parameters)
        assert set(targets) <= names, kind
        assert set(extras) <= names, kind
        assert ("value" in names) == (unit is not None), kind


def test_the_solve_reports_solved_geometry_without_recording_anything():
    result = S.solve(RECT_SKETCH)
    assert result["status"] == "solved" and result["dof"] == 0
    assert result["points"]["b"] == pytest.approx([40.0, 0.0], abs=1e-6) and result["points"]["c"] == pytest.approx([40.0, 20.0], abs=1e-6)
    assert result["profiles"][0]["area"] == pytest.approx(800.0)


def test_an_underconstrained_or_conflicting_sketch_is_an_answer_not_an_error():
    loose = {**RECT_SKETCH, "constraints": RECT_SKETCH["constraints"][:3]}
    under = S.solve(loose)
    assert under["status"] == "underconstrained" and under["dof"] > 0
    conflict = {**RECT_SKETCH, "constraints": [*RECT_SKETCH["constraints"], {"kind": "length", "targets": ["l0"], "value": 55.0}]}
    answer = S.solve(conflict)
    assert answer["status"] in ("conflicting", "failed") or any(d["severity"] != "info" for d in answer["diagnostics"])


def test_a_hundred_solves_are_fast_enough_for_a_drag():
    import time

    start = time.perf_counter()
    for _ in range(100):
        S.solve(HOLE_SKETCH)
    assert (time.perf_counter() - start) / 100 < 0.05  # well under a frame at 20 fps, with the profiles included


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["points"].append({"id": "a", "x": 1, "y": 1}), "used twice"),
        (lambda d: d["points"].append({"id": "Bad Id", "x": 1, "y": 1}), "lowercase"),
        (lambda d: d["entities"].append({"id": "x", "kind": "line", "start": "a", "end": "nope"}), "not a point"),
        (lambda d: d["entities"].append({"id": "x", "kind": "spline"}), "unknown entity"),
        (lambda d: d["constraints"].append({"kind": "length", "targets": ["l0"], "value": "ten"}), "a number is required"),
        (lambda d: d["constraints"].append({"kind": "length", "targets": ["l0"], "value": -1}), "greater than zero"),
        (lambda d: d["constraints"].append({"kind": "parallel", "targets": ["l0"]}), "needs 2 target"),
        (lambda d: d["constraints"].append({"kind": "horizontal", "targets": ["l0; import os"]}), "not a point or entity"),
        (lambda d: d["constraints"].append({"kind": "explode", "targets": []}), "unknown constraint"),
    ],
)
def test_a_bad_document_is_refused_before_it_can_reach_code(mutate, message):
    import copy

    doc = copy.deepcopy(RECT_SKETCH)
    mutate(doc)
    with pytest.raises(S.SketchError, match=message):
        S.validate(doc)


def test_a_sketch_on_a_face_frame_extrudes_along_its_normal():
    import copy

    from simplecadapi.editor import features as F

    frame = {"origin": [10.0, 0.0, 0.0], "x_axis": [0.0, 1.0, 0.0], "y_axis": [0.0, 0.0, 1.0]}
    doc = copy.deepcopy(RECT_SKETCH)
    doc["plane"] = frame
    assert S.plane_normal(S.validate(doc)["plane"]) == [1.0, 0.0, 0.0]
    solved = S.solve(doc)
    assert solved["status"] == "solved" and solved["profiles"][0]["centroid"][0] == pytest.approx(10.0)
    with scad.GraphSession(graph_id="face-sketch"):
        scope: dict = {"scad": scad}
        sketch = F.render_feature("sketch", "outline", {"sketch": doc}, bodies={})
        exec("\n".join(sketch.params), scope)
        exec(sketch.feature, scope)
        extrude = F.render_feature("extrude_sketch", "tab", {"profile": "outline", "direction": "normal", "distance": 4.0}, bodies={"outline": "face"}, env={"profile_normals": {"outline": S.plane_normal(S.validate(doc)["plane"])}})
        exec("\n".join(extrude.params), scope)
        exec(extrude.feature, scope)
        center = scope["tab"].get_center()
        assert center.x == pytest.approx(12.0) and scope["tab"].get_volume() == pytest.approx(40 * 20 * 4)
    for bad in ({"origin": [0, 0, 0], "x_axis": [1, 0, 0], "y_axis": [1, 0, 0]}, {"origin": [0, 0], "x_axis": [1, 0, 0], "y_axis": [0, 1, 0]}, {"origin": [0, 0, 0], "x_axis": [2, 0, 0], "y_axis": [0, 1, 0]}):
        with pytest.raises(S.SketchError):
            S.validate({**RECT_SKETCH, "plane": bad})
