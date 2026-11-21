# BLDC 与标准件性能验收（Windows x64）

分支 `perf/geometry-throughput`，参考 `origin/dev@389d4306`。主报告数据由 `python tools/perf/report.py` 从 `results/ab-*.json` 计算。研究仓库 `D:/project/plasticity-learning/kernel/` 保存 OCCT 的 C++ 源码、安装脚本和二进制哈希；本机原内核 `C:/occt`，SDK 实测内核 `C:/OCCT-modified/static`。

## 对照条件

* **Intel Core Ultra 7 251HX**，18 个逻辑处理器，CPython 3.10.22、MinGW GCC 15.2、Release。基线是干净 dev SDK 与本机原版静态 OCCT；候选是新 wheel 与修改版静态 OCCT。结果文件带原生模块 SHA-256。计时是墙钟时间，未使用 profiler。机器同时用于开发和测试；毫秒级小差别不能据此排序。
* 顺序：候选、基线、基线、候选，每批新 Python 进程。每个工厂预热一次，然后 7 组连续创建新对象，取组中位数，再对两轮取中位数。包含公开的齿轮、齿条、内齿圈、摆线盘、轴承、链轮、螺栓、螺母工厂；参数及每组次数见 `throughput.py`。这是具体参数下的计时，不涵盖整个 SDK 的每个操作或所有构型。
* BLDC 每轮用新临时目录，只复制例子的 `.py` 输入，不复制 notebook 缓存；计时从运行 notebook 开始，到带校验的产品包写出结束。29 个零件定义、29 个顶层组件、51 个约束，根 notebook 15 个单元全部执行。独立保存冷构建所有零件二进制 BREP 的 SHA-256；`dev-blobs.json` 与 `final-brep.json` 对应的 **29/29 项字节完全相同**，包括拓扑、几何表示及存储容差。另对全部接口几何哈希、容差 profile 逐一比对。

## BLDC（两轮中位数）

| 环节 | dev 秒 | 优化版秒 | 速度比 |
|---|---:|---:|---:|
| notebook 建模、装配、生成定义 | 84.866 | 74.760 | 1.135× |
| 写包、读回与校验 | 22.795 | 11.175 | 2.040× |
| 总计 | **107.661** | **85.935** | **1.253×** |

一次干净 BLDC 节省 **21.73 秒（20.2%）**。单次总耗时：基线 107.34 / 107.98 秒，候选 87.33 / 84.54 秒。计时以同组的端到端值为准。

## 哪些操作得到收益

交错样本中，通孔切削 `5.155 → 4.650 ms`，装饰螺纹螺母 `6.300 → 5.667 ms`，直齿条 `2.297 → 2.141 ms`，直锥齿轮 `53.876 → 50.973 ms`。12 齿人字齿轮 `2164 → 2138 ms`，差异小。普通轴承、内齿圈和链轮等在这批数据中没有稳定的加速。保留包括负收益在内的全部 19 行；执行 `report.py` 查看。第一轮候选与测试有重叠，尤其人字齿条的两轮中位数相差很大；不要把它当成确定的回退幅度。

单独验证布尔清理改动时，四轮交错的单进程中位数：M8 装饰螺母 −13.0%，通孔 −8.6%，双槽分件 −11.7%。验证了建模与回放的 BREP、带顺序的面/边及拓扑快照。曾尝试让 COMMON 和 CUT 共用一次求交：链轮约 `139.9 → 106.0 ms`，但半径 200 的两柱仅重叠 0.00004 时，顶点容差由约 `1.000018e−7` 变成 `1.129074e−7`，因此没有合入。

## 实施与复现

