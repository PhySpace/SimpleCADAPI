"""Acceptance must reject missing evidence and geometric false positives."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/research/build123dftc"))
from b3ftc.validation import compare_metrics, validate_directory, validate_row


def expected(**changes):
    trace = {"b3d_status": "ok", "b3d_volume": 1000.0,
             "b3d_bbox": [-5, -5, 0, 5, 5, 10], "solid_count": 1,
             "result_refs": ["s1"], "unsupported": []}
    trace.update(changes)
    return trace


def actual(**changes):
    metrics = {"status": "ok", "volume": 1000.0,
               "bbox": [-5, -5, 0, 5, 5, 10], "solid_count": 1,
               "body_count": 1, "is_valid": True}
    metrics.update(changes)
    return metrics


META = {"status": "ok", "unsupported": []}


def test_matching_metrics_accepted():
    result = compare_metrics(expected(), actual(), META)
    assert result["quality"] == "accepted", result
    assert result["bbox_error"] == 0


def test_reference_failure_reports_basic_geometry_separately(tmp_path, monkeypatch):
    import b3ftc.validation as validation
    ftc = tmp_path / "sample.ftc.py"
    ftc.write_text("# worker is isolated by this test")
    trace = tmp_path / "sample.trace.json"
    trace.write_text(json.dumps(expected()))
    ftc.with_name("sample.meta.json").write_text(json.dumps(META))
    monkeypatch.setattr(validation, "_worker", lambda *args, **kwargs:
        actual(reference_status="error", reference_error="kernel comparison failed"))
    row = validate_row(ftc, trace, reference_step=tmp_path / "reference.step")
    assert row["quality"] == "rejected"
    assert row["metrics_quality"] == "accepted"
    assert row["metrics_reasons"] == []
    assert row["reasons"] == ["reference_error"]


def test_rational_circle_cylinder_has_mathematical_area_four_pi():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.Geom import Geom_Circle
    from OCP.GeomConvert import GeomConvert
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir, gp_Vec
    from b3ftc._validate_worker import _area, _volume

    circle = Geom_Circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 1)
    spline = GeomConvert.CurveToBSplineCurve_s(circle)
    assert spline.IsRational()
    edge = BRepBuilderAPI_MakeEdge(spline).Edge()
    wire = BRepBuilderAPI_MakeWire(edge).Wire()
    face = BRepBuilderAPI_MakeFace(wire, True).Face()
    solid = BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 1)).Shape()
    # OCCT 7.9's continuity split adds about 7.7e-9 relative integration
    # error here; this precision still detects the original 0.0028 error.
    assert _area(solid) == pytest.approx(4 * math.pi, rel=1e-8)
    assert _volume(solid) == pytest.approx(math.pi, rel=1e-9)


def test_reference_export_cannot_change_geometry_to_obtain_acceptance():
    metrics = actual(reference_status="ok", reference_volume=1000,
                     symmetric_difference_volume=0, roundtrip_actual_volume=900,
                     roundtrip_actual_bbox=[-5, -5, 0, 5, 5, 10],
                     roundtrip_actual_solid_count=1, roundtrip_actual_valid=True)
    row = compare_metrics(expected(), metrics, META, require_reference=True)
    assert row["quality"] == "rejected"
    assert "reference_roundtrip_changed_geometry" in row["reasons"]


@pytest.mark.parametrize("changes", [
    {"b3d_status": "error"}, {"b3d_volume": None}, {"b3d_bbox": None},
    {"solid_count": None}, {"result_refs": []}, {"b3d_volume": math.nan},
    {"b3d_bbox": [0, 0, 0]}, {"unsupported": ["unsupported sweep"]},
])
def test_source_failure_or_missing_evidence_rejected(changes):
    assert compare_metrics(expected(**changes), actual(), META)["quality"] == "rejected"


@pytest.mark.parametrize("metadata", [None, {}, {"status": "partial"},
    {"status": "ok", "unsupported": ["torus"]},
    {"status": "ok", "unknown": ["operation"]},
    {"status": "ok", "unknown_operations": 1}])
def test_incomplete_conversion_never_accepted(metadata):
    assert compare_metrics(expected(), actual(), metadata)["quality"] == "rejected"


@pytest.mark.parametrize("changes", [
    {"body_count": 0}, {"solid_count": 2}, {"is_valid": False},
    {"volume": None}, {"bbox": None}, {"volume": math.inf},
    {"bbox": [0, -5, 0, 10, 5, 10]},
])
def test_actual_failure_including_rigid_translation_rejected(changes):
    assert compare_metrics(expected(), actual(**changes), META)["quality"] == "rejected"


def write_case(root: Path, stem: str, source: str, trace=None, metadata=None):
    ftc_dir, traces_dir = root / "ftc", root / "traces"
    ftc_dir.mkdir(exist_ok=True)
    traces_dir.mkdir(exist_ok=True)
    ftc = ftc_dir / (stem + ".ftc.py")
    ftc.write_text(source)
    trace_path = traces_dir / (stem + ".trace.json")
    trace_path.write_text(json.dumps(trace or expected()))
    ftc.with_name(stem + ".meta.json").write_text(json.dumps(metadata or META))
    return ftc, trace_path


def box_source(center_x=0):
    return f'''from pathlib import Path
import simplecadapi as scad
BODIES = None
@scad.part(id='validation-box', project_root=Path(__file__).parent)
def build():
    global BODIES
    body = scad.make_box_rsolid(10, 10, 10, bottom_face_center=({center_x}, 0, 0))
    BODIES = [body]
    return body
'''


def test_worker_builds_real_topology_and_checks_position(tmp_path):
    ftc, trace = write_case(tmp_path, "box", box_source())
    row = validate_row(ftc, trace, timeout=30)
    assert row["quality"] == "accepted", row
    assert row["ftc_solid_count"] == 1
    ftc.write_text(box_source(10))
    row = validate_row(ftc, trace, timeout=30)
    assert row["quality"] == "rejected", row
    assert "bbox_mismatch" in row["reasons"]


def test_no_bodies_cannot_fall_back_to_returned_part(tmp_path):
    source = box_source().replace("BODIES = [body]", "BODIES = []")
    ftc, trace = write_case(tmp_path, "empty", source)
    row = validate_row(ftc, trace, timeout=30)
    assert row["quality"] == "rejected", row
    assert "empty_bodies" in row["reasons"]


def test_timeout_and_build_failure_do_not_stop_batch(tmp_path):
    write_case(tmp_path, "a_timeout", "import time\ntime.sleep(100)\n")
    write_case(tmp_path, "b_failure", "raise RuntimeError('model failure')\n")
    write_case(tmp_path, "c_good", box_source())
    report = validate_directory(tmp_path / "ftc", tmp_path / "traces", timeout=8)
    assert [row["quality"] for row in report["rows"]] == ["rejected", "rejected", "accepted"], report
    assert report["rows"][0]["build"] == "timeout"
    assert "model failure" in report["rows"][1]["error"]


def test_missing_trace_rejected_but_other_cases_continue(tmp_path):
    ftc, trace = write_case(tmp_path, "a_missing", box_source())
    trace.unlink()
    write_case(tmp_path, "b_good", box_source())
    report = validate_directory(ftc.parent, tmp_path / "traces", timeout=30)
    assert report["counts"] == {"accepted": 1, "partial": 0, "rejected": 1}


def test_reference_step_detects_equal_volume_equal_bbox_different_holes(tmp_path):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone

    box = BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, 0), 10, 10, 10).Shape()
    hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(2, 0, 0), gp_Dir(0, 0, 1)), 1, 10).Shape()
    reference = BRepAlgoAPI_Cut(box, hole).Shape()
    step = tmp_path / "reference.step"
    writer = STEPControl_Writer()
    assert writer.Transfer(reference, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(step)) == IFSelect_RetDone
    source = box_source().replace("BODIES = [body]", "body = scad.cut_rsolid(body, scad.make_cylinder_rsolid(1, 10, bottom_face_center=(-2, 0, 0)))\n    BODIES = [body]")
    ftc, trace = write_case(tmp_path, "wrong_hole", source,
                            expected(b3d_volume=1000 - math.pi * 10))
    coarse = validate_row(ftc, trace, timeout=30)
    assert coarse["quality"] == "accepted", coarse
    strict = validate_row(ftc, trace, timeout=30, reference_step=step)
    assert strict["quality"] == "rejected", strict
    assert "symmetric_difference_mismatch" in strict["reasons"]
    assert strict["symmetric_difference_volume"] > 60
    independent = validate_row(ftc, trace, timeout=30, reference_step=step,
                                reference_python=sys.executable)
    assert independent["quality"] == "rejected", independent
    assert independent["reference_kernel"]
    assert "symmetric_difference_mismatch" in independent["reasons"]
    ftc.write_text(source.replace("bottom_face_center=(-2, 0, 0)", "bottom_face_center=(2, 0, 0)"))
    identical = validate_row(ftc, trace, timeout=30, reference_step=step,
                              reference_python=sys.executable)
    assert identical["quality"] == "accepted", identical
    assert identical["symmetric_difference_volume"] == pytest.approx(0)


def test_requested_missing_reference_rejected(tmp_path):
    ftc, trace = write_case(tmp_path, "box", box_source())
    row = validate_row(ftc, trace, timeout=30, reference_step=tmp_path / "absent.step")
    assert row["quality"] == "rejected", row
    assert "reference_error" in row["reasons"]


@pytest.mark.parametrize("returned", ["None", "scad.make_box_rsolid(1, 1, 1)",
                                     "scad.translate_shape(body, (10, 0, 0))"])
def test_actual_build_return_cannot_hide_behind_matching_bodies(tmp_path, returned):
    source = box_source().replace("return body", f"return {returned}")
    # A plain build allows None so the worker itself must reject it.
    source = "\n".join(line for line in source.splitlines() if not line.startswith("@scad.part"))
    ftc, trace = write_case(tmp_path, "wrong_return", source)
    row = validate_row(ftc, trace, timeout=30)
    assert row["quality"] == "rejected", row


def test_returned_assembly_is_checked_in_world_coordinates(tmp_path):
    source = """import simplecadapi as scad
BODIES = None
def build():
    global BODIES
    body = scad.make_box_rsolid(10, 10, 10)
    BODIES = [body]
    part = scad.make_part_rpart(part_id='box', body=body)
    assembly = scad.make_assembly_rassembly(assembly_id='placed')
    return scad.add_component_rassembly(assembly=assembly, item=part,
        component_id='box', placement=scad.make_placement_rplacement(origin=(10,0,0)))
"""
    ftc, trace = write_case(tmp_path, "placed", source)
    row = validate_row(ftc, trace, timeout=30)
    assert row["quality"] == "rejected", row
    assert "does not match" in row["error"]
