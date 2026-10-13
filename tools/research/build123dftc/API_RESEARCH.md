# build123d 0.13 API 与测试集调研

本调研针对工作区 `.venv` 中实际安装的 build123d 0.13.0，以及上层 `tests/manifest.json` 固定的 `v0.13.0`、提交 `38effd343e1508964673faf59300a5cc68fbedc1`。2026 年 10 月 7 日已联网核查对应版本的官方文档。清单是测试范围和实现检查表，不能当作已通过转换的声明。

## 完整公开入口清单

`api_coverage.json` 从实际安装包生成，包含以下范围：

| 范围 | 数量 | 含义 |
| --- | ---: | --- |
| 包 `__all__` 导出 | 203 | 官方顶层公开入口 |
| 公开成员定义 | 540 | 按定义所属类去重，含可达继承方法、属性与建模运算符 |
| 类接口 | 138 | 导出类，加上 Shape、几何维度 mixin、Builder、BaseObjectMeta |
| 工作区模型 | 50 | manifest 中全部模型，逐项记录调用位置统计 |
| 模型使用的顶层调用 | 50 种 | 已排除 `__main__` 导出代码和恒为 False 的文档生成分支 |
| 顶层调用位置 | 454 | 源码静态位置数量，循环次数和运行时内部调用未展开 |

顶层入口分类：32 个枚举，15 个常量或类型别名，3 个 builder，4 个位置阵列上下文，27 个曲线对象入口、15 个草图对象入口、11 个实体对象入口（均包含 Base 类），6 个图纸对象入口，23 个建模操作，12 个几何类入口，20 个直接拓扑入口，5 个装配关节，9 个导出入口，6 个导入入口，以及 15 个其他工具入口。

成员分类：40 个 `make_*` 等工厂、68 个直接特征方法、18 个变换方法、41 个代数运算符定义、4 个上下文生命周期方法、122 个属性，以及 247 个查询或工具方法。分类采用方法名和所属模块，不能替代逐方法的行为测试。底层 OCP/Python 标准类型的成员和下划线内部实现不算公开 API；专门列入了建模运算符。

重新生成：

```bash
.venv/bin/python simplecadapi/tools/research/build123dftc/research/inspect_api.py \
  --manifest tests/manifest.json \
  --output simplecadapi/tools/research/build123dftc/api_coverage.json
```

清单内每条入口有签名、定义文件与行号，类接口指向去重后的成员定义。`conversion_status: unverified` 表示尚未通过该接口的转换验证。后续覆盖报告应区分“识别入口”“真正生成 SimpleCAD 特征”“几何验证通过”，不要把成功执行源脚本等同于转换成功。

生成器也接受 `--validation-report` 和 `--traces-dir`。指定严格验收报告后，`verified_sampled_usage` 仅表示列出的模型中执行过该入口且模型验收通过。矩阵保留模型名单与报告 SHA256；其他参数、模式和未执行分支仍未验证。方法证据使用 trace 的实际 `source`，不会仅凭同名方法就把整个继承接口标为通过。最终验收报告更新后需重新生成矩阵。

## 捕获结构与可行的扩展方案

