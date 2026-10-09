# SDK 设计缺陷记录（pcg_facade_tower 构建过程中发现）

目的：把 PCG 建筑尺度的例子当作压力测试，记下每处「SDK 本身设计上的问题」——症状、触发条件、根因、
当前处置、修复方向——之后据此对症修复。末尾「启发」一节把单条缺陷归纳成可复用的排查规则
（下次在别处先按这些规则找同类问题）。

状态：`已修（未提交）` = 工作区里有补丁 + 回归测试，未 commit；`绕开` = 例子侧规避，SDK 未改；`待修` = 只记录。

规模参照：默认 36 层 CHAMFER 塔 = 26 板型 Part、16 个带子装配（每个 70–250 构件）、塔楼 79 构件 / 20 定义、
共 3697 个外立面件；楼板 36 m × 36 m。

---

## D1 `OperationGraph.is_dag` 递归 DFS → 长操作链 RecursionError

- 状态：已修（未提交）— `src/simplecadapi/topology/model.py`
- 症状：单层装配 `add_component_rassembly` 约 1000 次后抛 `RecursionError`。
- 根因：每次 add 是 feature graph 上的一个节点，链长 = 构件数；`is_dag` 用递归 DFS，深度 = 链长。
- 修复：`_kahn_order()` 迭代 Kahn，`is_dag` / `topological_order` 共用（后者原本还先跑一遍 DFS 再跑 Kahn）。
  顺带把 `queue.pop(0)`（O(N)）换成 `deque.popleft()`。
- 缺：没有「≥ 数千节点链」的回归测试。

## D2 id 去重用 `list.count` → 每次 add O(N²)

- 状态：已修（未提交）— `product/assembly.py`、`product/connector.py`、`product/constraint.py`
- 症状：3000 实例平铺装配 69 s；修后 12.6 s。
- 根因：`Assembly.__post_init__` 每次构造（不可变值，每 add 一次重建）都 `ids.count(id)` 查重 → 单次 O(N²)，整条链 O(N³)。
- 修复：`Counter`。
- 遗留：不可变 Assembly 每 add 整体重建 + 全量校验本身仍是每次 O(N)，整链 O(N²)；
  应提供批量 API（`add_components_rassembly(components=[...])`）或增量校验。

## D3 几何指纹量化整数超出 JSON 安全整数范围

- 状态：已修（未提交）— `artifacts/geometry_interface.py`；回归测试
  `test/test_geometry_summary.py::test_building_scale_part_hashes_and_round_trips_its_state`
- 症状：36 m 楼板 Part 建型后求指纹失败（哈希被 JSON 安全整数检查拒绝）。
- 根因：指纹把体积 / 面积 / 坐标按 1e-7 量化成 int；36e3² × 250 / 1e-7 ≈ 3e18 > 2^53。
  量化步长是**绝对**的，隐含了「零件尺度」假设。
- 修复：`_json_safe` 在哈希前把超界 int 编码为 `"int:<十进制>"`；范围内的值与旧哈希一致（不失效既有缓存）。
- 更好的方向：量化步长相对于包围盒对角线（与 `geometry_summary` 的相对容差一致），根本不产生这种量级。

## D4 RFC 8785 状态文件读回时拒绝大整值 double

- 状态：已修（未提交）— `scene/canonical.py`（同 D3 回归测试）
- 症状：写入 `latest-parts.json` 成功，下次读取时报越界整数。
- 根因：JCS 把 < 1e21 的整值 double（楼板惯量 ≈ 1.18e19）打印成无指数的整数 token
  `11773562012270215000`；`parse_strict_json` 按 Python int 读回 → 超 2^53 被拒 / 重新规范化不一致。
  即「写」和「读」对数字域的约定不对称。
- 修复：`parse_canonical_json` 用 `parse_int=_jcs_int`，超界整数 token 读成 double。

## D5 面 tag 经变换 / 后续布尔后退到 lineage 作用域，默认查询查不到

- 状态：绕开 — 例子把玻璃 tag 放在建型最后一步；渲染高亮用板局部坐标；V4 用「定义体 tag 面积 × 实例数」。
- 症状：`translate` / `rotate` 或其后布尔之后，`ql.tag(...)`（默认 effective）返回空。
- 根因：tag 绑定在具体面上，变换产生新面后只在 lineage 中可追溯；effective 作用域不跟随纯刚体变换。
- 影响：装配展平（`make_compound_from_assembly_rcompound`）后的整楼上无法按 tag 选玻璃面——
  「按语义选面」在装配层失效，而这恰是 PCG 统计（WWR）最需要的。
- 修复方向：纯刚体变换应保持 effective tag（面一一对应，无歧义）；或装配投影时按实例 placement 转发定义体 tag。

## D6 `@scad.part` 的 part_id 必须等于装饰器 id → 参数化族需要工厂写法

