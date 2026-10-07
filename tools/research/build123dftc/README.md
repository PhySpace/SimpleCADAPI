# build123d → FTC 转换工具

把真实执行的 build123d 模型转换成本仓库现行 FTC Python：显式草图、实体
特征、布尔和 QL 修改选择。组织方式沿用 `tools/research/cadqueryftc`，转换
与验收分开。支持 Builder、代数写法及已接入的底层实体 API。

```text
trusted model.py → build123d_trace.py → trace.json
trace.json → build123d_to_ftc.py → ftc.py + meta.json + sketches.json
ftc.py + trace.json [+ reference STEP] → build123d_validate.py → validate.json
trace.json → build123d_profile.py → profile.json
```

捕获执行模型的 Python；只对可信源文件运行。模型的 `__main__` 分支不会运行，
可在顶层将最终形状绑定为 `result`。捕获和验收分别在隔离子进程执行，设置
超时，一例失败仍处理后续文件。

## 环境

本次实测为 Python 3.12、build123d 0.13.0 / OCP 8.0.1.1，以及
SimpleCADAPI 2.2.0b1 / OCP 7.9.3.1。两个内核的绑定不能混装在同一环境：

```bash
# 在 SimpleCADAPI 仓库根目录运行。环境放在相邻工作区。
uv venv ../.venv --python 3.12
uv pip install --python ../.venv/bin/python 'build123d==0.13.0'
uv venv ../.venv-sca --python 3.12
uv pip install --python ../.venv-sca/bin/python -e . 'cadquery-ocp==7.9.3.1' pytest
```

已有环境无需重建。翻译阶段是纯 Python，不导入 build123d 或 CAD 内核；启用
约束恢复时才加载现有 CQ 的求解器。

## 单模型

```bash
../.venv/bin/python tools/research/build123dftc/build123d_trace.py \
  --input ../tests/models/01_rectangular_plate.py \
  --out tools/research/build123dftc/out/traces

../.venv-sca/bin/python tools/research/build123dftc/build123d_to_ftc.py \
  --trace tools/research/build123dftc/out/traces/01_rectangular_plate.trace.json \
  --out tools/research/build123dftc/out/ftc

../.venv-sca/bin/python tools/research/build123dftc/build123d_validate.py \
  --ftc-dir tools/research/build123dftc/out/ftc \
  --traces-dir tools/research/build123dftc/out/traces \
  --report tools/research/build123dftc/out/validate.json
```

`--constraints on` 从实际草图恢复推断约束，复用 `cqftc.constraints`。只有生产
求解器确认坐标复现才插入约束；约束 ID 标记推断出处。椭圆、样条及耗时超限
的草图在 `constraint_recovery` 中明确记录状态，其精确几何仍保留。

## 工作区 50 个模型

```bash
../.venv/bin/python tools/research/build123dftc/build123d_trace.py \
  --manifest ../tests/manifest.json \
  --out tools/research/build123dftc/out/traces --timeout 180

../.venv-sca/bin/python tools/research/build123dftc/build123d_to_ftc.py \
  --traces-dir tools/research/build123dftc/out/traces \
  --out tools/research/build123dftc/out/ftc

../.venv-sca/bin/python tools/research/build123dftc/build123d_validate.py \
  --ftc-dir tools/research/build123dftc/out/ftc \
  --traces-dir tools/research/build123dftc/out/traces \
  --reference-step-dir ../tests/step --reference-python ../.venv/bin/python \
  --report tools/research/build123dftc/out/validate.json --timeout 180

../.venv-sca/bin/python tools/research/build123dftc/build123d_profile.py \
  --traces-dir tools/research/build123dftc/out/traces \
  --report tools/research/build123dftc/out/profile.json
```

也可用 `--inputs-dir` 处理目录中的 `.py` 文件，或用 `--input` 指定一个模型。
每个模型产生 `.trace.json`、执行日志、`.ftc.py`、`.meta.json` 和
`.sketches.json`。批量验收报告保留所有模型，缺少转换结果也计入失败。

## 验收依据

