# BUILD_PLAN: ap242_gmsh_bracket 正式化重建

> **File layout after the notebook migration.** This plan is the build log;
> the stage scripts it names (`model.py`, `verify/s*_verify.py`,
> `s3_equivalence.py`, `s3_render.py`, the hypothesis scripts) were folded
> into the current layout:
>
> - `bracket.py`: the part notebook, one cell per feature block (the S1
>   boundary is the `gusset_ribs` cell).
> - `bracket_package.py`: runs the notebook and writes
>   `out/ap242_gmsh_bracket.scadpkg`; every `export_*.py` and
>   `translate_*_script.py` starts from it.
> - `export_fem_mesh.py`, `run_calculix.py`, `visualize_calculix.py`,
>   `study_mesh_convergence.py`: plain FEM modules that read the STEP and
>   the package (run `export_step.py` first).
> - `render_views.py`: the demo gallery renders.
> - `verify/acceptance.py`: the S1–S3 contracts below against the legacy
>   facts, plus the parameter guards; `verify/fcstd_check.py`: the S4
>   FreeCAD check.

Datum（来自功能基准）: 沿用 legacy 原点 = 竖壁底面中心（X 壁厚中面 / Y 宽度中面 / Z 底面）；+X 壁厚方向（fixed_support 背面 x=-2），+Y 宽度方向（零件关于 XZ 面 y=0 对称），+Z 高度方向。等价重建不改基准——下游 interface 面坐标（x=-2 / z=4 / z=22.32）全部锚定此系。

构造策略（block-and-feature）: 三块形体均为"完全含于基本形体"或"坐标已知的转录轮廓"——竖壁/横板是盒（FTC geometry tier 基元条款），三角筋是 legacy 坐标转录的 closed profile extrude（FTC 转录条款，`profile=geometry` 诚实标注），孔工具是圆柱基元（纯工具体条款）。理由：等价重建的忠实性优先，参数直接映射 legacy 命名常量（`scad.var` + unit）；不强行 sketch 化（约束未知 = 转录，这正是 FTC 允许 geometry tier 的场景）。特征顺序按 feature-ordering：build 基体 → add 筋 → subtract 孔 → annotate 标签。

## 阶段划分

- **S1 L 形基体 + 双三角筋**
  - 输出边界: wall ∪ shelf ∪ rib×2 单实体（含筋-壁正重叠 x∈[0,2]）。不含: 任何孔、任何 interface 标签。
  - 验证目标: 单 Solid、体积对解析值 10368（= 5760 壁 + 4480 板 − 640 壁∩板 + 2×486 筋 − 2×102 筋∩壁）偏差 <0.1%、bbox=[-2,-20,0]×[26,20,36]±0.05。
- **S2 孔系 + 界面标签**
  - 输出边界: mount_hole×2 + load_hole 切除；role.structural_l_bracket + 5 个 interface.* 面标签。不含: 导出。
  - 验证目标: 体积 = S1 − 270.177（2×π·2.5²·4 + π·3²·4）±0.1% 且与 legacy 10097.790 差 <0.1%；圆柱面卡片与 legacy 逐项一致（r/axis/位置）；interface 标签集合与 legacy 完全一致且各面面积/质心等价。
- **S3 新旧等价验证 + 导出渲染**
  - 输出边界: 正式 model.py（FTC 特征块 + Var 参数 + 参数守卫）capture 主包；export_step/obj/stl 重跑；4 视图渲染 + 隔离视觉评审。
  - 验证目标: REQUIREMENTS V1–V5 全过；评审逐区域 match。
- **S4（USER 第 2 轮）FCStd + 等价证据节**
  - 输出边界: export_fcstd.py 重跑产物；新旧等价证据（体积/包围盒/孔位实测/标签集合）成节写入本计划证据区。

## Verifier contracts（Role 3 逐阶段补填）

### S1
`Verifier contract: L 基体+双筋 / Criteria: C1 单 Solid + V=解析 10368±0.1%（5760 壁 + 4480 板 − 640 壁∩板 + 972 双筋 − 204 筋∩壁）; C2 bbox=[-2,-20,0]×[26,20,36]±0.05; C3 QL 可枚举（faces/edges 计数打印） / Script: verify/s1_verify.py`

