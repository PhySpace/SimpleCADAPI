# BUILD_PLAN: u_link_motor_mount

> **File layout after the notebook migration.** This plan is the build log;
> the stage scripts it names (`verify/s*_verify.py`, the hypothesis, probe and
> diag scripts, `assembly.py`) were folded into the current layout:
>
> - `u_link.py`, `shell.py`: part notebooks, one cell per feature;
>   `u_link_motor_mount.py`: the assembly notebook (`scad.use` of both).
> - `dimensions.py` (shared `ULinkDimensions`, guard chain `check()`),
>   `common.py` (shared sweep and cutter helpers): plain modules.
> - `export.py`: package, STEP, STL, renders into `out/`.
> - `verify/acceptance.py`: every stage contract below (S1–S4, S6 guard
>   matrix, S10–S13) on the notebook cell values;
>   `verify/export_artifacts.py` and `verify/render_check.py`: the S5 checks
>   of the exported files.

Datum（来自功能基准）: 原点 = 底部圆柱轴线中点；+X 沿连杆（指向右臂）；+Y 向上（U 开口方向）；+Z 横向。
平底面 y=0、槽底安装面 y=D_motor/2、臂端面 y=D 均为受控基准面。对称性：关于 XZ 原点对称（左右臂）、关于 XY 对称（z 镜像）。

构造策略（profile-driven）: U 形主形体由「圆形截面沿带拐角圆弧的线框路径 sweep」生成 —— L、D、R_corner 直接作为路径参数承载设计意图（适应长度变化 = 改 L 即改路径）；平底/电机槽为基元工具 boolean cut；倒角最后。

## 阶段划分

- **S1 U 形扫掠杆**
  - 输出边界: 单实体 U 杆（含拐角圆弧、⌀d_profile 圆截面、臂端平面端盖 y=D）。
    不含: 平底切、电机槽、倒角。
  - 验证目标: 单实体、正体积、bbox X=(L+d_profile) / Y=[−r, D] / Z=d_profile、两臂端盖为平面且位于 y=D。
- **S2 底部平底切**
  - 输出边界: 移除 y<0 材料 → 平底面 y=0。不含: 电机槽、倒角。
  - 验证目标: bbox Y=[0, D]、存在 y=0 平面（法向 −Y）、体积减小、仍单实体。
- **S3 电机安装槽 + 命名安装面**
  - 输出边界: 两臂端 ⌀(d_profile−thickness) 圆柱槽，底 y=D_motor/2；
    安装面（槽底面）打 tag `feature.motor_mount_floor_left/right`，QL 可索引。不含: 倒角。
  - 验证目标: 恰好 2 个安装面；平面法向 +Y；位置 (±L/2, D_motor/2)；直径 = d_profile−thickness；
    槽深 = D−D_motor/2；槽壁 = thickness/2；QL 按命名索引命中且仅命中它们。
- **S4 全局倒角**
  - 输出边界: 最终形态（拓扑允许边缘全部 R=fillet_r）。
  - 验证目标: 单实体、bbox 与 S3 一致（±0.05）、体积略减、命名安装面仍可被 QL 索引。
- **S5 导出**
  - 输出边界: out/ 下 .scadpkg + .step + .stl；新进程重开校验。
  - 验证目标: 重开成功、定义/实体数一致、三文件非空。

## Verifier contracts（Role 3 逐阶段补填）

### S1
`Verifier contract: U 形扫掠杆 / Criteria: C1 单Solid+体积=Pappus±0.5%；C2 恰2平面端盖@y=D 面积πr² 心(±L/2,D,0)；C3 bbox [±(L/2+r)]×[-r,D]×[±r]±0.05；C4 源码含 R_corner>r 参数守卫 / Script: verify/s1_verify.py`

Hypothesis 结果（verify/s1_hypothesis.py，已运行）:
- H1 采用: sweep(profile=圆Face⊥路径切向, path=5边wire) 体积 100961.888 = Pappus 精确值（rel_err 0.00000）
- H2 采用: QL `PLANE + center.y∈[D∓0.1]` 卡片恰 2 面，面积/法向正确
- H3 采用: bbox 须用 `BRepBndLib.AddOptimal_s(useTriangulation=False)+SetGap(0)`，`Add_s` 虚胖 ~0.07mm（已弃）
- H4 known-bad: 体积门拒绝 +5% 扰动期望 ✓（检查有区分度）
- H5 known-bad: R_corner=r 退化拐角**能建成**（体积虚高 103995.75）→ 不能依赖构建失败，须源码显式守卫（C4）

