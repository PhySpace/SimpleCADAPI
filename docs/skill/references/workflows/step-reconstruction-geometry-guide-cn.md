# STEP 逆向重建：本地几何分析指南

本指南保留本地的 STEP 几何分析方法。建模操作以上游
`step-reconstruction.md` 工作流和当前 SimpleCADAPI 接口为准。恢复的几何
信息是证据，不是可直接执行的原始操作历史。

从已有 `.step`/`.stp` 文件提取几何证据，推断特征树，并用 SimpleCADAPI
重新构建可编辑、可重放、可验证的模型。

## 一、适用范围

当交付目标是“根据目标 STEP 重新建模”时使用本工作流。

以下任务不进入本工作流：

- 只查询尺寸、拓扑、曲面或装配信息：使用
  `references/domains/step-inspection.md`；
- 只要计算几何证据和局部可视化产物、不需要可编辑候补：使用
  `references/workflows/step-computational-geometry-analysis.md`；
- 只做格式转换或导出：使用导出工作流；
- 直接加载目标 STEP 或复制整个 Solid 作为最终模型：这不是逆向重建。

## 二、不可绕过的硬规则

### 2.1 最终程序必须包含真实建模操作

最终重建程序必须在显式 `GraphSession` 中调用公开建模 API，并且最终结果的上游
操作链中至少存在一个 `constructive_modeling` 操作。

以下属于建模操作：

- 创建和约束草图；
- 拉伸、旋转、扫掠和放样；
- 创建基本体；
- 曲面拟合、曲面片和其他曲面构造；
- 并集、切除和相交；
- 阵列、圆角、倒角及其他几何修饰。

以下不属于建模操作：

- STEP/BREP 检查和测量；
- 导入、重放或导出 model JSON；
- 导出 STEP、渲染图片或打印报告；
- 标签、元数据和选择操作；
- `copy_step_region_rpath`；
- `load_brep_region_rshell` 或 `load_brep_region_rsolid`；
- 直接读取目标 STEP 得到的几何。

只包含检查、复制、加载、导入、重放或导出操作的程序必须判定为失败。即使受控
样条面拷贝已经获得授权，复制面也只能补充公开 API 无法满足要求的局部区域，不能
替代最终程序中的真实建模操作。

最终审计必须同时满足：

```text
result_reachable_constructive_modeling_operation_count >= 1
```

仅有 `transcription_load` 节点不能通过该门禁。

### 2.2 输出必须可追踪

最终程序必须：

1. 使用显式 `GraphSession`；
2. 通过 `capture_result` 捕获预期结果；
3. 原样保存 `export_model_json` 返回的 model JSON；
4. 导出候补 STEP；
5. 生成拓扑有序的操作序列；
6. 通过与最终源码绑定的模型审计。

不得手写 model JSON，也不得把源码扫描结果或自然语言特征清单冒充模型操作图。

### 2.3 目标和输出目录相互隔离

目标 STEP 及其目录只读。最终重放不能读取目标 STEP。

所有源码、参数、model JSON、候补 STEP、比较报告、日志、渲染图、sidecar 和
manifest 必须位于用户指定的绝对输出目录内。没有输出目录时不得开始工作，也不
得自行使用默认 `out/`。

输出目录分两层：前置解析包写入 `<绝对输出目录>/analysis/`，Phase 9 后只读；
重建产物全部写入 `<绝对输出目录>/reconstruction/`，不得写进 `analysis/`。
替换解析包后，`reconstruction/` 中依赖旧包的结果全部失效。

## 三、流程总览

```text
目标 STEP
   |
   v
1. 定义需求和验收标准
   |
   v
2. 前置计算几何解析（Phase 1-9，路由 reconstruction_prelude）
   + 读取并校验解析包（R0）
   |
   v
3. 推断特征树
   |
   v
4. 用公开 API 构建候补  <----------------------+
   |                                             |
   v                                             |
5. 审计 + 新进程严格重放 + STEP roundtrip       |
   |                                             |
   v                                             |
6. 分层比较 ---- 不通过：定位根因并修复上游特征 +
   |
   +---- 满足验收标准：进入交付
   |
   +---- 仅样条面持续失败：进入受控回退门禁
```

各阶段串行执行。前一阶段的产物和门禁没有完成时，不得提前宣称后一阶段成功。

