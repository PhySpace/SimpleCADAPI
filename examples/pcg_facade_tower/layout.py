"""PCG layout engine: plan -> setback tiers -> per-edge module subdivision -> panel schedule.

Pure data, no geometry. Every geometric file consumes the FacadeSchedule this module emits; this is the one
place where the procedural rules live (subdivision, closers, corners, fin wave field + quantization, ordered
dithering for the window-to-wall ratio, type and floor-type rationalization).

Frames (BUILD_PLAN datum):
  world   Z up, +X east, +Y north, origin = ground level at the plan's SW corner; plan polygons are CCW.
  edge i  from vertex i to i+1, tangent t_i, outward normal n_i = (t_y, -t_x).
  panel   local x along the edge (0 = left module boundary), y up (0 = level), z outward (0 = building line).
          placement: origin = V_i + s0*t_i + level*Z, x_axis = t_i, y_axis = Z  ->  z_axis = t_i x Z = n_i.
  corner  local x = incoming tangent, y up, z = incoming normal; origin = the building-line vertex.
  fin     panel orientation; origin = right-jamb centreline on the frame outer face (panel-local
          (w - joint/2 - frame_sight/2, joint/2, frame_d)). Fins are separate site-attached Parts: fixed to the
          panel, a 45 deg fin pushes the unit to ~1676 mm wide, past the 1600 transport envelope (V3).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any

import simplecadapi as scad

# ---- params ----
PLAN_W = scad.var("plan_w", 36000.0, comment="平面 X 外包（东西）", unit="mm")
PLAN_D = scad.var("plan_d", 24000.0, comment="平面 Y 外包（南北）", unit="mm")
CHAMFER = scad.var("chamfer", 6000.0, comment="CHAMFER：NE 角沿两边各切", unit="mm")
NOTCH_W = scad.var("notch_w", 12000.0, comment="L_SHAPE：NE 缺口 X 宽", unit="mm")
NOTCH_D = scad.var("notch_d", 9000.0, comment="L_SHAPE：NE 缺口 Y 深", unit="mm")
N_FLOORS = scad.var("n_floors", 36, comment="lobby 之上的标准层数")
FLOOR_H = scad.var("floor_h", 3600.0, comment="标准层高", unit="mm")
LOBBY_H = scad.var("lobby_h", 5400.0, comment="首层 lobby 层高", unit="mm")
SETBACK_EVERY = scad.var("setback_every", 12, comment="每 tier 层数")
SETBACK_DEPTH = scad.var("setback_depth", 3000.0, comment="每 tier 四边内退", unit="mm")
PARAPET_H = scad.var("parapet_h", 1200.0, comment="女儿墙高", unit="mm")
W_STD = scad.var("w_std", 1500.0, comment="标准板模数宽（含缝）", unit="mm")
CLOSER_MIN = scad.var("closer_min", 450.0, comment="收口板最小模数宽（含缝）", unit="mm")
JOINT = scad.var("joint", 20.0, comment="板缝（四周各 joint/2）", unit="mm")
CORNER_C = scad.var("corner_c", 450.0, comment="角件沿各边占宽（自 building line 顶点）", unit="mm")
FRAME_D = scad.var("frame_d", 150.0, comment="框深（building line 外）", unit="mm")
FRAME_SIGHT = scad.var("frame_sight", 60.0, comment="框面宽", unit="mm")
SPANDREL_H = scad.var("spandrel_h", 1100.0, comment="层间实体区高", unit="mm")
GLASS_T = scad.var("glass_t", 24.0, comment="玻璃厚", unit="mm")
GLASS_RECESS = scad.var("glass_recess", 40.0, comment="玻璃外面距框外面凹进", unit="mm")
FIN_T = scad.var("fin_t", 40.0, comment="竖挺厚", unit="mm")
FIN_DEPTH = scad.var("fin_depth", 300.0, comment="竖挺伸出深度（自框外面）", unit="mm")
FIN_AMP = scad.var("fin_amp", 30.0, comment="波场幅值", unit="deg")
FIN_WAVELENGTH = scad.var("fin_wavelength", 18000.0, comment="波场沿周长波长", unit="mm")
FIN_PERIOD_FLOORS = scad.var("fin_period_floors", 4, comment="波场 / 抖动竖向周期（层），须为 4 的倍数")
FIN_BINS = scad.var("fin_bins", 6, comment="竖挺角量化档数 K（合理化旋钮）")
SUN_AZIMUTH = scad.var("sun_azimuth", 180.0, comment="太阳方位角（自北顺时针）", unit="deg")
SLAB_T = scad.var("slab_t", 300.0, comment="楼板厚", unit="mm")
SLAB_GAP = scad.var("slab_gap", 30.0, comment="楼板外沿距 building line 内缩", unit="mm")
CANOPY_MODULES = scad.var("canopy_modules", 6, comment="南向入口雨棚跨越的标准模数（奇偶自动对齐到板缝）")
CANOPY_DEPTH = scad.var("canopy_depth", 3000.0, comment="雨棚外挑（自板外面 + 缝）", unit="mm")
CANOPY_T = scad.var("canopy_t", 250.0, comment="雨棚厚", unit="mm")

FIN_LIMIT = 45.0  # 竖挺角范围 [-45°, 45°]（0 = 垂直立面）
SUN_THETA_LIMIT = 30.0  # 朝向基准角 θ_sun 的限幅
FIN_FACING_MIN = -0.2  # n·sun > -0.2 的边带竖挺（E/W/S），其余（N、NE 切角）无挺
TYPE_ROUND_DIGITS = 3  # 板型身份：宽/角四舍五入到 0.001（A7）
WWR_TOL = 0.03
MAX_PANEL_H = 4200.0  # transport envelope height (V3); taller bands (lobby) split into stacked rows
BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


class PlanKind(str, Enum):
    RECT = "rect"
    CHAMFER = "chamfer"
    L_SHAPE = "l_shape"


class Band(str, Enum):
    LOBBY = "lobby"
    TOWER = "tower"
    PARAPET = "parapet"


def _value(value: object) -> float:
    evaluate = getattr(value, "evaluate", None)
    return float(evaluate()) if callable(evaluate) else float(value)


@dataclass(frozen=True)
class FacadeParams:
    plan_kind: PlanKind = PlanKind.CHAMFER
    plan_w: float = _value(PLAN_W)
    plan_d: float = _value(PLAN_D)
    chamfer: float = _value(CHAMFER)
    notch_w: float = _value(NOTCH_W)
    notch_d: float = _value(NOTCH_D)
    n_floors: int = int(_value(N_FLOORS))
    floor_h: float = _value(FLOOR_H)
    lobby_h: float = _value(LOBBY_H)
    setback_every: int = int(_value(SETBACK_EVERY))
    setback_depth: float = _value(SETBACK_DEPTH)
    parapet_h: float = _value(PARAPET_H)
    w_std: float = _value(W_STD)
    closer_min: float = _value(CLOSER_MIN)
    joint: float = _value(JOINT)
    corner_c: float = _value(CORNER_C)
    frame_d: float = _value(FRAME_D)
    frame_sight: float = _value(FRAME_SIGHT)
    spandrel_h: float = _value(SPANDREL_H)
    glass_t: float = _value(GLASS_T)
    glass_recess: float = _value(GLASS_RECESS)
    fin_t: float = _value(FIN_T)
    fin_depth: float = _value(FIN_DEPTH)
    fin_amp: float = _value(FIN_AMP)
    fin_wavelength: float = _value(FIN_WAVELENGTH)
    fin_period_floors: int = int(_value(FIN_PERIOD_FLOORS))
    fin_bins: int = int(_value(FIN_BINS))
    sun_azimuth: float = _value(SUN_AZIMUTH)
    slab_t: float = _value(SLAB_T)
    slab_gap: float = _value(SLAB_GAP)
    canopy_modules: int = int(_value(CANOPY_MODULES))
    canopy_depth: float = _value(CANOPY_DEPTH)
    canopy_t: float = _value(CANOPY_T)
    # glass / gross per orientation; ceiling ~0.54 (frames + spandrel + solid closers), south lowest for solar gain
    wwr_target: tuple = (("N", 0.50), ("E", 0.40), ("S", 0.35), ("W", 0.40))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["plan_kind"] = self.plan_kind.value
        data["wwr_target"] = dict(self.wwr_target)
        return data


def default_params(**overrides: Any) -> FacadeParams:
    return replace(FacadeParams(), **overrides)


# ---------------------------------------------------------------- guards


class LayoutError(ValueError):
    """Infeasible parameter set (raised instead of silently degrading the layout)."""


def assert_params(p: FacadeParams) -> None:
    def need(ok: bool, message: str) -> None:
        if not ok:
            raise LayoutError(message)

    positive = ("plan_w", "plan_d", "floor_h", "lobby_h", "parapet_h", "w_std", "closer_min", "joint", "corner_c",
                "frame_d", "frame_sight", "glass_t", "fin_t", "fin_depth", "fin_wavelength", "slab_t")
    for name in positive:
        need(math.isfinite(getattr(p, name)) and getattr(p, name) > 0.0, f"{name} must be positive")
    need(p.n_floors >= 1 and p.setback_every >= 1, "n_floors / setback_every must be >= 1")
    need(p.setback_depth >= 0.0 and p.slab_gap >= 0.0, "setback_depth / slab_gap must be >= 0")
    need(p.fin_bins >= 2, "fin_bins must be >= 2")
    need(p.fin_period_floors >= 4 and p.fin_period_floors % 4 == 0, "fin_period_floors must be a multiple of 4")
    need(p.closer_min > p.joint + 2.0 * p.frame_sight, "closer_min must leave a frame inside the joint")
    need(p.closer_min < p.w_std, "closer_min must be < w_std")
    need(p.corner_c > p.frame_d + p.joint, "corner_c must exceed frame_d + joint (concave corner bands overlap)")
    need(p.spandrel_h + 2.0 * p.frame_sight + p.joint < p.floor_h, "spandrel_h leaves no vision opening")
    need(p.glass_recess + p.glass_t < p.frame_d, "glass must sit inside the frame depth")
    need(p.fin_t < p.w_std / 2.0, "fin_t too thick for the module")
    need(p.floor_h <= MAX_PANEL_H and p.parapet_h <= MAX_PANEL_H, "floor_h / parapet_h exceed the transport height")
    # slab occupies [level, level + slab_t] and must hide behind the spandrel (A3); the parapet hides the roof slab
    need(p.slab_t < p.spandrel_h - p.frame_sight / 2.0, "slab_t shows below the spandrel")
    need(p.slab_t < p.parapet_h - p.joint / 2.0 - p.frame_sight, "slab_t shows above the parapet")
    need(p.slab_gap > 0.0, "slab_gap must keep the slab off the building line")
    need(p.canopy_modules >= 1 and p.canopy_depth > 0.0 and p.canopy_t > 0.0, "canopy size")
    need(p.canopy_t < p.lobby_h / math.ceil(p.lobby_h / MAX_PANEL_H - 1.0e-9), "canopy_t taller than a lobby row")
    need(0.0 <= p.fin_amp <= FIN_LIMIT, "fin_amp must lie in [0, 45]")
    if p.plan_kind is PlanKind.CHAMFER:
        need(0.0 < p.chamfer < min(p.plan_w, p.plan_d), "chamfer must lie inside the plan")
    if p.plan_kind is PlanKind.L_SHAPE:
        need(0.0 < p.notch_w < p.plan_w and 0.0 < p.notch_d < p.plan_d, "notch must lie inside the plan")
    need(all(0.0 < value <= 1.0 for _, value in p.wwr_target), "wwr targets must lie in (0, 1]")


# ---------------------------------------------------------------- plan + tiers


def base_plan(p: FacadeParams) -> list[tuple[float, float]]:
    w, d = p.plan_w, p.plan_d
    if p.plan_kind is PlanKind.RECT:
        return [(0.0, 0.0), (w, 0.0), (w, d), (0.0, d)]
    if p.plan_kind is PlanKind.CHAMFER:
        c = p.chamfer
        return [(0.0, 0.0), (w, 0.0), (w, d - c), (w - c, d), (0.0, d)]
    nw, nd = p.notch_w, p.notch_d
    return [(0.0, 0.0), (w, 0.0), (w, d - nd), (w - nw, d - nd), (w - nw, d), (0.0, d)]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, k):
    return (a[0] * k, a[1] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _unit(a):
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n)


def edge_frames(poly: list) -> list[dict]:
    """Per edge: start vertex, tangent, outward normal, length."""
    out = []
    for i, v0 in enumerate(poly):
        v1 = poly[(i + 1) % len(poly)]
        t = _unit(_sub(v1, v0))
        out.append({"v0": v0, "v1": v1, "t": t, "n": (t[1], -t[0]), "length": math.hypot(*_sub(v1, v0))})
    return out


def signed_area(poly: list) -> float:
    return 0.5 * sum(_cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _segments_cross(a0, a1, b0, b1) -> bool:
    d1, d2 = _cross(_sub(a1, a0), _sub(b0, a0)), _cross(_sub(a1, a0), _sub(b1, a0))
    d3, d4 = _cross(_sub(b1, b0), _sub(a0, b0)), _cross(_sub(b1, b0), _sub(a1, b0))
    return d1 * d2 < 0.0 and d3 * d4 < 0.0


def is_simple(poly: list) -> bool:
    n = len(poly)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n]):
                return False
    return True


def offset_polygon(poly: list, d: float) -> list:
    """Move every edge inward by d (edge lines shift along -n); vertex = intersection of adjacent offset lines."""
    frames = edge_frames(poly)
    out = []
    for i in range(len(poly)):
        n_in, n_out = frames[i - 1]["n"], frames[i]["n"]
        k = 1.0 + _dot(n_in, n_out)
        if k < 1.0e-6:
            raise LayoutError("edge reversal: adjacent edges are anti-parallel")
        out.append(_sub(poly[i], _mul(_add(n_in, n_out), d / k)))
    return out


def tier_plans(p: FacadeParams) -> list[list]:
    base = base_plan(p)
    n_tiers = (p.n_floors + p.setback_every - 1) // p.setback_every
    plans = []
    for k in range(n_tiers):
        poly = offset_polygon(base, k * p.setback_depth) if k else base
        before, after = edge_frames(base), edge_frames(poly)
        for b, a in zip(before, after):
            if _dot(b["t"], a["t"]) < 0.999999 or a["length"] <= 0.0:
                raise LayoutError(f"tier {k}: setback collapses an edge")
        if signed_area(poly) <= 0.0 or not is_simple(poly):
            raise LayoutError(f"tier {k}: setback polygon is not simple / CCW")
        plans.append(poly)
    return plans


# ---------------------------------------------------------------- corners


def corner_turn(frames: list, i: int) -> float:
    """Signed turn at vertex i (incoming edge i-1 -> outgoing edge i), degrees; + = convex (left turn)."""
    t_in, t_out = frames[i - 1]["t"], frames[i]["t"]
    return math.degrees(math.atan2(_cross(t_in, t_out), _dot(t_in, t_out)))


def corner_profile_local(turn_deg: float, p: FacadeParams, joint: float | None = None) -> list[tuple[float, float]]:
    """Corner piece plan polygon in the corner frame (x = incoming tangent, second coord = incoming normal).

    Bounded by the building line (two reserves of corner_c - joint/2 each side of the vertex), the two panel-band
    outer faces (offset frame_d) and the band end lines. Returned CCW in (x, n) coordinates."""
    j = p.joint if joint is None else joint
    c, fd = p.corner_c - j / 2.0, p.frame_d
    a = math.radians(turn_deg)
    # Plan coords with the incoming edge along +x; a CCW plan puts the outward normal at -y.
    t_in, n_in = (1.0, 0.0), (0.0, -1.0)
    t_out = (math.cos(a), math.sin(a))
    n_out = (t_out[1], -t_out[0])
    k = 1.0 + _dot(n_in, n_out)
    if k < 1.0e-6:
        raise LayoutError("corner too sharp")
    v = (0.0, 0.0)
    a0 = _mul(t_in, -c)
    a1 = _add(a0, _mul(n_in, fd))
    apex = _mul(_add(n_in, n_out), fd / k)
    b1 = _add(_mul(t_out, c), _mul(n_out, fd))
    b0 = _mul(t_out, c)
    poly = [a0, a1, apex, b1, b0, v]
    if signed_area(poly) < 0.0:
        poly.reverse()
    if not is_simple(poly):
        raise LayoutError(f"corner profile not simple at turn {turn_deg:.3f}")
    # (x, y) -> (x, outward = -y); the mirror flips orientation, so reverse to stay CCW
    local = [(x, -y) for x, y in poly]
    return list(reversed(local))


# ---------------------------------------------------------------- field + quantization


def fin_bin_angles(k: int) -> list[float]:
    return [-FIN_LIMIT + 2.0 * FIN_LIMIT * i / (k - 1) for i in range(k)]


def quantize_fin(theta: float, k: int) -> tuple[int, float]:
    theta = max(-FIN_LIMIT, min(FIN_LIMIT, theta))
    index = int(round((theta + FIN_LIMIT) / (2.0 * FIN_LIMIT) * (k - 1)))
    return index, fin_bin_angles(k)[index]


def sun_vector(p: FacadeParams) -> tuple[float, float]:
    az = math.radians(p.sun_azimuth)
    return (math.sin(az), math.cos(az))


def edge_has_fins(n, p: FacadeParams) -> bool:
    return _dot(n, sun_vector(p)) > FIN_FACING_MIN


def theta_sun(n, p: FacadeParams) -> float:
    s = sun_vector(p)
    phi = math.degrees(math.atan2(_cross(n, s), _dot(n, s)))
    return max(-SUN_THETA_LIMIT, min(SUN_THETA_LIMIT, phi))


def orientation(n) -> str:
    """N/E/S/W by outward normal; ties (45° edges) go to N/S (|ny| >= |nx|)."""
    if abs(n[1]) >= abs(n[0]):
        return "N" if n[1] > 0.0 else "S"
    return "E" if n[0] > 0.0 else "W"


# ---------------------------------------------------------------- subdivision


def subdivide_edge(length: float, p: FacadeParams) -> dict:
    """[corner c][closer][n x w_std][closer][corner c]; closers symmetric and in [closer_min, closer_min + w_std/2)."""
    eff = length - 2.0 * p.corner_c
    if eff < 2.0 * p.closer_min - 1.0e-9:
        raise LayoutError(f"edge {length:.3f} too short for two corners and two closers")
    n = int(math.floor((eff - 2.0 * p.closer_min) / p.w_std + 1.0e-9))
    closer = (eff - n * p.w_std) / 2.0
    widths = [closer] + [p.w_std] * n + [closer]
    starts, s = [], p.corner_c
    for w in widths:
        starts.append(s)
        s += w
    return {"n_std": n, "closer": closer, "widths": widths, "starts": starts}


def _r(value: float) -> float:
    return round(value, TYPE_ROUND_DIGITS)


def _mm(value: float) -> str:
    text = f"{_r(value):.3f}".rstrip("0").rstrip(".")
    return text.replace("-", "m")


def solid_type_id(w: float, h: float) -> str:
    return f"solid-w{_mm(w)}-h{_mm(h)}"


def vision_type_id(w: float, h: float, spandrel: float) -> str:
    return f"vision-w{_mm(w)}-h{_mm(h)}-s{_mm(spandrel)}"


def fin_type_id(angle: float, h: float) -> str:
    return f"fin-a{_mm(angle)}-h{_mm(h)}"


def fin_root_s(s0: float, w: float, p: FacadeParams) -> float:
    """Fin root along the edge: centreline of the panel's right jamb (A6)."""
    return s0 + w - p.joint / 2.0 - p.frame_sight / 2.0


