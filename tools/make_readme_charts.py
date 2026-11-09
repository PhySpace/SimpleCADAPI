#!/usr/bin/env python3
"""Draw the two comparison charts of the README (img/benchmark/*.svg) from the numbers below.

    python tools/make_readme_charts.py

The numbers are copied from the evaluation reports; to relabel a case or add one, change DATA and run it again.
The SVGs carry their own light card, so they read the same on GitHub's light and dark themes.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "img" / "benchmark"

INK, MUTED, GRID, CARD, SCA, OTHER = "#16181d", "#5b6270", "#e4e7ec", "#ffffff", "#e8590c", "#a3aab8"
FONT = "-apple-system, 'Segoe UI', 'Helvetica Neue', Arial, 'PingFang SC', 'Noto Sans CJK SC', sans-serif"

# ---- the data ------------------------------------------------------------------------------------------------------
# Same model (DeepSeek-V4.1-Flash), same prompt, same 200 parts, one attempt, one frozen scorer.
# SimpleCADAPI 2.2.7b1 against CadQuery 2.8.0.  (report: SimpleCADAPI vs CadQuery, testset200, sections 5 and 6)
CQ = {
    "distorted": (4.4, 15.6),  # % of delivered models with F1@1mm < 99.99 % (8/181 against 27/173)
    "error_mm": (0.00612, 2.885),  # mean Chamfer distance to the original, mm
    "delivered": (181, 173),  # valid models out of 200
}
# Tokens (millions) to finish each task, SimpleCADAPI against a mature commercial CAD driven through its MCP.
# `lower_bound`: the figure is "at least this much".  The case names are the evaluation's own ids.
MCP = [
    {"case": "S01", "sca": 3.555, "other": 14.166},
    {"case": "S05", "sca": 11.070, "other": 22.393, "lower_bound": True},
    {"case": "S06", "sca": 4.136, "other": 26.964},
    {"case": "S07", "sca": 12.072, "other": 14.880},
]
# --------------------------------------------------------------------------------------------------------------------

STR = {
    "en": {
        "cq_title": "Same model. Same prompt. Same 200 real parts. One attempt each.",
        "cq_sub": "Task: rebuild a part as parametric code from its STEP file. An independent, frozen scorer measures the result against the original.",
        "cq_other": "CadQuery",
        "p1": ("Delivered, but badly wrong", "lower is better", "3.5× fewer"),
        "p2": ("Distance from the original", "mean surface error, mm · lower is better", "472× smaller"),
        "p3": ("Valid models delivered", "out of 200 · higher is better", "+8 models"),
        "cq_foot": "SimpleCADAPI 2.2.7b1 vs CadQuery 2.8.0 · DeepSeek-V4.1-Flash · 200 open-hardware parts (2–1,384 mm) · no retries · paired test on the distorted rate: p = 0.002",
        "cq_alt": "SimpleCADAPI against CadQuery, same model and prompt on 200 parts: 3.5 times fewer badly wrong results",
        "mcp_title": "Up to 6.5× fewer tokens for the same task",
        "mcp_sub": "Tokens an agent spends on each task (millions) · SimpleCADAPI against a mature commercial CAD driven through its MCP · lower is better",
        "mcp_other": "Mature industrial CAD, through its MCP",
        "fewer": "{}× fewer",
        "fewer_bound": "≤{}× fewer",
        "mcp_foot": "≥ marks a lower bound: the figure is at least that much.",
        "mcp_alt": "Tokens spent per task, SimpleCADAPI against a mature commercial CAD through its MCP: up to 6.5 times fewer",
        "suffix": "",
    },
    "zh": {
        "cq_title": "同一个模型，同一套提示词，同样 200 个真实零件，各只试一次。",
        "cq_sub": "任务：根据 STEP 文件，用参数化代码重建零件。由独立且已冻结的评分器，把结果与原件逐一比对。",
        "cq_other": "CadQuery",
        "p1": ("交付了，但严重失真", "越低越好", "少 3.5 倍"),
        "p2": ("与原件的距离", "平均表面误差，mm · 越低越好", "小 472 倍"),
        "p3": ("交付的有效模型", "共 200 个 · 越高越好", "多 8 个"),
        "cq_foot": "SimpleCADAPI 2.2.7b1 对 CadQuery 2.8.0 · DeepSeek-V4.1-Flash · 200 个开源硬件零件（2–1,384 mm）· 不重试 · 严重失真率的配对检验 p = 0.002",
        "cq_alt": "SimpleCADAPI 对 CadQuery：同一模型、同一提示词、200 个零件，严重失真的模型少 3.5 倍",
        "mcp_title": "同样的任务，最多少用 6.5 倍 Token",
        "mcp_sub": "智能体在每个任务上消耗的 Token（百万）· SimpleCADAPI 对某成熟工业软件（经其 MCP 驱动）· 越低越好",
        "mcp_other": "某成熟工业软件（经其 MCP）",
        "fewer": "少 {} 倍",
        "fewer_bound": "至多少 {} 倍",
        "mcp_foot": "≥ 表示下界：实际数值不低于该值。",
        "mcp_alt": "每个任务消耗的 Token：SimpleCADAPI 对某成熟工业软件（经其 MCP），最多少 6.5 倍",
        "suffix": ".zh",
    },
}


def text(x, y, s, size=14, fill=INK, weight=400, anchor="start", italic=False):
    style = ' font-style="italic"' if italic else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{style}>{escape(s)}</text>'
    )


def rect(x, y, w, h, fill, rx=3):
    return f'<rect x="{x}" y="{y}" width="{max(w, 2):.1f}" height="{h}" rx="{rx}" fill="{fill}"/>'


def svg(width, height, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{escape(title)}">\n<title>{escape(title)}</title>\n'
        f'<rect width="{width}" height="{height}" rx="14" fill="{CARD}" stroke="{GRID}"/>\n' + "\n".join(body) + "\n</svg>\n"
    )


def legend(x, y, other):
    return [
        rect(x, y - 11, 14, 14, SCA, 3),
        text(x + 22, y, "SimpleCADAPI", 14, INK, 600),
        rect(x + 150, y - 11, 14, 14, OTHER, 3),
        text(x + 172, y, other, 14, INK, 600),
    ]


def cq_chart(lang):
    t = STR[lang]
    w, h = 1040, 430
    body = [
        text(36, 50, t["cq_title"], 24, INK, 700),
        text(36, 78, t["cq_sub"], 14, MUTED),
        *legend(36, 112, t["cq_other"]),
    ]
    panels = [
        (*t["p1"][:2], CQ["distorted"], lambda v: f"{v:.1f}%", 18.0, t["p1"][2]),
        (*t["p2"][:2], CQ["error_mm"], lambda v: f"{v:.3f} mm", 3.2, t["p2"][2]),
        (*t["p3"][:2], CQ["delivered"], lambda v: f"{v:.0f}", 200.0, t["p3"][2]),
    ]
    px, pw, gap, top = 36, 308, 30, 150
    for i, (title, sub, (a, b), fmt, top_value, callout) in enumerate(panels):
        x0 = px + i * (pw + gap)
        body += [
            text(x0, top, title, 16, INK, 700),
            text(x0, top + 20, sub, 12.5, MUTED),
            f'<line x1="{x0}" y1="{top + 38}" x2="{x0 + pw}" y2="{top + 38}" stroke="{GRID}"/>',
        ]
        barmax = pw - 96
        for j, (value, colour) in enumerate(((a, SCA), (b, OTHER))):
            y = top + 62 + j * 62
            body += [rect(x0, y, barmax * value / top_value, 34, colour, 4), text(x0 + 6 + barmax * value / top_value, y + 23, fmt(value), 17, INK, 700)]
        body.append(text(x0, top + 218, callout, 30, SCA, 800))
    body.append(text(36, 400, t["cq_foot"], 12.5, MUTED))
    return svg(w, h, body, t["cq_alt"])


def mcp_chart(lang):
    t = STR[lang]
    w, h = 1040, 520
    top_value = 30.0
    body = [
        text(36, 50, t["mcp_title"], 24, INK, 700),
        text(36, 78, t["mcp_sub"], 14, MUTED),
        *legend(36, 112, t["mcp_other"]),
    ]
    left, right, y0 = 120, w - 150, 140
    scale = (right - left) / top_value
    for tick in range(0, int(top_value) + 1, 10):
        x = left + tick * scale
        body += [f'<line x1="{x}" y1="{y0 - 6}" x2="{x}" y2="{y0 + 4 * 74 + 4}" stroke="{GRID}"/>', text(x, y0 + 4 * 74 + 26, f"{tick} M", 12.5, MUTED, 400, "middle")]
    for i, row in enumerate(MCP):
        y = y0 + i * 74
        ratio = row["other"] / row["sca"]
        body.append(text(36, y + 36, row["case"], 20, INK, 700))
        sw, ow = row["sca"] * scale, row["other"] * scale
        label = f'{"≥" if row.get("lower_bound") else ""}{row["sca"]:.2f}'
        body.append(rect(left, y + 4, sw, 28, SCA, 4))
        if row.get("lower_bound"):  # an open end: at least this much
            body.append(f'<path d="M{left + sw:.1f} {y + 4} l10 14 l-10 14" fill="none" stroke="{SCA}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
        body.append(text(left + sw + (20 if row.get("lower_bound") else 8), y + 24, label, 15, INK, 700))
        body.append(rect(left, y + 38, ow, 28, OTHER, 4))
        body.append(text(left + ow + 8, y + 58, f'{row["other"]:.2f}', 15, INK, 700))
        note = t["fewer_bound" if row.get("lower_bound") else "fewer"].format(f"{ratio:.1f}")  # a lower bound on our side caps the ratio
        body.append(text(w - 36, y + 36, note, 20, SCA, 800, "end"))
    body.append(text(36, 496, t["mcp_foot"], 12.5, MUTED))
    return svg(w, h, body, t["mcp_alt"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, t in STR.items():
        (OUT / f"vs_cadquery{t['suffix']}.svg").write_text(cq_chart(lang), encoding="utf-8")
        (OUT / f"vs_industrial_mcp{t['suffix']}.svg").write_text(mcp_chart(lang), encoding="utf-8")
    print("wrote", *sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
