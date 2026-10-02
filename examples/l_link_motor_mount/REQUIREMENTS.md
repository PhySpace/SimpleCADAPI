# Requirements: l_link_motor_mount（参数化 L 形垂直双电机连杆）

- Inputs: 用户 prose（2026-09-30）+ 三轮批量确认 + 两轮自由澄清（剖分形状；电机2 转接板）；参考结构 `examples/u_link_motor_mount/`（沿用其截面/倒角/圆柱槽/命名面/剖分壳体/boss/走线细节做法）；概念图 `sketch/concept_options.png`
- Route: `workflows/assembly-product-build.md`（上件 + 壳体 + 电机2 转接板 三件 + 装配；每件走 single-part Role 3/4 阶段门）
- Functional goals:
  1. 机械臂 link，两端各装一个电机，**两电机转轴互相垂直**：电机1 轴 ∥ Y（左臂端），电机2 轴 ∥ X（右端，与连杆同轴，roll 关节式）
  2. 外形圆润：圆截面扫掠 + 全局倒角（同 U-link 风格）
  3. 两安装面确定性命名，QL 可索引
  4. 沿轴线剖分出可拆壳体（内腔走线 + boss 螺丝压紧），剖分**不切进右端电机槽**
  5. 长度由 `L` 驱动，结构自适应

## Geometry targets（分区，已确认）

1. **L 形扫掠杆**：⌀`rod_d` 圆截面沿开放路径扫掠——左臂 (0, D) 竖直向下 → 拐角中心线圆弧 R=`r_corner`（圆心 (r_corner, r_corner)）→ 底部直段沿 +X 至右端面 x = x_end。
   左臂端盖平面 y=D（法向 +Y）；右端盖平面 x=x_end（法向 +X）。路径为平面 XY 路径（草图层级，同 U-link `_u_path_wire` 做法，3 实体开放链）。
2. **左电机槽（轴 Y）**：⌀(rod_d−thickness) 圆柱沿 Y 自 y=d_motor/2 向上越过臂端 cut；槽底 = **安装面 1**：平面、法向 +Y、y=d_motor/2、心 (0, d_motor/2, 0)。
   命名 `feature.motor_mount_floor_left`。槽深 = D − d_motor/2（=10.5），槽壁 = thickness/2。
3. **右电机槽（轴 X，与连杆同轴）**：⌀(rod_d−thickness) 圆柱沿 X 自 x = L − `plate_t` 向 +X 越过右端面 cut；槽底 = **安装面 2**（贴转接板）：平面、法向 +X、x = L − plate_t（默认 75）、心 (L−plate_t, 0, 0)。
   命名 `feature.motor_mount_floor_right`。**电机2 落座面 = 转接板外表面 x = L**（用户确认"槽底下沉 plate_t"），故电机位置、走线窗、右端面均不因转接板改变：
   电机侧槽深 = 左槽深 = D − d_motor/2 → **x_end = L + (D − d_motor/2)**（默认 90.5）；物理槽深 = 10.5 + plate_t = 15.5。
   安装面 2 上开**三叉定位凹槽**（见区 10）。
4. **"l" 形剖分线（唯一一刀，无丢弃面）**——前视 XY 中的剖分曲线，沿 Z 贯穿：
   - 水平段 y = `back_y` = r·(2·back_cut_frac−1)（默认 7.5，同 U-link），自左端起至 x_a = `split_arc_frac`·L（默认 0.60·80 = 48）；
   - 相切圆弧：自 (x_a, back_y) 起、切向 +X，**向壳体一侧（−Y）弯下**，至 x_b = `split_end_frac`·L（默认 0.75·80 = 60）处切向变为 −Y；弧半径 R_s = x_b − x_a（默认 12），圆心 (x_a, back_y − R_s) = (48, −4.5)；
   - 竖直段 x = x_b，自 y = back_y − R_s 向下穿出管底。
   - **上件** = 曲线上/右侧：左臂 + 左槽 + y∈[back_y, r] 上半条 + x ≥ x_b 整圆套筒（含右槽）。
   - **壳体** = 曲线下/左侧：y ≤ back_y 的圆底管壳（**无平底，保留原始管底曲面**），右端顺圆弧收起，至 x_b 竖直截止。
   - 上件 x∈[x_b, L−plate_t−groove_d] 整圆套筒段**保持实心**（用户选"方案 a + 转接板"；电机2 经转接板固定，不需背面通道）。