## Hypotheses（Role 4 逐阶段补填）

### S1
`Hypothesis: sweep(profile=圆Face@路径起点 normal=切向, path=make_wire_from_edges[seg,arc,seg,arc,seg]) / Result: 体积=Pappus 100961.888 (0 err), 7 faces, QL 端盖卡片 n=2 / Adopted: u_link.build_u_rod()`

S1 阶段证据（verify/s1_verify.py 全 PASS）:
- C1 volume=100961.888 = pappus；C2 端盖 n=2 areas=706.86×2；C3 bbox [−55,55]×[−15,40]×[−15,15]；C4 守卫 R=20>r=15

### S2
`Verifier contract: 平底切 / Criteria: C1 单Solid+体积∈解析界(去下半直段半圆柱~再加拐角下界)；C2 恰1平面−Y面@y=0 面积>πr²/2；C3 bbox y=[0,D]±0.05 / Script: verify/s2_verify.py`

Hypothesis 结果（verify/s2_hypothesis.py，已运行）:
- H1-H3 采用: cut(rod, box@y∈[−r−5,0] 越界包络) → volume=74086.958 ∈ (64618.1, 86824.7)；平底面 n=1 area=2668.8；bbox y=[0,40]
- H4 known-bad: 未切 u_rod 三项检查全挂（volume 出界/平底面 n=0/bbox y_min=−15）✓ 检查有区分度

### S3
`Verifier contract: 电机槽+命名安装面 / Criteria: C1 V=V_s2−2π·rp²·depth±0.1%；C2 恰2槽底平面+Y@y=d_motor/2 心(±L/2,y,0) 面积π·rp²；C3 端面环2片+槽壁圆柱2片(2π·rp·depth)；C4 ql.tag(feature.motor_mount_floor_left/right) 恰1面/侧且与几何选择同位 / Script: verify/s3_verify.py`

Hypothesis 结果（verify/s3_hypothesis.py，已运行）:
- H1-H3 采用: 槽底 2×452.39=π·12² 心(±40,35)；端面环 2×254.47；槽壁 2×376.99=2π·12·5
- H4 采用: GraphSession 内 `apply_tag_rselection(scope, targets=QL谓词, tag)` → `ql.tag()` 恰命中 1 面/侧，中心与几何选择一致
- H5 known-bad: 未打标实体 tag 查询 n=0 ✓（命中靠 tag 不靠几何巧合）

S3 阶段证据（verify/s3_verify.py 全 PASS）:
- C1 69563.068 vs expect 69563.064；C2/C3/C4 全过，tag 面 n=1 侧，中心 (±40,35)

### S4
`Verifier contract: 全局倒角 / Criteria: C1 单Solid+体积∈(0.98·V_s3, V_s3)；C2 bbox 与 S3 一致±0.05；C3 最终实体上 ql.tag(mount) 恰1面/侧 中心(±L/2, d_motor/2)；C4 槽底仍为平面+Y@y=d_motor/2 n=2 面积∈(π(rp−2fr)², πrp²)；C5 fillet patch n≥1 / Script: verify/s4_verify.py`

Hypothesis 结果（verify/s4_hypothesis.py，已运行）:
- H1 采用: 选择卡 n_edges=20 (len_sum 1111.43)，全边 fillet R1.2 成功；patch faces 12（切边处 1:1，光滑切边不产面）
- H2/H3 采用: 体积 −0.161%；bbox 严格不变
- H4 发现+修复: **tag 经 fillet lineage 断裂（n=0）**；槽底面存活为平面（area 366.44=π(rp−fr)²）→ 模型修复：S4 阶段倒角后重打标（检查不放松）
- H5 known-bad: radius=2.0>thickness/2 → SimpleCADError ✓（守卫承重）

S4 阶段证据（verify/s4_verify.py 全 PASS）:
- C1 69450.913∈带内；C2 bbox 逐维一致；C3 tag n=1/侧 中心(±40,35)；C4 366.44∈(289.53,452.39)；C5 patch n=12

## 参数变更重跑（2026-08-26，D 40→20）

