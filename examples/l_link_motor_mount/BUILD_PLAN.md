# BUILD_PLAN: l_link_motor_mount

## [Role Switch: Master Planner]
Reading: REQUIREMENTS.md, discipline/mechanical-modeling.md, discipline/datums-and-coordinate-systems.md
Artifact out: BUILD_PLAN.md

Datum（来自功能基准）: 原点 = 左电机轴线 ∩ 底部直段轴线；+X 沿连杆指向电机2；+Y 向上（左槽开口）；+Z 横向。
受控基准面: 左安装面 y=d_motor/2；安装面 2 x=L−plate_t；电机2 落座面（板面）x=L；剖分水平段 y=back_y；左臂端 y=D；右端 x=L+(D−d_motor/2)。
对称: 关于 XY 平面（z 镜像）对称——三叉臂 0/120/240°（自 +Y 量向 +Z）与径向孔同相，保持该对称。
三件均在装配位建模（placement=identity）：共享 L/plate_t/rod_d 等参数，采样干涉/贴合检查在同一坐标系进行，无未溯源的变换常数。

构造策略（profile-driven + 刀具布尔）: 主形体 = 圆截面沿 L 形草图路径 sweep（L、D、r_corner 直接为路径参数，同 U-link `_u_path_wire`）；
"l" 剖分线 = XY 约束草图（直线-相切弧-直线开放链）闭合成刀具面沿 Z 拉伸，上件 = rod − 壳区刀、壳体 = rod ∩ 壳区刀（一刀两件，接口天然贴合）；
槽/腔/孔/窗/凹槽为命名刀具 cut；倒角在外形与连接特征稳定后；走线窗、三叉凹槽、径向孔在倒角后最后切（U-link S13 结论：免 fillet 排除逻辑）。
转接板 = 圆盘 extrude + 刀具/凸起布尔；**盘面拓扑由 `PlatePreset` Enum 的 if 分支决定**（孔数/相位/臂段/中心孔），标量尺寸走 Var。

## 零件与文件

| 文件 | 零件 | 说明 |
| --- | --- | --- |
| `l_link.py` | 上件 `l-link-body` | 左臂+左槽+上半条+整圆套筒+右槽+boss+凹槽+径向孔 |
| `shell.py` | 壳体 `l-link-shell` | 剖分下侧圆底管壳+腔+pad/沉头+走线口 |
| `adapter_plate.py` | 转接板 `l-link-adapter-<preset>` | `PlatePreset.STAR3 / CENTER4` |
| `assembly.py` | 装配 `l-link-motor-mount` | 上件 ground；壳体/转接板 fixed |

### 迁移到 notebook 之后的文件布局

本台账记录的是逐阶段构建过程；其中引用的 `verify/sN_verify.py`、`sN_hypothesis.py`、`sN_known_bad.py`、
`s10_variants.py`、`s11_verify.py`、`render_stage.py`、`verify/renders/` 与 `assembly.py` 已随 notebook 迁移删除，
证据数值保留为历史记录。现在的文件：

| 文件 | 内容 |
| --- | --- |
| `l_link.py` / `shell.py` | 上件 `l-link-body` / 壳体 `l-link-shell` part notebook，每个 FTC 块一个 cell |
| `adapter_plate.py` | 转接板族：`id = dimensions.plate_part_id(preset)`，`sca run ... --id l-link-adapter-center4 --set PRESET=center4` |
| `l_link_motor_mount.py` | 装配族 `l-link-motor-mount-<preset>`：`scad.use` 三件，上件 ground、壳体/转接板 fixed，strict 求解 |
| `dimensions.py` / `common.py` | 共享参数（Var + 守卫链 `check_body/check_shell/check_plate`）与草图/基准 helper（普通模块） |
| `export.py` | `run_notebook` 加载产品 → `.scadpkg` → STEP / STL + 渲染 + `out/export_facts.json` |
| `verify/contracts.py` | S1–S9 阶段合同（原 `sN_verify.py` 的 `check_sN` / `check_sN_guards`），在 cell 值上检查 |
| `verify/acceptance.py` | `stages`（S1–S9 on cell values）/ `guards`（逐阶段守卫 + S10 边界矩阵）/ `sweep` / `edges`（变体经 `overrides={"p": ...}` 重跑全部 notebook） |
| `verify/export_artifacts.py` | 原 S11：新进程重开 package / STEP / STL 并对照 export facts |

阶段 → cell：S1 `l_rod`；S2 `motor_pockets`；S3 `l_split` + 壳 `shell_region`；S4 壳 `cable_notch`；
S5 `boss_holes` + 壳 `csink_holes`；S6 `cap_rim_fillet` + 壳 `rim_name`；S7 `mount_face_names`；S8 `plate_face_names`；S9 装配产品。
面 tag 只在每件最后一个 annotate cell 打一次，所以 S2–S5 的合同以 `tags=None` 跳过 tag 计数。

## 阶段划分

- **S1 L 形扫掠杆**（l_link.py 基础，壳体共用）
  - 输出边界: 单实体 L 杆（竖臂 + R=r_corner 拐角弧 + 直段至 x_end），两平面端盖 y=D / x=x_end。不含: 槽、剖分、腔、倒角。
  - 验证目标: 单实体；体积 = Pappus（直段+弧+臂）；bbox [−15,90.5]×[−15,20]×[±15]；端盖恰 2 平面（+Y@y=20、+X@x=90.5）。
- **S2 两电机槽 + 命名安装面**
  - 输出边界: 左槽 ⌀24 轴 Y 底 y=9.5（tag `feature.motor_mount_floor_left`）；右槽 ⌀24 轴 X 底 x=75（tag `feature.motor_mount_floor_right`）。不含: 剖分、凹槽。
  - 验证目标: V2（面位置/法向/面积、两法向正交）、V3（槽深 10.5 / 15.5、槽壁 3）、tag 各恰 1。
- **S3 "l" 剖分 → 上件毛坯 + 壳体毛坯**
  - 输出边界: 两单实体；接口 = 平面 y=7.5（x≤48）+ 圆柱 R12 心(48,−4.5) + 平面 x=60。不含: 腔、boss、倒角。
  - 验证目标: V4（接口面类型/位置、采样零干涉、体积和 = S2 体积）、V3 右槽整圆（x≥60 无剖分面）、壳体圆底 y_min=−15。
- **S4 壳体轮廓腔 + 走线口**
  - 输出边界: 壳体 = 等厚 wall_t 圆底管壳（右端弧形端壁）+ 左端 9×7 走线口。不含: pad/孔、倒角。
  - 验证目标: V5（壁厚采样、弧端壁厚、左槽底→腔 = wall_t）、V8（口中心空、sill 完好）。
- **S5 boss/筋（上件）+ pad/锪平/沉头通孔（壳体）**
  - 输出边界: 2 boss @x=25/40 + 4 向筋 + 盲孔；壳体 2 pad + 锪平 + 沉头 + 通孔。不含: 倒角。
  - 验证目标: V6（boss 底贴 pad 间隙 0、孔同轴、CONE×2、锪平×2、锥下壁 ≥1.0）、零干涉。
- **S6 同轴走线孔（壳体）+ 倒角（上件 R1.2 / 壳体 R0.6）+ 重打标**
  - 输出边界: 壳底 −Y 同轴走线孔（用户 S6 追加）；上件 4 条端盖 rim R1.2；壳体两走线口外环 R0.6（边集经用户确认的计划预览，见 `verify/renders/s5_*_s6plan.png`）；
    接口边/槽底边/锪平/锥口锐；命名面重打标。不含: 窗/凹槽/径向孔。
  - 验证目标: V8 同轴孔、V9（tag 各恰 1、接口面/安装面面积不变、体积带、bbox 不变、圆角面数与位置）。
- **S7 倒角后切削（上件）: 8 走线窗 + 三叉凹槽 + 3 径向沉头孔**
  - 输出边界: 上件成品。
  - 验证目标: V7（窗中心空/窗间壁完好/底边距落座面 3）、凹槽（宽 2.7 深 2.2 完整臂 r∈[0,11.3]）、V12 套筒侧（过孔+锪平+沉头 @0/120/240 x=77.5、头不凸出 r=15、与窗/凹槽不相交）。
- **S8 转接板（两个 preset）**
  - 输出边界: `build_adapter_plate(preset=...)` 对 STAR3 / CENTER4 各产单实体。
  - 验证目标: V11（厚 5 ⌀23.8、孔数/PCD/沉头在背面、凸起高 2 落在凹槽内零干涉、中心孔按 preset）、V12 板侧（导孔同轴、到电机孔/沉头口 ≥ min_web）。
- **S9 装配 + 贴合/干涉 + 渲染评审**
  - 输出边界: `assembly.py` 三件装配（每 preset 一份），connectors motor_left/motor_right。
  - 验证目标: V10 solve 零残差；板背面贴安装面 2 间隙 0、凸起顶到槽底 0.2；三件两两采样零干涉；命名视图 iso/前视/右视 → 隔离子代理评审。