5. **壳体内腔（轮廓贴合）**：内偏移 = 半径 r−wall_t 沿同路径扫掠（精确内偏移，同 U-link S10）∩ y ≤ back_y；右端腔壁沿圆弧+竖直段内偏 wall_t（壳体右端为等厚弧形端壁）；
   腔在剖分面敞开（上件下底面即腔顶）。左槽底 y=d_motor/2 到剖分面 back_y 的壁 = wall_t（=2，U-link S11 规则），左槽底将来钻孔直通内腔（pc=8 孔位 x∈[−8,8] 均落在腔内：距管中心线 ≤9.8 < r−wall_t=13 ✓）。
6. **长 boss（上件）+ 壳底沉头螺丝**：
   - 上件自剖分面 back_y 向下悬伸 2 根 boss（Ø`boss_d`，z=0，x = `boss_x1`/`boss_x2`），落在壳体底部直段腔内（远离左拐角与剖分弧）；
   - boss 底端贴合壳体内壁局部内凸台（pad）顶面；boss 中心自攻盲孔 Ø`boss_hole_d` 自底向上；boss 根部 4 向三角筋（高 `gusset_h`、水平边 `rib_len`、厚 `rib_t`，斜边倒角 `gusset_chamfer`）；
   - 壳体圆底在 boss 正下方：外侧锪平小平台 + 90° 沉头通孔（Ø`shell_hole_d` 通 + Ø`csink_d`×`csink_depth` 锥口，自外向内），内侧局部 pad 加厚到 wall_t+`pad_t`。
7. **走线窗（S13/S14 继承）**：两槽侧壁各 4 窗（rounded-rect 源型，宽 10 / 高 5 / 角 R1.2，相位 45° 对角布置），窗"底边"距各自电机落座面 `cable_w_off`=3（沿各自电机轴；右侧基准为板面 x=L，而非下沉后的槽底）。
   左槽窗围绕 Y 轴（y∈[12.5, 17.5]）；右槽窗围绕 X 轴（x∈[L+3, L+8] = [83, 88]，距右端面 2.5）。窗在倒角后最后一步切出。
8. **壳体走线口（S11/S12 继承）**：壳体左端外壁（左拐角下方，y ≤ back_y 段，外壁 x≈−13.6）开 1 个 rounded-rect 贯穿口，宽 `notch_w`=9（z）× 高 `notch_h`=7（y∈[back_y−notch_sill−notch_h, back_y−notch_sill] = [0, 7]），角 R`notch_rr`=1.5。
   **同轴电机走线孔**（S6 用户追加「同轴电机这里也要有一个孔来走线」，位置选壳底 −Y）：壳体底部直段、boss_x2 筋尖与右弧形端壁之间，同圆角矩形源型转 90°
   （沿 X = notch_h=7、沿 Z = notch_w=9、角 notch_rr），中心 x = 派生 `coax_hole_x` = ((boss_x2+boss_d/2+rib_len) + (x_b−wall_t))/2（默认 51.75，x∈[48.25, 55.25]），自腔内向 −Y 贯穿管底。