## 四、开始工作前的必读内容

检查 STEP 前必须完整阅读：

- `references/inspect/brep-reverse-engineering.md`；
- `references/domains/step-inspection.md`。

编写或修改零件源码前必须完整阅读
`references/discipline/feature-tree-convention.md`，并遵守其特征分块、强制边界注释，
以及 Sketch、直接几何和基本体的选用规则。

## 五、主流程

### 阶段 1：定义需求和验收标准

**输入**

- 目标 STEP；
- 用户的重建目标。

**动作**

阅读 `references/domains/requirement-refinement.md`，形成简短需求说明，明确：

- 目标 STEP 的绝对路径和 SHA-256；
- 用户指定的绝对输出目录；
- 重建范围：单个零件、多个零件或完整装配；
- 保真目标：拓扑一致、结构一致、功能等效或明确的其他目标；
- 尺寸、面积、体积、质心、材料区域、拓扑和自由曲面的验收阈值；
- 阈值的单位和来源；
- 是否允许目标派生的样条面拷贝。

**产物**

- 需求说明；
- 已绑定的输出目录。

**通过门禁**

- 范围、输出目录和验收标准均已确定；
- 未确定事项已经询问用户或记录为显式假设；
- 没有阈值的指标只允许报告数值，不能自行判定通过或“不支持”。

### 阶段 2：前置解析并读取解析包

**输入**

- 目标 STEP；
- 需求说明。

**动作**

1. 以路由 `reconstruction_prelude`、输出目录 `<绝对输出目录>/analysis/`、全部
   八类特征和记录在案的渲染预算，完整执行
   `references/workflows/step-computational-geometry-analysis.md` 的 Phase 1-9。
   该流程负责必读文档、识别、截面、可视化和封包；任一阶段失败即停止重建。
2. 按 `step-reconstruction.md` 的 R0 校验解析包。硬门禁：目标哈希、
   `analysis-config.json` 中的识别参数、目录与 `reconstruction` 的
   `schema_version`、SDK 版本、`artifact-manifest.json` 中的文件哈希、
   `truncated=false` 与 `complete=true`。任一不符就重跑 Phase 1-9，不做局部修补。
   软门禁：`run-status.json` 为 `complete_with_gaps` 时，缺图实例和专项复核
   `incomplete` 的实例可以进入阶段 3，但置信度降级并在交付时说明。
3. 读取 `feature-index.json`、`reconstruction-hypotheses.json`、
   `loft-sweep-specialist.json`、`section-index.json`、`parse-report.md` 和
   `unresolved-features.md`。
4. 解析包回答不了的具体问题，再按 `references/domains/step-inspection.md`
   直接检查目标，并遵守由便宜到昂贵的顺序：只有选定实体后才请求完整曲线或
   曲面定义；大型控制点、节点矢量和采样数组直接保存到 `reconstruction/`。

**产物**

- 通过 R0 的解析包（路径记录在 `reconstruction/` 中）；
- 有明确用途的补充实体、邻接、边界和截面证据；
- 待解释区域清单（含 `unresolved-features.md` 和软门禁缺口）。

**通过门禁**

- 解析包通过全部硬门禁；
- 后续每个特征假设都有目标证据；
- 目录条目只作为证据；缺失、冲突或非强置信度的条目回到实体、邻接、边界和截面
  检查，不能直接变成推断出的建模操作；
- 没有仅凭渲染图或外观猜测几何；
- 没有假设目标与候补中相同的 face ID 表示同一个语义面。

### 阶段 3：推断特征树

**输入**

- 目标证据；
- 待解释区域清单。

**动作**

按 `references/docs/guides/reconstruction-agent-strategy.md` 推断特征族：

```text
共享轴线并呈旋转截面         -> revolve
截面沿固定方向稳定平移       -> extrude
轮廓沿路径传送               -> sweep
有序且持续变化的截面         -> loft
已验证的等角度或等间距重复   -> 一个母特征 + pattern
多个局部几何信号             -> 有序混合特征树
```

对于每个放样/扫掠候选，从 `reconstruction-hypotheses.json` 读取已在 R0 校验过
目标哈希和 schema 的版本化 `reconstruction` 契约，再消费其中的截面、路径、标架、
导轨、端部条件、候选操作和能力状态。专项结果是几何证据，不是可直接执行的原始建模历史。按能够解释 ROI 的
最简单受支持操作选择：