- **S10 参数扫描 + 守卫边界矩阵**
  - 验证目标: L/split_frac/rod_d 等有效变体 × 不变量全过（× 两 preset）；约束链每条边界恰等即拒。
- **S11 导出（Role 5）**: scadpkg + STEP + STL（装配 + 每 preset 转接板）→ out/；新进程重开。

## Requirement → stage

| 需求区 | 阶段 |
| --- | --- |
| 1 L 扫掠 | S1 |
| 2/3 两槽+命名面（槽底下沉） | S2 |
| 4 "l" 剖分 | S3 |
| 5 轮廓腔 / 8 走线口 | S4 |
| 6 boss + 沉头 | S5 |
| 9 圆角 | S6（转接板圆角在 S8） |
| 7 走线窗 / 10 凹槽+径向孔（套筒侧） | S7 |
| 10 转接板+preset | S8 |
| 装配 / connectors | S9 |
| 约束链 | S10（守卫逐阶段写入，S10 统一扫描） |
| 导出 | S11 |

## Stage checklist（本会话无 TodoWrite 工具 → 以本节为门禁台账）

```text
[x] Requirements
[x] Plan
[x] S1 plan verifier
[x] S1 model
[x] S1 run verifier
[x] S2 plan verifier
[x] S2 model
[x] S2 run verifier
[x] S3 plan verifier
[x] S3 model
[x] S3 run verifier
[x] S4 plan verifier
[x] S4 model
[x] S4 run verifier
[x] S5 plan verifier
[x] S5 model
[x] S5 run verifier
[x] S6 plan verifier
[x] S6 model
[x] S6 run verifier
[x] S7 plan verifier
[x] S7 model
[x] S7 run verifier
[x] S8 plan verifier
[x] S8 model
[x] S8 run verifier
[x] S9 plan verifier
[x] S9 model
[x] S9 run verifier
[x] S10 plan verifier
[x] S10 model
[x] S10 run verifier
[x] Export     <- 6 产品 X0–X4 ALL PASS（SDK BRep 改二进制后解除阻塞，见 §S11）
```

## Verifier contracts（Role 3 逐阶段补填）

### S1
Verifier contract: L 扫掠杆（`l_link.build_stage("s1")`）/ Criteria: C1 单实体 + brep.valid + 体积 = π r²·中心线（(D−r_c)+π r_c/2+(x_end−r_c)）±0.5%；
C2 恰 1 平面 +Y @ (0,D,0)、恰 1 平面 +X @ (x_end,0,0)，面积 π r²，平面总数 = 2；C3 tight bbox = [−r,x_end]×[−r,D]×[±r] ±0.05；
C4 `assert_params(p)` 接受默认、拒绝 r_corner=r / r_corner=D / d_motor=2D / Script: `verify/s1_verify.py`（`check_s1(rod,p)` + `check_s1_guards(module)`，后续阶段复用）
- Hypothesis evidence (`verify/s1_hypothesis.py`): 3 实体开放链草图 dof=0 solved；volume 72950.282 = Pappus（rel 0.000000）；caps (0,20,0)/(90.5,0,0) 各 706.858；
  planes=2；`sweep_rsolid(start_face_tag/end_face_tag)` 各命中 1 面（后续 cap 可走 tag 路线）。
  **发现**: `brep.bounding_box` 带 ~0.12 容差间隙（−15.118），不能判 0.05 误差 → bbox 改用 `_common.tight_bbox`（OCP AddOptimal，仅验证侧）。
- Known-bad proof (`verify/s1_known_bad.py`): KB0 正确杆 pass；KB1 拐角 R19 → C1 fail（72343.5）；KB2 直段止于 x=L → C1/C2/C3 fail；
  KB3 rod_d 28 → C1/C2/C3 fail；KB4 臂镜像向下 → C2/C3 fail（体积相同，C1 不能单独判）；KB5 无守卫源 → C4 fail。ALL DISCRIMINATED。

### S2
Verifier contract: 两电机槽 + 命名安装面（`l_link.build_stage("s2")`）/ Criteria（rp=(rod_d−thickness)/2, fy=d_motor/2, fx=L−plate_t）:
C1 单实体 valid，体积 = V_S1 − π rp²·((D−fy)+(x_end−fx)) ±0.5；C2 恰 1 平面 +Y @ (0,fy,0) 与恰 1 平面 +X @ (fx,0,0)，面积 π rp²，法向点积 0（两电机轴垂直）；
C3 轴线采样：槽底+e..端盖−e 空、槽底−e 实（深 10.5 / 15.5），槽半径 rp−e 空 / rp+e 实；
C4 两端面环面积 π(r²−rp²)（槽壁 = thickness/2 = 3），右槽 r−e 环全实，**左槽最小径向壁 ≥ wall_t=2**；C5 两 tag 各恰 1 且落在 C2 面上 / Script: `verify/s2_verify.py`（`check_s2`）
- Hypothesis evidence (`verify/s2_hypothesis.py`): 两圆柱刀具全在料内 → 体积降 11762.123 = 解析值；floor 选择器各 1（面积 452.389）；轴线/半径采样全过。
  **发现**: 左臂 y<r_corner 段为圆环（torus），左槽外侧壁在槽底 −X 侧减薄至 **2.13**（端面处 3.0）——与 U-link 默认几何相同，≥ wall_t=2，记为 C4 下限而非 3。
- Known-bad proof (`verify/s2_known_bad.py`): KB0 正确 pass；KB1 右槽底在 x=L（未下沉 plate_t）→ C1/C2/C3/C5；KB2 rp 11.9 → C1–C4；KB3 左刀具短留皮 → C1/C3/C4；
  KB4 右槽轴偏 z+0.5 → C2/C3（体积不变，C1 不能判）；KB5 tag 互换 → C5；KB6 未打 tag → C5。ALL DISCRIMINATED。

### S3
Verifier contract: "l" 剖分（上件 `l_link.build_stage("s3")` + 壳体 `shell.build_stage("s3")`）/ Criteria（by=r(2·back_cut_frac−1), x_a=split_arc_frac·L, x_b=split_end_frac·L, Rs=x_b−x_a, 弧心 (x_a, by−Rs)）:
C1 两单实体 valid，V_up+V_sh = V_S2 ±0.5；C2 上件恰 1 平面 −Y@by（center.x<x_a）/ 恰 1 CYLINDER 于弧窗 / 恰 1 平面 −X@x_b，壳体镜像 +Y/CYL/+X 各恰 1；
C3 弧两侧采样（15/45/75°，z∈{0,±8}）Rs−e 属壳、Rs+e 属上件；C4 壳体 tight bbox y_max=by、x_max=x_b、y_min=−r（保留圆底）、z=±r，上件 bbox = S2；
C5 x≥x_b 套筒整圆（r−e / rp+e 环 + 轴线点全属上件）、两安装面 tag 在上件各恰 1；C6 2 mm 网格严格 IN 零重叠、S2 点零遗漏；
C7 守卫拒 x_b>fx−wall_t / x_a≥x_b / x_a≤r_corner+2 / Rs>by+r / back_cut_frac=1 / 左槽底<by+wall_t，接受默认 / Script: `verify/s3_verify.py`（`check_s3` + `check_s3_guards`）
- Hypothesis evidence (`verify/s3_hypothesis.py`): 5 实体闭合区域草图（flat→相切弧→drop→floor→back）fix+4 h/v+radius+2 tangent+2 extent → dof=0，弧心 (48,−4.5)、pb (60,−4.5)；面积 2731.597；
  upper 25928.576 + shell 35259.583 = S2 61188.159；接口面各恰 1；1.5 mm 网格 18000 点 both=0 missing=0。
- Known-bad proof (`verify/s3_known_bad.py`，区域用 box/圆柱并集独立构造): KB0 正确 pass；KB1 全长平切 y≤by → C1/C2/C3/C4/C5；KB2 无弧台阶 → C2/C3（体积相同 C1 不能判）；
  KB3 壳区 +0.5y 重叠 → C1/C2/C3/C4/C6；KB4 平底壳 y≥−14 → C4（仅 C4 能判）；KB5 上件取自无槽杆 → C1/C5；KB6 无守卫源 → C7。ALL DISCRIMINATED。
  **发现**: tag 不跨 `cut_rsolid` 存活（首跑 KB0 C5 tags=False）→ 模型剖分后必须重打安装面 tag。

