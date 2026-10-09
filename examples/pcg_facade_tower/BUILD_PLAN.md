# BUILD_PLAN: pcg_facade_tower

Datum: 原点 = 地坪 ∩ 平面参考点（RECT/CHAMFER/L_SHAPE 的 SW 角），Z up，+X 东 +Y 北；平面多边形 CCW，
边 i 自顶点 i → i+1，切向 t_i，外法向 n_i = (t_y, −t_x)。building line = tier 多边形。
板件局部系：x 沿边（0 = 板左端缝中线），y 向上（0 = 楼层标高），z 外法向（0 = building line）。
placement：origin = V_i + s0·t_i + z_floor·ẑ，x_axis = t_i，y_axis = ẑ（右手：z_axis = t_i × ẑ = n_i）。
角件局部系：origin = building line 顶点，x = 入边切向，y 向上，z = 入边外法向；平面轮廓在局部 (x, z) 内。
竖挺局部系：轴同板件；origin = 板局部 (w − joint/2 − frame_sight/2, 0, frame_d)（右竖框中线 × 框外面）。

构造策略：**布局引擎 (layout.py) 是唯一的 PCG 源**，只产数据（FacadeSchedule：tier 多边形、每层每边的板序列、
板型表、floor 类型表）；几何文件只消费板型参数。板型 = `scad.part(id=<type_id>)` 工厂，参数全部经 builder
实参进入 build_key → 同参数同 id 命中缓存；floor 类型 = `scad.assemble` 子装配，塔楼只放 floor 实例。

## 文件

| 文件 | 内容 |
| --- | --- |
| `layout.py` | FacadeParams、平面/退台、分格、收口、角部、波场 + 量化、抖动 WWR、板型/floor 类型去重 |
| `panels.py` | 板件族 builder（vision / solid / fin）+ Part 工厂 `make_panel_part(type_id, spec, params)` |
| `corners.py` | 凸角 / 凹角收口件（草图多边形拉伸） |
| `slabs.py` | 楼板 / 屋面退台板 / 雨棚 |
| `floor.py` | 带子装配（floor 类型 / lobby / 女儿墙；板 + 竖挺 + 角件，全 ground） |
| `tower.py` | 塔楼装配 |
| `export.py` | scadpkg / STEP / CSV / 渲染 |
| `verify/` | `sN_verify.py`、`render_stage.py`、`_common.py` |

## 阶段

- **S1 布局引擎**（无几何）
  - 输出边界: `build_schedule(params) -> FacadeSchedule`（JSON 可序列化）。
  - 验证: 每边 Σ宽 = 边长（1e-9）；收口宽 ∈ [closer_min, closer_min + w_std/2)；守卫矩阵（边过短 / 收口越界 / K<2 / 退台过深）
    恰等即拒；设计 WWR 与目标差 ≤ 0.03；板型数 / floor 类型数；三种平面都能出表。
  - 渲染: massing（tier 多边形拉伸 + lobby）四视图 + matplotlib 平面分格图（每 tier 的板/收口/角件着墨）。
- **S2 板件族**
  - 输出边界: 每 kind 至少一个板型单实体；玻璃面 tag。
  - 验证: V3 尺寸；框外面在 z=frame_d、building line 侧 z=0；缝 joint/2；玻璃 tag 面积 = 设计开口；
    V5 竖挺角（各 bin）；单实体 + brep valid。
  - 渲染: 每板型一张四视图（含一张 K 档竖挺并排）。
- **S3 角件 + 楼板 + 雨棚**
  - 验证: V7；角件多边形与相邻板端（布局值）缝 = joint；楼板内缩 slab_gap；雨棚在南边入口居中。
  - 渲染: 凸 90 / 凸 135 / 凹 270 角件各一 + 与两侧各一块板的局部拼装。
- **S4 楼层子装配**（先 tier0 第 1 层）
  - 验证: V1、V2（全层）、V4（本层）、ground 全部、solve 报告。
  - 渲染: 单层 iso + 顶视（缝可见）+ 角部特写。
- **S5 塔楼装配**
  - 验证: V1/V2 抽样（每 floor 类型一层 + 退台上下层）、V4 全楼、V5 包络、V6、V8、实例数 / 定义数。
  - 渲染: 四视图 + 南立面 + 退台特写。
- **S6 合理化 / 尺度 / 平面扫描**
  - 验证: K ∈ {2,3,4,6,8,12,24}：板型数单调、最大量化角误差 = 90/(2(K−1))；层数 ∈ {8,20,36,48}（setback_every = ceil(n/3)，保持 3 tier）：标准板型集合不变；
    RECT/CHAMFER/L_SHAPE 全过 V1/V4。
  - 产物: `out/rationalization.png`（板型数 vs 角误差）、`out/scale_sweep.json`。
