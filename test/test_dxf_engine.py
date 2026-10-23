"""dxf_engine 单元测试: 1-DOF 标注模型 / 引出线修复 / 自动诊断图 / 确定性。

覆盖 (按实现分组):
  rad   定向后文字仅剩沿线 1 自由度 —— 弧外/弧内候选、基线恒在线上方、
        引线派生延长、rot 恒等线向 (R2, 动作不可覆盖)、箭头随内外侧翻转
  lin   slide 沿尺寸线滑移、文字滑出测量段时尺寸线自动侧延长、
        窄跨度直接界外 + 延长
  dia   insert(基线锚) 与 anchor(OBB 中心) 分离, 动作换位重算
  lead  多行引出肘点上移到框顶上方 / 无空位兜底不崩 / 引线压文本不再 NameError
  diag  SheetDecl.diag_png 声明后 solve/apply 自动刷新诊断图 + 返回阅读指令
  misc  position 无基准 fail-fast (R6); R5 参数表兜底; 双次渲染确定性
"""

import hashlib
import math
import tempfile
import unittest
from pathlib import Path

import simplecadapi as scad
from simplecadapi.dxf_engine import (DimDecl, LeaderDecl, SheetDecl, SheetPlan,
                                     ViewDecl)
from simplecadapi.dxf_engine.planner import TEXT_H, _text_width

ANCHOR = (200.0, 200.0)          # front 视图锚: 模型 (x,y) → 纸面 (200+x, 200+y)
W = 30.0                          # 盒宽 → front 视图 x∈[-15,15]


def _box() -> scad.Solid:
    return scad.make_box_rsolid(width=W, height=20.0, depth=10.0)


def _sheet(dims=None, leaders=None, notes_zone=(25.0, 5.0, 232.0, 90.0),
           **decl_kw):
    return SheetDecl(
        title="T", dwg_no="T-000", scale=1.0, front="front", anchor=ANCHOR,
        views=[ViewDecl("front", _box().wrapped, (0, 0, 1), (1, 0, 0),
                        anchor=ANCHOR)],
        dims=dims or [], leaders=leaders or [], notes_zone=notes_zone,
        **decl_kw)


def _rad(plan, caption="r"):
    return next(r for r in plan.resolved
                if r.kind == "dim" and r.name == caption).draw


def _lin(plan, caption):
    return next(r for r in plan.resolved
                if r.kind == "dim" and r.name == caption).draw


def _norm_rot(at):
    rot = (at % 180.0 + 180.0) % 180.0
    return rot - 180.0 if rot > 90.0 else rot