def corner_type_id(turn: float, h: float) -> str:
    return f"corner-t{_mm(turn)}-h{_mm(h)}"


# ---------------------------------------------------------------- schedule


@dataclass
class FacadeSchedule:
    params: FacadeParams
    tiers: list  # tier polygons
    levels: dict  # band / floor -> level z
    types: dict = field(default_factory=dict)  # type_id -> spec
    bands: list = field(default_factory=list)  # band records (floor bands, lobby, parapets)
    floor_types: dict = field(default_factory=dict)  # floor_type_id -> {"tier", "phase", "band"}
    floors: list = field(default_factory=list)  # [{"floor", "tier", "level", "floor_type"}]
    stats: dict = field(default_factory=dict)
    vision_fraction: dict = field(default_factory=dict)  # orientation -> share of standard modules that are vision

    def to_dict(self) -> dict:
        return {"params": self.params.to_dict(), "tiers": self.tiers, "levels": self.levels, "types": self.types,
                "bands": self.bands, "floor_types": self.floor_types, "floors": self.floors, "stats": self.stats,
                "vision_fraction": self.vision_fraction}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=1, ensure_ascii=False)

    def band(self, band_id: str) -> dict:
        return next(b for b in self.bands if b["band_id"] == band_id)


def _register(types: dict, type_id: str, spec: dict) -> str:
    known = types.setdefault(type_id, spec)
    if known != spec:
        raise LayoutError(f"type id collision: {type_id}")
    return type_id