Hypothesis 结果（verify/s1_hypothesis.py，已运行）:
- H1 采用: 正确体 volume=10368.000 与解析逐位一致，bbox 精确 [-2,-20,-0.0]×[26,20,36]，双门 PASS
- H2 known-bad: 无筋体 V=9600 → 体积门 FAIL ✓（bbox 门不区分——预期，体积门承载）
- H3 known-bad: 筋平移出壁（x_offset=2，仅面接触）V=10572 → 体积门 FAIL ✓（面接触 union 可成体，体积门必须在场）
- 结论: ±0.1% 体积带对三种形态有区分度，bbox 门辅助定位漂移 → 采纳

### S2
`Verifier contract: 孔系+标签 / Criteria: C1 V=10097.823±0.1% 且 |V−legacy|/legacy<0.1%; C2 圆柱面恰 3 张且 r/axis/center 对 legacy 卡片(r±0.01/axis±0.01/center±0.05); C3 body 标签含 role.structural_l_bracket; C4 包 scene interface 集合=legacy 5 项且 area rel≤1e-4、centroid≤1e-3 mm / Script: verify/s2_verify.py`

Hypothesis 结果（verify/s2_hypothesis.py，已运行）:
- H1 采用: V=10097.7905 与 legacy 差 +4.9e-11 相对（位级一致）；解析 10097.823 差 0.0003%（kernel 舍入）
- H2 采用: 圆柱卡片 3/3 逐项命中 legacy（r=2.5×2 + 3.0，area 63.0604/75.3982 完全相同）
- H3 known-bad: 半径扰动 +0.1 → 卡片比对 FAIL ✓
- H4 修正后 known-bad: 匹配器 target 平移须**超出** 10mm 守卫带才被拒（首稿 +5mm 在带内仍命中唯一 -X 平面——守卫按参数工作的正确行为，探针设计错误而非模型错误）；+15mm → "too distant: distance^2=361" 拒绝 ✓
- 结论: 体积/卡片/守卫三路检查有区分度 → 采纳

### S3
`Verifier contract: 新旧等价+导出 / Criteria: E1 新旧包体积 rel<0.1%; E2 bbox 轴差≤0.05mm; E3 interface 集合相等+area rel≤1e-4+centroid≤1e-3mm; E4 BREP inspect valid+solids=1+正体积; E5 双包新进程 read+validate 重开; E6 step/obj/stl 非空; 视觉: iso(35,45)/front(0,90)/top(90,0)/detail(30,120,zoom2.4) 4 渲染 + 隔离评审逐区域 match/mismatch/unreviewable / Script: verify/s3_equivalence.py + verify/s3_render.py`

Hypothesis 结果（verify/s3_hypothesis.py，已运行）:
- H1 体积门拒 +0.2% ✓；H2 bbox 门拒 +0.3mm ✓；H3 集合门拒改名标签 ✓；H4 面积门拒 +1% ✓
- 结论: 四路等价门全部有区分度 → 采纳（门槛函数内联于 s3_equivalence.py 供假设脚本复用）

## Hypotheses（Role 4 逐阶段补填）

### S1
`Hypothesis: scad.var 参数直供基元标量位 + _f() 求值派生元组坐标（hypotheses/s1_var_probe.py） / Result: Var 在 make_box/make_cylinder 标量位可求值（wall V=5760 精确）；发现: unit-Var × unitless-Var 惰性构造但 .evaluate() 抛 UnitValidationError（mixes unit-declared with legacy）→ 派生值一律 _f() 进 plain-float 空间（z=36×0.62=22.32 精确） / Adopted: model.py # ---- params ---- 全 Var 化 + _f() 派生`

### S2
`Hypothesis: 越界圆柱工具切除 + 匹配器打标（S1 已全链验证: build_stage("s2") 产出与 legacy 位级同体积） / Result: V=10097.790499; 卡片 r=[2.5,2.5,3.0]; interface 5/5 命中 / Adopted: model.py s2 特征块（mount-holes/load-hole subtract + role-name/interface-names annotate）`

### S3
`Hypothesis: 导出+渲染走已封包产物（read_product_package→materialize 再渲染，图=交付物） / Result: step 66207B / obj 31976B (948 tri) / stl 47484B (948 tri); 4 渲染 33.8KB/9.1KB/12.1KB/18.1KB; E4 首跑败于检查器键名（'solids'→counts 实为 'solid'）——修复验证器非模型 / Adopted: verify/s3_render.py 视图集 (35,45)/(0,90)/(90,0)/(30,120,zoom2.4)`

## 阶段证据（Role 3 运行 verifier 后补填）

