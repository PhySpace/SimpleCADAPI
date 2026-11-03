# Discipline: Core Rules

**Read when:** every task, in the first batch (the router lists it). These are the rules that hold in every workflow and
both modes. Each has an ID so other pages and reviews can cite it (`core-rules R6`).

## Modelling rules

**R1. Refine before you model.** Turn the request into a brief first (`domains/requirement-refinement.md`). Geometry
before a brief is rework.

**R2. Keyword arguments.** Every documented public API and stdlib function takes keyword arguments. The one exception is
the durable export call `capture(result, path)`, whose two required arguments are positional.

**R3. A model is a marimo notebook** with a `[tool.simplecadapi]` header (`docs/guides/notebook-runtime.md`): one part per
notebook; one assembly notebook per product, composing children with `scad.use(...)`; parameters live in the notebook that
consumes them. Cell boundaries, `_private` names and `var()` follow `discipline/notebook-cell-design.md`; block structure
and the mandatory header `# ---- feature: <slug> (<role>) ----` follow `discipline/feature-tree-convention.md`. Read both
before writing any cell.

**R4. Sketch first.** 2D profiles and planar paths go through the sketch API; primitives only when the shape is entirely
the basic form.

**R5. Booleans** (`union_rsolid`, `cut_rsolid`, `cut_rsolid_list`, `intersect_rsolid`) accept mixed inputs. Union and
intersect return exactly one `Solid`; `cut_rsolid` returns one `Solid`, or the pieces (`list[Solid]`, centroid order)
when the cut splits the body (`on_split="error"` refuses instead); `cut_rsolid_list` always returns a list. Union defaults to `glue=False` with a conservative scale-relative tolerance and fails explicitly when
it cannot produce one merged solid.

**R6. Topology is enumerated through QL only.** Plural getters (`get_edges`, `get_faces`, `get_wires`, `get_vertices`,
`get_solids`, `get_inner_wires`) accept only an index; the no-argument list form raises. Enumerate, count and measure via
`ql.<kind>().resolve(shape)`; filter with QL predicates and `take`/`exactly`; never build a selection by looping over a
list and indexing it. An indexed pick is for an intentional, named choice. Details: `ql-playbook.md`.

**R7. Tags.** `apply_tag(shape=..., tag=...)` is local: it never propagates downward. `list_tags(shape=...)` inspects.
Numeric facts go in metadata, never in tags.

**R8. The notebook file is the only source.** `.scadpkg` is generated from it (`sca run product.py --out
out/product.scadpkg`, or `capture(result, "out/product.scadpkg")`) and is never read back as a source. `@scad.part` /
`@scad.assemble` are for reusable library parts in plain modules.

**R9. Inspection is diagnostic.** `simplecadapi.inspect.brep` and `simplecadapi.inspect.drawing` are rejected inside
`GraphSession`; produce or export the geometry first, inspect outside.

**R10. Standard parts first.** Before hand-modelling a gear, ring gear, rack, cycloidal disc or bearing, check
`scad.std.gear` / `scad.std.bearing`.

**R11. Run with `sca run`;** `sca edit` opens the editor for a person. Never enable marimo's
`[tool.marimo.runtime] cache_cells`, never commit `__marimo__/`.

**R12. Manage the project like software.** Put the workspace under git from the first file; commit at verified milestones
(a passed verification, not a clock) with messages that say what changed and why; use a branch per design direction when
alternatives are on the table. `__marimo__/`, `.sca-editor/` and `out/` go in `.gitignore`.

**R13. An API that is not on its page does not exist.** Before the first call of any API read its exact page
(`docs/api/<name>.md`, `docs/stdlib/<name>.md`, `docs/core/<type>.md`) in one batch with the others for that step. Never
read the whole index.

## Process rules

**P1. Gates bind artifacts.** A gate passes only when its named artifact exists: printed QL facts, targeted measurements,
named rendered views, completed brief fields. A feeling of success is not a result.

**P2. Resolve a blocking item before any geometry.** Ask once, batched (interactive), or record it as an assumption with
its evidence (unattended; `discipline/operating-modes.md`). Proceeding with neither is the failure, not the asking.

**P3. Serial phases.** Do not build later-phase artifacts early. After an interruption, re-ground from the owning
artifact (source file, brief), not from conversation memory.

**P4. Build and check in small steps.** Each major step prints small QL-derived facts; never print whole solids or model
objects.

**P5. Repair the owner.** Fix the named parameter, the brief field or the upstream selection, never the downstream
symptom. Candidate-by-parameter enumeration loops are diagnosis debt (`discipline/failure-and-repair.md`).

**P6. A failed check closes by changing the design, or by redefining the check in the open** (with the person, or in the
report when unattended), never by weakening or deleting it.

## Boundaries

- `.scadpkg` is the durable product; STL/OBJ/MJCF are point-in-time exports, never sources.
- Model JSON is the replay contract for `GraphSession` flows; never hand-author payloads.
- No claim of strength, fatigue, thermal, vibration, tolerance or regulatory fitness without the analysis run.
