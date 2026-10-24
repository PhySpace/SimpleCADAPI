# re-studio composer 轮 UI 重设计（问题清单 + 设计定稿）

分支 `feat/viewer-re-composer`。本文档记录 2026-09-05 用户验收提出的三类问题：
视口交互（1）、标注输入流（2/3/4）、渲染质量（5）、op 提示词覆盖面（6）。
逐项给出现状根因与目标设计；实现以本文档为准。

## 1. 视口旋转万向节死锁

**现状根因**（第一轮误判为极角夹持，用户复测否决）：`OrbitControls` 是
"转台式"旋转——固定以 `camera.up`（+Z）为极轴做球面坐标，垂直方向总
行程天生被限制在 ≤180°，拖到极点就停；极角夹持只挡住极点退化，改变不了
"转不过去"本身。

**设计**：换成 trackball 式旋转（three.js `TrackballControls`）——拖拽
向量对模型做自由四元数滚转，`camera.up` 随之滚动，没有极点、没有任何
180° 上限，任意方向可以连续转一整圈以上。配套调整：

- `rotateSpeed 1.0`、`dynamicDampingFactor 0.12`（轻微惯性）、
  min/maxDistance 保留原值。
- `keys` 换成不可达哨兵键位码：TrackballControls 在 **window** 级监听
  A/S/D 切换拖拽语义，会污染 composer 打字，必须废掉。
- `resize()` 里补调 `controls.handleResize()`：旋转/平移的像素映射依赖
  元素矩形，而本视口在加载和面板拖动时会变。
- FIT 兼作姿态逃生门：`frame()` 先把 `camera.up` 复位 (0,0,1) 再取景，
  任何滚转姿态下一键回到标准视图。
- `click-selection.ts` 控件参数改为结构类型 `{target, update()}`，点击
  瞬间恢复的相机快照增加 `up`（trackball 下 up 是姿态的一部分）。
- 包查看器（`src/main.ts`）仍为 OrbitControls，未在本轮范围内；
  如需同样行为可复用同一套改法。

## 2. 输入区重设计：一个大输入框 + 胶囊流

**现状**：`.re-composer` 里是四行——op 平铺按钮面板（`#re-op-palette`）、
composer 行（contenteditable + 外挂 ADD 按钮）、round note 输入框、
annotation chip 列表（`#re-chip-list`，intent/count/text）。信息层级乱、
ADD 在框外、chips 不带内容。

**设计**（自上而下只剩两层）：

1. **胶囊列表**（`#re-capsule-list`）：每 ADD 一条，输入框上方出现一枚
   有色胶囊。胶囊底色 = 该条 annotation 的标注色（即视口里高亮这些实体
   的 `markColor(i)`，与 3D marks 同色，一一对应）。
   - 文本 = 该条完整序列化内容（含 face/op 标签），**单行截断 + 省略号**
     （CSS `text-overflow: ellipsis`）。
   - hover 弹 bubble（绝对定位气泡，非原生 title），展示**全部内容**，
     标签照常渲染（同 composer 内联 chip 样式）。
   - 胶囊可删除（×），删除即 `removeAnnotation`。
2. **大输入框**（复用 `TokenComposer` contenteditable）：
   - 占据左下整行，高度更大（min 72px，随内容长高，max ~180px）。
   - **ADD 按钮内嵌**在输入框内部右下角（绝对定位），不再是兄弟节点。
   - round note 合并进大输入框第一行？——否，保留独立 note 输入框
     （提交语义不同：note 是整轮备注，胶囊是逐条标注），放在输入框下方
     一行弱化呈现。

序列化格式不变：`[label](token)`，token 为 `face:N` / `edge:N` /
`vertex:N` / `op:xxx`。

## 3. op 输入改为 slash 触发的上拉候选

**现状**：op 以平铺按钮面板常驻在输入框上方（`renderOperationPalette`），
占空间、打断文本流。

**设计**：

- 输入框内键入 `/` 触发**上拉**候选列表（向上展开，因为输入框贴着底部）。
- `/` 后继续键入 → **关键字母过滤**（对 op_id 与 label 做大小写不敏感的
  子串/首字母匹配）；空过滤 = 全量按类别分组。