```text
刚性截面 + 恢复路径                 -> sweep_rsolid
可变截面、不要求路径                 -> loft_rsolid / loft_rshell
可变截面 + 恢复路径                  -> loft_rsolid / loft_rshell 近似，路径保留为证据
一条控制朝向的辅助脊线               -> 上游接口暂不支持标架约束
多条强制边界导轨                     -> 已验证曲面网络，否则 unsupported
```

必须使用 `terminal_mode` 区分无点、起点/终点和双点终端。内部点应拆成两个操作。
不得把拟合路径或拟合导轨描述为原始设计意图，也不得把 `planned` 或
`unsupported` 候选当作原生能力执行。

每个基体、孔、槽、缺口、凸台或自由曲面区域记录一条来源信息：

- 观察到的边界或截面；
- 相邻载体和延续证据；
- 拟采用的建模操作；
- 方向、轴线、基准面或路径；
- 置信度；
- 可以证伪该假设的检查。

最终平面上的闭环可能来自后续孔、槽或口袋，不能直接并入基体轮廓。重复和对称也
必须先验证至少两个实例的位置、方向、间距和邻接关系。

**产物**

- 有顺序的特征树假设；
- 按区域记录的来源表；
- 首轮构建计划。

**通过门禁**

- 每个拟建特征都能追溯到证据；
- 每个低置信度假设都有明确的证伪方法；
- 已确定基体、加料、减料和修饰的先后顺序。

### 阶段 4：用公开 API 构建候补

**输入**

- 特征树假设；
- 区域来源表。

**动作**

单零件按 `references/workflows/single-part-modeling.md` 构建。只有证据证明目标包含
多个物理组件时才进入装配建模。

源码必须遵循 `references/discipline/feature-tree-convention.md`：

```text
sketch -> basic body operation -> boolean -> modifier
```

每个特征单独成块，并使用规定的特征边界注释。平面设计轮廓优先使用 Sketch；
非平面路径、自由曲面或 Sketch 无法表达的关系可以使用直接几何，但必须如实标记，
不能把坐标锁定或拟合结果描述为恢复出的设计意图。

构建时：

- 先完成基体，再按证据顺序添加或切除局部特征；
- 贯穿切除工具应超出基体，避免终止面共面；
- 先验证一个代表性特征，再创建阵列；
- 每个主要步骤输出少量 QL 派生事实；
- 布尔失败时修复操作数、相交关系或特征顺序，不把跳过的布尔称为成功。

每次调用放样前，检查截面顺序、闭合、朝向及拓扑兼容性。站位非单调或相邻截面
法向相反时先修复参数，不能反复调用内核碰运气。上游 `loft_rsolid` 与
`loft_rshell` 接受有序截面和 `ruled`，不接受路径或辅助脊线约束。若恢复路径
对结果有影响，必须将仅按截面放样的结果标为近似，并与目标对比验证。

当前 section loft 后端不能可移植地执行端部切向、拔模角、曲率或影响幅值条件。
应保留端部条件的识别证据，并明确选择近似方案或 unsupported，不能静默丢弃。
solid/shell 与 ruled/smooth 的选择
都必须有证据；端部不封闭时不能强制实体化，多导轨曲面网络也不能伪装成单辅助
脊线路径扫掠。

**产物**

- SimpleCADAPI 重建源码；
- API 生成的 model JSON；
- 本轮候补 STEP。

**通过门禁**

- 最终结果由显式 `GraphSession` 和 `capture_result` 产生；
- 最终结果上游至少有一个真实建模操作；
- 候补不是通过直接加载目标 STEP 或 whole-Solid copy 得到；
- model JSON 是 `export_model_json` 的原始输出。

### 阶段 5：审计、严格重放和 roundtrip

**输入**

- 最终源码；
- 该源码实际生成的 model JSON；
- 候补 STEP。

**动作**

生成拓扑有序的操作序列，并对最终源码绑定的 model JSON 执行 API 导入、新进程
严格重放和 STEP roundtrip。

审计时把操作分为：

- `constructive_modeling`：真实建模操作；
- `transcription_load`：加载复制的目标派生区域；
- `selection_or_annotation`：选择、标签或注释；
- `non_geometry`：导入、导出、报告等非几何操作。