### S4
Verifier contract: 壳体轮廓腔 + 走线口（`shell.build_stage("s4")`）/ Criteria（e=0.1）:
C1 单实体 valid，0<V<V_S3壳，tight bbox = S3 壳（圆底、x_min 保留）；C2 管壁：x∈{20,35,45} 与拐角弧 φ=200/230/260° 截面，管半径 r−e / r−wall_t+e 实、r−wall_t−e 空（下半、避开走线口）；
C3 弧形端壁：半径 Rs−e / Rs−wall_t+e 实、Rs−wall_t−e 空（10/45/80°，z∈{0,±6}），竖直段 x_b−e / x_b−wall_t+e 实、x_b−wall_t−e 空；
C4 腔在剖分面敞开（(x, by−e, 0) 空），接口 +Y@by 恰 1、+X@x_b 恰 1、弧窗 CYLINDER 恰 2（外接口弧 + 内端壁弧），rim tag `feature.shell_rim_face` 恰 1；
C5 走线口：壁中面在圆角矩形内采样空（中心/±3/圆角内侧），sill（y=by−sill/2）、下方、两侧实；
C6 守卫拒 2·notch_rr ≥ min(w,h) / notch_sill=0 / 走线口未穿壁（notch_h=17）/ Rs−wall_t<1，接受默认 / Script: `verify/s4_verify.py`（`check_s4` + `check_s4_guards`）
- Hypothesis evidence (`verify/s4_hypothesis.py`): 腔区草图（敞口顶 by+ovs → x_a 台阶至 by−wall_t → R=Rs−wall_t 同心弧 → x_b−wall_t 竖直）fix 弧心+台阶脚 → dof=0，arc_b=(58,−4.5)；
  腔 = 内缩扫掠 ∩ 腔区，壳 9191.645 valid；圆角矩形 4 线 + 4 相切弧 + 等半径 dof=0，面积 61.0686 = 解析；**`rotate_shape` 角度单位为度**（90° 绕 Y 把 +Z 拉伸映到 +X）；
  走线口刀具 x∈[−25,0] 去除 138.906，壳 9052.738 valid 22 面；管壁 45/45、端壁 33/33、敞口、走线口采样全过。
- Known-bad proof (`verify/s4_known_bad.py`，腔区/走线口用 box+圆柱并集独立构造): KB0 pass；KB1 腔区无端壁偏移 → C3；KB2 壁 1.5 → C2；KB3 腔在剖分面下 0.5 封闭 → C4；
  KB4 无走线口 → C5；KB5 走线口无 sill → C1/C4/C5（rim 被劈成 2 面）；KB6 rim 未打 tag → C4；KB7 无守卫源 → C6。ALL DISCRIMINATED。
  **发现**: 挖腔后弧窗内出现第 2 个 CYLINDER（内端壁弧），首版 C4 "恰 1" 误判正确件 → 契约改为恰 2（端壁厚度由 C3 径向采样负责）。

### S5
Verifier contract: 长 boss + 十字筋（上件 `l_link.build_stage("s5")`）+ pad/锪平/90° 沉头通孔（壳体 `shell.build_stage("s5")`）
/ Criteria（br=boss_d/2, hr=孔半径, pad_top=−(r−wall_t−pad_t)=−12, ys=−r+spot_depth, 锥 cr=csink_d/2 @ys → hr @ys+(cr−hr)）:
C1 上件单实体 valid、V>V_S3上件、tight bbox = S3 上件、两安装面 tag 各恰 1；
C2 boss (bx, z=0)：环中半径 pad_top+e..by−e 实、筋下 br+e 空、pad_top−e 下无料、盲孔轴线空至 pad_top+depth−e、其上实；恰 2 平面 −Y@pad_top（面积 π(br²−hr²)，心在 bx）；
C3 十字筋 4 向/boss：尖/根实、厚 rt（rt/2∓e）、斜边内实外空、by−gh 下空；倒角角点 (0.08,0.08) 空、(0.25,0.25) 实；斜倒角平面（各分量 |n|<0.8）恰 16；
C4 壳体单实体 valid、bbox = S4 壳、rim tag 恰 1；恰 2 平面 +Y@pad_top（π(pd²/4−hr²)）、2 平面 −Y@ys（锪平环 π(sd²/4−cr²)）、2 CONE（心在 bx）；pad 内实外空、轴线通、锪平凹空环实、锥口空、锥下孔壁实且长 ≥1.0；
C5 boss 附近 0.5 网格严格 IN 零干涉、pad_top 环两件皆 ON/IN（贴合间隙 0）、hr−e 环两件皆空 / hr+e 环各自实（同轴同径）；
C6 守卫拒 boss 近拐角 / 近剖分弧 / 两 boss 筋相碰 / 筋超出腔开口 / 盲孔 > boss−0.5 / rib_t<2·chamfer+0.3 / pad 顶不完整 / pad<boss / 锪平非整平 / 无锪平环 / 锥下壁<1.0，接受默认
/ Script: `verify/s5_verify.py`（`check_s5` + `check_s5_guards(upper_mod, shell_mod)`）
- Hypothesis evidence (`verify/s5_hypothesis.py`): 十字筋六边形草图（顶越 +1 入上件，斜边自 (br+rl, by) 到 (x_i, by−gh)，x_i=√(br²−(rt/2)²) 使低端恰落 boss 面）fix 4 点 + h/v + dy → dof=0；
  2 boss + 2×2 slab 并入 S3 上件单实体 valid（+837.194）；斜边长度窗恰 16 边（5.869），chamfer 0.3 valid；盲孔后 boss 底环 2×13.909 = 解析；
  壳体 pad/锪平/锥/通孔后 valid V=9073.622；pad 顶 2×44.540、锪平环 2×4.437、CONE 2 = 解析；boss 附近 both=0、pad_top 贴合。
- Known-bad proof (`verify/s5_known_bad.py`，boss/pad/孔用圆柱、筋用 harness 自建草图): KB0 pass；KB1 boss 短 0.5 → C2/C5；KB2 boss 入 pad 0.5 → C2/C5（both=114）；KB3 无盲孔 → C2/C5；
  KB4 无筋 → C3；KB5 未倒角 → C3；KB6 rib_t 1.6 → C3；KB7 上件未重打 tag → C1；KB8 无 pad → C4/C5；KB9 无沉头 → C4；KB10 无锪平 → C4；KB11 壳孔偏 0.5 → C4/C5；
  KB12 无守卫源 → C6。ALL DISCRIMINATED（≈9.7 min，干涉网格为主）。
  **发现（改 REQUIREMENTS）**: ① 守卫 `boss_x2+br+rib_len ≤ x_a−wall_t−2` 过严且几何理由不成立——壳腔在 y∈[by−wall_t, by] 的端界在 x=x_a（台阶），筋尖到壳料净距 = x_a−(boss_x2+br+rl)=2.5 → 改为 `≤ x_a−2`；
  ② 锪平 Ø = csink_d 时锪平环宽 0（锥口与锪平圆重合，V6 "锪平平台×2" 退化）→ 新增 `spot_d=5.9`（环宽 0.25，r=15 曲面矢高 0.293 < spot_depth 0.3 仍整平）；
  ③ 90° 沉头 csink_depth 与 (csink_d−hole_d)/2 冗余 → 改为派生量 `shell.csink_depth(p)`，不再是 Var。
  新增守卫：两 boss 筋不相碰 `boss_x2−boss_x1 ≥ 2(br+rl)+1`、pad 顶完整 `pad_top ≥ −√((r−wt)²−(pd/2)²)`（兼 pad 底埋入壳壁）、`pad_d ≥ boss_d+1`、锪平整平 `r−√(r²−(sd/2)²) < spot_depth`、`spot_d ≥ csink_d+0.2`。
- **S5 修订（S6 规划时由渲染 + 边长探针发现）**: spot_depth=0.3 时锪平圆柱侧壁在 z 向端点仅高 0.3−0.293=0.007（S5 壳体最短边 0.007，渲染呈毛边）→ `spot_depth=0.4`，
  守卫改为 `spot_depth − 矢高 ≥ 0.1`（侧壁最薄 0.107）；s5_verify C6 新增 "spot wall < 0.1" 拒绝用例，s5_known_bad P 同步 → S5 重跑 ALL PASS / ALL DISCRIMINATED。

