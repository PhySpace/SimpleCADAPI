# Skill Documentation Structure

The skill is task-routed: `SKILL.md` (one level up) is the router, and everything here is loaded in batches the router and the
workflows name. The contract the pages follow (sizes, headers, read sets, unattended mode, checks) is `skill-design.md`
in the repository's `docs/` folder; `python tools/skillbuild.py --check` enforces it.

```text
SKILL.md                         router: mode, routes with read sets, always-on rules
references/discipline/core-rules.md, operating-modes.md   read on every route
references/workflows/<name>.md   one lifecycle: Read now / Read when / Unattended mode
references/workflows/<name>/     the role or stage pages of a long workflow
references/domains/<name>.md     what the SDK offers for a kind of task
references/discipline/<name>.md  reasoning, invariants, rules
references/docs/guides/          how the runtime works
references/docs/api|stdlib|core/ exact signatures (generated; never edited by hand)
```

Load top-down and only what the task triggers; read each batch in one parallel request.

## Workflows

| Workflow | Scenario |
| --- | --- |
| `workflows/single-part-modeling.md` | one physical part from brief to validated solid (outline: roles, role switches, export, failure routes) |
| `workflows/assembly-product-build.md` | multi-part product or mechanism: connectors, constraints, package capture |
| `workflows/step-reconstruction.md` | editable rebuild from a target STEP with tiered acceptance |
| `workflows/scan-reconstruction.md` | rebuild from a mesh, point cloud or photos: what the SDK supports and what it does not |
| `workflows/drawing-reconstruction.md` | editable rebuild from vector-PDF dimensions (outline; stage pages in `workflows/drawing-reconstruction/`) |
| `workflows/engineering-drawing.md` | GB engineering drawing (DXF) from validated geometry |
| `workflows/export-and-translation.md` | downstream formats from a validated package |

Stage and role pages of the long workflows:

| Page | Read when |
| --- | --- |
| `workflows/single-part-modeling/requirements-template.md` | Single-Part Modeling: REQUIREMENTS.md template |
| `workflows/single-part-modeling/role-1-ask-bindings.md` | Role 1 (interactive mode) is about to send its batched ask round. |
| `workflows/single-part-modeling/role-1-requirements.md` | Single-Part Modeling: Role 1, Requirement Confirmer |
| `workflows/single-part-modeling/role-2-plan.md` | Single-Part Modeling: Role 2, Master Planner |
| `workflows/single-part-modeling/role-3-host-bindings.md` | Role 3 starts a stage (the hypothesis loop and the TODO state machine for the Verifier Planner). |
| `workflows/single-part-modeling/role-3-verifier.md` | Single-Part Modeling: Role 3, Verifier Planner |
| `workflows/single-part-modeling/role-4-build.md` | Single-Part Modeling: Role 4, Detail Modeling Planner & Builder |
| `workflows/single-part-modeling/verifier-contract-patterns.md` | Role 3 selects the checks for a stage. |
| `workflows/drawing-reconstruction/role-1-drawing-confirmer.md` | Drawing Reconstruction: Role 1, Drawing Requirement Confirmer |
| `workflows/drawing-reconstruction/role-2-master-planner.md` | Drawing Reconstruction: Role 2, Master Planner |
| `workflows/drawing-reconstruction/role-3-verifier-planner.md` | Drawing Reconstruction: Role 3, Verifier Planner |
| `workflows/drawing-reconstruction/role-4-detail-builder.md` | Drawing Reconstruction: Role 4, Detail Modeling Planner & Builder |
| `workflows/drawing-reconstruction/role-5-exporter.md` | Drawing Reconstruction: Role 5, Exporter |
| `workflows/drawing-reconstruction/roundtrip-acceptance.md` | Drawing Reconstruction: Roundtrip Acceptance |

## Domains

