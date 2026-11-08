# SimpleCADAPI JSON Operation Graph Spec

本文档定义 SimpleCADAPI 当前用于导出、交换、replay、以及外部转译适配的 JSON 规范。

目标读者：

- 需要消费 `export_graph_json()` / `export_model_json()` 输出的适配器开发者
- 需要把当前 JSON 图转译到其他 CAD / DSL / workflow 系统的实现者
- 需要确认字段语义、版本边界、以及节点参数格式的集成方

本文档描述的是当前实现行为，而不是理想化设计稿。外部适配请以本文档和当前测试为准。

## 1. Scope

当前存在两类相关 JSON 载荷：

1. `graph JSON`
   - 由 `export_graph_json(graph)` 导出
   - 表示 API 级操作图
   - `schema_version` 当前为 `2.0`
   - 适合轻量 roundtrip、节点级检查、简单 replay

2. `model JSON`
   - 由 `export_model_json(session)` 导出
   - 表示完整 2.0 interchange payload
   - `schema_version` 当前为 `2.0`
   - 包含 `graph`、`leaf_ids`、`expression_graph`、`frame_graph`、registry/log 等附加信息
   - 是当前对外推荐的 interchange / replay 边界

## 2. Versioning And Compatibility

### 2.1 graph JSON

- 导出版本：`schema_version = "2.0"`
- 导入兼容规则：`import_graph_json()` 仅接受 exactly `2.0`
- graph schema 的后续版本必须显式协商，不按 `2.x` 前缀自动接受

### 2.2 model JSON

- 导出版本：`schema_version = "2.0"`
- 导入兼容规则：`import_model_json()` 仅接受 exactly `2.0`
- 当前 canonical contract 版本：`canonical_contract.contract_version = "2.1"`

### 2.3 Contract Layers

SimpleCADAPI v2 明确区分三层契约：

| Layer | Boundary | Stability Rule |
| --- | --- | --- |
| source API | Python public functions such as `make_box_rsolid(...)`, `union_rsolid(...)`, `fillet_rsolid(...)` | 用户调用层；可以是 convenience API 或 macro API |
| canonical graph op | `graph.nodes[].op` values inside graph/model JSON | interchange/replay 层；必须来自 frozen canonical op set |
| model JSON schema | top-level model payload with `schema_version = "2.0"` and `canonical_contract.contract_version = "2.1"` | payload envelope 层；不得混用 draft/final-state version strings |

source API 名字不等于 canonical graph op 名字。Composite source API 可以展开为多个 canonical graph ops，例如 `make_box_rsolid(...)` 展开为 rectangle/face/extrude chain；model JSON schema 只规定 payload envelope 和 contract metadata。

### 2.4 Producer Version

- `producer_version` 是 Python package 版本号
- 它用于调试和排查，不应用作 schema 判断依据

## 3. High-Level Data Model

### 3.1 graph

`graph` 是唯一真相源的 canonical low-level graph。

特点：

- 必须限制在冻结的 canonical op set 内
- 不能泄漏 convenience-only 或 macro-only op
- composite builtin 可以内部构造表达式和 low-level 调用，但最终写入图中的节点只能是 low-level op
- FreeCAD translator 可以对安全的单消费者 transform 做 lowering 优化，例如把 `make_translate_rshape` 折叠进上游 `Part::Extrusion.Placement`，但 canonical graph 节点仍然保留，并在 `.FCStd` 对象的 `SimpleCADFoldedOps` 中记录 evidence

典型结果：

- `make_box` -> rectangle face chain + `extrude`
- `make_circle_rface` -> `make_circle_redge` + `make_wire_from_edges_rwire` + `make_face_from_wire_rface`
- `linear_pattern` -> 多个显式 `translate`
- `radial_pattern` -> 多个显式 `rotate`
- `helical_sweep` 不会作为独立 core node 出现

### 3.2 leaf_ids

`leaf_ids` 是最终结果集的显式 node id 列表。

规则：

- 多输出场景不能依赖 `graph.leaf_nodes()` 猜测最终结果
- `leaf_ids` 是模型导出时的显式返回集合

### 3.3 expression_graph

`expression_graph` 记录参数表达式 DAG。

规则：

- `params` 中保存的是数值快照
- 若某参数来自 `var(...)` / `Expr`，则 `param_exprs` 中会保存到 expression node 的引用
- 适配器如果只做纯几何转译，可以只消费 `params`
- 适配器如果需要恢复参数化关系，应同时消费 `param_exprs + expression_graph`

### 3.4 frame_graph

`frame_graph` 记录每个 operation node 在记录时的坐标系快照。

规则：

- 每个记录节点通常对应一个 `frame:<node_id>` frame
- `node.context` 保存该节点记录时已经完整合成的绝对工作平面；嵌套父帧不会在 replay 时再次相乘
- replay 对每个节点进入其 `node.context`，再用节点中的局部点和向量参数重建几何
- `frame_graph` 提供同一坐标快照的显式注册表，外部转译器也可用它恢复局部工作坐标语义

## 4. graph JSON Schema

`export_graph_json()` 的顶层对象结构如下：

```json
{
  "schema_version": "2.0",
  "producer_version": "2.0.4b3",
  "capabilities": {
    "selection_ref_strategies": true,
    "geo_select_nodes": true,
    "selector_hint_fallback": true,
    "display_payload": true,
    "sketch_constraints": true,
    "sketch_solve_snapshots": true,
    "topology_delta_summary": false,
    "assembly_graph": false,
    "scalar_field_graph": false,
    "expression_graph": true,
    "dimension_tolerances": true
  },
  "graph_id": "graph_xxxxxxxx",
  "nodes": [...],
  "edges": [["src_node_id", "dst_node_id"]]
}
```

### 4.1 Top-Level Fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `schema_version` | `string` | yes | graph schema version, current `2.0` |
| `producer_version` | `string` | yes | package version of exporter |
| `capabilities` | `object` | yes | feature flags for downstream consumers |
| `graph_id` | `string` | yes | unique graph instance id |
| `nodes` | `array<object>` | yes | operation nodes in topological order |
| `edges` | `array<[string,string]>` | yes | adjacency list, each entry is `[src, dst]` |

### 4.2 capabilities

当前导出固定包含以下字段：

| Field | Type | Meaning |
| --- | --- | --- |
| `selection_ref_strategies` | `bool` | detail feature 支持显式 topo refs / index / query 等多种选择策略 |
| `geo_select_nodes` | `bool` | detail selections from QL or indexed child-geometry getters can be serialized as `make_select_*` geo selector nodes |
| `selector_hint_fallback` | `bool` | replay 时支持 selector hint 近似匹配回退 |
| `display_payload` | `bool` | node 中包含 `display` 字段 |
| `sketch_constraints` | `bool` | graph/model JSON 支持声明式 constrained sketch nodes |
| `sketch_solve_snapshots` | `bool` | sketch promotion nodes carry solve evidence for strict replay validation |
| `topology_delta_summary` | `bool` | 当前为 `false`，表示没有额外 summary-only delta schema |
| `assembly_graph` | `bool` | 当前 graph JSON 本身不承载 assembly graph |
| `scalar_field_graph` | `bool` | 当前为 `false`；SDF / scalar field graph 暂时不在支持范围内 |
| `expression_graph` | `bool` | session/model payload 支持 expression graph |
| `dimension_tolerances` | `bool` | session/model payload supports variable tolerances and a tolerance requirement graph |