9. **圆角**：
   - 上件：R`fillet_r`=1.2 仅倒两端盖 4 条 rim 圆（臂端外/内 rim、右端面外/内 rim；S6 计划经用户确认）；**剖分接口边保持锐边**（配合面，同 U-link 结论）；
     两槽底边（y=9.5 / x=75，法兰与转接板落座）保持锐边（偏离 U-link：落座面需完整平面）；扫掠相切缝、boss/筋边不倒。
   - 壳体：防割手 R`safe_fillet_r`=0.6 倒两走线口（左端走线口 + 壳底同轴走线孔，见区 8）的**外环**；
     走线口内环不倒（R0.6 圆角溢出剖分面 y=back_y）；锪平平台外缘不倒（侧壁 0.1–0.4 < R，内核失败）；沉头锥口不倒（螺钉座面）；剖分接口边保持锐边。
   - 转接板：外圆边 R`safe_fillet_r`；三叉凸起根部/顶边保持锐边（配合面）。
10. **电机2 转接板（第 3 件，`adapter_plate.py`）+ 三叉定位 + 径向固定**：
    - 板体：圆盘 ⌀`plate_d` = (rod_d−thickness) − 2·`plate_gap`（默认 24−0.2 = 23.8）、厚 `plate_t` = 5（守卫 ≥ 5，用户要求），装配位 x∈[L−plate_t, L]；中心过孔 ⌀`m2_center_d`（避让电机轴/卡簧）。
    - 电机螺孔：`m2_hole_n` 个 ⌀`m2_hole_d` 通孔 @ PCD `m2_pcd`，**90° 沉头自板背面（面向安装面 2 一侧）**，头部沉入 `m2_head_recess`，不凸出、不顶安装面（用户要求）。
    - **三叉定位（奔驰标）**：3 条径向臂 @ 角度 `key_phase` + k·120°，臂宽 `key_w`、凸起高 `key_h` = 2（用户给定），位于板背面；
      安装面 2 上对应凹槽：臂宽 `key_w + 2·key_gap`、深 `groove_d` = 2.2（用户给定），**完整臂 r∈[0, key_r_out]**。
    - **兼容方案（用户："上面三个都可以兼容"）**——同一上件凹槽，换板即可，三种凸起均为完整臂的子集：
      | variant | 孔型 | 凸起 | 适用 |
      | --- | --- | --- | --- |
      | `star3` | 3 孔 120°，孔位在两臂之间（相位 key_phase+60°） | 完整三叉 r∈[m2_center_d/2+0.5, key_r_out] | 3 孔电机 |
      | ~~`outer4`~~ | 4 孔 90° | ~~外缘 3 短块~~ **已删除**（用户确认：外块 ≤1.3 mm 无效） | — |
      | `center4` | 4 孔 90° | 中心 3 短臂 r∈[0, key_r_in]（沉头口以内，**无中心过孔**） | 4 孔、底面中心平整的电机 |
      **预设选择 = Python `enum.Enum`（用户要求："通过一个 enum 决定兼容盘面"）**：`class PlatePreset(Enum): STAR3 / CENTER4`；
      `adapter_plate.py` 以 `if preset is PlatePreset.STAR3: … elif …CENTER4: …` 分支决定**拓扑结构**（孔数/相位、凸起臂段、有无中心孔），
      而非仅改数值——这是代码参数化相对特征树参数化的核心优势。`Var` 仅承载标量（尺寸），enum 为构建期参数，所选 preset 写入零件 metadata（`plate_preset`）。
      默认 `STAR3`；两个预设均构建、均过 V11/V12、均导出。上件凹槽与 preset 无关（完整三叉，两种凸起均为其子集）。4 孔与 120° 三叉最小角距固有 15°（孔型 mod 90° vs 臂 mod 30°），凸起边到沉头口 ≥ `min_web`=0.3 的可用臂段（Role 1 计算）：
      | 沉头 | key_w | 可用 r ≤ | 可用 r ≥ | 外块长（板 r 11.9−0.3） |
      | --- | --- | --- | --- | --- |
      | M2.5 ⌀5.1 | 2.5 | 4.19 | 11.27 | 0.33 |
      | M2.5 ⌀5.1 | 2.0 | 4.48 | 10.97 | 0.63 |
      | M2 ⌀4.0 | 2.5 | 4.84 | 10.61 | 0.99 |
      → **`outer4` 外块 ≤ 1.3 mm，定位无效 → 已删除（用户确认）**；`center4` 臂长 ≈ 4.2 mm 且要求取消中心过孔；`star3` 臂到孔心 6.93 ≥ 4.1 ✓ 完整。
    - **径向固定（用户选 3×M2 沉头自攻 120°）**：径向螺丝 @ 角度 `key_phase` + k·120°（与三叉臂同相，避开 3 孔方案孔位 60°），轴向位置 x = L − plate_t/2；
      上件套筒壁（r 12→15，厚 3）：⌀`rad_clear_d` 过孔 + 外侧锪平（r=15 曲面）+ 90° 沉头，头部与外圆齐平；
      转接板侧面：⌀`rad_pilot_d` 自攻导孔，径向深 `rad_pilot_depth`（每变体由守卫截短，保证到电机孔/沉头口剩余壁 ≥ min_web）。
    - 装配顺序：桌面上用沉头螺丝把电机2 拧到转接板 → 板（带电机）自右端口推入槽，三叉入凹槽定相 → 自套筒外侧拧 3×M2 径向螺丝。