class TestRadOneDOF(unittest.TestCase):
    """半径: at 定向后 1-DOF; 弧外→弧内候选; 基线/中心/延长全派生。"""

    def test_outer_geometry_contract(self):
        at, c, r = 30.0, (0.0, 10.0), 8.0
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "radius", "r", center=c, radius=r,
                    value=r, at=at)])).solve()
        dr = _rad(plan)
        u = (math.cos(math.radians(at)), math.sin(math.radians(at)))
        rot = _norm_rot(at)
        n = (-math.sin(math.radians(rot)), math.cos(math.radians(rot)))
        cc = (ANCHOR[0] + c[0], ANCHOR[1] + c[1])
        mpt = (cc[0] + r * u[0], cc[1] + r * u[1])
        w = _text_width(dr["text"], TEXT_H)
        s = 3.0                                    # 无冲突 → 首候选
        insert = (mpt[0] + s * u[0] + n[0], mpt[1] + s * u[1] + n[1])
        anchor = (insert[0] + u[0] * w / 2 + n[0] * TEXT_H * 0.35,
                  insert[1] + u[1] * w / 2 + n[1] * TEXT_H * 0.35)
        tail = (mpt[0] + (s + w + 1.5) * u[0], mpt[1] + (s + w + 1.5) * u[1])
        for key, want in (("mpt", mpt), ("insert", insert), ("anchor", anchor),
                          ("tail", tail)):
            self.assertAlmostEqual(dr[key][0], want[0], places=6, msg=key)
            self.assertAlmostEqual(dr[key][1], want[1], places=6, msg=key)
        self.assertAlmostEqual(dr["rot"], rot, places=6)
        # 弧外: 箭头自外指向圆弧; 引线长度覆盖全文 (侧延长派生)
        self.assertAlmostEqual(dr["arrow_deg"],
                               math.degrees(math.atan2(u[1], u[0])) + 180.0,
                               places=6)
        self.assertGreater(math.dist(mpt, dr["tail"]), w)

    def test_inner_variant_via_action(self):
        at, c, r = 60.0, (0.0, 10.0), 8.0
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "radius", "r", center=c, radius=r,
                    value=r, at=at)])).solve()
        w = _text_width(_rad(plan)["text"], TEXT_H)
        res = plan.apply([{"op": "rad", "name": "r", "s": -(w + 4.0)}])
        self.assertTrue(res["results"][0]["ok"], res["results"][0])
        dr = _rad(plan)
        u = (math.cos(math.radians(at)), math.sin(math.radians(at)))
        cc = (ANCHOR[0] + c[0], ANCHOR[1] + c[1])
        mpt = (cc[0] + r * u[0], cc[1] + r * u[1])
        # 弧内: 引线自弧向圆心侧延伸, 箭头自圆心侧指弧 (无 +180 翻转)
        self.assertLess(dr["tail"][0] * u[0] + dr["tail"][1] * u[1],
                        mpt[0] * u[0] + mpt[1] * u[1])
        self.assertAlmostEqual(dr["arrow_deg"],
                               math.degrees(math.atan2(u[1], u[0])), places=6)
        r_res = next(x for x in plan.resolved if x.name == "r")
        self.assertIn("inside the arc", r_res.resolved)

    def test_solver_falls_back_inner_when_outer_blocked(self):
        # 圆心沉入 notes 禁入区下方: at=270° 弧外候选全部进禁入区,
        # 弧内候选(过圆心向上)干净 → solver 应自动选弧内
        c = (0.0, -115.0)                           # 纸面圆心 (200, 85)
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "radius", "r", center=c, radius=8.0,
                    value=8.0, at=270.0)])).solve()
        r_res = next(x for x in plan.resolved if x.name == "r")
        self.assertIn("inside the arc", r_res.resolved, r_res.resolved)
        self.assertIn("slide", "".join(r_res.adjust))

    def test_rot_is_line_direction_not_overridable(self):
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "radius", "r", center=(0, 10),
                    radius=8.0, value=8.0, at=30.0)])).solve()
        res = plan.apply([{"op": "rad", "name": "r", "at": 50.0,
                           "rot": 77.0, "out": 99.0}])
        self.assertTrue(res["results"][0]["ok"])
        self.assertAlmostEqual(_rad(plan)["rot"], _norm_rot(50.0), places=6)


