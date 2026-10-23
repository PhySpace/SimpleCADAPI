from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import simplecadapi as scad
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Cut
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Dir, gp_Pnt
from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
from simplecadapi._cpp.occt.Quantity import Quantity_Color, Quantity_TOC_RGB
from simplecadapi._cpp.occt.STEPCAFControl import STEPCAFControl_Writer
from simplecadapi._cpp.occt.TCollection import TCollection_ExtendedString
from simplecadapi._cpp.occt.TDocStd import TDocStd_Document
from simplecadapi._cpp.occt.XCAFApp import XCAFApp_Application
from simplecadapi._cpp.occt.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool
from simplecadapi._cpp.occt.TDataStd import TDataStd_Name

from simplecadapi.inspect.brep.model import BRepEntityError, index_shape_rbrepmodel
from simplecadapi.inspect.brep.queries import (
    _section_contours,
    inspect_face_boundaries_rdescriptor,
    inspect_topology_neighborhood_rdescriptor,
    inspect_section_rdescriptor,
    measure_entity_relation_rdescriptor,
    inspect_point_rdescriptor,
    select_region_entities_rdescriptor,
)
from simplecadapi.inspect.brep.render import (
    _edge_polydata,
    _entity_map_legend,
    _load_step_xcaf,
    _mesh_polydata,
    _point_polydata,
    _run_render_worker,
    inspect_step_components_rdescriptorlist,
    render_entity_kind_maps_rpath,
    render_entity_map_rpath,
    render_region_rpath,
    render_step_components_colored_rpath,
    render_step_components_rpath,
    render_step_views_rpath,
)


def _box():
    return BRepPrimAPI_MakeBox(4.0, 3.0, 2.0).Shape()


def _translated(shape, x, y, z):
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Transform
    from simplecadapi._cpp.occt.gp import gp_Trsf, gp_Vec

    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(x, y, z))
    return BRepBuilderAPI_Transform(shape, transform, True).Shape()


def _model():
    return index_shape_rbrepmodel(_box())


def _plane_faces(model):
    return [
        f"face:{index}"
        for index in range(len(model.faces))
        if model.describe_entity(f"face:{index}")["geometry"]["type"] == "PLANE"
    ]


def test_topology_neighborhood_is_bounded_and_rejects_invalid_ids():
    model = _model()

    neighborhood = inspect_topology_neighborhood_rdescriptor(model, "face:0", depth=2, max_entities=3)

    assert neighborhood["root"] == "face:0"
    assert neighborhood["returned_entity_count"] == 3
    assert neighborhood["truncated"] is True
    assert [item["entity_id"] for item in neighborhood["entities"]] == sorted(
        (item["entity_id"] for item in neighborhood["entities"]),
        key=lambda value: (
            ("body", "face", "edge", "vertex").index(value.split(":")[0]),
            int(value.split(":")[1]),
        ),
    )
    with pytest.raises(BRepEntityError, match="out of range"):
        inspect_topology_neighborhood_rdescriptor(model, "face:99")


def test_measure_relation_reports_exact_distance_and_parallel_planes():
    model = _model()
    faces = _plane_faces(model)
    best = None
    for first in faces:
        for second in faces:
            if first >= second:
                continue
            result = measure_entity_relation_rdescriptor(model, first, second)
            if result["relations"]["parallel"]["value"] and result["distance"] > 0.0:
                best = result
                break
        if best:
            break

    assert best is not None
    assert best["distance"] == pytest.approx(4.0)
    assert best["closest_points"]
    assert best["relations"]["parallel"]["supported"] is True
    assert best["relations"]["parallel"]["value"] is True
    assert best["relations"]["coplanar"]["value"] is False


def test_cross_model_face_coincidence_is_not_inferred_from_zero_distance():
    first = _model()
    second = _model()

    relation = measure_entity_relation_rdescriptor(
        first,
        "face:0",
        "face:0",
        second_model_or_path=second,
    )

    assert relation["distance"] == pytest.approx(0.0)
    assert relation["relations"]["coincident"]["supported"] is False
    assert relation["relations"]["coincident"]["value"] is None
    assert relation["relations"]["touching"]["value"] is True


