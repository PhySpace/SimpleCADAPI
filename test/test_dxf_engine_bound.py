"""dxf_engine: 尺寸绑定到模型几何 / 原生 DIMENSION / 统一检查 / 自动比例与排布 / 剖视图。

  bind    of / between / extent 由模型几何解析; 模型改了尺寸跟着改; 侧视圆柱的直径标成轮廓间的线性尺寸
  truth   声明值与实测不符 (DIM_VALUE_MISMATCH); 手填坐标不在图线上 (DIM_NOT_ATTACHED)
  whole   漏标的孔与总体尺寸被报出; 报告与 evaluate 同源
  file    DXF 里是原生 DIMENSION (GB 样式, 测量值 = 模型值), 写出后回读核对
  sheet   scale=None / anchor=None 自动; 标题栏不再有写死的内容; 字符串路径可用
  section 剖面线 / 剖切符号 / 剖视图不画虚线
"""

import tempfile
import unittest
from pathlib import Path

import ezdxf

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi.dxf_engine import DimDecl, RoughDecl, SheetDecl, SheetPlan, ViewDecl
from simplecadapi.dxf_engine.refs import RefError


def _plate(w=80.0, hole_r=3.0):
    plate = scad.make_box_rsolid(width=w, height=50.0, depth=10.0)
    holes = [scad.make_cylinder_rsolid(radius=hole_r, height=40.0, bottom_face_center=(x, y, -20.0),
                                       axis=(0, 0, 1)) for x in (-30, 30) for y in (-17, 17)]
    holes.append(scad.make_cylinder_rsolid(radius=10.0, height=40.0, bottom_face_center=(0, 0, -20.0),
                                           axis=(0, 0, 1)))
    return scad.cut_rsolid(plate, holes)


def _hole(x, y):
    return ql.faces().where(ql.and_(
        ql.prop("geom.type", "==", "CYLINDER"),
        ql.prop("geom.center.x", ">=", x - 0.1), ql.prop("geom.center.x", "<=", x + 0.1),
        ql.prop("geom.center.y", ">=", y - 0.1), ql.prop("geom.center.y", "<=", y + 0.1)))


def _full_dims():
    return [DimDecl("overall", "top", "linear", "W", extent="x"),
            DimDecl("overall", "top", "linear", "H", extent="y"),
            DimDecl("size", "top", "linear", "hx", between=(_hole(-30, 17), _hole(30, 17)), side="top"),
            DimDecl("size", "top", "linear", "hy", between=(_hole(-30, -17), _hole(-30, 17)), side="left"),
            DimDecl("size", "top", "diameter", "d_hole", of=_hole(30, 17), count=4),
            DimDecl("size", "top", "diameter", "d_bore", of=_hole(0, 0), tol=(0.021, 0.0), fit="H7"),
            DimDecl("overall", "side", "linear", "T", extent="y", side="right")]


def _sheet(part, dims, section=False, **kw):
    side = ViewDecl("side", part, (0, -1, 0), (1, 0, 0), align={"to": "top", "side": "below", "gap": 30.0},
                    **({"section": (0, 0, 0), "label": "A", "mark_in": "top"} if section else {}))
    return SheetDecl(title="Plate", dwg_no="P-1", scale=kw.pop("scale", None), front="top",
                     anchor=kw.pop("anchor", None),
                     views=[ViewDecl("top", part, (0, 0, 1), (1, 0, 0)), side], dims=dims, **kw)


def _codes(plan, severity=None):
    return [i.code for i in plan.issues() if severity is None or i.severity == severity]


def _dim(plan, name):
    return next(d for d in plan.dims if d.caption == name)