- 状态：绕开 — `scad.part(id=type_id, revision=..., project_root=ROOT)(builder)(**kwargs)`，每个板型动态造一个装饰器。
- 根因：Part 身份 = 装饰器 id，而 PCG 的「类型」是运行时由参数算出来的（`solid-w1600-h3600`），
  装饰器在 import 时就要定 id。
- 修复方向：官方支持 `part_family` / `id=lambda **kw: ...`，或文档化工厂写法作为推荐模式。

## D7 装配 geometry_summary 递归内嵌子摘要 + 每次 assemble 全量读写状态文件 → warm 比 cold 慢

- 状态：待修（本分支 commit 8b218d4 引入的摘要设计）
- 症状：塔楼 cold 构建 31 s，**warm 49 s**（无任何改动的重建反而更慢）。
- 证据：`.simplecad/state/latest-assemblies.json` 4.7 MB，其中 facade-tower 一条 3.6 MB
  （`public_interface.geometry_summary.instances` 2.6 MB、`dependency_interfaces` 1.0 MB）。
  profiler（~114 s 含开销）：`load_latest_assembly_state` 57 s / 34 次，`canonical_json_bytes` 60 s，
  `update_latest_assembly_state` 29 s，part cache 读取 22 s，`validate_assembly_definition_graph` 17 s。
- 根因（两层叠加）：
  1. `assembly_geometry_summary`（`artifacts/geometry_summary.py`，调用处 `build/assembly_builder.py`
     `_assembly_geometry_summary`）把每个子定义的**完整摘要**按实例复制进父摘要：塔楼 ~40 个 floor 实例 ×
     每个带摘要 50–115 KB。同一定义被实例化 N 次就存 N 份，嵌套再乘一层。
  2. 每次 `assemble` 都把整个状态文件解析 + JCS 规范化校验一遍，写回时再全量序列化 → 代价 ∝ 调用次数 × 全项目状态大小，
     与本次改动无关。
- 修复方向：
  - 摘要里实例只存 `(instance_id, definition_id, placement)`，子摘要按 `definition_id` 去重存一份
    （或只存子摘要 hash，等价判定时按引用取）；`geometry_summaries_equivalent` 相应按引用比较。
  - 状态存储按条目分文件（`state/assemblies/<id>.json`）或进程内缓存 + 只写脏条目。
- 需要的回归测试：N 个同定义实例的父摘要大小不随 N 线性增长；warm 重建耗时 ≤ cold。
- S5 复测（z 区间窗口版 gate）：塔楼 warm 构建 47.2 s、再 warm 45.8 s（零改动），而 3697 件的 S5 全部几何检查才 169 s ——
  一次「什么都没变」的重建占到完整验证的 ~1/4。S6 扫描 6 座塔 / S7 六步各付一次这个代价。

## D8 增量基线是「每个 assembly id 全项目唯一的 latest 槽」→ 参数族 / 多进程互相覆盖基线

- 状态：待修（设计层面）
- 症状：`solve_report.dirty_instances` / `geometry_dirty_instances` 的对比对象是 `latest-assemblies.json` 里该
  assembly id 的**最后一次**构建，不论是谁、以什么参数建的。S6 在同一 id `facade-tower` 下依次建 8/20/36/48 层 +
  RECT/L_SHAPE，每次都把上一座当基线 → 报告的是「和上一个扫描点的差」，不是「和这组参数上次的差」；两个进程
  （例如 S6 扫描与 S7 增量 gate）同时跑时，彼此的基线在中途被替换，dirty 报告不可复现。
  状态文件本身有 O_EXCL 锁（`artifacts/interface.py` `_state_lock`），所以不会写坏，但**语义**上互相污染。
- 对照：part 缓存按 build_key 内容寻址，所有变体并存、回退即命中 —— 同一 SDK 里 part 层可以多变体、装配层只有一个槽。
- 触发：PCG 参数族（同一 id 多参数集）、CI 并行、notebook 与脚本并行。
- 修复方向：基线槽按 (assembly id, build_key/参数指纹) 分；或 `assemble(..., baseline=…)` 显式给出对比对象
  （上一次同参数 / 指定 build）；`solve_report` 里写出基线来自哪次构建（build_key + 时间），让报告可解释。
- 需要的回归测试：同一 id 交替构建参数 A、B、A → 第三次对 A 报告零 dirty。
- 规避（本例）：几何 gate 串行运行；S7 在同一进程里自建基线链（prime 步只建立基线、不判定）。

## D9 读 .scadpkg 的代价 ∝ 实例数 × 重复规范化 / 哈希 / schema 校验（读 20 s，materialize 只要 2.5 s）

- 状态：待修
- 症状：可行性探针的平铺包（12 板型 × 3000 实例，单层装配）在新进程里 `read_product_package` 20 s（profiler 下 40.7 s），
  其后 `materialize_definition` 仅 2.5 s —— 读包比把几何建出来还贵一个量级。
