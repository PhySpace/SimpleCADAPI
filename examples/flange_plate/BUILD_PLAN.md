# BUILD_PLAN: flange_plate

> 迁移说明（2026-10）：下文是原建模会话的构建记录。代码已迁为 notebook
> `flange_plate.py`：`build_solid()` 的各块成为 cell，`assert_params()` 成为 guard cell；
> 阶段脚本收敛为 `verify/s2_verify.py`（终态几何，含 S1 的 bbox / 凸台顶 / 孔壁卡）与
> `verify/s3_guard_evidence.py`（改参守卫证据，含 S1 C6 的 4 组 known-bad），产物在
> `examples/flange_plate/out/`。

Datum（来自功能基准）: 原点 = 法兰轴线 ∩ 盘底平面；+Z 向上（凸台方向）。
受控基准面：盘底 z=0、盘顶 z=`flange_t`、凸台顶 z=`boss_top_z`；法兰轴线 = Z 轴。
对称性：基体轴对称（Z），螺栓阵按 `bolt_count` 旋转对称，首孔相位 +X（0°）。

构造策略（block-and-feature / 几何体素）: 用户指定体素路线——盘、凸台、孔刀全部是
"完全含于圆柱基本体"的纯工具体（FTC geometry tier 第 3 类合法情形），无草图层。
盘 = 圆柱基体（build）；凸台 = 圆柱 union（add）；中心孔 = 圆柱孔刀 cut（subtract）；
螺栓阵 = `radial_pattern` 孔刀 cut（subtract，工具体在块内构型）；根部 R3 与外缘 R2×2
= QL 选边 fillet（modify），选边卡在源码打印、`.exactly(n)` 承重。圆角最后（FTC 顺序）。

## 阶段划分

- **S1 盘 + 凸台 + 中心孔**
  - 输出边界: 轴对称阶梯回转体，含中心通孔（flange-disc ∪ center-boss − center-bore）。
    不含: 螺栓孔、任何圆角。
  - 验证目标: 单实体；bbox = ⌀100 × [0, 30] ±0.05；体积 = π/4·(100²·10 + 55²·20 − 30²·30) = 104850.65 mm³ ±0.5%；
    QL 卡片：凸台顶平面 z=30、孔壁圆柱面 ⌀30、盘底平面 z=0。
- **S2 螺栓孔阵 + 两次圆角**
  - 输出边界: 最终形态（6 孔版）：+ 6×⌀11 @PCD78 螺栓通孔 + 凸台根部 R3 + 外缘上下 R2。不含: 改参。
  - 验证目标: 单实体；`bolt_count` 个 ⌀11 孔壁圆柱面，圆心到轴距离 = PCD/2 = 39，首孔相位 0°；
    孔壁圆心 z ∈ (0, flange_t)；torus 面：根部 R3 ×1（minor radius 3）、外缘 R2 ×2（minor radius 2）；
    体积 < S1 体积且 > S1 − 孔体积 − 5%；选边卡在模型源码输出中可见（数量 + 边长）。
- **S3 改参轮（USER 第 2 轮，2026-09-05）**
  - 输入: 螺栓孔 6 → 8 均布，PCD 拉大到 88（尽量）。
  - 输出边界: 守卫判定（88 拒绝 + 依据 + 最大可行 PCD 推导）→ 参数改为 bolt_count=8、bolt_pcd=可行值
    → V1/V2 全量回归 + 守卫判定证据 + 4 张渲染图 + 隔离 reviewer 逐区域判定。
  - 验证目标: PCD 88 被轮辐宽守卫拒绝（web = 50−44−5.5 = 0.5 < 2）；可行上限 = flange_od − bolt_d − 2·min_edge_web = 85；
    8 孔版 V1/V2 回归全 PASS（PCD/孔数/相位/torus 不变式）；渲染 4 图存在；reviewer 全区域 match。

（导出与重开校验由 Role 5 执行：.scadpkg + STEP + STL + 渲染集 → out/flange_plate/。）

## Verifier contracts（Role 3 逐阶段补填）

### S1
`Verifier contract: S1 轴对称阶梯回转体（盘+凸台+中心通孔）/ Criteria: C1 单Solid+体积=π/4·(od²·t+boss_od²·(top−t)−bore²·top)±0.5%；C2 bbox x/y∈[±od/2] z∈[0,top]±0.05；C3 凸台顶环面 z=top 面积 π((boss_od/2)²−(bore/2)²)；C4 孔壁圆柱面面积 π·bore·top；C5 盘底环面 z=0 面积 π((od/2)²−(bore/2)²)；C6 守卫=名义参数通过+4 组 known-bad（bore≥boss / web<min / 孔撞根部圆角 / 根部圆角>凸台高）各触发 AssertionError / Script: verify/s1_verify.py`

