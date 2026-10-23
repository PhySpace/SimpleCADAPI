from __future__ import annotations

import json
from copy import deepcopy

import pytest
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
)
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi._cpp.occt.gp import gp_Pnt

from simplecadapi.inspect import brep


def _open_face():
    wire = BRepBuilderAPI_MakeWire()
    points = (
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Pnt(2.0, 0.0, 0.0),
        gp_Pnt(2.0, 1.0, 0.0),
        gp_Pnt(0.0, 1.0, 0.0),
    )
    for first, last in zip(points, (*points[1:], points[0])):
        wire.Add(BRepBuilderAPI_MakeEdge(first, last).Edge())
    return BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()


def _compound(*shapes):
    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def test_validate_step_roundtrip_reports_persistence_and_topology(tmp_path):
    output = tmp_path / "box.step"
    result = brep.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape(), output
    )

    assert result["passed"] is True
    assert result["output_path"] == str(output.resolve())
    assert result["file_size"] > 0
    assert result["sha256"].startswith("sha256:")
    assert result["before"]["volume"] == pytest.approx(24.0)
    assert result["after"]["volume"] == pytest.approx(24.0)
    assert result["property_deltas"]["relative_volume"] == pytest.approx(0.0)
    assert result["topology_after"]["closed_manifold"] is True
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    ("drift", "detached"),
    [
        ("centroid", None),
        ("bounding_box", None),
        ("root_bounding_box", "vertex"),
        ("root_bounding_box", "edge"),
    ],
)
def test_roundtrip_does_not_publish_position_drift(
    tmp_path, monkeypatch, drift, detached
):
    from simplecadapi.inspect.brep import persistence

    output = tmp_path / "position.step"
    sentinel = b"do-not-replace"
    output.write_bytes(sentinel)
    original_index = persistence.index_shape_rbrepmodel
    index_calls = 0

    def drifting_index(*args, **kwargs):
        nonlocal index_calls
        index_calls += 1
        model = original_index(*args, **kwargs)
        if index_calls == 1:
            return model
        original_summary = model.summary

        def summary():
            result = original_summary()
            if drift == "centroid":
                result["centroid"][0] += 0.1
            else:
                result[drift]["min"][0] += 0.1
                result[drift]["max"][0] += 0.1
            return result

        model.summary = summary
        return model

    monkeypatch.setattr(persistence, "index_shape_rbrepmodel", drifting_index)

    shape = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    if detached == "vertex":
        shape = _compound(
            shape,
            BRepBuilderAPI_MakeVertex(gp_Pnt(2.0, 0.0, 0.0)).Vertex(),
        )
    elif detached == "edge":
        shape = _compound(
            shape,
            BRepBuilderAPI_MakeEdge(
                gp_Pnt(2.0, 0.0, 0.0), gp_Pnt(3.0, 0.0, 0.0)
            ).Edge(),
        )
    result = persistence.validate_step_roundtrip_rdescriptor(shape, output)

    assert result["passed"] is False
    assert result["output_replaced"] is False
    delta_name = (
        "centroid_distance"
        if drift == "centroid"
        else f"{drift}_max_coordinate_delta"
    )
    assert result["property_deltas"][delta_name] == pytest.approx(0.1)
    assert output.read_bytes() == sentinel


@pytest.mark.parametrize("position_tolerance", [-1.0, float("nan"), float("inf")])
def test_validate_step_roundtrip_rejects_invalid_position_tolerance(
    tmp_path, position_tolerance
):
    with pytest.raises(ValueError, match="position_tolerance must be finite"):
        brep.validate_step_roundtrip_rdescriptor(
            BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(),
            tmp_path / "invalid.step",
            position_tolerance=position_tolerance,
        )


def test_validate_step_roundtrip_preserves_open_face_semantics(tmp_path):
    result = brep.validate_step_roundtrip_rdescriptor(
        _open_face(), tmp_path / "face.step"
    )
    assert result["passed"] is True
    assert result["before"]["root_shape_type"] == "Face"
    assert result["after"]["root_shape_type"] == "Shell"
    assert result["topology_before"]["edge_classification_counts"]["free"] == 4
    assert result["topology_after"]["edge_classification_counts"]["free"] == 4