class TestBinding(unittest.TestCase):

    def test_values_are_measured_from_the_model(self):
        plan = SheetPlan(_sheet(_plate(), _full_dims())).solve()
        got = {d.caption: round(d._measured, 6) for d in plan.dims}
        self.assertEqual(got, {"W": 80.0, "H": 50.0, "hx": 60.0, "hy": 34.0, "d_hole": 6.0, "d_bore": 20.0,
                               "T": 10.0})
        texts = {r.name: r.draw["text"] for r in plan.resolved if r.kind == "dim"}
        self.assertEqual(texts["d_hole"], "4×⌀6")
        self.assertEqual(texts["d_bore"], "⌀20{+0.021|0} H7")
        self.assertEqual(texts["W"], "80")              # 默认不带参数名

    def test_dimension_follows_the_model(self):
        # 同一份声明, 模型改宽/改孔径 → 图上的数字跟着变, 不需要改任何坐标
        plan = SheetPlan(_sheet(_plate(w=96.0, hole_r=2.5), _full_dims())).solve()
        self.assertAlmostEqual(_dim(plan, "W")._measured, 96.0)
        self.assertAlmostEqual(_dim(plan, "d_hole")._measured, 5.0)

    def test_extension_lines_start_at_the_edge_nearest_the_dimension_line(self):
        plan = SheetPlan(_sheet(_plate(), _full_dims())).solve()
        dr = next(r.draw for r in plan.resolved if r.name == "W")
        bb = plan.views["top"]["bbox"]
        self.assertEqual(dr["side"], "bottom")
        for p in dr["defs"]:
            self.assertAlmostEqual(p[1], bb.y0, places=6)

    def test_side_view_cylinder_diameter_is_a_linear_dimension_with_the_sign(self):
        shaft = scad.make_cylinder_rsolid(radius=12.0, height=60.0, bottom_face_center=(0, 0, 0), axis=(1, 0, 0))
        cyl = ql.faces().where(ql.prop("geom.type", "==", "CYLINDER")).take(1)
        decl = SheetDecl(title="Shaft", dwg_no="S-1", scale=None, front="front", anchor=None,
                         views=[ViewDecl("front", shaft, (0, -1, 0), (1, 0, 0))],
                         dims=[DimDecl("size", "front", "diameter", "d", of=cyl),
                               DimDecl("overall", "front", "linear", "L", extent="x")])
        plan = SheetPlan(decl).solve()
        d = _dim(plan, "d")
        self.assertEqual((d.semantic, d._axis, d._sym), ("linear", "y", "⌀"))
        self.assertAlmostEqual(d._measured, 24.0)
        self.assertEqual(_codes(plan, "error") + _codes(plan, "warning"), [])
        # 轴线自动画出 (中心线)
        self.assertTrue(plan.center_segs)

    def test_selector_must_resolve_to_one(self):
        many = ql.faces().where(ql.prop("geom.type", "==", "CYLINDER"))
        with self.assertRaises(RefError) as cm:
            SheetPlan(_sheet(_plate(), [DimDecl("size", "top", "diameter", "d", of=many)])).solve()
        self.assertIn("exactly 1", str(cm.exception))

    def test_face_not_seen_edge_on_is_refused_with_a_reason(self):
        top_face = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "PLANE"),
                                            ql.prop("geom.center.z", ">=", 9.9))).exactly(1)
        with self.assertRaises(RefError) as cm:
            SheetPlan(_sheet(_plate(), [DimDecl("size", "top", "linear", "x",
                                                between=(top_face, (0.0, 0.0, 0.0)))])).solve()
        self.assertIn("edge-on", str(cm.exception))

    def test_declaration_needs_exactly_one_source(self):
        with self.assertRaises(ValueError):
            DimDecl("size", "top", "linear", "x")
        with self.assertRaises(ValueError):
            DimDecl("size", "top", "diameter", "d", of=object(), center=(0, 0), radius=1.0)