| Page | Read when |
| --- | --- |
| `domains/addon-development.md` | you create, publish, install, update or remove a SimpleCADAPI addon (`sca-addon.toml`), or decide whether a capability is an addon or SDK work. |
| `domains/assembly-and-product.md` | the deliverable has more than one physical part, repeated instances, nested subassemblies, motion semantics, or a `.scadpkg` package (details under "Use when"). |
| `domains/curve-surface-editing.md` | an existing Edge or Face must be reshaped by its control points, weights, knots or degree, refitted, or sampled for a curvature comb / isocurves. |
| `domains/drawing-inspection-evidence.md` | a section view of the drawing must be verified against the rebuilt model, a DIM ledger row needs its `measurement_contract`, or the roundtrip evidence (annotations, reviews, coverage) is built or checked. |
| `domains/drawing-inspection.md` | a vector-PDF engineering drawing must be parsed into tiered evidence, or a rebuilt model is read back for the roundtrip. |
| `domains/editor-collaboration.md` | a person has the code-first editor open (`sca edit`) and you edit the same notebooks (a selection, a cell reference or a tuned value arrives). |
| `domains/editor-gui-features.md` | a person made features with the editor's buttons (`# gui:` cells, `scad.ref` selections, workplanes, canvas sketches), or you run the same operations with `sca feature` / `sca sketch`. |
| `domains/engineering-drawing.md` | a validated part or product needs a GB-standard drawing sheet (DXF + PNG). |
| `domains/export-and-translation.md` | a validated `.scadpkg` must be delivered as STEP, STL, OBJ, MJCF or an editable external CAD document. |
| `domains/part-modeling.md` | the deliverable is one physical single-solid part, or an existing part source needs a geometry edit (Role 4 of `workflows/single-part-modeling.md`). |
| `domains/requirement-refinement.md` | every task starts here: any modeling, assembly, reconstruction, or export request is refined into a brief first, and whenever inputs conflict, are ambiguous, or mix modalities. |
| `domains/sketch-and-features.md` | the part's controlling dimensions are geometric constraints, or an editable, constraint-driven profile is requested (sketch tier profiles and paths). |
| `domains/standard-parts.md` | the request names gears, ring gears, racks, cycloidal discs or ball bearings, or a mechanism built from them (details under "Use when"). |
| `domains/step-inspection.md` | the input is an existing `.step`/`.stp` file and you need facts out of it, or a reconstruction candidate must be compared against a target STEP (details under "Use when"). |

## Discipline

| Page | Read when |
| --- | --- |
| `discipline/assembly-positioning.md` | you choose frames, connectors, placements or constraints for mating and motion, or placement comes out wrong after solving. |
| `discipline/core-rules.md` | every task, in the first batch (the router lists it). These are the rules that hold in every workflow and both modes. Each has an ID so other pages and reviews can cite it (`core-rules R6`). |
| `discipline/datums-and-coordinate-systems.md` | before the first primitive of a part or assembly, when choosing an origin, base plane or up axis, or when placing imported or factory geometry. |
| `discipline/failure-and-repair.md` | a build, solve, export or validation step fails, or the same check has failed twice. |
| `discipline/feature-ordering.md` | you plan the order of operations of a part, a fillet or chamfer fails, or you pattern a feature or loft sections. |
| `discipline/feature-tree-convention.md` | you author or edit any part source (every workflow): what a feature block is, its header and name. |
| `discipline/geometric-validation.md` | you write or run checks on a model: validity and volume gates, selection evidence before a fillet or chamfer, spec-driven measurements, replay, or what to report as having run. |
| `discipline/manufacturing-boundaries.md` | you apply default dimensions, or the request touches manufacturability, tolerance, strength or process claims. |
| `discipline/mechanical-modeling.md` | you choose a construction strategy or decompose a mechanical part or product before selecting SimpleCADAPI operations. |
| `discipline/notebook-cell-design.md` | Discipline: Notebook Cell Design |
| `discipline/operating-modes.md` | at the start of every task (the router sends you here), and again whenever a gate says to ask or to wait for a person. |
| `discipline/requirement-and-cad-brief.md` | Role 1 (or any brief-writing step) starts: prose, images or drawings are being turned into a brief, or evidence conflicts. |
| `discipline/verifier-scripts.md` | Role 3 writes the executable check for a stage, or any task needs a script that measures a finished model against the specification. |

## Guides and references

| Page | What |
| --- | --- |
| `docs/guides/README.md` | Engineering Guides |
| `docs/guides/notebook-composition-and-cache.md` | Notebook Composition and the Cell Cache |
| `docs/guides/notebook-runtime.md` | Notebook Runtime and Product Build Workflow |
| `docs/guides/product-export.md` | Product Package Export and Downstream Targets |
| `docs/guides/reconstruction-agent-strategy.md` | Reconstruction Agent Strategy |
| `docs/guides/reconstruction-agent-test-prompt.md` | Reconstruction Agent Test Contract |
| `ql-playbook.md` | how QL selection works, with the rules |
| `ql-recipes.md` | worked selection recipes |
| `scadpkg-format.md` | the `.scadpkg` consumer spec |
| `SDK_OVERVIEW.md` | package map |
| `inspect/brep-reverse-engineering.md` | normative BREP inspection guide |

## Authoring rules

- A page has one job and at most 300 lines. A rule is stated once, with its reason; other pages link to it.
- Domain pages say what a capability owns and which API pages to read; they do not restate signatures.
- Workflow pages compose domains and discipline; they never duplicate discipline content.
- Every workflow has `Read now`, `Read when` and `Unattended mode`, with one unattended row for every gate that asks a person.
- Every path written in a page must exist in the packaged skill.
- Reading an API page is an action with an output: note the signature, return type and documented failures before the
  first call. Non-SDK dependencies (Gmsh, CalculiX, VTK, FreeCAD scripting) are not covered by SDK pages.