- **S7 增量重建**
  - 验证: V9（cold → warm 全 hit；fin_depth 改 → miss = 竖挺件；n_floors 改 → 板型 hit）；耗时表。
- **S8 导出**
  - 验证: V10；CSV 板块清单（type_id, kind, w, h, count）。

## Stage checklist

```text
[x] Requirements
[x] Plan
[x] S1 layout      [x] S1 verify   [x] S1 render
[x] S2 panels      [x] S2 verify   [x] S2 render
[x] S3 corners     [x] S3 verify   [x] S3 render
[x] S4 floor       [x] S4 verify   [x] S4 render
[x] S5 tower       [x] S5 verify   [ ] S5 render
[ ] S6 sweeps      [ ] S6 verify
[ ] S7 incremental [ ] S7 verify
[ ] S8 export      [ ] S8 verify
```

## Feasibility probe（开工前，/tmp/pcg_probe）

- 12 板型 × 3000 实例平铺单层装配：SDK 原 `OperationGraph.is_dag` 递归 DFS 在 ~1000 个 add_component 时
  RecursionError；`Assembly.__post_init__` 的 `ids.count` 去重使每次 add 为 O(N²)（3000 实例 69 s）。
  已修（Kahn 迭代 + Counter）→ 3000 实例装配 12.6 s、capture 5.8 s、STEP 5.8 s（3000 occurrence，3.4 MB）。
- 渲染 3000 个 Located 共享 TShape 的复合体 ~10 s。
- `@scad.part` 的 part_id 必须等于装饰器 id → 每板型用 `scad.part(id=type_id)(builder)` 工厂。
- 仍用楼层子装配分层：塔楼只放 ~40 个 floor 实例，floor 类型复用（tier × 相位）。

## Stage log

- **S1**（`s1_verify.py` PASS，`s1_known_bad.py` 9/9 as designed）
  - WWR 目标下调为 N 0.50 / E,W 0.40 / S 0.35：原 N 0.55 超出物理上限（框 + 层间 + 实体收口 → 全 vision 约 0.54），
    引擎现在对不可达目标直接报错。
  - WWR 分配改为**全楼按朝向合池** + **Bayer 秩选择**（按 4×4 阈值排序取前 round(f·N) 格）：逐边 / 逐 tier 合池在
    切角、缺口、顶 tier 短边上不可达；纯阈值法把比例量化到 1/16（误差到 0.024）。现三种平面 × 8/20/36 层误差 ≤ 0.005。
  - 默认 36 层 CHAMFER：26 板型（solid 12 / vision 8 / corner 6），标准 vision 7 = K+1，12 floor 类型，2735 实例。
  - 48 层 + 每 12 层退 3000 → 4 个 tier，CHAMFER 顶 tier 切角边 1029 < 2c+2·closer_min、L_SHAPE 缺口边反向 —
    守卫正确拒绝；S6 层数扫描改为 setback_every = ceil(n_floors/3)。
  - 观察（留到调参）：W/E 立面 θ_sun = ±30 叠加幅值 30 → 大量饱和在 ±45 档。
- **S2**（`s2_verify.py` PASS 20 型：solid 12 / vision 2 / fin 6；`s2_known_bad.py` 12/12 as designed）
  - V3 逼出两处设计修改（回写 S1，S1 gate 加 C10 + 竖挺记录一致性检查，KB9/KB10）：
    竖挺改为独立 Part（45° 挺装在板上 bbox ≈ 1676 > 1600）→ vision 板型不再乘 K，标准板型 = 2 + K 个竖挺件；
    lobby 5400 > 4200 → 两排 2700。默认 CHAMFER 现 26 型（solid 12 / vision 2 / corner 6 / fin 6），3697 实例。
  - 框环 = 一张草图外环 + 1–2 个内环（全约束），玻璃 / 层间板为凹进板，向框内各伸 frame_sight/2 以融合成单实体。
  - SDK 行为：变换（translate/rotate）或后续布尔后，面 tag 只留在 lineage 作用域，`ql.tag(...)` 默认 effective 查不到；
    因此玻璃 tag 放在最后一步，渲染高亮用板局部坐标（不变换）。S4/S5 的 V4 用定义体上的 tag 面积 × 实例数。