### S6
Verifier contract: 同轴走线孔（壳体）+ 倒角（上件 `l_link.build_stage("s6")` / 壳体 `shell.build_stage("s6")`）
/ Criteria（R=fillet_r=1.2, Rs=safe_fillet_r=0.6, cx=((boss_x2+br+rib_len)+(x_b−wall_t))/2=51.75, 孔 x∈[cx±notch_h/2]、z∈±notch_w/2、角 notch_rr）:
C1 上件单实体 valid、tight bbox = S5、V_S5−V = 4 条端盖 rim 圆角 Pappus（截面 R²(1−π/4)、形心距角 R(10−3π)/(12−3π)；外环 r、内环 rp）±0.5%、面数 S5+4、两安装面 tag 各恰 1 且面积 π rp²；
C2 端盖 rim 8 角度 × 内外环 × 两端盖：0.05/0.05 空、0.45/0.45 实；槽底角（y=d_motor/2、x=L−plate_t）空侧点保持空（锐）；剖分接口面 −Y@by / bend CYL / −X@x_b 面积 = S5；
C3 壳体单实体 valid、bbox = S5、rim tag 恰 1 且面积 = S5；+Y@by / bend CYL×2 / +X@x_b / pad×2 / 锪平环×2 / CONE×2 不变；面数 S5+8+16；V_S5−V_孔（数值：圆角矩形 × 壁高 t(z)）−V ∈ (0,20]；
C4 壁中面在圆角矩形内（中心、±x、±z、四角弧内侧）空，外 0.3 实，矩形尖角 (hx0+0.15, ±(hz−0.15)) 实（圆角），端壁 (x_b−wall_t/2) 与 boss 2 锪平环完好；
C5 走线口外环上/下边（环面 torus_pt）0.05 空 / 0.45 实，内环上边 ri+0.05 实（锐）；同轴孔外环 x 边 0.05 空 / 0.45 实，内环实；
C6 守卫拒 fillet_r=thickness/4 / =D−d_motor/2 / =rp、safe_fillet_r=notch_rr、safe_fillet_r+0.5>wall_t、走线口圆角顶 > by−0.05（notch_sill=0.45）、同轴窗 < notch_h+2、外环不可按 y 分离（notch_w 过宽），接受默认
/ Script: `verify/s6_verify.py`（`check_s6(upper, upper_s5, shell, shell_s5, p, tags)` + `check_s6_guards(upper_mod, shell_mod)`）
- Hypothesis evidence (`verify/s6_hypothesis.py`): 端盖 PLANE 选择器 2 面 → boundary edge 恰 4（94.248×2 / 75.398×2）fillet 1.2 valid、dV −104.850 = Pappus、安装面面积不变、bbox 不变；
  同轴孔刀具 = 共享 `rounded_rect_face(w=notch_h, h=notch_w)` extrude +Z → rotate +90° 绕 X → translate (cx, −(r−wt)/2, 0)，cut valid dV −124.247、孔面 8；外环（孔面 edge 且 center.y ≤ −(r−wt/2)）恰 8；
  壳杆 sweep `side_faces_tag` 穿过腔/走线口/pad/锪平/沉头/同轴孔 cut 仍存活（2 面）→ 走线口外环 = 走线口面 `shared_boundary` 皮面 → 恰 8；
  两次 fillet 0.6 valid、各 8 blend，走线口圆角顶 y=7.422 < by−0.05；rim 303.718 / CONE 2 不变；重打 tag 各 1。
- Known-bad proof (`verify/s6_known_bad.py`，孔刀具 box+Y 圆柱并集、边集用 harness 自己的 Python 过滤器（圆长/位置、到环面中心圆距离）；基于模型 S5 两件):
  KB0 pass；KB1 槽底边也倒 → C1/C2；KB2 R1.0 → C1；KB3 只倒外环 → C1/C2；KB4 上件未重打 tag → C1；KB5 无同轴孔 → C3/C4/C5；KB6 孔偏 −3 → C4/C5；KB7 盲孔（差 0.3 未穿皮）→ C3/C5；
  KB8 走线口内环也倒 → C3/C5；KB9 同轴孔外环未倒 → C3/C5；KB10 同轴孔尖角 → C3/C4；KB11 壳 rim 未重打 → C3；KB12 无守卫源 → C6。ALL DISCRIMINATED（≈25 s）。
  **发现**: ① 任何 `fillet_rsolid` 都会丢掉先前的 tag（皮面 tag、上一次 fillet 的 generated_faces_tag）→ 走线口圆角顶须在同轴孔 fillet **之前**量，安装面/rim tag 必须在最后一次 fillet 后重打；
  ② 走线口内环一起倒会漫出到腔内壁并改变 rim 相邻面（KB8 面数 66）→ 只倒外环；③ 锪平外边 R0.6 不可行（锪平侧壁最薄 0.107）→ 保持锐；
  ④ 孔面 edge 中 y>−(r−wt/2) 的 "内环" 为 16 条（含柱面 seam）→ 只选外环，不对内环计数；⑤ 首版 C4 在圆角外侧取 "应空" 点（误判 KB0）→ 改为角弧平分线内侧点。

### S7
Verifier contract: 倒角后切削（上件 `l_link.build_stage("s7")`）: 8 走线窗 + 三叉凹槽 + 3 径向沉头孔
/ Criteria（rp=12, 窗 w×h=10×5 圆角 1.2、相位 45/135°、底边距落座面 cable_w_off=3；星形臂宽 key_w+2·gap=2.7、臂长 key_r_out+gap=11.3、深 gd=2.2、相位 0/120/240；
径向孔 @x=L−plate_t/2=77.5、角 0/120/240（YZ 面自 +Y 量向 +Z）、锪平 ⌀4.2 深 0.25、90° 沉头 ⌀4.0、过孔 ⌀2.2）:
C1 单实体 valid、tight bbox = S6、面数 S6+101、左安装面面积 π rp²、右安装面面积 π rp² − A_star（两 tag 各恰 1）；dV = harness 刀具与 S6 交体积之和 ±0.2%（窗用单侧半棱柱、凹槽/径向孔按连通组），
凹槽部分 = A_star·gd，右窗 = 4×数值窗体积；C2 窗中心/四角弧内侧空、外 0.3 实、窗间壁实、窗底边下 cable_w_off−e 实；
C3 凹槽底恰 1 平面（面积 A_star）、臂中心线/臂端内空、臂外 / 相位 60° 实、槽底 −e 实；C4 径向孔轴线/锪平/锥口空、孔壁实、CONE 恰 2n（seam 劈分）；
C5 S6 端盖 rim 圆角、槽底锐边、剖分接口面积不变；C6 12 条守卫各由对应断言拒绝、默认接受 / Script: `verify/s7_verify.py`（`check_s7(upper, upper_s6, p, tags)` + `check_s7_guards(upper_mod)`）
- Hypothesis evidence (`verify/s7_hypothesis.py`): H1 共享 `rounded_rect_face` extrude ±rod_d → rotate 相位 → translate，两槽 4+4 窗 cut valid dV 1226.831、64→128 面、窗射线全空；
  左窗穿过臂根圆环段，出口半径在 +X 对角窗 y=12.5 处最大 16.05（仍穿透外皮，无残皮）；
  H2 三 box 臂凹槽：dV 194.4216 = A_star·gd（A_star 88.3733），但槽底被劈成 6 个 PLANE（3×28.4056 + 3×1.0522）；
  H2b 9 顶点星形草图（全 fix，dof=0）一次 extrude：槽底恰 1 面 88.3733、128→138 面 → **采用星形草图**（`key_star_face`，S8 凸起复用同一草图）；
  H3 锪平柱 + 锥 + 过孔沿 +Y 建后 rotate 绕 X：valid、CONE 0→6（每锥被 seam 劈 2 面）、+27 面、锪平侧壁最薄 0.1023、锥下孔壁 1.85；H4 重打 tag 1/1、bbox 不变、成品 165 面。
- Known-bad proof (`verify/s7_known_bad.py`，窗 = box+圆柱圆角棱柱、凹槽 = 3D polyline 星形面沿 +X 拉伸、径向孔 = 圆柱+锥，均 harness 自建；基于模型 S6 上件):
  KB0 pass；KB1 窗相位 0 → C2；KB2 右窗自下沉槽底量 → C1/C2；KB3 棱柱过短未穿 → C1/C2；KB4 窗尖角 → C1/C2；KB5 无左窗 → C1/C2；KB6 凹槽相位 60 → C3（仅 C3 能判）；
  KB7 槽深 2.0 → C1/C3；KB8 臂短（r_out 10）→ C1/C2/C3；KB9 径向孔 60/180/300 → C4（仅 C4 能判）；KB10 无锪平 → C1/C4；KB11 无沉头 → C1/C4；KB12 未重打 tag → C1；
  KB13 无守卫源 → C6；KB14 凹槽 3 box（体积相同、槽底 6 面）→ C1/C3。ALL DISCRIMINATED。
  **发现**: ① `intersect_rsolid` 在交集不连通时**静默只返回一块**（贯穿窗棱柱 ∩ S6 得 149.7 而非 299.5），`union_rsolid` 对分离实体直接报错 → harness 体积量测改用单侧半棱柱 + 按连通组求交；
  ② 多 box 并集凹槽劈分槽底（影响 S8 凸起贴合面的单面选择）→ 星形单草图；③ **REQUIREMENTS 修正**: rad_spot_depth 0.15 时锪平侧壁仅 0.002（r=15 上 ⌀4.2 矢高 0.148）→ 0.25，
  新增 `rad_spot_d=4.2`（环宽 0.1）；④ 窗与径向孔不相交由 x 区间守卫（径向孔 x 严格在 (mount_x, L) 内、窗底边距 L ≥ 3）隐含，无需单独守卫。
  新增守卫（12）: cable_w_off∈[3,5]、两槽窗顶 ≤ 槽口−2、0<2rr<min(w,h)、w ≤ 1.6 rp、rad_screw_n ≥ 1、csink>clear、spot_d ≥ csink+0.2、spot_depth−矢高 ≥ 0.1、锥下壁 ≥ 1、
  径向孔 x 区间在 (mount_x, L) 内、key_r_out+gap ≤ rp−0.5、mount_x−groove_d ≥ x_b+wall_t。

