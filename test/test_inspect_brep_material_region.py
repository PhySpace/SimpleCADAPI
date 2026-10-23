from __future__ import annotations

import math
import pytest
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Cut
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi._cpp.occt.gp import gp_Pnt

from simplecadapi.inspect import brep


def _candidate_with_two_notches():
    target = BRepPrimAPI_MakeBox(10.0, 4.0, 4.0).Shape()
    first = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 1.0, 1.0), 1.0, 1.0, 1.0).Shape()
    second = BRepPrimAPI_MakeBox(gp_Pnt(8.0, 1.0, 1.0), 1.0, 1.0, 1.0).Shape()
    cut = BRepAlgoAPI_Cut(target, first)
    cut.Build()
    cut2 = BRepAlgoAPI_Cut(cut.Shape(), second)
    cut2.Build()
    return target, cut2.Shape()


def _compound(*shapes):
    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def test_compare_material_region_limits_evidence_to_roi(tmp_path):
    target, candidate = _candidate_with_two_notches()

    report = brep.compare_material_region_rdescriptor(
        target,
        candidate,
        region_min=(0.0, 0.0, 0.0),
        region_max=(5.0, 4.0, 4.0),
        output_directory=tmp_path,
    )

    assert report["missing_material"]["volume"] == pytest.approx(1.0)
    assert report["excess_material"]["volume"] == pytest.approx(0.0)
    assert report["missing_material"]["component_count"] == 1
    assert report["local_equality_supported"] is True
    assert report["global_equality_supported"] is False
    assert (tmp_path / "missing_material.step").is_file()


def test_compare_material_region_reports_empty_local_difference():
    target, candidate = _candidate_with_two_notches()

    report = brep.compare_material_region_rdescriptor(
        target,
        candidate,
        region_min=(4.0, 0.0, 0.0),
        region_max=(7.0, 4.0, 4.0),
    )

    assert report["missing_material"]["volume"] == pytest.approx(0.0)
    assert report["excess_material"]["volume"] == pytest.approx(0.0)
    assert report["locally_equal"] is True
    assert report["global_equality_supported"] is False


def test_compare_material_region_handles_empty_roi_crop():
    target, candidate = _candidate_with_two_notches()

    report = brep.compare_material_region_rdescriptor(
        target,
        candidate,
        region_min=(20.0, 20.0, 20.0),
        region_max=(21.0, 21.0, 21.0),
    )

    assert report["localized_target_volume"] == pytest.approx(0.0)
    assert report["localized_current_volume"] == pytest.approx(0.0)
    assert report["locally_equal"] is True


