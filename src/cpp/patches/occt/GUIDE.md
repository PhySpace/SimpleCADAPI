# 如何系统地修改 OCCT 内核

本文是 SimpleCADAPI 对 OpenCASCADE（OCCT）做"魔改"的工作规范：文件放在哪里、几何特例怎样做成策略分支、怎样开放给 SDK、怎样验证和发布。规范来自 `fillet-robustness-4` 补丁集（Y 形过渡圆角、收尖圆角、图补面），各项决策的理由见 `design-docs/y-patch-and-graph-patch.md`。

## 1. 原则

- **几何特例的判断放在内核里。** 不在 Python 里判断（太慢），也不在 SDK 的 C++ 业务层判断（与某一个内核耦合，以后换内核时要全部重写）。SDK 只转发一个开关。
- **补丁要小，新能力放进 overlay。** 补丁只用来改 OCCT 原有代码：加一个开关、一个调用点、一处修复。算法本体写成 overlay 里的新类，和 OCCT 原有源码分开，便于升级时重放，也便于将来单独提交给上游。
- **策略关闭时，结果不能有任何变化。** 新策略要么由调用方显式打开，要么只在"检测到特定几何情形、并且原算法失败"时才介入。没有命中的输入，必须走原来的代码路径，结果逐位相同。
- **每条策略都有验收关口。** 结果必须通过有效性检查（`BRepCheck_Analyzer`）和自干涉检查（`BOPAlgo_CheckerSI` 5 级），修改历史也必须正确；任何一项不过，就退回原算法。绝不能静默返回坏几何。

## 2. 文件放在哪里

| 位置 | 内容 |
| --- | --- |
| `src/cpp/patches/occt/000N-<主题>.patch` | 对 OCCT 原有文件的统一 diff，按编号顺序应用 |
| `src/cpp/patches/occt/manifest.json` | 基线版本（tag、commit、源码包 sha256）、补丁集名称、补丁列表，以及每个被改文件补丁前后的 sha256 |
| `src/cpp/patches/occt/overlay/<包名>_<类名>.{hxx,cxx}` | 新类的源码。安装时按文件名中第一个 `_` 之前的部分，放进 OCCT 的 `src/<包名>/` 目录，并登记到该包的 `FILES` 里 |
| `src/cpp/patches/occt/tests/` | 内核级检查工具（独立的 CMake 工程）：`cases`（Y/收尖案例族）、`graphpatch`、`yfillet`、`check`、`inspect`、`shellfillet`、`sidetail`、`wires` |
| `src/cpp/patches/occt/README.md` | 补丁集的说明：每个补丁改了什么、为什么 |
| `src/cpp/tools/occt_patches.py` | 校验哈希、精确应用补丁（不做模糊匹配，重复应用无害）、安装 overlay；`recipe()` 计算整套补丁的指纹 |
| `src/cpp/tools/build_occt.py` | 从源码构建静态 OCCT，安装到指定前缀，并在 `share/simplecadapi/occt-recipe.sha256` 写下指纹 |
| `src/cpp/cmake/ScadOcct.cmake` | SDK 链接哪些工具包 |
| `.github/workflows/ci.yml`、`release.yml` | CI 和发布都用 `build_occt.py` 从这套补丁编译内核，缓存键包含 `src/cpp/patches/occt/**`，改了补丁就会自动重编 |

overlay 用到新的工具包依赖时，在 `occt_patches.install_overlay()` 里追加到对应工具包的 `EXTERNLIB`（参考已有的 `TKFillet` 追加 `TKPrim` 的写法）。

## 3. 策略分支的写法

一个策略由四部分组成。以 Y 形过渡为例（`overlay/BRepFilletAPI_YPatch*`）：

1. **识别（Detect）**：一个纯函数，输入形状和用户的选择，输出带证据的结构体，例如交汇顶点、凹边和凸边、三个支承面、夹角。识别只依赖拓扑和少量几何量，开销要小，而且要尽量沿用 OCCT 自己的判断（例如凹凸性用 `ChFi3d::DefineConnectType`），不要另写一套。
2. **构造（Perform）**：尽量让 OCCT 的标准算法完成它能完成的部分，内核只补上交汇处的那一小块几何。Y 形的做法是：先切掉交汇楔形，在开壳上调用标准圆角，再补两张过渡曲面并缝合。这样远端收尾、其他边都由原算法负责，新代码的范围就小。
3. **验收（gate）**：`BRepCheck_Analyzer`、`BOPAlgo_CheckerSI` 5 级、缝合后没有自由边、连续性实测（接缝两侧法向夹角）。任何一项失败都返回 false。
4. **历史（history）**：用 `BRepTools_History` 记录每个输入子形状的 Modified / Generated / Removed，经过各个阶段时逐个组合，不要依赖 `Merge`（见第 6 节）。