## Units / coordinate convention

mm / deg。原点 = 左电机轴线与底部直段轴线的交点；+X 沿连杆指向右电机；+Y 向上（左槽开口方向）；+Z 横向。
受控基准：左安装面 y=d_motor/2 @ x=0；电机2 落座面 x=L；安装面 2 x=L−plate_t；剖分水平段 y=back_y；左臂端面 y=D；右端面 x=L+(D−d_motor/2)。对称性：关于 XY 平面（z 镜像）对称。

## Named parameters (Var)

- 沿用 U-link 默认（用户确认）：`D=20`、`rod_d=30`、`thickness=6`（槽 ⌀24）、`d_motor=19`（槽底距轴线 9.5，槽深 10.5）、`r_corner=17`、`fillet_r=1.2`、`back_cut_frac=0.75`（back_y=7.5）、`wall_t=2.0`
- `L = 80`：**左电机轴线 → 电机2 落座面（转接板外表面）** 的 X 距离（用户确认 L 基准 + 槽底下沉 plate_t）
- `split_arc_frac = 0.60`、`split_end_frac = 0.75`（基于 L；用户给定，"例如"值 → 暴露为 Var）
- boss/连接（ASSUMED，沿用 U-link 值 + 适配）：`boss_d=5.0`、`boss_hole_d=2.7`、`boss_hole_depth=6.0`（ASSUMED：M3×8 自攻，入 boss ≈6）、`boss_x1=25`、`boss_x2=40`（ASSUMED：直段腔 [r_corner, x_a] 内，筋距拐角/弧 ≥2）、`rib_t=1.2`、`rib_len=3.0`、`gusset_h=5.0`、`gusset_chamfer=0.3`、`shell_hole_d=2.7`、`csink_d=5.4`、`csink_depth=(csink_d−shell_hole_d)/2=1.35`（90° 派生，S5 改为非 Var）、`spot_depth=0.4`（S5 修正：0.3 时锪平侧壁在 z 向端点只剩 0.007 薄片，改为 ≥ 矢高 + 0.1）、`spot_d=5.9`（S5 新增：锪平环宽 0.25，否则锥口与锪平圆重合、平台退化）、`pad_t=1.0`、`pad_d=boss_d+3`
- 走线（沿用）：`cable_w_off=3`、`cable_w_h=5`、`cable_w_w=10`、`cable_w_rr=1.2`、`cable_w_phase=45`（S10：仅 |phase mod 90 − 45| ≤ 5 可行，窗朝 +X 会钻入拐角内弯）、`notch_w=9`、`notch_h=7`、`notch_sill=0.5`、`notch_rr=1.5`、`safe_fillet_r=0.6`
- 转接板（ASSUMED 除注明外）：`plate_t=5`（用户 ≥5）、`plate_gap=0.1`（径向）、`preset=PlatePreset.STAR3`（enum，非 Var）、`m2_hole_n`（由变体定 3/4）、`m2_hole_d=2.7`（M2.5 过孔）、`m2_pcd=16`、`m2_csink_d=5.1`（90°，M2.5 沉头 dk4.7 → 头顶低于板面 `m2_head_recess`≈0.2）、`m2_center_d=6`（star3；center4 强制 0）、
  `key_h=2.0`（用户）、`groove_d=2.2`（用户）、`key_w=2.5`、`key_gap=0.1`（凹槽宽 2.7）、`key_phase=0`（角度在 YZ 面内自 +Y 量向 +Z；臂 0/120/240 关于 z 镜像对称）、`key_r_out=10.9`（S10 修正：11.2 时臂端角距板背面外圆圆角仅 0.03，参数微增即割断背面平面 → 守卫 hypot(key_r_out, key_w/2) ≤ 板半径 − rf − 0.3）、`min_web=0.3`、
  `rad_screw_n=3`（用户）、`rad_clear_d=2.2`、`rad_csink_d=4.0`、`rad_spot_d=4.2`（S7 新增：锪平环宽 0.1，同 S5 理由）、`rad_spot_depth=0.25`（S7 修正：0.15 时 Ø4.2 锪平在 r=15 曲面矢高 0.148 → 侧壁仅 0.002 薄片，改为 ≥ 矢高 + 0.1）、`rad_pilot_d=1.6`、`rad_pilot_depth=4.0`（每变体守卫截短）