def _glass_area(w: float, h: float, spandrel: float, p: FacadeParams) -> float:
    """Design vision opening of a vision panel (module w x h).

    Horizontally inside the jambs; vertically from the transom (centred on the spandrel line) or, with no
    spandrel, the sill frame, up to the head frame."""
    gw = w - p.joint - 2.0 * p.frame_sight
    top = h - p.joint / 2.0 - p.frame_sight
    bottom = spandrel + p.frame_sight / 2.0 if spandrel > 0.0 else p.joint / 2.0 + p.frame_sight
    return gw * (top - bottom)


def _band_panels(tier_poly, band: Band, height: float, p: FacadeParams, types: dict, phase: int | None,
                 vision_cells: set | None) -> tuple[list, list, list]:
    """Panels, corners and fins of one horizontal band on one tier polygon (level-independent: local to the band)."""
    frames = edge_frames(tier_poly)
    panels, corners, fins_out = [], [], []
    u0 = 0.0
    for e, fr in enumerate(frames):
        sub = subdivide_edge(fr["length"], p)
        fins, facing = edge_has_fins(fr["n"], p), orientation(fr["n"])
        for k, (s0, w) in enumerate(zip(sub["starts"], sub["widths"])):
            is_closer = k in (0, len(sub["widths"]) - 1)
            record = {"edge": e, "slot": k, "s0": s0, "w": w, "orientation": facing}
            if band is Band.PARAPET or is_closer:
                record.update(kind="solid", type_id=_register(
                    types, solid_type_id(w, height), {"family": "solid", "w": _r(w), "h": _r(height)}))
            elif band is Band.LOBBY:
                record.update(kind="vision", type_id=_register(types, vision_type_id(w, height, 0.0), {
                    "family": "vision", "w": _r(w), "h": _r(height), "spandrel": 0.0}))
            else:
                if (e, k) in vision_cells:
                    fin = None
                    if fins:
                        u = u0 + s0 + w / 2.0
                        raw = theta_sun(fr["n"], p) + p.fin_amp * math.sin(
                            2.0 * math.pi * (u / p.fin_wavelength + phase / p.fin_period_floors))
                        _, fin = quantize_fin(raw, p.fin_bins)
                        record["fin_raw"] = raw
                        fins_out.append({"edge": e, "slot": k, "s": fin_root_s(s0, w, p), "angle": fin,
                                         "type_id": _register(types, fin_type_id(fin, height),
                                                              {"family": "fin", "angle": _r(fin), "h": _r(height)})})
                    record.update(kind="vision", fin=fin, type_id=_register(
                        types, vision_type_id(w, height, p.spandrel_h),
                        {"family": "vision", "w": _r(w), "h": _r(height), "spandrel": _r(p.spandrel_h)}))
                else:
                    record.update(kind="solid", type_id=_register(
                        types, solid_type_id(w, height), {"family": "solid", "w": _r(w), "h": _r(height)}))
            panels.append(record)
        u0 += fr["length"]
    for i in range(len(frames)):
        turn = corner_turn(frames, i)
        corners.append({"vertex": i, "turn": turn, "type_id": _register(
            types, corner_type_id(turn, height), {"family": "corner", "turn": _r(turn), "h": _r(height)})})
    return panels, corners, fins_out