用户定向 D 取半；守卫推导联动 d_motor 70→30、R_corner 20→17（约束链更新为
`d_profile/2 < R_corner < D`）。S1–S5 验证器 + 渲染检查全 PASS：
- S1: bbox y=[−15,20]，Pappus 体积门过
- S2/S3: 平底/槽特征全过（槽深仍 5，槽底 y=15）
- S4: 体积 41549.270；tag 重打标后 n=1/侧
- S5: scadpkg 9.92MB / STEP 107KB / STL 28888 三角形；新进程重开 + tag 索引过
- 渲染检查（verify/s5_render_check.py）: front 视图橙 17838px@x986 + 紫 18452px@x413
  关于图像中心镜像对称（Σx=1399≈w−1，Δy=1px，面积比 0.97）→ 恰两安装面、左右对称

### S5
`Verifier contract: 导出 / Criteria: C1 三工件存在非空；C2 新进程 read_product_package 校验+root single_solid@u-link-motor-mount；C3 BREP valid+体积与 S4 一致；C4 部件体上 tag 可索引；C5 STL solid_count=1 v/t>0、STEP defs=[u-link-motor-mount]（单件包 occurrence=0 为诚实编码）；渲染: 正交前视图 azim=90（安装面法向+Y）双色连通域恰 2 且镜像对称 / Script: verify/s5_verify.py + verify/s5_render_check.py`

Hypothesis/发现（S5 期间）:
- 视觉评审不可用（子代理无图像能力，如实记录为 not run）；关注点已转为确定性像素检查（双色 HSV 掩码）
- 渲染器事实（源码核实）: tag 调色板按序号分配 #f39c12(橙)/#9b59b6(紫)；轴色 R/G/B；azim 绕 +Z 度量 → 部件 +Y 法向面的正对视图为 (elev, azim)=(x, 90)，azim=0 系列视图安装面均迎面成线
- s5_verify 硬编码体积/中心已参数化（从 params() 推导），消除变更时的验证器债务

## S6 参数化变体与范围限制验证（2026-08-26）

`Verifier contract: 参数变体扫描+边界矩阵 / Criteria: 有效矩阵 8 变体 × G1-G7（单实体/bbox/平底/S3 槽特征三件套/S4 命名面/槽底面积带/倒角体积带）；无效矩阵 10 边界全部被 assert_params 以 AssertionError 拒绝（严格不等式边界=恰好取等即拒） / Script: verify/s6_param_sweep.py`

Hypothesis/发现（verify/s6_hypothesis.py，已运行）:
- H1 采用: 变体覆盖 = 模块级变量直接赋 plain float（`_value` 兼容），sweep 用 build_stage 避开 @part 缓存陷阱
- H2/H3 发现+修复: 两条缺失守卫承重——`fr≥rp`(rod_d30/th20/fr7) 与 `fr≥depth`(rod_d40/th10/D30/dm54/fr4.9) 旧守卫全放行、内核 fillet 崩溃 → assert_params 新增两条
- 变体扫描再发现+修复: `thickness=8/fr=3` 过全部守卫仍崩 → 真根因是**端面环宽** r−rp=thickness/2 被双侧倒角吃穿（2·fr≥环宽）；同时纠正 S4-H5 归因（R2.0 炸因 2·2>3 环宽，非壁厚 3）→ 守卫收紧为 `fr < thickness/4`

S6 证据（verify/s6_param_sweep.py ALL PASS，随后 S1-S5+渲染全量回归 PASS）:
- 有效: L∈{50,80,120,200}（长度适应 ✓）、rod_d∈{24,30,40}（联动 D30/dm40/rc25）、thickness=8+fr1.8、fr0.3、D26/dm44 深槽
- 无效边界 10/10 拒绝: dm/2==D、dm/2>D、rc==rod_d/2、rc==D、fr==thickness/4、fr==thickness/2、L==2rc、fr==rp、fr==depth、rc>D
- 最终约束链: dm/2<D；rod_d/2<rc<D；L>2rc；fr<thickness/4；fr<rp；fr<depth

## S7 背切上移至 75% + feature.back_face 命名（2026-08-26）