class TestLinearSlide(unittest.TestCase):
    """线性: side/row 结构位 + slide 沿线 1-DOF; 侧延长派生。"""

    def test_mid_default_not_extended(self):
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "linear", "w", value=20.0,
                    p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom",
                    row=0)])).solve()
        dr = _lin(plan, "w")
        yl = 190.0 - 8.0                            # bbox.y0(190) - BASE_OFF
        self.assertEqual(dr["line"], ((190.0, yl), (210.0, yl)))
        # insert=基线左端 (文字沿 +x 展开, 与渲染 set_placement 一致)
        w = _text_width(dr["text"], TEXT_H)
        self.assertAlmostEqual(dr["insert"][0], 200.0 - w / 2, places=6)
        self.assertAlmostEqual(dr["insert"][1], yl + 1.0, places=6)
        self.assertFalse(dr.get("extended", False))

    def test_slide_derived_elongation(self):
        dcl = DimDecl("size", "front", "linear", "w", value=20.0,
                      p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom", row=0)
        plan = SheetPlan(_sheet(dims=[dcl])).solve()
        text = "20 (w)"
        g = plan._lin_geometry(dcl, "bottom", 0, 25.0, text)
        w = _text_width(text, TEXT_H)
        self.assertTrue(g["extended"])
        self.assertAlmostEqual(g["center"][0], 200.0 + 25.0, places=6)
        # 正向滑移 → 文字滑出右测量点, 尺寸线右端自动侧延长覆盖全文
        self.assertGreaterEqual(g["line"][1][0], g["insert"][0] + w + 1.9)
        self.assertAlmostEqual(g["line"][0][0], 190.0, places=6)
        # 箭头仍指测量点 (滑移只动文字, 不动测量)
        yl = 190.0 - 8.0
        self.assertEqual(g["arrows"], ((190.0, yl), (210.0, yl)))

    def test_narrow_span_auto_outside(self):
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "linear", "t", value=2.0,
                    p1=(-1.0, 5.0), p2=(1.0, 5.0), side="bottom",
                    row=0)])).solve()
        dr = _lin(plan, "t")
        self.assertTrue(dr.get("extended"))
        r_res = next(x for x in plan.resolved if x.name == "t")
        self.assertTrue(any(("slid" in a or "extended" in a) for a in r_res.adjust),
                        r_res.adjust)

    def test_apply_lin_slide(self):
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "linear", "w", value=20.0,
                    p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom",
                    row=0)])).solve()
        x0 = _lin(plan, "w")["insert"][0]
        res = plan.apply([{"op": "lin", "name": "w", "slide": 14.0}])
        self.assertTrue(res["results"][0]["ok"], res["results"][0])
        self.assertAlmostEqual(_lin(plan, "w")["insert"][0], x0 + 14.0,
                               places=6)


class TestDiameterAnchors(unittest.TestCase):
    """直径: insert=基线锚(0.75r 线上方), anchor=OBB 中心; 动作换位重算。"""

    def test_anchor_split(self):
        at, c, r = 35.0, (0.0, 10.0), 8.0
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "diameter", "d", center=c, radius=r,
                    value=16.0, at=at)])).solve()
        dr = _rad(plan, "d")
        u = (math.cos(math.radians(at)), math.sin(math.radians(at)))
        rot = _norm_rot(at)
        n = (-math.sin(math.radians(rot)), math.cos(math.radians(rot)))
        cc = (ANCHOR[0] + c[0], ANCHOR[1] + c[1])
        w = _text_width(dr["text"], TEXT_H)
        insert = (cc[0] + 0.75 * r * u[0] + n[0],
                  cc[1] + 0.75 * r * u[1] + n[1])
        anchor = (insert[0] + u[0] * w / 2 + n[0] * TEXT_H * 0.35,
                  insert[1] + u[1] * w / 2 + n[1] * TEXT_H * 0.35)
        for key, want in (("insert", insert), ("anchor", anchor),
                          ("m1", (cc[0] + r * u[0], cc[1] + r * u[1])),
                          ("m2", (cc[0] - r * u[0], cc[1] - r * u[1]))):
            self.assertAlmostEqual(dr[key][0], want[0], places=6, msg=key)
            self.assertAlmostEqual(dr[key][1], want[1], places=6, msg=key)

    def test_apply_dia_at(self):
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "diameter", "d", center=(0, 10),
                    radius=8.0, value=16.0, at=35.0)])).solve()
        res = plan.apply([{"op": "dia", "name": "d", "at": 120.0}])
        self.assertTrue(res["results"][0]["ok"], res["results"][0])
        self.assertAlmostEqual(_rad(plan, "d")["rot"], _norm_rot(120.0),
                               places=6)