### S8
Verifier contract: 转接板 `adapter_plate.build_stage(preset=STAR3 | CENTER4)` + 与 S7 上件同图贴合
/ Criteria（R=rp−plate_gap=11.9, T=5, x0=mount_x=75, rf=0.6, 电机孔 ⌀2.7 PCD16、90° 沉头 ⌀5.1 自背面；STAR3 = 3 孔 @60/180/300 + 中心孔 ⌀6 + 3 段臂 r∈[3.5,11.2]；
CENTER4 = 4 孔 @45+k·90 + 中心短星 r≤4.2 无中心孔；凸起宽 2.5 高 2 相位 0/120/240；径向导孔 ⌀1.6 @x=77.5、0/120/240，内端 t0 按 min_web 截短）:
C1 单实体 valid、tight bbox = [x0−key_h, ±R, L]、V（`precise_volume` eps 1e-9）= πR²T − 2·Pappus + A_key·key_h − n(πhr²T + 锥增量) − 中心孔 − 3×导孔数值积分 ±0.01、面数 39 / 29；
C2 seat / back / key-top tag 面数 1 / 1 / key_faces 且面积解析（back 扣 A_key 与 STAR3 relief 底 πr0²）、CONE 恰 n 面积 n·侧面积、metadata plate_preset = preset；
C3 孔 / 沉头锥半径 ∓0.1 / 孔间实 / 落座面侧无沉头 / 臂实空边界（侧 ±(hw∓0.1)、端 r1∓0.1、臂间、顶 ∓0.05）/ STAR3 hub r0∓0.1 + 中心孔 / CENTER4 中心实 / 导孔空段 + 端实 + 壁 + 错相实 / 两 rim 圆角；
C4 与上件（同 GraphSession）: 裁剪上件（x∈[72,80.5]）∪ 板的重叠体积 |ov| ≤ 0.01；背面贴合（x0±0.05）；凸起顶隙 0.2、侧隙 0.1、STAR3 端隙 0.1、径向隙 0.1 均"两不属"；导孔与套筒过孔同轴；
C5 径向螺丝选型 STAR3 M2×6 / CENTER4 M2×5、电机螺丝头沉入 0.2 ≥ 0.1；C6 13 条守卫各由对应断言文本拒绝、默认接受
/ Script: `verify/s8_verify.py`（`check_s8(plate, preset, p)` + `check_s8_fit(plate, upper, crop, preset, p)` + `check_s8_screws(mod, p)` + `check_s8_guards(mod)`；`harness_plate` 供 known-bad）
- Hypothesis evidence (`verify/s8_hypothesis.py`): H1 纯圆盘 rim 边长窗恰 2 → fillet R0.6 valid、dV 11.4228 = 2×Pappus；H2 星形并入（根部 overshoot 0.5）STAR3 dV 116.6385 = 3×hub_strip×2、顶面 3×19.4397；
  CENTER4 57.5873 = star(2.5,4.2)×2、顶面 1×28.7937；H3 CONE 3 / 4（本处**不被 seam 劈分**，与 S7 径向锥不同）、面积 = n×侧面积；H4 导孔 t0 7.9 / 9.037（深 4.0 / 2.863）、采样无击穿；
  H5 tag 1/1/3 · 1/1/1、metadata 存活、面数 39 / 29；H6 与 S7 上件同图 union 单实体。
- Known-bad proof (`verify/s8_known_bad.py`，板由 harness 自建：圆柱 + 自选 rim fillet + 3D polyline 星形面沿 −X 拉伸 + 圆柱/锥刀具，仅复用源 tagger（失败则保持无 tag）；与 S7 上件同图):
  KB0a/KB0b 两 preset 正确 pass；KB1 沉头在落座面侧 → C2/C3（体积相同）；KB2 key_h = groove_d → C1/C2/C3/C4；KB3 CENTER4 凸起相位 60 → C3/C4（ov 34.2）；KB4 STAR3 用 CENTER4 孔 → C1/C2/C3；
  KB5 CENTER4 加中心孔 → C1/C2/C3；KB6 CENTER4 导孔未截短 → C1/C3；KB7 无 rim 圆角 → C1/C2/C3；KB8 板半径 = rp → C1/C2/C4；KB9 key_w 2.7 → C1/C2/C3/C4；KB10 无 tag → C2；
  KB11 STAR3 无 hub relief → C1/C2/C3；KB12 CENTER4 带 star3 metadata → C2（仅 C2 能判）；KB13 CENTER4 全长臂 → C1/C2/C3；KB14 无守卫源 → C6；KB15 径向螺丝 M2×8 → C5。ALL DISCRIMINATED。
  **发现**: ① `cut_rsolid` 与 `intersect_rsolid` 一样，结果不连通时**静默只保留一块**（星形 − 中心柱 → 3 段分离臂只剩 1 段，V 48.6）→ 凸起先整星并入板体、再从板上切 hub relief（顶面与背面共面）；
  ② `Solid.get_volume()`（默认 GProp）在圆柱−圆柱 BSpline 交线修剪面上每处偏差 ~0.1 mm³（单导孔 8.127 vs 解析 8.029；eps 1e-9 得 8.02895）→ 验证体积一律 `_common.precise_volume`，
  H6 的 0.0215 "重叠" 即此噪声（precise 下 0.000000）；③ STAR3 relief 底在 x0 成独立平面（3–3.5 环被臂侧劈成 6 小面），背面 tag 仍恰 1；
  ④ CENTER4 导孔被截短至深 2.863（到电机孔壁 ≥ min_web）→ 径向螺丝 M2×5（入板 2.15），STAR3 深 4.0 → M2×6；⑤ 臂端角到板背面圆角带仅 0.03（hypot(11.2,1.25)=11.2695 ≤ 11.3，守卫恰好通过）。

### S9
Verifier contract: `assembly.build_l_link_assembly(preset)` 对 STAR3 / CENTER4 各一份（组件 body / shell / plate；body ground；2 条 fixed：`shell_on_split` = body.split_datum↔shell.shell_rim、
`plate_on_mount2` = body.mount2_datum↔plate.plate_back；公开 connector motor_left / motor_right）
/ Criteria（期望帧由 REQUIREMENTS 直接写出，不调用源里的 connector 函数）:
C1 装配结构: assembly_id `l-link-motor-mount-<preset>`、组件恰 {body, shell, plate}、part_id `l-link-body` / `l-link-shell` / `l-link-adapter-<preset>`、grounded = (body,)、约束恰 2、
report 残差全 within_tolerance 且 Δt ≤ 1e-9 mm / Δθ ≤ 1e-9°、三组件 solved placement = identity（原点 / 轴 ±1e-9）；
C2 connector 帧（世界系 = placement ∘ 局部）: split_datum = shell_rim = 原点 (0,back_y,0) z −Y；mount2_datum = plate_back = 原点 (L−plate_t,0,0) z +X、x 轴 (0,cos φ,sin φ)（φ=key_phase）；
motor_left 原点 (0,d_motor/2,0) z +Y、motor_right 原点 (L,0,0) z +X、z 点积 0；两电机原点各落在对应 tag 面（TAG_MOUNT_LEFT / TAG_SEAT，世界系）的面心与平面内；公开 connector 解析到同一帧；
C3 两两干涉（OCP BRepAlgoAPI_Common，世界系 = solved placement 变换后，GProp eps 1e-9；验证侧诊断）: body∩shell、body∩plate、shell∩plate 体积各 ≤ 0.01；shell / plate tight bbox 不相交；
C4 接触面（世界系探针 ±0.05 恰属一件）: 板背面 x=75 环带 → body 侧 / plate 侧各 12 点；剖分平面 y=back_y（x<x_a）→ body / shell；boss 底 y=pad_top → body / shell（pad）；
凸起顶 x=L−plate_t−key_h 与槽底 x=L−plate_t−groove_d 之间"两不属"（隙 0.2）；plate 背面 tag 平面 = body 安装面 2 tag 平面（位置差 ≤ 1e-6、法向相反）、shell rim tag 平面 = body 剖分平面（同）；
C5 部件身份: 三件 body = 同进程独立阶段构建（`l_link.build_stage("s7")` / `shell.build_stage("s6")` / `adapter_plate.build_stage(preset=)`）的 precise V 差 ≤ 1e-6、面数相等；plate metadata plate_preset = preset；
C6 渲染评审: 每 preset 命名视图 iso / 前视（XY，看 −Z）/ 右视（沿 −X）+ 爆炸图 → 自审
/ Script: `verify/s9_verify.py`（`check_s9(solved, preset, p)`；known-bad 以 `assembly.assemble_parts(parts, preset)`（纯函数，@scad.assemble 内部同样调用）组装改动过的 Part）
- Known-bad proof (`verify/s9_known_bad.py`，交付 Part 仅换一个 connector / body，经同一 `assemble_parts` strict 求解):
  KB0a/KB0b 两 preset 正确 pass；KB1 plate_back 原点 x=75.2 → C1/C2/C3/C4（板下沉 0.2，ov 54.10）；KB2 shell_rim z 翻 +Y → C1/C3/C4（壳体绕 X 转 180°，ov 1251.0）；
  KB3 motor_right 放在安装面 2 → C2；KB4 motor_left z −Y → C2；KB5 STAR3 装配装 CENTER4 板 → C1/C4/C5；KB6 plate_back 相位 +60 → C1/C3/C4（ov 34.20）；
  KB7 上件无 S7 切削（无凹槽）→ C3/C4/C5（ov 116.638 = 凸起体积）；KB8 shell_rim y=7.4 → C1/C3/C4（ov 65.96）；KB9 mount2_datum x 轴 +Z → C1/C2/C3/C4（ov 112.87）。ALL DISCRIMINATED。
  **发现**: fixed 约束 = 两 connector 帧完全重合（原点 + 三轴），故 connector 的 x 轴即相位锁：凸起相位由 mount2_datum/plate_back 的 x 轴 = key_phase 方向固定（KB6/KB9 证实错相即干涉）。