`Verifier contract: 背面几何+命名 / Criteria: S2' C1 体积∈段面积解析带；C2 恰1平面−Y面@y=back_y 面积≥0.9·(L−2rc)·弦宽 且 tag n=1；C3 bbox y=[back_y,D]±0.05；S4 C6 back tag n=1；S6 G2/G3/G8 随动 + B10 frac==1 / B11 frac==0.4 / B12 back_y==floor 全拒 / Script: verify/s2_verify.py+s4_verify.py+s6_param_sweep.py`

Hypothesis/发现（verify/s7_hypothesis.py，已运行）:
- H1 采用: 75% 切割 → 恰 1 个 −Y 平面（弦带 2769.0 = 直段弦条+拐角弦区连通），bbox y=[7.5,20] 精确，仍单实体
- H2 采用: 体积移除 ∈ 解析带（a_below = πr²−弓形面积）
- H3 发现+修复: **back tag 连 S3 pocket cut 都不过（n=0），fillet 后亦 n=0**；几何面经 fillet 存活（n=1, area 2366.8）→ 链内 S2/S3/S4 每次拓扑变更后重打标（与 S4 安装面同策略）

S7 证据（全量回归 ALL PASS）:
- S1-S4 验证器、S6 sweep（8 变体×G1-G8 + 13 无效边界 = 77 检查）、S5 导出（体积 20246.508, STL 29700 三角形）、渲染检查全绿
- 安装面→背面距离 = 15−7.5 = 7.5（通孔路径减半，达成用户意图）
- build_flat_bottom 重复实现已收编为 build_stage("s2")（消除几何重复源）

## S9 弃卡扣 → boss 柱 + 盖子 + 装配（2026-08-26）

`Verifier contract: boss/盖/装配 / Criteria: 探针 H1-H6（boss 柱面分段和∈[55,105]%整面、4 孔壁、体积解析带含腔+boss−倒角余量、4 顶环 chamfer、命名面、pc 避让）；verify C1-C6（盖 bbox/孔位/包容/采样零干涉+径向隙 0.25/装配零残差/命名面） / Script: verify/s9_hypothesis.py + verify/s9_verify.py`

关键发现与修复（诊断链）:
- 筋 x 向穿 boss 中心 = 穿孔（既堵孔又啃柱面）→ **两段式筋**（内端自孔壁外让 0.5）
- diag 分组子进程定位全局倒角毒边: 腔壁竖角边（3.0 长与 rim 组合崩）→ 排除;
  boss 邻域/筋盒边全部排除（薄壁+孔保护）; included = mount+腔rim+backface长边（组合验证 OK）
- boss 顶 chamfer 使 fillet.global_patch tag 断裂（S4 已知 lineage 模式）→ 落地证明改终态拓扑（TORUS≥2 + CONE=4）
- intersect_rsolid 对零重叠实体报 validation 错 → 干涉检查改采样分类器法（cover 内网格点无一在 body 内）
- back_selector 被 boss 顶环污染（5 面）→ 加面积 ≥100 判据
- S6 新守卫（变体矩阵重适配后全绿）: fr<cavity_h/2（两面圆角不在腔壁相遇, thickness8/fr1.8 证）;
  waist_x≤L/2−rc+5（腰不深越拐角 torus 区, L=50/60 证——**腔设计适用域 L≥80, rod_d≥~28**;
  rod_d=24 属域外, 移出矩阵记为设计边界）
- 装配: identity placement + fixed(back_datum↔cover_bottom), solve 残差全 0

S9 证据（全量回归 ALL PASS: S1-S6 sweep+S9+S5+渲染）:
- body 体积 16849.555; cover 1287.668（解析 1292）; 装配包 14.4MB, STEP defs 3, occ 2, STL 35280 tri
- 盖-腔单边隙 0.15, boss-盖孔径向隙 0.25, 采样干涉 0
- 无效边界 19/19 拒（含 boss 越腔/孔过深/筋超高/boss 撞孔位/腰深越拐角/fr==cavity_h/2）

## S10 弃方形腔 → 75% 剖分两件 + 轮廓贴合 shell（2026-08-26）

`Verifier contract: 剖分+轮廓腔+boss+shell / Criteria: C1 上件命名面(mount×2+back 环)+中心; C2 boss 环采样+2 盲孔壁+≥14 筋倒角面; C3 band 开放(远离 boss 无材料)+shell 轮廓壁; C4 shell 壁/走线口/底孔 Ø 一致; C5 采样零干涉; C6 装配零残差 / Script: verify/s10_hypothesis.py + verify/s10_verify.py`