class TestLeaderFixes(unittest.TestCase):
    """引出线三修复: 肘点上移 / 无空位兜底 / 引线压文本不再 NameError。"""

    def test_multiline_elbow_above_box(self):
        plan = SheetPlan(_sheet(leaders=[
            LeaderDecl("front", anchor=(0, 10), lines=["一", "二"],
                       off=(40.0, 0.0), name="L")])).solve()
        dr = next(r.draw for r in plan.resolved if r.kind == "leader")
        # 肘点须在文本框顶上方 (旧实现肘线划过第二行文字)
        self.assertAlmostEqual(dr["path"][1][1], dr["text_y_top"] + 0.8,
                               places=6)
        self.assertGreater(dr["path"][1][1], dr["text_y_top"])

    def test_no_space_fallback_no_crash(self):
        # 禁入区覆盖全图 → 所有候选落空 → 兜底分支 (旧实现此处解包崩溃)
        plan = SheetPlan(_sheet(
            leaders=[LeaderDecl("front", anchor=(0, 10), lines=["x"],
                                off=(40.0, 0.0), name="L")],
            notes_zone=(25.0, 5.0, 415.0, 292.0))).solve()
        r = next(x for x in plan.resolved if x.kind == "leader")
        self.assertTrue(any("no free slot found" in a for a in r.adjust), r.adjust)

    def test_leader_seg_over_text_no_crash(self):
        # 引线段穿过已注册文本 OBB (旧实现该分支引用未定义名 kk2 → NameError)
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "linear", "h", value=20.0,
                    p1=(15.0, 0.0), p2=(15.0, 20.0), side="right", row=0)],
            leaders=[LeaderDecl("front", anchor=(0, 10), lines=["一", "二"],
                                off=(40.0, 0.0), name="L")])).solve()
        self.assertTrue(any(r.kind == "leader" for r in plan.resolved))


class TestAutoDiag(unittest.TestCase):
    """diag_png 声明后 solve/apply 自动刷新诊断图并返回阅读指令。"""

    def test_solve_writes_diag_and_report_mentions(self):
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "diag.png"
            plan = SheetPlan(_sheet(dims=[
                DimDecl("size", "front", "linear", "w", value=20.0,
                        p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom",
                        row=0)], diag_png=str(png))).solve()
            self.assertTrue(png.exists() and png.stat().st_size > 0)
            self.assertIn("diagnostic picture DIAG", plan.report())
            self.assertIn("read it before", plan.report())

    def test_apply_returns_instruction(self):
        with tempfile.TemporaryDirectory() as td:
            png = Path(td) / "diag.png"
            plan = SheetPlan(_sheet(dims=[
                DimDecl("size", "front", "linear", "w", value=20.0,
                        p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom",
                        row=0)], diag_png=str(png))).solve()
            out = plan.apply([{"op": "lin", "name": "w", "slide": 5.0}])
            self.assertEqual(out.get("diag"), str(png))
            self.assertIn("read it before", out.get("instruction", ""))


class TestMiscContracts(unittest.TestCase):

    def test_position_without_datum_fails_fast(self):
        with self.assertRaises(ValueError):
            DimDecl("position", "front", "linear", "x", value=5.0,
                    p1=(0, 0), p2=(5, 0))

    def test_r5_param_table_fallback(self):
        plan = SheetPlan(_sheet(
            dims=[DimDecl("size", "front", "linear", "w", value=20.0,
                          p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom",
                          row=0)],
            params={"w": 20.0, "unannotated": 3.0})).solve()
        cov = dict(plan.coverage)
        self.assertEqual(cov["unannotated"], "parameter table")

    def test_double_render_deterministic(self):
        import ezdxf
        plan = SheetPlan(_sheet(dims=[
            DimDecl("size", "front", "linear", "w", value=20.0,
                    p1=(-10.0, 0.0), p2=(10.0, 0.0), side="bottom", row=0),
            DimDecl("size", "front", "radius", "r", center=(0, 10),
                    radius=8.0, value=8.0, at=30.0)])).solve()
        with tempfile.TemporaryDirectory() as td:
            hashes = []
            for i in (1, 2):
                dxf, png = Path(td) / f"a{i}.dxf", Path(td) / f"a{i}.png"
                plan.render(dxf, png)
                hashes.append(hashlib.md5(png.read_bytes()).hexdigest())
                self.assertGreater(
                    len(list(ezdxf.readfile(dxf).modelspace())), 10)
            self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