Hypothesis 结果（verify/s1_hypothesis.py，已运行 2 轮）:
- H1 采用: 体素复刻体体积 104850.655 = 解析值（rel 0.000000）
- H2a-c 采用: QL 卡片——孔壁圆柱面/凸台顶环面/盘底环面各恰 1，面积逐项吻合
- H2b 修正（发现+修复）: 凸台顶面被中心孔穿透 → 环面 π(27.5²−15²)=1668.97，非整圆 π·27.5²；探针期望值修错后全过（修的是检查的算术，不是几何）
- H3 采用: bbox 用 `BRepBndLib.AddOptimal_s(useTriangulation=False)+SetGap(0)`，x/y∈[±50,50] z∈[0,30] 精确
- H4 known-bad: 去凸台复刻体体积 71471.233，偏离合格解析值 31.84% ≫ 0.5% → 体积门有区分度 ✓

S1 阶段证据（verify/s1_verify.py 全 PASS，2026-09-05）:
- C1 volume=104850.655 = analytic；C2 bbox [±50,50]×[0,30]；C3 凸台顶环面 1668.97 n=1；
  C4 孔壁 2827.43 n=1；C5 盘底环面 7147.12 n=1；C6 名义通过 + 4 守卫各触发（G1 bore≥boss /
  G2 web=1.5<2 / G3 gap=0 / G4 短凸台 高 2<R3）
- C6 探针迭代：G4 首版 bad-dict（加大 R）被 G1/G3 先拦（守卫顺序 G1→G2→G3→G4 且壁厚 12.5），
  改为 boss_top_z=t+2（短凸台）后 G4 恰好独占触发——4 守卫各自可达、各自承重。

### S2
`Verifier contract: S2 最终形态（6 孔+两圆角）/ Criteria: D1 单Solid+体积∈Pappus 支架±1.5%；D2 孔壁圆柱面 n=bolt_count 面积 π·bolt_d·flange_t 圆心轴距=PCD/2；D3 首孔相位 0°+相邻角距 360/n（≥2 单元实测）；D4 根部 TORUS n=1（面积=2π(Rmaj−2R/π)·πR/2, z>flange_t）+外缘 TORUS n=2（面积=2π(Rmaj'+2R/π)·πR/2, z≤flange_t）；D5 S1 回归（bbox±0.05+凸台顶环卡 n=1）；D6 pattern 工具数=bolt_count（源码 fact 卡证据）/ Script: verify/s2_verify.py`

Hypothesis 结果（verify/s2_hypothesis.py，已运行 2 轮）:
- P1 采用: radial_pattern(count=6, total_rotation_angle=360) 返回 6 工具**含原型**，相位 0..300°，首孔 0°（+X）
- P2a-c 采用: 孔壁卡 n=6，轴距全 39.000，等角距 60.0×5（实测 ≥2 单元）
- P3/P4 采用: 选边卡——根部 CIRCLE@z=10 len=172.788=π·55 n=1；外缘 2×CIRCLE len=314.159=π·100 @z=0/10
- P5 修正（发现+修复）: torus 面积初版用弧所在大半径（Pappus 误用）→ 实测 846.520/972.615 揭穿；
  正确为弧质心半径（偏移 2R/π：根部向内、外缘向外），修后 rel<0.0001
- P6 采用: 孔后体积 99148.664=解析精确；终体积 98955.987∈Pappus 支架（rel 0.00000）
- P7 known-bad: 无圆角体 TORUS n=0≠3 ✓ 门有区分度

S2 阶段证据（verify/s2_verify.py 全 PASS，2026-09-05）:
- 源码 fact 卡：bolt-holes 99148.664/12 面 → root-fillet 99490.521/13 面 → edge-fillets 98955.987/15 面；
  两张选边卡在圆角前打印（root n=1 len=172.788；edge n=2 len=314.159×2 @z=0/10），exactly(1)/exactly(2) 承重
- D1 98955.987 ∈ 支架（rel 0.00021）；D2 孔壁 n=6 轴距 [39.0]；D3 相位 0° 等距 60×5；
  D4a 根 torus 846.520 n=1；D4b 外缘 tori 972.615×2；D5 bbox 不变 + 凸台顶环卡 n=1

