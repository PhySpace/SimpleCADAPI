<p align="center">
  <img src="img/repocover.png" alt="SimpleCADAPI 仓库封面">
</p>

# SimpleCADAPI

[English](README.md)

## 它能做什么

四块能力支柱。下面每个 case 都是**真实、可复现的会话**：回放 demo 是单文件离线
HTML，忠实回放完整录制的对话（用户输入、Agent 思考、每一次工具调用与补丁、角色
切换），旁边就是导出的 3D 模型 —— 浏览器直接打开即可。

### 1 · 单零件建模

以可读的[特征树规约](docs/skill/references/discipline/feature-tree-convention.md)
特征块编写参数化零件 —— 带单位的命名参数、验证先行的分阶段建模、改参后仍然命中的
确定性面标签，以及同步产出的 `.scadpkg` / STEP AP242 / STL / 可编辑 FreeCAD 工程。

<table>
<tr>
<th width="18%">案例</th>
<th width="40%">首轮需求（prompt 节选）</th>
<th width="42%">交付模型 · BRep 旋转展示</th>
</tr>
<tr>
<td><b>机械臂 U 形连杆 + 电机安装槽</b><br/>15 轮用户输入 · 601 次工具调用<br/><a href="examples/u_link_motor_mount/demo/index.html">▶ 完整会话回放</a></td>
<td>“构建参数化的机械臂连杆，能适应长度变化、通用安装电机：圆形 profile 沿『下 D → 右 L → 上 D』扫掠成 U 形；两侧圆珠 boolean cut 切出电机安装槽，安装面必须有确定命名、可被查询语言索引；底部圆柱切成半圆柱；然后全局倒角平滑。”</td>
<td><img src="img/capability/ulink_turntable.gif" width="420" alt="u_link 旋转展示"></td>
</tr>
<tr>
<td><b>参数化法兰盘</b><br/>2 轮用户输入 · 66 次工具调用<br/><a href="examples/flange_plate/demo/index.html">▶ 完整会话回放</a></td>
<td>“参数化法兰盘：外径 100、厚 10、凸台 ⌀55 顶高 30、中心孔 ⌀30、6×⌀11 螺栓孔 @PCD 78、根部 R3 / 外缘 R2 圆角；所有尺寸走命名参数；每次圆角前打印选边卡；参数可行性守卫；一个 feature 一个块。”<br/><br/><i>GIF 为终态 8 孔 @PCD 84.5：第 2 轮改参 6→8 孔，PCD 88 被守卫当场拒绝、85 因圆角相切排除。</i></td>
<td><img src="img/capability/flange_turntable.gif" width="420" alt="法兰旋转展示"></td>
</tr>
<tr>
<td><b>筋板 L 形支架（FEM 主模型）</b><br/>2 轮用户输入 · 49 次工具调用<br/><a href="examples/ap242_gmsh_volume_mesh/demo/index.html">▶ 完整会话回放</a></td>
<td>“把已有的 L 形直角连接件 legacy 脚本按 single-part-modeling 工作流正式化：FTC 特征块 + 命名参数重建；与旧版几何等价（体积偏差 &lt; 0.1%）；<code>interface.*</code> FEM 边界标签必须原样保留——下游 Gmsh/CalculiX 按标签选面。”</td>
<td><img src="img/capability/bracket_turntable.gif" width="420" alt="支架旋转展示"></td>
</tr>
</table>

