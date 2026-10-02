# Engineering Guides

- [STEP BREP Reverse Engineering](step-brep-reverse-engineering.md): full workflow from STEP inspection, geometric fingerprint analysis, feature-tree inference, and candidate iteration to geometric point-set, BREP topology, parameter history, and model replay acceptance.
- [Reconstruction Agent Test Prompt](reconstruction-agent-test-prompt.md):
  compact, versioned run contract for controlled STEP reconstruction trials.
- [Reconstruction Agent Strategy](reconstruction-agent-strategy.md):
  advisory inspection, feature-selection, Sketch, Boolean, and iteration tactics.
- [Notebook Runtime and Product Build Workflow](notebook-runtime.md):
  models as marimo notebooks, `sca run`, `scad.use` composition, the cell
  cache, `@part`/`@assemble` library parts, `.scadpkg` delivery,
  FreeCAD/AP242 targets, and optional Gmsh volume meshing.

The corresponding runnable module and examples live in:

```text
src/simplecadapi/inspect/brep/
```
