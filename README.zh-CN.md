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
旋转展示由独立的 [sca-web-editor](https://github.com/PhySpace/sca-web-editor) 的 BRep
渲染器渲染（面着色 + 宽棱边），一圈 = 48 个确定性方位角步进，经其 `gif-harness.html` 驱动生成。

</table>

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

- 基于 OCP 的 `Vertex`、`Edge`、`Wire`、`Face` 和 `Solid` 类型。
- 支持基本体、轮廓、拉伸、旋转、放样、扫掠、布尔运算、变换、阵列、圆角、倒角和抽壳等函数式建模操作。
- 通过显式 `GraphSession`、`export_model_json(...)`、`import_model_json(...)` 和 `replay_model_json(...)` 记录并重放操作图。
- 通过 `var(...)`、算术表达式和可序列化表达式图定义参数。
- 使用 QL 选择器定位几何、查询拓扑并稳定选择特征。
- 通过 `apply_tag(shape=..., tag=...)` 和 `list_tags(shape=...)` 管理语义标签。
- 支持 STEP/STL 导出，以及 FreeCAD 脚本和 `.FCStd` 转换。
- 面向 Agent 的 STEP/BREP 逆向能力，提供稳定实体 ID、局部诊断、区域高亮截图和
  可测量的验收门槛。
- 可回放的开放/周期插值 B 样条 Edge 和 Wire，可用于自由轮廓与 Loft 截面。
- 模型即 marimo notebook：一个 cell 一个特征，按 cell 缓存实现增量无头运行
  （`sca run`），并可用 `scad.use` 组合 notebook。

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

```python
from pathlib import Path

import simplecadapi as scad

out = Path("out")

@scad.part(id="bracket")
def build_bracket() -> scad.Solid:
    base = scad.make_box_rsolid(
        width=60.0, height=36.0, depth=8.0, bottom_face_center=(0.0, 0.0, 0.0)
    )
    hole = scad.make_cylinder_rsolid(
        radius=5.0, height=14.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    body = scad.cut_rsolid(base, hole)
    return scad.apply_tag(shape=body, tag="role.demo.bracket")

result = build_bracket()
package_path = out / "bracket.scadpkg"
scad.capture(result, package_path)
print("volume", round(result.part.body.get_volume(), 3))
print("tags", scad.list_tags(shape=result.part.body))
scad.exporter.export_product_package_to_step(package_path, out / "bracket.step")
scad.exporter.export_product_package_to_stl(package_path, out / "bracket.stl")
scad.exporter.export_product_package_to_obj(package_path, out / "bracket.obj")
```


## 可重放操作图

几何流程需要检查、序列化、重放或转换到其他 CAD 环境时，请使用显式
`GraphSession`：

```python
import simplecadapi as scad
from simplecadapi import GraphSession, export_model_json, replay_model_json

with GraphSession(graph_id="drilled_block") as session:
    body = scad.make_box_rsolid(
        width=40.0, height=24.0, depth=10.0,
        bottom_face_center=(0.0, 0.0, 0.0),
    )
    cutter = scad.make_cylinder_rsolid(
        radius=4.0, height=16.0, bottom_face_center=(0.0, 0.0, -3.0)
    )
    drilled = scad.cut_rsolid(body, cutter)
    session.capture_result(value=drilled)
    model_json = export_model_json(session=session)
    recorded_nodes = session.graph.node_count

rebuilt = replay_model_json(json_str=model_json)
print("recorded_nodes", recorded_nodes)
print("replayed_outputs", len(rebuilt))
```

显式 `GraphSession` 在调用导出 API 前只存在于内存。需要持久 CAD/Viewer
交付物时，一个物理单实体零件使用 `@scad.part`，装配使用 `@scad.assemble`，
直接调用 `scad.capture(result, "out/product.scadpkg")`，一次完成捕获和写盘。
`.scadpkg` 包含完整定义闭包、求值场景、特征图、源码快照、拓扑以及渲染/选择资源。
STEP、STL、FCStd 和底层 JSON 仍由显式导出 API 生成。

## Notebook 运行时

模型是一个 [marimo](https://marimo.io) notebook：仓库里的一个普通 `.py`
文件，它始终是唯一的真相来源。PEP 723 头部的 `[tool.simplecadapi]` 表声明
产品 id；每个 cell 放一个特征块，几何会被自动记录。

```python
# /// script
# dependencies = ["simplecadapi"]
#
# [tool.simplecadapi]
# id = "mounting_plate"
# revision = "1.0.0"
# ///
import marimo

app = marimo.App()

with app.setup:
    import simplecadapi as scad


@app.cell
def _():
    width = 30.0
    return (width,)


@app.cell
def _(width):
    # ---- feature: plate (build) ----
    plate = scad.make_box_rsolid(width=width, height=20.0, depth=3.0)
    return (plate,)


@app.cell
def _(plate):
    mounting_plate = scad.make_part_rpart(part_id="mounting_plate", body=plate)
    return (mounting_plate,)
```

同一个运行时既在 marimo 编辑器里运行 notebook，也能无头运行，只需安装
`simplecadapi`。无头运行会缓存每个 cell，重跑时只执行代码、输入文件、本地
模块或子 notebook 发生变化的 cell：

```bash
sca run mounting_plate.py                                  # 输出 JSON 报告
sca run mounting_plate.py --set width=40 --out out/mounting_plate.scadpkg
```

装配 notebook 用 `scad.use("mounting_plate.py", width=40.0)` 引入其他
notebook。`@scad.part` / `@scad.assemble` 保留为可在 cell 中调用的可复用库
构建函数。cell 缓存、组合与产品包导出见
[Notebook 运行时与产品构建工作流](docs/skill/references/docs/guides/notebook-runtime.md)。

## STEP/BREP Agent 逆向

需要生成同步 STEP 视图或局部高亮截图时，请安装渲染依赖：

```bash
pip install "simplecadapi[inverse-engineer]"
```

专用命名空间 `simplecadapi.inverse_engineer.brep` 提供稳定的
Body/Face/Edge/Vertex ID，以及与 Agent 框架无关的工具注册表。逆向时应先读取
有界证据，只有在候选模型足够接近后，才执行成本较高的材料差集或严格拓扑检查：

```python
from simplecadapi.inverse_engineer import brep

schemas = brep.agent_tool_schemas()
summary = brep.call_agent_tool(
    name="get_model_summary",
    arguments={
        "model_path": "target.step",
        "include_parameter_groups": True,
    },
)
face = brep.call_agent_tool(
    name="inspect_entity",
    arguments={"model_path": "target.step", "entity_id": "face:0"},
)

print("tools", len(schemas))
print("faces", summary["face_count"])
print("carrier", face["geometry"]["type"])
```

CLI 使用同一份工具契约：

```bash
simplecad-brep tools
simplecad-brep tool get_model_summary --arguments-file summary-args.json
```

受控测试请使用 [Reconstruction Agent 测试规范](docs/skill/references/docs/guides/reconstruction-agent-test-prompt.md)，
完整证据、建模、回放和验收流程请阅读
[STEP BREP 逆向工程指南](docs/skill/references/workflows/reverse-engineering-studio.md)。

## FreeCAD 转换

外部 CAD 转换只接受经过验证的 `.scadpkg` 产品包：

```python
package_path = artifacts.artifact_paths["product"]
script = scad.translator.freecad_translator.translate_product_package_to_freecad_script(
    package_path
)
scad.translator.freecad_translator.translate_product_package_to_fcstd(
    package_path, "bracket.FCStd"
)
scad.exporter.export_product_package_to_step(package_path, "bracket.step")
scad.exporter.export_product_package_to_stl(package_path, "bracket.stl")
scad.exporter.export_product_package_to_obj(package_path, "bracket.obj")
```

STL 与 OBJ 共用 OpenCASCADE 对求值后 BREP 的直接三角化。两种格式包含相同的
定向三角面，不再需要可选 remeshing 依赖。曲面精度由 `linear_deflection` 和
`angular_deflection_degrees` 控制。

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
  `.scadpkg` 产品包规范：[`design-docs/scadpkg-spec.md`](design-docs/scadpkg-spec.md)

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