### S1 证据（verify/s1_verify.py 全 PASS，2026-09-05）
- C1 volume=10368.000 = 解析（rel_err 0.000000）；C2 bbox (-2,-20,-0.0)×(26,20,36) 精确；C3 ql faces=14 edges=36
- 源运行（model.py main，含完整特征链与 capture）faces=17 / volume=10097.790 —— 与 legacy 完全一致（S2 门后续独立验证）
- 注: FTC 源文件按特征块整体编写（@scad.part 主契约需要完整 builder），阶段门按 build_stage("s1") 边界执行，S2 特征块的验证契约在 S1 门关闭后才设计——串行纪律按"验证先行"实质执行

### S2 证据（verify/s2_verify.py 全 PASS，2026-09-05）
- C1 volume=10097.790499，与 legacy 相对差 +4.94e-11（位级一致）
- C2 圆柱面 3 张 r=[2.5, 2.5, 3.0] 全部命中 legacy 卡片
- C3 body tags = [role.structural_l_bracket, solid.boolean.cut]
- C4 interface 5/5：area 相对差 ≤5.3e-7、centroid 差 ≤4.5e-5 mm（fixed_support 1400.7301 / load_surface 835.7257 / load_hole 75.3982 / mount_hole 63.0604×2）

### S3 证据（verify/s3_equivalence.py 全 PASS，2026-09-05）
- E5 双包新进程 read+validate 重开：ap242_gmsh_bracket@2.1.0 (new) vs @2.0.0 (legacy)
- E1 体积 new=10097.790499 legacy=10097.790499 **rel=0.00e+00**（位级相同）
- E2 bbox 逐位相同 max_delta=0.0000（[-2.0035,-20,-0.0044]×[26,20,36]）
- E3 interface 集合相等（5 tags），面积/质心在阈内
- E4 brep valid / solid=1 / closed_shell=1 open_shell=0 / 17 faces / 51 edges / volume 一致
- E6 step 66207B、obj 31976B（948 tri）、stl 47484B（948 tri）
- repair 记录: E4 首跑 AssertionError——检查器键名错误（期望 'solids'，BRepInspection.counts 实为 'solid'+'closed_shell'）；属验证器缺陷，修复 s3_equivalence.py 后 PASS（模型未动）

### S3 视觉评审（隔离评审员逐区域判定，2026-09-05）
评审机制: 隔离视觉模型（干净上下文，只收渲染图 + REQUIREMENTS 形状描述，无会话历史）。

| 视图 | 判定 | 评审员原话（节选） |
| --- | --- | --- |
| render_iso (35,45) | R1-R5 全 match, OVERALL pass | "R1 overall L-shape ... match - L-bracket with tall vertical wall and horizontal shelf, proportions consistent with 40 wide x 36 tall x 28 deep"; "R4 ... load hole visible in shelf ... mid-depth" |
| render_front (0,90) | R1-R5 全 match, OVERALL pass | "R3 rib triangles: match — two right triangles visible ... symmetric placement at mid-height"; "R4 symmetry: match — mirror symmetry" |
| render_top (90,0) | **首评 mismatch → 契约修正 → 复评 pass** | 首评: "R3: mismatch - rib footprints appear as full rectangles, not triangular, and they do not sit adjacent to the wall edge" |
| render_detail (30,120) | R1-R6 全 match, OVERALL pass | "R3 wall hole ... match"; "R4 hole clipping rib top corner ... match"; "R5 shelf top flat adjacent to rib foot ... match" |

top-view mismatch 处置（不弱化检查、不改模型）:
1. 评审反馈转确定性谓词（geometric-validation 纪律）: 实测新旧包筋斜面卡片**逐位相同**（2 faces area=67.5638 centers=(10.0374, ±11.11, 11.9626)）；S1 体积门 10368 精确值已钉死筋 x∈[0,18] 贴壁（含 102 mm³/筋 壁内重叠）；安装孔穿筋顶角在 legacy 同样存在（体积位级相同为证）。
2. 投影算术: XZ 三角形沿 Y 拉伸的筋在 -Z 正交投影下**只可能是矩形带**（斜面投影为矩形）——首评契约要求"三角影"是几何不可能的期望，属评审契约缺陷非模型缺陷。
3. 修正契约（如实描述 -Z 投影应有的正确外观）后派**新**隔离评审: "R3: match - two 3-wide rectangular bands starting at the wall edge, ~2/3 of visible depth, centered y≈+/-11, symmetric ... R6: match - no unexpected elements. OVERALL: pass"。
4. 侧发现（记录非缺陷）: 筋斜面被安装孔咬角（理想 76.37 → 实际 67.56 mm²）——新旧完全一致，系 legacy 原生特征。


