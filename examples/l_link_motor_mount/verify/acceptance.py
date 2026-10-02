"""Acceptance checks for the l_link body, shell, adapter plates and assemblies.

    uv run python examples/l_link_motor_mount/verify/acceptance.py [stages | guards | sweep | edges | all]

stages  Run the four notebooks with ``run_notebook`` (cell-cached; both plate presets and both assembly
        members via ``id=``) and check every stage contract of ``contracts.py`` on the cell value that
        ends the stage (``STAGES``): S1 .. S7 body / shell, S8 plates (+ fit in the body, screw picks),
        S9 strictly solved assembly per preset.
guards  Per-stage guard contracts (``check_sN_guards``) plus the whole-chain boundary matrix
        (``dimensions.check_plate``):
          G1 coverage: every numeric param, moved alone from the default, meets a guard in each direction --
             or is in FREE with a reason (periodic angles / monotone-harmless growth). Edge found by outward
             step + bisection.
          G2 binding guard: the rejection just past each edge carries the expected guard text (BINDING).
          G3 exact boundary: for each ANALYTIC end the bound is re-derived here from the requirement geometry;
             bisection edge == analytic (|d| <= 1e-6); bound -/+ 1e-6 inside accepted, outside rejected with
             the binding text; the exact bound accepted iff the guard is inclusive (>= / <=), rejected iff strict.
          G4 discrete / periodic domains: rad_screw_n in 1..6 accepted exactly {1, 3} (2 / 4 put a pilot on a
             STAR3 hole at 180); key_phase free on a 5-degree sweep of [0, 360); cable_w_phase accepted on that
             sweep exactly where |a mod 90 - 45| <= 5 (a window aimed at +X tunnels into the corner's inner
             bend -- S10 finding).
sweep   V: each VARIANTS entry (valid multi-param changes; expected radial-screw picks derived by hand) runs
        every notebook with ``overrides={"p": variant}`` (uncached) and passes the S1 .. S9 stage checks
        (S9 = both presets assembled from the variant parts and strictly solved).
edges   E: EDGES = params pinned at an accepted extreme where geometry gets tight / tangent; the same stage
        checks must pass (the guard is sufficient, not merely firing).

sweep / edges run in a process pool.  Exit status 1 on any failure.
"""
from __future__ import annotations