- 约束链（初版，Role 3 以边界探针补全）：
  `d_motor/2 < D`；`rod_d/2 < r_corner < D`；`fillet_r < thickness/4`；`fillet_r < rp`；`fillet_r < D − d_motor/2`；
  `d_motor/2 ≥ back_y + wall_t`（左槽底壁）；`0.5 ≤ back_cut_frac < 1`；
  `r_corner + 2 < x_a < x_b`；`R_s = x_b − x_a ≤ back_y + r − wall_t − 1`（S10 修正：弧底须高于壳腔底 ≥ 1，否则腔内端壁竖直段消失；旧界 `≤ back_y + r` 在切点处剖分竖直面整面消失）；`x_b + wall_t ≤ L`（右安装面后方实心套筒 ≥ wall_t；默认 20）；
  `boss_x1 − boss_d/2 − rib_len ≥ r_corner + 2`；`boss_x2 + boss_d/2 + rib_len ≤ x_a − 2`（S5 修正：壳腔在剖分面下 wall_t 带内端界为 x=x_a）；`boss_x2 − boss_x1 ≥ 2(boss_d/2 + rib_len) + 1`（筋不相碰）；
  `boss_d/2 + rib_len ≤ sqrt((r−wall_t)² − back_y²) − 0.5`（筋在腔开口内，10.6）；
  `wall_t + pad_t − spot_depth − csink_depth ≥ 1.0`（沉头下剩余孔壁）；`boss_hole_depth ≤ boss 长 − 0.5`；`rib_t ≥ 2·gusset_chamfer + 0.3`；
  `pad_top ≥ −sqrt((r−wall_t)² − (pad_d/2)²)`（pad 顶面完整）；`pad_d ≥ boss_d + 1`；`spot_depth − (r − sqrt(r² − (spot_d/2)²)) ≥ 0.1`（锪平整平且侧壁不成薄片，S5 修正）；`spot_d ≥ csink_d + 0.2`；
  同轴走线孔：`(x_b−wall_t) − (boss_x2 + max(boss_d/2+rib_len, pad_d/2, spot_d/2)) ≥ notch_h + 2`（孔窗）、刀具顶在腔内、孔 x 区间处腔顶 ≥ 刀具顶 + 1；
  `safe_fillet_r < notch_rr`、`safe_fillet_r + 0.5 ≤ wall_t`、走线口外环圆角顶 ≤ back_y − 0.05；
  `cable_w_off ∈ [3,5]`；窗顶 ≤ 槽口 − 2（两槽各自）；`cable_w_w ≤ 1.6·rp`；
  `plate_t ≥ 5`；`x_b + wall_t ≤ L − plate_t − groove_d`（凹槽底后实心套筒，默认 12.8）；`groove_d > key_h`；`m2_csink 锥深 + m2_head_recess ≤ plate_t − 2`；
  `key_r_out ≤ plate_d/2 − 0.5`；三叉臂/凸起到沉头口 ≥ min_web（每变体）；径向导孔末端到电机孔/沉头口 ≥ min_web；径向孔 x 区间与走线窗 x 区间不相交；
  径向沉头（S7）：`rad_csink_d > rad_clear_d`、`rad_spot_d ≥ rad_csink_d + 0.2`、`rad_spot_depth − (r − sqrt(r² − (rad_spot_d/2)²)) ≥ 0.1`、`(r − rp) − rad_spot_depth − (rad_csink_d − rad_clear_d)/2 ≥ 1`（沉头下孔壁）、径向孔 x 区间 ⊂ (L − plate_t, L)（落在板厚内、不碰凹槽）；
  S10 补充：锥口 overshoot = min(0.2, (rad_spot_d − rad_csink_d)/4)（须留在锪平圆柱内，否则锪平侧壁被削出锥带）；`rad_screw_n ∈ {1, 3}`（2/4 使导孔落到 STAR3 180° 电机孔上）

