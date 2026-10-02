"""u_link_motor_mount: 共享尺寸、派生基准与参数守卫链。

上件（``u_link.py``）与下壳（``shell.py``）由同一根 U 形杆剖分而来，所以两件
共用一套尺寸：放在这里，两个 notebook 都在 setup 里导入同一个 ``DIMS``，
装配时两件天然一致。

Coordinate convention (REQUIREMENTS.md):
  origin = 底部圆柱轴线中点; +X 沿连杆指向右臂; +Y 向上(U 开口); +Z 横向.
  受控基准面: 背面 y=back_y=rod_d/2*(2*back_cut_frac-1)（默认 75% 高度处 7.5）,
  安装面(槽底) y=d_motor/2, 臂端面 y=D; 臂轴线 x=±L/2.
"""

from __future__ import annotations

from dataclasses import dataclass

# 命名特征面 tag（QL 索引入口）
TAG_MOUNT_LEFT = "feature.motor_mount_floor_left"
TAG_MOUNT_RIGHT = "feature.motor_mount_floor_right"
TAG_BACK = "feature.back_face"
TAG_SHELL_RIM = "feature.shell_rim_face"
TAG_SHELL_FLOOR = "feature.shell_hole_floor"  # 平底面（第一刀平面）


@dataclass(frozen=True)
class ULinkDimensions:
    """两件共用的尺寸（mm / deg）。字段默认值即交付值。"""

    L: float = 80.0  # 臂轴跨距/底宽（两电机轴线间距）
    D: float = 20.0  # 臂端面高度（自 y=0）；2026-08-26 用户定向 40->20
    rod_d: float = 30.0  # U 形圆杆直径
    thickness: float = 6.0  # 电机槽壁余量（槽壁厚=thickness/2）
    # 电机深度（槽底 y=d_motor/2）；S11 用户定向加深 30->19，安装面到 back face = wall_t
    d_motor: float = 19.0
    r_corner: float = 17.0  # 拐角中心线圆弧半径（须∈(rod_d/2, D)）；随 D=20 联动 20->17
    fillet_r: float = 1.2  # 全局倒角半径（<thickness/4）
    # 背切平面位置（底管高度百分比；0.5=中心线，0.75=中心线上移半径一半）
    back_cut_frac: float = 0.75
    # S10 剖分+轮廓腔（2026-08-26 用户定向：弃方形腔，75% 剖分两件+shell）
    wall_t: float = 2.0  # shell 壁厚=腔内偏移量（轮廓贴合由 r-wall_t 扫掠实现）
    boss_h: float = 5.0  # boss 柱高=剖分面下方悬臂长（腔带高）
    boss_d: float = 5.0  # boss 柱外径
    boss_x: float = 12.0  # boss 轴 x 位（±，剖分面中央区）
    boss_hole_d: float = 2.7  # boss 中心自攻孔径（=shell 底孔内径，用户指定一致）
    boss_hole_depth: float = 3.0  # boss 盲孔深（自柱底向上，留底 ≥0.5）
    rib_t: float = 1.2  # 三角筋厚
    rib_len: float = 3.0  # 三角筋水平边长（沿剖分面外伸）
    gusset_chamfer: float = 0.3  # 三角筋斜边倒角（先于全局圆角执行）
    # S13 电机槽走线窗（2026-08-26 用户定向）
    cable_w_off: float = 3.0  # 走线窗底边高于安装面距离（用户规定 ∈[3,5]，推荐 3）
    cable_w_h: float = 5.0  # 走线窗高（y 向）
    cable_w_w: float = 10.0  # 走线窗宽（周向弦长）；S14 用户定向 5->10
    cable_w_rr: float = 1.2  # 走线窗角圆角（rounded-rect 源型，防割手免 fillet）
    # 走线窗相位（相对 +X；45°=对角布置，避让内向盲区——0/180° 内向在窗低段撞拐角熔合区）
    cable_w_phase: float = 45.0

    # ---- derived datums ----
    @property
    def r(self) -> float:
        """杆半径。"""
        return self.rod_d / 2.0

    @property
    def pocket_r(self) -> float:
        """电机槽半径 (rod_d-thickness)/2。"""
        return (self.rod_d - self.thickness) / 2.0

    @property
    def floor_y(self) -> float:
        """安装面(槽底) y = d_motor/2。"""
        return self.d_motor / 2.0

    @property
    def back_y(self) -> float:
        """背切平面 y = r*(2f-1)：f=0.5 中心线，f=0.75 即底管高度 75% 处。"""
        return self.r * (2.0 * self.back_cut_frac - 1.0)

    @property
    def boss_tip_y(self) -> float:
        """boss 尖端平面 = shell 地板顶面。"""
        return self.back_y - self.boss_h

    @property
    def shell_bottom_y(self) -> float:
        """shell 平底（第一刀平面）= boss 尖端下移 wall_t。"""
        return self.boss_tip_y - self.wall_t

    def check(self) -> None:
        """参数约束链（REQUIREMENTS.md；退化参数会静默产出坏几何，须显式失败）。"""
        r, rp = self.r, self.pocket_r
        by = self.back_y
        depth = self.D - self.floor_y
        assert self.floor_y < self.D, "d_motor/2 必须小于 D（槽底低于臂端）"
        assert self.r_corner > r, "r_corner 必须大于杆半径（拐角内退化会静默产出坏几何）"
        # 端面环宽 = r-rp = thickness/2，环内外两边同时倒角，2*fr 不得相遇吃穿环
        assert self.fillet_r < self.thickness / 4.0, \
            "fillet_r 必须小于 thickness/4（端面环宽 thickness/2 内双侧倒角不得相遇）"
        assert self.L > 2.0 * self.r_corner, "L 必须大于 2*r_corner（底部直段存在）"
        assert self.D > self.r_corner, "D 必须大于 r_corner（臂直段存在）"
        assert self.fillet_r < rp, "fillet_r 必须小于槽半径 (rod_d-thickness)/2（槽底倒角吃穿槽壁）"
        assert self.fillet_r < depth, "fillet_r 必须小于槽深 D-d_motor/2（槽底倒角越过槽口）"
        # 背切平面范围
        assert 0.5 <= self.back_cut_frac < 1.0, \
            "back_cut_frac 须∈[0.5,1)（0.5=中心线半切；>=1 切穿底管）"
        assert by < self.floor_y, "背切平面必须低于槽底 d_motor/2（安装面到背面须留壁厚）"
        assert self.floor_y >= by + self.wall_t, \
            "d_motor/2 须 >= back_y+wall_t（电机安装面到 back face 至少标准壁厚）"
        # 剖分+轮廓腔+boss 可行性
        opening_half = ((r - self.wall_t) ** 2 - by ** 2) ** 0.5  # 腔带顶部开口 z 半宽
        assert 0.5 <= self.wall_t <= r / 3.0, \
            "wall_t 须∈[0.5, rod_d/6]（壁过薄无法制造, 过厚腔不可用）"
        assert self.boss_h < by - 2.0, "boss_h 须 < back_y-2（腔带底部留结构余量）"
        assert self.boss_hole_depth <= self.boss_h - 0.5, "boss 盲孔须留底 ≥0.5"
        assert self.boss_hole_d / 2.0 + 0.5 + 0.3 <= self.boss_d / 2.0 - 0.3, \
            "boss 孔壁过薄（孔半径+0.5 ≤ 柱半径-0.3）"
        assert self.boss_d / 2.0 + self.rib_len <= opening_half - 0.5, \
            "±z 筋须在腔开口内（boss_r+rib_len ≤ sqrt((r-wall_t)²-back_y²)-0.5）"
        assert self.boss_x + self.boss_d / 2.0 + self.rib_len <= self.L / 2.0 - self.r_corner - 2.0, \
            "±x 筋须在底部直段腔内（远离拐角）"
        assert self.rib_t >= 2.0 * self.gusset_chamfer + 0.3, "筋厚须容双侧倒角"
        # 走线窗（用户规定: 底边距安装面 ∈[3,5]；推荐 3）
        assert 3.0 <= self.cable_w_off <= 5.0, "cable_w_off 须∈[3,5]（用户规定：≥3 且 ≤5）"
        assert self.floor_y + self.cable_w_off + self.cable_w_h <= self.D - 2.0, \
            "窗顶须低于臂端面圆角区（floor+off+h ≤ D-2）"
        assert self.cable_w_rr < self.cable_w_w / 2.0 and self.cable_w_rr < self.cable_w_h / 2.0, \
            "窗角圆角须小于半宽/半高"
        assert self.cable_w_w <= 1.6 * rp, \
            "窗宽不得吃穿窗间壁（w ≤ 1.6×槽半径；w=10/rp=12 时窗间弧余 34mm）"


DIMS = ULinkDimensions()