import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parent
EXAMPLE_DIR = HERE.parent
for _path in (HERE, EXAMPLE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import contracts as c  # noqa: E402
import dimensions as dm  # noqa: E402
from dimensions import PlatePreset  # noqa: E402

P0 = dm.params()
EPS = 1e-6

# Cell that ends each stage: (notebook, cell).  The body has no S4 (cavity / notch are shell-only).
STAGES = {
    "s1": (("body", "l_rod"),),
    "s2": (("body", "motor_pockets"),),
    "s3": (("body", "l_split"), ("shell", "shell_region")),
    "s4": (("shell", "cable_notch"),),
    "s5": (("body", "boss_holes"), ("shell", "csink_holes")),
    "s6": (("body", "cap_rim_fillet"), ("shell", "rim_name")),
    "s7": (("body", "mount_face_names"),),
    "s8": (("plate", "plate_face_names"),),
}


def run_all(p: dict | None = None) -> SimpleNamespace:
    """Run every notebook; p=None: defaults, cell-cached; else p overrides the params cell, uncached.

    The assemblies get the variant parts by overriding their ``body, plate, shell`` cell."""
    cache = p is None
    over = {} if p is None else {"p": p}
    body = run_notebook(EXAMPLE_DIR / "l_link.py", overrides=over, cache=cache)
    shell = run_notebook(EXAMPLE_DIR / "shell.py", overrides=over, cache=cache)
    plates, assemblies = {}, {}
    for preset in PlatePreset:
        plate = run_notebook(EXAMPLE_DIR / "adapter_plate.py", id=dm.plate_part_id(preset),
                             overrides=dict(over, PRESET=preset.value), cache=cache)
        parts = {} if p is None else dict(body=body.product, shell=shell.product, plate=plate.product)
        assembly = run_notebook(EXAMPLE_DIR / "l_link_motor_mount.py", id=dm.assembly_id(preset),
                                overrides=dict(parts, PRESET=preset.value), cache=cache)
        plates[preset], assemblies[preset] = plate.values, assembly.product
    return SimpleNamespace(body=body.values, shell=shell.values, plates=plates, assemblies=assemblies)


def check_stages(p: dict, runs: SimpleNamespace, screws: dict | None = None, label: str = "default",
                 verbose: bool = True) -> dict:
    """{stage: failures} of the S1 .. S9 contracts on the cell values of *runs* (built from *p*)."""
    up, sh = runs.body, runs.shell
    body, shell = up["mount_face_names"], sh["rim_name"]
    tags = (dm.TAG_MOUNT_LEFT, dm.TAG_MOUNT_RIGHT)
    checks = {
        "s1": lambda: c.check_s1(up["l_rod"], p),
        "s2": lambda: c.check_s2(up["motor_pockets"], p, up["l_rod"].get_volume(), None, None),
        "s3": lambda: c.check_s3(up["l_split"], sh["shell_region"], up["motor_pockets"], p, None),
        "s4": lambda: c.check_s4(sh["cable_notch"], sh["shell_region"], p, None),
        "s5": lambda: c.check_s5(up["boss_holes"], up["l_split"], sh["csink_holes"], sh["cable_notch"], p, None),
        "s6": lambda: c.check_s6(up["cap_rim_fillet"], up["boss_holes"], shell, sh["csink_holes"], p,
                                 (None, None, dm.TAG_SHELL_RIM)),
        "s7": lambda: c.check_s7(body, up["cap_rim_fillet"], p, tags),
        "s8": lambda: sum((c.check_s8(runs.plates[pr]["plate_face_names"], pr, p)
                           + c.check_s8_fit(runs.plates[pr]["plate_face_names"], body, pr, p)
                           for pr in PlatePreset), []) + c.check_s8_screws(p, screws),
        "s9": lambda: sum((c.check_s9(runs.assemblies[pr], pr, p, reference={
            "body": body, "shell": shell, "plate": runs.plates[pr]["plate_face_names"]}) for pr in PlatePreset), []),
    }
    out = {}
    for stage, run in checks.items():
        if verbose:
            print(f"  [{label}] --- {stage}")
        try:
            out[stage] = run()
        except Exception as exc:  # noqa: BLE001
            out[stage] = [f"{stage} error: {type(exc).__name__}: {exc}"]
    return out


def check_guard_stages() -> list[str]:
    """The per-stage guard contracts (each part's chain rejects what its stage needs rejected)."""
    return (c.check_s1_guards() + c.check_s3_guards() + c.check_s4_guards() + c.check_s5_guards()
            + c.check_s6_guards() + c.check_s7_guards() + c.check_s8_guards())


# ---- G1 / G2: binding guard text per (param, direction); None = FREE (see reason) ----
BINDING = {
    "L": ("boss_x2 筋尖须距剖分弧起点", "弧底须高于壳腔底"),
    "D": ("走线窗顶须距各自槽口", None),
    "rod_d": ("三叉臂端角须落在板背面平面内", "左槽底须高于剖分面至少 wall_t"),
    "d_motor": ("左槽底须高于剖分面至少 wall_t", "走线窗顶须距各自槽口"),
    "r_corner": ("r_corner 必须大于杆半径", "boss_x1 筋根须距拐角"),
    "thickness": ("fillet_r 须∈(0, thickness/4)", "三叉臂端角须落在板背面平面内"),
    "plate_t": ("plate_t 须 ≥ 5", "凹槽底后须保留 ≥ wall_t"),
    "wall_t": ("沉头锥下剩余孔壁须 ≥ 1.0", "左槽底须高于剖分面至少 wall_t"),
    "back_cut_frac": ("走线口须贯穿左端拐角壁", "左槽底须高于剖分面至少 wall_t"),
    "split_arc_frac": ("boss_x2 筋尖须距剖分弧起点", "弧形端壁内弧半径"),
    "split_end_frac": ("同轴孔窗口", "弧底须高于壳腔底"),
    # boss_d / rib_len hi: both rib ends reach their margin at once (25-5.5 = 17+2, 40+5.5 = 48-2) -> either text
    "boss_d": ("boss_hole_d 须∈(0, boss_d − 2]", "boss_x1 筋根须距拐角 | boss_x2 筋尖须距剖分弧起点"),
    "boss_hole_d": ("boss_hole_d 须∈(0, boss_d − 2]", "boss_hole_d 须∈(0, boss_d − 2]"),
    "boss_hole_depth": ("boss 盲孔深须∈(0,", "boss 盲孔深须∈(0,"),
    "boss_x1": ("boss_x1 筋根须距拐角", "两 boss 十字筋须相距 ≥ 1"),
    "boss_x2": ("两 boss 十字筋须相距 ≥ 1", "boss_x2 筋尖须距剖分弧起点"),
    "rib_t": ("rib_t 须 ≥ 2·gusset_chamfer", "rib_t 须 < boss_d"),
    "rib_len": ("rib_len 须 > 0", "boss_x1 筋根须距拐角 | boss_x2 筋尖须距剖分弧起点"),
    "gusset_h": ("gusset_h 须∈(0,", "gusset_h 须∈(0,"),
    "gusset_chamfer": ("gusset_chamfer 须 > 0", "rib_t 须 ≥ 2·gusset_chamfer"),
    "pad_t": ("沉头锥下剩余孔壁须 ≥ 1.0", "boss 盲孔深须∈(0,"),
    "fillet_r": ("fillet_r 须∈(0, thickness/4)", "fillet_r 须∈(0, thickness/4)"),
    "cable_w_off": ("cable_w_off 须∈[3, 5]", "走线窗顶须距各自槽口"),
    "cable_w_h": ("走线窗圆角须 0 < 2·cable_w_rr", "走线窗顶须距各自槽口"),
    "cable_w_w": ("走线窗圆角须 0 < 2·cable_w_rr", "cable_w_w 须 ≤ 1.6·rp"),
    "cable_w_rr": ("走线窗圆角须 0 < 2·cable_w_rr", "走线窗圆角须 0 < 2·cable_w_rr"),
    "cable_w_phase": ("cable_w_phase 须∈45°±5°", "cable_w_phase 须∈45°±5°"),
    "key_w": ("key_w 须 > 0", "三叉臂端角须落在板背面平面内"),
    "key_gap": ("key_gap 须 > 0", "三叉凹槽臂长须 ≤ rp − 0.5"),
    "key_phase": (None, None),
    "key_r_out": ("key_r_in 须∈(0, key_r_out]", "三叉臂端角须落在板背面平面内"),
    "groove_d": ("groove_d 须 > key_h", "凹槽底后须保留 ≥ wall_t"),
    "rad_screw_n": (None, None),  # integer domain -> G4
    "rad_clear_d": ("rad_pilot_d 须∈(0, rad_clear_d)", "rad_csink_d 须 > rad_clear_d"),
    "rad_csink_d": ("rad_csink_d 须 > rad_clear_d", "rad_spot_d 须 ≥ rad_csink_d + 0.2"),
    "rad_spot_d": ("rad_spot_d 须 ≥ rad_csink_d + 0.2", "rad_spot_depth 须 ≥ 锪平曲面矢高"),
    "rad_spot_depth": ("rad_spot_depth 须 ≥ 锪平曲面矢高", "center4: 无可用径向 M2 螺丝长度"),
    "notch_w": ("notch_rr 须 < min(notch_w, notch_h)/2", "同轴孔外环须可按 y 与内环分离"),
    "notch_h": ("notch_rr 须 < min(notch_w, notch_h)/2", "同轴孔窗口"),
    "notch_sill": ("走线口上边圆角顶须低于剖分面 0.05", "走线口须贯穿左端拐角壁"),
    "notch_rr": ("safe_fillet_r 须∈(0, notch_rr)", "notch_rr 须 < min(notch_w, notch_h)/2"),
    "pad_d": ("pad_d 须 ≥ boss_d + 1", "pad 顶面须完整高于其边缘处的内壁"),
    "shell_hole_d": ("沉头锥下剩余孔壁须 ≥ 1.0", "csink_d 须 > shell_hole_d"),
    "csink_d": ("csink_d 须 > shell_hole_d", "spot_d 须 ≥ csink_d + 0.2"),
    "spot_d": ("spot_d 须 ≥ csink_d + 0.2", "锪平须整平且侧壁 ≥ 0.1"),
    "spot_depth": ("锪平须整平且侧壁 ≥ 0.1", "沉头锥下剩余孔壁须 ≥ 1.0"),
    "safe_fillet_r": ("safe_fillet_r 须∈(0, notch_rr)", "三叉臂端角须落在板背面平面内"),
    "plate_gap": ("plate_gap 须 > 0", "三叉臂端角须落在板背面平面内"),
    "m2_hole_d": ("径向导孔 x 带须距背面圆角 / 电机沉头锥", "center4: 无可用径向 M2 螺丝长度"),
    "m2_pcd": ("center4: 三叉凸起到电机沉头口须 ≥ min_web", "center4: 无可用径向 M2 螺丝长度"),
    "m2_csink_d": ("m2_csink_d 须 ≥ m2_head_dk + 0.2", "径向导孔 x 带须距背面圆角 / 电机沉头锥"),
    "m2_head_dk": ("电机沉头锥深 + 头沉入须 ≤ plate_t − 2", "m2_csink_d 须 ≥ m2_head_dk + 0.2"),
    "m2_center_d": ("m2_center_d 须 > 0", "star3: 电机沉头口到中心孔须 ≥ min_web"),
    "key_h": ("key_h 须 > 0", "groove_d 须 > key_h"),
    "key_r_in": ("key_r_in 须∈(0, key_r_out]", "center4: 三叉凸起到电机沉头口须 ≥ min_web"),
    "min_web": ("min_web 须 > 0", "center4: 无可用径向 M2 螺丝长度"),
    "rad_pilot_d": ("rad_pilot_d 须∈(0, rad_clear_d)", "center4: 无可用径向 M2 螺丝长度"),
    "rad_pilot_depth": ("star3: 无可用径向 M2 螺丝长度", None),
}
FREE = {
    ("D", "hi"): "longer left arm: pocket depth / windows / rim fillet all grow, nothing converges",
    ("rad_pilot_depth", "hi"): "pilot is truncated to min_web from the motor holes (pilot_inner_r) -> saturates",
    ("key_phase", "lo"): "periodic angle (G4)", ("key_phase", "hi"): "periodic angle (G4)",
    ("rad_screw_n", "lo"): "integer (G4)", ("rad_screw_n", "hi"): "integer (G4)",
}


def _g(p: dict) -> dict:
    """Requirement geometry used by the analytic bounds (written here, not imported from the source)."""
    r = p["rod_d"] / 2.0
    by = r * (2.0 * p["back_cut_frac"] - 1.0)
    rp = (p["rod_d"] - p["thickness"]) / 2.0
    return dict(r=r, by=by, xa=p["split_arc_frac"] * p["L"], xb=p["split_end_frac"] * p["L"], rp=rp,
                rpl=rp - p["plate_gap"], fx=p["L"] - p["plate_t"], reach=p["boss_d"] / 2.0 + p["rib_len"],
                pt=-(r - p["wall_t"] - p["pad_t"]), arm=math.hypot(p["key_r_out"], p["key_w"] / 2.0),
                cd=(p["csink_d"] - p["shell_hole_d"]) / 2.0, spot_y=-r + p["spot_depth"],
                win=p["d_motor"] / 2.0 + p["cable_w_off"] + p["cable_w_h"] + 2.0)


KEY_TIP_LAND = 0.3  # requirement (S10): flat land between the key-arm corner and the plate back fillet
DROP_MIN = 1.0  # requirement (S10): arc bottom above the shell cavity floor -(r - wall_t)


def _spot_d_max(r: float, depth: float) -> float:
    """Largest spot-face diameter whose sag on the r cylinder leaves a >= 0.1 side wall."""
    return 2.0 * math.sqrt(r * r - (r - depth + 0.1) ** 2)


def _sag(r: float, d: float) -> float:
    return r - math.sqrt(r * r - (d / 2.0) ** 2)


# (param, side) -> (bound(p), inclusive)
ANALYTIC = {
    ("L", "lo"): (lambda p, g: (p["boss_x2"] + g["reach"] + 2.0) / p["split_arc_frac"], True),
    ("L", "hi"): (lambda p, g: (g["by"] + g["r"] - p["wall_t"] - DROP_MIN) / (p["split_end_frac"] - p["split_arc_frac"]),
                  True),
    ("D", "lo"): (lambda p, g: g["win"], True),
    ("rod_d", "lo"): (lambda p, g: p["thickness"] + 2.0 * (g["arm"] + p["safe_fillet_r"] + KEY_TIP_LAND + p["plate_gap"]),
                      True),
    ("rod_d", "hi"): (lambda p, g: 2.0 * (p["d_motor"] / 2.0 - p["wall_t"]) / (2.0 * p["back_cut_frac"] - 1.0), True),
    ("d_motor", "lo"): (lambda p, g: 2.0 * (g["by"] + p["wall_t"]), True),
    ("d_motor", "hi"): (lambda p, g: 2.0 * (p["D"] - 2.0 - p["cable_w_off"] - p["cable_w_h"]), True),
    ("r_corner", "lo"): (lambda p, g: g["r"], False),
    ("r_corner", "hi"): (lambda p, g: p["boss_x1"] - g["reach"] - 2.0, True),
    ("thickness", "lo"): (lambda p, g: 4.0 * p["fillet_r"], False),
    ("thickness", "hi"): (lambda p, g: p["rod_d"] - 2.0 * (g["arm"] + p["safe_fillet_r"] + KEY_TIP_LAND + p["plate_gap"]),
                          True),
    ("plate_t", "lo"): (lambda p, g: 5.0, True),
    ("plate_t", "hi"): (lambda p, g: p["L"] - p["groove_d"] - g["xb"] - p["wall_t"], True),
    ("wall_t", "lo"): (lambda p, g: 1.0 + p["spot_depth"] + g["cd"] - p["pad_t"], True),
    ("wall_t", "hi"): (lambda p, g: p["d_motor"] / 2.0 - g["by"], True),
    ("back_cut_frac", "hi"): (lambda p, g: ((p["d_motor"] / 2.0 - p["wall_t"]) / g["r"] + 1.0) / 2.0, True),
    ("split_arc_frac", "lo"): (lambda p, g: (p["boss_x2"] + g["reach"] + 2.0) / p["L"], True),
    ("split_arc_frac", "hi"): (lambda p, g: p["split_end_frac"] - (p["wall_t"] + 1.0) / p["L"], True),
    ("split_end_frac", "hi"): (lambda p, g: p["split_arc_frac"] + (g["by"] + g["r"] - p["wall_t"] - DROP_MIN) / p["L"],
                               True),
    ("boss_d", "lo"): (lambda p, g: p["boss_hole_d"] + 2.0, True),
    ("boss_d", "hi"): (lambda p, g: 2.0 * (g["xa"] - 2.0 - p["boss_x2"] - p["rib_len"]), True),
    ("boss_hole_d", "lo"): (lambda p, g: 0.0, False),
    ("boss_hole_d", "hi"): (lambda p, g: p["boss_d"] - 2.0, True),
    ("boss_hole_depth", "lo"): (lambda p, g: 0.0, False),
    ("boss_hole_depth", "hi"): (lambda p, g: g["by"] - g["pt"] - 0.5, True),
    ("boss_x1", "lo"): (lambda p, g: p["r_corner"] + 2.0 + g["reach"], True),
    ("boss_x1", "hi"): (lambda p, g: p["boss_x2"] - 2.0 * g["reach"] - 1.0, True),
    ("boss_x2", "lo"): (lambda p, g: p["boss_x1"] + 2.0 * g["reach"] + 1.0, True),
    ("boss_x2", "hi"): (lambda p, g: g["xa"] - 2.0 - g["reach"], True),
    ("rib_t", "lo"): (lambda p, g: 2.0 * p["gusset_chamfer"] + 0.3, True),
    ("rib_t", "hi"): (lambda p, g: p["boss_d"], False),
    ("rib_len", "lo"): (lambda p, g: 0.0, False),
    ("rib_len", "hi"): (lambda p, g: g["xa"] - 2.0 - p["boss_x2"] - p["boss_d"] / 2.0, True),
    ("gusset_h", "lo"): (lambda p, g: 0.0, False),
    ("gusset_h", "hi"): (lambda p, g: g["by"] - g["pt"] - 0.5, True),
    ("gusset_chamfer", "lo"): (lambda p, g: 0.0, False),
    ("gusset_chamfer", "hi"): (lambda p, g: (p["rib_t"] - 0.3) / 2.0, True),
    ("pad_t", "lo"): (lambda p, g: 1.0 + p["spot_depth"] + g["cd"] - p["wall_t"], True),
    ("pad_t", "hi"): (lambda p, g: g["by"] - 0.5 - p["boss_hole_depth"] + g["r"] - p["wall_t"], True),
    ("fillet_r", "lo"): (lambda p, g: 0.0, False),
    ("fillet_r", "hi"): (lambda p, g: p["thickness"] / 4.0, False),
    ("cable_w_off", "lo"): (lambda p, g: 3.0, True),
    ("cable_w_off", "hi"): (lambda p, g: p["D"] - 2.0 - p["d_motor"] / 2.0 - p["cable_w_h"], True),
    ("cable_w_h", "lo"): (lambda p, g: 2.0 * p["cable_w_rr"], False),
    ("cable_w_h", "hi"): (lambda p, g: p["D"] - 2.0 - p["d_motor"] / 2.0 - p["cable_w_off"], True),
    ("cable_w_w", "lo"): (lambda p, g: 2.0 * p["cable_w_rr"], False),
    ("cable_w_w", "hi"): (lambda p, g: 1.6 * g["rp"], True),
    ("cable_w_rr", "lo"): (lambda p, g: 0.0, False),
    ("cable_w_phase", "lo"): (lambda p, g: 40.0, True),  # empirical: inner-bend torus splits at |dev| >= 7
    ("cable_w_phase", "hi"): (lambda p, g: 50.0, True),
    ("cable_w_rr", "hi"): (lambda p, g: min(p["cable_w_w"], p["cable_w_h"]) / 2.0, False),
    ("key_w", "lo"): (lambda p, g: 0.0, False),
    ("key_w", "hi"): (lambda p, g: 2.0 * math.sqrt((g["rpl"] - p["safe_fillet_r"] - KEY_TIP_LAND) ** 2 - p["key_r_out"] ** 2), True),
    ("key_gap", "lo"): (lambda p, g: 0.0, False),
    ("key_gap", "hi"): (lambda p, g: g["rp"] - 0.5 - p["key_r_out"], True),
    ("key_r_out", "lo"): (lambda p, g: p["key_r_in"], True),
    ("key_r_out", "hi"): (lambda p, g: math.sqrt((g["rpl"] - p["safe_fillet_r"] - KEY_TIP_LAND) ** 2 - (p["key_w"] / 2.0) ** 2), True),
    ("groove_d", "lo"): (lambda p, g: p["key_h"], False),
    ("groove_d", "hi"): (lambda p, g: g["fx"] - g["xb"] - p["wall_t"], True),
    ("rad_clear_d", "lo"): (lambda p, g: p["rad_pilot_d"], False),
    ("rad_clear_d", "hi"): (lambda p, g: p["rad_csink_d"], False),
    ("rad_csink_d", "lo"): (lambda p, g: p["rad_clear_d"], False),
    ("rad_csink_d", "hi"): (lambda p, g: p["rad_spot_d"] - 0.2, True),
    ("rad_spot_d", "lo"): (lambda p, g: p["rad_csink_d"] + 0.2, True),
    ("rad_spot_d", "hi"): (lambda p, g: _spot_d_max(g["r"], p["rad_spot_depth"]), True),
    ("rad_spot_depth", "lo"): (lambda p, g: _sag(g["r"], p["rad_spot_d"]) + 0.1, True),
    ("notch_w", "lo"): (lambda p, g: 2.0 * p["notch_rr"], False),
    ("notch_h", "lo"): (lambda p, g: 2.0 * p["notch_rr"], False),
    ("notch_rr", "lo"): (lambda p, g: p["safe_fillet_r"], False),
    ("notch_rr", "hi"): (lambda p, g: min(p["notch_w"], p["notch_h"]) / 2.0, False),
    ("pad_d", "lo"): (lambda p, g: p["boss_d"] + 1.0, True),
    ("shell_hole_d", "lo"): (lambda p, g: p["csink_d"] - 2.0 * (g["pt"] - g["spot_y"] - 1.0), True),
    ("shell_hole_d", "hi"): (lambda p, g: p["csink_d"], False),
    ("csink_d", "lo"): (lambda p, g: p["shell_hole_d"], False),
    ("csink_d", "hi"): (lambda p, g: p["spot_d"] - 0.2, True),
    ("spot_d", "lo"): (lambda p, g: p["csink_d"] + 0.2, True),
    ("spot_d", "hi"): (lambda p, g: _spot_d_max(g["r"], p["spot_depth"]), True),
    ("spot_depth", "lo"): (lambda p, g: _sag(g["r"], p["spot_d"]) + 0.1, True),
    ("spot_depth", "hi"): (lambda p, g: g["r"] + g["pt"] - 1.0 - g["cd"], True),
    ("safe_fillet_r", "lo"): (lambda p, g: 0.0, False),
    ("safe_fillet_r", "hi"): (lambda p, g: g["rpl"] - g["arm"] - KEY_TIP_LAND, True),
    ("plate_gap", "lo"): (lambda p, g: 0.0, False),
    ("plate_gap", "hi"): (lambda p, g: g["rp"] - g["arm"] - p["safe_fillet_r"] - KEY_TIP_LAND, True),
    ("m2_csink_d", "lo"): (lambda p, g: p["m2_head_dk"] + 0.2, True),
    ("m2_head_dk", "lo"): (lambda p, g: 2.0 * p["m2_csink_d"] - p["m2_hole_d"] - 2.0 * (p["plate_t"] - 2.0), True),
    ("m2_head_dk", "hi"): (lambda p, g: p["m2_csink_d"] - 0.2, True),
    ("m2_center_d", "lo"): (lambda p, g: 0.0, False),
    ("m2_center_d", "hi"): (lambda p, g: p["m2_pcd"] - p["m2_csink_d"] - 2.0 * p["min_web"], True),
    ("key_h", "lo"): (lambda p, g: 0.0, False),
    ("key_h", "hi"): (lambda p, g: p["groove_d"], False),
    ("key_r_in", "lo"): (lambda p, g: 0.0, False),
    ("min_web", "lo"): (lambda p, g: 0.0, False),
    ("rad_pilot_d", "lo"): (lambda p, g: 0.0, False),
}


def outcome(p: dict) -> str | None:
    try:
        dm.check_plate(p)
    except AssertionError as exc:
        return str(exc)
    return None


def _hit(frag: str, msg: str | None) -> bool:
    """`frag` may list alternatives 'a | b' (guards that tie at the same bound)."""
    return msg is not None and any(f in msg for f in frag.split(" | "))


def find_edge(key: str, sign: float) -> tuple[float | None, str | None]:
    """Outward geometric steps from the default until rejected, then bisect (60 halvings)."""
    x, step = P0[key], max(abs(P0[key]) * 0.02, 0.01)
    for _ in range(80):
        x2 = x + sign * step
        if outcome(dict(P0, **{key: x2})) is not None:
            break
        x, step = x2, step * 1.3
    else:
        return None, None
    a, b = x, x2
    for _ in range(60):
        m = (a + b) / 2.0
        a, b = (m, b) if outcome(dict(P0, **{key: m})) is None else (a, m)
    return a, outcome(dict(P0, **{key: b}))


def check_guards() -> list[str]:
    ck = c.Checks()
    ck("G0 default accepted", outcome(P0) is None, str(outcome(P0)))
    missing = sorted(set(P0) - set(BINDING))
    ck("G0 binding table covers every param", not missing, f"missing={missing}")
    n_edges = n_exact = 0
    for key, frags in BINDING.items():
        for side, sign, frag in (("lo", -1.0, frags[0]), ("hi", 1.0, frags[1])):
            if (key, side) in FREE:
                continue
            edge, msg = find_edge(key, sign)
            n_edges += 1
            if frag is None or edge is None:
                ck(f"G1 {key} {side} bounded", False, f"edge={edge} msg={msg} (not in FREE)")
                continue
            if not _hit(frag, msg):
                ck(f"G2 {key} {side} binding", False, f"edge={edge:.6f} got={msg!r} want~{frag!r}")
            if (key, side) in ANALYTIC:
                fn, incl = ANALYTIC[(key, side)]
                bound = fn(P0, _g(P0))
                inward = -sign  # direction back toward the default
                o_in = outcome(dict(P0, **{key: bound + inward * EPS}))
                o_out = outcome(dict(P0, **{key: bound - inward * EPS}))
                o_at = outcome(dict(P0, **{key: bound}))
                exact = (abs(edge - bound) <= EPS and o_in is None and _hit(frag, o_out)
                         and ((o_at is None) if incl else _hit(frag, o_at)))
                n_exact += 1
                if not exact:
                    ck(f"G3 {key} {side} exact", False,
                       f"analytic={bound:.9f} bisect={edge:.9f} inside={o_in!r} outside={o_out!r} at={o_at!r} incl={incl}")
    ck("G1/G2/G3 edges", not ck.failures, f"edges={n_edges} analytic={n_exact} free={len(FREE)}")
    ns = {n for n in range(1, 7) if outcome(dict(P0, rad_screw_n=float(n))) is None}
    ck("G4 rad_screw_n domain", ns == {1, 3}, f"accepted={sorted(ns)}")
    bad = [a for a in range(0, 360, 5) if outcome(dict(P0, key_phase=float(a))) is not None]
    ck("G4 key_phase free", not bad, f"rejected={bad[:6]}")
    acc = {a for a in range(0, 360, 5) if outcome(dict(P0, cable_w_phase=float(a))) is None}
    want = {a for a in range(0, 360, 5) if abs(a % 90 - 45) <= 5}
    ck("G4 cable_w_phase domain", acc == want, f"accepted={sorted(acc)}")
    return ck.failures


# ---- V / E: geometry sweeps ----
S_DEFAULT = {"star3": 6.0, "center4": 5.0}
VARIANTS = {
    # name: (overrides, radial-screw picks)  -- picks: head at r - rad_spot_depth, tip >= pilot bottom + 0.5,
    # engagement >= 1.5; pilot bottom t0 = max(plate_r - 4, csink-hole clearance 9.037 [center4] / bore 3.3 [star3])
    "long_L100": (dict(L=100.0), S_DEFAULT),
    "split_shift": (dict(split_arc_frac=0.65, split_end_frac=0.8), S_DEFAULT),
    "phase": (dict(key_phase=30.0, cable_w_phase=140.0), S_DEFAULT),  # window set = 45+5 mirror
    "plate_t8": (dict(plate_t=8.0), S_DEFAULT),
    # r=16 -> head 15.75, plate_r 12.9: star3 t0 8.9 -> M2x6; center4 t0 9.037 -> 15.75-6=9.75 >= 9.537 -> M2x6
    # (back_cut_frac 0.734375 keeps back_y 7.5 but the shell pad fuse's UnifySameDomain then writes an invalid
    #  corner torus face (wire imbrication, v span > 2 pi) -- kernel finding, see BUILD_PLAN S10; 0.70 is clean)
    "rod32": (dict(rod_d=32.0, back_cut_frac=0.70), {"star3": 6.0, "center4": 6.0}),
    "combo": (dict(L=90.0, D=24.0, r_corner=16.5, split_arc_frac=0.62, split_end_frac=0.76,
                   boss_x1=26.0, boss_x2=42.0), S_DEFAULT),
}


def _edge(key: str, side: str) -> dict:
    """Param pinned at its accepted extreme (the bound itself if inclusive, else 1e-6 inside)."""
    fn, incl = ANALYTIC[(key, side)]
    b = fn(P0, _g(P0))
    return {key: b if incl else b + (EPS if side == "lo" else -EPS)}


EDGES = {  # accepted extremes where geometry gets tight / tangent
    "cable_w_phase_lo": (_edge("cable_w_phase", "lo"), S_DEFAULT),
    "L_hi": (_edge("L", "hi"), S_DEFAULT),  # arc bottom 1 above the cavity floor (inner drop = 1)
    "boss_x2_hi": (_edge("boss_x2", "hi"), S_DEFAULT),  # rib tip 2 from the arc start
    "split_arc_frac_hi": (_edge("split_arc_frac", "hi"), S_DEFAULT),  # Rs - wall_t = 1
    "key_r_out_hi": (_edge("key_r_out", "hi"), S_DEFAULT),  # arm corner KEY_TIP_LAND from the plate back fillet
    "rad_spot_d_hi": (_edge("rad_spot_d", "hi"), S_DEFAULT),  # spot side wall 0.1
}


def _run(job: tuple) -> tuple:
    name, over, screws = job
    p = dict(P0, **over)
    try:
        res = check_stages(p, run_all(p), screws, name, verbose=False)
    except Exception as exc:  # noqa: BLE001 -- SimpleCADError does not unpickle; a raising build is a failure
        return name, {"build raised": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return name, {k: v for k, v in res.items() if v}


def check_geometry(table: dict, tag: str, workers: int = 6) -> list[str]:
    failures = []
    jobs = [(name, over, screws) for name, (over, screws) in table.items()]
    for name, over, _ in jobs:
        assert outcome(dict(P0, **over)) is None, f"{tag} {name} rejected by guards: {outcome(dict(P0, **over))}"
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for name, bad in pool.map(_run, jobs):
            print(f"{'PASS' if not bad else 'FAIL'} {tag} {name} {table[name][0]} {bad if bad else 'S1 .. S9 all pass'}")
            if bad:
                failures.append(f"{tag} {name}")
    return failures


def main(mode: str) -> int:
    failures = []
    if mode in ("stages", "all"):
        res = check_stages(P0, run_all())
        failures += [f"{stage}: {bad}" for stage, bad in res.items() if bad]
    if mode in ("guards", "all"):
        failures += check_guard_stages() + check_guards()
    if mode in ("sweep", "all"):
        failures += check_geometry(VARIANTS, "V")
    if mode in ("edges", "all"):
        failures += check_geometry(EDGES, "E")
    print(f"l_link acceptance ({mode}): {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