## Fastening & mounting

- 电机1：法兰贴左安装面（+Y），⌀24 槽自定心；槽底钻孔（下轮）螺丝穿 2mm 壁进入壳体内腔。
- 电机2：沉头螺丝（自转接板背面穿入电机底座）固定到转接板，头部沉入板面 → 板背面平贴安装面 2；板 ⌀23.8 在 ⌀24 槽内自定心，三叉凸起入凹槽定相；
  3×M2 沉头自攻自套筒外侧径向拧入板侧面，承担轴向保持。Envelope（S7 重核）：套筒壁 3（锪平 0.25 + 沉头锥 0.9）→ 过孔段 1.85；头顶 r=14.75 < 15 不凸出；M2×6 → 入板 ≈ 6 − 2.75 − 0.1 ≈ 3.15 ≤ rad_pilot_depth ✓（变体截短后重核）。
- 上件↔壳体：2×M3 沉头自攻，**自壳底外侧向 +Y 插入**，穿壳底进上件 boss 盲孔。
  Envelope math：壳底外表面 y=−r=−15（管底，曲面）；锪平 Ø5.9（沉头口 Ø5.4 外留 0.25 平台环）在 r=15 曲面上矢高 0.293 → spot_depth=0.4（侧壁最薄 0.107）；
  壳底内侧 pad 加厚 → 局部壁厚 wall_t+pad_t = 3.0；沉头锥深 1.35 → 锥下剩余 Ø2.7 孔壁 3.0−0.4−1.35 = 1.25 ≥ 1.0 ✓；
  boss 长 = back_y − (−(r−wall_t−pad_t)) = 7.5 + 12 = 19.5，底面贴 pad 顶面 y=−12（z=0 处；pad 顶面为平面，boss 底端平面贴合）；
  M3×8 沉头（全长含头）穿局部壁 3.0−0.4=2.6 → 入 boss ≈ 5.4；boss_hole_depth=6 ≥ 5.4+0.5 且 ≤ 19.5−0.5 ✓。