builder 与 algebra 是建模方式，Direct API 是两者共用的拓扑层；顶层入口捕获和底层特征捕获可以互补。[官方 Direct API 说明](https://build123d.readthedocs.io/en/v0.13.0/direct_api_reference.html)

当前实现选择 Direct API 层记录实体构造图，并在实体特征的输入边界转录草图轮廓。这覆盖两种建模方式，不需要改变 builder 的 Python frame。下文第一层是未来扩展原始对象/草图操作记录的方案，不是当前已实现的声明。`project / offset / make_hull` 等草图变化目前进入求解后的精确轮廓；不会逐项保留原草图操作。非平面 Face/Shell 曲面工厂、Vertex 终点放样以及清单中其他未验证 API 仍需单独检查，未支持构造必须显式报告。

### 第一层：可读的原建模操作

安装源码中 `build_common.BaseObjectMeta.__call__` 是全部内置 `BaseObject` 子类的统一入口。它能保留 `Box`、`Circle`、`Spline`、`Hole` 等原参数，也能接收自定义继承类；外层调用期间，内部建模需要防止被重复计入。23 个公开 operations 应全部登记。记录原参数以后，应展开 locations、默认参数以及隐式 pending faces/edges。

### 第二层：Direct API 特征与几何

工厂需要覆盖以下定义；方法会被继承，不能只包装 `Solid` 一种类：

- `Edge.make_bezier / make_circle / make_constrained_arcs / make_constrained_lines / make_ellipse / make_parabola / make_hyperbola / make_helix / make_line / make_mid_way / make_spline / make_bspline / make_spline_approx / make_tangent_arc / make_three_point_arc`。
- `Wire.make_circle / make_convex_hull / make_ellipse / make_polygon / make_rect`。
- `Face.make_bezier_surface / make_gordon_surface / make_rect / make_surface / make_surface_from_array_of_points / make_surface_from_curves / make_surface_patch / make_holes`。
- `Shell.make_loft`。
- `Solid.make_box / make_cone / make_cylinder / make_loft / make_sphere / make_torus / make_wedge`。
- `Compound.make_text / make_triad`。
- `Shape / Mixin1D / Mixin2D / Mixin3D / Edge / Wire / Face / Shell / Solid / Compound` 各自声明的 `extrude`；其中部分重载返回不同维度，不能假定都是 Solid。
- 3D 的 `extrude_taper / extrude_until / extrude_linear_with_rotation / revolve / sweep / sweep_multi / thicken / draft / fillet / chamfer / hollow / offset_3d / dprism`。
- 2D/1D 的 `offset / offset_2d / fillet_2d / chamfer_2d / trim* / project* / split* / close / stitch / combine / wrap*`。

对于没有 SimpleCAD 同名原语的曲线构造（如受约束圆弧、Airfoil、BlendCurve），可把求解后的单条曲线分解为解析参数或精确 BSpline 定义，再以 SimpleCAD 曲线原语重建。需保留 poles、degree、weights、knots、multiplicities、periodic，以及区间/方向。这个方法保留草图和后续特征，而不是把最终实体导入当作转换。

### 第三层：组合、位置与查询

布尔定义分布在 `Shape`、`Compound` 与 `Mixin1D`。1D 的加法可能得到 Wire/Curve，不能按 3D union 发射。`Shape` 的 `fuse / cut / intersect` 是 builder 和 algebra 实际共用的接口，应按几何维度分派。

`Location.__mul__` 对 Shape 实际调用 `other.moved(self)`，`Plane.__mul__` 也进入位置变换。因此包装 `Shape.moved` 后已经能捕获大多数 algebra placement 和 builder 发布，不必再重复包装 `*`。`move / locate / location.setter` 是原位变更；`moved / located` 返回副本。原位变更应建立新节点，保留变更前的输入节点。`translate / rotate / scale / mirror / transformed / transform_shape / transform_geometry` 也需覆盖。

查询 API 大多数不用发射新的 FTC 操作，但查询结果必须用于源脚本继续执行。边/面选择器的结果应关联已有特征，再记录指纹或索引；不能把选中边的 repr 当作可重放参数。曲线的 `@ / % / ^` 分别参与求值和位置计算，记录最终 Vector/Location 参数即可。枚举、单位、字体和颜色也应有稳定的序列化。

## 0.13 builder 语义的两个关键陷阱

所有 builder 先在自身 XY 局部坐标中构造。`output_placements` 只在输出或退出后统一应用。对象构造时使用的 `Locations` 属于局部位置；builder 发布时另有外层 `publication_locations`。两种位置不能重复应用，尤其是嵌套 BuildPart、BuildSketch、BuildLine 和多个 face placement。[官方 builder 位置说明](https://build123d.readthedocs.io/en/v0.13.0/key_concepts_builder.html)

本地源码 `Builder.__enter__` 用 Python frame 判断当前 builder 与父 builder 是否同一作用域。直接加 `__enter__` 或 `__init__` 包装函数会改变 frame，可能把嵌套 builder 误判为无父级。优先捕获 `_add_to_context`、`_PublicationService.place/publish`；如必须包装 enter/init，要保持原同作用域判定的含义，并测试函数内返回私有草图这种有意隔离的情况。

`Builder._add_to_context` 中拿到的 shapes 是 builder 的局部坐标，不能称为全局坐标。此处同时维护累计几何、pending faces/edges 和 Select.LAST/NEW 的变化历史。对截面依赖引用、用于扫掠的独立路径、多个离散实体，需要保留输入依赖图。

## 50 个模型真正考验的能力

最常出现的静态调用：BuildSketch 57，BuildPart 55，extrude 40，Circle 29，Rectangle 25，Locations 23，Box/Line 各 18，BuildLine 16，fillet 15，RegularPolygon 14，GridLocations 11，Plane 10。完整逐模型统计见 JSON。

以下模型需要独立回归，避免简单盒子通过造成覆盖错觉：

| 模型 | 关键行为 |
| --- | --- |
| 09、10、11、18、29、45、46、47 | 边/面选择、3D 圆角与倒角、修改后的选择指纹 |
| 12、30、40、46、47 | 样条、Bezier、端点切向量、非直线轮廓及扫掠 |
| 13、41、49 | 普通孔、沉孔、锥孔、负向深度、自动贯穿深度、多位置 |
| 14、39、40、46、50 | pending 路径/截面、扫掠参数、曲线起点坐标系 |
| 16、17、20、21、22、24、27、37、38、43 | 不同 workplane、嵌套位置、旋转、偏移与 builder 发布 |
| 19、31、32、33、42、48 | 循环/函数生成阵列，以及源查询决定下一操作参数 |
| 23、29、44、46、47 | 旋转、放样、壁厚偏置、开口选择、多截面 |
| 34 | Text 的字体形状与字内孔，不能只重建外轮廓 |
| 36 | `extrude(until=Until.*)`，限界对象与方向 |
| 45 | section、面内孔与比例缩放 |
| 49 | 四个彼此独立的 BuildPart 输出组合为 Compound |
| 50 | 完全 algebra 模型：Helix、`path ^ 0`、位置相乘、显式 sweep 参数 |

源码中被禁用的 SVG 文档导出和 `__main__` STEP 输出不属于建模转换测试，但导入/导出公开入口仍列在 API 清单。清单中的矩阵、关节、图纸类和未被这 50 个模型使用的几何操作，应通过额外小型行为用例逐项验证；50 个模型不等于全部 API 覆盖。

## SimpleCAD 对应关系与几何验证

现有目标原语已提供：线/圆/椭圆/三点圆弧/角度圆弧/精确样条/插值样条/螺旋、wire/face 构造、草图 2D 布尔、3D 原语、3D 布尔、拉伸/旋转/放样/扫掠、圆角/倒角/抽壳，以及曲面构造。可优先复用 `operators/geometry.py`、`features.py`、`boolean.py`、`transform.py` 和 cqftc 的选择指纹与重放模式。

每个测试应同时检查操作结构与几何：FTC 内必须存在实际构造特征和输入依赖，执行生成脚本时不依赖 build123d；体积、包围盒、实体数量和有效性应该与源模型一致。只有体积相同无法证明孔位置和姿态正确，建议再比较差集体积或对称差集，并在拓扑变化时用几何指纹选择。基准来源是执行源脚本所得结果或 manifest 的 STEP，不能把待检 FTC 的结果本身作为基准。

验收工具已实现独立进程与超时隔离，缺少指标、源执行失败、空 BODIES、无效实体、转换元数据中的 unsupported/unknown 都会拒绝。包围盒比较六个世界坐标而非仅比较尺寸。体积与 STEP 差集使用 `VolumePropertiesGK_s(..., Eps=1e-9, OnlyClosed=True, IsUseSpan=True)`；有理 BSpline 使用默认积分或普通自适应积分可能产生明显误差，所以源与目标必须用同一定义。

模型 28 揭示了内核差异：OCP 7.9 对实际形状与基准 STEP 的共同内部点判为 IN，却把 Common 计算为空、双向 Cut 留下全部体积。标准 ShapeFix 和微小 fuzzy 未解决。实际形状重新导出 STEP 后，独立 OCP 8.0.1.1 求得 Common 等于完整体积、双向 Cut 都为空。可选 `--reference-python` 因此让 FTC 在 SimpleCAD 环境中构建，同时在指定独立内核进程中对 STEP 做差集。实际 STEP 的读回体积、包围盒、有效性与实体数量也必须与 FTC 真实 BODIES 一致，验收门槛不变，报告记录两个内核与积分方法。

面积计算在独立的几何深拷贝上先按 C1 连续性切分积分区间，再用明确 `Eps` keyword 的自适应积分；不修改实际 FTC 或 STEP。半径 1、高度 1 的精确有理 BSpline 圆柱有面积 `4π`、体积 `π` 的独立数学测试。OCP 7.9 的测量区间切分在该例有约 `7.7e-9` 相对误差，数学测试精度为 `1e-8`，整模型验收门槛保持原值。

参考 STEP 的临时实际导出使用 trace `source_metadata.export_options` 中声明的参数曲线与精度模式；没有声明时用标准 `True / AVERAGE`。差集布尔在首次 Build 前统一使用输入实际 BRep 顶点/边容差与内核 `Precision.Confusion` 的最大值，记录该值，不逐级尝试容差。差集必须有效并通过原体积门槛。模型 46 的当前记录表明即使匹配 `False / GREATEST` 并使用该固定规则，跨内核差集仍可能无效；这种情况会报告 `reference_error`，不会将基础指标通过冒充严格 STEP 匹配通过。

验收 CLI 有任何 rejected/partial 或没有可验收案例时返回退出码 1，所有案例 accepted 才返回 0；NaN、Inf 与非正 timeout 会作为参数错误拒绝，报告仍保存每例拒绝原因。

确实不能转换的入口应报出明确 API 名、源位置与原因。允许用户显式选择近似曲线时，应报告近似误差并保持后续特征可修改。最终 BRep/STEP 导入只能作为明确标记的外部几何来源，不能用它把未覆盖操作伪装成成功 FTC 转换。

## 官方核查来源

- [Objects](https://build123d.readthedocs.io/en/v0.13.0/objects.html)
- [Operations](https://build123d.readthedocs.io/en/v0.13.0/operations.html)
- [Builder concepts](https://build123d.readthedocs.io/en/v0.13.0/key_concepts_builder.html)
- [Algebra concepts](https://build123d.readthedocs.io/en/v0.13.0/key_concepts_algebra.html)
- [Direct API reference](https://build123d.readthedocs.io/en/v0.13.0/direct_api_reference.html)
- [固定测试集上游提交](https://github.com/gumyr/build123d/tree/38effd343e1508964673faf59300a5cc68fbedc1)
