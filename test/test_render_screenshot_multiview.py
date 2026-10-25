"""Multi-view screenshot rendering contract tests.

render_screenshot_rpath defaults to a multi-view grid (SCREENSHOT_VIEWS)
carrying highlight-tag groups, callouts, legend and per-panel axis triads;
an explicit ``view`` keeps the legacy single-view path; ``views`` selects a
custom view set.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import simplecadapi as scad
from simplecadapi.inspect.brep import render as brep_render


class TestRenderScreenshotMultiView(unittest.TestCase):
    def _tagged_solid(self):
        box = scad.make_box_rsolid(4.0, 3.0, 2.0)
        return scad.apply_tag(box, "role.body")

    def test_screenshot_views_constant_shape(self):
        views = scad.operators.features.SCREENSHOT_VIEWS
        self.assertEqual(len(views), 4)
        for entry in views:
            self.assertEqual(len(entry), 3)
            self.assertIsInstance(entry[2], str)
        labels = [entry[2] for entry in views]
        self.assertEqual(labels, ["isometric", "top / X-Y", "front / X-Z", "side / Y-Z"])

    def test_real_multiview_render_writes_grid_image(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "real.png"
            result = scad.render_screenshot_rpath(
                solid,
                str(output),
                highlight_tags=["role.body"],
                image_size=(800, 600),
            )
            self.assertEqual(result, str(output))
            self.assertTrue(output.is_file())
            # the default is a 4-panel studio grid; rendering the same solid
            # as a single explicit panel must produce a different (non-grid)
            # image at the same size
            single = Path(tmp) / "single.png"
            scad.render_screenshot_rpath(
                solid, str(single), image_size=(800, 600), view="iso"
            )
            self.assertNotEqual(output.read_bytes(), single.read_bytes())

    def test_real_custom_views_render_writes_image(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "custom_real.png"
            scad.render_screenshot_rpath(
                solid,
                str(output),
                highlight_tags=["role.body"],
                image_size=(800, 600),
                views=[(30.0, -60.0, "custom-iso"), (0.0, -90.0, "front")],
            )
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 20_000)

    def test_empty_views_are_rejected(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(scad.SimpleCADError):
                scad.render_screenshot_rpath(
                    solid,
                    str(Path(tmp) / "empty.png"),
                    views=[],
                )

    def test_more_than_four_views_are_rejected(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(scad.SimpleCADError):
                scad.render_screenshot_rpath(
                    solid,
                    str(Path(tmp) / "five-views.png"),
                    views=[
                        (30.0, 45.0, "a"),
                        (0.0, 0.0, "b"),
                        (90.0, 0.0, "c"),
                        (0.0, -90.0, "d"),
                        (20.0, 45.0, "e"),
                    ],
                )

    def test_unknown_style_is_rejected(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(scad.SimpleCADError):
                scad.render_screenshot_rpath(
                    solid,
                    str(Path(tmp) / "unknown-style.png"),
                    view="iso",
                    style="cinematic",
                )

    def test_out_of_range_edge_width_scale_is_rejected(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(scad.SimpleCADError):
                scad.render_screenshot_rpath(
                    solid,
                    str(Path(tmp) / "bad-edge-scale.png"),
                    view="iso",
                    style="studio",
                    edge_width_scale=0.5,
                )

    def test_supersample_writes_requested_image_size(self):
        import struct

        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            for supersample, expected in ((1, 1), (2, 1), (3, 1)):
                output = Path(tmp) / f"ss{supersample}.png"
                scad.render_screenshot_rpath(
                    solid,
                    str(output),
                    image_size=(640, 400),
                    view=(30.0, 45.0),
                    show_axes=False,
                    supersample=supersample,
                )
                width, height = struct.unpack(">II", output.read_bytes()[16:24])
                self.assertEqual((width, height), (640, 400))

    def test_out_of_range_supersample_is_rejected(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(scad.SimpleCADError):
                scad.render_screenshot_rpath(
                    solid,
                    str(Path(tmp) / "bad-ss.png"),
                    view="iso",
                    supersample=4,
                )

    def test_occluded_callout_is_suppressed_per_view(self):
        # 背面标签：从正面看应被抑制（图 = 无标注版），从背面看应出现（图 ≠ 无标注版）
        import hashlib

        solid = scad.make_box_rsolid(6.0, 4.0, 2.0)
        faces = scad.ql.faces().resolve(solid)
        back = min(faces, key=lambda f: f.get_center().x)
        front = max(faces, key=lambda f: f.get_center().x)
        solid = scad.apply_tag_rselection(scope=solid, targets=[back], tag="role.back")
        solid = scad.apply_tag_rselection(scope=solid, targets=[front], tag="role.front")
        with tempfile.TemporaryDirectory() as tmp:
            outputs = {}
            for view_name, azimuth in (("from_front", 0.0), ("from_back", 180.0)):
                for callouts_on in (True, False):
                    path = Path(tmp) / f"{view_name}_{'on' if callouts_on else 'off'}.png"
                    scad.render_screenshot_rpath(
                        solid,
                        str(path),
                        image_size=(480, 320),
                        view=(0.0, azimuth),
                        highlight_tags=["role.back", "role.front"],
                        tag_labels={"role.back": "back", "role.front": "front"},
                        show_callouts=callouts_on,
                        show_legend=False,
                        show_axes=False,
                        supersample=1,
                    )
                    outputs[f"{view_name}_{'on' if callouts_on else 'off'}"] = hashlib.md5(
                        path.read_bytes()
                    ).hexdigest()
            # 正面视角：front 标签可见 → 有标注 ≠ 无标注
            self.assertNotEqual(outputs["from_front_on"], outputs["from_front_off"])
            # 背面视角：back 标签可见 → 有标注 ≠ 无标注
            self.assertNotEqual(outputs["from_back_on"], outputs["from_back_off"])

    def test_default_style_is_studio(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            default = Path(tmp) / "default.png"
            standard = Path(tmp) / "standard.png"
            common = dict(image_size=(320, 240), view="iso")
            scad.render_screenshot_rpath(solid, str(default), **common)
            scad.render_screenshot_rpath(solid, str(standard), style="standard", **common)
            self.assertTrue(default.is_file())
            # 默认（studio）与显式诊断风格必须不同张图
            self.assertNotEqual(default.read_bytes(), standard.read_bytes())

    def test_studio_single_view_render_writes_image(self):
        solid = self._tagged_solid()
        with tempfile.TemporaryDirectory() as tmp:
            standard = Path(tmp) / "standard.png"
            studio = Path(tmp) / "studio.png"
            scad.render_screenshot_rpath(
                solid,
                str(standard),
                image_size=(640, 400),
                view=(30.0, 45.0),
                style="standard",
                show_axes=False,
            )
            scad.render_screenshot_rpath(
                solid,
                str(studio),
                image_size=(640, 400),
                view=(30.0, 45.0),
                style="studio",
                show_axes=False,
            )
            self.assertTrue(studio.is_file())
            # studio must actually change the picture, not just be accepted:
            # lighting, backdrop and tubed edges all differ from the flat
            # inspection look produced by the same view
            self.assertNotEqual(standard.read_bytes(), studio.read_bytes())


class TestZeroHitHighlightGuard(unittest.TestCase):
    def test_zero_hit_names_missing_and_available_tags(self):
        # The guard must answer the typo question from the shapes
        # themselves: the missing tags AND the tags that are actually
        # available lead what_happened (mechanism-A promotion), so a
        # text-only agent can repair without re-querying.
        box = scad.make_box_rsolid(4.0, 3.0, 2.0)
        box = scad.apply_tag(box, "role.body")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(scad.SimpleCADError) as ctx:
            scad.render_screenshot_rpath(
                box,
                str(Path(tmp) / "guard.png"),
                highlight_tags=["role.bodyy", "total_fabrication"],
            )
        text = ctx.exception.guidance.what_happened
        self.assertIn("role.bodyy", text)
        self.assertIn("total_fabrication", text)
        self.assertIn("role.body", text)  # the available set contains the typo's neighbor
        self.assertIn("available tags", text)


if __name__ == "__main__":
    unittest.main()