- 装配：上件 ground；壳体 fixed，经剖分面 placement connector（z 轴 −Y，原点 (0, back_y, 0)）同坐标系零残差；转接板 fixed，经安装面 2 connector（原点 (L−plate_t,0,0)，z=+X，x 轴 = key_phase 方向）；三件均在安装位建模，placement=identity。
  额外暴露电机接口 connector：`motor_left`（原点左安装面心，z=+Y）、`motor_right`（原点**转接板外表面心 (L,0,0)**，z=+X；tag `feature.motor_seat_right` 在板上）（ASSUMED，供下游电机装配）。

## Service conditions

未声明（不做强度/FEM 断言）。长 boss（Ø5×19.5，长径比 ~4）刚度未分析，仅几何可行性。

## Export targets

`.scadpkg`（装配包）+ `STEP` + `STL` → `examples/l_link_motor_mount/out/`（ASSUMED，同 U-link）；转接板每个 preset 各一份 STEP/STL（`adapter_plate_star3.*`、`adapter_plate_center4.*`）

## Verification intent（建模前写定）

- V1 上件/壳体各为单实体、正体积；未倒角扫掠 bbox = X[−r, L+D−d_motor/2] × Y[−r, D] × Z[±r] = [−15, 90.5]×[−15, 20]×[±15]
- V2 两安装面各恰 1：QL 按 tag 命中；左 = 平面 +Y @ (0, 9.5, 0) 面积 π·12²；右 = 平面 +X @ (75, 0, 0) 面积 π·12² − 三叉凹槽口面积；板上落座面 `feature.motor_seat_right` @ x=80；两电机轴法向点积 = 0（**垂直**）
- V3 左槽深 10.5、右槽物理深 15.5（电机侧 10.5 自板面 x=L 起）、槽壁 = 3；右槽为**整圆**（槽壁圆柱面完整 360°，剖分未切入：x ≥ x_b 截面无剖分面）
- V4 剖分面几何：上件接口 = 水平平面 y=back_y（x ≤ x_a）+ 圆柱面 R_s 轴 Z 心 (x_a, back_y−R_s) + 竖直平面 x=x_b；壳体接口与之贴合；上件与壳体**采样零干涉**，二者 ∪ ≈ 原杆（去腔/boss/孔后体积记账）
- V5 壳体：圆底保留（y_min = −r），内腔壁厚采样 ≥ wall_t−0.1；右端弧形端壁厚 wall_t；左槽底到腔 = wall_t
- V6 boss×2：位置 (x_i, z=0)、底面贴 pad 顶面（接触间隙 0）、盲孔 Ø2.7 与壳底通孔同轴；沉头锥面 ×2、锪平平台 ×2、锥下剩余壁 ≥1.0
- V7 走线窗 8 个全开（窗中心采样为空、窗间壁完好）、底边距各自安装面 3±0.3；右槽窗围绕 X 轴
- V8 壳体走线口贯穿（口中心采样为空）、上下 sill 完好；同轴走线孔贯穿管底（孔内采样空、孔周管壁实），不碰 pad/锪平/弧形端壁
- V9 倒角后命名面仍可 QL 索引；剖分接口边未倒角
- V10 装配 solve 零残差；scadpkg 新进程重开；STEP/STL 非空
- V11 转接板（每变体）：单实体；厚 plate_t、⌀23.8；电机孔 n 个 @ PCD16 且沉头锥面 n 个在背面、头部包络（⌀4.7 锥体沉入 0.2）不越出背面；凸起高 2、全部落在上件凹槽内且与凹槽壁采样零干涉；装配后板背面与安装面 2 接触间隙 0（凸起顶到槽底留 0.2）
- V12 径向固定：套筒 3 过孔+沉头 @ 0/120/240°、x=77.5，与板导孔同轴；沉头头部包络不凸出 r=15 外圆；导孔末端到电机孔/沉头口 ≥ min_web；径向孔不与走线窗、凹槽相交
- 渲染：iso + 前视（XY）+ 右视（沿 −X 看右槽）命名视图，隔离子代理按区域评审