def _vision_cells(tier_poly, p: FacadeParams, fractions: dict) -> dict:
    """phase -> {(edge, slot)} of standard modules that are vision on this tier.

    Ordered dithering by rank: every (phase, standard module) cell of one orientation is ranked by its 4x4 Bayer
    threshold (column = running module index along that orientation, continuous across edges; row = phase), then
    exactly round(fraction x cells) lowest-ranked cells become vision. Rank selection hits the count to one cell
    (plain thresholding would quantize the fraction to 1/16) while keeping the Bayer spread."""
    cells: dict = {}
    column: dict = {}
    for e, fr in enumerate(edge_frames(tier_poly)):
        o = orientation(fr["n"])
        for k in range(1, subdivide_edge(fr["length"], p)["n_std"] + 1):
            bay = column[o] = column.get(o, -1) + 1
            for phase in range(p.fin_period_floors):
                rank = (BAYER4[phase % 4][bay % 4], phase // 4, bay // 4)
                cells.setdefault(o, []).append((rank, phase, e, k))
    chosen: dict = {phase: set() for phase in range(p.fin_period_floors)}
    for o, items in cells.items():
        items.sort()
        for _, phase, e, k in items[:int(round(fractions[o] * len(items)))]:
            chosen[phase].add((e, k))
    return chosen


def _vision_fractions(tiers: list, floors_per_tier: list, p: FacadeParams) -> dict:
    """Per orientation: fraction of standard modules that are vision.

    Pooled over the whole tower (every edge of that orientation on every floor): short chamfer / notch / upper-tier
    edges carry proportionally more solid closer area, so a per-edge or per-tier target is often unreachable while
    the orientation total (what V4 measures) is not."""
    targets = dict(p.wwr_target)
    g = _glass_area(p.w_std, p.floor_h, p.spandrel_h, p)
    gross, n_std = {}, {}
    for poly, reps in zip(tiers, floors_per_tier):
        for fr in edge_frames(poly):
            o = orientation(fr["n"])
            gross[o] = gross.get(o, 0.0) + reps * (fr["length"] - 2.0 * p.corner_c) * p.floor_h
            n_std[o] = n_std.get(o, 0) + reps * subdivide_edge(fr["length"], p)["n_std"]
    fraction = {}
    for o in gross:
        fraction[o] = targets[o] * gross[o] / g / n_std[o] if n_std[o] else 0.0
        if fraction[o] > 1.0:
            raise LayoutError(f"WWR target {o}={targets[o]} unreachable: needs {fraction[o]:.3f} of modules as vision")
    return fraction


def build_schedule(p: FacadeParams | None = None) -> FacadeSchedule:
    p = p or default_params()
    assert_params(p)
    tiers = tier_plans(p)
    types: dict = {}
    levels = {"lobby": 0.0}
    for f in range(1, p.n_floors + 1):
        levels[f"floor{f}"] = p.lobby_h + (f - 1) * p.floor_h
    sched = FacadeSchedule(params=p, tiers=[list(map(list, t)) for t in tiers], levels=levels)

    rows = math.ceil(p.lobby_h / MAX_PANEL_H - 1.0e-9)
    panels, corners, fins = _band_panels(tiers[0], Band.LOBBY, p.lobby_h / rows, p, types, None, None)
    sched.bands.append({"band_id": "lobby", "band": Band.LOBBY.value, "tier": 0, "height": p.lobby_h / rows,
                        "rows": rows, "level": 0.0, "panels": panels, "corners": corners, "fins": fins})
    floors_per_tier = [sum(1 for f in range(1, p.n_floors + 1) if (f - 1) // p.setback_every == k)
                       for k in range(len(tiers))]
    fractions = _vision_fractions(tiers, floors_per_tier, p)
    for k, poly in enumerate(tiers):
        vision = _vision_cells(poly, p, fractions)
        for phase in range(p.fin_period_floors):
            floors = [f for f in range(1, p.n_floors + 1)
                      if (f - 1) // p.setback_every == k and (f - 1) % p.fin_period_floors == phase]
            if not floors:
                continue
            band_id = f"tier{k}-phase{phase}"
            panels, corners, fins = _band_panels(poly, Band.TOWER, p.floor_h, p, types, phase, vision[phase])
            sched.bands.append({"band_id": band_id, "band": Band.TOWER.value, "tier": k, "phase": phase,
                                "height": p.floor_h, "rows": 1, "panels": panels, "corners": corners, "fins": fins})
            sched.floor_types[band_id] = {"tier": k, "phase": phase, "floors": floors}
        panels, corners, fins = _band_panels(poly, Band.PARAPET, p.parapet_h, p, types, None, None)
        top = max(f for f in range(1, p.n_floors + 1) if (f - 1) // p.setback_every == k)
        levels[f"roof{k}"] = p.lobby_h + top * p.floor_h
        sched.bands.append({"band_id": f"parapet{k}", "band": Band.PARAPET.value, "tier": k, "height": p.parapet_h,
                            "rows": 1, "panels": panels, "corners": corners, "fins": fins, "level": levels[f"roof{k}"]})
    for f in range(1, p.n_floors + 1):
        k, phase = (f - 1) // p.setback_every, (f - 1) % p.fin_period_floors
        sched.floors.append({"floor": f, "tier": k, "level": levels[f"floor{f}"], "floor_type": f"tier{k}-phase{phase}"})
    sched.vision_fraction = fractions
    sched.types = types
    sched.stats = schedule_stats(sched)
    return sched


# ---------------------------------------------------------------- design-side statistics (S1 evidence)


def band_instances(sched: FacadeSchedule, band_id: str) -> int:
    """How many times a band is realized (floor bands repeat per floor; lobby per stacked row; parapet once)."""
    b = sched.band(band_id)
    return len(sched.floor_types[band_id]["floors"]) if b["band"] == Band.TOWER.value else b["rows"]


def design_wwr(sched: FacadeSchedule) -> dict:
    """Glass / gross area per orientation over the tower floor bands (design values; S5 re-measures on geometry)."""
    p = sched.params
    glass, gross = {}, {}
    for b in sched.bands:
        if b["band"] != Band.TOWER.value:
            continue
        reps = band_instances(sched, b["band_id"])
        frames = edge_frames(sched.tiers[b["tier"]])
        for e, fr in enumerate(frames):
            o = orientation(fr["n"])
            gross[o] = gross.get(o, 0.0) + reps * (fr["length"] - 2.0 * p.corner_c) * p.floor_h
        for rec in b["panels"]:
            if rec["kind"] == "vision":
                glass[rec["orientation"]] = glass.get(rec["orientation"], 0.0) + reps * _glass_area(
                    rec["w"], p.floor_h, p.spandrel_h, p)
    return {o: glass.get(o, 0.0) / gross[o] for o in sorted(gross)}


def schedule_stats(sched: FacadeSchedule) -> dict:
    counts: dict = {}
    for b in sched.bands:
        reps = band_instances(sched, b["band_id"])
        for rec in b["panels"] + b["corners"] + b["fins"]:
            counts[rec["type_id"]] = counts.get(rec["type_id"], 0) + reps
    fam = {}
    for tid, spec in sched.types.items():
        fam[spec["family"]] = fam.get(spec["family"], 0) + 1
    p = sched.params
    std_types = sorted(t for t, s in sched.types.items()
                       if s["family"] in ("vision", "solid") and s["w"] == _r(p.w_std) and s["h"] == _r(p.floor_h))
    fin_types = sorted(t for t, s in sched.types.items() if s["family"] == "fin")
    fin_err = [abs(max(-FIN_LIMIT, min(FIN_LIMIT, rec["fin_raw"])) - rec["fin"])
               for b in sched.bands for rec in b["panels"] if "fin_raw" in rec]
    return {
        "n_types": len(sched.types),
        "types_by_family": fam,
        "standard_panel_types": std_types,
        "fin_types": fin_types,
        "n_instances": sum(counts.values()),
        "instances_by_type": dict(sorted(counts.items())),
        "n_floor_types": len(sched.floor_types),
        "n_floors": sched.params.n_floors,
        "n_tiers": len(sched.tiers),
        "design_wwr": design_wwr(sched),
        "max_fin_quant_error": max(fin_err) if fin_err else 0.0,
        "height": sched.levels[f"roof{len(sched.tiers) - 1}"] + sched.params.parapet_h,
    }


if __name__ == "__main__":
    s = build_schedule()
    print(json.dumps({k: v for k, v in s.stats.items() if k != "instances_by_type"}, indent=1))


# ---------------------------------------------------------------- world frames (placement data; y_axis is always +Z)


def _frame(origin2, level: float, t) -> dict:
    return {"origin": (origin2[0], origin2[1], level), "x_axis": (t[0], t[1], 0.0), "y_axis": (0.0, 0.0, 1.0)}


def band_levels(sched: FacadeSchedule, band_id: str) -> list[float]:
    """Base level of every realization of a band (per floor; per lobby row; the parapet's roof)."""
    b = sched.band(band_id)
    if b["band"] == Band.TOWER.value:
        return [sched.levels[f"floor{f}"] for f in sched.floor_types[band_id]["floors"]]
    if b["band"] == Band.LOBBY.value:
        return [row * b["height"] for row in range(b["rows"])]
    return [b["level"]]


def panel_frame(sched: FacadeSchedule, band: dict, rec: dict, level: float) -> dict:
    fr = edge_frames(sched.tiers[band["tier"]])[rec["edge"]]
    return _frame(_add(fr["v0"], _mul(fr["t"], rec["s0"])), level, fr["t"])


def fin_frame(sched: FacadeSchedule, band: dict, rec: dict, level: float) -> dict:
    fr = edge_frames(sched.tiers[band["tier"]])[rec["edge"]]
    root = _add(_add(fr["v0"], _mul(fr["t"], rec["s"])), _mul(fr["n"], sched.params.frame_d))
    return _frame(root, level, fr["t"])


def corner_frame(sched: FacadeSchedule, band: dict, rec: dict, level: float) -> dict:
    """x = incoming edge tangent, origin = the building-line vertex."""
    poly = sched.tiers[band["tier"]]
    frames = edge_frames(poly)
    return _frame(tuple(poly[rec["vertex"]]), level, frames[rec["vertex"] - 1]["t"])


# ---------------------------------------------------------------- slabs + canopy (data)


def slab_plans(sched: FacadeSchedule) -> list:
    """Per tier: the building line pulled in by slab_gap (floor slabs and that tier's roof share it)."""
    return [offset_polygon([tuple(v) for v in poly], sched.params.slab_gap) for poly in sched.tiers]


def slab_instances(sched: FacadeSchedule) -> list[dict]:
    """Slab occupies [level, level + slab_t]: floor slabs from their floor level (behind the spandrel), roof slabs
    below the roof level (top = the roof / terrace surface, behind the top floor's head). A tier's first floor stands
    on the tier below's roof, so it gets no slab of its own; its panels start j/2 above that roof, which a floor-style
    slab at the roof level would cut through outside the upper building line."""
    p = sched.params
    out = [{"tier": 0, "level": 0.0, "role": "ground"}]
    for rec in sched.floors:
        if rec["tier"] > 0 and (rec["floor"] - 1) % p.setback_every == 0:
            continue
        out.append({"tier": rec["tier"], "level": rec["level"], "role": f"floor{rec['floor']}"})
    for k in range(len(sched.tiers)):
        out.append({"tier": k, "level": sched.levels[f"roof{k}"] - p.slab_t, "role": f"roof{k}"})
    return out


def canopy_box(sched: FacadeSchedule) -> dict:
    """South entrance canopy over the lobby's central modules on edge 0, snapped to module joints.
    Plan x in [x0, x1] along edge 0, y in [-(frame_d + joint + depth), -(frame_d + joint)], z = [z0, z0 + canopy_t]
    with z0 on the lobby row joint."""
    p = sched.params
    lobby = sched.band("lobby")
    fr = edge_frames(sched.tiers[0])[0]
    if abs(fr["t"][0] - 1.0) > 1.0e-12 or fr["n"][1] > -1.0 + 1.0e-12:
        raise LayoutError("edge 0 is not the south edge")
    inner = sorted((r for r in lobby["panels"] if r["edge"] == 0), key=lambda r: r["slot"])[1:-1]
    m = p.canopy_modules if (len(inner) - p.canopy_modules) % 2 == 0 else p.canopy_modules - 1
    if m < 1 or m > len(inner):
        raise LayoutError(f"canopy spans {m} of {len(inner)} south modules")
    first = (len(inner) - m) // 2
    x0 = fr["v0"][0] + inner[first]["s0"]
    x1 = fr["v0"][0] + inner[first + m - 1]["s0"] + inner[first + m - 1]["w"]
    y1 = fr["v0"][1] - (p.frame_d + p.joint)
    z0 = lobby["height"] if lobby["rows"] > 1 else lobby["height"] - p.canopy_t
    return {"x0": x0, "x1": x1, "y0": y1 - p.canopy_depth, "y1": y1, "z0": z0, "z1": z0 + p.canopy_t, "modules": m}