## 5. Operation Node Schema

`nodes[]` 中每个元素是一个 operation node。

### 5.1 Base Shape

```json
{
  "node_id": "node_xxxxxxxx",
  "op": "extrude",
  "params": {...},
  "inputs": ["node_a", "node_b"],
  "output_count": 1,
  "tags": [],
  "display": {...},
  "param_exprs": {...},
  "context": {...},
  "semantic_delta": {...},
  "topo_delta": {...}
}
```

### 5.2 Field Semantics

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `node_id` | `string` | yes | unique node id within graph |
| `op` | `string` | yes | operation type |
| `params` | `object` | yes | replay / interchange parameter payload |
| `inputs` | `array<string>` | yes | upstream node ids in data-flow order |
| `output_count` | `int` | yes | number of shape outputs produced by this node |
| `tags` | `array<string>` | yes | normalized semantic labels attached at record time |
| `display` | `object` | yes | UI-friendly derived summary; advisory only |
| `param_exprs` | `object` | no | mapping from param name to expression references |
| `context` | `object` | no | fully composed absolute workplane snapshot used while replaying this node |
| `semantic_delta` | `object` | no | semantic entity delta |
| `topo_delta` | `object` | no | topology lineage delta |

### 5.3 Node Invariants

适配器应假设并维持以下不变量：

1. `nodes` 按拓扑序输出
2. `inputs` 中的 node id 必须已在更早节点中出现
3. `edges` 与 `inputs` 表达同一依赖关系，二者必须一致
4. `output_count >= 1`
5. 多输出节点的输出 slot 范围是 `[0, output_count - 1]`

### 5.4 display

`display` 是冗余的、面向 UI 的派生字段，不是 replay 所必需。

当前结构：

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `label` | `string` | yes | 例如 `Box`、`Fillet` |
| `category` | `string` | yes | `primitive` / `profile` / `feature` / `boolean` / `detail` / `transform` / `pattern` / `operation` |
| `summary` | `string` | yes | 基于 `params` 自动生成的短摘要 |
| `selection_count` | `int` | no | 当 `selected_edges` 或 `selected_faces` 存在时出现 |

消费建议：

- 可直接忽略 `display`
- 不要把 `display.summary` 当成结构化数据来源

### 5.5 context

当前 `context` 形状：

```json
{
  "origin": [0.0, 0.0, 0.0],
  "x_axis": [1.0, 0.0, 0.0],
  "y_axis": [0.0, 1.0, 0.0],
  "z_axis": [0.0, 0.0, 1.0]
}
```

字段含义：

- `origin`: 当前局部坐标系原点
- `x_axis`: 当前局部 X 轴方向
- `y_axis`: 当前局部 Y 轴方向
- `z_axis`: 当前局部 Z 轴方向

### 5.6 param_exprs

`params` 保存已求值后的数值；`param_exprs` 保存哪些参数来自表达式图。

示例：

```json
{
  "params": {
    "radius": 2.0
  },
  "param_exprs": {
    "radius": {
      "expr_id": "var_119b16e4"
    }
  }
}
```

规则：

- 如果某个参数没有表达式来源，则 `param_exprs` 中没有该键
- 计数和 legacy fallback 索引参数不会被表达式提升，例如：
  - `selected_edge_indices`
  - `selected_face_indices`
  - `count`
  - `edge_count`
  - `profile_count`
  - `output_count`

注意：

- 由于 canonicalize 规则，非离散标量通常会变成 JSON number，当前实现多数会导出成浮点数
- 即使原始输入是整数，也不要假设它一定以 integer 形式出现

## 6. Semantic Delta Schema

`semantic_delta` 表示语义实体层面的变化。

结构：

```json
{
  "created": [SemanticRef, ...],
  "modified": [SemanticRef, ...],
  "deleted": [SemanticRef, ...],
  "metadata": {...}
}
```

### 6.1 SemanticRef

```json
{
  "graph_id": "graph_xxx",
  "node_id": "node_xxx",
  "entity_type": "Feature",
  "entity_id": "extrude:0"
}
```

字段含义：

| Field | Type | Meaning |
| --- | --- | --- |
| `graph_id` | `string` | 所属 graph id |
| `node_id` | `string` | 产生该语义实体的 node id |
| `entity_type` | `string` | 语义实体类型，如 `Body` / `Feature` / `Sketch` / `Profile` / `Point` / `ShapeOutput` |
| `entity_id` | `string` | 在 node 内部稳定的实体 id，通常是 `<op>:<slot>` |

### 6.2 Current Entity Type Mapping

当前实现的默认映射如下：

- `make_point_rvertex` -> `Point`
- 草图/轮廓类节点 -> `Profile` 或 `Sketch`
- primitive solid / transform body -> `Body`
- feature / detail / boolean 类节点 -> `Feature`
- 无法分类时 -> `ShapeOutput`

其中：

- `make_*_face` 与 `make_face_from_wire` -> `Sketch`
- `make_*_edge` / `make_*_wire` -> `Profile`
- `make_extrude_rsolid` / `make_revolve_rsolid` / `make_loft_rsolid` / `make_sweep_rsolid` / `make_twisted_sweep_rsolid` / `make_fillet_rsolid` / `make_chamfer_rsolid` / `make_shell_rsolid` / `make_cut_rsolid` / `make_union_rsolid` / `make_intersect_rsolid` -> `Feature`

## 7. Topology Delta Schema

`topo_delta` 表示子拓扑级别的 lineage 变化。

结构：

```json
{
  "preserved": [TopoRef, ...],
  "modified": [TopoRef, ...],
  "generated": [TopoRef, ...],
  "deleted": [TopoRef, ...],
  "section_edges": [TopoRef, ...],
  "entries": [TopoEntry, ...],
  "raw_event": {...}
}
```

### 7.1 TopoRef

```json
{
  "graph_id": "graph_xxx",
  "node_id": "node_xxx",
  "output_slot": 0,
  "kind": "EDGE",
  "topo_id": "edge_640974"
}
```

字段含义：

| Field | Type | Meaning |
| --- | --- | --- |
| `graph_id` | `string` | 所属 graph id |
| `node_id` | `string` | 产生该 subshape 的 node id |
| `output_slot` | `number` | 对应 node 输出槽位；消费端应按整数解释 |
| `kind` | `string` | `VERTEX` / `EDGE` / `WIRE` / `FACE` / `SOLID` |
| `topo_id` | `string` | 当前实现生成的 opaque subshape id |

注意：

- `output_slot` 在 node-level topo refs 中通常是整数
- 但当 `TopoRef` 被嵌入 `params.selected_edges[]` 等深层对象并经过参数 canonicalize 后，可能表现为 `0.0`
- 消费端应将其按整数语义处理

### 7.2 TopoEntry

当前 schema 支持 richer entry，但多数情况下 `entries` 为空数组。

结构：

```json
{
  "ref": TopoRef,
  "event": "GENERATED",
  "origin_role": "tool",
  "parent_refs": [TopoRef, ...],
  "metadata": {...}
}
```

### 7.3 Topology Delta Notes

- 当前 `raw_event` 为保留字段，通常为空对象
- 许多 primitive node 没有 `topo_delta`
- 追踪型 feature / boolean node 更可能包含 `topo_delta`

## 8. Selection Reference Schema

detail feature 使用显式选择引用来稳定 replay。

### 8.1 Canonical Contract

