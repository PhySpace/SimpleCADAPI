"""What `render_screenshot` draws for each way of asking: the default grid, one view, a custom set of views.

(The SDK's own tests of this patch a VTK engine's internals to see which engine got the request; the native
screenshot is one renderer, so the routing is read off the frame it produced.)
"""
import pytest

pytest.importorskip("PIL")

import simplecadapi._cpp as scad
from simplecadapi._cpp.screenshot import SCREENSHOT_VIEWS, render_screenshot


def _solid():
    return scad.make_box_rsolid(4.0, 3.0, 2.0)


def _panels(tmp_path, **kwargs):
    path, frame = render_screenshot(_solid(), tmp_path / "out.png", image_size=(640, 480), return_frame=True, **kwargs)
    return [panel.label for panel in frame.panels]


def test_default_is_the_four_panel_grid(tmp_path):
    assert SCREENSHOT_VIEWS and len(SCREENSHOT_VIEWS) == 4
    assert _panels(tmp_path) == [label for _, _, label in SCREENSHOT_VIEWS]


def test_one_explicit_view_is_one_panel(tmp_path):
    assert len(_panels(tmp_path, view="iso")) == 1


def test_custom_views_are_the_grid(tmp_path):
    custom = [(30.0, -60.0, "custom-iso"), (0.0, -90.0, "front")]
    assert _panels(tmp_path, views=custom) == ["custom-iso", "front"]


def test_the_screenshot_views_are_label_triples():
    for entry in SCREENSHOT_VIEWS:
        assert len(entry) == 3 and isinstance(entry[2], str)
    assert [entry[2] for entry in SCREENSHOT_VIEWS] == ["isometric", "top / X-Y", "front / X-Z", "side / Y-Z"]