### S10
Verifier contract: 参数扫描 + 守卫边界矩阵（整条约束链 = `adapter_plate.assert_params` → shell → l_link）
/ Criteria:
G0 默认接受、BINDING 表覆盖全部数值参数；
G1 每个数值参数单独偏离默认，向两侧各碰到一条守卫（外步 + 二分求边），或列入 FREE 并写理由（D hi、rad_pilot_depth hi 饱和、周期角 / 整数交 G4）；
G2 边外一步的拒绝文本 = BINDING 期望守卫；
G3 ANALYTIC 端（93 个）的界由 verifier 按需求几何独立推导（`_g`，不从源导入）：二分边 = 解析界（|d| ≤ 1e-6），界 ∓1e-6 内侧接受、外侧以 binding 文本拒绝；包含型守卫接受界本身，严格型拒绝；
G4 离散 / 周期域：rad_screw_n ∈ 1..6 恰接受 {1, 3}；key_phase 5° 步长扫 [0,360) 全接受；cable_w_phase 恰接受 |a mod 90 − 45| ≤ 5；
V VARIANTS 6 组多参数合法变体（long_L100 / split_shift / phase / plate_t8 / rod32 / combo，径向螺丝选型手算）在同一图内建上件 / 壳体 / 双板全部阶段，check_s1 … check_s9 全过（s9 = 双 preset 以变体零件装配 + strict 求解）；
E EDGES 6 个参数钉在接受极值（几何最紧 / 相切处），同样 check_s1 … s9 全过（守卫充分，而非只是会触发）
/ Script: `verify/s10_verify.py [guards | sweep | edges | all]`（`s10_variants.run_variant`，sweep/edges 进程池；worker 异常就地转文本，因 SimpleCADError 跨进程不可 unpickle）；
渲染: `verify/render_stage.py s10 <names…>` → `verify/renders/s10_<name>_<preset>.png`
- Known-bad proof: S10 本身是对 S1–S9 verifier 的变体复用；S10 改动了 s3/s4/s6/s7/s8 verifier（守卫 / 探针参数化 / 面数），各自 known-bad 重跑 ALL DISCRIMINATED。

### S11
Verifier contract: `export.py`（capture → `.scadpkg` → 自包导出 STEP + STL；每产品 capture 失败记为 `blocked` 继续）→ `verify/s11_verify.py` 新进程重开（无活体）
/ Criteria: X0 6 个预期产品（l_link_body / l_link_shell / adapter_plate_{star3,center4} / l_link_assembly_{star3,center4}）均导出；
X1 `read_product_package` 通过校验、root = (single_solid | assembly, 构建时 id)；X2 `load_step_rshape` 实体数 = 产品体数、总体积 = 导出时活体参考体积（rel 1e-4）；
X3 二进制 STL 三角数 = 导出报告且 > 0、全部顶点在 STEP bbox + 0.05 内；X4 装配体组件 = (body, shell, plate)、strict 残差 within_tolerance
/ Script: `verify/s11_verify.py`；SDK 发现复现 `verify/s11_fingerprint_repro.py`

## Hypotheses（Role 4 逐阶段补填）

### S1
Hypothesis: 3 实体开放链约束草图（臂/拐角弧/直段，2 tangent + fix + radius + dx/dy）→ `make_wire_from_sketch_rwire(require_fully_constrained=True)` → 圆截面 `sweep_rsolid`
/ Result: s1_hypothesis H1–H5 全过（dof=0、Pappus rel 0、2 caps、tight bbox 精确）/ Adopted: `l_link._l_rod_path` + `_l_rod(p, rod_d)`（rod_d 参数化，S4 内偏移扫掠复用同一路径）。
Evidence（`verify/s1_verify.py` on `l_link.build_stage("s1")`）: C1 volume 72950.282 = Pappus；C2 arm=1 run=1 planes=2；C3 bbox [−15,−15,−15,90.5,20,15]；
C4 guards 拒绝 r_corner=r / r_corner=D / d_motor=2D → **S1 ALL PASS**。

### S2
Hypothesis: 两纯圆柱刀具（overshoot 5）一次 `cut_rsolid`；安装面以 PLANE+法向+中心窗 `.exactly(1)` 选择 → `apply_tag_rselection`
/ Result: s2_hypothesis H1–H3 全过 / Adopted: `_motor_pocket_tools`、`_mount_floor_selector`、`_tag_mount_floors`；新增守卫 thickness∈(0,rod_d)、plate_t≥5、安装面 2 在直段。
Evidence（`verify/s2_verify.py`）: C1 61188.159 = 解析；C2 面积 452.389×2、点积 0；C3 深 10.50/15.50；C4 环 254.469、左槽最小壁 2.13；C5 两 tag 各 1 → **S2 ALL PASS**（S1 回归 ALL PASS）。

### S3
Hypothesis: 5 实体闭合 XY 约束草图 → `make_face_from_sketch_rface` → extrude +Z 并平移一次居中 = 壳区刀具；上件 = S2 − 刀具（之后重打 tag）、壳体 = S1 杆 ∩ 刀具
/ Result: s3_hypothesis H1–H5 全过；known-bad 揭示 tag 不跨 cut 存活 / Adopted: `l_link.split_region_tool`（上件/壳体共用）、`back_y`、`split_xs`、`_reached`；
mount-face-names 块移到最后一次布尔之后；新建 `shell.py`（S1 杆 ∩ 刀具）；新增守卫 back_cut_frac∈[0.5,1)、左槽底 ≥ by+wall_t、x_a>r_corner+2、x_a<x_b、Rs≤by+r、x_b≤fx−wall_t。
Evidence（`verify/s3_verify.py`）: C1 25928.576+35259.583=61188.159；C2 接口面 6×1；C3 弧两侧；C4 壳 [−13.557,−15,−15,60,7.5,15]、上件 bbox=S2；C5 套筒整圆 + tag 各 1；
C6 7592 点 both=0 missing=0；C7 6 条守卫全拒、默认接受 → **S3 ALL PASS**（S1/S2 回归 ALL PASS）。

### S4
Hypothesis: 腔 = 内缩扫掠 ∩ 腔区草图刀具（敞口顶、同心弧端壁）；走线口 = 共享圆角矩形草图 extrude +Z → rotate 90° 绕 Y → translate 一次
/ Result: s4_hypothesis H1–H5 全过 / Adopted: `shell._cavity_region_tool`、`shell._notch_tool`、`l_link.rounded_rect_face`（S7 走线窗复用）、`shell._rim_selector` + `TAG_SHELL_RIM`（最后布尔后打）；
新增 `shell.assert_params`（含上件链）守卫 Rs−wall_t≥1、2·notch_rr<min(w,h)、notch_sill>0、notch_w/2<r−wall_t、走线口贯穿拐角壁。
Evidence（`verify/s4_verify.py`）: C1 V=9052.738 valid、bbox=S3 壳；C2 管壁 / C3 端壁 采样 0 坏点；C4 敞口、rim/bend/drop = 1/2/1、rim tag 1；C5 走线口 5 空 4 实；C6 4 条守卫全拒 → **S4 ALL PASS**（S3 回归 ALL PASS）。

### S5
Hypothesis: boss 柱（纯圆柱，pad_top→by+1）+ 十字筋六边形约束草图（x_i 使低端落 boss 面，Z 向片 rotate 90°）一次 `union_rsolid` → 斜边长度窗 `.exactly(16)` chamfer → 盲孔 cut；
壳体 pad 圆柱（壁中面→pad_top）union → 锪平圆柱 cut → 90° 锥（锥口 overshoot 0.2）+ 通孔 cut；tag 均在最后布尔后重打
/ Result: s5_hypothesis H1–H5 全过；known-bad 揭示 3 处需求修正（见 §S5 contract 发现）/ Adopted: `l_link.pad_top`、`boss_xs`、`_boss_columns`、`_cross_rib_tools`、`_rib_hyp_selector`、`_boss_hole_tools`
（上件 STAGES 加 "s5"，无 s4）；`shell.csink_depth`（派生）、`spot_y`、`_pad_tools`、`_spot_face_tools`、`_csink_hole_tools`；Var 新增 boss_*/rib_*/gusset_*/pad_t（上件，pad_t 两件共用）与 pad_d/shell_hole_d/csink_d/spot_d/spot_depth（壳体）；
守卫 7 条（上件）+ 7 条（壳体）。
Evidence（`verify/s5_verify.py`）: C1 上件 V=26693.029 valid、bbox=S3、tag 1/1；C2 boss 底 2×13.909；C3 筋 32 组采样 0 坏点、倒角面 16；C4 壳 V=9073.622 valid、pad 2×44.540、锪平环 2×4.437、CONE 2、锥下壁 1.350；
C5 both=0、贴合、同轴；C6 11 条守卫全拒、默认接受 → **S5 ALL PASS**（S1–S4 回归 ALL PASS；上件 60 面、壳体 32 面）。