关键发现与修复（诊断链）:
- **布尔越界纪律**: cut 盒顶停在臂盖区内部(19.5/12) → 内核静默垃圾(353mm³); 盒顶越界过杆顶 → 正确。所有 cut/intersect 非剖分侧越界
- **cut vs intersect 语义事故**: 腔工具误用 cut(er, box)(=er−box) 掏空了 7.5 以上全部内芯 → intersect(er, box)
- **fillet 静默负体积**: band 平面(7.5/2.5)弦 rim 边参与全局倒角 → 内核返回 −8790mm³ 烂实体(无异常!); 修: `_fillet_included_edges` 只含 y>back_y+2.5(S4-S9 一贯可靠集); 剖分接口锐边本就是正确配合设计
- **fillet 吞筋斜边**: 全局圆角重建销毁 16 条筋斜边 → 顺序换: 筋倒角(0.3)先、全局圆角后
- **band 干涉设计缺陷**: 上件 blank 带壁与 shell 壁在 [2.5,7.5] 全带重叠(120 采样点) → 上件 75% 以下仅存 boss+筋(等价用户两刀工艺几何),壁全让位 shell
- boss 柱 union 底界精确 by−boss_h(自由柱曾垂到 0.5); rim 面被 seam 分裂→打标放宽 n≥1
- 验证器教训: 采样点避开解析边界(±0 距离 ON 误判); 圆柱面记账因内核重叠弧段不可靠→材料采样法

S10 证据（全量回归 ALL PASS: S1-S6 sweep(11 变体×8 不变量+13 边界)+S10+S5+渲染）:
- 上件 20650.215(84 面), shell 11474.838(22 面); 装配包 13.2MB, STEP defs 3 occ 2, STL 37554 tri
- 走线口: y=4.75 壁区间 [50.5,52.8](探针), 4×4 方口贯通; 底孔 Ø2.7=boss 孔 Ø2.7 对齐 (±12,0)
- 轮廓贴合: shell 腔=缩径扫掠(r−wall_t)精确内偏移; 腔体积=Pappus(r=13) 55963.7 零误差

## S11 两刀工艺修正 + 沉头孔 + 大走线口 + 深槽（2026-08-26）

`Verifier contract: 接触面/沉头/方口/深槽 / Criteria: P1 floor_top==boss_tip(2.5)+地板带实体+上下腔空; P2 CONE×2+通孔壁×2; P3 方口贯通; P4 零干涉(采样避开接触面); P5 安装面-back=wall_t 精确 / Script: verify/s11_probe.py`

关键发现与修复:
- **S10 结构缺陷确认**: shell 螺栓孔在管底(−15)距 boss 尖 15.5mm——螺栓悬空(用户指出少切第一刀)
- 两刀工艺: 第一刀@0.5(地板底) 第二刀@7.5; shell=下段−内偏移∩(槽带∪地板上腔带) → 地板[0.5,2.5]顶面恰贴 boss 尖 2.5
- fillet 阈值精调: y>(back_y+d_motor/2)/2（原 y>10 漏掉 9.5 处安装面 rim——深槽后 rim 下移）
- sweep 默认参数脱节事故: set_params 残留 d_motor=30 与 u_link 新默认 19 不一致 → 孔壁质心窗口漂移混入臂外圆柱面(282.74@y18.5)——教训: 参数默认变更必须同步所有验证器快照
- iso 视角安装面被 10.5 深槽壁遮挡(几何必然) → 渲染检查由前视图承担双面对称校验
- rod_d 变体联动新守卫: rod_d=32 需 dm≥20(back_y=8); rod_d=40 变体 dm 40→36(原值 dm/2==D 被新守卫拒)

S11 证据（全量回归 ALL PASS）:
- 上件 15628.373(接触面 2.5=2.5 精确), shell 15794.845(地板+沉头×2+9×7 方口×2)
- 安装面 9.5−back 7.5=2.0=wall_t; 槽深 5→10.5; sweep 12 变体+14 边界全过
- 装配零残差; scadpkg/STEP/STL 重导出

## S11b shell 平底修正（2026-08-26，用户指出底面错误）

