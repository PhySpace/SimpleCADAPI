"""Boolean-family failure diagnosis: measurements, evidence, and repair.

Asserts the error-guidance contract designed in design-docs/error-guidance-review.md:
failure-time measurements, evidence rendering anchored to the part-cache root,
operation-specific parameterized repair, and the text axiom (every measurement
appears in the error text itself).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import simplecadapi as scad
from simplecadapi.errors import ErrorEvidence, ErrorMeasurement, SimpleCADMessageError


def _disjoint_boxes():
    base = scad.make_box_rsolid(10, 4, 4, bottom_face_center=(0, 0, 0))
    tool = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(20, 0, 0))
    return base, tool


@pytest.fixture(autouse=True)
def _no_render(monkeypatch):
    monkeypatch.setenv("SCA_NO_DIAGNOSTIC_RENDER", "1")


def _measurements_dict(error: scad.SimpleCADError) -> dict:
    return {m["name"]: m["value"] for m in error.to_dict()["measurements"]}


def test_disjoint_union_diagnosis_measurements_and_repair():
    base, tool = _disjoint_boxes()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(base, tool)

    error = ctx.value
    payload = error.to_dict()
    measurements = _measurements_dict(error)

    assert error.operation == "union_rsolid"
    assert "separated solids" in payload["what_happened"]
    assert "nearest detected gap" in payload["what_happened"]
    assert measurements["min_gap"] == pytest.approx(14.0)
    assert measurements["closure_vector_a_to_b"] == pytest.approx([14.0, 0.0, 0.0])
    assert measurements["closest_point_a"][0] == pytest.approx(5.0)
    assert measurements["closest_point_b"][0] == pytest.approx(19.0)

    assert any("(14, 0, 0)" in step for step in payload["repair"])
    assert any("make_assembly_rassembly" in step for step in payload["repair"])
    assert any("exactly one solid" in cause for cause in payload["possible_causes"])


def test_disjoint_union_text_axiom():
    base, tool = _disjoint_boxes()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(base, tool)

    text = str(ctx.value)
    assert "- min_gap: 14 mm" in text
    assert "closure_vector_a_to_b: (14, 0, 0) mm" in text
    assert "How to fix:" in text and "(14, 0, 0)" in text


def test_disjoint_union_evidence_render(tmp_path, monkeypatch):
    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    from simplecadapi.operators._diagnostics import _RENDER_DEDUP

    _RENDER_DEDUP.clear()
    base, tool = _disjoint_boxes()

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(base, tool)

    evidence = ctx.value.to_dict()["evidence"]
    assert len(evidence) == 1
    entry = evidence[0]
    assert entry["kind"] == "render"
    assert entry["path"].endswith(".png")
    rendered = Path(entry["path"])
    assert rendered.exists()
    assert rendered.stat().st_size > 10_000
    assert ".simplecad" in entry["path"]
    # Text axiom: the evidence path itself is part of the error text.
    assert entry["path"] in str(ctx.value)


def test_identical_failure_renders_evidence_only_once(tmp_path, monkeypatch):
    monkeypatch.delenv("SCA_NO_DIAGNOSTIC_RENDER", raising=False)
    monkeypatch.chdir(tmp_path)
    from simplecadapi.operators._diagnostics import _RENDER_DEDUP

    _RENDER_DEDUP.clear()
    base, tool = _disjoint_boxes()

    with pytest.raises(scad.SimpleCADError) as first:
        scad.union_rsolid(base, tool)
    with pytest.raises(scad.SimpleCADError) as retry:
        scad.union_rsolid(base, tool)  # same unmoved failure: agent retry loop

    assert len(first.value.to_dict()["evidence"]) == 1
    assert retry.value.to_dict()["evidence"] == []
    # The retry still carries the full text diagnosis.
    assert "min_gap: 14 mm" in str(retry.value)


def test_diagnostics_dir_is_under_the_working_directory(tmp_path, monkeypatch):
    from simplecadapi.operators._diagnostics import diagnostics_dir

    monkeypatch.chdir(tmp_path)
    assert diagnostics_dir() == tmp_path / ".simplecad" / "diagnostics"


def test_union_edge_contact_reports_non_manifold_contact():
    # box1: x/y in [-1,1], z in [0,2]; box2 shares only the edge x=1, y=1.
    box1 = scad.make_box_rsolid(2, 2, 2, bottom_face_center=(0, 0, 0))
    box2 = scad.make_box_rsolid(2, 2, 2, bottom_face_center=(2, 2, 0))

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(box1, box2)

    payload = ctx.value.to_dict()
    measurements = _measurements_dict(ctx.value)
    assert "edge, vertex, or tangent" in payload["what_happened"]
    assert measurements["min_gap"] == pytest.approx(0.0, abs=1e-6)
    assert any("positive-volume overlap" in step for step in payload["repair"])


def test_intersect_disjoint_gets_intersection_repair():
    base, tool = _disjoint_boxes()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.intersect_rsolid(base, tool)

    payload = ctx.value.to_dict()
    assert "intersection is empty" in " ".join(payload["possible_causes"])
    assert any("positive-volume overlap" in step for step in payload["repair"])
    _measurements_dict(ctx.value)["min_gap"] == pytest.approx(14.0)


def test_cut_strict_disjoint_gets_cut_repair():
    base, tool = _disjoint_boxes()
    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.cut_rsolid(base, tool, skip_non_intersecting=False)

    payload = ctx.value.to_dict()
    assert any("reaches inside the base solid" in step for step in payload["repair"])
    assert any("cut removes nothing" in cause for cause in payload["possible_causes"])


def test_cut_default_still_skips_disjoint_tool():
    base, tool = _disjoint_boxes()
    result = scad.cut_rsolid(base, tool)
    assert result.get_volume() == pytest.approx(base.get_volume())


def test_union_multi_operand_reports_nearest_pair():
    far_1 = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(0, 0, 0))
    far_2 = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(5, 0, 0))
    far_3 = scad.make_box_rsolid(1, 1, 1, bottom_face_center=(0, 5, 0))

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(far_1, far_2, far_3)

    payload = ctx.value.to_dict()
    measurements = _measurements_dict(ctx.value)
    assert "separated solids" in payload["what_happened"]
    assert measurements["min_gap"] == pytest.approx(4.0)


def test_union_cluster_chain_reports_inter_cluster_gap_not_internal_pair():
    # A and B overlap (one connected cluster); C is far away. The diagnosis
    # must report the cluster-to-C separation (B↔C, 11 mm), never the
    # internal A↔B pair — pairs connected transitively are not the failure.
    a = scad.make_box_rsolid(10, 4, 4, bottom_face_center=(0, 0, 0))
    b = scad.make_box_rsolid(10, 4, 4, bottom_face_center=(3, 0, 0))
    c = scad.make_box_rsolid(2, 4, 4, bottom_face_center=(20, 0, 0))

    with pytest.raises(scad.SimpleCADError) as ctx:
        scad.union_rsolid(a, b, c)

    payload = ctx.value.to_dict()
    measurements = _measurements_dict(ctx.value)
    assert "operand 2 and operand 3" in payload["what_happened"]
    assert measurements["min_gap"] == pytest.approx(11.0)


def test_message_error_contract_keys_present():
    from simplecadapi.topology.tagging import TagValidationError

    error = TagValidationError("tag already bound")
    payload = error.to_dict()
    assert payload["measurements"] == []
    assert payload["evidence"] == []
    assert payload["repair"] == []
    assert payload["inventory"] == []
    assert str(error) == "tag already bound"
    assert isinstance(error, SimpleCADMessageError)


def test_evidence_and_measurement_types_are_json_ready():
    measurement = ErrorMeasurement("min_gap", 4.25, "mm")
    assert measurement.display() == "min_gap: 4.25 mm"
    vector = ErrorMeasurement("closure", (1.5, 0.0, -2.0), "mm")
    assert vector.display() == "closure: (1.5, 0, -2) mm"

    evidence = ErrorEvidence(kind="render", path="/tmp/x.png", view="default")
    assert evidence.symbols == ()