def test_section_of_box_returns_one_closed_contour_with_area():
    section = inspect_section_rdescriptor(_model(), origin=(0.0, 0.0, 1.0), normal=(0.0, 0.0, 1.0))

    assert section["edge_count"] == 4
    assert section["closed_contour_count"] == 1
    contour = section["contours"][0]
    assert contour["closed"] is True
    assert contour["length_exact"] == pytest.approx(14.0)
    assert contour["area"] == pytest.approx(12.0)
    assert contour["role"] == "material"
    assert section["material_area"] == pytest.approx(12.0)
    assert len(contour["samples_3d"][0]) == 3
    assert len(contour["samples_2d"][0]) == 2


def test_section_can_be_scoped_to_one_face():
    model = _model()
    face_id = next(
        f"face:{index}"
        for index in range(len(model.faces))
        if model.describe_entity(f"face:{index}")["bounding_box"]["max"][0]
        == pytest.approx(0.0)
    )

    section = inspect_section_rdescriptor(
        model,
        origin=(0.0, 0.0, 1.0),
        normal=(0.0, 0.0, 1.0),
        face_ids=[face_id],
    )

    assert section["scope"]["face_ids"] == [face_id]
    assert section["edge_count"] == 1
    assert section["closed_contour_count"] == 0
    assert section["open_contour_count"] == 1
    assert section["contours"][0]["length_exact"] == pytest.approx(3.0)


def test_section_requires_enough_samples_to_classify_curved_contours():
    model = index_shape_rbrepmodel(BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape())
    with pytest.raises(ValueError, match="at least four"):
        inspect_section_rdescriptor(
            model,
            origin=(0.0, 0.0, 5.0),
            normal=(0.0, 0.0, 1.0),
            samples_per_edge=2,
        )

    section = inspect_section_rdescriptor(
        model,
        origin=(0.0, 0.0, 5.0),
        normal=(0.0, 0.0, 1.0),
        samples_per_edge=4,
    )

    assert section["closed_contour_count"] == 1
    assert section["material_area"] > 0.0


def test_section_connection_tolerance_heals_small_endpoint_gap():
    gap = 5.0e-6
    points = [
        ([0.0, 0.0, 0.0], [2.0, 0.0, 0.0]),
        ([2.0, 0.0, 0.0], [2.0, 1.0, 0.0]),
        ([2.0, 1.0, 0.0], [0.0, 1.0, 0.0]),
        ([0.0, 1.0, 0.0], [0.0, gap, 0.0]),
    ]
    edges = [
        {
            "index": index,
            "samples_3d": [start, end],
            "length_exact": math.dist(start, end),
        }
        for index, (start, end) in enumerate(points)
    ]
    origin = np.asarray((0.0, 0.0, 0.0))
    x_axis = np.asarray((1.0, 0.0, 0.0))
    y_axis = np.asarray((0.0, 1.0, 0.0))

    strict = _section_contours(
        edges,
        1.0e-7,
        origin,
        x_axis,
        y_axis,
    )
    healed = _section_contours(
        edges,
        1.0e-5,
        origin,
        x_axis,
        y_axis,
    )

    assert strict[0]["closed"] is False
    assert healed[0]["closed"] is True


