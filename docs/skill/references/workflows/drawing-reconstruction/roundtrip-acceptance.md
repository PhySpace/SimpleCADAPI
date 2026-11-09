# Drawing Reconstruction: Roundtrip Acceptance

Part of `workflows/drawing-reconstruction.md`. Load when the last stage closes and the model is drawn back into sheet B.

## Drawing-roundtrip acceptance

Owned by Role 3, executed after the last stage closes. This loop replaces
impression with evidence: the model must regenerate the sheet's content.

1. **Generate sheet B.** From the validated model, drive the engineering-
   drawing engine (`domains/engineering-drawing.md`) in batch: declare the
   view set from report A's view list (subset the engine supports), with
   dimensions covering the sheet-expressible ledger parameters. Read
   `report()`; declaration-level problems are re-declared, never
   action-patched. Export the DXF/PDF plus rendered PNGs.
   Build annotations from verified measurement records. Section evidence uses
   `build_section_annotation_rrecord`; native sheet dimensions require equivalent
   bindings to their model-measurement records. Copying A's nominal values is not
   a model measurement.
   Bind `DIM ID → feature/contours → section definition → measurement ID → model hash`.
   Independently bind `measurement_contract` from the ledger: dimension kind,
   direction, definition, line point, units and coordinate space. A contour ID
   shared by width and height cannot substitute for this contract.
   Before rendering, `validate_section_annotations_rreport` independently reruns
   geometry measurement and checks values, target IDs, section/configuration and
   current model hash. A model or section change invalidates the old evidence
   (conservative invalidation of all model evidence is acceptable). Preserve
   unrounded measured values for acceptance; configure displayed decimals from
   the tolerance band. Reject a display step wider than the band, rounding error
   greater than half its width, or a displayed number outside it. Keep
   `measured=999`, wrong-axis, wrong-definition, coarse-display and stale-model cases as
   required negative tests. Raw rendering remains permitted but cannot pass this gate.
2. **Generate section evidence.** For every section view in report A's view
   list, cut the model at the recorded plane (`measure_model_section_rdimensions`),
   verify the ledger-matching dimension candidates and their accuracy, and render the annotated
   section (`render_model_section_rpath`). The annotated values are model
   measurements only when their source binding passes independent validation.
   Declare section_strategy explicitly (auto/material/edges) and archive the
   method actually used. Formal section evidence requires the section_checks
   contract: independently resolved origin, normal and local axes, expected solid,
   material-face and hole counts, representative material/void points, point
   tolerance and its basis. Check model validity/closure, section closure, valid
   material faces and topological outer/inner wires. Classify each point against
   the original solid, material-face intersection and displayed polygons. Cover
   every material face and every hole; boundary/uncertain points remain pending.
   An image containing open or incomplete contours is diagnostic output only.
   First verify the section definition, intersection and display. Modify the
   model only when independent solid checks establish a geometry error supported
   by the drawing; a rendering failure never establishes that by itself.
   Record **layout readability** (legibility, clipping, overlap) separately from
   **feature association** (anchor, target geometry, leader path, text box).
   Automatic placeholder anchors are not association evidence. Tables require
   feature numbers plus view/detail references that permit checking the mapping.
   Archive local axes, final rotation/scale, canvas and pixel transforms, text
   boxes and leader paths; test interior-point forward/inverse transforms.
   Visual review records must retain the DIM/measurement/model/section IDs and
   SHA-256 of the actual reviewed PNG and sidecar. The acceptance script compares
   these with current files and annotation content; it must never overwrite a
   review's old IDs. Changes to anchors, displayed precision, render layout or
   either artifact require review of the new artifact even if model IDs agree.
   Compare each render against the drawing's own
   viewport crop (both are yours) and emit per-DIM verdicts
   (`consistent` / `different` / `unreviewable` + reasons); hand both images
   to the isolated reviewer when visual arbitration is required.

**Unattended:** the isolated reviewer is the fresh-context check described in the standing discipline of
`workflows/drawing-reconstruction.md`; per-DIM verdicts quote what was observed in both images, and the report lists
the arbitration as not independent.
3. **Parse report B blind.** Re-run Role 1's SOP (steps 0–7) on sheet B and
   write `drawing_work/report_B.md` in the same skeleton — without reading
   report A's values. B carries its own `DIM-xxx` ids for its own sheet.
   Blind reading tests communication. It never substitutes for model geometry
   measurement; A/B numerical agreement must still have a model-derived source.
4. **Diff.** Join verdicts to A's ledger parameters (geometry identity,
   not id text): sheet-expressible parameters join against report B's
   entries, section-expressible parameters against the section-evidence
   verdicts. Verdict per parameter: `consistent` (within the original
   tolerance band; unspecified tolerances per the sheet's default
   standard), `different`, or `not-expressible`. The diff table (parameter,
   A value, B value, verdict, channel) is a deliverable.
5. **Not-expressible fallback.** Parameters neither channel can carry
   (hatch-level geometry, features invisible in every resolved view)
   are verified by direct QL measurement of the model against the ledger —
   same tolerance criterion, different evidence channel, recorded in the
   coverage table.
6. **Triage every `different`.** Re-open the original drawing evidence
   (re-render the provenance viewport) before deciding:
   - **Sheet-generation artifact** — `report()` warnings, engine
     limitations, projection placement faults: fix the declaration,
     regenerate B, re-diff. The model is never touched for this.
   - **Section-plane artifact** — the cut plane was resolved wrong (R1–R4
     misapplied): correct the plane spec in report A's view list, re-render
     the section evidence, re-diff. The model is never touched for this.
   - **Parse error in report A** — the original evidence contradicts the
     ledger entry: correct `report_A.md` (tier marks intact), re-derive the
     affected hypotheses and stages, and re-model through the owning stages.
   - **Model error** — the evidence supports the ledger and the model
     measures otherwise: repair the owning source parameter (FTC block),
     re-run the stage verifier, then regenerate B.
7. **Convergence.** Two full rounds without convergence → ⛔ stop and ask
   the user with the diff table and the triage evidence. Blind parsing,
   section evidence, and delegated visual review apply to every round — no
   shortcuts on retries.

**Unattended:** no ask. After two non-converging rounds stop the repair loop and keep the diff table and the triage
evidence. Every non-converged DIM stays `different` or `pending` in `report.md`, with no pass claim, and no band is
relaxed to converge. Role 5 does not run as an accepted delivery: the part source, the reports and the diff table are
the deliverable. Blind parsing, section evidence and the fresh-context review still apply to every round.

Pass: each DIM separately passes (1) original interpretation — value, tolerance,
association and coordinate evidence; (2) model measurement — actual geometry and
adequate accuracy; (3) output expression — the matching measurement supplied the
number and the feature association is correct. The isolated reviewer also passes
layout readability and feature association separately for sheet B and section
pairs. `assess_dimension_rverdict` records the three gates. Coverage must enumerate
value verification, association verification and layout review independently;
missing evidence cannot be hidden in a combined pass count. A fallback measurement
can satisfy geometry, but cannot certify an absent or incorrect output expression.