`model.json.canonical_contract.selection_ref_schema` 当前固定声明：

```json
{
  "edge_param": "selected_edges",
  "face_param": "selected_faces",
  "edge_index_param": "selected_edge_indices",
  "face_index_param": "selected_face_indices",
  "required_topo_ref_fields": [
    "graph_id",
    "node_id",
    "output_slot",
    "kind",
    "topo_id"
  ],
  "optional_fields": ["selector_hint", "geo_selector", "selected_*_node_ids"],
  "replay_resolution_order": [
    "geo_select_nodes",
    "selection_query",
    "explicit_topo_refs",
    "legacy_indices",
    "selector_hint"
  ]
}
```

### 8.2 Explicit Edge / Face Ref

`selected_edges[]` / `selected_faces[]` 的元素结构：

```json
{
  "graph_id": "graph_xxx",
  "node_id": "node_xxx",
  "output_slot": 0.0,
  "kind": "EDGE",
  "topo_id": "edge_640974",
  "selector_hint": {
    "kind": "edge",
    "tags": ["edge", "left"],
    "length": 4.0,
    "start": [-2.0, -2.0, 4.0],
    "end": [-2.0, -2.0, 0.0]
  }
}
```

### 8.3 selector_hint

`selector_hint` 是最后一级 fallback 信息，不保证稳定命中，但可提高恢复率。

不同 shape kind 的可见字段：

| Shape Kind | Possible Hint Fields |
| --- | --- |
| `edge` | `kind`, `tags`, `length`, `start`, `end`, `center` |
| `face` | `kind`, `tags`, `area`, `center`, `normal` |
| `wire` | `kind`, `tags`, `edge_count`, `closed` |
| `vertex` | `kind`, `tags`, `coordinates` |
| `solid` | `kind`, `tags`, `volume`, `bbox` |

### 8.4 Geo Select Nodes

当 detail feature 使用 QL selector 或 `get_edges(index)` / `get_faces(index)` 这类 indexed child-geometry getter 时，新 graph 不把 QL 文本或 Python list position 作为主要事实来源。运行时读取每个被选中子形状的几何事实，并为每一项生成一个 canonical select 节点：

- `make_select_redge`
- `make_select_rface`
- `make_select_rwire`
- `make_select_rvertex`
- `make_select_rsolid`

如果选择结果是 list，则每个元素对应一个独立 select 节点。feature node 通过 `selected_edge_node_ids` 或 `selected_face_node_ids` 指向这些节点。

select node 示例：

```json
{
  "op": "make_select_redge",
  "params": {
    "target_kind": "edge",
    "geo_selector": {
      "mode": "geo_exact",
      "kind": "edge",
      "geom_type": "CIRCLE",
      "length": 6.283185307179586,
      "center": [0.0, 0.0, 0.0],
      "start": [1.0, 0.0, 0.0],
      "end": [1.0, 0.0, 0.0],
      "bbox": {
        "min": [-1.0, -1.0, 0.0],
        "max": [1.0, 1.0, 0.0]
      },
      "metadata_geo": {"edge_index": 2}
    }
  },
  "inputs": ["node_for_source_solid"],
  "output_count": 1
}
```

`geo_selector` 不包含 tags，也不通过 tag 搜索。它固定到运行时选中对象的完整可见几何事实；完整几何数据用于 replay、审计和外部 adapter 校验。

### 8.5 selection_query fallback

旧 payload 或手写 payload 仍可携带 `selection_query`。这是 `ShapeSelector.to_dict()` 的结果，示例：

```json
{
  "target_kind": "edge",
  "order_desc": false,
  "cardinality": {"exactly": 1},
  "predicate": {
    "kind": "property_compare",
    "data": {
      "path": "geom.type",
      "op": "==",
      "value": "CIRCLE"
    },
    "children": []
  },
  "order_key": {
    "kind": "property",
    "data": {
      "path": "geom.center.z",
      "default": null
    }
  },
  "limit": 1
}
```

可选 source scope 字段：

| Field | Type | Meaning |
| --- | --- | --- |
| `source_node_id` | `string` | replay 时先定位该 graph node 的输出作为 selector scope |
| `source_output_slot` | `int` | graph node 输出槽位，默认 `0` |
| `order_keys` | `array<object>` | 多 key 排序，按声明顺序做 lexicographic ordering |

`cardinality` 支持：

| Field | Meaning |
| --- | --- |
| `exactly` | selector 必须解析出准确数量 |
| `at_least` | selector 必须解析出至少该数量 |
| `at_most` | selector 必须解析出至多该数量 |

更复杂的 traversal selector 会出现：

- `source`
- `traversal`

例如 boundary traversal：

```json
{
  "target_kind": "edge",
  "source": {
    "target_kind": "wire",
    "source": {
      "target_kind": "face",
      "predicate": {...},
      "limit": 1,
      "cardinality": {"exactly": 1},
      "order_desc": true,
      "order_key": {...}
    },
    "traversal": {"relation": "boundary"},
    "predicate": {...},
    "limit": 1,
    "cardinality": {"exactly": 1},
    "order_desc": false
  },
  "traversal": {"relation": "boundary"},
  "order_desc": false,
  "cardinality": {"exactly": 4}
}
```

### 8.6 Replay Resolution Order

detail feature replay 的固定解析顺序为：

1. `selected_edge_node_ids` / `selected_face_node_ids` 指向的 geo select nodes
2. `selection_query` fallback
3. `selected_edges` / `selected_faces` 中的显式 topo refs
4. `selected_edge_indices` / `selected_face_indices` legacy fallback
5. `selector_hint`

适配器若要实现等价行为，必须保持这个顺序。

## 9. Tag Schema

normalized tags 是默认 tag schema。`tags[]` 应只承载满足以下 grammar 的语义标签：

```text
[a-z][a-z0-9_-]*(.[a-z][a-z0-9_-]*)*
```

常用 namespace：

| Prefix | Meaning |
| --- | --- |
| `role.*` | user/domain role, anchor lookup highest priority |
| `anchor.*` | explicit anchor alias |
| `face.*` | face-level semantic tag |
| `edge.*` | edge-level semantic tag |
| `wire.*` | wire-level semantic tag |
| `vertex.*` | vertex-level semantic tag |
| `solid.*` | solid-level semantic tag |
| `geom.*` | primitive/geometry classification tag, e.g. `geom.primitive.box` |
| `op.*` | operation lineage tags |
| `origin.*` | boolean/tracking origin role tags |

Legacy numeric or descriptive tags such as `"0"`, `"size: 1x2x3"`, or `"bottom center: ..."` must not be emitted into `tags[]` by new code. Store that data under `metadata["geo"]` instead, for example:

```json
{
  "tags": ["geom.primitive.box", "solid.primitive"],
  "metadata": {
    "geo": {
      "type": "box",
      "size": {"x": 1.0, "y": 2.0, "z": 3.0},
      "bottom_face_center": [0.0, 0.0, 0.0]
    }
  }
}
```

Anchor lookup priority is explicit and stable:

1. `role.<name>`
2. `anchor.<name>`
3. `<topology-kind>.<name>`, such as `face.top`, `edge.left`, `wire.outer`
4. legacy aliases, including bare names such as `top` or legacy-prefixed names

QL examples should use normalized tags:

```python
from simplecadapi import ql as Q

top = Q.faces().where(Q.tag("face.top")).take(1).exactly(1)
mount = Q.faces().where(Q.tag("role.mounting_surface")).take(1).exactly(1)
outer_edges = Q.faces().where(Q.tag("face.top")).boundary("wire").where(Q.tag("wire.outer")).boundary("edge")
```