- `↑`/`↓` 在候选间移动高亮；`Enter` 确认插入 `op:` token（并清除 `/`
  前缀文本）；`Esc` 关闭；鼠标点击同样确认。
- IME 安全：composing 期间（`isComposing`/keyCode 229）不触发导航键语义，
  沿用 composer 现有防线。
- 平铺面板 `#re-op-palette` 移除；`GET /api/operations` 协议不变，只是
  渲染端从 palette 换成 slash 弹层。输入框 placeholder 提示
  `type / for operations`。

## 4. 上下文注入：op 提示词 + 一层邻接；选择模式收敛

### 4a. 选择模式收敛（single-solid 前提）

- SELECT 只保留 **FACE / EDGE / VERTEX**；BODY 按钮删除（逆向对象恒为
  单 solid，body 不是选择概念）。
- DRAW 只保留 **LASSO**（+OFF）；CIRCLE 删除。
- 代码面：toolbar data 属性收敛；`composerKind`/`SelectionMode` 里
  body/component/solid 分支不再从 re-mode UI 触达（rebuilt 视口仍用
  face 模式，SceneView 能力保留不删）。

### 4b. 上下文注入（`compose_submission`）

**现状**：每条 annotation 的每个 entity 注入 `BRepModel.describe_entity`
结果（含 `adjacency.direct`，截 40 条 id），op 提示只注入被引用的 op。

**设计**（直接按配置注入，一层邻居闭包）：

- **op 提示词**：维持"被引用的 op 才注入"，但 op 清单按第 6 节补全。
- **一层邻接**：对每个选中实体，按其 kind 注入：
  - `face` → 面自身的几何 + **全部边**（每条边：id、几何类型、长度）；
    边给了 → 每条边给**邻接面**（即与该面共享这条边的面，排除自身，
    给 id + 面类型 + 面积）。同时给该面的**顶点**（id、坐标）。
  - `edge` → 该边两端**顶点** + **邻接面**（共享该边的所有面，含 id、
    类型、面积；面数 ≥2 表示内部边，=1 表示自由边/开口）。
  - `vertex` → 该顶点的**邻接边**（id、类型、长度）与**邻接面**（id、类型）。
  - 即"如果给了边，那么它的邻面要给出来；顶点也是一样"——邻接一律
    只做一层，不递归。
- JSON 形态（`annotation.context[entity_id]`）：

```json
{
  "entity": {"topo_id": "face:12", "kind": "face", "geometry": {...}, "properties": {...}},
  "edges": [
    {"topo_id": "edge:7", "geometry": {"type": "CIRCLE", ...}, "length": 18.85,
     "adjacent_faces": [{"topo_id": "face:12", "type": "PLANE"}, {"topo_id": "face:13", "type": "CYLINDER", "area": 512.3}]}
  ],
  "vertices": [
    {"topo_id": "vertex:3", "position": [x, y, z],
     "adjacent_edges": ["edge:7", "edge:9"], "adjacent_faces": ["face:12", "face:13"]}
  ]
}
```

- 邻接图由 `BRepModel`（`src/simplecadapi/inspect/brep.py`）一次性提供：
  `describe_entity` 升级或新增 `describe_entity(entity_id, adjacency_depth=1)`
  风格的入口；`MAX_ADJACENCY_IDS` 截断保留为防炸上限，邻面/邻边列表
  命名截断时在 payload 里标注 `truncated: true`（点名，不静默——遵循
  fallback-must-name-failures 约定）。

## 5. 着色渲染修复

**现状根因**（`scene-view.ts` / `cad-three.ts`）：

1. **颜色穿透**：标注 overlay（`buildEntityOverlays`）材质
   `MeshBasicMaterial(depthTest: false, side: DoubleSide, opacity 0.72)`、
   `renderOrder = 10`——高亮面无条件画在最上层，被模型正面挡住的标注
   全部透视出来（用户截图即多重标注叠加的效果）。边/顶点 overlay 同样
   `depthTest: false`。
