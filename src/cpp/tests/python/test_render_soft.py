"""The software renderer through the Python module (the C++ cases live in tests/cpp/render)."""
import numpy as np
import pytest

import simplecadapi._cpp as scad


def _box():
    return scad.make_box_rsolid(10, 8, 4)


def _render(scene, **kw):
    kw.setdefault("width", 320)
    kw.setdefault("height", 240)
    kw.setdefault("supersample", 1)
    kw.setdefault("style", "standard")
    kw.setdefault("threads", 1)
    return scad.render_scene(scene, **kw)


def test_top_view_fills_a_rectangle_and_reports_ids():
    scene = scad.RenderScene()
    assert scene.add_shape(_box(), edges=False) == 0
    frame = _render(scene, views=[(90.0, 0.0, "top")])
    assert frame.rgba.shape == (240, 320, 4)
    assert frame.depth.shape == frame.face_id.shape == (240, 320)
    ids = np.unique(frame.face_id[frame.face_id >= 0])
    assert len(ids) == 1
    covered = (frame.face_id >= 0).sum()
    panel = frame.panels[0]
    (x0, y0, d0, _), (x1, y1, d1, _) = panel.project((0, 0, 4)), panel.project((10, 8, 4))
    assert covered == pytest.approx(abs(x1 - x0) * abs(y1 - y0), rel=0.02)
    assert np.isinf(frame.depth[0, 0])
    assert frame.mesh_id.max() == 0


def test_anchor_visibility_uses_the_depth_buffer():
    scene = scad.RenderScene()
    scene.add_shape(_box(), edges=False)
    frame = _render(scene, views=[(0.0, 0.0, "right")], anchors=[(5, 0, 2), (-5, 0, 2)])
    a = frame.panels[0].anchors
    assert a[0][4] is True  # +X face faces the camera
    assert a[1][4] is False  # -X face is behind the box


def test_face_colors_and_opacity():
    scene = scad.RenderScene()
    colors = np.full((6, 4), np.nan, dtype=np.float32)
    probe = scad.RenderScene()
    probe.add_shape(_box(), edges=False)
    top = int(_render(probe, views=[(90.0, 0.0, "t")]).face_id[120, 160])
    colors[top] = (0.0, 1.0, 0.0, 1.0)
    scene.add_shape(_box(), face_colors=colors, edges=False)
    px = _render(scene, views=[(90.0, 0.0, "t")]).rgba[120, 160]
    assert px[1] > 200 and px[0] < 90 and px[2] < 90


def test_deterministic_across_threads():
    scene = scad.RenderScene()
    scene.add_shape(scad.fillet_rsolid(_box(), scad.ql.edges(), 1.0))
    frames = [_render(scene, supersample=2, threads=t, views=[(28, -45, "a"), (0, 0, "b")], show_axes=True) for t in (1, 3, 8)]
    for f in frames[1:]:
        assert np.array_equal(f.rgba, frames[0].rgba)
        assert np.array_equal(f.face_id, frames[0].face_id)


def test_errors_and_edges_api():
    scene = scad.RenderScene()
    scene.add_shape(_box(), edges=False)
    with pytest.raises(ValueError):
        _render(scene, supersample=7)
    with pytest.raises(ValueError):
        _render(scene, style="neon")
    with pytest.raises(ValueError):
        scad.render_view_preset("sideways")
    pts, starts = scad.render_edge_polylines(_box())
    assert len(starts) - 1 == 12 and pts.shape[1] == 3
    assert scad.render_view_preset("iso") == (25.0, 35.0)


def test_screenshot_helper_writes_png(tmp_path):
    pytest.importorskip("PIL")
    from simplecadapi._cpp.screenshot import render_screenshot

    box = _box()
    faces = box.faces()
    scad.apply_tag(faces[0], "role.a")
    out = render_screenshot(box, tmp_path / "s.png", highlight_tags=["role.a"], image_size=(480, 320))
    from PIL import Image

    assert Image.open(out).size == (480, 320)


def test_occluded_callout_is_suppressed_per_view(tmp_path):
    """Port of test_occluded_callout_is_suppressed_per_view: the label of a face seen from behind is dropped."""
    pytest.importorskip("PIL")
    import hashlib

    from simplecadapi._cpp.screenshot import render_screenshot

    box = scad.make_box_rsolid(6.0, 4.0, 2.0)
    faces = box.faces()
    back = min(faces, key=lambda f: f.get_center().x)
    front = max(faces, key=lambda f: f.get_center().x)
    scad.apply_tag(back, "role.back")
    scad.apply_tag(front, "role.front")
    digests = {}
    for name, az in (("from_front", 0.0), ("from_back", 180.0)):
        for on in (True, False):
            path = tmp_path / f"{name}_{on}.png"
            render_screenshot(box, path, image_size=(480, 320), view=(0.0, az), highlight_tags=["role.back", "role.front"],
                              tag_labels={"role.back": "back", "role.front": "front"}, show_callouts=on, show_legend=False,
                              show_axes=False, supersample=1)
            digests[(name, on)] = hashlib.md5(path.read_bytes()).hexdigest()
    assert digests[("from_front", True)] != digests[("from_front", False)]
    assert digests[("from_back", True)] != digests[("from_back", False)]

    # the hidden face's label must not appear: only the visible tag is annotated in each view
    _, frame = render_screenshot(box, tmp_path / "x.png", image_size=(480, 320), view=(0.0, 0.0), highlight_tags=["role.back", "role.front"],
                                 show_legend=False, show_axes=False, supersample=1, return_frame=True)
    assert [a[4] for a in frame.panels[0].anchors] == [False, True]
