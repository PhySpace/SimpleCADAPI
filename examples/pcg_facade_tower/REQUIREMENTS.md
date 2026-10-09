# REQUIREMENTS: pcg_facade_tower

PCG 单元式幕墙塔楼：同一份代码，任意平面轮廓 / 层数 / 退台，自动生成**可加工**的外立面。
论点：参数化的是**实例化**（少量板型 Part × 大量 placement），不是几何堆砌；GN 网格没有"板型"。

## CAD brief

```text
- Model: pcg-facade-tower, assembly (panel/corner/slab Parts → floor subassemblies → tower)
- Inputs: prose (本会话讨论)；inspiration, not reproduction
- Units: mm, degrees
- Coordinate convention: Z up；原点 = 地坪 z=0 ∩ 平面参考点；+X 东、+Y 北；平面多边形 CCW
- Overall dimensions (default CHAMFER plan): 36000 x 24000 底平面，NE 角 45° 切角 6000；
  lobby 5400 + 36 层 x 3600 → 屋面 135000；每 12 层四边内退 3000（3 个 tier）
- Functional features: 标准板（vision + 遮阳竖挺 / vision 无挺 / solid 实体板）、收口板 closer、
  lobby 通高玻璃板、女儿墙板、角部收口件（凸角 90°/135°、凹角 270°）、楼板/屋面/退台板、主入口雨棚
- Positioning/mating: 板件落在 building line（楼板外沿参考线）外侧 y∈[0, frame_d]；
  placement 由布局引擎自具名基准（building line 顶点、楼层标高）计算；幕墙固定于结构 → 全部 ground
- Parameters: 见 layout.py FacadeParams（全部具名；板件尺寸经 builder 参数传入以进入 build_key）
- Paths: examples/pcg_facade_tower/{layout,panels,corners,slabs,floor,tower,export}.py；out/*.scadpkg|step|csv|png
- Validation targets: 见下文 V1–V10
- Assumptions: 见下文 A1–A8
```

## 设计参数（默认值）

| 组 | 参数 | 默认 | 说明 |
| --- | --- | --- | --- |
| 平面 | `plan_kind` | CHAMFER | RECT / CHAMFER / L_SHAPE |
| | `plan_w`, `plan_d` | 36000, 24000 | X / Y 外包 |
| | `chamfer` | 6000 | CHAMFER：NE 角沿两边各切 6000（45° 边） |
| | `notch_w`, `notch_d` | 12000, 9000 | L_SHAPE：NE 角缺口 → 1 个 270° 凹角 |
| 竖向 | `n_floors` | 36 | lobby 之上的标准层数 |
| | `floor_h`, `lobby_h` | 3600, 5400 | |
| | `setback_every`, `setback_depth` | 12, 3000 | 每 tier 12 层，四边同时内退 |
| 模数 | `w_std` | 1500 | 标准板宽（含缝） |
| | `closer_min` | 450 | 收口板最小宽（含缝）；两端对称 → 上限 closer_min + w_std/2（不含） |
| | `joint` | 20 | 板间缝（四周各 joint/2） |
| | `corner_c` | 450 | 角部收口件沿各边占宽（自 building line 顶点） |
| 板件 | `frame_d`, `frame_sight` | 150, 60 | 框深 / 框面宽 |
| | `spandrel_h` | 1100 | 层间实体区高（盖住楼板边） |
| | `glass_t`, `glass_recess` | 24, 40 | 玻璃厚 / 距框外面凹进 |
| 遮阳 | `fin_t`, `fin_depth` | 40, 300 | 竖挺厚 / 伸出深度（自框外面） |
| | `fin_amp`, `fin_wavelength`, `fin_period_floors` | 30°, 18000, 4 | 波场：θ = θ_sun(边) + A·sin(2π(u/λ + f/P)) |
| | `fin_bins` K | 6 | θ 量化到 [-45°, 45°] 的 K 档（合理化旋钮） |
| 窗墙比 | `wwr_target` | S 0.35 / E,W 0.40 / N 0.50 | 按边外法向归到 4 个朝向；全楼按朝向合池，上限约 0.54（不可达即报错） |
| 太阳 | `sun_azimuth` | 180° | 自北顺时针；朝北边（n·sun ≤ 0）无竖挺 |
| 板型 | `type_round_mm` | 1e-3 | 板型身份 = 参数四舍五入到 0.001 mm（闭合用精确值，误差 ≤ 5e-4 由缝吸收） |

## 需求区

1. **布局引擎**（纯 Python，无几何）：平面 → tier 退台多边形 → 每边：角部占宽 → 标准板数 n + 两端对称收口板 →
   每块板的 (floor, edge, s0, s1, kind, fin_bin) → 板型去重 → floor 类型去重（tier × 相位 f mod P）。
