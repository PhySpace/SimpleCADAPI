# Task Domain: Assembly and Product

Compose multi-part products with explicit placement, connectors, and
declarative constraints; compose notebooks with `scad.use`, build durable
definitions (notebook products, `@part`/`@assemble` library parts), and
deliver `.scadpkg` packages.

## Use when

- The deliverable contains more than one physical part, repeated instances, or
  nested subassemblies.
- Parts must be positioned by interfaces (axes, faces, datum connectors) rather
  than raw transforms.
- The product needs motion semantics: hinges, sliders, gear meshes, rack and
  pinion, belt drives, or loop-closing joints.
- The build needs durable definitions, notebook composition, or a canonical
  delivery package.

## Do not use

- Monolithic single-body manufacturing intent: fuse with `union_rsolid` in
  `domains/part-modeling.md`.
- Export or translation decisions: they branch from the package in
  `domains/export-and-translation.md`.
## Structure model

- `Part` wraps exactly one `Solid` plus identity and optional material
  (`make_part_rpart`, `assign_material_rpart`, `make_material_rmaterial`).
- `Assembly` holds component instances with placements
  (`make_assembly_rassembly`, `add_component_rassembly`,
  `place_component_rassembly`, `make_placement_rplacement`,
  `identity_placement_rplacement`).
- Connectors live on leaf parts (`add_connector_rpart`,
  `make_placement_connector_rconnector`, `make_edge_connector_rconnector`,
  `make_face_connector_rconnector`, `make_vertex_connector_rconnector`).
- Public connectors are interface declarations, not cloned connectors
  (`set_public_connector_rassembly`): they record a public id plus a direct
  child component/connector reference, store no offset, and expose one nesting
  level at a time.
- Declarative constraints express mating and motion
  (`add_fixed_constraint_rassembly`, `add_revolute_constraint_rassembly`,
  `add_prismatic_constraint_rassembly`, `add_gear_constraint_rassembly`,
  `add_rack_pinion_constraint_rassembly`, `add_belt_constraint_rassembly`).
- `ground_component_rassembly` fixes components; `unground_component_rassembly`
  releases them. The solver requires **at least one** grounded component to
  seed placements; multiple grounded components are accepted but may
  overconstrain or fail residuals — ground exactly the components that are
  truly fixed in the product's frame.

## Product boundaries

- Every product is a notebook (`docs/guides/notebook-runtime.md`): a part
  notebook's product is a `Part`, an assembly notebook's product an
  `Assembly`, each with the notebook's id. An assembly notebook takes its
  parts and subassemblies from child notebooks with
  `scad.use("child.py", **overrides)`; each child product carries its own
  definition and is referenced, not copied.
- `@scad.part` (one physical single-solid part) and `@scad.assemble` (an
  assembly with explicit external definitions) build reusable library parts
  in plain modules. Each call builds in a session of its own, so it may be
  made inside a notebook cell or another builder.
- The notebook runtime caches cells, not parts or solves: an assembly is
  solved strictly whenever its cell runs. Inspect the solve with
  `inspect_assembly_constraints_rconstraintreport` and
  `measure_constraint_residual_rconstraintresidual`.

## Canonical delivery

- `capture(result, "out/product.scadpkg")` is the single public package write
  boundary (its two required arguments are positional).
- The package embeds the definition closure, evaluated scene, canonical
  occurrence graph, feature graphs, source snapshots, topology, connectors,
  constraints, and materials.
- Package capture and `validate_product_package` enforce the v3 package
  invariants; `solve_assembly_constraints_rassembly` returns the solved
  assembly with its constraint report. Never hand-author package payloads.

## API groups

Read the exact page under `references/docs/api/` for every API used, plus
`references/docs/guides/notebook-runtime.md` completely before writing or
composing notebooks.

- Notebook runtime: `use`, `run_notebook`, `NotebookRun`, `CellReport`,
  `NotebookConfig`, `sca run` CLI.
- Product build: `part`, `assemble`, `file_input`, `PartBuildResult`,
  `AssemblyBuildResult`.
- Packages: `capture`, `CaptureResult`, `ProductPackage`,
  `build_product_package`, `read_product_package`, `load_product_package`,
  `validate_product_package`.

## Validation gates

- Placement semantics: moving a component changes placement only; the part's
  internal solid is never transformed.
- Residuals within tolerance after solving; grounded root is the intended
  fixed part.
- Public connector frames resolve through nested placements; changing a public
  declaration changes the definition's content hash.

## Failure modes

- External dual-fixed constraints on nested subassemblies: the nested mechanism
  must expose and solve its own constraints through public connectors before the
  parent consumes them; a public declaration never makes an internal component
  movable by itself.
- Duplicate component ids, cycles in subassembly references, or invalid
  placements are rejected; fix the structure, not the symptom.
- A stale or suspicious cell cache is never repaired by hand: rerun with
  `sca run --no-cache` and report the difference.