## 10. Expression Graph Schema

`expression_graph` 结构：

```json
{
  "nodes": [
    {
      "expr_id": "var_119b16e4",
      "kind": "var",
      "name": "r",
      "default": 2.0,
      "unit": "mm",
      "tolerance": {
        "lower_deviation": -0.1,
        "upper_deviation": 0.2
      },
      "tolerance_unit": "mm"
    }
  ]
}
```

### 10.1 Node Variants

#### const

```json
{
  "expr_id": "const_xxx",
  "kind": "const",
  "value": 3.0
}
```

#### var

```json
{
  "expr_id": "var_xxx",
  "kind": "var",
  "name": "radius",
  "default": 2.0,
  "unit": "mm",
  "tolerance": {
    "lower_deviation": -0.05,
    "upper_deviation": 0.1
  },
  "tolerance_unit": "mm"
}
```

#### expr

```json
{
  "expr_id": "expr_xxx",
  "kind": "expr",
  "op": "mul",
  "args": ["var_xxx", "const_xxx"]
}
```

### 10.2 Supported Expression Ops

当前实现支持：

- `add`
- `sub`
- `mul`
- `div`
- `pow`
- `neg`
- `abs`
- `sin`
- `cos`
- `tan`
- `sqrt`
- `acos`
- `asin`
- `atan`
- `atan2`

### 10.3 Unit And Dimension Semantics

Variable nodes may include:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `unit` | `string | unit object` | no | nominal declaration unit |
| `tolerance` | `object` | no | signed deviations in `tolerance_unit` |
| `tolerance_unit` | `string | unit object` | no | source tolerance unit; defaults to `unit` in Python declarations |

Built-in units serialize as symbols such as `mm`, `in`, `deg`, or `rad`. Custom
units serialize in full:

```json
{
  "symbol": "thou",
  "dimension": {"length": 1, "angle": 0},
  "scale_to_canonical": 0.0254
}
```

Dimensions contain required integer `length` and `angle` exponents. Canonical
numeric values used by operation-node `params` and tolerance analysis are `mm`,
`mm^2`, `mm^3`, `deg`, or `1` for the named dimensions.

Import rebuilds the complete DAG and reruns dimension inference. Addition and
subtraction require matching dimensions; multiplication/division combine
exponents; dimensioned powers require supported constant exponents; square root
requires even exponents; and trigonometric operations enforce Angle/Dimensionless
inputs. A graph cannot mix unit-declared variables with legacy variables lacking
units. Unitless legacy graphs remain accepted.

### 10.4 Dimension Tolerance Graph

Variable `tolerance` values are signed deviations from `default`. A scalar source dimension must use `lower_deviation <= 0 <= upper_deviation`.

Session/model payloads may include a sibling `tolerance_graph`:

```json
{
  "requirements": [
    {
      "requirement_id": "req.clearance",
      "target_expr_id": "expr_clearance",
      "tolerance": {
        "lower_deviation": -0.2,
        "upper_deviation": 0.3
      },
      "method": "worst_case",
      "name": "clearance",
      "tolerance_unit": "mm",
      "target_dimension": {
        "length": 1,
        "angle": 0
      }
    }
  ],
  "validation": {
    "passed": true,
    "checks": []
  }
}
```

Supported methods are `worst_case` and `rss`. Unit-aware requirements must target
Length or Angle. `tolerance_unit` must match the inferred target dimension and is
converted to the canonical unit before comparison. Importers recompute validation
from `expression_graph`, compare the inferred result to `target_dimension`, and do
not trust serialized `validation` evidence. Missing `tolerance_graph` is treated as
an empty graph for backward compatibility. Legacy requirements may omit both unit
fields when their target expression is unitless.

## 11. Frame Graph Schema

`frame_graph` 结构：

```json
{
  "nodes": [
    {
      "frame_id": "frame:node_abc",
      "origin": [0.0, 0.0, 0.0],
      "x_axis": [1.0, 0.0, 0.0],
      "y_axis": [0.0, 1.0, 0.0],
      "z_axis": [0.0, 0.0, 1.0],
      "parent_frame_id": null,
      "metadata": {"node_id": "node_abc"}
    }
  ]
}
```

字段含义：

| Field | Type | Meaning |
| --- | --- | --- |
| `frame_id` | `string` | frame 唯一 id |
| `origin` | `vec3` | frame 原点 |
| `x_axis` | `vec3` | frame X 轴 |
| `y_axis` | `vec3` | frame Y 轴 |
| `z_axis` | `vec3` | frame Z 轴 |
| `parent_frame_id` | `string|null` | 父 frame；当前 node frames 通常为 `null` |
| `metadata` | `object` | 当前至少包含 `node_id` |

## 12. model JSON Schema

`export_model_json()` 的顶层结构：

```json
{
  "schema_version": "2.0",
  "canonical_contract": {...},
  "graph": {...},
  "expression_graph": {...},
  "tolerance_graph": {...},
  "frame_graph": {...},
  "geometry_registry": [...],
  "semantic_entity_registry": [...],
  "sketch_profile_registry": [...],
  "semantic_delta_log": [...],
  "topology_delta_log": [...],
  "leaf_ids": [...]
}
```

### 12.1 Top-Level Fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `schema_version` | `string` | yes | current `2.0` |
| `canonical_contract` | `object` | yes | machine-readable interchange contract |
| `graph` | `graph object` | yes | canonical low-level graph and only source of truth |
| `leaf_ids` | `array<string>` | yes | explicit result set for multi-output graph replay/export |
| `expression_graph` | `object` | yes | expression DAG |
| `tolerance_graph` | `object` | no | dimension-chain requirements and validation evidence; defaults to an empty graph |
| `frame_graph` | `object` | yes | frame snapshots |
| `geometry_registry` | `array<object>` | yes | output geometry registry |
| `semantic_entity_registry` | `array<object>` | yes | semantic entity registry |
| `sketch_profile_registry` | `array<object>` | yes | sketch/profile node registry |
| `semantic_delta_log` | `array<object>` | yes | semantic delta log |
| `topology_delta_log` | `array<object>` | yes | topology delta log |

### 12.2 canonical_contract

当前固定结构：

```json
{
  "contract_version": "2.1",
  "graph_roles": {
    "graph": "canonical_low_level_graph",
    "leaf_ids": "explicit_result_set"
  },
  "replay_policy": {
    "preferred_graph": "graph",
    "default_mode": "strict",
    "permissive_mode": "explicit_opt_in"
  },
  "core_op_set": [...],
  "selection_ref_schema": {...}
}
```

消费规则：

- `replay_model_json()` 直接使用 `graph`
- 多输出 graph 的最终结果集由 `leaf_ids` 显式声明
- replay 默认 strict；permissive 仅通过 API 参数显式 opt-in
- importer 仍识别冻结的 `2.0` contract，但 `2.0` graph 不得使用
  `load_brep_region_rshell`、`load_brep_region_rsolid`、
  `make_solid_from_shell_rsolid`、`trim_rsketch`、`extend_rsketch`、
  `fillet_corner_rsketch`、`chamfer_corner_rsketch`、`project_rsketch`、
  `insert_spline_anchor_rsketch`、`remove_spline_anchor_rsketch`、`convert_spline_to_anchors_rsketch`、
  `explode_rassembly` 或曲线/曲面编辑操作（`convert_to_bspline_*`、`set_*_poles_*`、
  `move_*_poles_*`、`set_*_weights_*`、`insert_*_knot_*`、`elevate_*_degree_*`、`rebuild_*`）。