def test_compare_material_region_handles_one_empty_crop_side():
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(5.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()

    report = brep.compare_material_region_rdescriptor(
        target,
        current,
        region_min=(0.0, 0.0, 0.0),
        region_max=(2.0, 2.0, 2.0),
    )

    assert report["missing_material"]["volume"] == pytest.approx(8.0)
    assert report["excess_material"]["volume"] == pytest.approx(0.0)
    assert report["boolean_result_valid"] is True


def test_compare_material_region_supports_multi_body_material_unions():
    first = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    second = BRepPrimAPI_MakeBox(gp_Pnt(5.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()
    target = _compound(first, second)

    report = brep.compare_material_region_rdescriptor(
        target,
        first,
        region_min=(-1.0, -1.0, -1.0),
        region_max=(8.0, 3.0, 3.0),
    )

    assert report["localized_target_volume"] == pytest.approx(16.0)
    assert report["localized_current_volume"] == pytest.approx(8.0)
    assert report["missing_material"]["volume"] == pytest.approx(8.0)
    assert report["missing_material"]["component_count"] == 1
    assert report["missing_material"]["components"][0]["centroid"] == pytest.approx(
        [6.0, 1.0, 1.0]
    )
    assert report["locally_equal"] is False


def test_compare_material_region_large_roi_does_not_hide_difference():
    target = BRepPrimAPI_MakeBox(0.5, 0.5, 0.5).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(10.0, 0.0, 0.0), 0.5, 0.5, 0.5).Shape()

    report = brep.compare_material_region_rdescriptor(
        target,
        current,
        region_min=(-1000.0, -1000.0, -1000.0),
        region_max=(1000.0, 1000.0, 1000.0),
    )

    assert report["missing_material"]["volume"] == pytest.approx(0.125)
    assert report["locally_equal"] is False


def test_compare_material_region_removes_stale_exports(tmp_path):
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(5.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()
    brep.compare_material_region_rdescriptor(
        target,
        current,
        region_min=(0.0, 0.0, 0.0),
        region_max=(2.0, 2.0, 2.0),
        output_directory=tmp_path,
    )
    assert (tmp_path / "missing_material.step").is_file()

    report = brep.compare_material_region_rdescriptor(
        target,
        target,
        region_min=(0.0, 0.0, 0.0),
        region_max=(2.0, 2.0, 2.0),
        output_directory=tmp_path,
    )

    assert report["locally_equal"] is True
    assert not (tmp_path / "missing_material.step").exists()


def test_compare_material_region_exports_one_sided_crop(tmp_path):
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(5.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()

    report = brep.compare_material_region_rdescriptor(
        target,
        current,
        region_min=(0.0, 0.0, 0.0),
        region_max=(2.0, 2.0, 2.0),
        output_directory=tmp_path,
    )

    assert report["exported_files"]["missing_material"] == str(
        tmp_path / "missing_material.step"
    )
    assert (tmp_path / "missing_material.step").is_file()


def test_compare_material_region_rejects_export_alias(tmp_path):
    from simplecadapi.kernel.ocp_export import export_step_shapes

    source = tmp_path / "missing_material.step"
    export_step_shapes([BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()], str(source))

    with pytest.raises(ValueError, match="would overwrite an input STEP"):
        brep.compare_material_region_rdescriptor(
            source,
            source,
            region_min=(0.0, 0.0, 0.0),
            region_max=(1.0, 1.0, 1.0),
            output_directory=tmp_path,
        )


def test_compare_material_region_bounds_component_records():
    target = BRepPrimAPI_MakeBox(10.0, 2.0, 2.0).Shape()
    first = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 0.5, 0.5), 1.0, 1.0, 1.0).Shape()
    second = BRepPrimAPI_MakeBox(gp_Pnt(7.0, 0.5, 0.5), 1.0, 1.0, 1.0).Shape()
    cut = BRepAlgoAPI_Cut(target, first)
    cut.Build()
    cut2 = BRepAlgoAPI_Cut(cut.Shape(), second)
    cut2.Build()

    report = brep.compare_material_region_rdescriptor(
        target,
        cut2.Shape(),
        region_min=(0.0, 0.0, 0.0),
        region_max=(10.0, 2.0, 2.0),
        max_components=1,
    )

    assert report["missing_material"]["component_count"] == 2
    assert len(report["missing_material"]["components"]) == 1
    assert report["missing_material"]["components_truncated"] is True


def test_compare_material_region_rejects_invalid_region():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    with pytest.raises(ValueError, match="region_max must exceed region_min"):
        brep.compare_material_region_rdescriptor(
            box,
            box,
            region_min=(0.0, 0.0, 0.0),
            region_max=(0.0, 1.0, 1.0),
        )
    with pytest.raises(ValueError, match="boolean_tolerance must be finite"):
        brep.compare_material_region_rdescriptor(
            box,
            box,
            region_min=(0.0, 0.0, 0.0),
            region_max=(1.0, 1.0, 1.0),
            boolean_tolerance=math.nan,
        )


def test_compare_material_region_rejects_invalid_zero_volume_solid():
    from simplecadapi._cpp.occt.BRep import BRep_Builder
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from simplecadapi._cpp.occt.TopoDS import TopoDS_Shell

    shell = TopoDS_Shell()
    BRep_Builder().MakeShell(shell)
    zero_volume = BRepBuilderAPI_MakeSolid(shell).Solid()

    with pytest.raises(ValueError, match="valid positive-volume solid material"):
        brep.compare_material_region_rdescriptor(
            zero_volume,
            zero_volume,
            region_min=(0.0, 0.0, 0.0),
            region_max=(1.0, 1.0, 1.0),
        )


@pytest.mark.parametrize(
    ("failure", "function_name"),
    [
        ("crop", "_common_shape"),
        ("boolean", "_cut_shape"),
        ("component", "_component_summary"),
        ("export", "export_step_shapes"),
    ],
)
def test_compare_material_region_cleans_staging_after_failure(
    tmp_path, monkeypatch, failure, function_name
):
    from simplecadapi.inspect.brep import diagnostics

    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()

    def fail(*args, **kwargs):
        raise RuntimeError(f"{failure} failed")

    monkeypatch.setattr(diagnostics, function_name, fail)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        diagnostics.compare_material_region_rdescriptor(
            target,
            current,
            region_min=(0.0, 0.0, 0.0),
            region_max=(2.0, 2.0, 2.0),
            output_directory=tmp_path,
        )

    assert not list(tmp_path.glob(".localized-material-*"))


def test_compare_material_region_rolls_back_publication_failure(
    tmp_path, monkeypatch
):
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()
    missing = tmp_path / "missing_material.step"
    excess = tmp_path / "excess_material.step"
    missing.write_bytes(b"previous missing")
    excess.write_bytes(b"previous excess")
    original_replace = type(missing).replace

    def fail_second_publication(path, target_path):
        destination = type(path)(target_path)
        if (
            path.name == "excess_material.step"
            and path.parent.name.startswith(".localized-material-")
            and destination.parent == tmp_path
        ):
            raise RuntimeError("publication failed")
        return original_replace(path, target_path)

    monkeypatch.setattr(type(missing), "replace", fail_second_publication)

    with pytest.raises(RuntimeError, match="publication failed"):
        brep.compare_material_region_rdescriptor(
            target,
            current,
            region_min=(0.0, 0.0, 0.0),
            region_max=(3.0, 2.0, 2.0),
            output_directory=tmp_path,
        )

    assert missing.read_bytes() == b"previous missing"
    assert excess.read_bytes() == b"previous excess"
    assert not list(tmp_path.glob(".localized-material-*"))


def test_compare_material_region_keeps_publication_when_backup_cleanup_fails(
    tmp_path, monkeypatch
):
    target = BRepPrimAPI_MakeBox(2.0, 2.0, 2.0).Shape()
    current = BRepPrimAPI_MakeBox(gp_Pnt(1.0, 0.0, 0.0), 2.0, 2.0, 2.0).Shape()
    missing = tmp_path / "missing_material.step"
    excess = tmp_path / "excess_material.step"
    missing.write_bytes(b"previous missing")
    excess.write_bytes(b"previous excess")
    original_unlink = type(missing).unlink

    def fail_backup_cleanup(path, *args, **kwargs):
        if path.name == "previous-excess_material.step":
            raise OSError("cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(missing), "unlink", fail_backup_cleanup)

    report = brep.compare_material_region_rdescriptor(
        target,
        current,
        region_min=(0.0, 0.0, 0.0),
        region_max=(3.0, 2.0, 2.0),
        output_directory=tmp_path,
    )

    assert report["locally_equal"] is False
    assert missing.is_file()
    assert excess.is_file()
    assert missing.read_bytes() != b"previous missing"
    assert excess.read_bytes() != b"previous excess"
    assert not list(tmp_path.glob(".localized-material-*"))
