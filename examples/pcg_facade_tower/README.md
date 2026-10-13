# pcg_facade_tower

PCG 单元式幕墙塔楼：同一份参数化代码，任意平面轮廓（RECT / CHAMFER / L_SHAPE）、层数与退台，
自动生成**可加工**的外立面——板型 Part 只有一种身份， placement 才是数量（3,697 个实例落在
22–43 个类型上，量化误差有硬上界）。设计策略全部写在代码里：分格规则、竖挺波场按 K 量化、
窗墙比按朝向有序抖动到目标值、角件按转角+高度归型；不可行的参数直接 `LayoutError`，不静默降级。

## Run

```bash
# 完整导出（包 + AP242 STEP + 板型清单 CSV + 主渲染），可带平面类型与层数
../../.venv/bin/python export.py [rect|chamfer|l_shape] [n_floors]

# 验证门（几何 / 布局 / 有效性 / 装配 / 导出回读），s1 最快，s4-s8 较慢
../../.venv/bin/python verify/s1_verify.py
../../.venv/bin/python verify/s6_verify.py            # 参数化扫描（K 量化 / 规模 / 平面）
../../.venv/bin/python verify/s6_verify.py --no-geometry
```

## 模块

- `layout.py` — 纯数据布局引擎：平面 → 退台 → 逐边分格 → 板型清单（所有程序化规则只在这里）。
- `panels.py` / `corners.py` / `slabs.py` — 按 type id 的 Part 工厂（同参数即同一身份）。
- `floor.py` / `tower.py` — 带 子装配（每 band 建一次，按标高平移放置）+ 塔楼装配。
- `export.py` — scadpkg 闭包 + XCAF AP242 STEP（每个 definition 只写一次，occurrence 为定位引用）
  + 板型清单 CSV + 主渲染。
- `verify/` — s1 体量 / s2 板型 / s3 角件·楼板·雨棚 / s4 band 装配 / s5 塔楼 / s6 扫描 /
  s7 重建计时 / s8 导出回读；`s*_known_bad.py` 证明每道门在故意做错的构件上会失败。

## 产物（out/，git 忽略）

`facade_tower.scadpkg`、`facade_tower.step`、`facade_tower_panels.csv`、
`rationalization.png`、`scale_sweep.json`、`incremental.json`、`verify/renders/*.png`。

## Known limitations

- **L_SHAPE 全塔验证未闭合**：反射角（270°，转角 -90°）的角件轮廓为填充内凹缺口沿法向伸出
  440 mm（> frame_d 150），在塔楼装配的 V5 包络检查（角件沿边法向 ≤ frame_d，为凸角所写）下
  不成立——S6 的平面几何扫描因此只含 RECT / CHAMFER，L_SHAPE 目前仅做布局层验证
  （`facade_sweep` / s1 / s3 的 m90 角件局部框架检查）。`SDK_DEFECTS.md` D9 记录了该开放问题，
  欢迎贡献修复。

设计笔记：`REQUIREMENTS.md`（需求与验收门表）、`BUILD_PLAN.md`（布局引擎的构造顺序）、
`SDK_DEFECTS.md`（把例子当压力测试记下的 SDK 设计问题；缓存时代的历史条目见文首时点说明）。