- 为兼容早期 `2.0` model payload，importer 将缺失的
  `canonical_contract` 视为最小 legacy `{"contract_version": "2.0"}`；
  新导出的 model payload 仍必须显式包含完整 contract。

### 12.3 geometry_registry

每条记录结构：

```json
{
  "graph_id": "graph_xxx",
  "node_id": "node_xxx",
  "entity_type": "Feature",
  "entity_id": "extrude:0",
  "source_op": "extrude"
}
```

来源规则：

- 若 node 有 `semantic_delta.created`，则按其 created refs 写入 registry
- 若 node 没有 semantic delta，则按 `output_count` fallback 生成 `ShapeOutput`

### 12.4 semantic_entity_registry

当前内容与 `geometry_registry` 高度重叠，但语义上强调 semantic entity 视角。Assembly/constraint semantic entities are not emitted while the assembly system is redesigned.

### 12.5 sketch_profile_registry

仅收录草图/轮廓相关 op，当前集合包括：

- `make_point`
- `make_line`
- `make_segment_wire`
- `make_circle_edge`
- `make_circle_wire`
- `make_circle_face`
- `make_rectangle_wire`
- `make_rectangle_face`
- `make_three_point_arc`
- `make_three_point_arc_wire`
- `make_angle_arc`
- `make_angle_arc_wire`
- `make_spline`
- `make_spline_wire`
- `make_polyline_wire`
- `make_helix`
- `make_helix_wire`
- `make_wire_from_edges`
- `make_face_from_wire`

New canonical profile nodes use the `make_*_r*` names listed in `canonical_contract.core_op_set`; legacy short names are only tolerated here as older registry metadata, not as canonical model graph ops.

记录结构：

```json
{
  "graph_id": "graph_xxx",
  "node_id": "node_xxx",
  "op": "make_circle_face",
  "params": {...}
}
```

### 12.6 semantic_delta_log / topology_delta_log

两者都按 graph 的拓扑顺序记录。

结构分别为：

```json
{
  "node_id": "node_xxx",
  "op": "extrude",
  "delta": {...}
}
```

## 13. graph Canonical Op Set

当前 canonical low-level graph op set 固定为下面的 source-API-like op names。注意这些是 graph/model JSON 的 canonical op names，不是旧版短 op names：

- `make_point_rvertex`
- `load_brep_region_rshell`
- `load_brep_region_rsolid`
- `make_line_redge`
- `make_circle_redge`
- `make_three_point_arc_redge`
- `make_angle_arc_redge`
- `make_spline_redge`
- `make_helix_redge`
- `make_wire_from_edges_rwire`
- `make_face_from_wire_rface`
- `make_face_from_wires_rface`
- `make_sketch_rsketch`
- `add_point_rsketch`
- `add_line_rsketch`
- `add_circle_rsketch`
- `add_arc_rsketch`
- `add_bspline_rsketch`
- `trim_rsketch`
- `extend_rsketch`
- `fillet_corner_rsketch`
- `chamfer_corner_rsketch`
- `project_rsketch`
- `insert_spline_anchor_rsketch`
- `remove_spline_anchor_rsketch`
- `convert_spline_to_anchors_rsketch`
- `make_constrain_coincident_rsketch`
- `make_constrain_point_on_rsketch`
- `make_constrain_horizontal_rsketch`
- `make_constrain_vertical_rsketch`
- `make_constrain_parallel_rsketch`
- `make_constrain_perpendicular_rsketch`
- `make_constrain_collinear_rsketch`
- `make_constrain_tangent_rsketch`
- `make_constrain_concentric_rsketch`
- `make_constrain_midpoint_rsketch`
- `make_constrain_symmetric_rsketch`
- `make_constrain_equal_length_rsketch`
- `make_constrain_equal_radius_rsketch`
- `make_constrain_distance_rsketch`
- `make_constrain_distance_x_rsketch`
- `make_constrain_distance_y_rsketch`
- `make_constrain_length_rsketch`
- `make_constrain_angle_rsketch`
- `make_constrain_radius_rsketch`
- `make_constrain_diameter_rsketch`
- `make_constrain_fix_rsketch`
- `make_wire_from_sketch_rwire`
- `make_face_from_sketch_rface`
- `make_extrude_rsolid`
- `make_revolve_rsolid`
- `make_loft_rsolid`
- `make_sweep_rsolid`
- `make_twisted_sweep_rsolid`
- `make_translate_rshape`
- `make_rotate_rshape`
- `make_mirror_rshape`
- `make_cut_rsolid`
- `make_union_rsolid`
- `make_intersect_rsolid`
- `make_fillet_rsolid`
- `make_chamfer_rsolid`
- `make_shell_rsolid`
- `make_bezier_surface_rface`
- `make_cylindrical_surface_rface`
- `fit_point_grid_rface`
- `make_ruled_surface_rface`
- `make_gordon_surface_rface`
- `make_surface_patch_rface`
- `trim_surface_rface`
- `convert_to_bspline_redge`
- `convert_to_bspline_rface`
- `set_curve_poles_redge`
- `move_curve_poles_redge`
- `set_curve_weights_redge`
- `insert_curve_knot_redge`
- `elevate_curve_degree_redge`
- `set_surface_poles_rface`
- `move_surface_poles_rface`
- `set_surface_weights_rface`
- `insert_surface_knot_rface`
- `elevate_surface_degree_rface`
- `rebuild_curve_redge`
- `rebuild_surface_rface`
- `make_loft_rshell`
- `sew_faces_rshell`
- `make_solid_from_shell_rsolid`
- `free_boundaries_rwirelist`
- `fill_holes_rshell`

下列 node 不允许出现在 canonical `graph`：

- `make_box`
- `make_cylinder`
- `make_sphere`
- `make_cone`
- `make_point`
- `make_line`
- `make_circle_edge`
- `make_three_point_arc`
- `make_angle_arc`
- `make_spline`
- `make_helix`
- `make_wire_from_edges`
- `make_face_from_wire`
- `extrude`
- `revolve`
- `loft`
- `sweep`
- `translate`
- `rotate`
- `mirror`
- `cut`
- `union`
- `intersect`
- `fillet`
- `chamfer`
- `shell`
- `make_circle_face`
- `make_rectangle_face`
- `make_circle_wire`
- `make_rectangle_wire`
- `make_polyline_wire`
- `make_segment_wire`
- `make_three_point_arc_wire`
- `make_angle_arc_wire`
- `make_spline_wire`
- `make_helix_wire`
- `linear_pattern`
- `radial_pattern`
- `helical_sweep`
- `make_sketch_point_rsketchref`
- `make_solve_sketch_rsketchresult`

Tests must treat this list as a hard constraint: every exported model graph op must be a subset of `canonical_contract.core_op_set`, and legacy op names must be rejected or isolated outside canonical model JSON.

Sketch solve is a promotion process, not a standalone graph result. Canonical sketch-to-geometry nodes (`make_wire_from_sketch_rwire`, `make_face_from_sketch_rface`) include `solve_snapshot` evidence and replay checks that evidence in strict mode.

## 14. Recorded Operation Catalog

本节定义当前会出现在 graph/model JSON 中的 operation node 格式。

