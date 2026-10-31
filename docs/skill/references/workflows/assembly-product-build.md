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

## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `workflows/assembly-product-build.md` | this page: steps, gates, failure routes |
| `domains/requirement-refinement.md` | step 1: product structure, parts manufactured vs purchased vs standard, motion, delivery |
| `domains/assembly-and-product.md` | placement, connectors, constraints, `scad.use` composition, capture |
| `discipline/assembly-positioning.md` | frames, connectors and constraints: how mating and motion intent is written and checked |

## Read when

| When | File |
| --- | --- |
| step 2: decomposing the product into part and assembly notebooks | `discipline/mechanical-modeling.md` |
| the mechanism uses gears, ring gears, racks, cycloidal discs or bearings | `domains/standard-parts.md` |
| authoring or editing any part or assembly notebook (before the first write) | `docs/guides/notebook-runtime.md` |
| composing notebooks, nested subassemblies, library parts, the cell cache | `docs/guides/notebook-composition-and-cache.md` |
| authoring a custom part (step 4) | `workflows/single-part-modeling.md` |
| writing a part source | `discipline/feature-tree-convention.md` |
| splitting a part or assembly source into cells | `discipline/notebook-cell-design.md` |
| the constraint solve fails or placement is wrong | `discipline/failure-and-repair.md` |
| a validation gate needs a check script | `discipline/geometric-validation.md` |
| defaults for clearances, backlash or walls are needed | `discipline/manufacturing-boundaries.md` |
| capturing the package and exporting (steps 9-10) | `docs/guides/product-export.md`, `domains/export-and-translation.md` |

## Unattended mode

Nothing in this workflow waits for a person except the places below; each binds an artifact in both modes.

| Interactive gate | Unattended replacement |
| --- | --- |
| Step 1: ask about product structure, manufactured vs purchased vs standard, motion, materials, delivery targets | Record each as an assumption in the ledger (`value / evidence / how to change it / the check that would show it wrong`); the structure that the evidence supports wins |
| A part or mate that the request implies but no source supplies (purchased part without a STEP, unstated mate intent or degrees of freedom) | Record the blocker in the report; build only what the evidence supports; a stand-in is labelled as an assumption and never reported as the real part. Never invent the missing input |
| Step 2: a choice between decompositions or subassembly boundaries | Take the one that meets the stated requirements and is easier to change; record the other in the plan |
| Step 4: each custom part's own consent and verifier gates (`workflows/single-part-modeling.md`) | Run the unattended rows of that workflow; every part still passes its single-part gates before assembly |
| Step 6: unknown joint type or ground choice | Record the choice and its evidence in the ledger; ground only what the evidence says is fixed |
| Step 8: a person looks at placement renders | Look yourself: name the views, what you looked for, quote the observation; the QL placement checks still run |
| A second reviewer of the assembly | A fresh-context checklist pass quoting observations (subagent if offered); otherwise the report says the review was not independent |
| Constraint failure or placement error twice for the same cause | Change the constraint graph or the datum, or redefine the check in the report; do not retry (`discipline/failure-and-repair.md`) |
| Closing message to the person | `report.md`: assumptions, what was built and omitted, checks run and not run, reproduce commands (`discipline/operating-modes.md`) |

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
   **Unattended:** record each as an assumption in the ledger.
2. **Decompose the product** (`discipline/mechanical-modeling.md`): one part
   notebook per physical part, one assembly notebook; group functional units
   as nested subassembly notebooks that are placed, reasoned about, or
   repeated as units (`references/docs/guides/notebook-runtime.md`).
   **Unattended:** pick the decomposition that meets the requirements and is easier to change; record the other.
3. **Select standard components first** (`domains/standard-parts.md`)
   when the mechanism uses gears, ring gears, racks, cycloidal discs, or
   bearings: never hand-model a standard shape. Compute the kinematics
   explicitly — center distance from tooth counts and module, backlash,
   ratios — and derive bearing seats and gear seats from the selected
   components by measurement (QL queries, not assumed dimensions).
4. **Author each custom part** (shafts, housings, carriers, spacers,
   connectors) via `single-part-modeling.md` (which mandates
   `discipline/feature-tree-convention.md` block structure and the cell and
   `Var` rules of `discipline/notebook-cell-design.md`); attach interface
   connectors on leaf parts (`add_connector_rpart`,
   `make_placement_connector_rconnector`, ...) at mating datums
   (`discipline/assembly-positioning.md`).
   **Unattended:** use the unattended rows of `workflows/single-part-modeling.md`; each part still passes its gates.
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
   **Unattended:** record the joint and ground choices with their evidence.
7. **Solve and read the evidence** (`solve_assembly_constraints_rassembly`,
   `inspect_assembly_constraints_rconstraintreport`,
   `measure_constraint_residual_rconstraintresidual`): constraint status and
   residuals. Nested mechanisms must solve their own constraints before the
   parent consumes their public connectors.
8. **Validate positioning**: component placements realized as intended;
   mating faces flush or offset as specified; axes aligned. Use QL queries on
   the solved assembly, not eyeballing.
   **Unattended:** look at the renders yourself and quote what you saw.
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
  **Unattended:** the same cause twice means change the design or redefine the check in the report.

## Deliverables

Part and assembly notebook paths, package path, constraint report, residuals,
positioning checks actually run, assumptions.
**Unattended:** these go in `report.md` (`discipline/operating-modes.md`).

**Required reading before authoring or editing any part source in this
workflow:** `discipline/feature-tree-convention.md` — the block-structured
sketch → basic body op → bool → modifier convention, its mandatory boundary
comments, and the sketch/geometry/primitive tier rules. Every part source
is a marimo notebook, one block per cell
(`references/docs/guides/notebook-runtime.md`): run it with `sca run`, and
load its product from verification scripts with
`simplecadapi.runtime.run_notebook(...)`.
