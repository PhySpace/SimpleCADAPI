# 会话回放 Demo（单文件离线）

**打开方式：直接双击 `index.html`**（离线可用、无需服务器；数据、three.js、STL、渲染图全部内联，约 0.9 MB）。

把 `../session_transcript.md`（L 形直角连接件 single-part-modeling 正式化重建）
**忠实回放**成可交互页面：2 轮用户输入、49 次工具调用、9 次角色切换，右侧 three.js
实时渲染最终单实体支架。看点是新旧几何等价对账：体积相对偏差 0.00e+00、包围盒逐位
相同、5 个 `interface.*` FEM 标签面积 rel ≤ 5.3e-7，FCStd 特征树经 CLI 重开验证（该 FreeCAD 导出随转译器移出 SDK 已删除，回放保持当时原样）。

## 重新生成（仓库根目录）

```bash
python3 examples/ap242_gmsh_volume_mesh/demo/build.py
```

构建器与转录格式见 [`examples/demo_kit/`](../../demo_kit/)。