1. 草图端点按实体 id 建索引求连通分量，输出仍按原实体顺序；追踪历史改为只读访问，跳过无目标的拓扑种类。
2. 指纹从同一次 OCCT 积分读取质量与质心；快照遍历中仅在同一计算上下文内复用定向、定位、容差均相同的实体测量。保留实际重读 BREP 的校验，以及规范 JSON 的严格错误路径。
3. 布尔清理仅在 OCCT `IsEqual`（同一 TShape、位置和方向）时跳过与自身的重复比较；实际变化的结果仍检查实体数与有效性。保留请求的历史。
4. 修复 Windows 多线程渲染缓冲区生命周期及测试发现的平台差异；给零宽容差区间使用已求得的名义值。全量测试不通过时不把单例通过算作验收。

另做了 19 项工厂的[分配器对照](allocator-mingw.md)。模块级替换分配器得到一些轻量操作上的收益，但同 ABI 扩展可以共享 pybind11 注册表，跨模块所有权没有隔离；未将其加入发布配置。

```powershell
$env:SCAD_OCCT_PREFIX='C:/OCCT-modified/static'
$env:CMAKE_ARGS='-DOpenCASCADE_DIR=C:/OCCT-modified/static/lib/cmake/opencascade -DSCAD_BUILD_TESTS=ON'
$env:SKBUILD_BUILD_DIR='out/static-build'
uv sync --frozen --extra verify --extra gmsh --extra whucad
$env:PYTHONUTF8='1'
$env:PATH="$((Resolve-Path .venv/Scripts).Path);$env:PATH"
& .venv/Scripts/python.exe tools/perf/throughput.py bldc out/perf/my-bldc.json
& .venv/Scripts/python.exe tools/perf/throughput.py operators out/perf/my-operators.json
& .venv/Scripts/python.exe tools/perf/report.py
ctest --test-dir out/static-build --output-on-failure
$env:SCAD_GOLDEN_STRICT='1'
& .venv/Scripts/python.exe -m pytest src/cpp/tests/python -q
& .venv/Scripts/python.exe -m pytest test tests -q
```

`C:/OCCT-modified` 另有动态库。新补面 / Y 圆角由显式 C++ 入口调用；性能分支保留原有操作的几何策略。Windows wheel 使用静态子前缀，运行时只依赖 Python 与系统 DLL。

本机已构建包：`out/perf/wheel/simplecadapi-2.3.0.post1-cp310-cp310-win_amd64.whl`。包含 Windows 长路径缓存修复的交付包 SHA-256 为 `01d7f34865086173fb02a5b8997d6a35629d20c84fc13d446b54a5a634d19db0`，`_native.pyd` 为 `b4a542cd0b978db5302d4e2dbc2eeb801cefb007f9f3b5b6588ffa188caa6b20`。计时批次的前一版 `.pyd` 为 `368b5391d7ba392df5161a755a298bc201911a969a860e79f402d26793a8ecde`；两个 PE 的 `.text`（`b4363bcf6c55b59e3412634ead7b100368314799c5a64db7035df34dc2b27598`）、`.data`、`.rdata`、导入表和重定位节均逐字节一致。

## 测试结果

静态 wheel 默认 `pytest test tests` 为 **2762 passed、126 skipped、0 failed**。`SCAD_GOLDEN_STRICT=1` 的绑定对照为 **558 passed、1 skipped、0 failed**；C++ Release CTest 为 **14/14**。额外把本机 `D:/Application/FreeCAD/bin` 加入 PATH，整个 FreeCAD 翻译测试为 **107 passed、0 skipped**。跳过数按各自运行记录列示（例如外部工具、参考解释器或单独启用的慢测试）。JUnit 汇总及文件摘要见 [verification.json](results/verification.json)。

重打交付 wheel 后，在同一次全套 `pytest test tests` 中同时启用 `SCA_EDITOR_E2E=1`、`SIMPLECADAPI_RUN_SLOW_SCENE_EXAMPLES=1` 和 FreeCAD，结果为 **2830 passed、58 skipped、0 failed**。其中包含真实编辑器启动、预览、局部重算、中断恢复，以及液压缸、两级行星减速器、BLDC 三个大型装配。