2. **窗墙比分配**：每边 vision/solid 由有序抖动（4×4 Bayer，按 bay × floor）分配，使该朝向实测 WWR 贴近目标。
3. **板件族**：vision（标准层带层间区 / lobby 无层间区）、solid（实体标准板、收口板、lobby 收口、女儿墙）、
   fin（K 档竖挺，独立 Part，现场挂在板右竖框上）；板件单实体，玻璃面打 tag `facade.vision_glass`。
   lobby 5400 超运输高度 → 上下两排 2700 板（排数 = ceil(lobby_h / 4200)）。
4. **角部收口件**：由相邻两边方向 + frame_d + corner_c 计算的平面多边形 → 草图拉伸；凸角与凹角两族。
5. **楼板 / 屋面 / 退台 / 雨棚**：tier 多边形内缩 slab_gap 拉伸；退台 = 下 tier 屋面；南向主入口雨棚。
6. **楼层子装配**（带子装配）：每个 floor 类型 / lobby / 各 tier 女儿墙一个 `scad.assemble` 定义，内含该带所有板、竖挺与角件（ground，placement 来自布局帧，带局部 z = 0 为本带标高；lobby 含上下两排）；相同 floor 类型只建一次。楼板与雨棚由塔楼装配直接放置（上 tier 首层立在下 tier 屋面上，楼板不是 floor 类型的属性）。
7. **塔楼装配**：lobby 层 + 36 标准层（floor 类型实例）+ 各 tier 屋面/女儿墙 + 雨棚。
8. **合理化与尺度**：K 扫描（板型数 vs 最大角度偏差）；层数扫描（8/20/36/48 层：标准板型数不增长）；三种平面。
9. **增量重建**：改 `fin_depth` → 只有竖挺件 miss，其余命中；改 `n_floors` → 板型全部命中。
10. **导出**：scadpkg + AP242 STEP（共享定义）+ 板块清单 CSV + 渲染。

## 验证目标

| # | 检查 | 方法（几何实测，不信设计值） |
| --- | --- | --- |
| V1 | 立面闭合 | 每层每边：世界坐标下板/角件沿边区间（bbox 投影）首尾相接，缝 = joint ± 1e-3，无重叠；角件与两侧板缝 = joint |
| V2 | 零干涉 | 同层相邻件、相邻层上下件：采样分类 + Common 体积 = 0（抽样：每 floor 类型 1 层全查） |
| V3 | 运输尺寸 | 每板型 tight bbox ≤ 1600 x 4200 x 600（宽 x 高 x 深） |
| V4 | 窗墙比 | Σ(实例 × tag 玻璃面面积) / 朝向毛立面积（标准层板带），与目标差 ≤ 0.03 |
| V5 | 竖挺 | 竖挺侧面法向实测角 = bin 角 ± 0.05°；挺尖离 building line ≤ frame_d + fin_depth + 1 |
| V6 | 板型数 | 标准板型（vision + solid，w_std × floor_h）= 2，竖挺件 ≤ K；48 层与 8 层标准板型集合相同 |
| V7 | 角件 | 凸/凹角件为单实体、外轮廓与两侧板带外面共面（± 1e-3） |
| V8 | 楼层与退台 | 每层 z 标高、tier 退台深度、女儿墙位于 tier 屋面边 |
| V9 | 增量 | fin_depth 改动：miss 集合 = 竖挺件；n_floors 改动：板型全 hit；装配 solve 报告符合预期 |
| V10 | 导出 | 新进程重开 scadpkg：体积和 / 实例数 / 定义数一致；STEP occurrence 数 = 实例数 |

## 假设（需要报告的）

- A1 板件是"外观级"单元板：框 + 玻璃 + 层间板合为一个实体（Part 只含 1 个 Solid），不分铝/玻璃材质；
  不含锚件、密封胶、排水，不做结构/热工/风压分析（manufacturing-boundaries）。
- A2 幕墙固定于结构，不建连接件约束：placement 由布局基准计算，全部 ground（intent ladder: placement tied to named datum）。
- A3 building line 即楼板外沿参考线；板件在其外侧；楼板内缩 slab_gap = 30，楼层板占 [level, level + slab_t]（藏在层间板后）；
  屋面板占 [roof − slab_t, roof]（顶面 = 屋面 / 退台面，藏在顶层板上沿后）；上 tier 首层立在下 tier 屋面板上
  （其板件底 = roof + joint/2；若屋面板也取 [roof, roof + slab_t]，会在上 tier building line 外被上 tier 首层板件穿过 — S5 规划时发现，S3 K3 补 terrace 检查 + KB10）。
- A4 退台四边同距内退，保持平面形状；任何边内退后长度不足（< 2·corner_c + closer_min·2）时布局报错而非降级。
- A5 收口板两端对称分布；收口板为实体板、无竖挺。
- A6 朝北边无竖挺；竖挺位于每块板右侧竖框中线（沿边正向的末端），为独立的现场安装件：
  固定在板上时 45° 挺使单元宽约 1676 > 1600（V3），且 fin_depth 只应影响竖挺件（V9）。
- A7 板型身份取参数到 0.001 mm 的四舍五入值（与上次讨论一致：身份用离散化，闭合与检查用精确值 + 容差）。
- A8 渲染为灰度实体（玻璃不透明），用于形态评审，不是效果图。