### S2 建模假设（Role 4）
`Hypothesis: 孔刀原型@(+X,PCD/2) → radial_pattern(count=n, 360°) 含原型 → cut 一次 6 刀；圆角走几何窗选边（CIRCLE+len 2πr+z 窗）+ 卡片先行 + exactly(n) / Result: fact 卡链体积 99148.664→98955.987 与解析/Pappus 吻合；faces 6→12→13→15 / Adopted: flange_plate.build_solid() S2 三块`

### S3
`Verifier contract: S3 改参轮（8 孔 + PCD 尽量大）/ Criteria: E1 守卫 G2 拒绝 8/88（断言消息含算术 web=0.500<2）；E2 由 G2 不等式推导最大可行 PCD = flange_od − bolt_d − 2·min_edge_web = 85；E3 (8,85) 通过全部 4 守卫（G3 gap=6.5、G1 wall=12.5、G4 boss_h=20）；E4 源码参数落位 bolt_count=8/bolt_pcd=85；回归 = s1_verify + s2_verify 重跑（D2/D3 自动按新参数校 8 孔 @45° 距、PCD 42.5 轴距）/ Script: verify/s3_guard_evidence.py`

视觉契约（Role 3 预定，Role 4 产图，隔离 reviewer 判定——本上下文不得自证）:
- 渲染集（out/flange_plate/）：render_iso.png（等轴测 (30°,45°)）、render_front.png（正视 (0°,0°)）、
  render_top.png（俯视 (90°,0°)）、render_detail.png（(25°,20°) 高倍 zoom=9，螺栓孔+凸台根部圆角特写）
- reviewer 输入：4 图路径 + REQUIREMENTS.md 形状描述（分区 1-5）
- 判定字段（逐区域）：match / mismatch / unreviewable + 理由；mismatch → 修模型重渲再评审（换新 reviewer）

Hypothesis 结果（verify/s3_guard_evidence.py 改参前决策轮，已运行）:
- E1 ✓ G2 拒绝 8/88：web = 100/2 − 88/2 − 11/2 = 0.500 < min_edge_web = 2.0（断言消息原样入证据）
- E2 ✓ pcd_max = 100 − 11 − 2×2 = **85.0**
- E3 ✓ (8, 85) 过全部守卫：web=2.000（恰达下限，守卫为 ≥）、G3 gap=6.500、G1 wall=12.500>R3、G4 boss_h=20≥R3
- E4（改参前 FAIL 属预期——决策轮在模型改参之前运行，E4 在改参后翻转）

S3 阶段证据（verify/s3_guard_evidence.py + s2_verify.py 全 PASS，2026-09-05）:
- 判定链：E1 8/88 → G2a 拒（web=0.500<2，断言消息原样）；E2a 上确界 pcd_sup=85（web=2.0 恰达下限）；
  E2b 85 → G2b 拒（**实证退化**：8×PCD85 实跑 faces=16≠17、孔壁 7/8、0° 孔被边圆角吞并、
  体积反常 +950、顶/底面中心偏移 +X —— web==R_edge 精确相切）；E2c 交付 84.5（0.5mm 网格，
  web=2.25 裕度 0.25）；E3 (8,84.5) 过 G1/G2a/G2b/G3/G4（附 chord 32.34>11）；E4 源码落位
- 几何回归（84.5 版）：D1 97055.323（rel 0.00021）D2 n=8 r=42.25 D3 相位 0°@45°×7 D4 torus 846.520+972.615×2 D5 bbox/凸台顶环 —— 全 PASS
- **修复循环记录**（repair: S3 PCD 相切）：初版按上确界交付 85 → D2 n=7≠8 暴露 → 诊断（面孔卡：
  0° 孔壁缺失、顶/底面中心偏移）→ 定因 web==R_edge 布尔相切 → 修 owning artifact（守卫拆 G2a/G2b + 
  参数 84.5 + 证据脚本 E2a/b/c）→ 重跑全过。检查未削弱（D2 仍要 exactly 8）
- **s1_verify 阶段锁定说明**：S3 后在最终源码重跑 s1_verify，C1/C5 FAIL 属预期——其契约测 S1 输出边界
  （当时源码仅 3 特征块）；S1 不变量在最终形态的存活由 s2_verify D5 承担（bbox±0.05、凸台顶环卡 n=1），
  孔壁卡 C4 亦过。非回归，不改 S1 契约