### S6
Hypothesis: 上件 = S5 → 端盖 PLANE 选择器 `.boundary("edge").exactly(4)` 一次 fillet R1.2 → 重打安装面 tag；壳体杆扫掠带 `side_faces_tag`（皮面）→ … S5 → 同轴孔 cut（共享圆角矩形 extrude/rotate X/translate）
→ 走线口外环（口面 `shared_boundary` 皮面 `.exactly(8)`）fillet R0.6 → 同轴孔外环（孔面 edge 按 y 取外侧 `.exactly(8)`）fillet R0.6 → 重打 rim tag
/ Result: s6_hypothesis H1–H5 全过；known-bad 揭示 fillet 丢 tag（见 §S6 contract 发现）/ Adopted: `l_link.FILLET_R`、`_cap_rim_selector`、`_l_rod(skin_tag=)`（上件 STAGES 加 "s6"）；
`shell.SAFE_FILLET_R`、`TAG_SKIN`、`coax_hole_x`、`coax_tool_top`、`notch_blend_rise`、`_coax_hole_tool`、`_notch_outer_selector`、`_coax_outer_selector`；守卫 3 条（上件）+ 7 条（壳体：同轴窗、刀具顶在腔内、刀具顶低于端壁内弧、外环可分离、safe<notch_rr、safe+0.5≤wall_t、走线口圆角顶 ≤ by−0.05）。
Evidence（`verify/s6_verify.py`）: C1 上件 V=26588.179、dV 104.850 = Pappus、60→64 面、floors 452.389×2；C2 rim/槽底/接口 0 坏点；C3 壳 V=8934.480 valid、32→56 面、rim 303.718、fillet_V 10.574；C4/C5 0 坏点；
C6 8 条守卫各由对应断言拒绝（逐条核对报错文本）、默认接受 → **S6 ALL PASS**（S1–S5 回归 ALL PASS；known-bad 以模型重跑 ALL DISCRIMINATED）。
Render review（`verify/renders/s6_upper.png`、`s6_shell.png`、`s6_shell_detail_coax.png`、`s6_shell_detail_notch.png`，自审）: 上件两端盖外环 + 槽口均见圆角过渡线、槽底锐；
壳体走线口 / 同轴孔外环圆角沿圆角矩形连续、内环锐、同轴孔落在 boss 2 与端壁之间、锪平/沉头不受影响；无毛边 / 薄片。

### S7
Hypothesis: 所有 S7 刀具在最后一次 fillet 之后 cut（免 fillet 排除逻辑）：窗 = 共享 `rounded_rect_face` extrude ±rod_d → rotate 相位（左绕 Y / 右绕 X）→ translate；
凹槽 = 9 顶点星形约束草图 `key_star_face`（(u,v)=(−z,y)）extrude +Z → rotate +90° 绕 Y → translate 至 mount_x−gd；径向孔 = 锪平柱 + 90° 锥（锥口 overshoot 0.2）+ 过孔沿 +Y 建 → rotate 绕 X 到各角；最后重打安装面 tag
/ Result: s7_hypothesis H1–H4 全过；H2 三 box 方案因槽底劈 6 面弃用 / Adopted: `radial_x`、`radial_angles`、`key_star_face`（S8 共用）、`_cable_window_tools`、`_key_groove_tool`、`_radial_csink_tools`；
Var 新增 cable_w_*（5）、key_w/key_gap/key_phase/key_r_out、groove_d、rad_*（5）；STAGES 加 "s7"；守卫 12 条。
Evidence（`verify/s7_verify.py`）: C1 V=25115.864 valid、dV 1472.315 vs harness 1472.387（窗 1226.806 [右 598.997 vs 599.017]、凹槽 194.421 = A_star·gd、径向 51.160）、64→165 面、floors 452.389 / 364.016；
C2/C3/C4/C5 0 坏点（槽底 1 面 88.3733、CONE 6、接口面积 = S6）；C6 12 条守卫各由对应断言拒绝、默认接受 → **S7 ALL PASS**（S1–S6 回归 ALL PASS）。
Render review（`verify/renders/s7_upper.png`、`s7_upper_detail_collar.png`、`s7_upper_detail_groove.png`，自审）: 两槽各 4 圆角窗对称分布于 45° 对角、窗间壁完整、窗底边在落座面上方；
套筒 x=77.5 处 +Y 与 ±120° 三处锪平 + 沉头清晰、不与窗相交；安装面 2 槽底三叉星形凹槽（一臂沿 +Y）与三径向孔同相、臂端距槽壁留料、背面（az 180）完好；无毛边 / 薄片。

### S8
Hypothesis: 板 = 纯圆盘（轴 +X）→ rim 边长窗 `.exactly(2)` fillet R0.6（在所有孔 / 凸起之前，守卫保证其余特征不进圆角带）→ 共享 `key_star_face` 星形 extrude +Z → rotate +90° 绕 Y → translate 并入
→ [STAR3] hub relief 柱 cut → 电机过孔 + 90° 锥（自背面）cut → [STAR3] 中心孔 cut → 径向导孔（沿 +Y 建 → rotate 绕 X）cut → 最后打 seat / back / key-top tag + metadata；
盘面拓扑由 `PlatePreset` if 分支（`plate_layout`）决定，Var 只承载标量
/ Result: s8_hypothesis H1–H6 全过；首版"星形先减中心柱"因 cut 只留 1 段臂而弃用 / Adopted: `PlatePreset`、`plate_layout`、`hole_angles`、`pilot_inner_r`、`radial_screw_len`、`_web_to_arms`、
`_plate_disk`、`_rim_edge_selector`、`_key_tool`、`_key_hub_relief_tool`、`_motor_csink_tools`、`_center_bore_tool`、`_radial_pilot_tools`、`_plane_x_selector`、`_tag_plate_faces`；
Var 新增 plate_gap、m2_hole_d/pcd/csink_d/head_dk/center_d、key_h、key_r_in、min_web、rad_pilot_d/depth（11）；守卫 13 条（两 preset 均须可行）。
Evidence（`verify/s8_verify.py`）: STAR3 V=2054.5280 = 解析 2054.5280、39 面、seat 355.699 / back 243.0616 / tops 3×19.4397、CONE 3 = 62.3781；CENTER4 V=2107.1629 vs 2107.1628、29 面、
seat 378.2478 / back 290.6435 / top 28.7937、CONE 4 = 83.1708；两者 bbox [73,±11.9,80]、C3 0 坏点、C4 重叠 0.000000 且间隙点全过；C5 M2×6 / M2×5、头沉入 0.2；C6 13 条守卫全拒、默认接受
→ **S8 ALL PASS**（S7 回归 ALL PASS）。
Render review（`verify/renders/s8_plate_star3.png`、`s8_plate_center4.png`、`s8_fit_star3.png`、`s8_fit_center4.png`，自审）: STAR3 背面三段分离臂（一臂 +Y）绕中心孔、3 沉头在两臂之间、relief 环可见，
落座面 3 过孔 + 中心孔；CENTER4 背面中心短星、4 沉头 @45°、落座面 4 过孔；两者外圆两 rim 圆角连续、径向导孔在 rim 中部 0/120/240；贴合图中板落座于右槽、落座面与槽口齐平方向正确；无毛边 / 薄片。

### S9
Hypothesis: 三件均装配位建模 → placement connector 与 part 同源（`l_link.split_datum_placement / mount2_datum_placement / motor_left_placement`、`adapter_plate.motor_right_placement`），
每件 `@scad.part`（转接板按 preset 由工厂 `_plate_part_builder` 各生成一个定义，id `l-link-adapter-<preset>`）；装配体 = 纯函数 `assemble_parts`（add_component identity ×3 → ground body →
2 fixed → 公开 motor_left / motor_right → strict solve + 残差断言），`@scad.assemble` 边界只包一层（每 preset 一个 id）
/ Result: 首次即 solve 零残差（Δt 8.9e-16 / 0）、三件 placement = identity / Adopted: 上述 connector helper、`build_l_link_part`、`build_shell_part`、`build_adapter_plate_part(preset)` / `PLATE_PART_BUILDERS`、
`assembly.assemble_parts`、`assembly.build_l_link_assembly(preset)`
Evidence（`verify/s9_verify.py`，两 preset 相同）: C1 id / part_id / grounded / 2 约束 / 残差 ≤ 1e-9 / identity；C2 6 帧 + 公开帧 + 两电机原点落各自 tag 面心、z 点积 0；
C3 OCP common 体积 body/shell、body/plate、shell/plate 均 0.000000，shell/plate bbox 不相交；C4 58 探针全对（背面环、剖分面、boss↔pad、凸起顶隙 0.2）、plate/body 面 75.0/75.0、shell/body 7.5/7.5 法向相反；
C5 三件与独立阶段构建 precise V 差 ≤ 1e-6、面数相等、plate_preset 一致 → **S9 ALL PASS**。
Render review（`verify/renders/s9_assembly_<preset>.png` iso / 前视 XY / 右视 / 底面 iso，`s9_exploded_<preset>.png`，自审）: 前视见 "l" 剖分线（水平 → R12 弧 → x=60 竖直）与壳体下沿连续、两端窗口、径向沉头；
右视 STAR3 3 孔 + 中心孔（透见槽底星形）、CENTER4 4 孔 @45° 无中心孔、板与槽口同心；底面见壳体 2 沉头 + 同轴走线孔 + 走线口；爆炸图 boss / 筋 / pad 对位、板凸起面朝凹槽；无错位 / 穿插。
**渲染发现**: `view_up=(0,1,0)` 下 (elev 0, az ±90) 是自 −Y 的俯视而非侧视；前视 XY（相机 +Z）= (90, 0)，右视（相机 +X）= (0, 0)。