class TestTruthAndCompleteness(unittest.TestCase):

    def test_declared_value_that_the_geometry_does_not_measure(self):
        dims = _full_dims()
        dims[2] = DimDecl("size", "top", "linear", "hx", between=(_hole(-30, 17), _hole(30, 17)), side="top",
                          value=62.0)
        plan = SheetPlan(_sheet(_plate(), dims)).solve()
        bad = [i for i in plan.issues() if i.code == "DIM_VALUE_MISMATCH"]
        self.assertEqual(len(bad), 1)
        self.assertEqual((bad[0].severity, bad[0].data["declared"], bad[0].data["measured"]), ("error", 62.0, 60.0))
        self.assertEqual(next(r.draw["text"] for r in plan.resolved if r.name == "hx"), "60")

    def test_typed_point_off_the_figure_is_reported_with_the_nearest_point(self):
        dims = [DimDecl("size", "top", "linear", "w", p1=(-40.0, -25.0), p2=(38.0, -25.0), side="bottom")]
        plan = SheetPlan(_sheet(_plate(), dims)).solve()
        na = [i for i in plan.issues() if i.code == "DIM_NOT_ATTACHED"]
        self.assertEqual(len(na), 0)                    # (38,-25) 在底边上: 在图线上, 只是不是端点
        dims = [DimDecl("size", "top", "linear", "w", p1=(-40.0, -25.0), p2=(38.0, -27.0), side="bottom")]
        plan = SheetPlan(_sheet(_plate(), dims)).solve()
        na = [i for i in plan.issues() if i.code == "DIM_NOT_ATTACHED"]
        self.assertEqual(len(na), 1)
        self.assertAlmostEqual(na[0].data["distance"], 2.0, places=6)

    def test_missing_hole_and_overall_sizes_are_reported(self):
        plan = SheetPlan(_sheet(_plate(), [DimDecl("overall", "top", "linear", "W", extent="x")])).solve()
        issues = plan.issues()
        cyl = sorted(i.data["diameter"] for i in issues if i.code == "UNDIMENSIONED_CYLINDER")
        self.assertEqual(cyl, [6.0, 20.0])
        self.assertEqual(next(i.data["count"] for i in issues
                              if i.code == "UNDIMENSIONED_CYLINDER" and i.data["diameter"] == 6.0), 4)
        sizes = sorted(round(i.data["size"], 6) for i in issues if i.code == "OVERALL_SIZE_MISSING")
        self.assertEqual(sizes, [10.0, 50.0])

    def test_complete_sheet_has_no_errors_or_warnings(self):
        plan = SheetPlan(_sheet(_plate(), _full_dims())).solve()
        self.assertEqual(_codes(plan, "error") + _codes(plan, "warning"), [])

    def test_report_and_evaluation_say_the_same(self):
        # 两个尺寸量同一段、声明在同一行: 必有冲突或挪位; 报告的 R1 与 evaluate 的 warn 数必须一致
        dims = [DimDecl("size", "top", "diameter", "a", of=_hole(30, 17)),
                DimDecl("size", "top", "diameter", "b", of=_hole(30, 17), at=45.0)]
        plan = SheetPlan(_sheet(_plate(), dims)).solve()
        n_warn = plan.evaluate()["n_warn"]
        r1 = [i for i in plan.issues() if i.rule == "R1" and i.severity == "warning"]
        self.assertEqual(n_warn == 0, len(r1) == 0)
        self.assertIn("DUPLICATE_DIMENSION", _codes(plan))
        self.assertIn("Not checked", plan.report())