### S4（USER 第 2 轮）
`Verifier contract: FCStd+证据 / Criteria: F1 export_fcstd.py 重跑成功且产物非空; F2 FCStd 于 FreeCAD 运行时重开为可编辑特征树（文档对象≥5、非 App:: 基元特征≥5、App::Part 结果体体积与交付体积一致≤0.1%）；SDK 新进程重开包校验并列体积; F3 本证据节写入 / Script: verify/s4_fcstd_check.py`

Hypothesis/发现（s4 期间，已运行）:
- F2 首版谓词"最大 sane 体积"错向：中间特征（MultiFuse 10368）> 最终结果，且 XZ/YZ_Plane 载有 1e152 垃圾 Volume——改为锁定唯一 App::Part 结果容器的 Shape.Volume（6.76e-11 命中）
- FreeCAD 运行时 = /Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd（SDK 自动发现）；GUI 目检未执行（无 GUI 会话），以 CLI 重开+特征树枚举+体积对账代替（更强）

### S4 证据（verify/s4_fcstd_check.py 全 PASS，2026-09-05）
- F1 FCStd 53537 bytes（export_fcstd.py 重跑，脚本未改一行）
- F2 SDK 新进程重开 @2.1.0 volume=10097.790499；FreeCAD CLI 重开 26 objects / 15 editable（Spreadsheet 参数表 + Box×2 + Cylinder×3 + Extrusion 筋×2 + Fuse/MultiFuse + Cut×3 + App::Part 结果），结果体 10097.790499682898（rel 6.76e-11）

## 新旧版本几何等价证据（USER 第 2 轮要求，S4 补填）

**引用锚点**: 后续 FEM 结果请引用 `examples/out/ap242_gmsh_volume_mesh/ap242_gmsh_bracket.scadpkg`（md5 4866a6837c5b57aca225ffc1b7e37ec0，part `ap242_gmsh_bracket` @ revision **2.1.0**）。对照基线 = `examples/out/ap242_gmsh_volume_mesh/legacy_baseline/ap242_gmsh_bracket.scadpkg`（revision 2.0.0）。

| 项目 | legacy @2.0.0 | rebuilt @2.1.0 | 判定 |
| --- | --- | --- | --- |
| 体积 (mm³) | 10097.790499 | 10097.790499 | **rel = 0.00e+00**（位级相同）✓ |
| 包围盒 (mm) | (-2.0035, -20.0000, -0.0044) → (26.0000, 20.0000, 36.0000) | 同左逐位 | max_delta = 0.0000 ✓ |
| BREP | 17 faces / 51 edges | valid / solid=1 / closed_shell=1 / open_shell=0 / 17 faces | 单实体闭壳 ✓ |
| interface 标签集合 | {fixed_support, load_surface, mount_hole_1, mount_hole_2, load_hole} | 同左（集合相等） | ✓ |

孔位/孔径实测（BRepAdaptor 圆柱面卡片，新旧逐项一致）:

| 孔 | 半径 | 轴 | 位置 | 孔壁面积 mm² | 面心 |
| --- | --- | --- | --- | --- | --- |
| mount_hole_1 | 2.5 | +X | y=-11, z=22.32 | 63.0604 | (0.0075, -11, 22.3111) |
| mount_hole_2 | 2.5 | +X | y=+11, z=22.32 | 63.0604 | (0.0075, +11, 22.3111) |
| load_hole | 3.0 | +Z | x=12, y=0 | 75.3982 | (12, 0, 2) |

interface 面几何对账（面积 rel ≤5.3e-7、质心差 ≤4.5e-5 mm，远优于 export_fem_mesh 匹配阈值 area 1e-6/centroid 1e-5/bounds 0.05）:

| 标签 | 面积 mm² | 质心 | 解析核对 |
| --- | --- | --- | --- |
| interface.fixed_support | 1400.7301 | (-2.0, 0, 17.8789) | =40×36−2π·2.5² |
| interface.load_surface | 835.7257 | (14.5271, 0, 4.0) | =24×40−2·(16×3)−π·3² |
| interface.load_hole | 75.3982 | (12, 0, 2.0) | =2π·3·4 |
| interface.mount_hole_1/2 | 63.0604 | (0.0075, ∓11, 22.3111) | =2π·2.5·4(+孔-筋相交修正) |

侧记录: 筋斜面被安装孔咬角（67.5638 mm²/片，新旧逐位相同）——legacy 原生特征，非本次引入。export_step/export_obj/export_stl/export_fcstd 四脚本未改动、对 @2.1.0 包重跑全部通过。