旋转展示由独立的 [sca-web-editor](https://github.com/PhySpace/sca-web-editor) 的 BRep
渲染器渲染（面着色 + 宽棱边），一圈 = 48 个确定性方位角步进，经其 `gif-harness.html` 驱动生成。

### 2 · 装配体建模

嵌套持久装配体 + 显式运动学：齿轮啮合、转动副、轴承接口都是被求解的约束，不是目测
摆放。标准件 —— 渐开线齿轮、带滚珠的轴承子装配、滚子链轮、真实牙型公制紧固件 ——
全部来自 `scad.std.*`，组合成机构后可导出 STEP、可编辑 FreeCAD 工程和面向物理引擎
的 MJCF。

<table>
<tr>
<td width="44%" align="center" valign="top">
<img src="img/capability/bldc_assembly.png" alt="BLDC 关节执行器装配态"><br/>
<b>一体化 BLDC 关节执行器</b> —— 装配态（影棚渲染）<br/>
29 个组件 · 51 条约束全部解算 · 两级行星减速 20:1
</td>
<td width="56%" align="center" valign="top">
<img src="img/capability/bldc_exploded.gif" width="430" alt="BLDC 关节执行器爆炸旋转"><br/>
<b>同一模型</b> —— 爆炸旋转展示：四个模块（电调 · 电机 ·<br/>
双级减速器 · 输出轴）沿轴向分离，模块内同心零件按半径<br/>
分层剥离；相机沿倾斜圆轨道环绕
</td>
</tr>
</table>

复现方式：模型是装配 notebook `integrated_bldc_joint_actuator.py`，用
`scad.use` 组合各零件与子装配 notebook。
`uv run python examples/integrated_bldc_joint_actuator/export_all.py` 导出装配包和
STEP / 可编辑 FCStd / MJCF；`render_showcase.py` 渲染上述视图。

### 3 · 逆向工程

导入 STEP，在浏览器里检查 BREP，直接点选你关注的几何对象——每次点选都会以标签
形式落进标注输入框，旁边配上操作意图（sketch · boolean · fillet · 阵列…）和自由
备注。你的逆向思路挂在具体的面标签上，agent 收到的是被收窄的搜索空间，而不是从
零盲猜——人机协作全程录制、可回放。

<table>
<tr>
<td width="50%" align="center" valign="top">
<img src="img/capability/reverse_studio_mvp.gif" alt="re-studio：点选面、标注意图，agent 重建"><br/>
<b>re-studio MVP</b> —— 在 STEP 目标上点选面、逐条叠加操作意图与备注后提交；
agent 据此对连杆全部 37 个面做分类，从你的上下文出发开始重建 ·
<a href="img/capability/reverse_studio_mvp.mp4">▶ 完整视频</a>
</td>
</tr>
</table>

### 4 · 仿真插件

同一份参数化包直接喂给下游求解器，无需人工返工：AP242 STEP 进 Gmsh 体网格 +
CalculiX 静力 FEM（边界面按保真的 `interface.*` 标签选取，仿真链在模型改版后依然
成立），MJCF 进 MuJoCo 做机构动力学——仿真环境里的虚拟碰撞检查会暴露装配干涉，
驱动修正，直到机构全程干净运动。

<table>
<tr>
<td width="34%" align="center" valign="top" rowspan="2">
<img src="img/capability/ap242_gmsh_bracket_static_von_mises.png" alt="支架 FEM von Mises 云图"><br/>
<b>L 形支架静力 FEM</b> —— CalculiX von Mises 云图<br/>
经 Gmsh OpenCASCADE 内核从 AP242 导出体网格
</td>
<td width="33%" align="center" valign="top">
<img src="img/capability/fourbar_collision_before.gif" alt="MuJoCo 中四连杆相互碰撞贯穿"><br/>
<b>四连杆 + MuJoCo</b> —— 首次装配：连杆在运动中撞在一起，装配不对 ·
<a href="img/capability/fourbar_collision_before.mp4">▶ 完整视频</a>
</td>
</tr>
<tr>
<td width="33%" align="center" valign="top">
<img src="img/capability/fourbar_collision_after.gif" alt="修正后的四连杆在 MuJoCo 中全程干净运动"><br/>
<b>虚拟碰撞修正后</b> —— 同一仿真环境，修正后的装配全程干净运动 ·
<a href="img/capability/fourbar_collision_after.mp4">▶ 完整视频</a>
</td>
</tr>
</table>

---

## 更新日志（2.1.3b1）

> **发布说明：** 预发布（beta）。用于生产前，请验证生成的定义、装配约束和制造几何。

SimpleCADAPI 2.1.3b1 带来插件生态：`sca` 命令行安装第三方 skill+工具仓库
（`sca addon init/add/update/remove/list`）、带平台与 `[compat] sca` 硬门的
严格 `sca-addon.toml` 描述文件，以及面向消费者的 `.scadpkg` 格式规范——把
文档交给 agent 即可写出正确的解析器/导出器。CLI 契约、两种合法集成模式与
tag 通道见[完整中文更新说明](docs/updates/2.1.3b1.zh-CN.md)。2.1.2 的脚本
锚定 part cache（[docs/updates/2.1.2.zh-CN.md](docs/updates/2.1.2.zh-CN.md)）
已由 notebook 运行时及其 cell 缓存取代。

每个示例模型都是 notebook；导出脚本用 `run_notebook` 载入产品，捕获一个
`.scadpkg`，再从同一个产品包转换出 AP242 `.step` 和可编辑 `.FCStd`。
`examples/ap242_gmsh_volume_mesh/` 下的 AP242/Gmsh 示例把每个导出和 FEM 阶段
都做成可直接运行的独立脚本。

---

<div align="center">
  <h2>SimpleCADAPI 论文成果</h2>
  <p>本仓库是以下论文工作的项目产物：</p>
  <p>
    <strong><a href="https://arxiv.org/abs/2608.00891">CADIR: A Cross-Backend Editable Intermediate Representation for Agentic CAD Generation</a></strong>
  </p>
  <p><strong>Computer-Aided Design 2026 接收</strong></p>
</div>

---

SimpleCADAPI 是一个基于 OCP 的 Python CAD SDK，提供清晰的函数式建模操作和可重放的模型图。它在 OpenCascade 几何内核之上提供精简的公共 API，可用于创建实体、应用特征、添加语义标签、查询拓扑、导出制造文件，以及将记录的模型转换为 FreeCAD 工作流。

当前版本：`simplecadapi==2.1.3`。

## 核心能力

- 模型即 [marimo](https://marimo.io) notebook：普通 `.py` 文件就是唯一的真相
  来源，一个 cell 一个特征，按 cell 缓存实现增量无头运行（`sca run`），并可用
  `scad.use` 组合 notebook。
- 由 notebook 生成的规范 `.scadpkg` 产品包，用于交换和发布，不会反过来作为模型
  输入。
- 基于 OCP 的 `Vertex`、`Edge`、`Wire`、`Face` 和 `Solid` 类型。
- 支持基本体、轮廓、拉伸、旋转、放样、扫掠、布尔运算、变换、阵列、圆角、倒角和抽壳等函数式建模操作。
- 通过显式 `GraphSession`、`export_model_json(...)`、`import_model_json(...)` 和 `replay_model_json(...)` 记录并重放操作图。
- 通过 `var(...)`、算术表达式和可序列化表达式图定义参数。
- 使用 QL 选择器定位几何、查询拓扑并稳定选择特征。
- 通过 `apply_tag(shape=..., tag=...)` 和 `list_tags(shape=...)` 管理语义标签。
- 支持 STEP/STL/OBJ 导出、可编辑 FreeCAD 产品包转换，以及带材料和命名元数据
  属性的 AP242 产品结构导出。
- 面向 Agent 的 STEP/BREP 逆向能力，提供稳定实体 ID、局部诊断、区域高亮截图和
  可测量的验收门槛。
- 可回放的开放/周期插值 B 样条 Edge 和 Wire，可用于自由轮廓与 Loft 截面。

## 安装

使用 pip：

```bash
pip install simplecadapi
```

使用 uv：

```bash
uv add simplecadapi
```

从本仓库进行本地开发：

```bash
uv sync --group dev
```

### Agent Skill

pip 安装完成后，为你的 agent harness 安装内置 skill：

```bash
sca skill targets
# 默认位置（~/.agents/skills），或显式指定 ZCode 的 skills 目录：
sca skill install --target zcode --skills-dir ~/.zcode/skills
```

`targets` 列出可用的 harness 目标。`install` 编译内置源码并写入
`<skills-dir>/simplecadapi`；不传 `--skills-dir` 时，沿用既有 addon 配置/
环境解析，默认回退到 `~/.agents/skills`，不要求先执行 `sca init`。wheel
内置的是未编译的 `docs/skill/` 源树和 `skillproj.toml` 资源，编译发生在
安装时机；无需 checkout 本仓库。使用 `uv` 时，上述命令前缀 `uv run`。

`install` 在目标位置已存在时报错。加 `--force` 允许替换，但仅限
`SKILL.md` 声明了同名 skill（`simplecadapi`）的目录；无关目录不会被覆盖。

## 快速开始

模型是一个 [marimo](https://marimo.io) notebook：仓库里的一个普通 `.py` 文件，
它始终是唯一的真相来源。PEP 723 头部的 `[tool.simplecadapi]` 表声明产品；每个
cell 放一个[特征块](docs/skill/references/discipline/feature-tree-convention.md)，
几何会被自动记录——不需要 session 或装饰器样板代码。

```python
# bracket.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "bracket"
# revision = "1.0.0"
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    # ---- params: plate ----
    width = scad.var("width", 60.0, unit="mm")
    return (width,)


@app.cell
def _():
    # ---- params: bore ----
    hole_radius = scad.var("hole_radius", 5.0, unit="mm")
    return (hole_radius,)


@app.cell
def _(width):
    # ---- feature: base-plate (build) ----
    base = scad.make_box_rsolid(
        width=width, height=36.0, depth=8.0, bottom_face_center=(0.0, 0.0, 0.0)
    )
    return (base,)


@app.cell
def _(base, hole_radius):
    # ---- feature: bore-and-slot (subtract) ----
    _bore = scad.make_cylinder_rsolid(
        radius=hole_radius, height=14.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    _slot = scad.make_box_rsolid(
        width=18.0, height=8.0, depth=14.0, bottom_face_center=(14.0, 0.0, -3.0)
    )
    drilled = scad.cut_rsolid(base, _bore, _slot)
    return (drilled,)


@app.cell
def _(drilled):
    # ---- feature: boss (add) ----
    _boss = scad.make_cylinder_rsolid(
        radius=8.0, height=7.0, bottom_face_center=(-18.0, 0.0, 8.0)
    )
    bossed = scad.union_rsolid(drilled, _boss)
    return (bossed,)


@app.cell
def _(bossed):
    # ---- feature: role-tag (annotate) ----
    tagged = scad.apply_tag(shape=bossed, tag="role.demo.bracket")
    return (tagged,)


@app.cell
def _(tagged):
    bracket = scad.Part(part_id="bracket", body=tagged)
    return (bracket,)


if __name__ == "__main__":
    app.run()
```

产品是 id 等于 notebook id 的那个顶层变量。可以在编辑器里交互修改，也可以只装
`simplecadapi` 无头运行：

```bash
marimo edit bracket.py                                    # 响应式编辑器
sca run bracket.py                                        # 运行并输出 JSON 报告
sca run bracket.py --set width=80 --out out/bracket.scadpkg
sca export out/bracket.scadpkg --output-dir out/exports   # AP242 STEP、STL、OBJ
```

## Notebook 运行时

marimo 编辑器、`sca run` 和 Python 里的 `simplecadapi.runtime.run_notebook()`
用的是同一个运行时。无头运行会缓存每个 cell，重跑时只执行代码、输入文件、本地
模块或子 notebook 发生变化的 cell。`--set` 覆盖一个顶层变量（定义它的 cell
不再运行，所以要按“一起变化”的原则把参数分进不同 cell）；报告里每个 cell 的
状态是 `ran`、`cached` 或 `skipped`。

导出和验证脚本是普通 Python 脚本，用 `run_notebook` 载入产品再写出产品包：

```python
from pathlib import Path

import simplecadapi as scad
from simplecadapi.runtime import run_notebook

out = Path("out")
run = run_notebook("bracket.py", overrides={"width": 80.0})
print("volume", round(run.product.body.get_volume(), 3))
print("tags", scad.list_tags(shape=run.product.body))

package = out / "bracket.scadpkg"
scad.capture(run.definition, package)
scad.exporter.export_product_package_to_step(package, out / "bracket.step")
scad.exporter.export_product_package_to_stl(package, out / "bracket.stl")
scad.exporter.export_product_package_to_obj(package, out / "bracket.obj")
```

`.scadpkg` 包含完整定义闭包、求值场景、特征图、源码快照、拓扑以及渲染/选择
资源。它由代码生成，只用于交换和发布，不会反过来作为模型输入。

### 组合 notebook

装配 notebook 用 `scad.use` 引入其他 notebook。相对路径相对于调用方 notebook，
关键字参数覆盖子 notebook 的顶层变量：

```python
@app.cell
def _():
    bracket = scad.use("bracket.py", width=80.0)
    return (bracket,)


@app.cell
def _(bracket):
    rig = scad.make_assembly_rassembly(assembly_id="rig", name="Rig")
    rig = scad.add_component_rassembly(
        assembly=rig, item=bracket, component_id="bracket",
        placement=scad.identity_placement_rplacement(),
    )
    return (rig,)
```

一个 notebook 可以描述一个零件族——只有参数不同的一组零件，比如连杆机构里的
各根连杆。产品写成 `part_id=scad.notebook_id()`，每处使用时给成员起名：
`scad.use("link_bar.py", id="crank", center_distance=40.0)`（或
`sca run link_bar.py --id crank`）。每个成员是一个独立定义，有自己的内容哈希和
cell 缓存。

`@scad.part` / `@scad.assemble` 保留给放在 notebook 旁边普通模块里的可复用库
构建函数；cell 调用它们并取 `.value`。工程目录结构、cell 缓存和下游格式见
[Notebook 运行时与产品构建工作流](docs/skill/references/docs/guides/notebook-runtime.md)。

### 从 `@scad.part` 脚本迁移

2.1.2 的脚本锚定 part cache（构建函数的 `cache=` 选项、`.simplecad` 缓存目录和
增量装配报告）已删除；现在缓存的单位是 cell。

- 每个零件搬进一个 notebook：参数放进 params cell，每个 FTC 块单独一个 cell
  （每个 cell 绑定一个新名字），最后一个 cell 构建 `scad.Part(...)` 或装配体。
- 用调用 `run_notebook` 和 `scad.capture` 的导出脚本，替换那些顺带构建并导出的
  `main.py` 入口。
- 产品之间直接调用构建函数的地方改成 `scad.use(...)`；`@scad.part` 构建函数只
  保留给在 cell 中调用的库零件。
- 把 `__marimo__/`（生成的运行时状态）加入 `.gitignore`。

### 命令行产品导出

不写包装脚本，直接从经过验证的产品包导出标准交付集（AP242 STEP、二进制 STL
和 OBJ）：

```bash
uv run sca export out/bracket.scadpkg --output-dir out/exports
```

其他格式需显式指定。FCStd 需要 `FreeCADCmd`（或显式的 `--freecad-cmd` 路径）；
`--check` 只校验产品包、输出路径和所选格式的前置条件，不写文件。

```bash
uv run sca export out/bracket.scadpkg \
  --format fcstd --format mjcf --output-dir out/exports --check
uv run sca export out/bracket.scadpkg \
  --format fcstd --freecad-cmd /path/to/FreeCADCmd --output-dir out/exports
```

STL 与 OBJ 共用 OpenCASCADE 对求值后 BREP 的直接三角化。两种格式包含相同的
定向三角面，不再需要可选 remeshing 依赖。曲面精度由 `linear_deflection` 和
`angular_deflection_degrees` 控制。

### 可选 CalculiX FEM 流程

AP242/Gmsh 示例还包含可选 CalculiX FEM 流程。Python 侧依赖通过
`uv sync --extra fem` 安装；CalculiX 求解器需要单独安装（macOS：
`brew install costerwi/homebrew-calculix/calculix-ccx`）：

```bash
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py \
  --ccx "$(brew --prefix calculix-ccx)/bin/ccx_2.23"
uv run --extra fem python examples/ap242_gmsh_volume_mesh/visualize_calculix.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/study_mesh_convergence.py \
  --ccx "$(brew --prefix calculix-ccx)/bin/ccx_2.23" \
  --linear-solver "ITERATIVE CHOLESKY" --solver-timeout 2400
```

分析统一使用 `mm`、`N`、`MPa`，输出 CalculiX `.inp`、`.dat`、`.frd`、求解日志、
摘要 JSON、ParaView `.vtu` 和位移放大后的 von Mises 云图 PNG。图中用黄色轮廓
标出载荷 physical group，并用红色 `-Z` 箭头表示载荷方向，不覆盖应力热力图。
收敛研究支持 `--resume`；失败的求解级别单独记录，不会混入数值序列。

仓库中的 `-1000 N` 研究从 `h=3.0 mm` 加密到 `h=0.25 mm`，共 11 级。平台要求
连续三组细化同时满足最大位移变化低于 `5%`、积分点峰值 von Mises 应力变化低于
`10%`。第 N 级验证网格为 `h=0.25 mm`（`0.0331843 mm`、`98.6392 MPa`），
因此生产计算推荐第 N-1 级 `h=0.27 mm`。细网格使用迭代 Cholesky；在
`h=0.375 mm` 同网格上与 SPOOLES 的位移和峰值应力差异均低于 `0.005%`，从而
绕过直接求解器的内存容量限制。

## 可重放操作图

notebook 之外的几何流程需要检查、序列化或重放时，使用显式 `GraphSession`：

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json
from simplecadapi import ql as Q

with GraphSession(graph_id="chamfered_block") as session:
    body = scad.make_box_rsolid(
        width=40.0, height=24.0, depth=10.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    cutter = scad.make_cylinder_rsolid(
        radius=4.0, height=16.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    drilled = scad.cut_rsolid(body, cutter)

    bottom_circle = (
        Q.edges()
        .where(Q.curve_type(kind="circle"))
        .order_by(Q.center_axis(axis="z"))
        .take(1)
        .exactly(1)
    )
    final = scad.chamfer_rsolid(solid=drilled, edges=bottom_circle, distance=0.6)
    session.capture_result(value=final)
    model_json = export_model_json(session=session)
    recorded_nodes = session.graph.node_count

rebuilt = replay_model_json(json_str=model_json)
print("recorded_nodes", recorded_nodes)
print("replayed_outputs", len(rebuilt))
```

显式 `GraphSession` 用于 notebook 之外的检查、序列化和重放；notebook 的每个
cell 已经记录进各自的 session，不要在 cell 里再开一个。它在调用导出 API 前只
存在于内存。持久的 CAD/Viewer 交付物是 notebook 产品捕获出的 `.scadpkg`（见
[Notebook 运行时](#notebook-运行时)）。

## STEP/BREP 检查

需要同步 STEP 视图、区域高亮或截面叠加时，安装可选渲染依赖：

```bash
pip install "simplecadapi[inspect]"
```

检查 API 位于 `simplecadapi.inspect.brep`。它们是诊断工具，不是建模操作：不进入
操作图，在 `GraphSession` 内调用会被拒绝。先导出或拿到几何，再在建模脚本之外
检查。

按当前问题需要的证据选择调用，而不是走固定的逆向流程。先取有界的全局和局部
事实；只有这些事实回答得了当前问题时，才再加截面、组件渲染、边界距离、材料差集
或严格拓扑比较。

```python
from simplecadapi.inspect import brep

summary = brep.inspect_step_rsummary(
    path="target.step",
    include_parameter_groups=True,
)
face = brep.inspect_step_entity_rdescriptor(
    path="target.step",
    entity_id="face:0",
)

print("faces", summary["face_count"])
print("carrier", face["geometry"]["type"])
```

受控测试请使用 [Reconstruction Agent 测试规范](docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md)，
检查原语、建模循环、回放检查和验收门槛请阅读
[STEP BREP 逆向工程指南](docs/skill/references/workflows/reverse-engineering-studio.md)。

## FreeCAD 转换

外部 CAD 转换只接受经过验证的 `.scadpkg` 产品包：

```python
package_path = "out/bracket.scadpkg"
script = scad.translator.freecad_translator.translate_product_package_to_freecad_script(
    package_path
)
scad.translator.freecad_translator.translate_product_package_to_fcstd(
    package_path, "out/bracket.FCStd"
)
```

Part/Assembly 模型写成可编辑的 FreeCAD 装配结构：零件是 `App::Part`，装配是
`Assembly::AssemblyObject`，组件是链接。中性 STEP 与 STL 文件由 exporter 命名
空间输出。

## 示例

每个示例都是一个自包含目录：零件和装配 notebook、它们导入的普通模块、导出与
验证脚本，以及 `examples/<name>/out/` 下的新鲜产物。覆盖零件建模、装配、逆向
工程和 FEM——分类索引见 [`examples/README.md`](examples/README.md)。

```bash
# 零件（快速入门 FTC notebook，附外部验证脚本）
marimo edit examples/flange_plate/flange_plate.py
uv run python examples/flange_plate/verify.py

# 装配（两级行星减速器：零件族 notebook、MJCF 导出）
sca run examples/compact_two_stage_planetary_reducer/compact_two_stage_planetary_reducer.py
uv run python examples/compact_two_stage_planetary_reducer/export_mjcf.py

# FEM（AP242 STEP -> Gmsh 体网格 -> CalculiX 静力）
uv run python examples/ap242_gmsh_volume_mesh/export_step.py
uv run --extra gmsh python examples/ap242_gmsh_volume_mesh/export_fem_mesh.py
uv run --extra fem python examples/ap242_gmsh_volume_mesh/run_calculix.py
```

逆向工程在独立的 [sca-web-editor](https://github.com/PhySpace/sca-web-editor)
的 `Re-mode` 工作区里针对目标 STEP 进行（见 `examples/bowl_connector/` 和
[逆向工程 studio 工作流](docs/skill/references/workflows/reverse-engineering-studio.md)）。

## 文档

- 2.1.3b1 更新说明：[`docs/updates/2.1.3b1.zh-CN.md`](docs/updates/2.1.3b1.zh-CN.md)
- 2.1.2 更新说明：[`docs/updates/2.1.2.zh-CN.md`](docs/updates/2.1.2.zh-CN.md)
- 2.1.1 更新说明：[`docs/updates/2.1.1.zh-CN.md`](docs/updates/2.1.1.zh-CN.md)
- 2.1.0 更新说明：[`docs/updates/2.1.0.zh-CN.md`](docs/updates/2.1.0.zh-CN.md)
- Reconstruction Agent 测试规范：
  [`docs/guides/reconstruction-agent-test-prompt.md`](docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md)
- STEP BREP 逆向工程指南：
  [`docs/guides/step-brep-reverse-engineering.md`](docs/skill/references/workflows/reverse-engineering-studio.md)
- Notebook 运行时与产品构建工作流：
  [`docs/guides/notebook-runtime.md`](docs/skill/references/docs/guides/notebook-runtime.md)
- 公共 API 参考：[`docs/api/`](docs/skill/references/docs/api/)
- 核心类型与建模说明：[`docs/core/`](docs/skill/references/docs/core/)
- 序列化与重放：[`docs/core/serialization/README.md`](docs/skill/references/docs/core/serialization/README.md)
- 操作图 JSON 规范：[`docs/core/operation_graph_json_spec.md`](docs/skill/references/docs/core/operation_graph_json_spec.md)
- 示例索引：[`examples/README.md`](examples/README.md)
- `.scadpkg` 产品包格式：[`docs/skill/references/scadpkg-format.md`](docs/skill/references/scadpkg-format.md)

## 发布 Agent Skill

skill 源树位于 `docs/skill/`，保持 harness 中立。`tools/skillbuild.py` 是
`sca skill` CLI 所用同一编译器的封装，供本仓库维护者构建：按 harness 目标
编译（目标与默认输出目录配置在 `skillproj.toml`；`skills/simplecadapi-*/`
下的输出是可再生的构建产物，不提交入库）。如需 harness 特定文本，用
`<!-- skill:if ... -->` 条件块标记，按目标编译。wheel 本身不包含任何预编译
目标——终端用户用 `sca skill install` 从内置源码自行安装。

在干净的工作区中更新项目版本和文档，然后生成并验证发布产物：

```bash
uv sync --group dev
uv run python tools/auto_docs_gen.py --quiet
uv run python tools/skillbuild.py --target omp
uv run pytest test/test_skill_build.py
tar -C skills -czf skills/simplecadapi.tar.gz simplecadapi-omp
```

这组命令会重新生成 skill 源树内的 API 参考、重新编译 omp 目标，并生成
`skills/simplecadapi.tar.gz`。发布前检查源树和编译产物：

```bash
git diff -- docs/skill
tar -tzf skills/simplecadapi.tar.gz | head
```

发布时只提交 `docs/skill/` 源树；harness 编译产物由发布工作流生成，归档
文件上传到 GitHub Release。通过 pip 安装后，优先使用 `sca skill` 构建和安装。

## 开发

```bash
uv sync --group dev
uv run python -m pytest test tests
python3 -m compileall src/simplecadapi
```

## 许可证

本项目采用 Apache 许可证 2.0 版（Apache-2.0），详见 [`LICENSE`](LICENSE)。

## 社区交流

由于群聊人数过多，无法直接扫码入群。请扫描下方二维码添加杜鹏老师微信，由杜鹏老师邀请加入 CADDesigner 技术交流群：

<p align="center">
  <img src="img/dp个人账号.png.jpg" alt="杜鹏老师个人微信二维码" width="420">
</p>

## Star History

<a href="https://www.star-history.com/?repos=PhySpace%2FSimpleCADAPI&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&theme=dark&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=PhySpace/SimpleCADAPI&type=date&legend=top-left" />
 </picture>
</a>
