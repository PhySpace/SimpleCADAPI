"""Tests for rendering detailed STEP/BRep section descriptors."""

from __future__ import annotations

import math
import json

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pytest
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

import simplecadapi as scad
from simplecadapi.inspect import brep
from simplecadapi.inspect.brep.feature_visualization import FEATURE_COLORS


def _box_section(*, normal=(0.0, 0.0, 1.0)):
    return brep.inspect_section_rdescriptor(
        model_or_path=BRepPrimAPI_MakeBox(4.0, 3.0, 2.0).Shape(),
        origin=(0.0, 0.0, 1.0),
        normal=normal,
        samples_per_edge=32,
    )


def _through_hole_section():
    box = BRepPrimAPI_MakeBox(10.0, 10.0, 4.0).Shape()
    axis = gp_Ax2(gp_Pnt(5.0, 5.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
    cut = BRepAlgoAPI_Cut(
        box,
        BRepPrimAPI_MakeCylinder(axis, 2.0, 4.0).Shape(),
    )
    cut.Build()
    assert cut.IsDone()
    return brep.inspect_section_rdescriptor(
        model_or_path=cut.Shape(),
        origin=(0.0, 0.0, 2.0),
        normal=(0.0, 0.0, 1.0),
        samples_per_edge=64,
    )


def _empty_section():
    return {
        "plane": {
            "origin": [0.0, 0.0, 20.0],
            "normal": [0.0, 0.0, 1.0],
            "x_direction": [1.0, 0.0, 0.0],
            "y_direction": [0.0, 1.0, 0.0],
        },
        "contours": [],
        "closed_contour_count": 0,
        "open_contour_count": 0,
        "material_area": 0.0,
    }


def _open_section():
    section = _empty_section()
    section["contours"] = [
        {
            "index": 0,
            "closed": False,
            "samples_2d": [[10.0, 20.0], [12.0, 21.0], [14.0, 20.0]],
            "length_exact": 2.0 * math.sqrt(5.0),
            "area": None,
        }
    ]
    section["open_contour_count"] = 1
    return section


def test_box_section_renders_nonempty_image_and_creates_parent(tmp_path):
    output = tmp_path / "nested" / "box-section.png"

    result = brep.render_sections_rpath(
        sections=[_box_section()],
        output_path=output,
        titles=["box-center"],
        columns=1,
        image_size_per_panel=(4.0, 3.0),
        dpi=80,
    )

    assert result == output
    assert output.is_file()
    assert output.stat().st_size > 0
    image = mpimg.imread(output)
    assert image.shape[0] >= 200
    assert image.shape[1] >= 300
    assert float(np.std(image)) > 0.01


def test_hole_and_material_use_distinct_styles_and_area_text(tmp_path, monkeypatch):
    section = _through_hole_section()
    plot_calls = []
    original_plot = plt.Axes.plot

    def capture_plot(axes, *args, **kwargs):
        plot_calls.append((args, kwargs.copy()))
        return original_plot(axes, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "plot", capture_plot)
    output = tmp_path / "hole.png"

    brep.render_sections_rpath(
        sections=[section],
        output_path=output,
        titles=["through-hole"],
        columns=1,
        dpi=80,
    )

    contour_calls = [call for call in plot_calls if "color" in call[1]]
    assert {call[1]["color"] for call in contour_calls} >= {"#1f77b4", "#d62728"}
    assert section["material_area"] == pytest.approx(100.0 - math.pi * 4.0, rel=2.0e-3)
    assert output.stat().st_size > 0


def test_open_contour_uses_samples_2d_dashed_and_is_not_filled(tmp_path, monkeypatch):
    plot_calls = []
    fill_calls = []
    original_plot = plt.Axes.plot
    original_fill = plt.Axes.fill

    def capture_plot(axes, *args, **kwargs):
        plot_calls.append((args, kwargs.copy()))
        return original_plot(axes, *args, **kwargs)

    def capture_fill(axes, *args, **kwargs):
        fill_calls.append((args, kwargs.copy()))
        return original_fill(axes, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "plot", capture_plot)
    monkeypatch.setattr(plt.Axes, "fill", capture_fill)

    brep.render_sections_rpath(
        sections=[_open_section()],
        output_path=tmp_path / "open.png",
        columns=1,
        dpi=80,
    )

    contour_call = next(
        call for call in plot_calls if call[1].get("color") == "#9467bd"
    )
    assert list(contour_call[0][0]) == [10.0, 12.0, 14.0]
    assert list(contour_call[0][1]) == [20.0, 21.0, 20.0]
    assert contour_call[1]["linestyle"] == "--"
    assert fill_calls == []


def test_non_axis_aligned_section_uses_local_samples_2d(tmp_path, monkeypatch):
    section = _box_section(normal=(1.0, 1.0, 1.0))
    expected = np.asarray(section["contours"][0]["samples_2d"], dtype=float)
    captured = []
    original_plot = plt.Axes.plot

    def capture_plot(axes, *args, **kwargs):
        if kwargs.get("color") == "#1f77b4":
            captured.append(np.column_stack((args[0], args[1])))
        return original_plot(axes, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "plot", capture_plot)

    brep.render_sections_rpath(
        sections=[section],
        output_path=tmp_path / "oblique.png",
        columns=1,
        dpi=80,
    )

    assert captured
    assert captured[0] == pytest.approx(expected)


def test_multi_panel_preserves_input_title_order_and_column_layout(
    tmp_path, monkeypatch
):
    observed = {}
    original_savefig = plt.Figure.savefig

    def capture_savefig(figure, *args, **kwargs):
        visible_axes = [axes for axes in figure.axes if axes.get_visible()]
        observed["titles"] = [axes.get_title() for axes in visible_axes]
        observed["positions"] = [
            axes.get_subplotspec().get_geometry() for axes in visible_axes
        ]
        return original_savefig(figure, *args, **kwargs)

    monkeypatch.setattr(plt.Figure, "savefig", capture_savefig)
    titles = ["first", "second", "third"]

    brep.render_sections_rpath(
        sections=[_box_section(), _empty_section(), _open_section()],
        output_path=tmp_path / "atlas.png",
        titles=titles,
        columns=2,
        dpi=80,
    )

    assert [title.split("\n", 1)[0] for title in observed["titles"]] == titles
    assert all(geometry[:2] == (2, 2) for geometry in observed["positions"])


def test_empty_section_renders_explicit_panel(tmp_path, monkeypatch):
    observed_text = []
    original_text = plt.Axes.text

    def capture_text(axes, *args, **kwargs):
        if len(args) >= 3:
            observed_text.append(str(args[2]))
        return original_text(axes, *args, **kwargs)

    monkeypatch.setattr(plt.Axes, "text", capture_text)

    brep.render_sections_rpath(
        sections=[_empty_section()],
        output_path=tmp_path / "empty.png",
        titles=["empty-plane"],
        columns=1,
        dpi=80,
    )

    assert any("No section contours" in text for text in observed_text)


@pytest.mark.parametrize(
    ("sections", "kwargs", "message"),
    [
        ([], {}, "At least one section"),
        ([_empty_section()], {"titles": []}, "titles"),
        ([_empty_section()], {"columns": 0}, "columns"),
        ([{"compact": True, **_empty_section()}], {}, "compact"),
        (
            [{**_empty_section(), "contours": [{"closed": False}]}],
            {},
            "samples_2d",
        ),
        (
            [
                {
                    **_empty_section(),
                    "contours": [
                        {"closed": False, "samples_2d": [[0.0, math.nan], [1.0, 1.0]]}
                    ],
                }
            ],
            {},
            "finite",
        ),
    ],
)
def test_invalid_section_render_inputs_fail_loudly(tmp_path, sections, kwargs, message):
    with pytest.raises((TypeError, ValueError), match=message):
        brep.render_sections_rpath(
            sections=sections,
            output_path=tmp_path / "invalid.png",
            **kwargs,
        )


def test_render_closes_figure_after_save(tmp_path):
    before = set(plt.get_fignums())

    brep.render_sections_rpath(
        sections=[_box_section()],
        output_path=tmp_path / "closed.png",
        columns=1,
        dpi=80,
    )

    assert set(plt.get_fignums()) == before


def test_public_renderer_rejects_active_graph_session(tmp_path):
    with scad.GraphSession(graph_id="section-render-boundary"):
        with pytest.raises(
            RuntimeError, match="cannot run inside an active GraphSession"
        ):
            brep.render_sections_rpath(
                sections=[_empty_section()],
                output_path=tmp_path / "forbidden.png",
            )


def _box_feature_report():
    shape = BRepPrimAPI_MakeBox(10.0, 8.0, 4.0).Shape()
    report = brep.inspect_geometric_features_rdescriptor(
        model_or_path=shape,
        feature_kinds=("extrusion",),
    )
    return shape, report


def test_geometric_feature_renderer_consumes_saved_report_without_recognition(
    tmp_path, monkeypatch
):
    shape, report = _box_feature_report()
    saved = tmp_path / "feature-index.json"
    saved.write_text(json.dumps(report), encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("renderer must not rerun feature recognition")

    monkeypatch.setattr(
        "simplecadapi.inspect.brep.manufacturing.inspect_manufacturing_hints_rdescriptor",
        forbidden,
    )
    output = tmp_path / "all-features.png"
    result = brep.render_geometric_features_rpath(
        shape,
        saved,
        output,
        views=((25.0, -45.0, "isometric"),),
        image_size=(4.0, 3.0),
        dpi=80,
    )

    assert result == output
    assert output.is_file()
    assert output.stat().st_size > 0


def test_geometric_feature_renderer_rejects_stale_entity_ids(tmp_path):
    shape, report = _box_feature_report()
    report["features"][0]["highlight_entity_ids"] = ["face:9999"]

    with pytest.raises(ValueError, match="out of range"):
        brep.render_geometric_features_rpath(shape, report, tmp_path / "stale.png")


def test_feature_palette_matches_human_review_standard():
    assert FEATURE_COLORS == {
        "extrusion": pytest.approx((41 / 255, 173 / 255, 87 / 255)),
        "hole": pytest.approx((148 / 255, 61 / 255, 199 / 255)),
        "revolution": pytest.approx((6 / 255, 182 / 255, 212 / 255)),
        "loft": pytest.approx((236 / 255, 72 / 255, 153 / 255)),
        "sweep": pytest.approx((79 / 255, 70 / 255, 229 / 255)),
        "fillet": pytest.approx((239 / 255, 68 / 255, 68 / 255)),
        "chamfer": pytest.approx((242 / 255, 177 / 255, 52 / 255)),
        "sheet_metal": pytest.approx((59 / 255, 130 / 255, 246 / 255)),
        "sheet_metal_bend": pytest.approx((249 / 255, 115 / 255, 22 / 255)),
    }