说明约定：

- `Inputs` 表示 `inputs[]` 依赖的上游输出类型
- `Outputs` 表示当前 node 的 shape 输出类型
- `Params` 只写当前真正落盘的键，不写 Python API 的全部形参名
- 如果某个 Python API 会被宏展开而不是单独记录，会单独说明

### 14.1 Primitive And Profile Ops

#### `make_point_rvertex`

- Inputs: none
- Outputs: 1 `Vertex`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `x` | scalar | X coordinate |
| `y` | scalar | Y coordinate |
| `z` | scalar | Z coordinate |

#### `make_line_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `start` | `vec3` | start point |
| `end` | `vec3` | end point |

Notes:

- `make_segment_redge()` 是别名 API，但记录成 `make_line_redge`

#### `make_segment_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `start`, `end`

#### `make_circle_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Params: `center`, `radius`, `normal`

#### `make_circle_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `center`, `radius`, `normal`

#### `make_circle_rface`

- Inputs: none
- Outputs: 1 `Face`
- Params: `center`, `radius`, `normal`

#### `make_rectangle_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `width`, `height`, `center`, `normal`

#### `make_rectangle_rface`

- Inputs: none
- Outputs: 1 `Face`
- Params: `width`, `height`, `center`, `normal`

#### `make_face_from_wire_rface`

- Inputs: 1 `Wire`
- Outputs: 1 `Face`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `normal` | `vec3` | desired normal hint |

#### `make_wire_from_edges_rwire`

- Inputs: N `Edge`
- Outputs: 1 `Wire`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `edge_count` | `int` | number of consumed edges |

#### `make_three_point_arc_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Params: `start`, `middle`, `end`

#### `make_three_point_arc_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `start`, `middle`, `end`

#### `make_angle_arc_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Params: `center`, `radius`, `start_angle`, `end_angle`, `normal`

#### `make_angle_arc_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `center`, `radius`, `start_angle`, `end_angle`, `normal`

#### `make_spline_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Semantics: exact B-spline definition. `control_points` are poles, not sampled/interpolated curve points. Use `fit_cubic_bspline_control_points(...)` to convert sampled curve points into this exact payload before calling the geometry API.
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `control_points` | `array<vec2|vec3>` | B-spline poles; 2D points are lifted to z=0 |
| `degree` | `int` | B-spline degree, default/source canonical examples use `3` |
| `knots` | `array<number>` | strictly increasing unique knot values |
| `multiplicities` | `array<int>` | multiplicities aligned with `knots` |
| `weights` | `array<number> | null` | optional positive rational weights |
| `periodic` | `bool` | whether the exact curve is periodic |

#### `make_spline_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `control_points`, `degree`, `knots`, `multiplicities`, `weights`, `periodic`

#### `make_polyline_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `points`, `closed`

#### `make_helix_redge`

- Inputs: none
- Outputs: 1 `Edge`
- Params: `pitch`, `height`, `radius`, `center`, `dir`

#### `make_helix_rwire`

- Inputs: none
- Outputs: 1 `Wire`
- Params: `pitch`, `height`, `radius`, `center`, `dir`

### 14.2 Declarative Sketch Ops

#### `make_sketch_rsketch`

- Inputs: none
- Outputs: 1 `Sketch`
- Params: `name`, `plane`, `sketch_id`

#### `add_point_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `point_id`, `x`, `y`

#### `add_line_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity_id`, `start`, `end`, `construction`
- `start` and `end` are stable point target ids such as `p0`, `p1`, or endpoint paths such as `line.start`.

#### `add_circle_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity_id`, `center`, `radius`, `construction`
- `center` is a stable point target id.

#### `add_arc_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity_id`, `start`, `end`, `center`, `construction`

#### `add_bspline_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity_id`, `start`, `end`, `control_points`, `degree`, `knots`, `multiplicities`, `weights`, `periodic`, `construction`
#### `trim_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity`, `at`, `against`
- `at` is `[x, y]` in sketch coordinates or a point id; `against` is a list of entity ids or `null` (every non-construction entity). The edit is made on the solved geometry, so replay is deterministic.

#### `extend_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `entity`, `end` (`start` or `end`), `to` (entity id or `null`)

#### `fillet_corner_rsketch` / `chamfer_corner_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `a`, `b` (line ids), `radius` (fillet) or `distance` (chamfer)
- The edit is made on the solved geometry and picks its own ids (`p<n>`, `a<n>`, `l<n>`, `c_<kind>_<n>`), so replay is deterministic. `radius` / `distance` are recorded as symbolic parameters when they were `Var` / `Expr`.

#### `project_rsketch`

- Inputs: the target `Sketch` and either the source `Sketch` (`source_kind: "sketch"`: inputs `[target, source]`) or the projected shapes (`source_kind: "shapes"`: the shape inputs, then the target `Sketch`)
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `source_kind`, `source` (source sketch id, or the number of shapes), `entities` (source entity ids or `null`; sketch sources only), `construction`
- Projected ids are `proj_<source sketch id>_<n>` (`proj_shape_<n>` for shapes); the target sketch's `projections` metadata lists `{source, entity, projected}`.

#### `insert_spline_anchor_rsketch` / `remove_spline_anchor_rsketch` / `convert_spline_to_anchors_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `spline` (B-spline id); insert: `at` (`[x, y]` or a point id); remove: `anchor` (point id)
- The edit is made on the solved geometry and picks its own ids (`p<n>`), so replay is deterministic.

#### `explode_rassembly`

- Inputs: 1 `Assembly`
- Outputs: 1 `Assembly` (a display copy: only component placements differ)
- Params: `assembly_id`, `factor`, `center`, `axis` (3-vectors or `null`), `directions` (component id to 3-vector), `weights` (component id to number)
- `factor` is recorded as a symbolic parameter when it was a `Var` / `Expr`. Constraints are not re-solved; solving the result moves the components back.

#### Curve and surface edits (`*_redge` / `*_rface`)

`convert_to_bspline_redge`, `convert_to_bspline_rface`, `set_curve_poles_redge`, `move_curve_poles_redge`,
`set_curve_weights_redge`, `insert_curve_knot_redge`, `elevate_curve_degree_redge`, `set_surface_poles_rface`,
`move_surface_poles_rface`, `set_surface_weights_rface`, `insert_surface_knot_rface`, `elevate_surface_degree_rface`,
`rebuild_curve_redge`, `rebuild_surface_rface`.

- Inputs: 1 `Edge` (`*_redge`) or 1 `Face` (`*_rface`), named by `params.input_refs` (a pick from a solid becomes a selection node first)
- Outputs: 1 new `Edge` / `Face` (the input is not changed)
- Params (besides `input_refs` and `tag_prefix`): `poles` (list of points / grid of rows along U), `moves` (`[[index, point], ...]` for a curve, `[[row, column, point], ...]` for a surface; indices 0-based), `weights` (list / grid), `parameter`, `multiplicity`, `direction` (`"U"` / `"V"`), `degree`, `u_degree` / `v_degree` (`null` = unchanged for `elevate_surface_degree_rface`), `pole_count` / `u_pole_count` / `v_pole_count` (`null` = from `tolerance`), `tolerance`. Points are in the node's `context` coordinate system.
- `topo_delta`: the face and its edges (an edge: itself) are `MODIFIED`, derivation `continuation`, each with its input entity as parent, so tags and references follow.
- `inspect_curve_rcurvedata`, `inspect_surface_rsurfacedata`, `sample_curve_rcurvature`, `sample_surface_risocurves` are diagnostic: no node.

