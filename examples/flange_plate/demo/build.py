#!/usr/bin/env python3
"""Rebuild the flange_plate replay demo with demo_kit.

Run from the repository root:

    python3 examples/flange_plate/demo/build.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # demo/
ROOT = HERE.parent                              # flange_plate/
KIT = ROOT.parent / "demo_kit"
sys.path.insert(0, str(KIT))

from build_demo import build_case  # noqa: E402

build_case({
    "root": ROOT,
    "stl": {
        "path": ROOT / "out" / "flange_plate.stl",
        "name": "flange_plate.stl",
        "note": "7,266 三角面 · 最终 8 孔 @PCD 84.5",
        "gl_cap": "flange_plate 终态 · 8 孔 @PCD 84.5（第 2 轮改参后交付）· 会话自动导出（scadpkg / STEP AP242 / STL）",
    },
    "imgs": [
        {"key": "iso", "path": ROOT / "out" / "render_iso.png", "cap": "终版 · 8 孔 @PCD 84.5 · 等轴"},
        {"key": "top", "path": ROOT / "out" / "render_top.png", "cap": "终版 · 俯视（45° 均布）"},
        {"key": "detail", "path": ROOT / "out" / "render_detail.png", "cap": "终版 · 螺栓孔 + 根部圆角特写"},
    ],
    "params": [
        ["flange_od", "100 mm", "法兰盘外径"],
        ["flange_t", "10 mm", "法兰盘厚度"],
        ["boss_od / boss_top_z", "55 / 30 mm", "中心凸台外径 / 顶面高度"],
        ["bore_d", "30 mm", "中心通孔直径"],
        ["bolt_count", "8", "螺栓孔数（USER 第 2 轮 6 → 8）"],
        ["bolt_pcd", "84.5 mm", "分布圆直径（78 → 88 被守卫拒 → 85 相切排除 → 84.5）"],
        ["bolt_d", "11 mm", "螺栓通孔直径（≈M10+1 间隙）"],
        ["boss_fillet_r", "3 mm", "凸台根部圆角"],
        ["edge_fillet_r", "2 mm", "法兰外缘上下圆角"],
        ["min_edge_web", "2 mm", "轮辐宽下限 + 禁与 edge_fillet_r 相切（实测发现的第三守卫条款）"],
    ],
    "tags": [
        "fillet.boss_root",
        "fillet.flange_edge",
    ],
    "tags_note": "圆角生成面携带确定性标签：改参（6→8 孔、PCD 78→84.5）后选择仍按标签命中，不依赖拓扑序号。",
    "artifacts": {
        "files": [
            ["flange_plate.scadpkg", "4.37 MB", "SimpleCAD 原生产品包 · 新进程重开校验通过"],
            ["flange_plate.step", "53 KB", "STEP AP242DIS"],
            ["flange_plate.stl", "363 KB", "7,266 三角面 · 单实体"],
            ["render_*.png", "×4", "等轴 / 正视 / 俯视 / 孔+圆角特写"],
        ],
        "scripts": [
            "verify", "verify/s2_verify", "verify/s3_guard_evidence",
        ],
        "notes": [
            "改参守卫链：PCD 88 拒（轮辐 0.5<2）· 85 相切排除 · 84.5 交付",
            "体积/圆角环量按解析公式逐位对账（Pappus）",
        ],
    },
    "about": [
        "<b>这是什么。</b>一个按 single-part-modeling 工作流完整走完的建模会话回放：Role 1 需求确认 → Role 2 总体规划 → Role 3/4 逐阶段「先验证契约、后建模」→ Role 5 导出。Agent 在 {tools} 次工具调用中交付一个几何体素路线的参数化法兰盘。",
        "<b>左侧对话</b>逐条回放全部 {N} 条消息（用户输入 / 思考 / 工具调用输入输出 / 补丁 / 角色切换），与 session_transcript.md 一一对应，未做删改。",
        "<b>看点在第 2 轮用户输入</b>：客户把 6 孔改成 8 孔并把 PCD 拉到 88 —— 参数守卫当场拒绝（轮辐宽不足），上确界 85 因圆角相切被排除，最终以 0.5 mm 网格取到严格可行最大值 84.5 交付。参数化不是口号，是被验证器守住的合同。",
        "<b>右侧 3D 与渲染图为终态</b>（第 2 轮改参后的 8 孔交付）；渲染图第一张是第 1 轮需求的 6 孔初版，两图对照即本次改参的几何效果。3D 模型（{stlName}，{stlTris} 三角面）由 three.js 实时渲染，可拖拽旋转 / 缩放 / 平移。",
    ],
    "highlights": "① 每阶段先写验证契约再建模（{allPass} 次 ALL PASS）；② 圆角生成面带确定性标签，改参后仍可按标签选择；③ 守卫拒绝链 + 解析体积对账保证改参安全；④ 选边卡（QL resolve）在每次圆角前打印在案。",
    "subtitle": "· 参数化改参 + 守卫拒绝链演示",
    "extra_stat": ["8 孔", "终态螺栓孔（6→8 改参交付）"],
})