- profiler（`read_product_package`，40.7 s）：
  - `_decode_definitions` 38.4 s；其中 `canonical_bytes` 5401 次 / 22.9 s、`content_hash` 3913 次 / 15.0 s
    （次数 ≈ 实例数，而不是定义数）；rfc8785 `dump` 递归 744 万次。
  - `validate_assembly_definition_graph` 20.1 s（读包时整图再验一遍，而 `_mark_package_validated` 之后 materialize 又查一次标记）。
  - `load_feature_graph_artifact` 13 次 / 17.2 s（`FeatureGraph.from_dict` 12.7 s、`__post_init__` 8.5 s）。
  - jsonschema `validate_manifest` 53 次 / 11.7 s（per-item `items` / `ref` 递归 58 万次）。
- 根因：读路径把「完整性」拆成了逐对象、逐实例的重复工作：每个 component / placement 记录单独 JCS 规范化 + 哈希，
  同一份内容在 decode、图校验、feature graph 构造里各算一遍；schema 校验对大数组逐项走完整 `$ref` 解析。
- 修复方向：
  - 每个 blob 只按 zip 成员哈希一次（manifest 已记内容 hash），decode 后的派生对象不再重算 `content_hash`，缓存 canonical bytes。
  - 读包路径一次图校验，结果随对象携带（已有 `_validated` 标记的思路，推广到 assembly graph / feature graph）。
  - 实例数组用紧凑 schema（或跳过逐项 jsonschema、用类型化解码代替）。
- 需要的回归测试：读包耗时对实例数近似线性且常数小（例如 3000 实例 < 2 s）；同一 blob 在一次读中只哈希一次。

## D10 SDK 自己的输出类型不被兄弟 API 接受：`make_compound_from_assembly_rcompound` → `render_screenshot_rpath` 报错

- 状态：待修（小，但每次都撞）
- 症状：`render_screenshot_rpath(shapes=[scad.make_compound_from_assembly_rcompound(assembly=asm)])` →
  `ValueError: render_screenshot_rpath supports Solid or raw TopoDS_Shape inputs`；要手动 `.wrapped` 降到 OCP 原始类型。
  而且错误在构建 + 展平 3700 件（~5 min 的整个渲染脚本）之后才抛出。
- 根因：渲染入口按 `Solid | TopoDS_Shape` 白名单判型，没有覆盖 SDK 自己的 `Compound` / `Shell` / `Face` 包装类型；
  没有「SDK 返回的几何值都可直接喂给 inspect / render」的类型闭包约定。
- 修复方向：渲染 / 测量入口统一接受任何带 `.wrapped` 的 SDK 形状包装（或一个 `ShapeLike` 协议）；输入判型放在最前面。
- 需要的回归测试：对 SDK 每个返回形状的 `make_*` / `*_rcompound`，结果都能直接 render / measure。

---

## 启发（排查规则）

1. **尺度假设**：凡是「绝对」量化步长 / 容差（1e-7、JSON 2^53、float→int）都要问：100 m 级、1e5 件级时还成立吗？
   优先相对于包围盒的容差。（D3、D4）
2. **读写对称**：序列化规范（JCS）写出来的每一种 token，解析器都必须按同一数域读回；给每种持久化格式做一次
   极值 round-trip 测试。（D4）
3. **与用户规模成正比的递归**：图遍历、链式 feature、嵌套装配——深度随用户输入增长的地方一律迭代实现。（D1）
4. **不可变值 × 逐项追加**：每次追加都重建 + 全量校验 → 整链 O(N²)；校验里再有 O(N) 查找就是 O(N³)。
   找所有 `__post_init__` 中的 `.count` / `in list` / 全量扫描，并提供批量构造入口。（D2）
5. **实例化 ≠ 复制**：任何「按实例」记录的派生数据（摘要、接口、依赖）都应按定义去重、按引用链接；
   否则大小 ∝ 实例数 × 嵌套深度。（D7）
6. **缓存命中路径的代价**：命中路径必须 ≤ 未命中路径；凡是命中时仍要读 / 解析 / 规范化全局状态的，按项目规模退化。
   给 warm/cold 耗时比加基准测试。（D7）
7. **语义标签要跟随刚体变换**：tag / 选择器在变换、装配投影后仍应可用，否则语义层在装配层失效。（D5）
8. **运行时类型族**：PCG 的类型是算出来的，身份（id）不能只能在 import 时声明。（D6）
9. **缓存各层的键要一致**：part 层内容寻址（多变体并存）、装配层 id 单槽（后写覆盖）——同一个「增量」概念在两层
   语义不同，参数族与并行一来就暴露。凡是 “latest” 语义的全局状态，都要问：谁的 latest？（D8）
10. **完整性检查只做一次**：内容哈希 / 规范化 / schema 校验在一次读写里按「对象」计次而不是按「引用」计次；
    给每条 I/O 路径数一下同一 blob 被哈希了几次。验证结果要能随对象携带，别让下游再验。（D7、D9）
11. **API 类型闭包**：SDK 任一函数的返回值，应能直接作为其它 SDK 函数的同类输入；判型白名单要从「SDK 输出类型全集」
    生成，不是手写。（D10）