- 实际执行 FTC，检查非空实体、内核有效性、体积、表面积和实体数量。
- 比较世界坐标中的六个包围盒边界；同尺寸但位置错误会失败。
- 指定参考 STEP 时，要求两个方向几何差集的总体积通过检查。
- `--reference-python` 让参考几何对账在指定内核执行，FTC 仍在
  SimpleCADAPI 环境构建。报告记录两个内核版本，并检查 STEP 导出往返的
  体积、包围盒、有效性和实体数。
- 体积使用按样条节点区间计算的 Gauss–Kronrod 积分。普通固定阶积分对有理
  样条有明显误差，还会在某些非均匀缩放后的裁剪曲面上崩溃。

面积只在独立副本上切开不连续的曲面参数区间，再做自适应积分；原始模型和
拓扑保持不变。参考导出沿用 manifest 声明的参数曲线与精度选项，布尔对账
采用输入已有的内核容差，报告保留这些设置。

阈值为体积、面积和包围盒相对误差 `1e-3`，另有绝对误差保护；STEP 双向
差集体积相对误差 `1e-3`。源执行失败、缺指标、未知操作、翻译不完整和空实体
都不会判为通过。验收通过是给定输入在这些阈值下的结果。`metrics_quality`
单独报告基础几何检查；要求 STEP 对账时，任何参考计算失败仍会使
`quality` 为拒绝，且 CLI 返回非零。工作区实测结果见 [BENCHMARK.md](BENCHMARK.md)。

模型 28 的重合球面在 OCP 7.9 中出现错误的空交集；相同几何在 OCP 8 的
严格双向差集为零。因此上述工作区命令使用独立的 OCP 8 参考环境。

## 转换结构和覆盖

`b3ftc/tracer.py` 在真实底层实体构造、布尔、修改和变换边界捕获操作图。
所有已执行的草图对象与查询仍由 build123d 计算，在实体特征的输入处转录
实际轮廓。JSON 保存参数、世界坐标、精确曲线控制数据和拓扑指纹，不保存
最终实体 BRep。`profiles.py`、`emit.py`、`replay.py` 分别负责轮廓、格式和
实体数据流；外部验收位于 `validation.py` 及独立 worker。

当前支持盒、圆柱、圆锥、球、完整圆环及部分原语；拉伸、带拔模角拉伸、
限界拉伸、扭转拉伸、旋转、放样、单/多截面扫掠；布尔、圆角、倒角、拔模、
双向实体偏移与抽壳、平面分割、刚体与一般仿射变换、多实体组合。
草图支持直线、圆弧、圆、椭圆、精确有理 B 样条与闭合/周期样条；曲线型
文字及三维路径使用实际曲线控制数据。多实体输出为完整 `@scad.assemble`。

生成代码使用现行 FTC 块头、几何档标注、keyword 实参、QL 谓词和基数。
数字来源于实际调用，不虚构参数名。动态追踪只描述执行到的路径；输出不会
保留未执行的分支，也不承诺恢复源草图的约束或全部表达式。

**API 清单不等于全部 API 转换已通过验证。** `api_coverage.json` 和
`API_RESEARCH.md` 梳理了 203 个顶层导出、540 个去重公开成员和 138 个类。
查询、布局和多数草图 API 通过实际求值再转录轮廓覆盖；非平面曲面构造、
原生内核直接包装等未接入的实体构造、部分圆环截面、特殊扫掠模式、复杂孔
拓扑变化等仍有明确边界。未知节点会阻断依赖它的后续特征，并写入 meta，
不会导入最终模型作为替代。完整清单可重生：

```bash
../.venv/bin/python tools/research/build123dftc/research/inspect_api.py --help
```

## 回归测试

`test/build123d_traces` 保留真实捕获的轮廓、修改、镜像、文字和螺旋扫掠
fixture，并带出处。普通 FTC 测试不依赖 build123d；执行捕获测试在其专用
环境运行。

```bash
../.venv/bin/python -m pytest test/test_build123d_trace.py test/test_build123d_unknown_api.py -q
../.venv-sca/bin/python -m pytest \
  test/test_build123d_cli.py test/test_build123d_translation_output.py \
  test/test_build123d_validation.py test/test_deformation_features.py \
  test/test_section_features.py test/test_limited_extrusion.py \
  test/test_rational_volume_precision.py test/test_sketch_closed_bspline.py -q
```
