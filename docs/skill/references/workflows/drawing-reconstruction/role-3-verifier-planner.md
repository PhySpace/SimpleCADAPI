# Drawing Reconstruction: Role 3, Verifier Planner

Part of `workflows/drawing-reconstruction.md`. Load when Role 3 starts (before every stage's modeling work).

## Role 3 — Verifier Planner

Runs before every stage's modeling work and owns the roundtrip contract.
This is "tests before implementation" applied to sheet evidence.

For the current `S` stage, in order:

1. **Stage output**: name the substructure, its datum relationship, and the
   `DIM-xxx` subset it must satisfy; state what is deliberately out of
   scope.
2. **Acceptance criteria** from the ledger subset: dimensions with their
   tolerance bands, required topology (face/hole/axis counts), interfaces
   with already-built geometry, BREP validity and single-solid expectations,
   visual criteria where a view must confirm attachment.
   Apply the scope restriction in `workflows/drawing-reconstruction.md` when planning the verifier: no center-of-mass,
   mass, inertia, or high-precision volume-equivalence checks without a separate
   user requirement. Record the requirement/validity condition and threshold
   basis for each blocking assertion; do not introduce gates during debugging.
   For every DIM write a measurement contract before modeling: feature/geometry
   selection, datum, direction, section origin/normal/basis, algorithm, sampling
   configuration, accuracy class, error-bound evidence and tolerance basis.
   Verify true circle geometry for diameters; use continuous extrema for envelopes.
   Define wall thickness as minimum boundary gap, radial thickness, or material
   length along a specified line before selecting the algorithm. A fitted circle
   is only a candidate; sampled nesting is only a pair-selection candidate.
   Neither fit residual, intersection `tolerance`, nor additional sampling alone
   establishes the total error bound. Record convergence checks as such.
   An approximate value with reliable bound e passes only when [value-e,value+e]
   is wholly inside the tolerance band. Boundary overlap or unknown error is
   `pending`; refine the algorithm or obtain a supported uncertainty assessment.
   Cite any default tolerance actually specified by the sheet; otherwise record
   missing tolerance basis and keep conformance pending, never invent a standard.
   Unreliable fits or measurements stay pending. They cannot justify changing
   CAD dimensions. For circle candidates record residuals, angular coverage,
   conditioning, closure and actual edge types; a local arc, gapped contour or
   nearly collinear sample set cannot establish a full circular feature.
3. **Deterministic checks**: iterate hypothesis snippets in the execution
   environment; good and bad probes must show each check separates pass
   from fail. QL-only topology enumeration (plural getters take an index or
   are driven through `ql.<kind>().resolve`). Reject checks that merely
   print a plausible number.
4. **Executable verification script** with explicit assertions and named
   measurements; append `Verifier contract: <output> / Criteria: <...> /
   Script: <path>` to `BUILD_PLAN.md` with hypothesis evidence and known-bad
   proof. Complete the stage's `plan verifier` TODO; only then may `model`
   start. After Role 4 finishes, run the exact prepared script; only its
   passing output closes the stage.
5. **Roundtrip contract** (written once, before S1): the coverage table
   mapping every ledger `DIM-xxx` to its verification channel — a generated
   sheet dimension where the drawing engine can express it, a
   **section-evidence render** where the drawing's section views express it
   (cut plane from the view list, measured dimensions from
   `measure_model_section_rdimensions`, annotated render via
   `render_model_section_rpath`, compared against the drawing's viewport by
   you), or direct QL model measurement otherwise;
   for each section view, a section-evidence task (plane spec, expected
   DIM-id set, provenance viewport); the sheet declaration plan derived
   from report A's view list; the pass criterion (every parameter within its
   original tolerance band with sufficient accuracy; defaults only when the sheet
   explicitly supplies a standard/class).

Role 3 may prepare visual verification (named views, regions, verdict
fields for the isolated reviewer) but never certifies its own renders.

**Unattended:** the isolated reviewer is replaced by a fresh-context check of your own against the written criteria
(a subagent if the host offers one); Role 3 still never certifies renders in the context that generated them, so the
check reads only the artifacts and the criteria. The verdict is quoted and listed as not independent in the report.

<!-- skill:if omp -->

### Host binding: persistent REPL and TODO state machine (omp)

Use the persistent `eval` tool (language `py`) for hypothesis snippets,
known-bad probes, and the verification scripts; keep cells incremental.
Never treat a modeling success message as verification: invoke the prepared
verifier and record its output. Drive the stage gates through `todo`
exactly as declared in Role 2; close `plan verifier` only when contract,
executable check, hypothesis evidence, and known-bad proof exist; after
Role 4's run, start and complete `run verifier` on the script's real output.
On failure do not rewrite the criterion to clear the list — open
`repair: <stage> <owner>` for the verifier or the model and repeat the loop.

<!-- skill:endif -->

<!-- skill:if opencode -->

### Host binding: file-based hypothesis loop (opencode)

No persistent REPL: every Python run is a fresh process. Keep hypothesis
snippets, known-bad probes, and final checks as numbered files under
`<part-dir>/verify/` (`s1_hypothesis.py`, `s1_known_bad.py`, `s1_verify.py`),
run them via `bash`, and persist intermediate state to files (JSON,
pickle, or captured packages) between runs. The script file is the
evidence. Gate the stages through `todowrite` with the exact task strings;
`todowrite`'s echoed list is the re-grounding source after any interruption.

<!-- skill:endif -->

<!-- skill:if zcode,claudecode,codex,dsh,kimicode -->

### Host binding: file-based verification

No persistent REPL is assumed. Write hypotheses, known-bad probes and final
checks under `<part-dir>/verify/`, and execute them through the available shell
or execution tool. Retain scripts and JSON results so the stage can resume from
files. Update the plan/checklist from actual outputs; a failed check reopens its
owning artifact and cannot be cleared by weakening the criterion.

<!-- skill:endif -->