**产物**

- 操作序列；
- 与最终源码绑定的模型审计报告；
- 新进程严格重放证据；
- STEP roundtrip 报告。

**通过门禁**

- model JSON 可通过公开 API 导入；
- `strict=True` 重放成功并返回几何；
- 显式结果 ID 非空且可解析；
- 操作序列非空；
- `result_reachable_constructive_modeling_operation_count >= 1`；
- whole-Solid copy 不存在；
- roundtrip 验证通过；
- 源码、model JSON、操作序列和审计报告通过 SHA-256 相互绑定。

源码发生任何最终修改后，以上产物全部失效，必须重新执行本阶段。缺少所需审计
能力时应停止验收，不能退化为源码目测、普通重放或“看起来正确”。

### 阶段 6：分层比较并迭代

**输入**

- 已通过阶段 5 的候补；
- 目标 STEP；
- 验收标准。

**动作**

按以下顺序比较：

1. `compare_global_properties_rdescriptor`：尺寸、面积、体积和质心；
2. `compare_boundary_distance_rdescriptor`：不超过 200 个样本、限定 face ID 的局部
   误差定位；
3. `compare_material_rdescriptor(include_components=True)`：严格材料差异；
4. `compare_steps_rbrepcomparison`：要求精确 BREP 时的最终严格门禁。

必要时使用：

- `track_section_contours_rdescriptor`：分析截面的出现、消失、分裂或合并；
- `fit_face_analytic_rdescriptor`：验证解析载体假设；
- `render_step_comparison_rpath`：提供共同视角的人工复核图。

渲染图只用于复核，不能替代严格比较。严格比较失败后，用
`BRepComparison.to_error_summary()` 按共同根因分组，修复对应的上游特征，然后回到
阶段 4，重新构建、审计、重放、roundtrip 和比较。

每次尝试记录：

- 唯一正整数迭代编号；
- `complete` 或 `failed_attempt` 状态；
- 假设、操作顺序及具体参数变化；
- 重放、BREP 有效性和 roundtrip 状态；
- 候补 STEP 路径和 SHA-256；
- 全局、局部、材料和精确比较摘要；
- 是否成为新的最佳候补及其证据；
- 下一轮要证伪的问题。

`complete` 必须同时满足新进程重放成功、生成新候补 STEP、目标种类 BREP 有效、
roundtrip 有效，并记录候补 SHA-256。其他情况只能记为 `failed_attempt`。

**产物**

- 迭代日志；
- 各层比较报告；
- 通过哈希绑定的最佳有效候补。

**通过门禁**

- 当前候补满足阶段 1 定义的验收标准；或
- 已有足够证据按本文验收层级停止；或
- 只有目标样条面仍失败，并满足进入受控回退评估的前提。

始终保留最佳有效候补。一次参数修正可以沿用当前构造策略；连续没有改善时必须
修改特征假设，不能盲目枚举参数。全局相似不能推翻局部已经证伪的特征。

## 六、样条曲面受控回退

目标派生面拷贝默认禁止。它只用于局部样条面，而且不能替代阶段 4 中的真实建模。

### 6.1 可考虑拷贝的门禁

以下条件必须全部成立：

1. 至少已有 3 次 `complete` 迭代，或至少 5 次格式有效的总迭代；
2. 当前评估对象是迄今最佳的有效完整候补，并与迭代日志的 SHA-256 一致；
3. 需求说明给出了明确的样条面距离或面积阈值；
4. 最佳候补仍有至少一个目标样条面超过阈值；
5. 已枚举目标 STEP 的全部 B-spline/Bezier 面；
6. 每个目标样条面都搜索了候补 STEP 的全部面，不按候补载体类型过滤；
7. 每个目标样条面的映射都为有证据的 `resolved`，没有 `ambiguous` 或
   `unmatched`；
8. 所有与证据相符、公开 API 可表达的适用建模操作序列都已执行，并记录为未达到
   质量要求；
9. 普通任务取得用户明确授权；受控试验处于 `exact_brep_transcription` 模式；
10. 拟拷贝对象只含超过阈值的目标样条面，并能形成连通、有效的 Shell。

满足以上条件只能将 `copy_consideration_ready` 设为 `true`。它表示量化证据完备，
不等于已经获得拷贝授权，也不能自动触发拷贝。