class TestFile(unittest.TestCase):

    def _render(self, decl, td):
        plan = SheetPlan(decl).solve()
        out = plan.render(str(Path(td) / "s.dxf"), str(Path(td) / "s.png"))       # str paths
        return plan, out, ezdxf.readfile(Path(td) / "s.dxf")

    def test_native_dimensions_measure_what_the_model_measures(self):
        with tempfile.TemporaryDirectory() as td:
            plan, out, doc = self._render(_sheet(_plate(), _full_dims(), scale=0.5), td)
            dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"]
            self.assertEqual(len(dims), 7)
            self.assertEqual(out["issues"], [])
            style = doc.dimstyles.get("GB")
            self.assertAlmostEqual(style.dxf.dimlfac, 2.0)          # 1:2 的图, CAD 量出的仍是实物尺寸
            got = sorted(round(abs(e.get_measurement()) * style.dxf.dimlfac, 4) for e in dims)
            self.assertEqual(got, [6.0, 10.0, 20.0, 34.0, 50.0, 60.0, 80.0])
            self.assertTrue(all(e.dxf.dimstyle == "GB" and doc.blocks.get(e.dxf.geometry) is not None
                                for e in dims))
            self.assertTrue((Path(td) / "s.png").stat().st_size > 0)

    def test_readback_catches_a_wrong_picture(self):
        from simplecadapi.dxf_engine.render import verify_dxf
        with tempfile.TemporaryDirectory() as td:
            plan, out, doc = self._render(_sheet(_plate(), _full_dims()), td)
            handles = {}
            for e in doc.modelspace():
                if e.dxftype() == "DIMENSION" and abs(e.dxf.actual_measurement - 80.0) < 1e-9:
                    handles["W"] = e.dxf.handle
                    for t in doc.blocks.get(e.dxf.geometry):
                        if t.dxftype() == "TEXT":
                            t.dxf.text = "81"
            doc.saveas(Path(td) / "s.dxf")
            bad = [i for i in verify_dxf(plan, Path(td) / "s.dxf", handles) if i.element == "dim:W"]
            self.assertEqual([i.code for i in bad], ["DIM_RENDER_MISMATCH"])

    def test_title_block_holds_only_what_was_declared(self):
        with tempfile.TemporaryDirectory() as td:
            _plan, _out, doc = self._render(_sheet(_plate(), _full_dims(), designer="Li", material="45"), td)
            texts = {e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"}
            self.assertIn("Li", texts)
            self.assertIn("45", texts)
            self.assertFalse({"GLM-Agent", "PLA-CF / PAHT"} & texts)


class TestSheetAndSection(unittest.TestCase):

    def test_scale_and_position_are_chosen(self):
        plan = SheetPlan(_sheet(_plate(), _full_dims(), sheet="A4")).solve()
        self.assertEqual(plan.s, 1.0)
        fx0, fy0, fx1, fy1 = plan.fmt.free
        for vw in plan.views.values():
            bb = vw["bbox"]
            self.assertTrue(fx0 <= bb.x0 and bb.x1 <= fx1 and fy0 <= bb.y0 and bb.y1 <= fy1)
        big = scad.make_box_rsolid(width=900.0, height=400.0, depth=50.0)
        plan = SheetPlan(SheetDecl(title="B", dwg_no="B-1", scale=None, front="top", anchor=None,
                                   views=[ViewDecl("top", big, (0, 0, 1), (1, 0, 0))])).solve()
        self.assertEqual(plan.s, 0.2)

    def test_too_large_a_declared_scale_is_an_error_with_a_way_out(self):
        plan = SheetPlan(_sheet(_plate(), _full_dims(), scale=5.0)).solve()
        bad = [i for i in plan.issues() if i.code == "VIEW_OUTSIDE_FRAME"]
        self.assertTrue(bad)
        self.assertIn("scale=None", bad[0].hint)

    def test_gap_is_the_clear_distance_between_views(self):
        plan = SheetPlan(_sheet(_plate(), [])).solve()
        self.assertAlmostEqual(plan.views["top"]["bbox"].y0 - plan.views["side"]["bbox"].y1, 30.0, places=6)

    def test_section_view(self):
        with tempfile.TemporaryDirectory() as td:
            plan = SheetPlan(_sheet(_plate(), _full_dims(), section=True)).solve()
            sec = plan.views["side"]
            self.assertEqual(len(sec["hatch"]), 2)                 # 中心孔两侧各一块剖面
            self.assertTrue(all(vis for _ad, _pts, vis in sec["edges"]))   # 剖视图不画虚线
            self.assertEqual(plan.section_marks[0]["title"], "A-A")
            self.assertEqual(plan.section_marks[0]["traces"][0]["view"], "top")
            plan.render(Path(td) / "s.dxf", Path(td) / "s.png")
            doc = ezdxf.readfile(Path(td) / "s.dxf")
            self.assertEqual(sum(1 for e in doc.modelspace() if e.dxftype() == "HATCH"), 1)
            self.assertEqual(_codes(plan, "error"), [])

    def test_centre_lines_come_from_the_model_and_stop_at_text(self):
        with tempfile.TemporaryDirectory() as td:
            plan = SheetPlan(_sheet(_plate(), _full_dims())).solve()
            crosses = [s for s in plan.center_segs if s[0] == "top"]
            self.assertEqual(len(crosses), 10)                     # 5 个孔, 每孔一横一竖
            plan.render(Path(td) / "s.dxf", Path(td) / "s.png")
            doc = ezdxf.readfile(Path(td) / "s.dxf")
            from simplecadapi.dxf_engine.collide import seg_hits_obb
            for e in doc.modelspace():
                if e.dxftype() == "LINE" and e.dxf.layer == "05_CENTER":
                    p, q = e.dxf.start, e.dxf.end
                    for _k, cx, cy, w, h, rot in plan.text_obbs:
                        self.assertFalse(seg_hits_obb((p.x, p.y), (q.x, q.y), cx, cy, w, h, rot, pad=0.0))

    def test_roughness_symbol_stands_on_the_referenced_surface(self):
        part = _plate()
        top_face = ql.faces().where(ql.and_(ql.prop("geom.type", "==", "PLANE"),
                                            ql.prop("geom.center.z", ">=", 9.9))).exactly(1)
        decl = _sheet(part, _full_dims(), roughs=[RoughDecl("side", on=top_face, text="Ra 1.6")])
        plan = SheetPlan(decl).solve()
        g = next(r.draw for r in plan.resolved if r.kind == "rough")
        self.assertAlmostEqual(g["strokes"][0][1][1], plan.views["side"]["bbox"].y1, places=6)   # 尖端在上表面线上
        self.assertTrue(g["readable"])


if __name__ == "__main__":
    unittest.main()
