# Single-Part Modeling: Role 4, Detail Modeling Planner & Builder

Outline: `workflows/single-part-modeling.md`.

## Role 4 — Detail Modeling Planner & Builder

Role 4 starts only after Role 3's current-stage verifier contract and
executable check exist. It owns the detailed construction of the current
stage, not the acceptance definition.

For the current stage:

1. Read the verifier contract, then choose a construction strategy from the
   geometry and the controlling dimensions. The categories below are a design
   ladder, **not an API whitelist**: select the operations that express the
   current stage's design intent, then read the exact documentation page for
   every operation before its first call. A method absent from its page does
   not exist.

   - **Profile and sketch first when they control the shape.** Analyze the
     required 2D sections, symmetry, datum planes, and dimensional relations.
     Use `make_sketch_rsketch` with the applicable `constrain_*` APIs and
     `inspect_sketch_rsketchresult` when a constrained sketch carries design
     intent; promote it through `make_wire_from_sketch_rwire` or
     `make_face_from_sketch_rface`. Build solids from that intent with
     `extrude_rsolid`, `revolve_rsolid`, `loft_rsolid`, `sweep_rsolid`, or a
     helical sweep when the feature is genuinely helical. A closed profile is
     preferred when its parameters directly represent the requirement.
   - **Primitives are an alternative for genuinely regular base forms.** Use a
     box, cylinder, cone, sphere, or other documented primitive when it maps
     directly to the controlled form; do not force a sketch only because one
     exists. Keep the controlling dimensions as named parameters either way.
   - **Build named feature solids, then combine them deliberately.** Start
     from a named base solid, create each additive boss/rib/flange or
     subtractive bore/pocket/opening as a separately named solid or tool, then
     use `union_rsolid`, `cut_rsolid`, or `intersect_rsolid` to obtain the next
     single Solid (a cut that splits the body returns its pieces as a list;
     a Part holds one solid, so one Part per piece in an Assembly when that is the design). Repeat construct-feature -> Boolean -> verify for each
     required feature group; ensure intentional positive overlap for unions
     and tool overshoot for cuts. Do not assemble an opaque final shape in one
     expression.
   - **Use advanced features only after the prototype feature is proven.**
     Validate one representative feature before `linear_pattern_rsolidlist` or
     `radial_pattern_rsolidlist`; use documented transforms or mirrors for
     symmetry. Apply `fillet_rsolid`, `chamfer_rsolid`, `shell_rsolid`, and
     similar topology-sensitive features after their supporting geometry and
     selectors are stable.
   - **Use surface construction when the requirement is surface-led.**
     Consider documented ruled, patch, Bezier, Gordon, cylindrical, trimmed,
     sewn, or lofted surfaces; turn a closed, valid shell into a Solid only
     when that is the required topology. Do not approximate a freeform or
     transition surface with arbitrary primitives merely because booleans are
     familiar.

2. Name every meaningful construction step before it is used: source variables,
   helper functions, exposed parameters, and tags must identify the part role
   or feature rather than its creation order. Prefer names such as
   `mounting_base`, `port_bore_tool`, `front_flange`, and
   `feature.mounting_bore` over `shape2`, `cut1`, or numeric topology indexes.
   Attach semantic tags with `apply_tag(shape=..., tag=...)`, inspect them with
   `list_tags(shape=...)`, and use tag-aware QL selection where later features
   or verification need stable intent. Use `role.*`, `feature.*`, and `tool.*`
   namespaces; keep numeric facts in metadata rather than tags.

3. Use small hypothesis code snippets or probes in the available execution
   environment to test the proposed construction sequence on minimal solids.
   Print types, counts, volumes, bounds, tag/selection cards, and other facts
   required by the verifier contract. Adopt an operation only when its evidence
   shows that it can produce the required shape. Append
   `Hypothesis: ... / Result: ... / Adopted: ...` under the current stage in
   `BUILD_PLAN.md`.
4. Edit the part source only after the operation hypotheses pass. Use keyword
   arguments, named parameters, role/feature/tool tags, and QL fact prints;
   include selection cards before every fillet/chamfer.
5. Run the source and hand the resulting stage geometry to Role 3. Role 3
   executes the exact prepared verification script. The stage passes only when
   all assertions, measurements, fit/access checks, and required visual
   verdicts pass. A visual verdict comes from the isolated reviewer contract
   planned by Role 3.
5. On failure, do not weaken the check. Determine whether the verifier
   contract or the model owns the defect, add a `repair:` TODO to that owner,
   and repeat Role 3/4 for the same stage. Start the next stage only after the
   current stage's `model` and `run verifier` items are both complete.

**Unattended:** the visual verdict is the fresh-context check Role 3 planned, with the observation quoted
(`workflows/single-part-modeling/verifier-contract-patterns.md`); the stage passes only when it is recorded. A failure still reopens the owning artifact.

<!-- skill:if omp -->

### Host binding: persistent REPL for Detail Modeling Planner & Builder (omp)

Use `eval` (language `py`) for incremental construction hypotheses; names
survive across calls. Keep the real source run in bash. Never use a modeling
success message as the verification result: invoke the prepared verifier
function or script and record its output in the stage evidence.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop for Detail Modeling Planner & Builder (opencode)

opencode has no persistent REPL; run incremental construction hypotheses as
numbered scripts under the part directory (e.g.
`<part-dir>/hypotheses/s1_base_probe.py`) through `bash`. Names do not
survive between runs: carry intermediate geometry between probes by writing
it to a file (pickle, JSON, or `capture`) and reloading, or by
re-materializing from the part source. Keep the real source run in `bash`
too. Never use a modeling success message as the verification result:
invoke the prepared verifier script and record its output in the stage
evidence.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode -->

### Host binding: file-based hypothesis loop for Detail Modeling Planner & Builder (Claude Code / ZCode)

This host has no persistent REPL; run incremental construction hypotheses as
numbered scripts under the part directory (e.g.
`<part-dir>/hypotheses/s1_base_probe.py`) through the `Bash` tool. Names do
not survive between runs: carry intermediate geometry between probes by
writing it to a file (pickle, JSON, or a captured package) and reloading, or
by re-materializing from the part source. Keep the real source run in `Bash`
too. Never use a modeling success message as the verification result: invoke
the prepared verifier script and record its output in the stage evidence.

<!-- skill:endif -->

<!-- skill:if codex -->

### Host binding: file-based hypothesis loop for Detail Modeling Planner & Builder (codex)

codex has no persistent REPL; run incremental construction hypotheses as
numbered scripts under the part directory (e.g.
`<part-dir>/hypotheses/s1_base_probe.py`) through the shell tool. Names do
not survive between runs: carry intermediate geometry between probes by
writing it to a file (pickle, JSON, or a captured package) and reloading, or
by re-materializing from the part source. Keep the real source run in the
shell too. Never use a modeling success message as the verification result:
invoke the prepared verifier script and record its output in the stage
evidence.

<!-- skill:endif -->

<!-- skill:if dsh,kimicode -->

### Host binding: file-based hypothesis loop for Detail Modeling Planner & Builder (dsh / kimicode)

No persistent REPL is assumed for this host; run incremental construction
hypotheses as numbered scripts under the part directory (e.g.
`<part-dir>/hypotheses/s1_base_probe.py`) through the shell. Names do not
survive between runs: carry intermediate geometry between probes by writing
it to a file (pickle, JSON, or a captured package) and reloading, or by
re-materializing from the part source. Keep the real source run in the shell
too. Never use a modeling success message as the verification result: invoke
the prepared verifier script and record its output in the stage evidence.

<!-- skill:endif -->