- **S3**（`s3_verify.py` PASS；`s3_known_bad.py` 14/14 as designed）
  - 角件 9 型（turn −90 / +45 / +90 × h 2700 / 3600 / 1200）；三种平面 × 每 (tier, 带类) 一带共 105 处角部在世界坐标实测：
    外面与两侧板带外面共面、building line 面、端面在 corner_c − joint/2，与两侧板最小距离 = joint。
  - K6 实测到 A7 的舍入：收口板按 0.001 mm 取整建型、按精确起点放置，其后的缝偏差 ≤ 3.1e-4 mm；
    缝容差取 A7 声明的 5e-4（不是放宽几何，是把 A7 写进 gate）。
  - 楼板：每 tier 一型，38 个实例（地坪 + 各层 + 各 tier 屋面；上 tier 首层立在下 tier 屋面上，不另设板）；
    楼板与同层板件 / 角件最小距离 = slab_gap。雨棚 6 模数，两端落在 lobby 板缝上、居中、外挑起点距板外面 = joint，
    底面在 lobby 两排的横缝上。
  - SDK 修复（建筑尺度首次触发，均带回归测试 `test_building_scale_part_hashes_and_round_trips_its_state`）：
    ① 几何指纹按 1e-7 量化，36 m 楼板体积 / 1e-7 超出 2^53 → 哈希被 JSON 安全整数检查拒绝；
    ② RFC 8785 把 < 1e21 的整值 double（楼板惯量 ≈ 1.2e19）写成无指数整数，读回 latest-parts 状态时被当作越界整数拒绝。
  - （S5 规划时回改）屋面板原按楼板惯例占 [roof, roof + slab_t]，会切进上 tier 首层（其板件从 roof + j/2 起、位于上 tier
    building line 上，而屋面板平面是下 tier 的）→ 屋面板改占 [roof − slab_t, roof]（顶面 = 屋面 / 退台面，藏在顶层板带头部后）。
    K3 改写：屋面板顶 = 女儿墙标高、与顶层板件距离 = slab_gap、与上 tier 首层板件 / 角件 / 竖挺距离 = joint/2；
    `s3_known_bad` 加 KB10（楼板式屋面板）→ 15/15。SDK 缺陷统一记在 `SDK_DEFECTS.md`。
- **S4**（`s4_verify.py` PASS 全部 16 带；`s4_known_bad.py` 13/13 as designed，每例须触发列出的 gate）
  - 带子装配 = `scad.assemble(id="band-<band_id>")`，定义 = 本带用到的板型 Part（floor 带 11–12 个、lobby / 女儿墙 5 个）；
    构件 id `r{row}-e{edge}-s{slot}` / `…-fin` / `r{row}-v{vertex}`，全部 ground。楼板、雨棚留给塔楼放置（REQUIREMENTS 6 已改）。
  - 验证在**求解后的 Placement** 上独立重建 gp_Trsf（不走布局帧），并与 SDK `make_compound_from_assembly` 的体积 / bbox 对账；
    V1 每排每边「角件 | 板按 slot | 角件」沿 t 顺序 + 缝 = joint（A7 容差）+ z 跨度；V2 对 bbox 相交的全部构件对做 Common
    （floor 带 22–70 对，含竖挺与所在板、lobby 上下排）；V4 定义体 tag 玻璃面积 = 布局设计值。
  - 本带 WWR（仅报告，目标按全楼朝向合池，S5 检）：tier0-phase0 E .530 / N .544 / S .439 / W .549，phase1/3 低至 .21–.35。
  - 重建全 warm（无 dirty instance，定义 hash 不变）；16 带 cold + warm + 全部检查 88 s。
- **S5**（`s5_verify.py` PASS；`s5_known_bad.py` 11/11 as designed）
  - 塔楼 = `scad.assemble(id="facade-tower")`，79 构件（lobby + 36 floor + 3 女儿墙 + 38 楼板 / 屋面板 + 雨棚），
    20 定义（16 带 + 3 tier 楼板 + 雨棚），展开 3697 件 / 26 型；SDK 展平复合体 3736 实体（+ 板 / 雨棚），高 136.2 m。
  - 验证在「塔楼 placement × 带 placement」合成的 gp_Trsf 上重建世界几何：T0 构件 / 定义 / 叶子型集 / 件数；
    T1 全部 placement 为纯 z 平移 + SDK 投影对账；V8 楼层 / 女儿墙 / 屋面板标高与 tier，建筑线内缩 = k·setback_depth；
    V1 / V5 / V2 抽样 19 个实现（lobby、首末层、每 floor 类型首层、每次退台上下层、全部女儿墙），18 个接缝窗口 1845 对 Common。
  - V4 全楼（定义体 tag 玻璃面积 × 实例数）：E .400 / N .499 / S .351 / W .398，与 `design_wwr` 一致、距目标 ≤ 0.001。
  - V6：标准板型 `solid-w1500-h3600` + `vision-w1500-h3600-s1100`，竖挺 6 型 = K。
  - known-bad 逼出的两处 gate 修正：KB2（缺一层）T1 是 SDK-对-我们的一致性检查，自洽时不该响 → 期望改 T0 + V4；
    KB4（女儿墙放错 roof）按 schedule id 选接缝窗口会漏掉被放错的构件 → 窗口改为「实测 z 区间与窗口相交的全部构件」。
  - 耗时：塔楼 build 47.2 s，零改动 rebuild 45.8 s（warm 不比 cold 快，见 SDK_DEFECTS D7），全部检查 169 s。
