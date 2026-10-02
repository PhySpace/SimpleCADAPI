# Workflow: Assembly and Product Build

Compose a multi-part product with explicit placement, connectors, and
constraints; run it as a notebook and capture the canonical package.

## Goal and scope

Use for products with more than one physical part, repeated instances, nested
subassemblies, motion semantics, or product package delivery — including
mechanisms composed of standard-library components (gearboxes, reducers,
rack drives, cycloidal drives): standard-part usage lives here. Not for
monolithic parts (`single-part-modeling.md`) or export-only requests
(`export-and-translation.md` runs from an existing package).

## Task decomposition

```yaml
goal: solved assembly captured as one .scadpkg
primary_domain: assembly-and-product
required_domains:
  - requirement-refinement
  - part-modeling            # every component is still authored as a part
  - assembly-and-product
optional_domains:
  - sketch-and-features
  - standard-parts
  - export-and-translation
artifacts:
  - one part notebook per physical part
  - one assembly notebook composing them with scad.use
  - connectors on leaf parts; public declarations on subassemblies
  - solved AssemblyBuildResult and package
validation_gates:
  - each part passes single-part gates before assembly
  - constraint report and residuals as expected
  - grounded root is the intended fixed component
  - package validation passes
  - stdlib mechanisms: module/backlash/center-distance consistency per
    mesh; bearing seats match measured shaft/housing diameters
repair_routes:
  - constraint unsolved/conflicting -> assembly-and-product (constraint graph)
  - placement wrong -> assembly-positioning discipline (datum/connector frames)
  - part invalid -> back to part-modeling for that part
```

## Steps

1. **Refine the requirement** (`domains/requirement-refinement.md`): product
   structure, which parts are manufactured vs purchased vs standard, motion
   requirements, materials, delivery targets.
2. **Decompose the product** (`discipline/mechanical-modeling.md`): one part
   notebook per physical part, one assembly notebook; group functional units
   as nested subassembly notebooks that are placed, reasoned about, or
   repeated as units (`references/docs/guides/notebook-runtime.md`).
3. **Select standard components first** (`domains/standard-parts.md`)
   when the mechanism uses gears, ring gears, racks, cycloidal discs, or
   bearings: never hand-model a standard shape. Compute the kinematics
   explicitly — center distance from tooth counts and module, backlash,
   ratios — and derive bearing seats and gear seats from the selected
   components by measurement (QL queries, not assumed dimensions).
4. **Author each custom part** (shafts, housings, carriers, spacers,
   connectors) via `single-part-modeling.md` (which mandates
   `discipline/feature-tree-convention.md` block structure); attach interface
   connectors on leaf parts (`add_connector_rpart`,
   `make_placement_connector_rconnector`, ...) at mating datums
   (`discipline/assembly-positioning.md`).
5. **Compose the assembly** in the assembly notebook: bring each part or
   subassembly notebook in with `scad.use("part.py", **overrides)` (or call a
   `@scad.part` / `@scad.assemble` library builder inside a cell);
   `make_assembly_rassembly` + `add_component_rassembly` with placements;
   expose subassembly interfaces with `set_public_connector_rassembly`
   (declaration only — no offsets).
6. **Express mating and motion as constraints**
   (`discipline/assembly-positioning.md`): fixed for the root, revolute /
   prismatic for motion, gear / rack-pinion / belt for drivetrain relations,
   ground the components that are truly fixed (at least one).
7. **Solve and read the evidence** (`solve_assembly_constraints_rassembly`,
   `inspect_assembly_constraints_rconstraintreport`,
   `measure_constraint_residual_rconstraintresidual`): constraint status and
   residuals. Nested mechanisms must solve their own constraints before the
   parent consumes their public connectors.
8. **Validate positioning**: component placements realized as intended;
   mating faces flush or offset as specified; axes aligned. Use QL queries on
   the solved assembly, not eyeballing.
9. **Capture** (`domains/assembly-and-product.md`):
   `sca run <assembly>.py --out out/<product>.scadpkg`, or
   `capture(run.definition, ...)` from `run_notebook` — the single delivery
   boundary.
10. **Export** (`domains/export-and-translation.md`) only after validation.

## API pages to read

`make_part_rpart`, `add_connector_rpart`, `make_placement_rplacement`,
`identity_placement_rplacement`, `make_assembly_rassembly`,
`add_component_rassembly`, `place_component_rassembly`,
`set_public_connector_rassembly`, the `add_*_constraint_rassembly` family,
`ground_component_rassembly`, `solve_assembly_constraints_rassembly`,
`inspect_assembly_constraints_rconstraintreport`,
`measure_constraint_residual_rconstraintresidual`, `part`, `assemble`,
`capture`, `use`, `run_notebook`, plus
`references/docs/guides/notebook-runtime.md` in full before writing or
composing notebooks.

## Validation gates

- Constraint report shows every constraint satisfied, residuals within
  tolerance.
- At least one grounded component, and only the truly-fixed ones grounded;
  moving a component never transforms its internal solid.

- Public connector frames resolve through nested placements; changing a
  public declaration changes the definition `content_hash`.
- `validate_product_package` (via capture) passes.

## Failure routes

- Dual-fixed external constraint on a nested subassembly → solve the nested
  mechanism internally first; the parent consumes only public connectors.
- Duplicate component ids / cycles / invalid placements → fix the structure.
- Placement systematically wrong → datum or connector frame error; see
  `discipline/assembly-positioning.md`.

## Deliverables

Part and assembly notebook paths, package path, constraint report, residuals,
positioning checks actually run, assumptions.

**Required reading before authoring or editing any part source in this
workflow:** `discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