def test_face_boundaries_preserve_hole_loop_and_pcurve_samples():
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 4.0).Shape()
    axis = gp_Ax2(gp_Pnt(5.0, 5.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    cut = BRepAlgoAPI_Cut(box, BRepPrimAPI_MakeCylinder(axis, 2.0, 4.0).Shape())
    cut.Build()
    assert cut.IsDone()
    model = index_shape_rbrepmodel(cut.Shape())
    top_face = next(
        f"face:{index}"
        for index in range(len(model.faces))
        if model.describe_entity(f"face:{index}")["geometry"]["parameters"]["origin"][2]
        == pytest.approx(4.0)
    )

    boundaries = inspect_face_boundaries_rdescriptor(model, top_face, samples_per_edge=8)

    assert boundaries["outer"]["closed"] is True
    assert boundaries["inner_loop_count"] == 1
    inner_edge = boundaries["inner"][0]["edges"][0]
    assert inner_edge["length_exact"] > 0.0
    assert inner_edge["uv_samples"] is not None
    assert len(inner_edge["uv_samples"]) == 8


def test_face_boundaries_compact_mode_preserves_order_without_samples():
    model = _model()
    detailed = inspect_face_boundaries_rdescriptor(model, "face:0", samples_per_edge=8)
    compact = inspect_face_boundaries_rdescriptor(
        model,
        "face:0",
        samples_per_edge=2,
        compact=True,
    )

    assert compact["compact"] is True
    assert compact["outer"]["geometry_type_counts"] == {"LINE": 4}
    assert [edge["entity_id"] for edge in compact["outer"]["edges"]] == [
        edge["entity_id"] for edge in detailed["outer"]["edges"]
    ]
    first = compact["outer"]["edges"][0]
    assert first["geometry_type"] == "LINE"
    assert first["length_exact"] > 0.0
    assert len(first["start"]) == 3
    assert len(first["end"]) == 3
    assert "samples_3d" not in first
    assert "uv_samples" not in first


def test_compact_boundaries_return_selected_exact_curve_definitions():
    spline = scad.make_spline_redge(
        control_points=[
            (0.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (2.0, 1.0, 0.0),
            (3.0, 0.0, 0.0),
        ],
        degree=3,
    )
    edges = [
        spline,
        scad.make_line_redge((3.0, 0.0, 0.0), (3.0, -1.0, 0.0)),
        scad.make_line_redge((3.0, -1.0, 0.0), (0.0, -1.0, 0.0)),
        scad.make_line_redge((0.0, -1.0, 0.0), (0.0, 0.0, 0.0)),
    ]
    face = scad.make_face_from_wire_rface(scad.make_wire_from_edges_rwire(edges))
    model = index_shape_rbrepmodel(face.wrapped)
    spline_id = next(
        f"edge:{index}"
        for index in range(len(model.edges))
        if model.describe_entity(f"edge:{index}")["geometry"]["type"] == "BSPLINE"
    )

    boundaries = inspect_face_boundaries_rdescriptor(
        model,
        "face:0",
        compact=True,
        include_curve_definitions=True,
        curve_definition_edge_ids=[spline_id],
        max_total_control_points=4,
    )
    definitions = boundaries["curve_definitions"]

    assert definitions["edge_ids"] == [spline_id]
    assert definitions["total_control_points"] == 4
    definition = definitions["definitions"][spline_id]["definition"]
    assert definition["degree"] == 3
    assert len(definition["control_points"]) == 4

    with pytest.raises(BRepEntityError, match="control points; maximum is 3"):
        inspect_face_boundaries_rdescriptor(
            model,
            "face:0",
            compact=True,
            include_curve_definitions=True,
            max_total_control_points=3,
        )


def test_compact_boundary_definition_ids_are_deduplicated_and_sorted():
    model = _model()
    boundary = inspect_face_boundaries_rdescriptor(model, "face:0", compact=True)
    edge_ids = [edge["entity_id"] for edge in boundary["outer"]["edges"]]

    result = inspect_face_boundaries_rdescriptor(
        model,
        "face:0",
        compact=True,
        include_curve_definitions=True,
        curve_definition_edge_ids=[edge_ids[-1], edge_ids[0], edge_ids[-1]],
    )

    assert result["curve_definitions"]["edge_ids"] == sorted(
        {edge_ids[0], edge_ids[-1]},
        key=lambda value: int(value.split(":")[1]),
    )


def test_compact_boundary_definitions_mark_unsupported_carriers_unavailable(
    monkeypatch,
):
    model = _model()
    boundary = inspect_face_boundaries_rdescriptor(model, "face:0", compact=True)
    edge_id = boundary["outer"]["edges"][0]["entity_id"]
    monkeypatch.setattr(
        "simplecadapi.inspect.brep.queries._curve_type",
        lambda edge: "OFFSET",
    )

    result = inspect_face_boundaries_rdescriptor(
        model,
        "face:0",
        compact=True,
        include_curve_definitions=True,
        curve_definition_edge_ids=[edge_id],
    )

    definition = result["curve_definitions"]["definitions"][edge_id]
    assert definition["available"] is False
    assert definition["definition"] is None


def test_compact_section_omits_samples_and_preserves_summary():
    detailed = inspect_section_rdescriptor(
        _model(),
        origin=(0.0, 0.0, 1.0),
        normal=(0.0, 0.0, 1.0),
    )
    compact = inspect_section_rdescriptor(
        _model(),
        origin=(0.0, 0.0, 1.0),
        normal=(0.0, 0.0, 1.0),
        compact=True,
    )

    assert compact["compact"] is True
    assert compact["edge_count"] == detailed["edge_count"]
    assert compact["material_area"] == detailed["material_area"]
    assert (
        compact["contours"][0]["length_exact"]
        == detailed["contours"][0]["length_exact"]
    )
    assert all("samples_3d" not in edge for edge in compact["edges"])
    assert all("samples_2d" not in contour for contour in compact["contours"])
    assert all(len(edge["start"]) == 3 for edge in compact["edges"])


def test_section_classifies_hole_and_reports_material_area():
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 4.0).Shape()
    axis = gp_Ax2(gp_Pnt(5.0, 5.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    cut = BRepAlgoAPI_Cut(box, BRepPrimAPI_MakeCylinder(axis, 2.0, 4.0).Shape())
    cut.Build()
    assert cut.IsDone()

    section = inspect_section_rdescriptor(
        index_shape_rbrepmodel(cut.Shape()),
        origin=(0.0, 0.0, 2.0),
        normal=(0.0, 0.0, 1.0),
        samples_per_edge=64,
    )

    assert section["closed_contour_count"] == 2
    assert {contour["role"] for contour in section["contours"]} == {
        "material",
        "hole",
    }
    assert section["material_area"] == pytest.approx(
        100.0 - math.pi * 4.0,
        rel=2.0e-3,
    )


def test_probe_point_orders_exact_nearest_entities():
    result = inspect_point_rdescriptor(_model(), point=(8.0, 1.0, 1.0), limit=4)

    assert result["candidate_count"] == 26
    assert len(result["hits"]) == 4
    assert result["hits"][0]["distance"] == pytest.approx(4.0)
    assert result["hits"][0]["closest_point"] == pytest.approx([4.0, 1.0, 1.0])
    assert result["hits"][0]["kind"] == "face"
    assert result["exact_distance_evaluation_count"] < result["candidate_count"]
    assert result["bbox_pruned_count"] > 0


def test_select_region_entities_expands_stable_ids_and_returns_bounds():
    model = _model()
    selection = select_region_entities_rdescriptor(model, entity_ids=["face:0"], depth=1)

    assert "face:0" in selection["entity_ids"]
    assert "body:0" in selection["entity_ids"]
    assert any(entity.startswith("edge:") for entity in selection["entity_ids"])
    assert all(
        minimum <= maximum
        for minimum, maximum in zip(
            selection["bounds"]["min"], selection["bounds"]["max"]
        )
    )


def test_render_region_writes_highlighted_image(tmp_path):
    output = tmp_path / "highlight.png"

    result = render_region_rpath(_model(), ["face:0"], output, dpi=60)

    assert result == output
    assert output.is_file()
    assert output.stat().st_size > 0

def test_render_step_views_preserves_xcaf_colors_and_brep_edges(tmp_path):
    XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    color_tool = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    label = shape_tool.AddShape(_box(), False, False)
    TDataStd_Name.Set_s(label, TCollection_ExtendedString("colored"))
    expected = (0.8, 0.1, 0.2)
    color_tool.SetColor(
        label,
        Quantity_Color(*expected, Quantity_TOC_RGB),
        XCAFDoc_ColorSurf,
    )
    step = tmp_path / "colored.step"
    writer = STEPCAFControl_Writer()
    assert writer.Transfer(document)
    assert writer.Write(str(step)) == IFSelect_RetDone

    shape, face_colors = _load_step_xcaf(step)
    assert face_colors
    assert all(color[:3] == pytest.approx(expected) for color in face_colors.values())
    mesh = _mesh_polydata(
        [shape],
        linear_deflection=0.1,
        angular_deflection=0.2,
        face_colors=face_colors,
    )
    assert mesh.GetCellData().GetScalars().GetName() == "STEP_RGBA"
    assert _edge_polydata([shape], deflection=0.1).GetNumberOfLines() == 12
    output = tmp_path / "colored.png"
    assert render_step_views_rpath(step, output, image_size=(2.0, 2.0), dpi=60) == output
    assert output.stat().st_size > 0

    components = inspect_step_components_rdescriptorlist(step)
    assert components[0]["name"] == "colored"
    named = tmp_path / "named.png"
    assert render_step_components_rpath(
        step,
        ["colored"],
        named,
        with_context=False,
        image_size=(2.0, 2.0),
        dpi=60,
    ) == named
    assert named.stat().st_size > 0


def test_render_step_components_colored_maps_palette_and_legend(tmp_path):
    from simplecadapi.inspect.brep.render import _resolve_color

    XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    labels = []
    for name, offset in (("red_part", 0.0), ("blue_part", 20.0)):
        label = shape_tool.AddShape(_translated(_box(), offset, 0.0, 0.0), False, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
        labels.append(label)
    step = tmp_path / "colored.step"
    writer = STEPCAFControl_Writer()
    assert writer.Transfer(document)
    assert writer.Write(str(step)) == IFSelect_RetDone

    # color resolution: hex, named, tuple, and palette index forms
    assert _resolve_color("#ff0000") == (1.0, 0.0, 0.0)
    assert _resolve_color("blue") == pytest.approx((0.20, 0.35, 0.95))
    assert _resolve_color("crimson") == pytest.approx((0.86, 0.08, 0.24))
    assert _resolve_color("skyblue")[2] == pytest.approx(0.95)
    assert _resolve_color((0.1, 0.2, 0.3)) == (0.1, 0.2, 0.3)
    with pytest.raises(ValueError):
        _resolve_color("chartreuse")
    palette = ["#e6194b", "#3cb44b"]
    assert _resolve_color(0, palette) == (230 / 255, 25 / 255, 75 / 255)
    with pytest.raises(ValueError):
        _resolve_color(3, palette)
    with pytest.raises(ValueError):
        _resolve_color(0)

    colored = tmp_path / "colored.png"
    assert render_step_components_colored_rpath(
        step,
        {"red_part": 0, "blue_part": "#3cb44b"},
        colored,
        palette=palette,
        with_context=True,
        image_size=(2.0, 2.0),
        dpi=60,
    ) == colored
    assert colored.stat().st_size > 0

    bare = tmp_path / "bare.png"
    assert render_step_components_colored_rpath(
        step,
        {"red_part": "red", "blue_part": (0.2, 0.3, 0.4)},
        bare,
        with_context=False,
        image_size=(2.0, 2.0),
        dpi=60,
        show_legend=False,
    ) == bare
    assert bare.stat().st_size > 0

    with pytest.raises(ValueError):
        render_step_components_colored_rpath(step, {}, tmp_path / "none.png")


def test_render_entity_map_writes_multicolor_annotated_image(tmp_path):
    model = _model()
    output = tmp_path / "entity-map.png"

    result = render_entity_map_rpath(
        model,
        ["body:0", "face:0", "edge:0", "vertex:0"],
        output,
        views=((28.0, -45.0, "isometric"),),
        image_size=(4.0, 3.0),
        dpi=80,
        label_mode="legend",
    )

    assert result == output
    assert output.is_file()
    assert output.stat().st_size > 0

def test_render_entity_map_uses_external_key_for_large_selection(tmp_path):
    model = _model()
    output = tmp_path / "entity-key.png"
    ids = [f"face:{index}" for index in range(6)]

    assert render_entity_map_rpath(
        model,
        ids,
        output,
        max_callouts=4,
        label_mode="auto",
        legend_columns=2,
        image_size=(5.0, 3.0),
        dpi=80,
    ) == output
    assert output.stat().st_size > 0
    colors = [(float(index), 0.0, 0.0) for index in range(6)]
    assert [label for label, _ in _entity_map_legend(
        [(ids[index], "PLANE", colors[index]) for index in range(6)], columns=2
    )] == [f"face:{index} · PLANE" for index in range(6)]

def test_render_entity_map_preserves_opaque_context_and_true_edges(tmp_path):
    model = _model()
    output = tmp_path / "depth-map.png"
    assert render_entity_map_rpath(
        model,
        ["body:0", "face:0", "edge:0", "vertex:0"],
        output,
        views=((28.0, -45.0, "isometric"),),
        image_size=(4.0, 3.0),
        dpi=80,
    ) == output
    assert output.stat().st_size > 0

def test_render_entity_kind_maps_splits_geometry_kinds(tmp_path):
    model = _model()
    outputs = render_entity_kind_maps_rpath(
        model,
        ["face:0", "edge:0", "vertex:0"],
        tmp_path / "split",
        views=((28.0, -45.0, "isometric"),),
        image_size=(4.0, 3.0),
        dpi=80,
        highlight_edge_width=8.0,
        highlight_point_size=22.0,
    )
    assert set(outputs) == {"face", "edge", "vertex"}
    assert all(path.is_file() and path.stat().st_size > 0 for path in outputs.values())


def test_render_entity_map_rejects_empty_duplicate_and_invalid_options(tmp_path):
    model = _model()

    with pytest.raises(ValueError, match="At least one entity ID"):
        render_entity_map_rpath(model, [], tmp_path / "empty.png")
    with pytest.raises(ValueError, match="duplicate entity ID 'face:0'"):
        render_entity_map_rpath(
            model,
            ["face:0", "face:0"],
            tmp_path / "duplicate.png",
        )
    with pytest.raises(ValueError, match="context_opacity"):
        render_entity_map_rpath(
            model,
            ["face:0"],
            tmp_path / "opacity.png",
            context_opacity=1.1,
        )
    with pytest.raises(ValueError, match="label_mode"):
        render_entity_map_rpath(
            model,
            ["face:0"],
            tmp_path / "label-mode.png",
            label_mode="invalid",
        )

    with pytest.raises(ValueError, match="highlight_edge_width"):
        render_entity_map_rpath(
            model, ["edge:0"], tmp_path / "edge-width.png", highlight_edge_width=0.0
        )
    with pytest.raises(ValueError, match="highlight_point_size"):
        render_entity_map_rpath(
            model, ["vertex:0"], tmp_path / "point-size.png", highlight_point_size=0.0
        )



def test_render_worker_retries_crash_and_requires_clean_exit(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(tuple(command))
        payload = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        Path(payload["output_path"]).write_bytes(b"crashed-image")
        Path(payload["completion_path"]).touch()
        if len(calls) == 1:
            return SimpleNamespace(returncode=-11, stderr="", stdout="")
        Path(payload["output_path"]).write_bytes(b"complete-image")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(
        "simplecadapi.inspect.brep.render.subprocess.run", fake_run
    )
    output = tmp_path / "worker.png"
    result = _run_render_worker(
        mode="views",
        output_path=output,
        datasets={"base": _point_polydata([(0.0, 0.0, 0.0)])},
        options={},
    )

    assert result == output
    assert output.read_bytes() == b"complete-image"
    assert len(calls) == 2

def test_render_region_does_not_mutate_cached_model_geometry(tmp_path):
    model = _model()
    before = model.summary()

    render_region_rpath(model, ["face:0"], tmp_path / "highlight.png", dpi=60)

    after = model.summary()
    assert after["bounding_box"] == pytest.approx(before["bounding_box"])
    assert after["volume"] == pytest.approx(before["volume"])
    assert after["surface_area"] == pytest.approx(before["surface_area"])