2. **边线看不清**：`cadEdgeColor` 把基色亮度 `L + 0.5`——浅灰基体渲染
   出近白边线，叠在被光照打亮的浅色面上直接消失。

**设计**：

1. 面 overlay 改为 `depthTest: true` + 保留 `polygonOffset(-4)` +
   `side: DoubleSide` + `depthWrite: false`：贴着表面画、被前面的实体
   正确遮挡。顶点 overlay：`depthTest: true`，但当顶点在背面被完全吃掉
   会影响选择确认——顶点本身只在 VERTEX 模式可见，用小半径深度偏移。
   边 overlay 同理 `depthTest: true` + polygon offset。
2. 边线颜色：固定深色 `CAD_EDGE_COLOR = '#3a414d'`（深板岩色）——在亮
   体上是明确轮廓，在纯黑背景的剪影处仍可分辨；不做基色派生（浅色派生
   在 AA 半覆盖像素混白后观感随视角漂移）。
3. **线自身的深度偏移**：边线恰好在曲面上，掠射角（剪影）处线片段的
   真实深度会落进面三角形后面，出现虚线断点——面材质
   `polygonOffset(+1,+1)` 后推之外，线材质对称地加
   `polygonOffset(-2,-2)`（负的斜率缩放拉近），随视角斜率自适应。
4. 基材 `materialFor` 不透明（现状已是不透明），光照强度复核
   （key 3.1 偏亮，ACES 下压到 ~2.2），避免浅色面糊掉边线。

## 6. op 提示命令清单（按类别盘点，扩写 operations/*.md）

用户钦定的目标集合（slash 候选即此清单）：

| 类别 | 必含 op |
| --- | --- |
| sketch | sketch（含约束轮廓） |
| boolean | union / cut / intersect |
| body build | extrude / revolve / sweep / loft +（盘点 SDK 全量 body build） |
| primitive | box / cylinder / cone +（盘点 SDK 全量 primitive） |
| surface | fill holes / patch +（盘点 SDK 全量曲面） |
| modifier | chamfer / fillet +（盘点 SDK 全量 modifier） |
| pattern | linear pattern / circular pattern |

现有 `viewer/server/operations/` 只有 13 个 md（boolean 合并、缺
union/cut/intersect 独立即、缺全部 primitive）。盘点结果与补写清单见
下方"Subagent 盘点结论"。

## Subagent 盘点结论

### SDK op 全量清单（六类）

SDK 无 `torus/wedge/pipe/thicken/draft/rib`；pattern 族有 `mirror_shape`，
`translate_shape`/`rotate_shape` 属变换工具不进菜单。落位（op_id → SDK 入口）：

- sketch：`sketch`（make_sketch_rsketch + add_* + constrain_*×27 + make_face_from_sketch_rface）
- boolean：`union`/`cut`/`intersect`（union_rsolid / cut_rsolid / intersect_rsolid，N-ary）；
  2D 版 make_2d_*_rface 属 sketch 通道，不进菜单
- solid build：`extrude`、`revolve`、`sweep`、`loft`、`twisted_sweep`、`helical_sweep`
  （另 `loft_rshell`/`sew_faces_rshell`/`make_solid_from_shell_rsolid` 为壳侧/收尾，归入
  gordon_ruled 与 shell 提示的引用，不单独进菜单）
- primitive：`box`、`cylinder`、`cone`、`sphere`（cone 的 top_radius>0 即 frustum）
- surface：`surface_patch`（make_surface_patch_rface）、`fill_holes`（fill_holes_rshell +
  free_boundaries_rwirelist）、`gordon_ruled`（gordon + ruled + bezier + loft_rshell）；
  `fit_point_grid_rface`/`make_cylindrical_surface_rface`/`trim_surface_rface` 为低频，
  记录在案不进菜单
- modify：`fillet`、`chamfer`、`shell`（shell_rsolid 抽壳，产物仍是 solid）
- pattern：`linear_pattern`、`radial_pattern`（=circular）、`mirror`

