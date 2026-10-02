# 八孔法兰盘（FTC 单零件示例）

最简 Feature Tree Convention 示例：一个零件 notebook `flange_plate.py`，纯几何体素
（geometry tier 第 3 类：形状完全含于基本体素），QL 选边做圆角，外置脚本验证。

## 形状 brief（尺寸为演示假设值，mm）

| 特征 | 参数 | 值 |
| --- | --- | --- |
| 法兰盘 | 外径 × 厚 | Ø100 × 10（z 0..10） |
| 中心凸台 | 外径 × 顶高 | Ø55，顶面 z=30 |
| 中心孔 | 通孔直径 | Ø30 |
| 螺栓孔 | 数量 × 孔径 × 分布圆 | 8 × Ø11 × PCD Ø84.5 |
| 圆角 | 凸台根部 R3；盘外缘上下 R2 | |

基准：原点在盘底中心，+Z 为凸台方向。参数可行性由 notebook 的 guard cell 断言
（G1 中心孔 < 凸台、G2a/G2b 轮辐宽且不与外缘圆角相切、G3 孔不撞根部圆角、
G4 根部圆角 ≤ 凸台高）：轮辐 50 − 42.25 − 5.5 = 2.25 > R2。

## Notebook 结构（一个 FTC block 一个 cell）

```text
params: disc | params: boss and bore | params: bolt pattern   (按一起覆盖的单位分组)
guard: parameter feasibility
flange_disc (build) -> center_boss (add) -> center_bore (subtract)
-> bolt_holes (subtract) -> boss_root_fillet (modify) -> flange_edge_fillets (modify)
flange_plate = scad.Part(...)                                  (产品，id = flange-plate)
```

## 运行

```bash
marimo edit examples/flange_plate/flange_plate.py              # 交互建模（cell 缓存、增量重跑）
sca run examples/flange_plate/flange_plate.py                  # 无头运行，打印 content_hash
uv run python examples/flange_plate/export.py                  # scadpkg + STEP（+ STL，需 gmsh extra）
uv run python examples/flange_plate/export.py --validate       # 新进程回读包
uv run python examples/flange_plate/render_views.py            # 4 张渲染图
uv run python examples/flange_plate/verify.py                  # 外置验收（断言，非目检）
uv run python examples/flange_plate/verify/s2_verify.py        # 孔阵 + 圆角几何验收
uv run python examples/flange_plate/verify/s3_guard_evidence.py  # 改参守卫证据（overrides 逐条触发）
```

产物写入 `examples/flange_plate/out/`。`BUILD_PLAN.md`、`REQUIREMENTS.md`、
`session_transcript.md` 是原建模会话的记录（`demo/` 回放），保留原貌。

## 验证契约（verify.py）

- 单实体、体积与解析值偏差 < 1%（期望值从 notebook 参数读取）；
- QL：Ø11 圆孔圆缘边 16 条（8 孔 × 上下），孔心距轴 = PCD/2；孔壁 8 张；
- 中心孔 Ø30（圆缘周长 2π·15）上下各一条；
- 圆角面 TORUS 恰 3 张（根部 1 + 外缘 2）；
- `.scadpkg` 回读、id/revision 与 notebook 的 content_hash 一致，`.step` 非空。