## Ask-or-Record ledger

| item | asked/assumed | answer/value |
| --- | --- | --- |
| 构型 | asked | L 形（一端同轴）：左槽轴 Y，右槽轴 X 与连杆同轴 |
| 背面/通孔路径 | asked | 沿用剖分+壳体方案 |
| 交付范围 | asked | 主体+壳体+装配（→ assembly workflow） |
| 尺寸/电机规格 | asked | 沿用 U-link 默认，两电机同规格 |
| 剖分形状 | asked (用户自由描述) | "l" 形：沿轴线水平切，0.60·L 起圆弧弯向壳体侧（−Y），0.75·L 处竖直出，不切进右槽 |
| 丢弃面 y=0.5 | asked (用户定向) | 不需要——只一刀，壳体保留圆底 |
| L / 百分比基准 | asked | 左电机轴 → 右安装面；x_end = L + 槽深 |
| 连接方式 | asked | 长 boss，螺丝从壳底装 |
| 电机2 螺孔 | asked → superseded | ~~本轮套筒保持实心~~ → 用户选"方案 a（实心套筒）+ 转接板" |
| 转接板要求 | asked (用户定向) | 电机螺丝沉头不凸出；板厚 ≥5；侧面+套筒开径向孔；背面奔驰标三叉凸起高 2、安装面凹槽深 2.2 |
| 电机2 孔型 | asked | "做兼容方案，三个都兼容" → 解读为换板预设（Enum `PlatePreset`），上件共用一组完整三叉凹槽（各凸起均为完整臂子集） |
| outer4 可行性 | asked | 外块 ≤1.3 mm 无效 → 删除（用户确认） |
| 预设机制 | asked (用户定向) | Python Enum `PlatePreset` + if 分支决定盘面拓扑 |
| 槽底位置 | asked | 下沉 plate_t：安装面 2 x=75，电机落座面 = 板面 x=L=80 |
| 凸起 2 / 槽 2.2 | asked | 仅指高度/深度；宽度 ASSUMED key_w=2.5、槽宽 2.7 |
| 径向螺丝 | asked | 3×M2 沉头自攻 120°（与三叉臂同相 0/120/240） |
| 电机2 螺丝规格 | assumed | M2.5 @ PCD16，⌀2.7 过孔 + ⌀5.1 90° 沉头（参数化） |
| 板中心过孔 | assumed | ⌀6（star3）；center4 为 0 |
| key_phase | assumed | 0（一臂朝 +Y；z 镜像对称） |
| 继承特征 | asked | 走线窗、壳体走线口、防割手圆角、左槽底贴腔壁厚 |
| 右槽深 / 右端面 | assumed | 同左槽深 10.5 → x_end = 90.5（同规格推导） |
| boss 位置 | assumed | x=25 / 40，z=0（直段腔内，避让拐角与弧；守卫校验） |
| 圆底沉头 | assumed | 外锪平 0.3 + 内 pad 加厚 1.0（2mm 壁直接沉头只剩 0.35 孔壁，不可靠） |
| boss 盲孔深 | assumed | 6.0（M3×8 自攻） |
| 走线口位置 | assumed | 壳体左端外壁 1 个，y∈[0,7] |
| 同轴电机走线孔 | asked (S6 用户追加) | 壳底 −Y，boss_x2 与弧形端壁之间，同走线口源型 |
| S6 倒角边集 | asked (用户确认 S6 计划预览) | 上件 4 条端盖 rim R1.2；壳体两走线口外环 R0.6；其余锐边见区 9 |
| 右槽走线窗 | assumed | 围绕 X 轴 4 窗，相位 45°，x∈[83,88] |
| 电机接口 connector | assumed | motor_left / motor_right 暴露于上件 |
| 导出格式 | assumed | scadpkg + STEP + STL |