### S10
Hypothesis: 约束链已由 S1–S9 逐阶段补全，S10 只需以独立推导的解析界 + 变体全阶段重建证明"守卫必要且充分"
/ Result: 首轮 G3 / E / V 暴露 3 处真实模型缺陷 + 1 处经验域 + 若干 verifier 探针硬编码，全部修复后 ALL PASS / Adopted: 下列修正；
`s10_variants.run_variant`、`render_stage.render_variants`。
Evidence（`verify/s10_verify.py all`，日志 /tmp/s10/{guards,sweep2,edges2}.log）:
G0 默认接受、BINDING 覆盖全参数；G1/G2/G3 110 个边、93 个解析端逐一吻合、6 个 FREE；G4 rad_screw_n → {1,3}、key_phase 全周接受、cable_w_phase → {40,45,50,130,…,320}；
V 6 组变体 check_s1..s9 全过；E cable_w_phase 40 / L 130 / boss_x2 40.5 / split_arc_frac 0.7125 / key_r_out 10.92875 / rad_spot_d 4.23202 全过 → **S10 ALL PASS**；
默认回归 S1–S9 ALL PASS；s3/s4/s6/s7/s8 known-bad 重跑 ALL DISCRIMINATED。
**发现 / 修正**:
① **径向沉头锥带（模型缺陷，E rad_spot_d_hi 暴露 CONE 9）**: 锥口 overshoot 0.2 越出锪平圆柱（sr−cr 仅 0.1）→ 在锪平侧壁上削出一圈锥带，带在 z 向端点贴皮、随 rad_spot_d 断成数片。
  修正 `_radial_csink_tools` overshoot = min(0.2, (sr−cr)/2)；默认上件 S7 面数 +27 → +12（每孔 4 面）、CONE 6 → 3（**不再被 seam 劈分**）、groove 189.075、S7 dV 1466.437、成品 150 面。
② **KEY_TIP_LAND（模型缺陷，E key_r_out_hi 暴露背面 tag 0 命中）**: 旧默认 key_r_out 11.2 臂端角距板背面外圆圆角仅 0.03，微增即割断背面平面环 →
  新守卫 hypot(key_r_out, key_w/2) ≤ rpl − rf − 0.3，**默认 key_r_out 11.2 → 10.9**（凹槽臂长 11.0；STAR3 V 2054.528 → 2050.028、back 245.3116、tops 3×18.6897）。
③ **弧底 ≥ 腔底 + 1（模型缺陷，E L_hi 暴露）**: 旧界 R_s ≤ back_y + r 在切点处剖分竖直面整面消失；且 R_s > back_y + r − wall_t 时腔内端壁内弧穿出腔底 →
  守卫改为 x_b − x_a ≤ back_y + r − wall_t − 1（L 上限 150 → 130，split_end_frac 上限同）。
④ **cable_w_phase 经验域**: 窗朝 +X 会钻入拐角内弯（S7 checks 失败）→ 守卫 |phase mod 90 − 45| ≤ 5（`CABLE_W_PHASE_TOL`），相位 45 族以外不支持。
⑤ **内核发现**: rod_d 32 + back_cut_frac 0.734375（保持 back_y 7.5）时壳体 pad `union_rsolid(clean=True)` 的 UnifySameDomain 写出无效拐角 torus 面（wire imbrication，v 跨度 > 2π）；
  back_cut_frac 0.70 干净 → 变体 rod32 用 0.70；未加守卫（非几何可推导，已记录）。
⑥ **verifier 缺陷**（非模型）: S4 C3 / S6 C4 端壁竖直段探针 y 硬编码（−6/−9、−4/−10）→ 改为腔底与弧底间比例点；`_bend` / 右窗符号 / s5 y 探针随变体几何参数化。
⑦ 单参数域观察: 默认下 rod_d 仅 [29.94, 30]（下界 = KEY_TIP_LAND、上界 = 左槽底壁，thickness / back_cut_frac 固定时）→ 改杆径须同时改 thickness 或 back_cut_frac（rod32 变体示例）；
  默认值落在多个包含型界上（如 rod_d hi、wall_t）是设计意图，G3 已确认包含。
Render review（`verify/renders/s10_{combo,L_hi,rod32,phase}_{star3,center4}.png`，自审）: combo（L90 D24 r_corner16.5）拐角更大、"l" 剖分线随 x_a/x_b 移动且与壳体下沿连续；
L_hi（L130）杆身长、弧底贴近壳底但竖直段仍在；rod32 杆径 / 板径同步放大、右视板与槽口同心；phase（key_phase 30、cable_w_phase 140）凹槽 / 凸起 / 径向孔 / 板孔一起转 30°、窗组偏 5°（140 = 135+5 的镜像组）；四组均无毛边 / 薄片 / 穿插。
（注：§S7 / §S8 contract 与 evidence 中 "CONE 6（seam 劈分）"、"+27 面"、"key_r_out 11.2 / 臂长 11.3"、S7/S8 体积为 S10 修正前数值，当前值见本节 ①②。）

### S11
Hypothesis: 零件 / 装配体 `@scad.part` / `@scad.assemble` 结果直接 `scad.capture`，STEP / STL 只从包导出（export-and-translation.md）
/ Result: **PASS（二次）** —— 首轮 body、双板 PASS，壳体及含壳体的两装配体 `scad.capture` 在包自校验处报
`geometry_mismatch at /geometry_hash: BRep geometry differs`（SDK 缺陷，非模型缺陷）；SDK 修复 (c) 后 6 产品 X0–X4 ALL PASS。
Evidence（`verify/s11_verify.py`）: l_link_body STEP V 25121.742 = 参考、STL 36784 三角、bbox [−15,−15,−15,90.5,20,15]；adapter_plate_star3 V 2049.895、13064 三角；
adapter_plate_center4 V 2107.030、13266 三角（STEP 体积为默认 GProp，与 S8 precise 值差即 §S8 发现 ② 的噪声）；FAIL X0 l_link_shell / l_link_assembly_star3 / l_link_assembly_center4。
**SDK 发现**（`verify/s11_fingerprint_repro.py`）: `geometry_interface_fingerprint` 以 1e-7 量化默认（非自适应）GProp 的体积 / 面积 / 形心；
壳体面 42（走线口底平面 y=0，两条 fillet / torus 交线 BSpline 边界）默认积分面积 7.7988451 vs eps 1e-9 真值 7.7997813（误差 ~1e-3），
ASCII BRep（15 位有效数字）写读一次使其变为 7.7988429（Δ 2.2e-6 = 22 量子）→ 活体与解码体指纹不同；解码体为不动点（rt == rt2）。
进程内把 `_mass` 换成 eps 1e-9 自适应 GProp 后 fresh == decoded（P3）。可选修复（SDK 侧，未改动，交用户决定）: (a) `_mass` 用 eps 自适应 GProp（更准，但改变所有含 BSpline 形体的既有哈希）；
(b) 零件定义 / 拓扑快照改从解码后的 BRep 计算（对已稳定形体哈希不变）；(c) BRep 负载以 17 位 / 二进制写出使往返逐位一致。
**已采用 (c)**：`artifacts/brep.py::write_brep_bytes` 改 BinTools V4 二进制（无网格），double 逐位保存 → 解码体 == 活体，指纹必然一致；
写→读→写字节不动点（191085 B 两次一致）；`read_brep_shape` 按前导识别，旧 ASCII 负载仍可读。
二次 Evidence: l_link_shell STEP V 8934.479（参考 8934.480）、24932 三角、bbox [−13.56,−15,−15,60,7.5,15]；
l_link_assembly_star3 V 36106.116、3 solids、74780 三角、X4 components [body, shell, plate] residuals_ok；
l_link_assembly_center4 V 36163.251、3 solids、74982 三角、X4 同上；body / 双板数值与首轮一致。
Render review（`out/render_assembly_{star3,center4}.png`、`out/render_parts.png`，活体渲染，自审）: 交付态装配与 S9 一致（剖分线、窗、径向沉头、同轴走线孔、STAR3 / CENTER4 盘面）；
爆炸图壳体 boss / 筋 / pad 对位、双板凸起面朝凹槽；无错位 / 穿插。