接入 OCCT 原有入口的方式（补丁 `0004`）：

- **显式开关**：`BRepFilletAPI_MakeFillet::SetYPatch(bool)`，打开时优先走策略。
- **默认兜底**：开关关闭时，先跑标准算法；只有识别命中、并且标准结果失败、无效或自交时，才改用策略结果。识别没有命中的输入只多一次拓扑扫描，结果不变。
- **结果报告**：`NbYPatches()`、`YPatchJunction(i)`（含实测的接缝夹角）、`YPatchFallback()`（区分"显式请求"和"自动兜底"）。
- **历史转发**：`Generated` / `Modified` / `IsDeleted` 在走策略路径时从策略的历史作答，调用方的历史跟踪和标签不需要任何特殊处理。

多个策略的顺序要写死在入口里，不能依赖代码的先后顺序隐式决定。例如默认路径是"标准 → 收尖 → Y"，`SetYPatch(true)` 表示直接走 Y。

## 4. 开放给 SDK

- **编译期探测**：用 `#if __has_include(<BRepFilletAPI_YPatch.hxx>)` 判断内核是否带有该策略。SDK 必须能对着原版 OCCT 编译；在不带补丁的内核上请求策略时，抛出 `ValueError` 并写明需要哪个补丁集，不能静默忽略。
- **参数形式**：用明确命名的布尔参数，例如 `strategy_auto_y_patch: bool`、`strategy_graph_patch: bool`，默认 `False`。
- **记录与回放**：只有参数为 `True` 时才写进操作图，这样标准路径的旧记录保持不变。回放有两处：`src/simplecadapi/recording/serializer.py` 和 C++ 的 `executors.cpp`。
- **能力查询**：`simplecadapi._cpp._kernel_capabilities()` 返回当前内核带有哪些策略。
- **文档**：在 `src/simplecadapi/_glue/docstrings.json` 写说明；SDK 编译后运行 `tools/auto_docs_gen.py` 重新生成 API 文档；更新 `CHANGELOG.md`。
- **前置条件在 SDK 里先检查**：例如图补面要求每条边都属于自己的支承面。这样报错信息能说清楚是哪一条不满足，而不是内核笼统地返回 false。

## 5. 工作流程

所有中间产物都放在仓库之外，例如 `D:/occt-kernel/`。

1. **开发循环（不重编内核前缀）**：用 `tests/` 这个 CMake 工程链接已安装的前缀，打开 `-DYPATCH_DEV=ON`，把仓库里的 overlay 源码直接编进工具，覆盖前缀里的旧版本。改了补丁里的 `MakeFillet` 时，再加 `-DYPATCH_MAKEFILLET=<补丁后 MakeFillet 所在目录>`。几秒钟就能完成一次编译测试。
2. **重新生成补丁**：
   - 原始文件放在 `a/src/<包>/`，修改后的放在 `b/src/<包>/`。
   - 每个文件写一行 `diff --git`，再用 `diff -u --label a/src/... --label b/src/...` 生成。标签里不能带时间戳，否则 `occt_patches` 解析出的文件名会不对。
   - 更新 `manifest.json` 里该文件的 before/after 哈希。
3. **重建内核前缀（增量）**：
   - 源码树里被补丁改过的文件，要先恢复成原始版本。因为补丁后的哈希变了，旧版本会被 `apply()` 拒绝。
   - 调用 `occt_patches.install_overlay(<源码树>)`，然后在构建目录里执行 `cmake --build . --target install`。只有被改动的工具包会重编。
   - 用 `occt_patches.recipe()` 的输出更新前缀里的 `occt-recipe.sha256`。
   - 新内核装到新的前缀目录（例如 `C:/OCCT-modified/static-ypatch`），对照用的旧前缀保留不动。