def test_validate_step_roundtrip_rejects_input_output_alias(tmp_path):
    source = tmp_path / "source.step"
    brep.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), source
    )
    with pytest.raises(ValueError, match="must differ from the input STEP path"):
        brep.validate_step_roundtrip_rdescriptor(source, source)
    model = brep.load_step_rbrepmodel(source)
    with pytest.raises(ValueError, match="protected input STEP path"):
        brep.validate_step_roundtrip_rdescriptor(model, source)


def test_failed_roundtrip_does_not_replace_existing_output(tmp_path, monkeypatch):
    from simplecadapi.inspect.brep import persistence

    output = tmp_path / "existing.step"
    sentinel = b"do-not-replace"
    output.write_bytes(sentinel)
    monkeypatch.setattr(persistence, "_relative_delta", lambda before, after: 1.0)

    result = persistence.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), output
    )
    assert result["passed"] is False
    assert result["output_replaced"] is False
    assert output.read_bytes() == sentinel


@pytest.mark.parametrize("count_name", ["edge_count", "vertex_count"])
def test_roundtrip_does_not_publish_topology_count_drift(
    tmp_path, monkeypatch, count_name
):
    from simplecadapi.inspect.brep import persistence

    output = tmp_path / f"{count_name}.step"
    sentinel = b"do-not-replace"
    output.write_bytes(sentinel)
    original_index = persistence.index_shape_rbrepmodel
    index_calls = 0

    def drifting_index(*args, **kwargs):
        nonlocal index_calls
        index_calls += 1
        model = original_index(*args, **kwargs)
        if index_calls == 1:
            return model
        original_summary = model.summary

        def summary():
            result = original_summary()
            result[count_name] += 1
            return result

        model.summary = summary
        return model

    monkeypatch.setattr(persistence, "index_shape_rbrepmodel", drifting_index)

    result = persistence.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), output
    )

    assert result["passed"] is False
    assert result["output_replaced"] is False
    assert output.read_bytes() == sentinel


@pytest.mark.parametrize(
    ("section", "name", "delta_name"),
    [
        ("edge_classification_counts", "free", "free_edges"),
        ("edge_classification_counts", "non_manifold", "non_manifold_edges"),
        ("edge_evidence_counts", "degenerate", "degenerate_edges"),
        ("edge_evidence_counts", "orphan", "orphan_edges"),
        (
            "edge_classification_counts",
            "orientation_defect",
            "orientation_defect_edges",
        ),
        (None, "orphan_vertex_count", "orphan_vertices"),
    ],
)
def test_roundtrip_rejects_new_edge_topology_evidence(
    tmp_path, monkeypatch, section, name, delta_name
):
    from simplecadapi.inspect.brep import persistence

    output = tmp_path / f"{name}.step"
    original_inspect = persistence.inspect_topology_rdescriptor
    calls = 0

    def regressing_inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        report = deepcopy(original_inspect(*args, **kwargs))
        if calls == 2:
            if section is None:
                report[name] += 1
            else:
                report[section][name] += 1
        return report

    monkeypatch.setattr(
        persistence, "inspect_topology_rdescriptor", regressing_inspect
    )

    result = persistence.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), output
    )

    assert result["passed"] is False
    assert result["topology_deltas"][delta_name] == 1
    assert result["output_replaced"] is False


@pytest.mark.parametrize("regression", ["closure", "orientation", "closed_manifold"])
def test_roundtrip_rejects_shell_topology_regressions(
    tmp_path, monkeypatch, regression
):
    from simplecadapi.inspect.brep import persistence

    output = tmp_path / f"{regression}.step"
    original_inspect = persistence.inspect_topology_rdescriptor
    calls = 0

    def regressing_inspect(*args, **kwargs):
        nonlocal calls
        calls += 1
        report = deepcopy(original_inspect(*args, **kwargs))
        if calls != 2:
            return report
        if regression == "closure":
            report["shells"][0]["closed"] = False
            report["shells"][0]["closure_status"] = "BRepCheck_NotClosed"
        elif regression == "orientation":
            report["shells"][0]["orientation_status"] = "BRepCheck_BadOrientation"
        else:
            report["closed_manifold"] = False
        return report

    monkeypatch.setattr(
        persistence, "inspect_topology_rdescriptor", regressing_inspect
    )

    result = persistence.validate_step_roundtrip_rdescriptor(
        BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), output
    )

    assert result["passed"] is False
    assert result["output_replaced"] is False