最终菜单 23 个 op = `viewer/server/operations/*.md`（boolean.md 已拆分为
union/cut/intersect；每个 md 带 frontmatter label/category/api/reads/doc_refs，
`GET /api/operations` 协议不变）。类别扩为七类：sketch / boolean / solid /
primitive / modify / surface / pattern（`OPERATION_CATEGORIES`）。

### 一层邻接能力

`BRepModel`（`src/simplecadapi/inspect/brep/model.py`）加载 STEP 时已构建全量
邻接表并缓存：`adjacency_details(id)` 对 face 给 `edges`+`neighboring_faces`，
对 edge 给 `faces`+`vertices`+`adjacent_edges`，对 vertex 给 `edges`+`faces`；
`describe_entity(id)` 给 entity_id/kind/geometry（face 含 type/area/centroid，
edge 含 type/length/start/end/closed，vertex 含 coordinates）/bounding_box/adjacency。

实现取 `entity_neighborhood(describe, adjacency, entity_id)`
（`viewer/server/runtime.py`）：选中面 → 卡片含 entity 自述 + 边列表（每条边带
curve_type/length + 其邻接面 topo_id/surface_type/area，含自身）+ 顶点（坐标）+
邻面列表；选中边 → 两端点 + 邻面（1=自由边/接缝边，2=内部边）+ 相邻边；选中顶点
→ 邻接边 + 邻接面。截断上限 `MAX_ADJACENCY_IDS=40`，超限时列表携带
`{items, total, truncated: true}`（点名不静默）。`compose_submission` 新增可选
`adjacency` 参数，`server.py` 传入 `model.adjacency_details` 接通。语义注意：
圆柱接缝边两侧是同一张面，邻面数=1 属正确拓扑，不是缺陷。

## 验收清单（ego browser 真机）

- [ ] 同方向连续拖拽可越过任意极点，累计转角可超 180°（任意轴、任意模型）；
      FIT 后回到 Z-up 标准视图；composer 里打字（含 a/s/d）不改变拖拽语义。
- [ ] slash 输入 `/ext` → 上拉候选过滤出 extrude，↑↓ 选择，Enter 插入
      op token；Esc 关闭；中文 IME 组字期间 Enter 不误触发。
- [ ] ADD 后胶囊出现，颜色与视口标注色一致；长内容截断省略号；hover
      bubble 完整内容且 face/op 标签带样式渲染。
- [ ] SELECT 无 BODY；DRAW 无 CIRCLE。
- [ ] 多个标注着色后模型不透视（背面标注被遮挡），边线在着色体上清晰可读。
- [ ] submission.json 中 context 带 face→edges→adjacent_faces 一层邻接
      与 op 提示词。

## 7. 第二轮 UI 修复（flat 化 + 布局 + FIT 根因）

1. **drag resize**：左右列之间加 7px 列 resizer，右列 REBUILT/底部 dock 之间加
   行 resizer（`#re-col-resizer` / `#re-row-resizer`，lime 高亮，交互与
   .scadpkg viewer 面板一致）。列宽写 `--re-left-width`（默认 50%，min 340px，
   右列保底 380px），行高写 `--re-rebuilt-height`（默认 1.2fr，min 140px）。
2. **输入框简化**：round-note 输入框删除，submission 的 `note` 字段恒为
   `''`；composer placeholder = `whats your idea to rebuild ?`；ADD 按钮 →
   方形 "+"（lucide Plus，28px）。
3. **tab 切换修复**：根因是 `.re-source-panel { display:flex }` 覆盖了
   `hidden` 属性的 UA `display:none`，source 面板永远可见、其余 tab 内容被
   挤到下方。remode.css 顶部加 `[hidden] { display:none !important }` 全局
   守卫（对照 scadpkg viewer 的 `.navigator-view[hidden]` 先例）。