`Verifier contract: 平底/沉头/方口 / Criteria: P1 平底面@0.5 n=1 面积 2738 且 0.5 以下无材料 bbox ymin=0.5; P1b 地板实体+腔空+ft==boss_tip; P2 CONE×2+通孔壁×2; P3 方口贯通+环壁完好; P4 零干涉; P5 安装面−back=wall_t / Script: verify/s11_probe.py`

关键发现与修复:
- **shell 底面结构错误（用户指出）**: S11 版保留了 0.5 以下的原始管底曲面+槽内走线；
  正确架构=第一刀@0.5 切掉下半部 → 平底面 0.5，shell=[0.5,7.5]，线束走腔体[2.5,7.5]
- make_box y 居中语义再坑: notch 盒 y∈[0,5] 而非[2.5,7.5]（静默切错位置）→ yc=ft+h/2
- 侧检取样教训: 环形壁带随 z 增大内移（圆管几何），采样点必须按 torus 几何取

## S12 防割手圆角（2026-08-26）

`Verifier contract: / Criteria: C1 rim torus>=4+cyl>=2; C2 口角圆柱面>=6; C3 上下sill 完好+口敞开; C4 有效性回归 / Script: verify/s12_verify.py`

关键发现:
- **矩形口边缘 fillet 不可行**: 口角三面圆角相遇处内核稳定崩溃（R0.3-0.6 全败;
  逐边单试全过=链式传播问题, 非单边几何）; 口底边与地板顶共面时进一步退化
- **源型圆角(rounded-rect extrude)是正解**: 一次成功、面数更少(15)、免 fillet 稳定
- 环壁采样教训: 端部环壁随高度外移(torus 几何), 验证采样点必须按 y 分带定位

## S12b 走线口丢失修复（2026-08-26，用户发现）

- 事故: S12 换 rounded-rect 源型后走线口消失（端壁 z 全宽实心）。
- 根因: `_rounded_rect_prism` 中 extrude(自 x=0 拉 distance) 后又 `translate_shape(+x_lo)`
  = 双重平移, 工具落在 x∈[70.5,89.5] 空气里, cut 静默无效果（skip_non_intersecting=True）。
  wire 本就画在目标 x_lo 处 → extrude 后不需任何平移。
- 教训:
  1. cut 工具落空是**静默**的——`skip_non_intersecting=True` 交互默认值吞掉无效工具
  2. s12_verify C2/C3 采样点恰落在口外（口角圆柱面中心 z≈±3，非口中心）→ 误判 PASS；
     验证口敞开必须直接采**口中心**（x=端壁, y=口中带, z=0）
- 修复后: 口敞开/壁完好/上下 sill 在; S11/S12/全量回归 ALL PASS

## S13 电机槽走线窗（2026-08-26）

`Verifier contract: / Criteria: P1 方向开度图(对角开/内向盲); P2 8窗全开+窗间壁+底边=3±0.3 / Script: verify/s13_probe.py`

关键决策与发现:
- **切口在最后一步**（用户定向）: 倒角后成品拓扑直接切窗——省去 fillet 排除窗区逻辑,
  rounded-rect 源型自带角圆角, 链更简
- 方向开度探针（P1）: 内向(0/180°)在窗低段 y=13/15 撞底部拐角熔合区（BLIND）,
  ±Z 与对角 45° 全高度开 → 相位定 45°（对角布置）
- 跨 session 工具构造第三次踩坑（s8/s13）: rotate/translate 后工具仍属原 session,
  正式实现必须进链; 探针改验证链成品
- sweep: G7 体积带补窗材料项(8×w×h×壁厚×0.85); D=26/dm=44 深槽变体与窗需求
  本质冲突（臂端余量<off+h）→ 联动 dm=36; 新边界 B26-B29（off<3/off>5/窗顶入圆角区/窗宽吃壁）

## S14 走线窗周向加宽 2 倍（2026-08-26）

- cable_w_w 5→10（周向弦长 2 倍, 弧宽 10.31mm, 窗间壁弧余 34mm）
- 守卫上界 1.2→1.6×rp（原值恰好卡死新宽度）
- 窗体积公式系数标定: 平板近似 0.85 → 实测 1.046（弧壁外表面>内表面; 直接构建
  无窗版与有窗版差值标定, 非猜测）——G7/C1 体积带用 ±180 带
- 全量回归 ALL PASS