4. **重建 SDK**：
   - 用独立的构建目录（例如 `out/ypatch-build`），配置时指定 `-DSCAD_OCCT_PREFIX=<前缀>` 和 `-DOpenCASCADE_DIR=<前缀>/lib/cmake/opencascade`。
   - 编译出的 `.pyd` 会生成在 `src/simplecadapi/_cpp/`。把 `.venv` 里正在使用的模块先改名，再把新模块复制过去；已加载的 DLL 不能被覆盖，但可以改名。
5. **测试**：
   - 内核：`cases.exe` 跑完整案例族，要求输出 `failures 0`，含严格历史检查。
   - SDK：`ctest` 全部通过；`pytest src/cpp/tests/python` 和 `pytest test tests` 分两次运行，放在同一次运行里会因为同名测试模块冲突而无法收集。
   - 连续性：用 `tools/render/zebra.py` 出斑马纹图并逐张查看。
   - 参照结果：用桌面自动化驱动 Plasticity 生成同一案例的结果，脚本在 `out/plasticity-gt/tools/`，对比偏差和分叉点位置。
6. **提交**：一次决策一个提交，提交说明按决策记录的格式写（DECISION / PROBLEM / WHY / REJECTED / EVIDENCE / NOT DONE），先写进文件再用 `git commit -F`。

## 6. 已经踩过的坑

- **换行符**：仓库按字节原样存储（`.gitattributes` 中 `* -text`）。Windows 上 Python 的 `write_text` 会写出 CRLF，必须用 `write_bytes` 或 `newline='\n'`，提交前用 `file` 命令检查。
- **`BRepFilletAPI_MakeFillet::IsDeleted` 只对面有意义**：对边和顶点它会返回"已删除"。判断边和顶点是否保留，要看它们是否出现在结果里。
- **`BRepBuilderAPI_Sewing::IsModified/Modified` 只认整体加入的形状**：查询其中子形状的修改，要用 `IsModifiedSubShape/ModifiedSubShape`，否则支承面会被误判为删除。
- **`BRepTools_History::Merge` 会丢映射**：在第二段历史里，由第一段的修改结果生成的形状不会被带回原始形状。多段历史要逐个子形状显式组合。
- **标准圆角的结果和 `Add` 的顺序有关**：同一组边换个添加顺序，结果可能从"未完成"变成"成功"。测试要固定选边顺序。
- **周期面的参数接缝**：圆柱的接缝顶点落在待倒圆的链上时，标准算法会把一条圆角带建两遍。处理办法是先把接缝挪到远离选中边的位置，再把旧接缝留下的顶点合并掉（只合并边）。
- **悬空的临时列表**：`TopTools_ListOfShape::Iterator it(f())` 里，如果 `f()` 按值返回列表，迭代器会指向已经析构的临时对象。要先把列表存进局部变量。
- **历史检查不能太宽松**：只要求"保留、修改或删除三者之一"，会把错误的"删除"也放过去。必须要求：输入面不能报为删除；交汇边生成的面数达标；每张结果面都能追溯到某个输入面或输入边。
- **实验输出和最终输出分开存放**：实验代码写出的结果文件会覆盖正式结果，后续的对比就会悄悄用错文件。每次正式运行用新的输出目录。
- **同步 overlay 前先确认没人在改**：重建前缀时会把 overlay 目录原样复制进源码树。别人改到一半的文件也会被编进去，这样的构建只能算临时结果。
- **文本 BREP 读回不是修复手段**：把形状写成文本再读回，有时会让本来失败的情形通过。这只说明那里在数值上处于临界状态，应该从几何上修。

## 7. 新策略的验收清单

- [ ] 有识别、构造、验收、历史四部分，策略关闭时结果逐位不变
- [ ] 覆盖整个情形族，不只是一个样件：相切与近相切、不同半径、任意位姿、周期面接缝的各种位置、单个交汇和多个交汇、一个应当被拒绝的反例
- [ ] 通过 `MakeFillet`（或相应的公开入口）做严格历史检查
- [ ] 斑马纹出图，并与 Plasticity 的参照结果对比
- [ ] 补丁重新生成、manifest 更新、增量重建前缀、SDK 重建，C++ 和 Python 测试全部通过
- [ ] SDK 参数、操作图记录与回放、能力查询、文档、CHANGELOG
- [ ] 决策记录（`design-docs/`）和决策式提交说明