4. **CodeMirror 主题**：PythonEditor 增加 `theme?: Extension[]` 选项（不传
   保持 oneDark 现状，SourceDock 不受影响）；新增 `remode/code-theme.ts` ——
   扁平深色（编辑器 #0b0e12、gutter #0d1117/#202832、active line 微 lime），
   语法色 keywords lime #b3e36b / strings sand #c7a86f / numbers blue
   #91b8ed / functions #a8cdf5，替换原先 oneDark+CSS 硬改底色的拼凑。
5. **FIT 根因修复**（2.05 系数只是表层）：`brep-renderer.ts frame()` 里的
   `Math.max(size.length()*0.5, 0.01)` 半径地板把小模型（link 半径
   0.0028）强行抬到 0.01，相机被推远 3.6×；且 TrackballControls 构造的
   `minDistance=0.01` 绝对值又把推近后的距离钳回 0.01。修复：地板降为
   0.0005（仅防退化几何）、near/far/minDistance/maxDistance 全部改由 radius
   派生（near=r/100 floor 1e-5、far=r×100 floor 0.5、minDistance=r×0.2）。
   乘数 2.8→2.05。ego 实测 dist/radius = 2.050。
6. **高亮色**：draft（ADD 前）视口高亮与 lasso 实时描边从柠檬黄 #fff04d →
   #00c8ff（青色，白模型/深底都可读，且不与已提交标注的 MARK_COLORS 撞色）。
7. **flat 风格对齐 viewer**：全部圆角归零（按钮/胶囊/弹层/输入框）；
   配色 tokens 换成 style.css 体系（#10141a 面板、#202832 细线、#b3e36b
   lime 强调、#151b22 悬浮底、active 模式键 #18221c/#526d40）；品牌角标改
   lime 描边旋转方块；spinner lime；DM Mono 小号大写微标签；lucide SVG
   图标进 FIT/SUBMIT/FACE/EDGE/VERTEX/OFF/LASSO/CLEAR/+/7 个底部 tab/2 个
   顶部 tab（createIcons，stroke-width 1.8）。

### 验收（ego 真机）

- [x] tab 切换互斥：EVALUATION 时 source 隐藏、内容顶对齐 bottom-body 顶部；
- [x] 列 resizer 拖 -160px → 左列 560px；行 resizer 拖 +120px → 447→567px；
- [x] FIT 后 dist/radius = 2.050（修复前 7.31），模型充满视口（抓帧确认）；
- [x] 20 个 lucide 图标渲染、全界面 border-radius=0、CM 编辑器 #0b0e12；
- [x] round-note 不存在、placeholder="whats your idea to rebuild ?"、
      ADD 为 "+" 图标键。

### 第二轮追补（用户截图复测）

- composer 只占左下区一半：模板里遗留的空壳 `#re-composer-host`（flex:1）
  与真正的 composer.host 平分了行宽 —— 删除空壳（composer.host 自带
  `.re-composer-input` flex:1），实测 fill ratio = 1.000。
- FEATURE TREE 标签换行：改名 FEATURE + `.re-tab` 加 white-space:nowrap。
- feature 行取消点击跳 code：FeatureTreeView 不再传 onSelectFeature（回调
  本就可选），fallback 行从 button 改 div、删 click；`.re-feature-tree
  .tree-row` cursor 改 default。
- 代码预览横向滚动：全局 chrome 隐藏滚动条导致横向滚动不可发现；
  `.re-bottom-body` / `.re-code` / `.cm-scroller` / `.re-feature-tree` 显式
  打开 8px 可见滚动条（thumb #344353/#52677c，直角，同 viewer 先例）。

### 第二轮追补 2（CONTEXT PREVIEW 撑爆右列 + FIT 微调）

- 右列被长 single line 撑宽、rebuilt viewport 跟着变形模型偏离：`.re-right`
  只定义了 grid-template-rows，隐式列是 auto（按内容取宽）—— 显式
  `grid-template-columns: minmax(0, 1fr)` 后列宽锁定，代码区由 `.re-code`
  自身横向滚动（ego 注入 4000 字符行实测：右列/canvas 恒 713px，行
  scrollWidth 29067 可滚动）。
- FIT 2.05 → 2.3（用户复测"稍微小一点点"，ego 实测 ratio=2.300）。