候补对应面可以是一面或多面，也可以是任意载体类型。只有明确的一对一对应才能
使用单面实体比较；一对多或多对一必须比较面集合的双向边界距离和面积误差。

### 6.2 执行拷贝的限制

- `copy_step_region_rpath` 必须提供显式、非空的 `face_ids`；
- face ID 只能来自超过阈值的目标 B-spline/Bezier 面；
- 禁止复制非样条面、禁止省略 `face_ids`、禁止复制整个 Solid；
- sidecar 必须是连通有效的 Shell，并位于输出目录内；
- 最终源码只能用相对路径和 SHA-256 加载 sidecar；
- 最终重放不得读取目标 STEP；
- 拷贝区域必须记录为 `copied / transcribed / retained / embedded_target_derived`；
- 不得把复制的载体、修剪线、pcurve 或拓扑称为恢复出的特征历史。

使用拷贝时必须生成 `simplecadapi.spline-copy-decision/1` 决策记录，绑定目标、最佳
候补、迭代日志、量化报告、授权证据、目标 face ID、sidecar 相对路径和 SHA-256。

最终审计必须检查源码中的拷贝调用、所有 `.scadbrep` 的实际面和决策证据，并通过：

- `source_copy_calls_allowed`；
- `copied_faces_are_spline_surfaces_only`；
- `copy_gate_evidence_valid`；
- whole-Solid copy absent；
- `result_reachable_constructive_modeling_operation_count >= 1`。

最后一项再次确保：即使使用了样条 sidecar，最终程序仍然包含真实建模操作。

## 七、验收层级

按以下顺序判断结果，低层证据不能覆盖高层门禁失败：

1. **拓扑一致**：完成重建；
2. **结构一致，仅有浮点序列化漂移**：记录证据后可以接受；
3. **结构不同，但有依据停止**：只有证据证明不存在更合适的特征顺序，或当前 SDK
   缺少所需操作，并明确记录差异和未恢复区域时才可交付；
4. **仅视觉接近**：不能通过验收。

无论采用哪个层级，最终重建程序都必须通过真实建模操作门禁。

## 八、失败后的处理

| 失败 | 处理 |
| --- | --- |
| 前置解析失败或 R0 硬门禁不通过 | 重跑 Phase 1-9 或报告失败阶段；不得进入阶段 3 |
| 某区域证据不足 | 记录证据缺口，不发明几何 |
| 特征族被局部证据推翻 | 回到阶段 3，修改特征假设和顺序 |
| 布尔或构造失败 | 回到阶段 4，修复操作数、相交关系或上游参数 |
| 没有结果可达的真实建模操作 | 重写最终程序；不得用复制或加载操作代替 |
| 模型审计、严格重放或 roundtrip 失败 | 修复最终源码或 `GraphSession`，重新执行阶段 5 |
| 比较失败 | 定位共同根因，回到阶段 3 或阶段 4 |
| 样条迭代数量不足 | 继续公开 API 建模；拷贝不可用 |
| 样条对应存在 `ambiguous`/`unmatched` | 改进对应搜索；拷贝不可用 |
| 没有明确阈值或授权 | 交付最佳建模候补和差异报告，不执行拷贝 |
| 缺少重建或审计工具 | 明确报告缺失能力，不静默降级 |

## 九、交付物

### 9.1 必须交付

- 前置解析包路径（`analysis/`）及其 `run-status.json` 状态；
- 最终 SimpleCADAPI 重建源码；
- API 生成的 model JSON；
- 拓扑有序的操作序列，其中至少一个结果可达的 `constructive_modeling` 操作；
- 与最终源码绑定的模型审计报告；
- 最佳候补 STEP；
- 新进程严格重放和 STEP roundtrip 证据；
- 目标证据笔记、特征树假设和区域来源表；
- 迭代日志；
- 分层比较报告、验收结论和验收层级；
- 明确列出的未恢复区域；
- 包含角色、字节数和 SHA-256 的产物 manifest。

### 9.2 条件性交付

只有样条回退门禁触发时才增加：

- 全部目标样条面的对应搜索和量化比较报告；
- 模型专用比较代码和数值结果；
- 绑定哈希的 `.scadbrep` sidecar；
- `simplecadapi.spline-copy-decision/1` 决策记录。