- 视觉判定（4 视图隔离 reviewer，2026-09-05；机制说明：本 host 无 task/subagent 工具，
  隔离评审由独立视觉模型（analyze_image MCP，全新上下文，仅收渲染图 URL + REQUIREMENTS 形状描述）
  承担，每视图一次独立调用，符合"产图上下文不得自证"的门槛）:
  - iso: "region 1: match - thin round disc ... region 2: match - coaxial cylindrical boss ... region 3: match -
    central through bore clearly visible on boss top face ... region 4: match - 8 evenly spaced round holes ...
    region 5: unreviewable - the boss-to-disc junction shows a smooth transition but fillet radii (R3 concave
    ring, R2 rim rounds) cannot be verified precisely at this resolution ... overall: PASS"
  - top: "region 4: match - exactly 8 bolt holes, evenly spaced 45° apart, one hole lies on the +X axis
    (right side), all holes clear of the outer rim ... region 5: unreviewable - edge rounding radii cannot be
    reliably confirmed from a top-down view alone ... overall: PASS"
  - front: "region 5: match - Left/right ends of the disc silhouette are visibly rounded (convex rim rounding),
    and the boss-to-disc transition shows a smooth concave curve rather than a sharp step ... overall: PASS"
  - detail: "region 2: match - boss root shows a smooth concave sweeping fillet into the disc top, no sharp
    corner. region 3: match - visible bolt holes are plain cylinders with sharp unchamfered edges, clearly
    separated from the rim fillet by flat web ... overall: PASS"
  - 结论：0 mismatch；unreviewable 均为视图原理性不可见项（俯视看不到圆角半径、正视看不到隐藏孔），
    对应不变量已由 D4 torus 卡/孔壁卡在几何层面证明。视觉门关闭，无需修模重渲

## Hypotheses（Role 4 逐阶段补填）

### S1
`Hypothesis: 体素链 make_cylinder(盘) → union(make_cylinder 凸台) → cut(make_cylinder 孔刀, z∈[-5,35] 过切) / Result: 三步 fact 卡 volume 78539.816→126056.405→104850.655（末值=解析），faces 3→5→6；@scad.part 包装返回 PartBuildResult / Adopted: flange_plate.build_solid() + build_flange_plate()`

### S2
（待补）

### S3
（待补）

## TODO（Role 2 初始化）

- Requirements: completed（REQUIREMENTS.md + 批量预答台账）
- Plan: completed（本文件）
- Build & Verify: S1 plan verifier / S1 model / S1 run verifier / S2 plan verifier / S2 model /
  S2 run verifier（S3 三项在改参轮追加）
- Export: .scadpkg + STEP + STL + 渲染集 + 重开校验 + 最终报告

## Role 5 导出证据（2026-09-05）

- capture: `scad.capture(build_flange_plate(), examples/out/flange_plate/flange_plate.scadpkg)`
  → CaptureResult；STEP 从包导出（AP242DIS，definition ('flange-plate',)）；STL 直读 BREP
  （3617 vertices / 7266 triangles，linear_deflection 0.1，需 `--extra gmsh`）
- 新进程重开门（export.py --validate）：`read_product_package` + `validate_product_package` OK；
  `load_product_package` → definition_id='flange-plate'，definition_kind='single_solid'，
  revision='1.0.0'，solid_cache（BREP blob sha256:2678736…）present —— 单实体零件确认
- 产物清单（examples/out/flange_plate/）：flange_plate.scadpkg 4,373,342 B / flange_plate.step 52,981 B /
  flange_plate.stl 363,384 B / render_iso.png 69,140 B / render_front.png 28,312 B /
  render_top.png 94,349 B / render_detail.png 165,441 B

## 未执行的检查（诚实清单）

- FEM/强度/疲劳：无工况声明，按 manufacturing-boundaries 不做几何外断言
- `validate_step_roundtrip_rdescriptor`（STEP 重导入往返）：需求未声明 roundtrip 敏感消费方，未跑
- GraphSession model-JSON replay 门：本流程走 @scad.part（非显式 GraphSession），replay 未演练；
  耐久性由 capture/reopen 门承担
- 孔-圆角干涉的参数敏感性扫描（web 裕度 0.25 之外的扫描）：未跑（守卫+单点实证已足）
- OBJ/MJCF/FCStd：未要求，未导出

## 承重假设（报告用）

- min_edge_web=2（=R_edge，ASSUMED）→ 引出 G2b 相切禁令（实证承重）
- "可行最大 PCD" 的 0.5mm 网格量化 → 84.5（上确界 85 被相切排除）
- ⌀11 ≈ M10+1mm 间隙（规格推断，不影响几何）
- 隔离评审机制：host 无 task/subagent 工具 → 独立视觉模型 MCP（analyze_image）逐视图独立调用