#### `make_constrain_*_rsketch`

- Inputs: 1 `Sketch`
- Outputs: 1 updated `Sketch`
- Params: `sketch_id`, `kind`, `targets`, `value`, `constraint_id`, `driving`, `metadata`
- `targets` contains stable target ids, not graph object ids. Examples: `bottom`, `p0`, `bottom.end`, `hole.center`.

#### `make_wire_from_sketch_rwire`

- Inputs: 1 `Sketch`
- Outputs: 1 promoted `Wire`
- Params: `profile`, `sketch`, `require_fully_constrained`, `strict`, `tolerance`, `max_iterations`, `solve_snapshot`, `promotion_map`
- The solver runs inside this promotion step. `solve_snapshot` is evidence for strict replay validation, not a separate graph leaf.

#### `make_face_from_sketch_rface`

- Inputs: 1 `Sketch`
- Outputs: 1 promoted `Face`
- Params: `profile`, `sketch`, `require_fully_constrained`, `strict`, `tolerance`, `max_iterations`, `solve_snapshot`, `promotion_map`
- The promoted face/wire/edges carry `source_sketch`, `sketch_solve`, and sketch entity tags/metadata.

### 14.3 Primitive Solid Source APIs

#### `load_brep_region_rshell`

- Inputs: none
- Outputs: 1 `Shell`
- Params: `path`, `sha256`, `tag_prefix`
- `path` locates a required external `.scadbrep` sidecar; `sha256` identifies
  and verifies the complete artifact before native BREP decoding.

#### `load_brep_region_rsolid`

- Inputs: none
- Outputs: 1 `Solid`
- Params: `path`, `sha256`, `tag_prefix`
- Model JSON does not embed the sidecar bytes. Replay fails closed when the file
  is missing, changed, corrupt, or has the wrong root kind.

#### `make_box_rsolid`

- Inputs: none
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `w` | scalar | width |
| `h` | scalar | height |
| `d` | scalar | depth |
| `bottom_face_center` | `vec3` | placement anchor |

Important:

- 该 source API 在 active `GraphSession` 中展开为 canonical low-level graph ops，不作为 `make_box` node 落入 canonical model JSON
- geometry details such as size and bottom anchor belong in `metadata["geo"]`, not legacy descriptive tags

#### `make_cylinder_rsolid`

- Inputs: none
- Outputs: 1 `Solid`
- Params: `radius`, `height`, `bottom_face_center`, `axis`

#### `make_cone_rsolid`

- Inputs: none
- Outputs: 1 `Solid`
- Params: `bottom_radius`, `top_radius`, `height`, `bottom_face_center`, `axis`

#### `make_sphere_rsolid`

- Inputs: none
- Outputs: 1 `Solid`
- Params: `radius`, `center`

### 14.4 Transform Ops

#### `make_translate_rshape`

- Inputs: 1 shape
- Outputs: 1 shape
- Params: `vector`

#### `make_rotate_rshape`

- Inputs: 1 shape
- Outputs: 1 shape
- Params: `angle`, `axis`, `origin`

#### `make_mirror_rshape`

- Inputs: 1 shape
- Outputs: 1 shape
- Params: `plane_origin`, `plane_normal`

### 14.5 Feature Ops

#### `make_extrude_rsolid`

- Inputs: 1 `Wire` or `Face`
- Outputs: 1 `Solid`
- Params: `direction`, `distance`

#### `make_revolve_rsolid`

- Inputs: 1 `Wire` or `Face`
- Outputs: 1 `Solid`
- Params: `axis`, `angle`, `origin`

#### `make_loft_rsolid`

- Inputs: N `Wire`
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `profile_count` | `int` | number of profiles |
| `ruled` | `bool` | whether ruled loft mode was requested |

#### `make_sweep_rsolid`

- Inputs: 1 profile + 1 path
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `is_frenet` | `bool` | sweep orientation mode |

#### `make_twisted_sweep_rsolid`

- Inputs: 1 profile `Face`
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `axis` | 3-number array | sweep and rotation-axis direction in caller coordinates |
| `origin` | 3-number array | sweep start and a point on the rotation axis |
| `distance` | positive number | axial sweep distance |
| `twist_angle` | number | signed total rotation in degrees |
| `guide_radius` | positive number | internal auxiliary-spine radius |

Replay rebuilds the auxiliary spine deterministically inside the operation. It
does not infer section counts or lower to transient loft nodes.

### 14.6 Boolean Ops

#### `make_union_rsolid`

- Inputs: N `Solid`
- Outputs: 1 `Solid`
- Params base fields:

| Key | Type | Meaning |
| --- | --- | --- |
| `input_count` | `int` | number of input solids |
| `clean` | `bool` | whether post-clean was requested |
| `glue` | `bool` | OCC glue mode flag |
| `tol` | `number | null` | effective fuzzy tolerance |

Notes:

- `output_count` is always 1 for `union_rsolid(...)`.
- If the kernel cannot produce exactly one merged solid, the API raises instead of returning disconnected pieces.
- replay passes recorded `clean`, `glue`, and `tol` back to `union_rsolid(...)`; the tracking builder uses the same `glue` and fuzzy tolerance as the actual boolean builder.

#### `make_cut_rsolid`

- Inputs: base solid + tool solids
- Outputs: 1 `Solid` (wrapped in a single-output node)
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `tool_count` | `int` | number of subtractive tool solids |
| `skip_non_intersecting` | `bool` | whether non-intersecting tools are skipped |

Notes:

- Public `cut_rsolid(...)` defaults this flag to `true` for interactive convenience.
- Graph replay defaults missing `skip_non_intersecting` to `false` so malformed or drifting graphs fail diagnostically instead of silently skipping tools.
- Multi-tool cut preserves the full topology delta chain across all performed tool cuts.

#### `make_intersect_rsolid`

- Inputs: N `Solid`
- Outputs: 1 `Solid` when overlap exists
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `input_count` | `int` | number of intersected solids |

Notes:

- Multi-tool intersect preserves the full topology delta chain across all performed intersection steps.

### 14.7 Detail Feature Ops

#### `make_fillet_rsolid`

- Inputs: 1 source `Solid` plus optional `make_select_redge` nodes
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `radius` | scalar | fillet radius |
| `edge_count` | `int` | number of targeted edges |
| `selected_edges` | `array<TopoRefWithHint>` | explicit edge refs |
| `selected_edge_node_ids` | `array<string>` | primary geo select node refs for QL/index-derived selections |
| `selected_edge_indices` | `array<int>` | legacy index fallback when select nodes are unavailable |
| `selection_query` | `ShapeSelector object` | legacy/fallback serialized QL selector |

#### `make_chamfer_rsolid`

- Inputs: 1 source `Solid` plus optional `make_select_redge` nodes
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `distance` | scalar | chamfer distance |
| `edge_count` | `int` | number of targeted edges |
| `selected_edges` | `array<TopoRefWithHint>` | explicit edge refs |
| `selected_edge_node_ids` | `array<string>` | primary geo select node refs for QL/index-derived selections |
| `selected_edge_indices` | `array<int>` | legacy index fallback when select nodes are unavailable |
| `selection_query` | `ShapeSelector object` | legacy/fallback serialized QL selector |

#### `make_shell_rsolid`

