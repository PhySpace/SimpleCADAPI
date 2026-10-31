# Drawing Reconstruction: Role 4, Detail Modeling Planner & Builder

Part of `workflows/drawing-reconstruction.md`. Load when a stage's modeling starts.

## Role 4 — Detail Modeling Planner & Builder

Starts only after the stage's verifier contract and executable check exist.

1. Read the contract, then choose construction from the geometry: profile
   and sketch first when they control the shape (constrained sketches,
   promotion, `extrude/revolve/loft/sweep_rsolid`); documented primitives
   when they map directly; named feature solids combined deliberately with
   `union/cut/intersect_rsolid` (positive overlap, tool overshoot); patterns
   only after one representative feature is proven; topology-sensitive
   features (fillet/chamfer/shell) last. The ladder expresses intent — it
   is not an API whitelist; read the exact API page before every first
   call.
2. Name every construction step for its part role or feature
   (`mounting_base`, `port_bore_tool`, `front_flange`), never its creation
   order. Attach `role.*` / `feature.*` / `tool.*` tags; numeric facts in
   metadata, not tags.
3. Probe the construction on minimal solids before editing the part source;
   print types, counts, volumes, bounds as the contract requires; append
   `Hypothesis / Result / Adopted` rows to `BUILD_PLAN.md`.
4. Edit the part source with keyword arguments, named parameters, FTC block
   structure, and boundary comments; selection cards before every
   fillet/chamfer.
5. Run the source and hand the stage geometry to Role 3. The stage passes
   only when all assertions, measurements, and required visual verdicts
   pass. On failure: no weakened checks — determine the owner (contract or
   model), open a `repair:` item, repeat the loop.

<!-- skill:if omp -->

### Host binding: persistent REPL (omp)

Hypothesis construction lives in `eval` (names survive across calls); the
real source run lives in bash. Close `S<n> model` only after the source run
completes, then start `S<n> run verifier` for Role 3.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop (opencode)

Run incremental construction hypotheses as numbered scripts under
`<part-dir>/hypotheses/` via `bash`; carry geometry between probes by
writing files (pickle/JSON/`capture`) and reloading, or by re-materializing
from the part source. The source run itself also runs in `bash`. A modeling
success message is never the verification result.

<!-- skill:endif -->


**Unattended:** the user's explicit review is not available. Use the fresh-context check of the standing discipline
(`workflows/drawing-reconstruction.md`), store its identity, quoted observations and reviewed-file hashes, and list it
as not independent in the report; the visual gate stays pending until that written verdict exists.
<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: modeling execution and independent image review

Run the part source with the available execution tool and preserve the stage's
verification outputs. For image judgments, use an available isolated reviewer
with the render paths and written criteria, or the user's explicit review when
no such tool exists. The context that generated the image cannot provide its
own acceptance verdict. Store reviewer identity, result and reviewed artifact
hashes; lack of a reviewer leaves the visual gate pending.

<!-- skill:endif -->