- Inputs: 1 source `Solid` plus optional `make_select_rface` nodes
- Outputs: 1 `Solid`
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `thickness` | scalar | shell thickness |
| `removed_face_count` | `int` | number of faces removed |
| `selected_faces` | `array<TopoRefWithHint>` | explicit face refs |
| `selected_face_node_ids` | `array<string>` | primary geo select node refs for QL/index-derived selections |
| `selected_face_indices` | `array<int>` | legacy index fallback when select nodes are unavailable |
| `selection_query` | `ShapeSelector object` | legacy/fallback serialized QL selector |

### 14.8 Pattern Ops

#### `linear_pattern`

- Inputs: 1 shape
- Outputs: `count` shape instances
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `direction` | `vec3` | translation direction |
| `count` | `int` | number of instances |
| `spacing` | `number` | distance between adjacent instances |

Notes:

- canonical graph does not keep a single `linear_pattern` node
- the pattern must expand into explicit `make_translate_rshape` instance nodes and declare final outputs via `leaf_ids`

#### `radial_pattern`

- Inputs: 1 shape
- Outputs: `count` shape instances
- Params:

| Key | Type | Meaning |
| --- | --- | --- |
| `center` | `vec3` | rotation center |
| `axis` | `vec3` | rotation axis |
| `count` | `int` | number of instances |
| `total_rotation_angle` | `number` | angular coverage of the pattern |

Notes:

- canonical graph does not keep a single `radial_pattern` node
- the pattern must expand into explicit `make_rotate_rshape` / `make_translate_rshape` instance nodes and declare final outputs via `leaf_ids`

### 14.9 Macro / Non-Node Cases

#### `helical_sweep_rsolid`

这不是一个稳定记录节点。

规则：

- 当 `GraphSession` 处于激活状态时，`helical_sweep_rsolid()` 不记录 `helical_sweep`
- 它会显式展开为：
  - `make_helix_redge`
  - `make_wire_from_edges_rwire`
  - `make_face_from_wire_rface`
  - `make_sweep_rsolid` with `is_frenet=true`
- 因此 graph JSON / model JSON 中不应期待存在 `op == "helical_sweep"`

#### `make_segment_redge`

- 这是 `make_line_redge()` 的别名 API
- 记录时仍然是 `op == "make_line"`

## 15. SDF / Scalar Field Status

SDF / scalar field modeling is temporarily removed from the supported public surface.

- `simplecadapi.field` is not exported.
- `make_field_surface_rsolid` is not exported.
- `make_field_surface_rsolid` is not part of `CANONICAL_CORE_OP_SET`.
- New graph/model JSON payloads must not contain `op == "make_field_surface_rsolid"`.
- Historical payloads that contain scalar field nodes should be treated as unsupported until a new SDF contract is designed.

## 16. Replay Semantics

### 16.1 graph replay

`replay_graph(graph)`：

- 逐节点按拓扑序执行
- 使用节点 `op + params + inputs` 恢复几何
- 默认 strict，缺参数、缺输入、未知 op、leaf 无 output、selection cardinality mismatch 都会失败
- 只有调用 `replay_graph(graph, strict=False)` 时才启用 permissive fallback
- 返回 leaf node outputs

### 16.2 model replay

`replay_model_json(json_str)`：

1. 先导入 model payload
2. 直接 replay `graph`
3. 若存在 `leaf_ids`，返回这些显式 leaf ids 对应的 outputs
4. 否则返回 graph leaf outputs

默认 strict，只有调用 `replay_model_json(json_str, strict=False)` 时才启用 permissive fallback。

### 16.3 Output Collection Rule

- 如果未显式指定 leaf ids，最终结果等于 graph 的 leaf node outputs 拼接
- 多输出 node 会把其所有 output slots 依序加入结果

## 17. Adapter Guidance

### 17.1 Strong Recommendations

1. 优先消费 `model.json`
2. 若要做工业 interchange，请直接消费 canonical low-level `graph`
3. 若要恢复参数化，请同时读取 `params`、`param_exprs`、`expression_graph`
4. detail feature 必须按声明顺序解析选择：geo select nodes -> query fallback -> explicit refs -> legacy indices -> hint
5. 不要依赖 `display.summary` 解析业务语义

### 17.2 Tolerances For Consumers

消费端应对以下实现细节保持宽容：

- 数值字段可能表现为整数或浮点数
- `output_slot` 在深层 param 对象中可能是 `0.0`
- `tags` 可能为空
- `semantic_delta` / `topo_delta` 可能缺失
- `selection_query` 是旧 payload / 手写 payload fallback；新 detail selections 应优先产生 geo select nodes

### 17.3 Recommended Minimal Interchange Subset

如果外部系统只需做几何重建，最小可消费集合是：

- `model.schema_version`
- `model.graph`
- 每个 node 的 `op` / `params` / `inputs` / `output_count`
- `leaf_ids`

如果需要稳定 detail feature 选择，还必须消费：

- `selected_edge_node_ids` / `selected_face_node_ids` and their `make_select_*` nodes
- `selected_edges` / `selected_faces`
- `selected_edge_indices` / `selected_face_indices` as legacy fallback
- `selection_query` fallback, when present
- `selector_hint`

## 18. Known Limitations

1. `helical_sweep` 不是独立 stable node，而是宏展开
2. `opaque_callable` field surface 不可 replay
3. `assembly_graph` capability is false; assembly/constraint model JSON fields are currently not emitted
4. `display` 是派生字段，不保证长期稳定
5. composite builtins may expand into multiple low-level nodes, so node count/granularity should not be assumed from public API call count

## 19. Worked Examples

### 19.1 fillet Node Example

```json
{
  "node_id": "node_caf7b43f",
  "op": "fillet",
  "params": {
    "radius": 0.3,
    "edge_count": 2,
    "selected_edges": [
      {
        "graph_id": "graph_24fc9c20",
        "node_id": "node_f7e1ea08",
        "output_slot": 0.0,
        "kind": "EDGE",
        "topo_id": "edge_640974",
        "selector_hint": {
          "kind": "edge",
          "tags": ["edge.left", "role.mounting_edge"],
          "length": 4.0,
          "start": [-2.0, -2.0, 4.0],
          "end": [-2.0, -2.0, 0.0]
        }
      }
    ],
    "selected_edge_node_ids": ["node_select_edge_0", "node_select_edge_1"]
  },
  "inputs": ["node_f7e1ea08", "node_select_edge_0", "node_select_edge_1"],
  "output_count": 1
}
```

### 19.2 extrude Node With Expression Reference

```json
{
  "op": "make_circle_face",
  "params": {
    "center": [0.0, 0.0, 0.0],
    "radius": 2.0,
    "normal": [0.0, 0.0, 1.0]
  },
  "param_exprs": {
    "radius": {
      "expr_id": "var_119b16e4"
    }
  }
}
```

## 20. Summary

可以把当前 JSON interchange 简化理解为：

- `graph` = 唯一真相源的 canonical low-level 图
- `expression_graph` = 参数化依赖图
- `frame_graph` = 工作坐标快照
- `semantic/topology delta` = 语义与拓扑 lineage 补充信息

外部转译适配的主实现建议是：

1. 读 `model.json`
2. 直接使用 `graph`
3. 按本文件的 operation catalog 解释 `params`
4. 对 detail feature 按固定顺序恢复选择对象
5. 在需要参数化恢复时联动 `param_exprs + expression_graph`
